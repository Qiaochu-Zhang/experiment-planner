"""BoTorch-compatible probability models, with joint candidate covariance."""
import torch
from torch import nn
from botorch.models.model import Model, ModelList
from botorch.models import SingleTaskGP
from botorch.posteriors.gpytorch import GPyTorchPosterior
from botorch.posteriors.transformed import TransformedPosterior
from gpytorch.distributions import MultivariateNormal
from gpytorch.kernels import RBFKernel, MaternKernel, ScaleKernel

from experiment_planner.domain.errors import CapabilityError, ValidationError
from experiment_planner.knowledge.priors import check_capabilities
from experiment_planner.engine.gp_fitting import fit_gp, training_context
from experiment_planner.domain.reliability import data_weights
from experiment_planner.engine.reliability import weighted_gaussian_likelihood

DTYPE = torch.double


class Encoder:
    def __init__(self, template):
        self.fields = [p for p in template.parameters if p.get("value_type") != "text" and p.get("use_as_model_input", True)]
        self.indices = {}
        width = 0
        for p in self.fields:
            size = len(p.get("values", [p.get("fixed_value")])) if p.get("value_type") == "category" else 1
            self.indices[p["name"]] = list(range(width, width + size))
            width += size
        self.width = width

    def encode(self, conditions):
        rows = []
        for condition in conditions:
            row = []
            for p in self.fields:
                value = condition[p["name"]]
                if p.get("value_type") == "category": row.extend(float(value == v) for v in p.get("values", [p.get("fixed_value")]))
                elif p.get("value_type") == "bool": row.append(float(value))
                else:
                    bounds = p.get("bounds", [min(p["values"]), max(p["values"])]) if "values" in p else p.get("bounds", [0, 1])
                    row.append((value - bounds[0]) / (bounds[1] - bounds[0]) if bounds[1] != bounds[0] else 0.0)
            rows.append(row)
        return torch.tensor(rows, dtype=DTYPE).reshape(len(rows), self.width)


class BayesianLinear(Model):
    def __init__(self, X, y, variance, prior_mean=None, prior_precision=None):
        super().__init__()
        phi = torch.cat([torch.ones_like(X[..., :1]), X], -1)
        mean = torch.zeros(phi.shape[-1], dtype=DTYPE) if prior_mean is None else prior_mean
        precision = torch.eye(phi.shape[-1], dtype=DTYPE) if prior_precision is None else prior_precision
        precision[0, 0] = max(precision[0, 0].item(), 1e-6)
        weights = variance.reshape(-1).clamp_min(1e-8).reciprocal()
        post_precision = precision + phi.T @ (weights[:, None] * phi)
        cov = torch.linalg.inv(post_precision)
        mu = cov @ (precision @ mean + phi.T @ (weights * y.reshape(-1)))
        self.register_buffer("coefficient_mean", mu)
        self.register_buffer("coefficient_covariance", cov)

    @property
    def num_outputs(self): return 1
    @property
    def batch_shape(self): return torch.Size()

    def posterior(self, X, output_indices=None, observation_noise=False, posterior_transform=None):
        if observation_noise is not False: raise CapabilityError("未来量测区间需要单独的未来噪声设置")
        phi = torch.cat([torch.ones_like(X[..., :1]), X], -1)
        mean = phi @ self.coefficient_mean
        cov = phi @ self.coefficient_covariance @ phi.transpose(-1, -2)
        cov = cov + torch.eye(X.shape[-2], dtype=X.dtype, device=X.device) * 1e-9
        posterior = GPyTorchPosterior(MultivariateNormal(mean, cov))
        return posterior_transform(posterior) if posterior_transform else posterior


