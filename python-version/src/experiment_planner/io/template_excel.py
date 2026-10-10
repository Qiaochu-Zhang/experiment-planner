"""Editable Chinese Excel template definitions (distinct from experiment rows)."""
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from experiment_planner.application.template_editing import blank_template, normalize_draft
from experiment_planner.domain.errors import ValidationError


FIELD_COLUMNS = [
    ("内部名称", "name"), ("显示名称", "label"), ("类型", "value_type"), ("单位", "unit"),
    ("说明", "note"), ("下限", "lower"), ("上限", "upper"), ("离散值", "values"),
    ("固定值", "fixed_value"), ("作为模型输入", "use_as_model_input"),
    ("作为响应", "is_response"), ("直接建模", "model_base"), ("测量时点", "measured_at"),
    ("计算公式", "expression"), ("显示小数位数", "display_digits"),
    ("执行模式", "execution_mode"), ("执行小数位数", "execution_digits"),
    ("步长", "execution_step"), ("网格起点", "execution_origin"), ("其他属性", "extra"),
]
TABLES = {
    "输入参数": ("parameters", FIELD_COLUMNS),
    "原始测量": ("measurements", FIELD_COLUMNS),
    "派生指标与公式": ("derived_metrics", FIELD_COLUMNS),
    "优化目标": ("objectives", [("响应或指标", "metric"), ("方向", "direction"), ("变换", "transform"), ("目标值", "target"), ("其他属性", "extra")]),
    "先验关系": ("knowledge_priors", [("启用", "enabled"), ("输入参数", "input"), ("基础响应", "response"), ("关系", "relation"), ("系数", "coefficient"), ("强度", "strength"), ("来源", "source"), ("其他属性", "extra")]),
    "输入约束": ("input_constraints", [("系数", "coefficients"), ("比较", "op"), ("阈值", "rhs"), ("其他属性", "extra")]),
    "输出约束": ("outcome_constraints", [("响应或指标", "metric"), ("比较", "op"), ("阈值", "bound"), ("其他属性", "extra")]),
}
ALIASES = {
    "数值": "float", "整数": "int", "类别": "category", "是否": "bool", "文字": "text",
    "实验前": "before", "实验后": "after", "未指定": "unknown",
    "不限制": "none", "小数位数": "digits", "指定步长": "step",
    "尽量大": "maximize", "尽量小": "minimize", "原值": "identity", "绝对值": "abs", "距指定值的距离": "absolute_distance",
    "多目标折中": "pareto", "单目标": "single", "加权目标": "weighted",
    "移除比值目标": "remove", "稳定化比值": "stabilized", "有效区域内比值": "valid_region",
}
BOOL_KEYS = {"use_as_model_input", "is_response", "model_base", "enabled"}
INT_KEYS = {"display_digits", "execution_digits", "schema_version", "template_version"}
NUMBER_KEYS = {"lower", "upper", "execution_step", "execution_origin", "target", "coefficient", "strength", "rhs", "bound"}


def _cell_value(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False) if isinstance(value, (dict, list)) else value


def _append(sheet, values):
    sheet.append([_cell_value(value) for value in values])
    # Store strings literally, including expressions and user notes beginning '='.
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str): cell.data_type = "s"


def _flatten(data, prefix=""):
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            yield from _flatten(value, path)
        else:
            yield path, value


