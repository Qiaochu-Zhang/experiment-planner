"""Conditional input sampling, predictive mixtures and expected-objective BO."""
import torch
from botorch.models.model import Model
from botorch.posteriors.posterior import Posterior
from botorch.sampling.base import MCSampler
from botorch.sampling.get_sampler import GetSampler, get_sampler
from botorch.acquisition.objective import GenericMCObjective
from botorch.acquisition.multi_objective.objective import GenericMCMultiOutputObjective

from experiment_planner.domain.errors import CapabilityError
from experiment_planner.domain.input_uncertainty import selected_inputs


class InputDistribution:
    def __init__(self, template, encoder, seed=0):
        self.template, self.encoder, self.seed = template, encoder, seed
        self.fields = selected_inputs(template)
        self.n_w = template.data.get("input_uncertainty", {}).get("samples", 16)

    def expand(self, X):
        """Return ... x q x n_w x d draws; do not round physical fluctuations."""
        flat = X.reshape(-1, X.shape[-1])
        constraints = self.template.data.get("input_constraints", [])
        # Only encoded fields can be evaluated here. A non-model input's known
        # nominal contribution is unavailable to BO, so refuse such constraints.
        for constraint in constraints:
            if any(name not in self.encoder.indices or len(self.encoder.indices[name]) != 1
                   for name in constraint["coefficients"]):
                raise CapabilityError("输入不确定度与线性约束组合时，约束中的输入须全部参与数值模型")
        engine = torch.quasirandom.SobolEngine(len(self.fields), scramble=True, seed=self.seed)
        size = self.n_w
        while True:
            u = engine.draw(size, dtype=X.dtype).to(X.device).clamp(1e-12, 1-1e-12)
            expanded = flat[:, None, :].expand(-1, size, -1).clone()
            for j, field in enumerate(self.fields):
                index = self.encoder.indices[field["name"]][0]
                center = flat[:, index, None]
                if ((center < 0) | (center > 1)).any():
                    raise CapabilityError(f"{field['name']}：输入不确定度采样的中心超出模板范围，请核对历史输入与当前范围")
                amount = field["input_uncertainty"]["amount"] / (field["bounds"][1] - field["bounds"][0])
                if field["input_uncertainty"].get("kind", "std") == "std":
                    lo = torch.special.ndtr(-center / amount)
                    hi = torch.special.ndtr((1-center) / amount)
                    value = center + amount * torch.special.ndtri(lo + (hi-lo)*u[:, j])
                else:
                    lo, hi = (center-amount).clamp_min(0), (center+amount).clamp_max(1)
                    value = lo + (hi-lo)*u[:, j]
                if not torch.isfinite(value).all():
                    raise CapabilityError(f"{field['name']}：输入不确定度采样发生数值溢出，请检查单位与误差尺度")
                # Inverse-CDF sampling already enforces bounds. This only removes
                # floating-point roundoff, not tails of an unbounded distribution.
                expanded[..., index] = value.clamp(0, 1)
            valid = torch.ones(expanded.shape[:-1], dtype=torch.bool, device=X.device)
            for constraint in constraints:
                lhs = torch.zeros_like(valid, dtype=X.dtype)
                for name, coefficient in constraint["coefficients"].items():
                    field = next(p for p in self.encoder.fields if p["name"] == name)
                    lo, hi = (field.get("bounds", [min(field["values"]), max(field["values"])])
                              if "values" in field else field.get("bounds", [0, 1]))
                    native = lo + (hi-lo)*expanded[..., self.encoder.indices[name][0]]
                    lhs = lhs + coefficient * native
                valid &= lhs <= constraint["rhs"] + 1e-10 if constraint["op"] == "<=" else lhs >= constraint["rhs"] - 1e-10
            if (valid.sum(-1) >= self.n_w).all():
                indices = torch.arange(size, device=X.device).expand_as(valid)
                selected = indices.masked_fill(~valid, size).sort(-1).values[:, :self.n_w]
                result = expanded.gather(1, selected[..., None].expand(-1, -1, X.shape[-1]))
                return result.reshape(*X.shape[:-1], self.n_w, X.shape[-1])
            if size >= self.n_w * 128:
                row = int((valid.sum(-1) < self.n_w).nonzero()[0])
                raise CapabilityError(f"输入不确定度：第 {row+1} 个条件在范围及线性约束内不足 {self.n_w} 个有效扰动样本；"
                                      "约束可能过紧或无可用体积，请调整不确定度/约束，或关闭此功能后比较。")
            size *= 2
            engine.reset()


