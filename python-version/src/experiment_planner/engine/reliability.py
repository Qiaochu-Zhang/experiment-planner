"""Learn a common GP noise scale with per-observation relative precision."""
from gpytorch.likelihoods.noise_models import HomoskedasticNoise
from linear_operator.operators import DiagLinearOperator
from botorch.models.utils.gpytorch_modules import get_gaussian_likelihood_with_lognormal_prior

from experiment_planner.domain.errors import CapabilityError


class RelativePrecisionNoise(HomoskedasticNoise):
    def __init__(self, weights, original):
        super().__init__(noise_prior=original.noise_prior,
                         noise_constraint=original.raw_noise_constraint)
        self.initialize(noise=original.noise.detach().clone())
        self.register_buffer("precision_weights", weights.reshape(-1))

    def forward(self, *params, shape=None, **kwargs):
        base = super().forward(*params, shape=shape, **kwargs)
        if "noise" in kwargs:
            return base
        if base.shape[-1] != self.precision_weights.numel():
            raise CapabilityError("批次可信度模型仅定义历史观测噪声；未来量测噪声须另行提供")
        return DiagLinearOperator(base.diagonal(dim1=-2, dim2=-1) / self.precision_weights)


def weighted_gaussian_likelihood(weights):
    likelihood = get_gaussian_likelihood_with_lognormal_prior()
    likelihood.noise_covar = RelativePrecisionNoise(weights, likelihood.noise_covar)
    return likelihood
