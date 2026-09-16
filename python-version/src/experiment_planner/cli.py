"""Local Python interface to the same services used by the desktop application."""
import argparse
import json
from pathlib import Path
import sys

from experiment_planner.application.service import PlannerService
from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def dispatch(args):
    if args.command == "create":
        template = Template.read(args.template) if args.template else Template.builtin()
        with Project.create(args.project, args.name, template) as project:
            return {"project": str(project.path), "revision": project.revision}
    if args.command == "builtin-template":
        Template.builtin().write(args.output)
        return {"template": str(args.output)}
    with Project(args.project) as project:
        service = PlannerService(project)
        if args.command == "records":
            return project.experiments()
        if args.command == "history":
            return project.history()
        if args.command == "template":
            if args.input:
                service.update_template(Template.read(args.input))
            return project.template.data
        if args.command == "record":
            record = read_json(args.input)
            if args.id is None:
                eid = service.add_record(**record)
            else:
                eid = args.id
                service.revise_record(eid, **record)
            return project.experiment(eid)
        if args.command == "import":
            from experiment_planner.io.exchange import preview_import
            preview = preview_import(service, args.input, read_json(args.mapping) if args.mapping else None)
            if preview.errors:
                raise ValueError(json.dumps(preview.errors, ensure_ascii=False))
            if args.commit:
                return {"imported_ids": preview.commit(service)}
            return {"preview": preview.records, "revision": preview.revision, "saved": False}
        if args.command == "export":
            from experiment_planner.io.exchange import export_records
            export_records(project, args.output)
            return {"export": str(args.output)}
        if args.command == "backup":
            project.backup(args.output)
            return {"backup": str(args.output)}
        if args.command == "recommend":
            from experiment_planner.engine.planner import generate
            from experiment_planner.engine.space import BatchRequest
            batch = generate(project.snapshot(), BatchRequest(**read_json(args.request)))
            if args.commit:
                bid, ids = service.commit_batch(batch)
                batch["saved_batch_id"], batch["experiment_ids"] = bid, ids
            return batch
        if args.command == "predict":
            from experiment_planner.application.analysis import analyze
            return analyze(project.snapshot(), read_json(args.request))
    raise ValueError("Unknown command")


def main(argv=None):
    parser = argparse.ArgumentParser(description="实验规划助手 Python 接口（全部计算在本地）")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="创建独立 SQLite 项目")
    create.add_argument("project", type=Path)
    create.add_argument("--name", default="实验项目")
    create.add_argument("--template", type=Path)
    builtin = sub.add_parser("builtin-template", help="导出内置模板，供编辑和复制")
    builtin.add_argument("output", type=Path)
    for name in ("records", "history", "template", "record", "import", "export", "backup", "recommend", "predict"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
        if name == "template":
            command.add_argument("--input", type=Path, help="保存新的模板版本（版本号必须递增）")
        if name in ("record", "import"):
            command.add_argument("input", type=Path)
        if name == "record":
            command.add_argument("--id", type=int, help="更正/回填此实验编号；省略时新增")
        if name == "import":
            command.add_argument("--mapping", type=Path, help="原始表头到模板字段名的 JSON 映射")
        if name in ("import", "recommend"):
            command.add_argument("--commit", action="store_true", help="把预览结果保存到项目")
        if name in ("export", "backup"):
            command.add_argument("output", type=Path)
        if name in ("recommend", "predict"):
            command.add_argument("request", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(dispatch(args), ensure_ascii=False, indent=2, allow_nan=False))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