class BernoulliLogit(BayesianLinear):
    def __init__(self, X, y, weights=None):
        Model.__init__(self)
        phi = torch.cat([torch.ones_like(X[..., :1]), X], -1)
        beta = torch.zeros(phi.shape[-1], dtype=DTYPE, requires_grad=True)
        optimizer = torch.optim.LBFGS([beta], max_iter=70, line_search_fn="strong_wolfe")
        def loss_at(b):
            losses = torch.nn.functional.binary_cross_entropy_with_logits(phi @ b, y.reshape(-1), reduction="none")
            return (losses if weights is None else losses * weights.reshape(-1)).sum() + b.square().sum() / 2
        def closure():
            optimizer.zero_grad()
            loss = loss_at(beta)
            loss.backward()
            return loss
        optimizer.step(closure)
        covariance = torch.linalg.inv(torch.autograd.functional.hessian(loss_at, beta))
        self.register_buffer("coefficient_mean", beta.detach())
        self.register_buffer("coefficient_covariance", covariance.detach())

    def posterior(self, X, **kwargs):
        latent = super().posterior(X, **kwargs)
        return TransformedPosterior(latent, sample_transform=torch.sigmoid)


class ProjectedModel(Model):
    """Remove features per response, add a documented soft linear trend."""
    def __init__(self, inner, indices, trend):
        super().__init__()
        self.inner = inner
        self.indices = indices
        self.register_buffer("trend", trend)

    @property
    def num_outputs(self): return 1
    @property
    def batch_shape(self): return torch.Size()

    def posterior(self, X, output_indices=None, observation_noise=False, posterior_transform=None):
        reduced = X[..., self.indices] if self.indices else torch.zeros_like(X[..., :1])
        posterior = self.inner.posterior(reduced, observation_noise=observation_noise)
        if isinstance(self.inner, BernoulliLogit): return posterior
        mean = posterior.distribution.mean + self.trend[0] + X @ self.trend[1:]
        result = GPyTorchPosterior(MultivariateNormal(mean, posterior.distribution.lazy_covariance_matrix))
        return posterior_transform(result) if posterior_transform else result


