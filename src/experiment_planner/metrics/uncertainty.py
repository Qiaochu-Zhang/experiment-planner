"""Explicit uncertainty semantics and shared-source propagation."""
import math
from dataclasses import asdict, dataclass
from statistics import NormalDist

import numpy as np

from experiment_planner.domain.errors import ValidationError


@dataclass(frozen=True)
class Uncertainty:
    kind: str = "unspecified"
    amount: float | None = None
    lower: float | None = None
    upper: float | None = None
    distribution: str | None = None
    coverage_factor: float | None = None
    confidence: float | None = None
    source: str | None = None

    def __post_init__(self):
        if self.kind not in ("unspecified", "std", "sem", "interval", "bounds", "asymmetric"):
            raise ValidationError("未知不确定度含义")
        for value in (self.amount, self.lower, self.upper):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValidationError("不确定度必须为有限非负数")
        if self.coverage_factor is not None and (not math.isfinite(self.coverage_factor) or self.coverage_factor <= 0):
            raise ValidationError("覆盖因子必须大于零")
        if self.confidence is not None and not 0 < self.confidence < 1:
            raise ValidationError("置信水平必须在 0 与 1 之间")
        if self.kind == "asymmetric" and (self.lower is None or self.upper is None):
            raise ValidationError("非对称误差需要上下误差")

    def standard(self):
        if self.amount is None: return None
        if self.kind in ("std", "sem"): return self.amount
        if self.kind == "bounds" and self.distribution == "uniform": return self.amount / math.sqrt(3)
        if self.kind == "interval" and self.distribution == "normal":
            factor = self.coverage_factor
            if factor is None and self.confidence is not None:
                factor = NormalDist().inv_cdf((1 + self.confidence) / 2)
            return self.amount / factor if factor is not None else None
        return None

    def offsets(self):
        if self.kind == "asymmetric": return -self.lower, self.upper
        if self.kind == "bounds" and self.amount is not None: return -self.amount, self.amount
        std = self.standard()
        return (-1.96 * std, 1.96 * std) if std is not None else None


def difference(first, second, u_first, u_second, covariance=None):
    value = first - second
    u, v = u_first.standard(), u_second.standard()
    result = {"value": value, "standard": None, "interval": None, "assumption": "independent" if covariance is None else "provided_covariance"}
    if u is not None and v is not None:
        cov = covariance or 0
        if abs(cov) > u * v + 1e-12: raise ValidationError("协方差超过允许范围")
        result["standard"] = math.sqrt(max(0, u*u + v*v - 2*cov))
        result["interval"] = [value - 1.96*result["standard"], value + 1.96*result["standard"]]
        result["method"] = "exact_covariance"
    elif u_first.kind in ("bounds", "asymmetric") and u_second.kind in ("bounds", "asymmetric"):
        a, b = u_first.offsets(), u_second.offsets()
        if a is not None and b is not None:
            result["interval"] = [value + a[0] - b[1], value + a[1] - b[0]]
            result["method"] = "worst_case_bounds"
    else: result["method"] = "unknown_uncertainty"
    return result


def propagate(graph, values, uncertainties, *, covariance=None, samples=4096, seed=0):
    """Every raw field is sampled once and reused throughout the expression DAG.

    Covariance is in the raw fields' native units, ordered by sorted(values).
    Unknown uncertainties remain unknown; they are never substituted with zero.
    """
    names = sorted(k for k, v in values.items() if type(v) in (float, int))
    rng = np.random.default_rng(seed)
    streams = {}
    if covariance is not None:
        stds = [uncertainties.get(n, Uncertainty()).standard() for n in names]
        if any(s is None for s in stds): raise ValidationError("协方差传播需要全部标准不确定度")
        cov = np.asarray(covariance, dtype=float)
        if cov.shape != (len(names), len(names)) or not np.isfinite(cov).all() or not np.allclose(cov, cov.T) or np.linalg.eigvalsh(cov).min() < -1e-10:
            raise ValidationError("协方差矩阵必须对称半正定且与字段顺序一致")
        if not np.allclose(np.diag(cov), np.square(stds)): raise ValidationError("协方差对角线与标准不确定度不符")
        matrix = rng.multivariate_normal([values[n] for n in names], cov, samples)
        streams.update({n: matrix[:, i] for i, n in enumerate(names)})
    else:
        sources = {}
        for name in names:
            u = uncertainties.get(name, Uncertainty())
            std = u.standard()
            if std is None: continue
            distribution = "uniform" if u.kind == "bounds" else "normal"
            key = u.source or f"field:{name}"
            if key in sources and sources[key][0] != distribution:
                raise ValidationError("同一共享来源的分布口径冲突")
            if key not in sources:
                z = rng.uniform(-math.sqrt(3), math.sqrt(3), samples) if distribution == "uniform" else rng.standard_normal(samples)
                sources[key] = (distribution, z)
            streams[name] = values[name] + std * sources[key][1]
    result = {}
    for name in graph.order:
        formula = graph.formulas[name]
        if any(dep not in streams for dep in formula.dependencies):
            result[name] = {"standard": None, "method": "unknown_uncertainty"}
            continue
        output = []
        for i in range(samples):
            try:
                value = formula.evaluate({dep: streams[dep][i] for dep in formula.dependencies})
                if graph.metrics[name].get("unit") == "um": value /= 1000
            except (ArithmeticError, ValueError): value = np.nan
            output.append(value)
        array = np.asarray(output)
        streams[name] = array
        valid = array[np.isfinite(array)]
        is_ratio = graph.metrics[name].get("undefined_policy") == "ratio_policy"
        result[name] = {"standard": None if is_ratio or len(valid) != samples else float(np.std(valid, ddof=1)),
                        "interval": np.quantile(valid, [.025, .975]).tolist() if len(valid) else None,
                        "method": "joint_monte_carlo", "samples": samples, "seed": seed,
                        "assumption": "provided_covariance" if covariance is not None else "independent_except_shared_sources",
                        "moment_notice": "原始比值仅给样本分位数，不声明均值或方差存在" if is_ratio else ""}
    return result
