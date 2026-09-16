import copy
import hashlib

from experiment_planner.application.records import derive, normalize_observations
from experiment_planner.domain.errors import ValidationError
from experiment_planner.storage.project import Project, encode, now


class PlannerService:
    def __init__(self, project): self.project = project

    def prepare_record(self, conditions, observations, *, status="completed", note="", field_notes=None, suggested=None):
        if status not in ("pending", "running", "completed", "partial", "failed", "cancelled"):
            raise ValidationError("未知实验状态")
        t = self.project.template
        actual = t.validate_conditions(conditions, execution=False)
        cells = normalize_observations(t, observations)
        if suggested is not None: t.validate_conditions(suggested)
        return {"actual": actual, "suggested": suggested, "observations": cells,
                "derived": derive(t, actual, cells), "status": status, "note": note,
                "field_notes": field_notes or {}, "template_version": t.data["template_version"], "updated": now()}

    def add_record(self, conditions, observations, **kwargs):
        revision=self.project.revision
        record = self.prepare_record(conditions, observations, **kwargs)
        p = self.project
        with p.transaction(revision):
            cursor = p.db.execute("INSERT INTO experiments(payload) VALUES(?)", (encode(record),))
            p.bump()
            p.log("experiment", cursor.lastrowid, None, record)
        return cursor.lastrowid

    def revise_record(self, experiment_id, conditions, observations, **kwargs):
        p = self.project
        revision=p.revision
        old = p.experiment(experiment_id)
        new = self.prepare_record(conditions, observations, suggested=old.get("suggested"), **kwargs)
        for key in ("batch_id", "prediction", "arrangement", "changes", "repeat_of", "baseline_id", "cross_members"):
            if key in old: new[key] = old[key]
        with p.transaction(revision):
            p.db.execute("UPDATE experiments SET payload=? WHERE id=?", (encode(new), experiment_id))
            p.bump()
            p.log("experiment", experiment_id, old, new)

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
        with p.transaction(expected_revision):
            for key, record in prepared:
                existing = p.db.execute("SELECT id,payload FROM experiments WHERE import_key=?", (key,)).fetchone()
                if existing:
                    prior = __import__("json").loads(existing[1])
                    for obj in (prior, record): obj.pop("updated", None)
                    if prior != record: raise ValidationError("同一外部实验编号内容冲突，请使用更正功能")
                    continue
                cursor = p.db.execute("INSERT INTO experiments(payload,import_key) VALUES(?,?)", (encode(record), key))
                ids.append(cursor.lastrowid)
                p.bump()
                p.log("import", cursor.lastrowid, None, record)
        return ids

    def update_template(self, template):
        p = self.project
        revision=p.revision
        old = p.template
        # Structural edits require a new project; formula/role/goal changes are explicit revisions.
        for section in ("parameters", "measurements"):
            keys = ("name", "unit", "value_type", "bounds", "values", "fixed_value")
            signature = lambda t: [{k: f.get(k) for k in keys} for f in t.data.get(section, [])]
            if signature(old) != signature(template): raise ValidationError("字段结构、单位或范围改变需要新建项目；当前未提供结构迁移")
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
                c = p.db.execute("INSERT INTO experiments(payload) VALUES(?)", (encode(record),))
                ids.append(c.lastrowid)
            p.bump()
            p.log("batch", bid, None, {"experiment_ids": ids, "source_revision": batch["revision"]})
        return bid, ids
