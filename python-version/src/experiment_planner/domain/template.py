import copy
import json
import math
import re
from importlib.resources import files

from experiment_planner.domain.errors import ValidationError
from experiment_planner.metrics.formulas import FormulaGraph, unit_dimension
from experiment_planner.precision.rounding import grid_spec, on_grid


def parse_value(value, field):
    if value is None or value == "": return None
    kind = field.get("value_type", "float")
    if kind == "bool":
        if type(value) is bool: return value
        mapping = {"true": True, "false": False, "是": True, "否": False, "1": True, "0": False}
        key = str(value).strip().lower()
        if key not in mapping: raise ValidationError(f"{field['name']}：非法布尔值")
        return mapping[key]
    if kind in ("text", "category"):
        result = str(value)
        if kind == "category" and result not in field.get("values", []):
            raise ValidationError(f"{field['name']}：未知类别")
        return result
    if kind not in ("float", "int") or isinstance(value, bool):
        raise ValidationError(f"{field['name']}：数值类型错误")
    try: result = float(value)
    except (ValueError, TypeError) as exc: raise ValidationError(f"{field['name']}：需要数值") from exc
    if not math.isfinite(result): raise ValidationError(f"{field['name']}：数值必须有限")
    if kind == "int" and not result.is_integer(): raise ValidationError(f"{field['name']}：需要整数")
    return int(result) if kind == "int" else result


