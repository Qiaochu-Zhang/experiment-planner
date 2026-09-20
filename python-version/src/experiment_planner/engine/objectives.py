import ast
import torch
from botorch.acquisition.multi_objective.objective import GenericMCMultiOutputObjective
from botorch.acquisition.objective import GenericMCObjective

from experiment_planner.domain.errors import CapabilityError, ValidationError


class Objectives:
    def __init__(self, template, response_names):
        self.template = template
        self.names = response_names
        self.policy = template.data.get("ratio_policy", {"mode": "remove"})
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
                a, b = values["sio2_loss_nm"], values["sin_loss_nm"]
                # Finite values for every sample; valid-region infeasibility is separately
                # applied INSIDE the acquisition function, never by dropping samples.
                values[name] = a.abs() / b.abs().clamp_min(self.policy["epsilon_nm"])
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
        if self.policy["mode"] == "valid_region":
            index = self.names.index("sin_loss_nm")
            epsilon = self.policy["epsilon_nm"]
            result.append(lambda samples, i=index, e=epsilon: e - samples[..., i].abs())
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


def prediction_summary(model, encoder, names, template, conditions, seed=0, samples=512):
    with torch.random.fork_rng(), torch.no_grad():
        torch.manual_seed(seed)
        draws = model.posterior(encoder.encode(conditions)).rsample(torch.Size([samples]))
        objectives = Objectives(template, names)
        values = objectives.values(draws)
        # Raw ratio is always a separate record with quantiles, never finite moments.
        if "sio2_loss_nm" in values and "sin_loss_nm" in values:
            values["raw_selectivity_abs"] = (values["sio2_loss_nm"] / values["sin_loss_nm"]).abs()
            original=objectives.policy.get("original_metric")
            if original and objectives.policy["mode"]=="stabilized":
                values[objectives.policy.get("stable_metric_name","selectivity_stable")]=(values["sio2_loss_nm"].abs() / values["sin_loss_nm"].abs().clamp_min(objectives.policy["epsilon_nm"]))
                values[original]=values["raw_selectivity_abs"]
        summaries = [{} for _ in conditions]
        for name, array in values.items():
            for i in range(len(conditions)):
                column = array[:, i]
                finite = column[torch.isfinite(column)]
                raw = name in ("raw_selectivity_abs",objectives.policy.get("original_metric"))
                summaries[i][name] = {"mean": None if raw or len(finite) != samples else finite.mean().item(), "quantiles": torch.quantile(finite, torch.tensor([.025, .5, .975], dtype=draws.dtype)).tolist() if len(finite) else None, "interval_kind": "latent_response", "source": "joint_posterior_samples", "moment_notice": "原始比值仅报告有限样本分位数；不声明均值/方差存在" if raw else ""}
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
                summary["objective_predictions"].append({"definition":objective,"ratio_policy":objectives.policy["mode"],"mean":None if is_raw else column.mean().item(),"quantiles":torch.quantile(column,torch.tensor([.025,.5,.975],dtype=draws.dtype)).tolist(),"notice":"有效区域策略的原始比值不声明有限均值；可行性单独报告" if is_raw else ""})
        return summaries
