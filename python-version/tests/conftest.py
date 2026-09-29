import pytest
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project
from experiment_planner.application.service import PlannerService


@pytest.fixture
def template(): return Template.builtin()


@pytest.fixture
def conditions(template): return {p["name"]: sum(p["bounds"])/2 for p in template.parameters}


@pytest.fixture
def measurements(): return {"sio2_initial_nm": 100., "sio2_remaining_nm": 90., "sin_initial_nm": 100., "sin_remaining_nm": 99.}


@pytest.fixture
def service(tmp_path):
    project = Project.create(tmp_path/"模拟项目"/"project.sqlite", "合成测试")
    yield PlannerService(project)
    project.close()


@pytest.fixture
def legacy_template(template):
    data = template.data
    data["template_version"] = 1
    data["derived_metrics"][-1].update(name="selectivity_abs", label="比值绝对值", expression="abs(sio2_loss_nm / sin_loss_nm)")
    data["objectives"][0]["transform"] = "abs"
    data["objectives"][2]["metric"] = "selectivity_abs"
    data["ratio_policy"]["original_metric"] = "selectivity_abs"
    return Template(data)


@pytest.fixture(autouse=True)
def isolated_desktop_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))


@pytest.fixture(scope="session")
def qt_application():
    """One Qt application must outlive every widget in the test process."""
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    yield app
    gc.collect()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def keep_gui_application_alive(request):
    if request.node.get_closest_marker("gui"):
        request.getfixturevalue("qt_application")
