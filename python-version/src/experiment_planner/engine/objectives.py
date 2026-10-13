import ast
import math
import torch
from botorch.acquisition.multi_objective.objective import GenericMCMultiOutputObjective
from botorch.acquisition.objective import GenericMCObjective

from experiment_planner.domain.errors import CapabilityError, ValidationError
from experiment_planner.metrics.ratio import ratio_definition, stable_ratio_tensor, canonical_value


class Objectives:
    def __init__(self, template, response_names):
        self.template = template
        self.names = response_names
        self.policy = template.data.get("ratio_policy", {"mode": "remove"})
        self.ratio = ratio_definition(template)
        original = self.policy.get("original_metric")
        self.objectives = [o for o in template.data["objectives"] if not (o["metric"] == original and self.policy["mode"] == "remove")]
        if not self.objectives: raise ValidationError("没有参与优化的目标")

    def values(self, samples, *, optimization=False):
        values = {name: samples[..., i] for i, name in enumerate(self.names)}
        def visit(node):
            if isinstance(node, ast.Name):
                if node.id not in values: raise CapabilityError(f"预测公式缺少已知基础响应：{node.id}")
                value = values[node.id]
                # Match Formula.evaluate: evaluate lengths in canonical nm.
                return value * 1000 if formula.units[node.id] == "um" else value
            if isinstance(node, ast.Constant): return node.value
            if isinstance(node, ast.UnaryOp): return -visit(node.operand) if isinstance(node.op, ast.USub) else visit(node.operand)
            if isinstance(node, ast.BinOp):
                a, b = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): return a + b
                if isinstance(node.op, ast.Sub): return a - b
                if isinstance(node.op, ast.Mult): return a * b
                return a / b
            if isinstance(node, ast.Compare):
                a, b = visit(node.left), visit(node.comparators[0])
                operations = {ast.Lt: torch.lt, ast.LtE: torch.le, ast.Gt: torch.gt, ast.GtE: torch.ge, ast.Eq: torch.eq, ast.NotEq: torch.ne}
                return operations[type(node.ops[0])](a, b).to(samples.dtype)
            args = [visit(arg) for arg in node.args]
            if node.func.id == "abs": return torch.abs(args[0])
            if node.func.id in ("min", "max"):
                tensors = [torch.as_tensor(a, dtype=samples.dtype, device=samples.device).expand_as(samples[..., 0]) for a in args]
                stack = torch.stack(tensors)
                return stack.amin(0) if node.func.id == "min" else stack.amax(0)
            digits = args[1] if len(args) > 1 else 0
            value = args[0] * 10**digits
            return value.sign() * (value.abs()+.5).floor() / 10**digits
        for name in self.template.graph.order:
            if name in values: continue
            formula = self.template.graph.formulas[name]
            if not formula.dependencies <= values.keys(): continue
            if optimization and name == self.policy.get("original_metric") and self.policy["mode"] in ("stabilized", "valid_region"):
                _, numerator, denominator, absolute = self.ratio
                a, b = canonical_value(self.template, numerator, values[numerator]), canonical_value(self.template, denominator, values[denominator])
                # Finite values for every sample; valid-region infeasibility is separately
                # applied INSIDE the acquisition function, never by dropping samples.
                values[name] = stable_ratio_tensor(a, b, self.policy["epsilon_nm"], absolute)
            else:
                values[name] = visit(formula.root)
                if self.template.graph.metrics[name].get("unit") == "um":
                    values[name] = values[name] / 1000
        return values

    def transformed(self, samples, X=None, *, optimization=True):
        values = self.values(samples, optimization=optimization)
        result = []
        for objective in self.objectives:
            if objective["metric"] not in values: raise CapabilityError("目标无法从基础响应联合样本推导")
            v = values[objective["metric"]]
            if objective.get("transform") == "abs": v = v.abs()
            elif objective.get("transform") == "absolute_distance": v = (v - objective["target"]).abs()
            result.append(v if objective["direction"] == "maximize" else -v)
        return torch.stack(result, -1)

    def constraints(self):
        result = []
        if self.policy["mode"] == "valid_region" and self.ratio:
            index = self.names.index(self.ratio[2])
            epsilon = self.policy["epsilon_nm"]
            factor = canonical_value(self.template, self.ratio[2], 1)
            result.append(lambda samples, i=index, e=epsilon, f=factor: e - (samples[..., i] * f).abs())
        for c in self.template.data.get("outcome_constraints", []):
            if c.get("op") not in ("<=", ">=") or c.get("metric") not in self.names:
                raise CapabilityError("当前输出约束支持基础响应的 <= / >= 阈值")
            i, bound = self.names.index(c["metric"]), c["bound"]
            if c["op"] == "<=": result.append(lambda s, i=i, b=bound: s[..., i] - b)
            else: result.append(lambda s, i=i, b=bound: b - s[..., i])
        return result

    def scalar(self, samples, X=None):
        transformed = self.transformed(samples)
        config = self.template.data["optimization"]
        if config["mode"] == "single":
            if transformed.shape[-1] != 1: raise ValidationError("单目标模式需要明确保留一个目标")
            return transformed.squeeze(-1)
        weights, scales = config.get("weights"), config.get("scales")
        if weights is None or scales is None or len(weights) != transformed.shape[-1] or len(scales) != transformed.shape[-1] or any(s <= 0 for s in scales) or any(w < 0 for w in weights) or sum(weights) <= 0:
            raise ValidationError("加权模式需要每个目标的非负权重与正归一化尺度")
        return (transformed * torch.tensor(weights, dtype=samples.dtype) / torch.tensor(scales, dtype=samples.dtype)).sum(-1)

    def botorch_objective(self):
        return GenericMCMultiOutputObjective(self.transformed) if self.template.data["optimization"]["mode"] == "pareto" else GenericMCObjective(self.scalar)


