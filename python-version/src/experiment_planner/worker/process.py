"""Spawn worker: calculate on an immutable snapshot, commit only in parent."""
import multiprocessing as mp
import traceback
from filelock import FileLock, Timeout

from experiment_planner.domain.errors import ValidationError


def _run(connection, snapshot, request, operation):
    try:
        if operation == "analyze":
            from experiment_planner.application.analysis import analyze
            result = analyze(snapshot, request)
        else:
            from experiment_planner.engine.planner import generate
            result = generate(snapshot, request)
        connection.send({"result": result})
    except Exception as exc:
        connection.send({"error": f"{type(exc).__name__}: {exc}"})
    finally: connection.close()


class CalculationTask:
    active = set()

    def __init__(self, project, request, operation="generate"):
        if operation not in ("generate", "analyze"):
            raise ValidationError("未知计算操作")
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
        if self.connection.poll():
            try: result = self.connection.recv()
            except EOFError: result = {"error": "计算进程意外退出，项目未修改"}
            self.finish()
            return result
        if not self.process.is_alive():
            self.finish()
            return {"error": "计算进程退出但未返回结果，项目未修改"}
        return None

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
