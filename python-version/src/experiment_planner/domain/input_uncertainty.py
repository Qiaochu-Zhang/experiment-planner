"""Optional future execution uncertainty; historical input locations stay fixed."""
import math

from experiment_planner.domain.errors import ValidationError


def eligible_input(field):
    return (field.get("value_type", "float") == "float" and "bounds" in field
            and "values" not in field and "fixed_value" not in field
            and field.get("use_as_model_input", True))


def selected_inputs(template):
    if not template.data.get("input_uncertainty", {}).get("enabled", False):
        return []
    return [p for p in template.parameters if p.get("input_uncertainty", {}).get("enabled", False)]


def validate_input_uncertainty(template):
    config = template.data.get("input_uncertainty", {})
    if not isinstance(config, dict) or type(config.get("enabled", False)) is not bool:
        raise ValidationError("输入不确定度总开关必须是布尔值")
    if type(config.get("samples", 16)) is not int or config.get("samples", 16) not in (8, 16, 32):
        raise ValidationError("输入不确定度采样数请选择 8、16 或 32")
    for p in template.parameters:
        setting = p.get("input_uncertainty", {})
        if not isinstance(setting, dict) or type(setting.get("enabled", False)) is not bool:
            raise ValidationError(f"{p['name']}：输入不确定度需要明确的启用开关")
        if not config.get("enabled", False) or not setting.get("enabled", False):
            continue
        if not eligible_input(p):
            raise ValidationError(f"{p['name']}：输入不确定度仅支持有上下限、参与建模的连续数值输入；整数、离散及固定值暂不支持")
        amount = setting.get("amount")
        if type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0:
            raise ValidationError(f"{p['name']}：输入不确定度必须填写大于零的有限数值")
        if setting.get("kind", "std") not in ("std", "bounds"):
            raise ValidationError(f"{p['name']}：请选择正态标准差或均匀最大偏差")
        width = p["bounds"][1] - p["bounds"][0]
        scaled = amount / width
        if not math.isfinite(width) or not math.isfinite(scaled) or not 1e-12 <= scaled <= 1e6:
            raise ValidationError(f"{p['name']}：不确定度相对输入范围过小或过大，请核对单位和数值")
    if config.get("enabled", False) and not selected_inputs(template):
        raise ValidationError("开启输入不确定度后，请至少勾选一个输入参数并填写其不确定度")


def uncertainty_info(template):
    fields = selected_inputs(template)
    if not fields:
        return None
    return {
        "enabled": True, "samples": template.data.get("input_uncertainty", {}).get("samples", 16),
        "scope": "future_execution_only", "boundary_policy": "condition_on_template_bounds_and_constraints",
        "dependence": "independent_before_constraint_conditioning",
        "recommendation": "expected_objectives_with_all_sampled_outcomes_feasible",
        "parameters": [{"name": p["name"], "label": p.get("label", p["name"]), "unit": p.get("unit", "1"),
                        **p["input_uncertainty"]} for p in fields],
    }


INPUT_UNCERTAINTY_NOTICE = (
    "已考虑所选输入的未来执行波动：各输入原始扰动独立，并假设实际执行限制在模板范围与线性约束内（条件分布采样）。"
    "正态 1σ / 均匀最大偏差均指截断前分布；靠近边界时实际均值与标准差会改变。"
    "历史输入仍按记录值训练；结果不包含额外未来量测噪声。"
)
