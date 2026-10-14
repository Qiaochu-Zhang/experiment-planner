"""Best-effort variation across a batch, independent of per-row change limits."""
from experiment_planner.precision.rounding import decimal, grid_spec


def different(field, before, after):
    if field.get("value_type", "float") not in ("float", "int"):
        return before != after
    # Match execution-grid semantics and the existing per-row change tolerance.
    bounds = field.get("bounds", [0, 1])
    tolerance = 0 if grid_spec(field.get("execution_rounding", {})) else 1e-10 * max(1, bounds[1] - bounds[0])
    return abs(decimal(after) - decimal(before)) > decimal(tolerance)


class BatchCoverage:
    def __init__(self, template, variables):
        self.fields = {p["name"]: p for p in template.parameters if p["name"] in variables}
        self.extremes = {}
        self.varied = set()

    def gain(self, condition):
        return sum(
            different(self.fields[name], low, condition[name]) or different(self.fields[name], high, condition[name])
            for name, (low, high) in self.extremes.items() if name not in self.varied
        )

    def add(self, condition):
        for name, field in self.fields.items():
            if name in self.varied:
                continue
            value = condition[name]
            low, high = self.extremes.get(name, (value, value))
            low, high = min(low, value), max(high, value)
            self.extremes[name] = low, high
            if different(field, low, high):
                self.varied.add(name)

    def choose(self, pool, scores=None):
        # The first row follows the existing ranking. Thereafter prefer the
        # largest additional variable coverage, breaking ties by that ranking.
        # Once covered (or no gain is possible), this is the original ranking.
        return max(range(len(pool)), key=lambda i: (self.gain(pool[i]), scores[i] if scores is not None else -i))

    def report(self):
        return {
            "algorithm": "variable_coverage_v1",
            "requested_variables": list(self.fields),
            "varied_variables": [name for name in self.fields if name in self.varied],
            "constant_variables": [name for name in self.fields if name not in self.varied],
            "complete": len(self.varied) == len(self.fields),
        }


def coverage_variables(template, request):
    if request.variables:
        return request.variables
    return [p["name"] for p in template.parameters
            if "fixed_value" not in p and len(p.get("values", [0, 1])) > 1
            and not (p.get("value_type") == "text" and "values" not in p)]


def retain_coverage(template, variables, candidates, size):
    """Keep witnesses of sampled variation before filling a bounded pool."""
    if len(candidates) <= size:
        return candidates
    coverage = BatchCoverage(template, variables)
    kept = []
    while candidates and len(kept) < size:
        chosen = coverage.choose(candidates)
        if kept and coverage.gain(candidates[chosen]) == 0:
            break
        condition = candidates.pop(chosen)
        kept.append(condition)
        coverage.add(condition)
    return kept + candidates[:size - len(kept)]
