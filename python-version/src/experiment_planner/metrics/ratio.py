"""One ratio definition for observations, posterior samples and acquisition."""
import ast

from experiment_planner.domain.errors import ValidationError


def ratio_definition(template):
    policy = template.data.get("ratio_policy", {})
    name = policy.get("original_metric")
    if not name or name not in template.graph.formulas:
        return None
    node = template.graph.formulas[name].root
    absolute = isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "abs"
    if absolute:
        node = node.args[0]
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
            and isinstance(node.left, ast.Name) and isinstance(node.right, ast.Name)):
        raise ValidationError("分母策略对应的指标必须是两个基础响应相除，或该比值的绝对值")
    return name, node.left.id, node.right.id, absolute


def stable_ratio(a, b, epsilon, absolute):
    """Signed denominator clipping; exact zero explicitly uses +epsilon."""
    if absolute:
        return abs(a) / max(abs(b), epsilon)
    denominator = max(abs(b), epsilon) * (-1 if b < 0 else 1)
    return a / denominator


def canonical_value(template, name, value):
    field = next(f for f in template.fields if f["name"] == name)
    return value * 1000 if field.get("unit") == "um" else value


def stable_ratio_tensor(a, b, epsilon, absolute):
    import torch
    magnitude = b.abs().clamp_min(epsilon)
    if absolute:
        return a.abs() / magnitude
    return a / torch.where(b < 0, -magnitude, magnitude)
