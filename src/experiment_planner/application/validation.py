"""Packaged executable smoke loop using explicitly synthetic data only."""
import json
import time
from pathlib import Path


def self_test(directory):
    from experiment_planner.application.service import PlannerService
    from experiment_planner.application.synthetic import synthetic_records
    from experiment_planner.storage.project import Project
    from experiment_planner.engine.planner import generate
    from experiment_planner.engine.space import BatchRequest
    from experiment_planner.worker.process import CalculationTask
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    evidence={"data":"synthetic only","stages":[]}
    with Project.create(directory/"project.sqlite","合成冻结验证") as project:
        service=PlannerService(project)
        service.update_template(project.template.revised(ratio_policy={**project.template.data["ratio_policy"],"mode":"stabilized","epsilon_nm":1.}))
        for row in synthetic_records(project.template,6):service.add_record(**row)
        for preset in ("gp_rbf_v1","gp_matern25_v1","bayesian_linear_v1"):
            request=BatchRequest(n=1,mode="single",baseline_id=1,variables=["cl2_sccm"],pool_size=6,model=preset)
            batch=generate(project.snapshot(),request)
            assert batch["stage"]=="model_driven" and len(batch["candidates"])==1
            service.commit_batch(batch)
            evidence["stages"].append(preset)
        task=CalculationTask(project,BatchRequest(n=1,mode="double",baseline_id=1,variables=["rf_w","cl2_sccm"],pool_size=6,model="bayesian_linear_v1"))
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            result=task.poll()
            if result is not None:break
            time.sleep(.1)
        else:
            task.cancel();raise RuntimeError("spawn 计算超时")
        if "error" in result:raise RuntimeError(result["error"])
        service.commit_batch(result["result"])
        evidence["stages"].append("spawn_batch")
        saved=project.experiments()
        project.backup(directory/"backup.sqlite")
    with Project(directory/"backup.sqlite") as restored:
        assert restored.experiments()==saved
        evidence["stages"].append("sqlite_restore")
    (directory/"evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    return evidence
