"""Rebuild Ax tracking from business records; no model pickle is required."""
import math
import pandas as pd
from ax.core.arm import Arm
from ax.core.data import Data
from ax.core.experiment import Experiment
from ax.core.metric import Metric
from ax.core.parameter import ChoiceParameter, FixedParameter, ParameterType, RangeParameter
from ax.core.search_space import SearchSpace
from ax.storage.json_store.encoder import object_to_json


def rebuild(template, records, name="local_experiment"):
    parameters = []
    for p in template.parameters:
        kind = {"float": ParameterType.FLOAT, "int": ParameterType.INT, "category": ParameterType.STRING, "bool": ParameterType.BOOL}[p.get("value_type", "float")]
        if "fixed_value" in p: parameter = FixedParameter(p["name"], kind, p["fixed_value"])
        elif "values" in p or kind == ParameterType.BOOL:
            values = p.get("values", [False, True])
            parameter = FixedParameter(p["name"], kind, values[0]) if len(values) == 1 else ChoiceParameter(p["name"], kind, values, is_ordered=kind in (ParameterType.FLOAT, ParameterType.INT), sort_values=False)
        else: parameter = RangeParameter(p["name"], kind, *p["bounds"])
        parameters.append(parameter)
    experiment = Experiment(search_space=SearchSpace(parameters), name=name, tracking_metrics=[Metric(f["name"]) for f in template.responses], is_test=True)
    rows, mapping = [], {}
    for record in records:
        trial = experiment.new_trial().add_arm(Arm(parameters=record["actual"], name=f"experiment_{record['id']}"))
        mapping[str(record["id"])] = trial.index
        if record["status"] in ("completed", "partial"):
            trial.mark_running(no_runner_required=True)
            for response in template.responses:
                metric = response["name"]
                cell = record["derived"].get(metric, record["observations"].get(metric))
                if not cell or cell.get("value") is None or cell.get("status", "valid") != "valid": continue
                uncertainty = cell.get("uncertainty") or {}
                sem = uncertainty.get("standard")
                if "kind" in uncertainty:
                    from experiment_planner.metrics.uncertainty import Uncertainty
                    sem = Uncertainty(**uncertainty).standard()
                rows.append({"trial_index": trial.index, "arm_name": trial.arm.name, "metric_name": metric, "metric_signature": experiment.metrics[metric].signature, "mean": float(cell["value"]), "sem": sem if sem is not None else float("nan")})
            if record["status"] == "completed": trial.mark_completed()
        elif record["status"] == "failed":
            trial.mark_running(no_runner_required=True).mark_failed()
        elif record["status"] == "cancelled": trial.mark_abandoned()
        elif record["status"] == "running": trial.mark_running(no_runner_required=True)
    if rows: experiment.attach_data(Data(df=pd.DataFrame(rows)))
    return experiment, mapping


def snapshot(experiment, mapping):
    def finite_json(value):
        if isinstance(value, float) and not math.isfinite(value): return None
        if isinstance(value, list): return [finite_json(v) for v in value]
        if isinstance(value, dict): return {k: finite_json(v) for k,v in value.items()}
        return value
    return {"experiment": finite_json(object_to_json(experiment)), "business_id_to_trial": mapping,
            "restore_policy": "rebuild_from_business_records", "role": "Ax experiment tracking; custom BoTorch acquisition bridge"}