def write_template_excel(data, path):
    data = normalize_draft(data)
    workbook = Workbook()
    help_sheet = workbook.active; help_sheet.title = "填写说明"
    for text in (
        "本文件定义实验模板，不是实验记录导入表。可导入“新建 / 复制 / 修改模板”继续编辑。",
        "保留中文表头；每行一个字段，内部名称以英文字母开头，可用数字和下划线，所有表中不得重名。",
        "类型填 float/int/category/bool/text，或 数值/整数/类别/是否/文字。单位可自由填写，无量纲填 1。",
        "数值输入填写下限/上限，或离散值，或固定值；这三种方式选一种。是否输入可全部留空。",
        '离散值可写 JSON 数组（例如 [1,2,3] 或 ["甲","乙"]），也可用中英文逗号分隔。',
        "文字输入不进入数值模型；可自由填写，推荐时需基准文字或固定值/离散值。",
        "开关列填 是/否 或 true/false；文字/类别测量的作为响应填否。",
        "原始测量作为响应、直接建模默认是；派生指标作为响应默认是、直接建模默认否。",
        "派生公式使用内部名称，例如 result * 2；可写 =result * 2，导入只解析文字，不执行 Excel 公式。",
        "至少一个输入、一个直接建模的响应、一个有效目标。目标方向填 maximize/minimize 或 尽量大/尽量小。",
        "模板设置每行一个属性路径，例如 name、optimization.mode（pareto/single/weighted）、ratio_policy.mode。",
        "模板设置的列表/对象填写 JSON；加权模式用 optimization.weights/scales，顺序对应有效目标。",
        "其他属性可留空；用于保留扩展 JSON 配置。输入约束系数示例：{\"speed\":1}。",
        "留空属性表示待填写，可先导入编辑；最终保存时校验类型、范围、公式量纲和优化目标。",
        "显示小数位数仅改变显示；执行模式 digits 配合执行小数位数，step 配合步长与网格起点。",
    ): _append(help_sheet, [text])
    for title, (section, columns) in TABLES.items():
        sheet = workbook.create_sheet(title)
        _append(sheet, [title for title, _ in columns])
        for field in data.get(section, []):
            row = dict(field)
            if columns is FIELD_COLUMNS:
                if section != "parameters":
                    # Export effective roles explicitly: handwritten worksheets
                    # have helpful defaults, but export/import must not activate
                    # an originally inactive field or stop direct modeling.
                    row.setdefault("is_response", False)
                    row.setdefault("model_base", True)
                    if section == "measurements": row.setdefault("measured_at", "unknown")
                if "bounds" in row: row["lower"], row["upper"] = row.pop("bounds")
                rule = row.pop("execution_rounding", {})
                for key in ("mode", "digits", "step", "origin"):
                    if key in rule: row[f"execution_{key}"] = rule[key]
                extra_rule = {k: v for k, v in rule.items() if k not in ("mode", "digits", "step", "origin")}
            else: extra_rule = {}
            extra = {k: v for k, v in row.items() if k not in {key for _, key in columns} or v is None}
            if extra_rule: extra["execution_rounding"] = extra_rule
            row["extra"] = extra or None
            _append(sheet, [row.get(key) for _, key in columns])
    settings = workbook.create_sheet("模板设置")
    _append(settings, ["属性", "值", "类型（可留空）"])
    for key, value in _flatten({k: v for k, v in data.items() if k not in {s for s, _ in TABLES.values()}}):
        # JSON null distinguishes a stored null from a new empty cell.
        _append(settings, [key, "null" if value is None else value, "null" if value is None else type(value).__name__])
    for sheet in workbook:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="2563EB")
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(65, max(16, max(len(str(c.value or "")) for c in column) + 2))
    workbook.save(path)
    workbook.close()


def _parse(key, value):
    if value is None or (isinstance(value, str) and not value.strip()): return None
    if isinstance(value, str): value = value.strip()
    if key in BOOL_KEYS:
        if type(value) is bool: return value
        mapping = {"是": True, "否": False, "true": True, "false": False, "1": True, "0": False}
        if str(value).lower() not in mapping: raise ValidationError("开关需填写是/否或 true/false")
        return mapping[str(value).lower()]
    if key in INT_KEYS:
        number = float(value)
        if not number.is_integer(): raise ValidationError("小数位数和版本需为整数")
        return int(number)
    if key in NUMBER_KEYS: return float(value)
    if key in ("extra", "coefficients"):
        result = json.loads(value) if isinstance(value, str) else value
        if not isinstance(result, dict): raise ValidationError("需要 JSON 属性组")
        return result
    if key == "values":
        if isinstance(value, str) and value.startswith("["): return json.loads(value)
        return [v.strip() for v in str(value).replace("，", ",").split(",") if v.strip()]
    if key in ("value_type", "measured_at", "execution_mode", "direction", "transform"):
        return ALIASES.get(value, value)
    return value


