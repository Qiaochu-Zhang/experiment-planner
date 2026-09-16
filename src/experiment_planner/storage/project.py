"""SQLite business records are authoritative; model caches are disposable."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from experiment_planner.domain.errors import StaleVersionError, ValidationError
from experiment_planner.domain.template import Template


def encode(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
def now(): return datetime.now(timezone.utc).isoformat()


class Project:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file(): raise ValidationError("项目文件不存在")
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            if self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValidationError("不支持此数据库结构版本；请保留原文件并使用对应版本")
            self.template = Template(json.loads(self.db.execute("SELECT template FROM project WHERE id=1").fetchone()[0]))
        except Exception:
            self.db.close()
            raise

    @classmethod
    def create(cls, path, name, template=None):
        path = Path(path)
        if path.exists(): raise ValidationError("项目文件已存在，不覆盖")
        template = template or Template.builtin()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also prevents a second creator from replacing this project.
        with path.open("xb"): pass
        db = sqlite3.connect(path)
        try:
            db.executescript('''
                PRAGMA user_version=1;
                CREATE TABLE project(id INTEGER PRIMARY KEY CHECK(id=1), uuid TEXT NOT NULL, name TEXT NOT NULL, template TEXT NOT NULL, revision INTEGER NOT NULL, created TEXT NOT NULL);
                CREATE TABLE experiments(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, import_key TEXT UNIQUE);
                CREATE TABLE batches(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE change_log(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, entity TEXT NOT NULL, entity_id TEXT, old_payload TEXT, new_payload TEXT, created TEXT NOT NULL);
                CREATE TABLE snapshots(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
            db.execute("INSERT INTO project VALUES(1,?,?,?,?,?)", (str(uuid.uuid4()), name, encode(template.data), 0, now()))
            db.commit()
        finally: db.close()
        return cls(path)

    @property
    def revision(self): return self.db.execute("SELECT revision FROM project WHERE id=1").fetchone()[0]

    @property
    def template(self):
        raw=self.db.execute("SELECT template FROM project WHERE id=1").fetchone()[0]
        if getattr(self,"_template_json",None)!=raw:
            self._template=Template(json.loads(raw));self._template_json=raw
        return self._template

    @template.setter
    def template(self,value):
        self._template=value;self._template_json=encode(value.data)

    @property
    def name(self): return self.db.execute("SELECT name FROM project WHERE id=1").fetchone()[0]

    @contextmanager
    def transaction(self, expected=None):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if expected is not None and self.revision != expected:
                raise StaleVersionError("项目已修改，请基于最新数据重新计算")
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def bump(self):
        self.db.execute("UPDATE project SET revision=revision+1 WHERE id=1")
        return self.revision

    def log(self, entity, entity_id, old, new):
        self.db.execute("INSERT INTO change_log(revision,entity,entity_id,old_payload,new_payload,created) VALUES(?,?,?,?,?,?)", (self.revision, entity, str(entity_id), encode(old), encode(new), now()))

    def experiments(self):
        return [{"id": row["id"], **json.loads(row["payload"])} for row in self.db.execute("SELECT id,payload FROM experiments ORDER BY id")]

    def experiment(self, experiment_id):
        row = self.db.execute("SELECT payload FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None: raise ValidationError("实验编号不存在")
        return {"id": experiment_id, **json.loads(row[0])}

    def batches(self):
        return [{"id": r[0], "revision": r[1], **json.loads(r[2])} for r in self.db.execute("SELECT id,revision,payload FROM batches ORDER BY id")]

    def history(self): return [dict(r) for r in self.db.execute("SELECT * FROM change_log ORDER BY id")]

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination == self.path or destination.exists(): raise ValidationError("备份目标已存在，请选择新文件")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"): pass
        target = sqlite3.connect(destination)
        try: self.db.backup(target)
        finally: target.close()

    def snapshot(self):
        # A read transaction prevents a mixed revision when another connection writes.
        self.db.execute("BEGIN")
        try:
            return {"name": self.name, "revision": self.revision, "template": json.loads(self.db.execute("SELECT template FROM project WHERE id=1").fetchone()[0]), "experiments": self.experiments()}
        finally: self.db.rollback()

    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