class Template:
    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.validate()

    @classmethod
    def builtin(cls):
        return cls(json.loads(files("experiment_planner").joinpath("resources/templates/icp.json").read_text(encoding="utf-8")))

    @classmethod
    def read(cls, path):
        with open(path, encoding="utf-8") as source: return cls(json.load(source))

    def write(self, path):
        with open(path, "w", encoding="utf-8") as target:
            json.dump(self.data, target, ensure_ascii=False, indent=2, allow_nan=False)

    @property
    def parameters(self): return self.data["parameters"]

    @property
    def measurements(self): return self.data.get("measurements", [])

    @property
    def metrics(self): return self.data.get("derived_metrics", [])

    @property
    def fields(self): return self.parameters + self.measurements + self.metrics

    @property
    def responses(self):
        return [f for f in self.fields if f.get("is_response") and f.get("model_base", True)]

    def revised(self, **changes):
        data = copy.deepcopy(self.data)
        data.update(changes)
        data["template_version"] += 1
        return Template(data)

    def validate(self):
        d = self.data
        if d.get("schema_version") != 2: raise ValidationError("只支持 schema v2；旧项目需要明确迁移")
        if not isinstance(d.get("template_version"), int) or d["template_version"] < 1:
            raise ValidationError("模板版本无效")
        if not d.get("parameters"): raise ValidationError("模板至少需要一个可控输入")
        names = [f.get("name", "") for f in self.fields]
        if len(names) != len(set(names)) or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", n) or n in ("abs", "min", "max", "round") for n in names):
            raise ValidationError("字段名重复、保留或不合法")
        for field in self.fields:
            unit_dimension(field.get("unit", "1"))
            if field.get("value_type", "float") not in ("float", "int", "category", "bool", "text"):
                raise ValidationError("未知字段类型")
            if field.get("use_as_model_input") and (field.get("measured_at") in ("after", "unknown") or field.get("value_type") == "text"):
                raise ValidationError(f"{field['name']}：事后/未知测量或备注不能作为未来输入")
        for p in self.parameters:
            kind = p.get("value_type", "float")
            if kind == "text": raise ValidationError("文字备注不能作为可控输入")
            if kind in ("bool", "category") and p.get("execution_rounding", {}).get("mode", "none") != "none":
                raise ValidationError("类别/布尔输入不能数值取整")
            grid_spec(p.get("execution_rounding", {}))
            if "bounds" in p:
                lo, hi = p["bounds"]
                if not all(type(x) in (float, int) and math.isfinite(x) for x in (lo, hi)) or lo >= hi:
                    raise ValidationError("输入范围无效")
            elif "fixed_value" not in p and "values" not in p and kind != "bool":
                raise ValidationError("可控输入需要范围、离散值或固定值")
            if "values" in p and (not p["values"] or len(set(p["values"])) != len(p["values"])):
                raise ValidationError("离散值不能为空或重复")
            if "fixed_value" in p: self._validate_parameter(p, p["fixed_value"])
        self.graph = FormulaGraph(self.parameters + self.measurements, self.metrics, d["template_version"])
        fields = {f["name"]: f for f in self.fields}
        for formula in self.graph.formulas.values():
            if any(fields[n].get("value_type") in ("text","category") for n in formula.dependencies):
                raise ValidationError("数值公式不能引用文字或类别字段")
        def known(name):
            f = fields[name]
            if name in self.graph.formulas:
                return all(known(dep) for dep in self.graph.formulas[name].dependencies)
            return name in {p["name"] for p in self.parameters} or f.get("measured_at") == "before"
        for f in self.fields:
            if f.get("use_as_model_input") and not known(f["name"]): raise ValidationError("模型输入依赖未来未知测量")
        for obj in d.get("objectives", []):
            if obj.get("metric") not in fields: raise ValidationError("目标字段不存在")
            if fields[obj["metric"]].get("value_type") in ("text", "category"): raise ValidationError("文字和类别不能直接作为数值目标")
            if obj.get("direction") not in ("minimize", "maximize"): raise ValidationError("目标方向无效")
            if obj.get("transform", "identity") not in ("identity", "abs", "absolute_distance"): raise ValidationError("未知目标变换")
        policy = d.get("ratio_policy", {"mode": "remove"})
        if policy.get("mode") not in ("require_configuration", "valid_region", "stabilized", "remove"):
            raise ValidationError("未知分母策略")
        if policy["mode"] in ("valid_region", "stabilized"):
            epsilon = policy.get("epsilon_nm")
            if type(epsilon) not in (int, float) or not math.isfinite(epsilon) or epsilon <= 0:
                raise ValidationError("分母策略需要大于零的 epsilon（nm）")
        for constraint in d.get("input_constraints", []):
            if constraint.get("op") not in ("<=", ">=") or not constraint.get("coefficients"):
                raise ValidationError("仅支持明确系数的线性输入约束")
            if set(constraint["coefficients"]) - {p["name"] for p in self.parameters}:
                raise ValidationError("输入约束字段不存在")
            if any(type(v) not in (float,int) or not math.isfinite(v) for v in [constraint.get("rhs"),*constraint["coefficients"].values()]):
                raise ValidationError("输入约束系数及阈值必须是有限数值")
            for key in constraint["coefficients"]:
                if fields[key].get("value_type", "float") not in ("float", "int"):
                    raise ValidationError("线性约束仅支持数值输入")

    def _validate_parameter(self, field, value, execution=True):
        value = parse_value(value, field)
        if value is None: raise ValidationError(f"缺少输入：{field['name']}")
        if "bounds" in field and not field["bounds"][0] <= value <= field["bounds"][1]:
            raise ValidationError(f"{field['name']}：超出范围")
        if "values" in field and value not in field["values"]: raise ValidationError("不在离散值集合")
        if "fixed_value" in field and value != field["fixed_value"]: raise ValidationError("固定值不能改变")
        if execution and field.get("value_type", "float") in ("float", "int") and not on_grid(value, field.get("execution_rounding", {})):
            raise ValidationError(f"{field['name']}：不在执行网格")
        return value

    def validate_conditions(self, values, execution=True):
        if set(values) != {p["name"] for p in self.parameters}: raise ValidationError("输入条件字段不完整或含未知字段")
        result = {p["name"]: self._validate_parameter(p, values[p["name"]], execution) for p in self.parameters}
        for c in self.data.get("input_constraints", []):
            lhs = sum(float(a) * result[n] for n, a in c["coefficients"].items())
            if (c["op"] == "<=" and lhs > c["rhs"] + 1e-10) or (c["op"] == ">=" and lhs < c["rhs"] - 1e-10):
                raise ValidationError("输入条件不满足线性约束")
        return result

    def require_ratio_configuration(self):
        if any(o["metric"] == self.data.get("ratio_policy", {}).get("original_metric") for o in self.data.get("objectives", [])):
            if self.data["ratio_policy"]["mode"] == "require_configuration":
                raise ValidationError("需要设置分母处理方式；仍可记录数据和预测基础响应")
