"""Small AST interpreter. Templates never execute Python code."""
import ast
import math
from dataclasses import dataclass

from experiment_planner.domain.errors import ValidationError
from experiment_planner.precision.rounding import round_decimal


def unit_dimension(unit):
    units = {"1": {}, "": {}, "nm": {"length": 1}, "um": {"length": 1},
             "sccm": {"flow": 1}, "W": {"power": 1}, "mT": {"pressure": 1},
             "mTorr": {"pressure": 1}, "°C": {"temperature": 1}, "s": {"time": 1}}
    if unit not in units:
        raise ValidationError(f"未支持的单位：{unit}")
    return units[unit]


def combine(a, b, sign):
    result = a.copy()
    for key, value in b.items():
        result[key] = result.get(key, 0) + sign * value
    return {k: v for k, v in result.items() if v}


class Formula:
    def __init__(self, expression, units):
        if not isinstance(expression, str) or len(expression) > 2048:
            raise ValidationError("公式过长或类型错误")
        try:
            self.root = ast.parse(expression, mode="eval").body
        except (SyntaxError, RecursionError) as exc:
            raise ValidationError("公式语法错误") from exc
        if len(list(ast.walk(self.root))) > 256:
            raise ValidationError("公式过于复杂")
        self.dependencies = set()
        self.units = units
        self.dimension = self._check(self.root)

    def _check(self, node):
        if isinstance(node, ast.Name):
            if node.id not in self.units:
                raise ValidationError(f"公式引用未知字段：{node.id}")
            self.dependencies.add(node.id)
            return unit_dimension(self.units[node.id])
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not math.isfinite(node.value):
                raise ValidationError("公式常数必须有限")
            return {}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return self._check(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = self._check(node.left), self._check(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if a != b:
                    raise ValidationError("加减运算单位不兼容")
                return a
            return combine(a, b, 1 if isinstance(node.op, ast.Mult) else -1)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name not in ("abs", "min", "max", "round"):
                raise ValidationError("公式函数不在白名单")
            if not node.args or (name == "abs" and len(node.args) != 1) or (name == "round" and len(node.args) not in (1, 2)):
                raise ValidationError("公式函数参数数量错误")
            first = self._check(node.args[0])
            if name == "round" and len(node.args) == 2:
                try:
                    digits = ast.literal_eval(node.args[1])
                    round_decimal(0, digits)
                except (ValueError, TypeError) as exc:
                    raise ValidationError("round 位数必须是整数常量") from exc
            elif any(self._check(arg) != first for arg in node.args[1:]):
                raise ValidationError("min/max 单位不兼容")
            return first
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)):
            if self._check(node.left) != self._check(node.comparators[0]):
                raise ValidationError("比较运算单位不兼容")
            return {}
        raise ValidationError(f"公式不允许语法：{type(node).__name__}")

    def evaluate(self, values):
        def visit(node):
            if isinstance(node, ast.Name):
                value = values.get(node.id)
                if value is None:
                    raise KeyError(node.id)
                # Canonical lengths are nm; do not silently mix um and nm.
                return value * 1000 if self.units[node.id] == "um" else value
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.UnaryOp):
                value = visit(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                a, b = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): return a + b
                if isinstance(node.op, ast.Sub): return a - b
                if isinstance(node.op, ast.Mult): return a * b
                return a / b
            if isinstance(node, ast.Compare):
                a, b = visit(node.left), visit(node.comparators[0])
                op = node.ops[0]
                if isinstance(op, ast.Lt): return a < b
                if isinstance(op, ast.LtE): return a <= b
                if isinstance(op, ast.Gt): return a > b
                if isinstance(op, ast.GtE): return a >= b
                if isinstance(op, ast.Eq): return a == b
                return a != b
            name = node.func.id
            args = [visit(arg) for arg in node.args]
            if name == "abs": return abs(args[0])
            if name == "min": return min(args)
            if name == "max": return max(args)
            return round_decimal(*args)
        value = visit(self.root)
        if not math.isfinite(value):
            raise ArithmeticError("非有限公式结果")
        return value


@dataclass
class MetricValue:
    value: float | bool | None
    status: str
    sources: list[str]
    formula_version: int
    reason: str = ""


class FormulaGraph:
    def __init__(self, fields, metrics, version=1):
        self.metrics = {m["name"]: m for m in metrics}
        self.version = version
        units = {f["name"]: f.get("unit", "1") for f in [*fields, *metrics]}
        self.formulas = {name: Formula(m["expression"], units) for name, m in self.metrics.items()}
        self.order = []
        visiting = set()

        def walk(name):
            if name in visiting:
                raise ValidationError(f"公式循环依赖：{name}")
            if name in self.order: return
            visiting.add(name)
            formula = self.formulas[name]
            if formula.dimension != unit_dimension(units[name]):
                raise ValidationError(f"公式结果单位不符：{name}")
            for dep in formula.dependencies:
                if dep in self.formulas: walk(dep)
            visiting.remove(name)
            self.order.append(name)
        for name in self.formulas: walk(name)

    def evaluate(self, values):
        values = values.copy()
        output = {}
        for name in self.order:
            formula = self.formulas[name]
            try:
                value = formula.evaluate(values)
                if self.metrics[name].get("unit") == "um": value /= 1000
                status, reason = "valid", ""
            except KeyError as exc:
                value, status, reason = None, "missing", f"缺少依赖：{exc.args[0]}"
            except (ArithmeticError, ValueError) as exc:
                value, status, reason = None, "undefined", str(exc)
            output[name] = MetricValue(value, status, sorted(formula.dependencies), self.version, reason)
            values[name] = value
        return output
