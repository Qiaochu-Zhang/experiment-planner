from decimal import Decimal, ROUND_HALF_UP
from math import isfinite

from experiment_planner.domain.errors import ValidationError


def decimal(value):
    if isinstance(value, bool):
        raise ValidationError("布尔值不能进行数值取整")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValidationError("需要有限数值") from exc
    if not result.is_finite():
        raise ValidationError("需要有限数值")
    return result


def round_decimal(value, digits=0):
    if isinstance(digits, bool) or not isinstance(digits, int) or not -12 <= digits <= 12:
        raise ValidationError("取整位数必须为 -12 至 12 的整数")
    return float(decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def grid_spec(rule):
    mode = rule.get("mode", "none")
    if mode == "none":
        if rule.get("digits") is not None or rule.get("step") is not None:
            raise ValidationError("未启用执行取整，但配置了步长或位数")
        return None
    if mode not in ("digits", "step"):
        raise ValidationError("未知执行精度模式")
    digits, step = rule.get("digits"), rule.get("step")
    if digits is not None:
        round_decimal(0, digits)
        expected = Decimal(1).scaleb(-digits)
        if step is not None and decimal(step) != expected:
            raise ValidationError("执行步长和位数冲突")
        step = expected
    if step is None or decimal(step) <= 0:
        raise ValidationError("执行步长必须大于零")
    return decimal(step), decimal(rule.get("origin", 0))


def quantize(value, rule):
    grid = grid_spec(rule)
    if grid is None:
        return float(decimal(value))
    step, origin = grid
    return float(origin + ((decimal(value) - origin) / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step)


def on_grid(value, rule):
    grid = grid_spec(rule)
    return grid is None or (decimal(value) - grid[1]) % grid[0] == 0


def display(value, digits=None):
    if value is None:
        return "未测"
    if isinstance(value, bool):
        return "是" if value else "否"
    if digits is None or not isinstance(value, (int, float)):
        return str(value)
    if not isfinite(value):
        raise ValidationError("不能显示非法数值")
    return f"{round_decimal(value, digits):.{max(0, digits)}f}"
