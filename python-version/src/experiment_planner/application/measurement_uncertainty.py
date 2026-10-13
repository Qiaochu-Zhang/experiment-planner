"""Plan explicit bulk edits to raw measurement uncertainty without changing values."""
import copy
import math
from dataclasses import asdict, dataclass, field

from experiment_planner.domain.errors import ValidationError
from experiment_planner.metrics.uncertainty import Uncertainty


@dataclass
class UncertaintyPlan:
    changes: list = field(default_factory=list)
    details: list = field(default_factory=list)
    changed_cells: int = 0
    replaced_known: int = 0
    skipped_missing: int = 0
    skipped_known: int = 0

    def summary(self):
        return {"changed_records": len(self.changes), "changed_cells": self.changed_cells,
                "replaced_known": self.replaced_known, "skipped_missing": self.skipped_missing,
                "skipped_known": self.skipped_known}


def raw_measurement_names(template, name):
    """Resolve a response through the formula graph to numeric measurements."""
    numeric = {f["name"] for f in template.measurements if f.get("value_type", "float") in ("float", "int")}
    def visit(key):
        if key not in template.graph.formulas:
            return {key} & numeric
        return set().union(*(visit(dep) for dep in template.graph.formulas[key].dependencies))
    return visit(name)


def validate_standard(amount):
    if (type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0
            or not math.isfinite(amount * amount) or amount * amount == 0):
        raise ValidationError("请输入有限且大于 0 的标准不确定度 1σ，数值及其平方需在可计算范围内；0 不表示未知误差")


def plan_standard_uncertainty(template, records, measurement_names, amount, *, only_unknown=False,
                              trusted_experiment_ids=(), trusted_factor=None, reason=""):
    """A preview only: derived values are recalculated by the committing service."""
    validate_standard(amount)
    trusted = list(trusted_experiment_ids)
    if trusted_factor is not None:
        if (type(trusted_factor) not in (int, float) or not math.isfinite(trusted_factor)
                or not 0 < trusted_factor < 1):
            raise ValidationError("高可信误差比例必须大于 0 且小于 1；该比例不是准确率")
        validate_standard(amount * trusted_factor)
        if (not trusted or any(type(eid) is not int for eid in trusted)
                or not set(trusted) <= {r["id"] for r in records}):
            raise ValidationError("请在应用范围内至少选择一条高可信实验")
    elif trusted:
        raise ValidationError("选择高可信实验后需填写误差比例")
    if not isinstance(reason, str):
        raise ValidationError("设置依据需要填写文字")
    reason = reason.strip()
    trusted = set(trusted)
    fields = {f["name"]: f for f in template.measurements}
    names = list(dict.fromkeys(measurement_names))
    if not names or any(n not in fields or fields[n].get("value_type", "float") not in ("float", "int") for n in names):
        raise ValidationError("请至少选择一个数值型原始测量字段；派生指标的误差由原始测量计算")
    plan = UncertaintyPlan()
    for old in records:
        new = copy.deepcopy(old)
        changed = False
        for name in names:
            cell = new["observations"].get(name)
            if cell is None or cell.get("value") is None:
                plan.skipped_missing += 1
                continue
            previous = Uncertainty(**(cell.get("uncertainty") or {}))
            standard = previous.standard()
            known = standard is not None
            high_trust = old["id"] in trusted
            target = amount * trusted_factor if high_trust else amount
            # Never increase an already smaller, quantified uncertainty on a
            # trusted record. The baseline's fill-only rule applies to others.
            if known and ((high_trust and standard <= target) or (not high_trust and only_unknown)):
                plan.skipped_known += 1
                continue
            # Source denotes correlation, not a trust label. Preserve it; never
            # invent a common source merely because all amounts are equal.
            updated = Uncertainty(kind="std", amount=float(target), source=previous.source)
            if previous == updated:
                continue
            cell["uncertainty"] = asdict(updated)
            note = ""
            if trusted_factor is not None:
                role = "高可信" if high_trust else "基准"
                note = f"误差设定假设：{role} 1σ={target:g} {fields[name].get('unit', '1')}"
                if high_trust:
                    note += f"（基准 {amount:g} × {trusted_factor:g}）"
            if reason:
                note += ("；" if note else "误差设置依据：") + reason
            if note:
                cell["note"] = "\n".join(filter(None, (cell.get("note", ""), note)))
            plan.details.append({"experiment_id": old["id"], "measurement": name,
                                 "before": standard, "after": float(target),
                                 "role": "高可信" if high_trust else ("基准" if trusted_factor is not None else "统一"),
                                 "note": note})
            plan.changed_cells += 1
            plan.replaced_known += int(known)
            changed = True
        if changed:
            plan.changes.append((old, new))
    return plan
