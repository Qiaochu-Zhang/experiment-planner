import csv
import json
import math
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from experiment_planner.application.records import normalize_observations
from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import parse_value


@dataclass
class ImportPreview:
    revision: int
    records: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    stop_row: int | None = None
    stop_fields: list = field(default_factory=list)

    @property
    def stop_message(self):
        if self.stop_row is None: return ""
        return f"第 {self.stop_row} 行的前 {len(self.stop_fields)} 个输入均为空，已作为结束标记；该行及后续行不导入。检查字段：" + "、".join(self.stop_fields)

    def commit(self, service):
        if self.errors: raise ValidationError("请先修复导入预览中的错误")
        return service.import_records(self.records, self.revision)


def missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def checked_headers(values):
    headers = [str(value).strip() if value is not None else "" for value in values]
    while headers and not headers[-1]: headers.pop()
    if not headers or any(not h for h in headers) or len(headers) != len(set(headers)):
        raise ValidationError("导入表头为空或重复，请检查第一行")
    return headers


def table_rows(path):
    """Yield headers, then (physical starting row, cells), preserving empty rows."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            headers = checked_headers(next(reader, []))
            yield headers
            while True:
                start = reader.line_num + 1
                values = next(reader, None)
                if values is None: break
                row = {name: values[i] if i < len(values) else None for i, name in enumerate(headers)}
                if any(not missing(value) for value in values[len(headers):]): row[None] = values[len(headers):]
                yield start, row
        return
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            rows = workbook.active.iter_rows(values_only=True)
            headers = checked_headers(next(rows, ()))
            yield headers
            for number, values in enumerate(rows, 2):
                row = {name: values[i] if i < len(values) else None for i, name in enumerate(headers)}
                if any(not missing(value) for value in values[len(headers):]): row[None] = values[len(headers):]
                yield number, row
        finally: workbook.close()
        return
    raise ValidationError("仅支持 CSV / XLSX")


def read_headers(path):
    with closing(table_rows(path)) as rows: return next(rows)


def read_rows(path):
    with closing(table_rows(path)) as rows:
        next(rows)
        return [row for _, row in rows]


def preview_import(service, path, mapping=None):
    t = service.project.template
    preview = ImportPreview(service.project.revision)
    fields = t.parameters + t.measurements
    aliases = {f.get("label", f["name"]): f["name"] for f in fields}
    aliases.update({f["name"]: f["name"] for f in fields})
    suffixes = {"_不确定度": "_uncertainty", "_误差类型": "_uncertainty_kind", "_备注": "_note", "_单位": "_unit", "_分布": "_distribution", "_覆盖因子": "_coverage_factor", "_置信水平": "_confidence"}
    def mapped_name(column):
        if column in (mapping or {}): return mapping[column]
        for suffix, canonical in suffixes.items():
            if column.endswith(suffix) and column[:-len(suffix)] in aliases:
                return aliases[column[:-len(suffix)]] + canonical
        return aliases.get(column, column)
    count = max(1, math.ceil(len(t.parameters) * .3))
    first_inputs = [p["name"] for p in t.parameters[:count]]
    with closing(table_rows(path)) as rows:
        headers = next(rows)
        mapped = {h: mapped_name(h) for h in headers}
        if len(set(mapped.values())) != len(mapped):
            preview.errors.append({"row": 1, "message": "多列映射到同一字段，请调整列对应关系"})
            return preview
        absent = [name for name in first_inputs if name not in mapped.values()]
        if absent:
            preview.errors.append({"row": 1, "message": "用于结束判断的输入列未匹配：" + "、".join(absent)})
            return preview
        for row_number, raw in rows:
            row = {mapped[k]: value for k, value in raw.items() if k in mapped}
            if all(missing(row.get(name)) for name in first_inputs):
                preview.stop_row = row_number; preview.stop_fields = first_inputs
                break
            try:
                if None in raw: raise ValidationError("数据列数超过表头，请检查多余的分隔符或表头")
                inputs = {p["name"]: parse_value(row.get(p["name"]), p) for p in t.parameters}
                t.validate_conditions(inputs, execution=False)
                measurements = {}
                for f in t.measurements:
                    n = f["name"]
                    uncertainty = {"kind": row.get(n+"_uncertainty_kind") or "unspecified", "distribution": row.get(n+"_distribution") or None}
                    for suffix in ("amount", "coverage_factor", "confidence"):
                        value = row.get(n+("_uncertainty" if suffix == "amount" else "_"+suffix))
                        if value not in ("", None): uncertainty[suffix] = float(value)
                    measurements[n] = {"value": row.get(n), "unit": row.get(n+"_unit") or f.get("unit", "1"), "note": row.get(n+"_note") or "", "uncertainty": uncertainty, "source_text": str(row.get(n, ""))}
                normalize_observations(t, measurements)
                preview.records.append({"conditions": inputs, "observations": measurements, "external_id": row.get("external_id") or row.get("experiment_id"), "note": row.get("note") or "", "status": row.get("status") or "completed", "field_notes": {p["name"]: row.get(p["name"]+"_note") or "" for p in t.parameters}})
            except (ValueError, TypeError) as exc:
                preview.errors.append({"row": row_number, "message": str(exc)})
    return preview


def export_records(project, path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(project.snapshot(), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return
    rows = []
    for e in project.experiments():
        row = {"experiment_id": e["id"], "status": e["status"], "note": e["note"], **e["actual"]}
        for name, note in e.get("field_notes", {}).items(): row[name+"_note"] = note
        for n, c in e["observations"].items():
            u = c.get("uncertainty") or {}
            row.update({n: c["value"], n+"_unit": c["unit"], n+"_note": c["note"], n+"_uncertainty": u.get("amount"), n+"_uncertainty_kind": u.get("kind"), n+"_distribution": u.get("distribution"), n+"_coverage_factor": u.get("coverage_factor"), n+"_confidence": u.get("confidence"), n+"_uncertainty_json": json.dumps(u, ensure_ascii=False)})
        for n, c in e["derived"].items(): row.update({n: c["value"], n+"_status": c["status"]})
        row["suggested_json"] = json.dumps(e.get("suggested"), ensure_ascii=False)
        row["prediction_json"] = json.dumps(e.get("prediction"), ensure_ascii=False)
        rows.append(row)
    headers = list(dict.fromkeys(["experiment_id", "status", "note", *(p["name"] for p in project.template.parameters), *(k for r in rows for k in r)]))
    if path.suffix.lower() == ".csv":
        with path.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        sheet = wb.active
        sheet.title = "实验记录"
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(k) for k in headers])
            # Notes and external text are literal text, never spreadsheet formula code.
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str): cell.data_type = "s"
        wb.save(path)
        wb.close()
    else: raise ValidationError("导出支持 CSV / XLSX / JSON")
