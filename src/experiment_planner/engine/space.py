import itertools
import math
import random
from dataclasses import asdict, dataclass, field

from experiment_planner.domain.errors import ValidationError
from experiment_planner.precision.rounding import decimal, grid_spec, quantize


@dataclass
class BatchRequest:
    n: int = 6
    mode: str = "full_space"
    baseline: dict | None = None
    baseline_id: int | None = None
    variables: list[str] = field(default_factory=list)
    exact_two: bool = False
    repeat_ids: list[int] = field(default_factory=list)
    cross_values: dict = field(default_factory=dict)
    repeat_baseline: bool = True
    model: str = "gp_rbf_v1"
    seed: int = 0
    pool_size: int = 128
    show_trend_plots: bool = False

    def validate(self, template):
        if type(self.n) is not int or not 1 <= self.n <= 100: raise ValidationError("本轮总数必须为 1–100")
        if type(self.pool_size) is not int or not 1 <= self.pool_size <= 10000: raise ValidationError("候选池数量必须为 1–10000")
        if self.mode not in ("full_space", "single", "double", "cross"): raise ValidationError("未知变化模式")
        names = {p["name"] for p in template.parameters}
        if set(self.variables) - names or len(set(self.variables)) != len(self.variables): raise ValidationError("变化变量名称无效")
        if self.variables and self.baseline is None:raise ValidationError("指定变化变量时需要基准，以固定其余条件")
        if self.mode != "full_space" or self.baseline is not None:
            if self.baseline is None: raise ValidationError("此模式需要完整基准条件")
            template.validate_conditions(self.baseline)
        if len(self.repeat_ids) > self.n: raise ValidationError("复测占用总配额，不能超过 n")
        if self.mode == "cross":
            if len(self.cross_values) != 2 or set(self.cross_values) - names: raise ValidationError("交叉布局需要两项变化值")
            if any(self.baseline[k] == v for k, v in self.cross_values.items()): raise ValidationError("交叉布局的新值不能与基准相同")
            required = 4 if self.repeat_baseline else 3
            if self.n - len(self.repeat_ids) < required: raise ValidationError("总配额不足以容纳完整交叉布局")


def changes(template, baseline, candidate):
    if baseline is None: return {}
    result = {}
    for p in template.parameters:
        k = p["name"]
        # Execution grids have exact decimal semantics; unquantized floats use
        # 1e-10 of the declared range as a documented comparison tolerance.
        if p.get("value_type", "float") in ("float", "int"):
            tolerance = 0 if grid_spec(p.get("execution_rounding", {})) else 1e-10 * max(1, (p.get("bounds", [0, 1])[1] - p.get("bounds", [0, 1])[0]))
            different = abs(decimal(candidate[k])-decimal(baseline[k])) > decimal(tolerance)
        else: different = candidate[k] != baseline[k]
        if different:
            result[k] = {"before": baseline[k], "after": candidate[k], "delta": candidate[k]-baseline[k] if p.get("value_type", "float") in ("float", "int") else None}
    return result


def key(conditions): return tuple(sorted(conditions.items()))


def valid_candidate(template, request, candidate):
    try: template.validate_conditions(candidate)
    except ValidationError: return False
    diff = changes(template, request.baseline, candidate)
    if request.variables and set(diff) - set(request.variables): return False
    if request.mode == "single" and len(diff) != 1: return False
    if request.mode == "double" and len(diff) not in ((2,) if request.exact_two else (1, 2)): return False
    return True


def parameter_values(p, rng, count):
    if "fixed_value" in p: return [p["fixed_value"]]
    if "values" in p: return p["values"]
    if p.get("value_type") == "bool": return [False, True]
    lo, hi = p["bounds"]
    rule = p.get("execution_rounding", {})
    grid = grid_spec(rule)
    if grid:
        step, origin = grid
        start = math.ceil((decimal(lo)-origin)/step)
        end = math.floor((decimal(hi)-origin)/step)
        if end < start: return []
        indices = list(range(start, end+1)) if end-start < count else [start, end] + [rng.randint(start,end) for _ in range(count)]
        return sorted(set(float(origin + i*step) for i in indices))
    if p.get("value_type") == "int":
        return list(range(math.ceil(lo), math.floor(hi)+1)) if hi-lo < count else sorted(set([math.ceil(lo), math.floor(hi)] + [rng.randint(math.ceil(lo), math.floor(hi)) for _ in range(count)]))
    return [lo, hi, *[rng.uniform(lo, hi) for _ in range(count)]]


def candidate_pool(template, request, excluded=()):
    request.validate(template)
    rng = random.Random(request.seed)
    blocked = {key(c) for c in excluded}
    candidates = []
    fields = {p["name"]: p for p in template.parameters}
    allowed = request.variables or list(fields)
    choices = {name: parameter_values(fields[name], rng, request.pool_size) for name in fields}
    if request.mode == "single": subsets = list(itertools.combinations(allowed, 1))
    elif request.mode == "double": subsets = [s for count in ([2] if request.exact_two else [1,2]) for s in itertools.combinations(allowed, count)]
    else: subsets = [tuple(allowed)]
    for subset in subsets:
        if any(not choices[k] for k in subset): continue
        count = math.prod(len(choices[k]) for k in subset)
        rows = itertools.product(*(choices[k] for k in subset)) if count <= request.pool_size * 4 else (tuple(rng.choice(choices[k]) for k in subset) for _ in range(request.pool_size*4))
        for row in rows:
            candidate = dict(request.baseline or {k: vals[0] for k, vals in choices.items() if vals})
            candidate.update(dict(zip(subset, row)))
            if key(candidate) in blocked or not valid_candidate(template, request, candidate): continue
            blocked.add(key(candidate))
            candidates.append(candidate)
    rng.shuffle(candidates)
    return candidates[:request.pool_size]
