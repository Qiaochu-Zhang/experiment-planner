from dataclasses import asdict

from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import parse_value
from experiment_planner.metrics.uncertainty import Uncertainty, difference, propagate
from experiment_planner.metrics.ratio import ratio_definition, stable_ratio, canonical_value


def normalize_observations(template, observations):
    fields = {f["name"]: f for f in template.measurements}
    if set(observations) - set(fields): raise ValidationError("包含未知测量字段")
    result = {}
    for name, raw in observations.items():
        cell = raw.copy() if isinstance(raw, dict) else {"value": raw}
        field = fields[name]
        value = parse_value(cell.get("value"), field)
        unit = cell.get("unit", field.get("unit", "1"))
        if unit != field.get("unit", "1"):
            raise ValidationError(f"{name}：单位不匹配，请先明确转换")
        uncertainty = Uncertainty(**(cell.get("uncertainty") or {}))
        if field.get("value_type") in ("bool", "text", "category") and uncertainty.kind != "unspecified":
            raise ValidationError("非数值测量不能附数值误差")
        result[name] = {**cell, "value": value, "unit": unit, "uncertainty": asdict(uncertainty), "note": str(cell.get("note", ""))}
    return result


def derive(template, conditions, observations):
    values = {**conditions, **{n: c["value"] for n, c in observations.items()}}
    results = {n: asdict(v) for n, v in template.graph.evaluate(values).items()}
    uncertainties = {n: Uncertainty(**c["uncertainty"]) for n, c in observations.items()}
    propagated = propagate(template.graph, values, uncertainties)
    for name, item in results.items(): item["uncertainty"] = propagated.get(name)
    # Exact subtraction for ICP, retaining error bounds separately from standard errors.
    for metric, initial, remaining in (("sio2_loss_nm", "sio2_initial_nm", "sio2_remaining_nm"), ("sin_loss_nm", "sin_initial_nm", "sin_remaining_nm")):
        if metric not in results or results[metric]["status"] != "valid": continue
        if template.graph.metrics[metric]["expression"] != f"{initial} - {remaining}": continue
        u, v = uncertainties.get(initial, Uncertainty()), uncertainties.get(remaining, Uncertainty())
        covariance = None
        if u.source and u.source == v.source and u.standard() is not None and v.standard() is not None:
            covariance = u.standard() * v.standard()
        results[metric]["uncertainty"] = difference(values[initial], values[remaining], u, v, covariance)
    definition = ratio_definition(template)
    if definition:
        name, numerator, denominator, absolute = definition
        responses = {**observations, **results}
        ratio, a, b = results[name], responses.get(numerator, {}), responses.get(denominator, {})
        interval = (b.get("uncertainty") or {}).get("interval")
        if denominator in uncertainties:
            offsets = uncertainties[denominator].offsets()
            if offsets and b.get("value") is not None:
                interval = [b["value"] + offset for offset in offsets]
        if b.get("value") == 0 or (interval and interval[0] <= 0 <= interval[1]):
            ratio["status"] = "unstable"
            ratio["reason"] = "分母为零或其测量区间跨零；保留有效 A、B"
        policy = template.data["ratio_policy"]
        if policy["mode"] == "stabilized" and a.get("value") is not None and b.get("value") is not None:
            results[policy.get("stable_metric_name", "selectivity_stable")] = {"value": stable_ratio(canonical_value(template, numerator, a["value"]), canonical_value(template, denominator, b["value"]), policy["epsilon_nm"], absolute), "status": "valid", "source": "stabilized_observation", "epsilon_nm": policy["epsilon_nm"], "formula_version": template.data["template_version"]}
    return results