class RiskPosterior(Posterior):
    """Posterior of expected utilities, preserving joint function uncertainty."""
    def __init__(self, raw, transform, n_w, outputs, seed):
        self.raw, self.transform, self.n_w, self.outputs, self.seed = raw, transform, n_w, outputs, seed
        self._cached_moments = None

    @property
    def device(self): return self.raw.device
    @property
    def dtype(self): return self.raw.dtype

    def _extended_shape(self, sample_shape=torch.Size()):
        shape = self.raw._extended_shape(sample_shape)
        return shape[:-2] + torch.Size([shape[-2] // self.n_w, self.outputs])

    def rsample(self, sample_shape=None):
        return self.transform(self.raw.rsample(sample_shape))

    def _moments(self):
        if self._cached_moments is None:
            with torch.random.fork_rng(), torch.no_grad():
                torch.manual_seed(self.seed)
                samples = self.rsample(torch.Size([128]))
                self._cached_moments = samples.mean(0), samples.var(0)
        return self._cached_moments

    @property
    def mean(self): return self._moments()[0]
    @property
    def variance(self): return self._moments()[1]


class RiskSampler(MCSampler):
    def __init__(self, posterior, sample_shape, seed=None):
        super().__init__(sample_shape, seed)
        self.inner = get_sampler(posterior.raw, sample_shape, seed=seed)

    def forward(self, posterior):
        return posterior.transform(self.inner(posterior.raw))

    def _update_base_samples(self, posterior, base_sampler):
        self.inner._update_base_samples(posterior.raw, base_sampler.inner)


@GetSampler.register(RiskPosterior)
def risk_sampler(posterior, sample_shape, *, seed=None):
    return RiskSampler(posterior, sample_shape, seed)


class ExpectedInputModel(Model):
    def __init__(self, model, distribution, objectives):
        super().__init__()
        self.model, self.distribution, self.objectives = model, distribution, objectives
        self.constraint_functions = objectives.constraints()
        self.utility_count = len(objectives.objectives)

    @property
    def num_outputs(self): return self.utility_count + len(self.constraint_functions)
    @property
    def batch_shape(self): return self.model.batch_shape

    def transform(self, samples):
        n_w = self.distribution.n_w
        directed = self.objectives.transformed(samples)
        if not torch.isfinite(directed).all():
            raise CapabilityError("输入扰动后的目标出现非有限样本，请检查比值策略、公式及不确定度")
        utilities = directed.reshape(*directed.shape[:-2], -1, n_w, self.utility_count).mean(-2)
        constraints = [fn(samples).reshape(*samples.shape[:-2], -1, n_w).amax(-1)
                       for fn in self.constraint_functions]
        return torch.cat([utilities, *[c.unsqueeze(-1) for c in constraints]], -1)

    def posterior(self, X, output_indices=None, observation_noise=False, posterior_transform=None):
        if output_indices is not None or posterior_transform is not None or observation_noise is not False:
            raise CapabilityError("输入不确定度的稳健目标后验不支持额外后验变换或未来测量噪声")
        expanded = self.distribution.expand(X).flatten(-3, -2)
        return RiskPosterior(self.model.posterior(expanded), self.transform, self.distribution.n_w,
                             self.num_outputs, self.distribution.seed)


class ExpectedObjectives:
    def __init__(self, original):
        self.original = original
        self.objectives = original.objectives
        self.m = len(self.objectives)

    def transformed(self, samples, X=None): return samples[..., :self.m]

    def scalar(self, samples, X=None):
        values = self.transformed(samples)
        config = self.original.template.data["optimization"]
        if config["mode"] == "single": return values.squeeze(-1)
        return (values * values.new_tensor(config["weights"]) / values.new_tensor(config["scales"])).sum(-1)

    def botorch_objective(self):
        return (GenericMCMultiOutputObjective(self.transformed) if self.original.template.data["optimization"]["mode"] == "pareto"
                else GenericMCObjective(self.scalar))

    def constraints(self):
        return [lambda samples, i=self.m+j: samples[..., i] for j in range(len(self.original.constraints()))]
