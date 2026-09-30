import copy
import hashlib
import uuid
from functools import wraps

from experiment_planner.application.records import derive, normalize_observations
from experiment_planner.domain.errors import ValidationError
from experiment_planner.storage.project import Project, encode, now


def reversible(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        p = self.project
        with p.transaction():
            before = self._state_without_transaction()
            revision = before["revision"]
            self._action_revision = revision
            result = method(self, *args, **kwargs)
            after = self._state_without_transaction()
        if revision != self._history_revision:
            self._undo.clear(); self._redo.clear()
        if after["revision"] != revision:
            self._undo.append((before, after))
            self._undo = self._undo[-50:]
            self._redo.clear()
        self._history_revision = after["revision"]
        return result
    return wrapped


class PlannerService:
    def __init__(self, project):
        self.project = project
        self._undo, self._redo = [], []
        self._history_revision = project.revision

    def _restore(self, state, action):
        p = self.project
        with p.transaction(self._history_revision):
            old = self._state_without_transaction()
            data = copy.deepcopy(state["template"])
            current = p.template.data
            semantic = lambda value: {k: v for k, v in value.items() if k != "template_version"}
            if semantic(data) != semantic(current):
                # A restored configuration receives a new version, never an old one.
                data["template_version"] = current["template_version"] + 1
                p.db.execute("UPDATE project SET template=? WHERE id=1", (encode(data),))
            p.db.execute("DELETE FROM experiments")
            p.db.executemany("INSERT INTO experiments(id,payload,import_key) VALUES(?,?,?)", state["rows"])
            p.bump()
            p.log(action, 1, old, self._state_without_transaction())
        self._history_revision = p.revision

    def _state_without_transaction(self):
        return {"revision": self.project.revision, "template": self.project.template.data,
                "rows": [tuple(row) for row in self.project.db.execute("SELECT id,payload,import_key FROM experiments ORDER BY id")]}

    def undo(self):
        if not self._undo: raise ValidationError("没有可撤销的已保存操作")
        before, after = self._undo[-1]
        self._restore(before, "undo")
        self._undo.pop(); self._redo.append((before, after))

    def redo(self):
        if not self._redo: raise ValidationError("没有可重做的操作")
        before, after = self._redo[-1]
        self._restore(after, "redo")
        self._redo.pop(); self._undo.append((before, after))

    def prepare_record(self, conditions, observations, *, status="completed", note="", field_notes=None, suggested=None):
        if status not in ("pending", "running", "completed", "partial", "failed", "cancelled"):
            raise ValidationError("未知实验状态")
        t = self.project.template
        actual = t.validate_conditions(conditions, execution=False)
        cells = normalize_observations(t, observations)
        if suggested is not None: t.validate_conditions(suggested)
        return {"record_uid": str(uuid.uuid4()), "actual": actual, "suggested": suggested, "observations": cells,
                "derived": derive(t, actual, cells), "status": status, "note": note,
                "field_notes": field_notes or {}, "template_version": t.data["template_version"], "updated": now()}

    @reversible
    def add_record(self, conditions, observations, **kwargs):
        revision=self._action_revision
        record = self.prepare_record(conditions, observations, **kwargs)
        p = self.project
        with p.transaction(revision):
            cursor = p.insert_experiment(record)
            p.bump()
            p.log("experiment", cursor.lastrowid, None, record)
        return cursor.lastrowid

    @reversible
    def revise_record(self, experiment_id, conditions, observations, **kwargs):
        p = self.project
        revision=self._action_revision
        old = p.experiment(experiment_id)
        new = self.prepare_record(conditions, observations, suggested=old.get("suggested"), **kwargs)
        for key in ("record_uid", "repeat_of_uid", "baseline_id_uid", "batch_id", "prediction", "arrangement", "changes", "repeat_of", "baseline_id", "cross_members"):
            if key in old: new[key] = old[key]
        with p.transaction(revision):
            p.db.execute("UPDATE experiments SET payload=? WHERE id=?", (encode(new), experiment_id))
            p.bump()
            p.log("experiment", experiment_id, old, new)

    @reversible
    def delete_records(self, experiment_ids, expected_revision=None):
        """Remove active records atomically, retaining audit data; inactive numbers can be reused."""
        ids = list(experiment_ids)
        if not ids or any(type(eid) is not int or eid <= 0 for eid in ids):
            raise ValidationError("请选择至少一条有效实验记录")
        ids = list(dict.fromkeys(ids))
        p = self.project
        with p.transaction(self._action_revision if expected_revision is None else expected_revision):
            records = [p.experiment(eid) for eid in ids]
            old_template = p.template
            defaults = copy.deepcopy(old_template.data.get("batch_defaults", {}))
            if defaults.get("baseline_experiment_id") in ids:
                defaults["baseline_experiment_id"] = None
            if "repeat_ids" in defaults:
                defaults["repeat_ids"] = [eid for eid in defaults["repeat_ids"] if eid not in ids]
            revised = old_template.revised(batch_defaults=defaults) if defaults != old_template.data.get("batch_defaults", {}) else None
            # Older applications must not reopen tombstones as active experiments.
            p.db.execute("PRAGMA user_version=2")
            p.bump()
            for old in records:
                eid = old["id"]
                removed = {**old, "deleted_at": now()}
                removed.pop("id")
                # Keep deleted payload until this number is reused; audit remains permanent.
                # Release import identity so the same source can be imported again.
                p.db.execute("UPDATE experiments SET payload=?, import_key=NULL WHERE id=?", (encode(removed), eid))
                p.log("experiment_delete", eid, old, removed)
            if revised:
                p.db.execute("UPDATE project SET template=? WHERE id=1", (encode(revised.data),))
                p.log("template", 1, old_template.data, revised.data)
        return ids

    @reversible
    def import_records(self, records, expected_revision):
        p = self.project
        prepared = []
        for item in records:
            record = self.prepare_record(item["conditions"], item["observations"], note=item.get("note", ""), field_notes=item.get("field_notes"), status=item.get("status", "completed"))
            identity = str(item["external_id"]) if item.get("external_id") is not None else None
            # Content fallback preserves actual inputs, never rounded modeling inputs.
            key = hashlib.sha256(encode({"external_id": identity} if identity else item).encode()).hexdigest()
            prepared.append((key, record))
        ids = []
        if expected_revision != self._action_revision:
            from experiment_planner.domain.errors import StaleVersionError
            raise StaleVersionError("项目已修改，请重新预览导入")
        with p.transaction(expected_revision):
            for key, record in prepared:
                existing = p.db.execute("SELECT id,payload FROM experiments WHERE import_key=?", (key,)).fetchone()
                if existing:
                    prior = __import__("json").loads(existing[1])
                    for obj in (prior, record):
                        obj.pop("updated", None); obj.pop("record_uid", None); obj.pop("template_version", None)
                    if prior != record: raise ValidationError("同一外部实验编号内容冲突，请使用更正功能")
                    continue
                cursor = p.insert_experiment(record, key)
                ids.append(cursor.lastrowid)
                p.bump()
                p.log("import", cursor.lastrowid, None, record)
        return ids

    @reversible
    def update_template(self, template):
        p = self.project
        revision=self._action_revision
        old = p.template
        # Structural edits require a new project; formula/role/goal changes are explicit revisions.
        for section in ("parameters", "measurements"):
            keys = ("name", "unit", "value_type", "bounds", "values", "fixed_value")
            signature = lambda t: [{k: f.get(k) for k in keys} for f in t.data.get(section, [])]
            if signature(old) != signature(template) and p.experiments():
                raise ValidationError("已有实验记录的字段结构、单位或范围不同，请将修改另存为模板或使用它新建项目")
        if template.data["template_version"] <= old.data["template_version"]:
            raise ValidationError("模板修改必须递增版本")
        recomputed = []
        for exp in p.experiments():
            exp["derived"] = derive(template, exp["actual"], exp["observations"])
            exp["template_version"] = template.data["template_version"]
            recomputed.append(exp)
        with p.transaction(revision):
            p.db.execute("UPDATE project SET template=? WHERE id=1", (encode(template.data),))
            p.bump()
            p.log("template", 1, old.data, template.data)
            for exp in recomputed:
                eid = exp.pop("id")
                p.db.execute("UPDATE experiments SET payload=? WHERE id=?", (encode(exp), eid))
        p.template = template

    def commit_batch(self, batch):
        p = self.project
        if len(batch["candidates"]) > batch["request"]["n"]: raise ValidationError("批次超过总配额")
        for candidate in batch["candidates"]: p.template.validate_conditions(candidate["conditions"])
        with p.transaction(batch["revision"]):
            cursor = p.db.execute("INSERT INTO batches(revision,payload) VALUES(?,?)", (p.revision, encode(batch)))
            bid = cursor.lastrowid
            ids = []
            for candidate in batch["candidates"]:
                record = self.prepare_record(candidate["conditions"], {}, status="pending", suggested=candidate["conditions"])
                record.update({"batch_id": bid, "prediction": candidate.get("prediction"), "arrangement": candidate.get("arrangement", "new"), "changes": candidate.get("changes", {})})
                for name in ("repeat_of","baseline_id","cross_members"):
                    if name in candidate:record[name]=candidate[name]
                for ref in ("repeat_of", "baseline_id"):
                    if candidate.get(ref) is not None:
                        record[ref + "_uid"] = p.experiment(candidate[ref]).get("record_uid")
                c = p.insert_experiment(record)
                ids.append(c.lastrowid)
            p.bump()
            p.log("batch", bid, None, {"experiment_ids": ids, "source_revision": batch["revision"]})
        self._undo.clear(); self._redo.clear()
        self._history_revision = p.revision
        return bid, ids
