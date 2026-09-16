"""Synthetic create → fit → recommend → backfill → plot → export → restore.

Run in PyCharm or: python examples/workflow.py --output local-data/example
The output directory must not already exist. No real experimental data is used.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    from experiment_planner.application.analysis import analyze
    from experiment_planner.application.service import PlannerService
    from experiment_planner.application.synthetic import synthetic_records
    from experiment_planner.engine.planner import generate
    from experiment_planner.engine.space import BatchRequest
    from experiment_planner.io.exchange import export_records
    from experiment_planner.storage.project import Project

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("local-data/example"))
    args = parser.parse_args()
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with Project.create(destination / "project.sqlite", "合成 Python 示例") as project:
        service = PlannerService(project)
        # Demonstration setting only. The user must choose their own strategy
        # and epsilon for an actual experiment; this is not a machine default.
        service.update_template(project.template.revised(ratio_policy={
            **project.template.data["ratio_policy"], "mode": "stabilized", "epsilon_nm": 1.0,
        }))
        for record in synthetic_records(project.template, count=8):
            service.add_record(**record)
        request = BatchRequest(n=2, mode="single", baseline_id=1,
                               variables=["cl2_sccm"], model="bayesian_linear_v1", pool_size=16)
        batch = generate(project.snapshot(), request)
        bid, ids = service.commit_batch(batch)
        first = project.experiment(ids[0])
        condition = first["actual"]
        # Explicitly synthetic measurements, matching synthetic_records().
        a = 5 + .2 * condition["cl2_sccm"] + .025 * condition["icp_w"] + .04 * condition["etch_time_s"]
        b = 1 + .06 * condition["rf_w"] + .03 * condition["bcl3_sccm"]
        measurements = dict(sio2_initial_nm=150., sio2_remaining_nm=150.-a,
                            sin_initial_nm=100., sin_remaining_nm=100.-b)
        service.revise_record(ids[0], condition, {
            k: {"value": v, "unit": "nm", "uncertainty": {"kind": "std", "amount": .2}}
            for k, v in measurements.items()
        }, note="合成回填；不代表真实机台")
        result = analyze(project.snapshot(), {
            "conditions": [condition], "model": "bayesian_linear_v1",
            "plot_path": str(destination / "trend.png"), "variables": ["cl2_sccm"],
            "metric": "sio2_loss_nm", "points": 10,
        })
        for name in ("records.csv", "records.xlsx", "snapshot.json"):
            export_records(project, destination / name)
        project.template.write(destination / "template.json")
        project.backup(destination / "backup.sqlite")
        saved = project.experiments()
        (destination / "prediction.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with Project(destination / "backup.sqlite") as restored:
        assert restored.experiments() == saved
    print(f"Completed synthetic batch {bid}, experiments {ids}. Files: {destination}")


if __name__ == "__main__":
    main()