def read_template_excel(path):
    workbook = load_workbook(path, data_only=False)
    try:
        if not any(title in workbook.sheetnames for title in TABLES):
            raise ValidationError("不是模板定义 Excel：需要“输入参数”“原始测量”等工作表，可先导出模板作为填写格式")
        data = blank_template()
        for title, (section, columns) in TABLES.items():
            if title not in workbook: continue
            sheet = workbook[title]
            headers = {cell.value: index for index, cell in enumerate(sheet[1]) if cell.value is not None}
            expected = {label for label, _ in columns} | {key for _, key in columns}
            unknown = set(headers) - expected
            if unknown: raise ValidationError(f"{title}：未知表头 {', '.join(map(str, unknown))}")
            required = "内部名称" if columns is FIELD_COLUMNS else "响应或指标" if section in ("objectives", "outcome_constraints") else "输入参数" if section == "knowledge_priors" else "系数"
            if required not in headers and dict(columns)[required] not in headers:
                raise ValidationError(f"{title}：缺少表头 {required}")
            for row_number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
                if all(c.value is None or str(c.value).strip() == "" for c in cells): continue
                try:
                    row = {}
                    for label, key in columns:
                        index = headers.get(label, headers.get(key))
                        if index is None: continue
                        cell = cells[index]
                        value = cell.value
                        if cell.data_type == "f" and key != "expression":
                            raise ValidationError(f"{label} 请填写实际值，不能使用 Excel 单元格公式")
                        if key == "expression" and isinstance(value, str): value = value.removeprefix("=")
                        value = _parse(key, value)
                        if value is not None: row[key] = value
                    row = {**row.pop("extra", {}), **row}
                    if columns is FIELD_COLUMNS:
                        row.setdefault("value_type", "float"); row.setdefault("unit", "1")
                        if "lower" in row or "upper" in row:
                            if not {"lower", "upper"} <= row.keys(): raise ValidationError("下限和上限需同时填写")
                            row["bounds"] = [row.pop("lower"), row.pop("upper")]
                        rule = row.get("execution_rounding", {})
                        for key in ("mode", "digits", "step", "origin"):
                            if f"execution_{key}" in row: rule[key] = row.pop(f"execution_{key}")
                        if rule: row["execution_rounding"] = rule
                        from experiment_planner.domain.template import parse_value
                        if "values" in row: row["values"] = [parse_value(v, row) for v in row["values"]]
                        if "fixed_value" in row: row["fixed_value"] = parse_value(row["fixed_value"], row)
                        if section == "parameters" and row["value_type"] == "text": row["use_as_model_input"] = False
                        if section != "parameters":
                            row.setdefault("is_response", row["value_type"] not in ("text", "category"))
                            row.setdefault("model_base", section == "measurements")
                        if section == "measurements": row.setdefault("measured_at", "after")
                    if section == "objectives": row.setdefault("direction", "maximize")
                    data[section].append(row)
                except (ValueError, TypeError, KeyError) as exc:
                    raise ValidationError(f"{title} 第 {row_number} 行：{exc}") from exc
        if "模板设置" in workbook:
            for row_number, (key, value, *rest) in enumerate(workbook["模板设置"].iter_rows(min_row=2, values_only=True), 2):
                if key is None: continue
                try:
                    key = str(key).strip()
                    if key.split(".")[0] in {s for s, _ in TABLES.values()}: raise ValidationError("字段与目标请在对应工作表填写")
                    kind = rest[0] if rest else None
                    if kind == "str": value = str(value) if value is not None else ""
                    elif isinstance(value, str):
                        try: value = json.loads(value)
                        except json.JSONDecodeError: value = ALIASES.get(value, value)
                    value = _parse(key, value) if key in INT_KEYS else value
                    parts = key.split("."); target = data
                    for part in parts[:-1]: target = target.setdefault(part, {})
                    target[parts[-1]] = value
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValidationError(f"模板设置 第 {row_number} 行：{exc}") from exc
        return normalize_draft(data)
    finally: workbook.close()


def read_template_draft(path):
    if Path(path).suffix.lower() == ".xlsx": return read_template_excel(path)
    with open(path, encoding="utf-8") as source: return normalize_draft(json.load(source))
