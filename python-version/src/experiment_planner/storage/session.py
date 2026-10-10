"""GUI edits live in a temporary SQLite copy until explicit project save."""
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile

from filelock import FileLock

from experiment_planner.domain.errors import StaleVersionError
from experiment_planner.storage.project import Project


def fingerprint(path):
    if not path.exists(): return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


class ProjectSession(Project):
    def __init__(self, target, *, template=None, creating=False):
        self.target_path = Path(target).resolve()
        self._temporary = TemporaryDirectory(prefix="experiment-planner-")
        working = Path(self._temporary.name) / "working.sqlite"
        try:
            self._saved_fingerprint = fingerprint(self.target_path)
            if creating:
                project = Project.create(working, self.target_path.stem, template)
                project.close()
            else:
                with Project(self.target_path) as source: source.backup(working)
                if fingerprint(self.target_path) != self._saved_fingerprint:
                    raise StaleVersionError("打开时项目被其他窗口修改，请重新打开")
            super().__init__(working)
        except BaseException:
            self._temporary.cleanup()
            raise
        self._saved_revision = None if creating else self.revision

    @property
    def dirty(self): return self._saved_revision != self.revision

    def save(self):
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.target_path) + ".save.lock"):
            if fingerprint(self.target_path) != self._saved_fingerprint:
                raise StaleVersionError("项目文件在打开后被其他窗口修改，请另存项目或重新打开，避免覆盖其他变化")
            with NamedTemporaryFile(dir=self.target_path.parent, prefix=".project-save-", suffix=".sqlite", delete=False) as file:
                temporary = Path(file.name)
            try:
                temporary.unlink()
                self.backup(temporary)
                with temporary.open("rb") as source: os.fsync(source.fileno())
                os.replace(temporary, self.target_path)
            finally:
                temporary.unlink(missing_ok=True)
            self._saved_revision = self.revision
            self._saved_fingerprint = fingerprint(self.target_path)

    def close(self):
        super().close()
        self._temporary.cleanup()
