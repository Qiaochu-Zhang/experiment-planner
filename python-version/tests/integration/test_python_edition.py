"""Verify the standalone source delivery and its new public entry points."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from experiment_planner.application.synthetic import synthetic_records
from experiment_planner.domain.errors import ValidationError
from experiment_planner.worker.process import CalculationTask


def test_launchers_work_without_parent_repository(tmp_path):
    root = Path(__file__).resolve().parents[2]
    standalone = tmp_path / "独立 Python project"
    standalone.mkdir()
    shutil.copytree(root / "src/experiment_planner", standalone / "src/experiment_planner",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("main.py", "cli.py"):
        shutil.copy2(root / name, standalone / name)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ""}

    def run(name, *args, expected=0):
        result = subprocess.run([sys.executable, str(standalone / name), *map(str, args)],
                                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90)
        assert result.returncode == expected, result.stderr
        return result

    project = tmp_path / "sample.sqlite"
    run("main.py", "--demo", project)
    rows = json.loads(run("cli.py", "records", project).stdout)
    assert len(rows) == 12
    # A repeat invocation must not overwrite the project.
    run("cli.py", "create", project, expected=1)
    run("main.py", "--smoke", "--project", project)
    template_file = tmp_path / "template.json"
    run("cli.py", "builtin-template", template_file)
    template = json.loads(template_file.read_text())
    assert len(template["parameters"]) == 8
    record = {"conditions": rows[0]["actual"], "observations": {}, "status": "partial", "note": "CLI revision"}
    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps(record), encoding="utf-8")
    updated = json.loads(run("cli.py", "record", project, record_file, "--id", 1).stdout)
    assert updated["status"] == "partial" and updated["note"] == "CLI revision"
    assert json.loads(run("cli.py", "history", project).stdout)[-1]["old_payload"]


@pytest.mark.model
def test_analysis_worker_does_not_write_project(service, tmp_path):
    p = service.project
    for record in synthetic_records(p.template, count=6):
        service.add_record(**record)
    before = p.snapshot()
    path = tmp_path / "trend.png"
    task = CalculationTask(p, {
        "conditions": [p.experiments()[0]["actual"]], "model": "bayesian_linear_v1",
        "plot_path": str(path), "variables": ["cl2_sccm"], "metric": "sio2_loss_nm", "points": 4,
    }, operation="analyze")
    try:
        with pytest.raises(ValidationError):
            CalculationTask(p, {}, operation="analyze")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = task.poll()
            if result is not None:
                break
            time.sleep(.05)
        else:
            pytest.fail("analysis worker timed out")
    finally:
        if str(p.path) in CalculationTask.active:
            task.cancel()
    assert "error" not in result, result
    assert result["result"]["revision"] == before["revision"]
    assert result["result"]["predictions"][0]["sio2_loss_nm"]["quantiles"]
    assert path.stat().st_size > 1000
    assert p.snapshot() == before


@pytest.mark.gui
def test_extended_desktop_requests_and_cleanup(service):
    from PySide6.QtWidgets import QApplication
    from experiment_planner.ui.desktop import PythonWindow
    from experiment_planner.storage.project import Project
    app = QApplication.instance() or QApplication([])
    for record in synthetic_records(service.project.template, count=2):
        service.add_record(**record)
    window = PythonWindow()
    window.set_project(Project(service.project.path))
    try:
        assert window.tabs.count() == 4
        window.table.selectRow(0)
        window.copy_conditions()
        assert json.loads(window.conditions.toPlainText()) == service.project.experiment(1)["actual"]
        window.mode.setCurrentIndex(window.mode.findData("cross"))
        window.cross_values.setText('{"cl2_sccm": 20, "rf_w": 30}')
        window.baseline.setCurrentIndex(window.baseline.findData(1))
        request = window.batch_request()
        assert request.cross_values == {"cl2_sccm": 20, "rf_w": 30}
        assert request.baseline_id == 1 and request.repeat_baseline
        window.close_project()
        assert not window.conditions.toPlainText()
        assert not window.template_view.toPlainText()
    finally:
        window.close()
        app.processEvents()
