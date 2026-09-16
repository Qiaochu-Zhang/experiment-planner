"""BoTorch-compatible probability models, with joint candidate covariance."""
import torch
from torch import nn
from botorch.models.model import Model, ModelList
from botorch.models import SingleTaskGP
from botorch.fit import fit_gpytorch_mll
from botorch.posteriors.gpytorch import GPyTorchPosterior
from botorch.posteriors.transformed import TransformedPosterior
from gpytorch.distributions import MultivariateNormal
from gpytorch.kernels import RBFKernel, MaternKernel, ScaleKernel
from gpytorch.mlls import ExactMarginalLogLikelihood

from experiment_planner.domain.errors import CapabilityError, ValidationError
from experiment_planner.knowledge.priors import check_capabilities

DTYPE = torch.double


class Encoder:
    def __init__(self, template):
        self.fields = [p for p in template.parameters if p.get("use_as_model_input", True)]
        self.indices = {}
        width = 0
        for p in self.fields:
            size = len(p["values"]) if p.get("value_type") == "category" else 1
            self.indices[p["name"]] = list(range(width, width + size))
            width += size
        self.width = width

    def encode(self, conditions):
        rows = []
        for condition in conditions:
            row = []
            for p in self.fields:
                value = condition[p["name"]]
                if p.get("value_type") == "category": row.extend(float(value == v) for v in p["values"])
                elif p.get("value_type") == "bool": row.append(float(value))
                else:
                    bounds = p.get("bounds", [min(p["values"]), max(p["values"])]) if "values" in p else p.get("bounds", [0, 1])
                    row.append((value - bounds[0]) / (bounds[1] - bounds[0]) if bounds[1] != bounds[0] else 0.0)
            rows.append(row)
        return torch.tensor(rows, dtype=DTYPE).reshape(len(rows), self.width)


class BayesianLinear(Model):
    def __init__(self, X, y, variance, prior_mean=None, prior_precision=None):
        super().__init__()
        phi = torch.cat([torch.ones_like(X[..., :1]), X], -1)
        mean = torch.zeros(phi.shape[-1], dtype=DTYPE) if prior_mean is None else prior_mean
        precision = torch.eye(phi.shape[-1], dtype=DTYPE) if prior_precision is None else prior_precision
        precision[0, 0] = max(precision[0, 0].item(), 1e-6)
        weights = variance.reshape(-1).clamp_min(1e-8).reciprocal()
        post_precision = precision + phi.T @ (weights[:, None] * phi)
        cov = torch.linalg.inv(post_precision)
        mu = cov @ (precision @ mean + phi.T @ (weights * y.reshape(-1)))
        self.register_buffer("coefficient_mean", mu)
        self.register_buffer("coefficient_covariance", cov)

    @property
    def num_outputs(self): return 1
    @property
    def batch_shape(self): return torch.Size()

    def posterior(self, X, output_indices=None, observation_noise=False, posterior_transform=None):
        if observation_noise is not False: raise CapabilityError("未来量测区间需要单独的未来噪声设置")
        phi = torch.cat([torch.ones_like(X[..., :1]), X], -1)
        mean = phi @ self.coefficient_mean
        cov = phi @ self.coefficient_covariance @ phi.transpose(-1, -2)
        cov = cov + torch.eye(X.shape[-2], dtype=X.dtype, device=X.device) * 1e-9
        posterior = GPyTorchPosterior(MultivariateNormal(mean, cov))
        return posterior_transform(posterior) if posterior_transform else posterior


class BernoulliLogit(BayesianLinear):
    def __init__(self, X, y):
        Model.__init__(self)
        phi = torch.cat([torch.ones_like(X[..., :1]), X], -1)
        beta = torch.zeros(phi.shape[-1], dtype=DTYPE, requires_grad=True)
        optimizer = torch.optim.LBFGS([beta], max_iter=70, line_search_fn="strong_wolfe")
        def loss_at(b):
            return torch.nn.functional.binary_cross_entropy_with_logits(phi @ b, y.reshape(-1), reduction="sum") + b.square().sum() / 2
        def closure():
            optimizer.zero_grad()
            loss = loss_at(beta)
            loss.backward()
            return loss
        optimizer.step(closure)
        covariance = torch.linalg.inv(torch.autograd.functional.hessian(loss_at, beta))
        self.register_buffer("coefficient_mean", beta.detach())
        self.register_buffer("coefficient_covariance", covariance.detach())

    def posterior(self, X, **kwargs):
        latent = super().posterior(X, **kwargs)
        return TransformedPosterior(latent, sample_transform=torch.sigmoid)


class ProjectedModel(Model):
    """Remove features per response, add a documented soft linear trend."""
    def __init__(self, inner, indices, trend):
        super().__init__()
        self.inner = inner
        self.indices = indices
        self.register_buffer("trend", trend)

    @property
    def num_outputs(self): return 1
    @property
    def batch_shape(self): return torch.Size()

    def posterior(self, X, output_indices=None, observation_noise=False, posterior_transform=None):
        reduced = X[..., self.indices] if self.indices else torch.zeros_like(X[..., :1])
        posterior = self.inner.posterior(reduced, observation_noise=observation_noise)
        if isinstance(self.inner, BernoulliLogit): return posterior
        mean = posterior.distribution.mean + self.trend[0] + X @ self.trend[1:]
        result = GPyTorchPosterior(MultivariateNormal(mean, posterior.distribution.lazy_covariance_matrix))
        return posterior_transform(result) if posterior_transform else result


