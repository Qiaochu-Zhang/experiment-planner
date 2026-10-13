import time

import pytest

from experiment_planner.engine.space import BatchRequest
from experiment_planner.worker.process import CalculationTask


def wait_for_result(task):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = task.poll()
        if result is not None:
            return result
        time.sleep(.02)
    pytest.fail("计算进程未按时返回")


@pytest.mark.parametrize("operation", ["generate", "analyze"])
def test_spawned_worker_returns_original_exception_and_traceback(service, operation):
    # Invalid input reaches the real child process without fitting a model.
    request = BatchRequest(n=0) if operation == "generate" else {"conditions": []}
    before = service.project.snapshot()
    task = CalculationTask(service.project, request, operation=operation)
    try:
        result = wait_for_result(task)
        assert "error" in result
        assert "ValidationError:" in result["diagnostic"]
        assert "Traceback (most recent call last):" in result["diagnostic"]
        assert "_run" in result["diagnostic"]
        assert result["error"] in result["diagnostic"]
        assert str(service.project.path) not in CalculationTask.active
        assert not task.lock.is_locked
        assert service.project.snapshot() == before
    finally:
        if str(service.project.path) in CalculationTask.active:
            task.cancel()


@pytest.mark.parametrize("operation", ["generate", "analyze"])
def test_abrupt_worker_exit_has_readable_exit_diagnostic_and_releases_lock(service, operation):
    before = service.project.snapshot()
    task = CalculationTask(service.project, {}, operation=operation)
    try:
        task.process.terminate()
        task.process.join(timeout=5)
        result = wait_for_result(task)
        assert "error" in result
        assert f"退出码：{task.process.exitcode}" in result["diagnostic"]
        assert f"进程 PID：{task.process.pid}" in result["diagnostic"]
        assert operation in result["diagnostic"]
        assert "无法提供原始异常堆栈" in result["diagnostic"]
        assert str(service.project.path) not in CalculationTask.active
        assert not task.lock.is_locked
        assert service.project.snapshot() == before
    finally:
        if str(service.project.path) in CalculationTask.active:
            task.cancel()