def _sample_summary(column, *, raw=False):
    """Report finite draws explicitly; never pass NaN/Inf into a saved interval."""
    finite = column[torch.isfinite(column)]
    total, count = column.numel(), finite.numel()
    quantiles, mean = None, None
    notices = []
    if count != total:
        notices.append(f"有效有限样本 {count}/{total}，其余 {total-count} 个样本为非有限值。"
                       + ("区间仅描述有限样本，不能视为完整预测分布的区间。" if count else "没有可用的预测区间。")
                       + "请检查指标公式的分母、单位和数据尺度。")
    if count:
        q = torch.quantile(finite, column.new_tensor([.025, .5, .975]))
        if torch.isfinite(q).all():
            quantiles = q.tolist()
        else:
            notices.append("有限样本的分位数计算发生数值溢出，区间不可用；请检查单位和数据尺度。")
        if not raw and count == total:
            candidate = finite.mean().item()
            if math.isfinite(candidate):
                mean = candidate
            else:
                notices.append("样本均值计算发生数值溢出，均值不可用；请检查单位和数据尺度。")
    return {
        "mean": mean, "quantiles": quantiles,
        "sample_count": total, "finite_sample_count": count,
        "nonfinite_sample_count": total-count,
        "nonfinite_counts": {"nan": int(torch.isnan(column).sum()),
                             "positive_infinity": int(torch.isposinf(column).sum()),
                             "negative_infinity": int(torch.isneginf(column).sum())},
        "summary_status": "unavailable" if quantiles is None else "partial" if notices else "ok",
        "summary_notice": " ".join(notices),
    }


