"""Bounded GP retries with original optimizer evidence and unchanged observations."""
from contextlib import contextmanager
from functools import lru_cache
from importlib.metadata import version
import json
import logging
import math
import traceback
import warnings

import torch
from botorch.exceptions.errors import ModelFittingError
from botorch.fit import fit_gpytorch_mll
from botorch.logging import logger
from botorch.optim.core import OptimizationStatus
from botorch.optim.fit import fit_gpytorch_mll_scipy
from gpytorch.mlls import ExactMarginalLogLikelihood
from linear_operator.utils.errors import NanError, NotPSDError

from experiment_planner.domain.errors import ModelTrainingError


@lru_cache(maxsize=1)
def dependency_versions():
    return {name: version(name) for name in ("botorch", "gpytorch", "torch", "scipy")}


def tensor_summary(values):
    values = values.detach().reshape(-1)
    finite = values[torch.isfinite(values)]
    return {
        "count": values.numel(), "nonfinite_count": values.numel() - finite.numel(),
        "min": finite.min().item() if finite.numel() else None,
        "max": finite.max().item() if finite.numel() else None,
    }


def warning_detail(w):
    return f"{w.category.__name__}: {w.message}\n  {w.filename}:{w.lineno}"


def training_context(response, preset, seed, encoder, active, records, ids, X, y, residual, variance):
    """Summaries only: no complete project, record notes, or measurement payloads."""
    inputs = []
    for field in encoder.fields:
        columns = [i for i in encoder.indices[field["name"]] if i in active]
        if not columns:
            continue
        values = [r[0][field["name"]] for r in records]
        item = {"name": field["name"], "label": field.get("label", field["name"]),
                "unique_count": len(set(values)), "encoded": tensor_summary(X[:, columns])}
        if field.get("value_type", "float") in ("float", "int"):
            finite = [v for v in values if math.isfinite(v)]
            item.update(observed_min=min(finite) if finite else None, observed_max=max(finite) if finite else None)
            if "bounds" in field:
                lo, hi = field["bounds"]
                item.update(allowed_bounds=[lo, hi],
                            outside_experiment_ids=[eid for eid, v in zip(ids, values) if v < lo or v > hi],
                            boundary_count=sum(v == lo or v == hi for v in values))
        inputs.append(item)
    groups = {}
    for i, row in enumerate(X[:, active].tolist()):
        groups.setdefault(tuple(row), []).append(i)
    duplicates = []
    for indices in groups.values():
        if len(indices) > 1:
            duplicates.append({"experiment_ids": [ids[i] for i in indices],
                               "response": tensor_summary(y[indices])})
    return {
        "response": response["name"], "label": response.get("label", response["name"]),
        "unit": response.get("unit", "1"), "model": preset, "seed": seed,
        "sample_count": len(records), "experiment_ids": ids,
        "encoded_dimensions": len(active), "unique_model_conditions": len(groups),
        "inputs": inputs, "response_values": tensor_summary(y),
        "residual_after_fixed_trend": tensor_summary(residual),
        "noise_mode": "fixed_observation_variance" if variance is not None else "learned_common_noise",
        "observation_variance_original_units": tensor_summary(variance) if variance is not None else None,
        "duplicate_condition_groups": duplicates[:20], "duplicate_group_count": len(duplicates),
        "dependency_versions": dependency_versions(),
    }


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(f"{record.levelname}: {record.getMessage()}")


@contextmanager
def capture_fit_messages():
    # Fits run in the dedicated calculation process. Restore the library logger
    # for callers using the synchronous CLI as well; do not change root logging.
    handler = _LogCapture()
    previous = logger.level, logger.handlers[:], logger.propagate, logger.disabled
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.disabled = False
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            yield captured, handler.messages
    finally:
        level, handlers, propagate, disabled = previous
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate
        logger.disabled = disabled
        handler.close()


