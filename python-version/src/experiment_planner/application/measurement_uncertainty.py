"""Plan explicit bulk edits to raw measurement uncertainty without changing values."""
import copy
import math
from dataclasses import asdict, dataclass, field

from experiment_planner.domain.errors import ValidationError
from experiment_planner.metrics.uncertainty import Uncertainty


@dataclass
class UncertaintyPlan:
    changes: list = field(default_factory=list)
    changed_cells: int = 0
    replaced_known: int = 0
    skipped_missing: int = 0
    skipped_known: int = 0

    def summary(self):
        return {"changed_records": len(self.changes), "changed_cells": self.changed_cells,
                "replaced_known": self.replaced_known, "skipped_missing": self.skipped_missing,
                "skipped_known": self.skipped_known}


def plan_standard_uncertainty(template, records, measurement_names, amount, *, only_unknown=False):
    """A preview only: derived values are recalculated by the committing service."""
    if (type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0
            or not math.isfinite(amount * amount) or amount * amount == 0):
        raise ValidationError("请输入有限且大于 0 的标准不确定度 1σ，数值及其平方需在可计算范围内；0 不表示未知误差")
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
            known = previous.standard() is not None
            if only_unknown and known:
                plan.skipped_known += 1
                continue
            # Source denotes correlation, not a trust label. Preserve it; never
            # invent a common source merely because all amounts are equal.
            updated = Uncertainty(kind="std", amount=float(amount), source=previous.source)
            if previous == updated:
                continue
            cell["uncertainty"] = asdict(updated)
            plan.changed_cells += 1
            plan.replaced_known += int(known)
            changed = True
        if changed:
            plan.changes.append((old, new))
    return plan