def _summarize_draws(draws, names, template, conditions, seed):
    samples = draws.shape[0]
    with torch.no_grad():
        invalid = ~torch.isfinite(draws)
        if invalid.any():
            _, condition_index, response_index = invalid.nonzero()[0].tolist()
            name = names[response_index]
            field = next(f for f in template.fields if f["name"] == name)
            count = int(invalid[:, condition_index, response_index].sum())
            error = ValidationError(
                f"预测失败：条件 {condition_index+1} 的基础响应 {field.get('label', name)}（{name}）"
                f"产生 {count}/{samples} 个非有限后验样本，不能作为有效预测。")
            error.add_note(f"预测输入条件：{conditions[condition_index]!r}\n"
                           f"响应：{name}；随机种子：{seed}；请检查模型数值稳定性、响应单位和数据尺度。")
            raise error
        objectives = Objectives(template, names)
        values = objectives.values(draws)
        # Raw ratio is always a separate record with quantiles, never finite moments.
        raw_name = None
        if objectives.ratio:
            original, numerator, denominator, absolute = objectives.ratio
            raw_name = "raw_selectivity_abs" if absolute else "raw_selectivity"
            a, b = canonical_value(template, numerator, values[numerator]), canonical_value(template, denominator, values[denominator])
            raw_ratio = a / b
            values[raw_name] = raw_ratio.abs() if absolute else raw_ratio
            if original and objectives.policy["mode"]=="stabilized":
                values[objectives.policy.get("stable_metric_name","selectivity_stable")]=stable_ratio_tensor(a, b, objectives.policy["epsilon_nm"], absolute)
                values[original]=values[raw_name]
        summaries = [{} for _ in conditions]
        for name, array in values.items():
            for i in range(len(conditions)):
                column = array[:, i]
                raw = name in (raw_name,objectives.policy.get("original_metric")) or template.graph.metrics.get(name, {}).get("undefined_policy") == "ratio_policy"
                item = _sample_summary(column, raw=raw)
                item.update(interval_kind="latent_response", source="joint_posterior_samples",
                            moment_notice=" ".join(filter(None, [
                                "原始比值仅报告有限样本分位数；不声明均值/方差存在" if raw else "",
                                item["summary_notice"]])))
                expression = template.graph.metrics.get(name, {}).get("expression")
                if expression is not None:
                    item["expression"] = expression
                summaries[i][name] = item
        constraints = objectives.constraints()
        feasible = torch.ones(draws.shape[:-1], dtype=torch.bool)
        for constraint in constraints: feasible &= constraint(draws) <= 0
        for i, summary in enumerate(summaries):
            summary["feasibility_probability"] = feasible[:, i].double().mean().item()
            summary["samples"] = samples
            summary["seed"] = seed
        # Valid-region display reports the raw, unconditional ratio quantiles.
        # Acquisition alone uses finite off-region scores plus its constraint.
        transformed=objectives.transformed(draws, optimization=objectives.policy["mode"] != "valid_region")
        for i,summary in enumerate(summaries):
            summary["objective_predictions"]=[]
            for j,objective in enumerate(objectives.objectives):
                column=transformed[:,i,j] * (1 if objective["direction"]=="maximize" else -1)
                is_raw=objective["metric"]==objectives.policy.get("original_metric") and objectives.policy["mode"]!="stabilized"
                item = _sample_summary(column, raw=is_raw)
                item.update(definition=objective, ratio_policy=objectives.policy["mode"],
                            notice=" ".join(filter(None, [
                                "原始比值不声明有限均值；可行性单独报告" if is_raw else "",
                                item["summary_notice"]])))
                expression = template.graph.metrics.get(objective["metric"], {}).get("expression")
                if expression is not None:
                    item["expression"] = expression
                summary["objective_predictions"].append(item)
        return summaries


def prediction_summary(model, encoder, names, template, conditions, seed=0, samples=512):
    from experiment_planner.domain.input_uncertainty import uncertainty_info
    with torch.random.fork_rng(), torch.no_grad():
        torch.manual_seed(seed)
        X = encoder.encode(conditions)
        draws = model.posterior(X).rsample(torch.Size([samples]))
        nominal = _summarize_draws(draws, names, template, conditions, seed)
        info = uncertainty_info(template)
        if info is None:
            return nominal
        from experiment_planner.engine.input_uncertainty import InputDistribution
        distribution = InputDistribution(template, encoder, seed)
        expanded = distribution.expand(X)
        # Each condition has a joint posterior over its perturbations. Batching
        # conditions avoids a (conditions * perturbations)^2 covariance matrix.
        summaries = []
        per_input = max(1, (samples + distribution.n_w - 1) // distribution.n_w)
        for offset in range(0, len(conditions), 16):
            perturbed = expanded[offset:offset+16]
            draws = model.posterior(perturbed).rsample(torch.Size([per_input]))
            mixture = draws.permute(0, 2, 1, 3).reshape(-1, len(perturbed), len(names))
            summaries.extend(_summarize_draws(mixture, names, template, conditions[offset:offset+16], seed))
        for i, summary in enumerate(summaries):
            for item in summary.values():
                if isinstance(item, dict) and "quantiles" in item:
                    item["interval_kind"] = "latent_response_with_input_uncertainty"
                    item["source"] = "posterior_and_conditional_input_samples"
            summary["nominal_prediction"] = nominal[i]
            summary["input_uncertainty"] = {**info, "seed": seed,
                "posterior_function_samples": per_input, "mixture_samples": per_input * distribution.n_w,
                "realized_inputs": {}}
            for field in distribution.fields:
                lo, hi = field["bounds"]
                values = lo + (hi-lo)*expanded[i, :, encoder.indices[field["name"]][0]]
                summary["input_uncertainty"]["realized_inputs"][field["name"]] = {
                    "sample_mean": values.mean().item(), "sample_std": values.std(unbiased=False).item(),
                    "min": values.min().item(), "max": values.max().item(),
                }
        return summaries