def _advice(context, attempts):
    messages = json.dumps(attempts, ensure_ascii=False).lower()
    advice = []
    if any(word in messages for word in ("notpsd", "positive definite", "cholesky", "jitter")):
        advice.append("日志涉及协方差矩阵数值稳定性；检查重复/相近条件及测量误差是否过小。")
    if any(word in messages for word in ("abnormal", "line search", "linesearch")):
        advice.append("日志涉及优化器线搜索终止；检查数据尺度、极端先验及噪声设置。")
    if context["duplicate_group_count"]:
        advice.append("存在模型输入相同的记录，详见重复组；真实复测可保留，误差应反映实际散布。")
    if any(p.get("outside_experiment_ids") for p in context["inputs"]):
        advice.append("部分历史输入超出当前模板范围，详见字段和实验编号；训练没有裁剪这些记录。")
    if any(p["unique_count"] == 1 for p in context["inputs"]):
        advice.append("有输入在训练数据中不变化，无法从本批数据识别其影响。")
    if not advice:
        advice.append("结合各次原始停止消息核对响应数据、测量误差和先验；当前信息不足以认定单一根因。")
    return advice


def _failure(context, attempts, cause):
    label = f"{context['label']}（{context['response']}）"
    stage = f"{len(attempts)} 次拟合尝试后" if attempts else "训练数据检查时"
    message = f"{label}：GP 在{stage}失败。请点击“查看原始诊断”查看具体原因和实验编号。"
    reason = str(cause)
    if attempts:
        last = attempts[-1]
        original = last.get("optimizer_exception") or last.get("optimizer_result") or {}
        reason = original.get("message") or reason
    sections = ["GP 训练诊断", f"直接失败原因：\n{type(cause).__name__}: {cause}",
                "最后一次原始停止消息：\n" + reason,
                "排查提示（不是已确认根因）：\n- " + "\n- ".join(_advice(context, attempts)),
                "训练上下文（原单位；编码范围另列）：\n"
                + json.dumps(context, ensure_ascii=False, indent=2, allow_nan=False)]
    for attempt in attempts:
        metadata = {k: v for k, v in attempt.items()
                    if k not in ("traceback", "warnings", "botorch_logs", "optimizer_exception")}
        sections.extend([f"第 {attempt['attempt']} 次拟合：",
                         json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False),
                         "原始警告：\n" + ("\n".join(attempt["warnings"]) or "未产生警告"),
                         "BoTorch 日志：\n" + ("\n".join(attempt["botorch_logs"]) or "未取得额外日志")])
        if "optimizer_exception" in attempt:
            sections.append("优化器原始异常：\n" + attempt["optimizer_exception"]["traceback"])
        if "traceback" in attempt:
            sections.append("本次拟合异常堆栈：\n" + attempt["traceback"])
    details = "\n\n".join(sections)
    raise ModelTrainingError(message, details) from cause