def fit_models(template, experiments, preset, seed=0, *, response_names=None):
    check_capabilities(template, preset)
    responses = [r for r in template.responses if response_names is None or r["name"] in response_names]
    if not responses: raise CapabilityError("没有可拟合的基础响应")
    source_usage={}
    def raw_dependencies(name):
        if name not in template.graph.formulas:return {name}
        return set().union(*(raw_dependencies(dep) for dep in template.graph.formulas[name].dependencies))
    for response in responses:
        for experiment in experiments:
            if experiment["status"] not in ("completed","partial"):continue
            for name in raw_dependencies(response["name"]):
                source=(experiment["observations"].get(name,{}).get("uncertainty") or {}).get("source")
                if source:source_usage.setdefault(source,set()).add((experiment["id"],response["name"]))
    if any(len(uses)>1 for uses in source_usage.values()):
        raise CapabilityError("共享误差来源跨实验或跨响应：当前独立似然未适配，不能静默忽略相关性")
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    encoder = Encoder(template)
    models, names, notices, datasets = [], [], [], {}
    for response in responses:
        name = response["name"]
        boolean = response.get("value_type") == "bool"
        records, record_ids, source_records = [], [], []
        fitting = None
        for row_number, e in enumerate(experiments, 1):
            if e["status"] not in ("completed", "partial"): continue
            cell = e["derived"].get(name) if name in e["derived"] else e["observations"].get(name)
            if cell is None or cell.get("value") is None or cell.get("status", "valid") != "valid": continue
            u = cell.get("uncertainty") or {}
            standard = u.get("standard")
            if "kind" in u:
                from experiment_planner.metrics.uncertainty import Uncertainty
                standard = Uncertainty(**u).standard()
            records.append((e["actual"], float(cell["value"]), standard))
            record_ids.append(e.get("id", f"输入第 {row_number} 行（无实验编号）"))
            source_records.append(e)
        if len(records) < 2:
            raise CapabilityError(f"{name}：有效数据不足两条，预测尚不可用")
        X = encoder.encode([r[0] for r in records])
        y = torch.tensor([r[1] for r in records], dtype=DTYPE).unsqueeze(-1)
        known = [r[2] is not None for r in records]
        if any(known) and not all(known):
            known_ids = [str(eid) for eid, has_error in zip(record_ids, known) if has_error]
            unknown_ids = [str(eid) for eid, has_error in zip(record_ids, known) if not has_error]
            raise CapabilityError(
                f"{name}：混合已知/未知观测噪声尚未适配，不能把未知误差当作零。\n"
                f"误差已知的实验：{'、'.join(known_ids)}；误差未知的实验：{'、'.join(unknown_ids)}。\n"
                "可在“实验记录 → 统一设置误差”中按量测依据或明确假设补齐未知误差；"
                "派生响应需补齐相关原始测量的误差。")
        variance = torch.tensor([r[2] for r in records], dtype=DTYPE).unsqueeze(-1).square() if all(known) else None
        raw_weights, weighting = data_weights(template, source_records)
        weights = torch.tensor(raw_weights, dtype=DTYPE).unsqueeze(-1)
        weighted = any(w != 1. for w in raw_weights)
        if weighted:
            notices.append(f"{response.get('label', name)}：已应用批次可信度 / 近期权重（{min(raw_weights):.5g}–{max(raw_weights):.5g}）；相对建模权重不代表准确率。")
        if any(d["legacy_time"] for d in weighting["records"]):
            notices.append(f"{name}：旧记录以原保存时间近似实验日期；可在批次设置或 Excel 中补正实际日期。")
        if any(d["unknown_time"] for d in weighting["records"]):
            notices.append(f"{name}：部分实验日期未知，未对这些记录施加时间衰减；请补充实际日期。")
        if any(d["weight_floor_applied"] for d in weighting["records"]):
            notices.append(f"{name}：极低权重已按数值下限 1e-6 处理，详见技术详情。")
        if weighted and variance is not None:
            variance = variance.clamp_min(1e-8) / weights
        priors = [p for p in template.data.get("knowledge_priors", []) if p.get("enabled", True) and p["response"] == name]
        excluded = {i for p in priors if p["relation"] == "independent" for i in encoder.indices.get(p["input"], [])}
        active = [i for i in range(encoder.width) if i not in excluded]
        reduced = X[..., active] if active else torch.zeros_like(X[..., :1])
        trend = torch.zeros(encoder.width + 1, dtype=DTYPE)
        prior_mean = torch.zeros(reduced.shape[-1] + 1, dtype=DTYPE)
        prior_precision = torch.eye(reduced.shape[-1] + 1, dtype=DTYPE) * .01
        prior_precision[0, 0] = 1e-6
        for p in priors:
            if p["relation"] == "independent": continue
            field = next(f for f in encoder.fields if f["name"] == p["input"])
            lo, hi = field.get("bounds", [0, 1])
            index = encoder.indices[p["input"]][0]
            if index not in active: raise ValidationError("无关先验与系数先验冲突")
            coefficient = p.get("coefficient", 0)
            scaled = coefficient * (hi - lo)
            if preset == "bayesian_linear_v1":
                prior_mean[active.index(index)+1] = scaled
                prior_precision[active.index(index)+1, active.index(index)+1] = p["strength"]
                if p["relation"] == "proportional":
                    prior_mean[0] += coefficient * lo
                    prior_precision[0, 0] = p["strength"]
            else:
                # A fixed signed mean trend plus a GP residual is explicitly soft.
                trend[index+1] += scaled * p["strength"] / (1 + p["strength"])
                trend[0] += coefficient * lo * p["strength"] / (1 + p["strength"])
        if boolean:
            inner = BernoulliLogit(reduced, y, weights if weighted else None)
            notices.append(f"{name}: Bernoulli-logit / Laplace；概率是参数后验采样统计")
        elif preset == "bayesian_linear_v1":
            if variance is None:
                # Explicit empirical residual estimate; never claim measurement error=0.
                phi = torch.cat([torch.ones_like(reduced[:, :1]), reduced], -1)
                # Fixed inputs and few records often make the design rank deficient.
                # SVD handles that design and supplies the effective residual degrees.
                least_squares = torch.linalg.lstsq(phi, y, driver="gelsd")
                beta = least_squares.solution
                rank = int(least_squares.rank.item())
                mse = (y - phi @ beta).square().sum() / max(1, len(y)-rank)
                noise = max(mse.item(), y.var().item() * .01, 1e-6)
                variance = torch.full_like(y, noise) / weights if weighted else torch.full_like(y, noise)
                notices.append(f"{name}: 未提供误差；经验残差方差={noise:.8g}，少数据时有局限")
            inner = BayesianLinear(reduced, y, variance, prior_mean, prior_precision)
        else:
            kernel_cls = RBFKernel if preset == "gp_rbf_v1" else MaternKernel
            residual = y - (trend[0] + X @ trend[1:]).unsqueeze(-1)
            context = training_context(response, preset, seed, encoder, active, records,
                                       record_ids, X, y, residual, variance)
            context["enabled_priors"] = [{k: p[k] for k in ("input", "relation", "coefficient", "strength") if k in p} for p in priors]
            context["data_weighting"] = weighting

            def factory():
                kernel = kernel_cls(ard_num_dims=reduced.shape[-1], **({"nu": 2.5} if kernel_cls is MaternKernel else {}))
                likelihood = weighted_gaussian_likelihood(weights) if weighted and variance is None else None
                return SingleTaskGP(reduced, residual, train_Yvar=variance, likelihood=likelihood, covar_module=ScaleKernel(kernel))

            inner, fitting = fit_gp(factory, reduced, residual, variance, context)
            notices.append(f"{name}: {'已提供观测方差 u²' if variance is not None else 'GP 估计未知噪声'}")
            if fitting["recovered"]:
                notices.append(f"{response.get('label', name)}：调整核参数初值和线搜索后，第 {len(fitting['attempts'])} 次 GP 拟合恢复；原始记录和测量误差未改变，过程见技术详情。")
            if fitting["attempts"][-1].get("optimizer_result", {}).get("status") == "STOPPED":
                notices.append(f"{response.get('label', name)}：优化达到停止条件，训练点后验有限；请查看技术详情中的停止原因，这不保证已充分收敛。")
            if any(p.get("outside_experiment_ids") for p in context["inputs"]):
                notices.append(f"{name}：部分历史输入超出当前模板范围，训练保留原值；请核对技术详情中的字段及实验编号。")
        models.append(ProjectedModel(inner, active, trend))
        names.append(name)
        feature_ranges = {}
        for field in encoder.fields:
            if not any(i in active for i in encoder.indices[field["name"]]): continue
            observed = [r[0][field["name"]] for r in records]
            unique = len(set(observed))
            feature_ranges[field["name"]] = {"unique_count": unique}
            if field.get("value_type", "float") in ("float", "int"):
                feature_ranges[field["name"]].update(min=min(observed), max=max(observed))
            if unique == 1:
                notices.append(f"{response.get('label', name)}：有效训练记录中的 {field.get('label', field['name'])} 只有一个取值；无法从这些数据识别其影响，平坦预测不代表物理无关")
        datasets[name] = {"count": len(records), "features": [p["name"] for p in encoder.fields if any(i in active for i in encoder.indices[p["name"]])], "feature_ranges": feature_ranges, "conditions": [r[0] for r in records]}
        datasets[name]["experiment_ids"] = record_ids
        datasets[name]["data_weighting"] = weighting
        if fitting is not None:
            datasets[name]["gp_training"] = fitting

    return ModelList(*models), encoder, names, datasets, ["各基础响应条件独立；同一响应保留候选点间相关性", "区间表示潜在响应，不包含未提供的未来测量误差", *notices]
