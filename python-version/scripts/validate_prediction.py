"""固定种子留出评估；全部为合成数据，不代表机台物理规律。

从 python-version 执行：python scripts/validate_prediction.py --output result.json
每次拟合都经实际录入/SQLite 快照/analyze 路径；测试真值从不交给模型。
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from experiment_planner.application.analysis import analyze
from experiment_planner.application.service import PlannerService
from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project
import experiment_planner.engine.models as model_module

SEEDS = [11, 23, 37, 51, 79]
PRESETS = ["gp_rbf_v1", "gp_matern25_v1", "bayesian_linear_v1"]
SCENARIOS = {
    "linear_64": {"train": 64, "train_range": [0.0, 1.0], "test_range": [0.0, 1.0]},
    "linear_12": {"train": 12, "train_range": [0.0, 1.0], "test_range": [0.0, 1.0]},
    "nonlinear_64": {"train": 64, "train_range": [0.0, 1.0], "test_range": [0.0, 1.0]},
    "extrapolation_64": {"train": 64, "train_range": [0.1, 0.55], "test_range": [0.7, 0.95]},
}
RESPONSES = ["sio2_loss_nm", "sin_loss_nm"]


def truth(x, scenario):
    """独立解析真值；x 是模板参数顺序的归一化坐标。"""
    a = 10 + 20*x[:, 0] + 35*x[:, 3] + 12*x[:, 7]
    b = 1 + 6*x[:, 4] + 3*x[:, 1]
    if scenario == "nonlinear_64":
        a = a + 12*np.sin(2*np.pi*x[:, 0]) + 16*(x[:, 3]-0.5)*(x[:, 7]-0.5)
        b = b + 2*np.sin(2*np.pi*x[:, 4]) + 2*(x[:, 1]-0.5)**2
    return np.column_stack([a, b])


def conditions(template, x):
    return [{p["name"]: float(p["bounds"][0] + v*(p["bounds"][1]-p["bounds"][0]))
             for p, v in zip(template.parameters, row)} for row in x]


def metrics(actual, predicted, intervals, baseline):
    actual, predicted, intervals = map(np.asarray, (actual, predicted, intervals))
    mse = np.mean((predicted-actual)**2)
    baseline_mse = np.mean((np.asarray(baseline)-actual)**2)
    rmse = float(np.sqrt(mse))
    nrmse = float(rmse / np.std(actual))
    skill = float(1-mse/baseline_mse)
    coverage = float(np.mean((intervals[:, 0] <= actual) & (actual <= intervals[:, 2])))
    return {"mae": float(np.mean(np.abs(predicted-actual))), "rmse": rmse,
            "nrmse": nrmse, "r2": float(1-mse/np.var(actual)),
            "baseline_rmse": float(np.sqrt(baseline_mse)), "skill": skill,
            "coverage95": coverage, "interval_width": float(np.mean(intervals[:, 2]-intervals[:, 0])),
            "screen_pass": bool(skill > 0 and nrmse <= 0.25 and coverage >= 0.85)}


def summarize(points):
    result = {}
    for name in RESPONSES + ["raw_selectivity_abs", "selectivity_stable"]:
        actual = [p["truth"][name] for p in points]
        # 原始比值无均值，用中位数评估；其他指标沿用应用显示均值。
        predicted = [p["prediction"][name]["quantiles"][1] if name == "raw_selectivity_abs"
                     else p["prediction"][name]["mean"] for p in points]
        result[name] = metrics(actual, predicted,
                               [p["prediction"][name]["quantiles"] for p in points],
                               [p["baseline"][name] for p in points])
    return result


def run(output):
    started = time.monotonic()
    template = Template.builtin()
    template = template.revised(ratio_policy={**template.data["ratio_policy"],
                                              "mode": "stabilized", "epsilon_nm": 1.0})
    evidence = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "data": "synthetic_only",
        "python": sys.version, "platform": platform.platform(),
        "module_file": str(Path(model_module.__file__).resolve()),
        "versions": {p: importlib.metadata.version(p) for p in
                     ("numpy", "scipy", "torch", "gpytorch", "botorch", "ax-platform")},
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [Path(__file__), *sorted((ROOT / "src").rglob("*.py"))]},
        "config": {"seeds": SEEDS, "models": PRESETS, "scenarios": SCENARIOS,
                   "test_count_per_run": 64, "posterior_samples": 512, "thickness_std_nm": 0.2,
                   "truth": "See truth() in scripts/validate_prediction.py; x is normalized to template bounds",
                   "screen": "skill > 0 and NRMSE <= 0.25 and latent coverage95 >= 0.85"},
        "runs": [], "aggregate": [], "errors": [],
    }
    with tempfile.TemporaryDirectory(prefix="prediction-audit-") as directory:
        for scenario, config in SCENARIOS.items():
            for seed in SEEDS:
                streams = np.random.SeedSequence(seed).spawn(3)
                train_rng, test_rng, noise_rng = [np.random.default_rng(s) for s in streams]
                train_x = train_rng.uniform(*config["train_range"], size=(config["train"], 8))
                test_x = test_rng.uniform(*config["test_range"], size=(64, 8))
                train_c, test_c = conditions(template, train_x), conditions(template, test_x)
                assert not set(map(tuple, train_x)) & set(map(tuple, test_x))
                train_y, test_y = truth(train_x, scenario), truth(test_x, scenario)
                observations = []
                for a, b in train_y:
                    raw = np.array([150.0, 150.0-a, 100.0, 100.0-b]) + noise_rng.normal(0, 0.2, 4)
                    observations.append({name: {"value": float(v), "uncertainty": {"kind": "std", "amount": 0.2}}
                                         for name, v in zip(["sio2_initial_nm", "sio2_remaining_nm",
                                                             "sin_initial_nm", "sin_remaining_nm"], raw)})
                database = Path(directory) / f"{scenario}-{seed}.sqlite"
                with Project.create(database, "独立合成预测留出验证", template) as project:
                    service = PlannerService(project)
                    for c, obs in zip(train_c, observations):
                        service.add_record(c, obs, note="合成验证，不代表机台物理规律")
                    snapshot = project.snapshot()
                observed_y = np.array([[e["derived"][n]["value"] for n in RESPONSES]
                                       for e in snapshot["experiments"]])
                baseline = dict(zip(RESPONSES, observed_y.mean(0).tolist()))
                baseline["raw_selectivity_abs"] = float(np.median(np.abs(observed_y[:, 0]/observed_y[:, 1])))
                baseline["selectivity_stable"] = float(np.mean(np.abs(observed_y[:, 0])/np.maximum(np.abs(observed_y[:, 1]), 1)))
                for preset in PRESETS:
                    print(f"{scenario} seed={seed} {preset}", flush=True)
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        try:
                            result = analyze(snapshot, {"conditions": test_c, "model": preset, "seed": seed})
                            assert result["revision"] == snapshot["revision"]
                            assert len(result["predictions"]) == len(test_c)
                            points = []
                            for c, (a, b), prediction in zip(test_c, test_y, result["predictions"]):
                                assert prediction["samples"] == 512
                                truths = dict(zip(RESPONSES, [float(a), float(b)]))
                                truths.update(raw_selectivity_abs=float(abs(a/b)),
                                              selectivity_stable=float(abs(a)/max(abs(b), 1)))
                                points.append({"conditions": c, "truth": truths, "baseline": baseline,
                                               "prediction": {n: prediction[n] for n in truths}})
                            run_result = {"scenario": scenario, "seed": seed, "model": preset,
                                          "metrics": summarize(points), "notices": result["notices"],
                                          "points": points,
                                          "training_observations": [{"conditions": c, "observations": o}
                                                                    for c, o in zip(train_c, observations)]}
                        except Exception as exc:
                            evidence["errors"].append({"scenario": scenario, "seed": seed, "model": preset,
                                                       "error": f"{type(exc).__name__}: {exc}"})
                            print(f"FAILED: {type(exc).__name__}: {exc}", flush=True)
                            continue
                    counts = Counter((w.category.__name__, str(w.message)) for w in caught)
                    run_result["warnings"] = [{"category": category, "message": message, "count": count}
                                              for (category, message), count in sorted(counts.items())]
                    evidence["runs"].append(run_result)
        for scenario in SCENARIOS:
            for preset in PRESETS:
                runs = [r for r in evidence["runs"] if r["scenario"] == scenario and r["model"] == preset]
                if not runs:
                    continue
                evidence["aggregate"].append({"scenario": scenario, "model": preset, "runs": len(runs),
                                               "metrics": summarize([p for r in runs for p in r["points"]]),
                                               "per_seed_coverage95": {n: [r["metrics"][n]["coverage95"] for r in runs]
                                                                        for n in RESPONSES}})
    evidence["elapsed_seconds"] = time.monotonic()-started
    output.parent.mkdir(parents=True, exist_ok=True)
    # 排除 NaN/Infinity，避免把数值异常藏入看似成功的证据。
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(f"Saved {output}: {len(evidence['runs'])} fits, {len(evidence['errors'])} errors", flush=True)
    return bool(evidence["errors"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("输出文件已存在，请选择新文件，保留原始证据")
    raise SystemExit(run(args.output))