def fit_gp(factory, X, y, variance, context):
    """Try the existing fit first, then two distinct, data-scaled initializations.

    Fixed observation noise, kernel family and raw data are identical in all
    attempts. Library jitter stays at its normal setting. Recovery is reported.
    """
    attempts, all_warnings = [], []
    for label, values in (("编码输入", X), ("扣除固定先验后的响应", y), ("观测方差", variance)):
        if values is None:
            continue
        invalid = ~torch.isfinite(values)
        if label == "观测方差":
            invalid |= values < 0
        if invalid.any():
            rows = sorted(set(invalid.nonzero()[:, 0].tolist()))
            ids = [context["experiment_ids"][i] for i in rows]
            cause = ValueError(f"{label}含非有限值或无效方差；实验编号：{ids}")
            _failure(context, attempts, cause)

    plans = [(100, 20, None), (300, 50, .5), (300, 100, 2.)]
    retryable = (ModelFittingError, NotPSDError, NanError, torch.linalg.LinAlgError)
    for number, (maxiter, maxls, scale) in enumerate(plans, 1):
        attempt = {"attempt": number, "optimizer": "L-BFGS-B", "maxiter": maxiter,
                   "maxls": maxls, "initialization": "library_default" if scale is None else "data_scaled",
                   "lengthscale_spread_multiplier": scale}
        attempts.append(attempt)
        error = None
        optimizer_messages = []
        with capture_fit_messages() as (captured, logs):
            try:
                # Fresh model resets both trainable parameters and prediction caches.
                inner = factory()
                if scale is not None:
                    spread = X.std(dim=0, unbiased=False).clamp(.1, 2.5)
                    inner.covar_module.base_kernel.lengthscale = (spread * scale).clamp(.05, 5.)
                    inner.covar_module.outputscale = 1.
                    inner.mean_module.constant = 0.
                attempt["initial_lengthscale"] = inner.covar_module.base_kernel.lengthscale.detach().reshape(-1).tolist()

                def optimizer(mll, **kwargs):
                    # BoTorch's inner warning recorder can discard warnings when
                    # an optimizer raises (notably NotPSDError). Retain evidence
                    # at this boundary before its retry policy handles the error.
                    optimizer_warnings = []
                    try:
                        with warnings.catch_warnings(record=True) as optimizer_warnings:
                            warnings.simplefilter("always")
                            result = fit_gpytorch_mll_scipy(mll, **kwargs)
                    except Exception as exc:
                        attempt["optimizer_exception"] = {
                            "type": type(exc).__name__, "message": str(exc),
                            "traceback": traceback.format_exc(),
                        }
                        raise
                    finally:
                        optimizer_messages.extend(optimizer_warnings)
                        for w in optimizer_warnings:
                            warnings.warn_explicit(str(w.message), w.category, w.filename, w.lineno)
                    attempt["optimizer_result"] = {
                        "status": result.status.name, "message": str(result.message or ""),
                        "iterations": result.step,
                        "objective": float(result.fval) if math.isfinite(result.fval) else None,
                    }
                    if not math.isfinite(result.fval):
                        raise ModelFittingError("优化目标出现 NaN 或 Inf，不能接受此次拟合。")
                    if result.status not in (OptimizationStatus.SUCCESS, OptimizationStatus.STOPPED):
                        raise ModelFittingError(f"优化器停止状态 {result.status.name}: {result.message}")
                    return result

                fit_gpytorch_mll(ExactMarginalLogLikelihood(inner.likelihood, inner),
                                optimizer=optimizer, max_attempts=1,
                                optimizer_kwargs={"options": {"maxiter": maxiter, "maxls": maxls}})
                if any(not torch.isfinite(p).all() for p in inner.parameters()):
                    raise ModelFittingError("拟合参数出现 NaN 或 Inf。")
                with torch.no_grad():
                    posterior = inner.posterior(X)
                    if not torch.isfinite(posterior.mean).all() or not torch.isfinite(posterior.variance).all():
                        raise ModelFittingError("训练点后验出现 NaN 或 Inf，不能返回预测。")
                attempt["outcome"] = "accepted"
                attempt["posterior_check"] = "finite_at_training_points"
            except Exception as exc:
                error = exc
                attempt.update(outcome="failed", exception_type=type(exc).__name__,
                               exception=str(exc), traceback=traceback.format_exc())
        attempt["warnings"] = list(dict.fromkeys(warning_detail(w) for w in [*captured, *optimizer_messages]))
        attempt["botorch_logs"] = logs
        all_warnings.extend([*captured, *optimizer_messages])
        if error is None:
            # Preserve warnings in the existing worker notices / diagnostics too.
            seen = set()
            for w in all_warnings:
                key = warning_detail(w)
                if key not in seen:
                    warnings.warn_explicit(str(w.message), w.category, w.filename, w.lineno)
                    seen.add(key)
            return inner, {"context": context, "attempts": attempts, "recovered": number > 1}
        if not isinstance(error, retryable) or number == len(plans):
            _failure(context, attempts, error)
