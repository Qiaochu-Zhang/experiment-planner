import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.diagnostics import FailureDialog


pytestmark = pytest.mark.gui


@pytest.fixture
def window(qt_application, tmp_path):
    window = PythonWindow()
    window.set_project(Project.create(tmp_path / "diagnostics.sqlite", "诊断测试"))
    window.show()
    qt_application.processEvents()
    yield window
    window.close()


def inspect_next_failure():
    """Click real modal controls; make assertions outside Qt's event callbacks."""
    observed = {}

    def inspect():
        dialog = QApplication.activeModalWidget()
        try:
            observed["dialog_type"] = type(dialog)
            observed["title"] = dialog.windowTitle()
            observed["initially_expanded"] = dialog.details.isVisible()
            if not dialog.details.isVisible():
                observed["button"] = dialog.details_button.text()
                QTest.mouseClick(dialog.details_button, Qt.MouseButton.LeftButton)
            observed["visible"] = dialog.details.isVisible()
            observed["text"] = dialog.details.toPlainText()
            QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
            observed["copied"] = QApplication.clipboard().text()
        except Exception as exc:
            observed["callback_error"] = repr(exc)
        finally:
            if dialog:
                dialog.accept()

    QTimer.singleShot(0, inspect)
    return observed


def assert_diagnostic(observed, expected):
    assert "callback_error" not in observed, observed
    assert observed["dialog_type"] is FailureDialog
    assert observed["visible"]
    assert expected in observed["text"]
    assert observed["copied"] == observed["text"]


class CompletedTask:
    def __init__(self, result):
        self.result = result

    def poll(self):
        return self.result


@pytest.mark.parametrize("operation", ["generate", "analyze"])
def test_worker_failure_is_readable_copyable_and_reopenable(window, operation):
    before = window.require_project().snapshot()
    diagnostic = "Traceback (most recent call last):\n  模型拟合位置\nRuntimeError: 原始错误 <矩阵> & 参数\n"
    payload = {"error": "计算或操作未完成", "diagnostic": diagnostic}
    if operation == "analyze":
        window.analysis_task = CompletedTask(payload)
        timer, start, poll = window.analysis_timer, window.analyze_button, window.poll_analysis
        output = window.analysis_output
    else:
        window.task = CompletedTask(payload)
        timer, start, poll = window.timer, window.generate_button, window.poll
        output = window.details
    start.setEnabled(False)
    timer.start()
    observed = inspect_next_failure()
    poll()
    assert_diagnostic(observed, diagnostic)
    assert observed["button"] == "查看原始诊断"
    assert not observed["initially_expanded"]
    assert not timer.isActive() and start.isEnabled()
    assert window.task is None and window.analysis_task is None
    assert "查看原始诊断" in output.toPlainText()
    assert window.require_project().snapshot() == before
    assert window.diagnostic_button.isEnabled() and window.diagnostic_button.isVisible()
    observed = inspect_next_failure()
    QTest.mouseClick(window.diagnostic_button, Qt.MouseButton.LeftButton)
    assert_diagnostic(observed, diagnostic)
    assert observed["initially_expanded"]


def test_start_failure_retains_chained_exception_and_next_failure_replaces_it(window, conditions, monkeypatch):
    from experiment_planner.worker import process

    window.conditions.set_values(conditions)

    def fail_start(*args, **kwargs):
        try:
            raise OSError("底层启动错误")
        except OSError as exc:
            raise RuntimeError("无法启动计算进程") from exc

    monkeypatch.setattr(process, "CalculationTask", fail_start)
    observed = inspect_next_failure()
    window.guard(window.start_analysis)
    assert_diagnostic(observed, "RuntimeError: 无法启动计算进程")
    assert "OSError: 底层启动错误" in observed["text"]
    assert "start_analysis" in observed["text"]
    assert window.analysis_task is None and window.analyze_button.isEnabled()
    observed = inspect_next_failure()
    window.guard(lambda: int("第二次错误"))
    assert_diagnostic(observed, "ValueError")
    observed = inspect_next_failure()
    window.diagnostic_button.click()
    assert_diagnostic(observed, "第二次错误")
    assert "底层启动错误" not in observed["text"]


@pytest.mark.parametrize("operation", ["generate", "analyze"])
def test_poll_exception_stops_timer_and_keeps_diagnostic(window, operation):
    class BrokenTask:
        cancelled = False

        def poll(self):
            raise OSError("读取计算管道失败")

        def cancel(self):
            self.cancelled = True

    task = BrokenTask()
    if operation == "generate":
        window.task = task
        timer, start, poll = window.timer, window.generate_button, window.poll
    else:
        window.analysis_task = task
        timer, start, poll = window.analysis_timer, window.analyze_button, window.poll_analysis
    start.setEnabled(False)
    timer.start()
    observed = inspect_next_failure()
    poll()
    assert_diagnostic(observed, "OSError: 读取计算管道失败")
    assert task.cancelled and not timer.isActive() and start.isEnabled()
    assert window.task is None and window.analysis_task is None


def test_missing_diagnostic_is_explicit_and_success_does_not_erase_last_failure(window):
    window.analysis_task = CompletedTask({"error": "计算未返回诊断"})
    observed = inspect_next_failure()
    window.poll_analysis()
    assert_diagnostic(observed, "未收到原始诊断")
    assert "计算未返回诊断" in observed["text"]
    previous = window.last_failure
    report = {"revision": window.require_project().revision, "predictions": [], "notices": []}
    window.analysis_template = window.require_project().template
    window.analysis_task = CompletedTask({"result": report})
    window.poll_analysis()
    assert window.analysis_report == report
    assert window.last_failure == previous


def test_analysis_result_rendering_failure_has_diagnostics(window, monkeypatch):
    import experiment_planner.ui.desktop as desktop

    def fail_render(*args):
        raise RuntimeError("展示预测结果时失败")

    monkeypatch.setattr(desktop, "analysis_text", fail_render)
    window.analysis_template = window.require_project().template
    window.analysis_task = CompletedTask({"result": {"predictions": []}})
    observed = inspect_next_failure()
    window.poll_analysis()
    assert_diagnostic(observed, "RuntimeError: 展示预测结果时失败")
    assert window.analyze_button.isEnabled() and window.analysis_task is None


def test_recommendation_commit_failure_has_diagnostics(window, monkeypatch):
    def fail_commit(*args):
        raise RuntimeError("提交计算批次时失败")

    monkeypatch.setattr(window.service, "commit_batch", fail_commit)
    window.task = CompletedTask({"result": {}})
    observed = inspect_next_failure()
    window.poll()
    assert_diagnostic(observed, "RuntimeError: 提交计算批次时失败")
    assert window.generate_button.isEnabled() and window.task is None


def test_configuration_failure_before_calculation_has_details(window, conditions):
    window.conditions.set_values(conditions)
    window.plot_variables.setText("cl2_sccm")
    window.plot_ranges.editors["cl2_sccm"][0].setText("不是数值")
    observed = inspect_next_failure()
    window.guard(window.start_analysis)
    assert_diagnostic(observed, "上下限需要数值")
    assert window.analysis_task is None and window.analyze_button.isEnabled()
