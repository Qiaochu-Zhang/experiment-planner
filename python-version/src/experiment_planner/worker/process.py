"""Spawn worker: calculate on an immutable snapshot, commit only in parent."""
import multiprocessing as mp
import warnings
from filelock import FileLock, Timeout

from experiment_planner.domain.errors import ValidationError


def _run(connection, snapshot, request, operation):
    captured = []
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            if operation == "analyze":
                from experiment_planner.application.analysis import analyze
                result = analyze(snapshot, request)
            elif operation == "importance":
                from experiment_planner.application.importance import analyze_importance
                result = analyze_importance(snapshot, request)
            else:
                from experiment_planner.engine.planner import generate
                result = generate(snapshot, request)
        from experiment_planner.ui.messages import warning_text
        result.setdefault("notices", []).extend(dict.fromkeys(warning_text(w) for w in captured))
        result["diagnostics"] = list(dict.fromkeys(f"{w.category.__name__}: {w.message}" for w in captured))
        connection.send({"result": result})
    except Exception as exc:
        from experiment_planner.ui.messages import user_error, exception_diagnostic
        diagnostic = exception_diagnostic(exc)
        if captured:
            diagnostic += "\n计算失败前的原始警告：\n" + "\n".join(
                f"{w.category.__name__}: {w.message}\n  {w.filename}:{w.lineno}"
                for w in captured
            )
        connection.send({"error": user_error(exc), "diagnostic": diagnostic})
    finally: connection.close()


class CalculationTask:
    active = set()

    def __init__(self, project, request, operation="generate"):
        if operation not in ("generate", "analyze", "importance"):
            raise ValidationError("未知计算操作")
        self.operation = operation
        self.key = str(project.path)
        if self.key in self.active: raise ValidationError("本项目已有生成任务，请等待或取消")
        self.lock=FileLock(self.key+".generate.lock")
        try:self.lock.acquire(timeout=0)
        except Timeout as exc:raise ValidationError("另一个程序窗口正在为本项目生成实验") from exc
        try:snapshot = project.snapshot()
        except BaseException:
            self.lock.release();raise
        context = mp.get_context("spawn")
        self.connection, child = context.Pipe(duplex=False)
        self.process = context.Process(target=_run, args=(child, snapshot, request, operation), daemon=True)
        self.active.add(self.key)
        try: self.process.start()
        except BaseException:
            self.active.discard(self.key)
            self.lock.release()
            self.connection.close()
            child.close()
            raise
        child.close()

    def poll(self):
        if not self.connection.poll() and self.process.is_alive():
            return None
        # Recheck after process exit: the last payload may have arrived between
        # the first pipe poll and the liveness check.
        if self.connection.poll():
            try:
                result = self.connection.recv()
            except EOFError:
                result = self.exit_failure("通信管道已关闭，未收到计算结果（EOFError）")
        else:
            result = self.exit_failure("计算进程退出但未返回结果")
        self.finish()
        return result

    def exit_failure(self, reason):
        self.process.join(timeout=.2)
        return {
            "error": "计算进程意外退出，项目未修改。请查看原始诊断。",
            "diagnostic": (
                f"{reason}\n计算类型：{self.operation}\n"
                f"进程 PID：{self.process.pid}\n退出码：{self.process.exitcode}\n"
                "进程未返回 Python 异常内容，无法提供原始异常堆栈。"
            ),
        }

    def finish(self):
        self.process.join(timeout=.2)
        self.connection.close()
        self.active.discard(self.key)
        self.lock.release()

    def cancel(self):
        if self.process.is_alive(): self.process.terminate()
        self.process.join(timeout=2)
        self.connection.close()
        self.active.discard(self.key)
        self.lock.release()