def fit_models(template, experiments, preset, seed=0):
    check_capabilities(template, preset)
    source_usage={}
    def raw_dependencies(name):
        if name not in template.graph.formulas:return {name}
        return set().union(*(raw_dependencies(dep) for dep in template.graph.formulas[name].dependencies))
    for response in template.responses:
        for experiment in experiments:
            if experiment["status"] not in ("completed","partial"):continue
            for name in raw_dependencies(response["name"]):
                source=(experiment["observations"].get(name,{}).get("uncertainty") or {}).get("source")
                if source:source_usage.setdefault(source,set()).add((experiment["id"],response["name"]))
    if any(len(uses)>1 for uses in source_usage.values()):
        raise CapabilityError("共享误差来源跨实验或跨响应：当前独立似然未适配，不能静默忽略相关性")
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    encoder = Encoder(template)
    models, names, notices, datasets = [], [], [], {}
    for response in template.responses:
        name = response["name"]
        boolean = response.get("value_type") == "bool"
        records = []
        for e in experiments:
            if e["status"] not in ("completed", "partial"): continue
            cell = e["derived"].get(name) if name in e["derived"] else e["observations"].get(name)
            if cell is None or cell.get("value") is None or cell.get("status", "valid") != "valid": continue
            u = cell.get("uncertainty") or {}
            standard = u.get("standard")
            if "kind" in u:
                from experiment_planner.metrics.uncertainty import Uncertainty
                standard = Uncertainty(**u).standard()
            records.append((e["actual"], float(cell["value"]), standard))
        if len(records) < 2:
            raise CapabilityError(f"{name}：有效数据不足两条，预测尚不可用")
        X = encoder.encode([r[0] for r in records])
        y = torch.tensor([r[1] for r in records], dtype=DTYPE).unsqueeze(-1)
        known = [r[2] is not None for r in records]
        if any(known) and not all(known):
            raise CapabilityError(f"{name}：混合已知/未知观测噪声尚未适配，不能把未知误差当作零")
        variance = torch.tensor([r[2]**2 for r in records], dtype=DTYPE).unsqueeze(-1) if all(known) else None
        priors = [p for p in template.data.get("knowledge_priors", []) if p.get("enabled", True) and p["response"] == name]
        excluded = {i for p in priors if p["relation"] == "independent" for i in encoder.indices.get(p["input"], [])}
        active = [i for i in range(encoder.width) if i not in excluded]
        reduced = X[..., active] if active else torch.zeros_like(X[..., :1])
        trend = torch.zeros(encoder.width + 1, dtype=DTYPE)
        prior_mean = torch.zeros(reduced.shape[-1] + 1, dtype=DTYPE)
        prior_precision = torch.eye(reduced.shape[-1] + 1, dtype=DTYPE) * .01
        prior_precision[0, 0] = 1e-6
        for p in priors:
            if p["relation"] == "independent": continue
            field = next(f for f in encoder.fields if f["name"] == p["input"])
            lo, hi = field.get("bounds", [0, 1])
            index = encoder.indices[p["input"]][0]
            if index not in active: raise ValidationError("无关先验与系数先验冲突")
            coefficient = p.get("coefficient", 0)
            scaled = coefficient * (hi - lo)
            if preset == "bayesian_linear_v1":
                prior_mean[active.index(index)+1] = scaled
                prior_precision[active.index(index)+1, active.index(index)+1] = p["strength"]
                if p["relation"] == "proportional":
                    prior_mean[0] += coefficient * lo
                    prior_precision[0, 0] = p["strength"]
            else:
                # A fixed signed mean trend plus a GP residual is explicitly soft.
                trend[index+1] += scaled * p["strength"] / (1 + p["strength"])
                trend[0] += coefficient * lo * p["strength"] / (1 + p["strength"])
        if boolean:
            inner = BernoulliLogit(reduced, y)
            notices.append(f"{name}: Bernoulli-logit / Laplace；概率是参数后验采样统计")
        elif preset == "bayesian_linear_v1":
            if variance is None:
                # Explicit empirical residual estimate; never claim measurement error=0.
                phi = torch.cat([torch.ones_like(reduced[:, :1]), reduced], -1)
                beta = torch.linalg.lstsq(phi, y).solution
                mse = (y - phi @ beta).square().sum() / max(1, len(y)-phi.shape[-1])
                noise = max(mse.item(), y.var().item() * .01, 1e-6)
                variance = torch.full_like(y, noise)
                notices.append(f"{name}: 未提供误差；经验残差方差={noise:.8g}，少数据时有局限")
            inner = BayesianLinear(reduced, y, variance, prior_mean, prior_precision)
        else:
            kernel_cls = RBFKernel if preset == "gp_rbf_v1" else MaternKernel
            kernel = kernel_cls(ard_num_dims=reduced.shape[-1], **({"nu": 2.5} if kernel_cls is MaternKernel else {}))
            residual = y - (trend[0] + X @ trend[1:]).unsqueeze(-1)
            inner = SingleTaskGP(reduced, residual, train_Yvar=variance, covar_module=ScaleKernel(kernel))
            fit_gpytorch_mll(ExactMarginalLogLikelihood(inner.likelihood, inner), optimizer_kwargs={"options": {"maxiter": 100}})
            notices.append(f"{name}: {'已提供观测方差 u²' if variance is not None else 'GP 估计未知噪声'}")
        models.append(ProjectedModel(inner, active, trend))
        names.append(name)
        datasets[name] = {"count": len(records), "features": [p["name"] for p in encoder.fields if any(i in active for i in encoder.indices[p["name"]])], "conditions": [r[0] for r in records]}
    return ModelList(*models), encoder, names, datasets, ["各基础响应条件独立；同一响应保留候选点间相关性", "区间表示潜在响应，不包含未提供的未来测量误差", *notices]
