import pytest
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
