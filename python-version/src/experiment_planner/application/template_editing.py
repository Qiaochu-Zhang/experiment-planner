"""Template drafts and reference-aware edits; no experiment data is rewritten."""
import copy
import re

from experiment_planner.domain.errors import ValidationError

SECTIONS = ("parameters", "measurements", "derived_metrics")


def blank_template():
    return {"schema_version": 2, "template_version": 1, "name": "全新实验模板",
            "parameters": [], "measurements": [], "derived_metrics": [], "objectives": [],
            "optimization": {"mode": "pareto", "default_model_preset": "gp_rbf_v1"},
            "ratio_policy": {"mode": "remove"}, "knowledge_priors": [],
            "input_constraints": [], "outcome_constraints": [], "batch_defaults": {}}


def check_name(name, others=()):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name in ("abs", "min", "max", "round"):
        raise ValidationError("内部名称须以英文字母开头，仅含字母、数字和下划线，且不能使用公式函数名")
    if name in others: raise ValidationError("内部名称与已有字段重复")


def normalize_draft(data):
    if not isinstance(data, dict): raise ValidationError("模板必须是属性组")
    result = {**blank_template(), **copy.deepcopy(data)}
    for section in (*SECTIONS, "objectives", "knowledge_priors", "input_constraints", "outcome_constraints"):
        if not isinstance(result[section], list) or any(not isinstance(row, dict) for row in result[section]):
            raise ValidationError(f"{section} 应为属性组组成的列表")
    names = []
    for section in SECTIONS:
        for field in result[section]:
            name = field.get("name", "")
            check_name(name, names); names.append(name)
    for section in ("optimization", "ratio_policy", "batch_defaults"):
        if not isinstance(result[section], dict): raise ValidationError(f"{section} 应为属性组")
    result["optimization"].setdefault("mode", "pareto")
    result["ratio_policy"].setdefault("mode", "remove")
    return result


def rename_field(data, old, new):
    result = copy.deepcopy(data)
    fields = [f for section in SECTIONS for f in result.get(section, [])]
    check_name(new, [f["name"] for f in fields if f["name"] != old])
    for field in fields:
        if field["name"] == old: field["name"] = new
        if "expression" in field:
            field["expression"] = re.sub(r"\b" + re.escape(old) + r"\b", new, field["expression"])
    for section, keys in (("objectives", ("metric",)), ("knowledge_priors", ("input", "response")), ("outcome_constraints", ("metric",))):
        for item in result.get(section, []):
            for key in keys:
                if item.get(key) == old: item[key] = new
    for item in result.get("input_constraints", []):
        coefficients = item.get("coefficients", {})
        if old in coefficients: coefficients[new] = coefficients.pop(old)
    policy = result.get("ratio_policy", {})
    if policy.get("original_metric") == old: policy["original_metric"] = new
    defaults = result.get("batch_defaults", {})
    if "changed_parameter_names" in defaults:
        defaults["changed_parameter_names"] = [new if n == old else n for n in defaults["changed_parameter_names"]]
    cross = defaults.get("cross_values", {})
    if old in cross: cross[new] = cross.pop(old)
    return result


def remove_fields(data, names):
    result = copy.deepcopy(data)
    removed = set(names)
    while True:
        dependencies = {f["name"] for f in result.get("derived_metrics", [])
                        if set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", f.get("expression", ""))) & removed}
        if dependencies <= removed: break
        removed |= dependencies
    policy = result.get("ratio_policy", {})
    active = [o for o in result.get("objectives", []) if not (policy.get("mode") == "remove" and o["metric"] == policy.get("original_metric"))]
    for key in ("weights", "scales"):
        values = result.get("optimization", {}).get(key)
        if isinstance(values, list):
            result["optimization"][key] = [v for o, v in zip(active, values) if o["metric"] not in removed]
    for section in SECTIONS:
        result[section] = [f for f in result.get(section, []) if f["name"] not in removed]
    result["objectives"] = [o for o in result.get("objectives", []) if o["metric"] not in removed]
    result["knowledge_priors"] = [p for p in result.get("knowledge_priors", []) if not {p.get("input"), p.get("response")} & removed]
    result["input_constraints"] = [c for c in result.get("input_constraints", []) if not set(c.get("coefficients", {})) & removed]
    result["outcome_constraints"] = [c for c in result.get("outcome_constraints", []) if c.get("metric") not in removed]
    if policy.get("original_metric") in removed: result["ratio_policy"] = {"mode": "remove"}
    defaults = result.get("batch_defaults", {})
    if "changed_parameter_names" in defaults:
        defaults["changed_parameter_names"] = [n for n in defaults["changed_parameter_names"] if n not in removed]
    if "cross_values" in defaults:
        defaults["cross_values"] = {n: v for n, v in defaults["cross_values"].items() if n not in removed}
    return result, sorted(removed)
