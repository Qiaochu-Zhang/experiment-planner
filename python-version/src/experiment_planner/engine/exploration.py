"""Explicit uncertainty bonus and dedicated feasible, diverse exploration."""
import math

import torch

from experiment_planner.domain.errors import CapabilityError


def candidate_statistics(model, X, objectives, scales, seed):
    uncertainty, feasibility = [], []
    with torch.random.fork_rng(), torch.no_grad():
        torch.manual_seed(seed)
        for chunk in X.split(32):
            # Independent batch marginals avoid a pool_size² covariance matrix.
            draws = model.posterior(chunk.unsqueeze(-2)).rsample(torch.Size([128]))
            values = objectives.transformed(draws)
            if not torch.isfinite(values).all():
                raise CapabilityError("探索评分出现非有限目标样本，请检查比值策略和公式")
            relative = values.std(0).squeeze(-2) / scales
            uncertainty.append(relative.mean(-1))
            feasible = torch.ones(draws.shape[:-1], dtype=torch.bool, device=draws.device)
            for constraint in objectives.constraints():
                feasible &= constraint(draws) <= 0
            feasibility.append(feasible.double().mean(0).squeeze(-1))
    return torch.cat(uncertainty), torch.cat(feasibility)


def adjusted_scores(log_acquisition, uncertainty, feasibility, strength):
    # strength=0 is exactly the previous BO selection. Positive strengths favor
    # larger standardized posterior uncertainty, tempered by feasibility.
    return log_acquisition + strength * feasibility * torch.log1p(uncertainty)


def dedicated_scores(X, uncertainty, feasibility, pending=None):
    score = feasibility * torch.log1p(uncertainty)
    if pending is not None and len(pending):
        distance = torch.cdist(X, pending).amin(-1) / math.sqrt(X.shape[-1])
        score = score * distance.clamp(0, 1)
    return score
