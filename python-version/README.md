# 实验规划助手 · Python 源码版 0.3.0

支持标准 **CPython 3.12、3.13**。运行 `main.py` 打开中文桌面程序；计算、帮助和项目存储均可在依赖安装后离线使用。软件支持自行定义实验输入、测量、公式与目标，内置模板只是可选示例。

- [Windows 新手教程](Windows新手使用教程.md)
- [通用变量与操作说明](src/experiment_planner/resources/help/使用说明.md)
- [问题与回答](回答.md)、[参数与操作说明](参数与操作白话说明.md)
- [版本记录](版本改动记录.md)、[验证结果](docs/validation.md)、[功能边界](docs/coverage.md)

## 安装与启动

在本目录创建独立环境，不与父目录旧工程共用可编辑安装：

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Python 3.12 可替换首行版本号。Linux 使用 `python3.13 -m venv .venv` 和 `.venv/bin/python`。PyCharm 打开本目录，选择此解释器，以普通 Python Run 配置运行 `main.py`，不要在 Python Console 中运行整个程序。

## 模板与项目

“新建 / 复制 / 修改模板”可选择从空白开始、复制当前项目、打开本地模板文件或复制内置示例。空白草稿没有默认工艺字段。

“参数 / 测量 / 公式（增删改名）”提供字段表单：可定义名称、类型、单位、范围/离散值/固定值、备注及公式。内部名称改动同步更新已知引用；删除会提示连带移除的公式、目标、先验及约束。“全部属性”可编辑其他属性与扩展配置。精度、先验和目标仍有专用表单。

至少配置一个输入、一个直接建模的响应以及有效目标后保存模板，再通过“从模板新建项目”使用它。可选单目标、多目标折中或加权目标；实验目标以当前模板为准。

空项目可直接更换结构。已有实验且结构不兼容时，编辑成果可以直接另存为模板，或用它新建项目；无需从头改一遍。兼容配置可在原项目保存并更新版本。原有实验不会被套用新的字段含义，新增参数也不会自动补造数据。

## 导入与日常操作

常用页默认有“导入 CSV / Excel”。核对列映射后，程序按**模板输入参数顺序**检查前 30%（向上取整，至少一项）：这些值全部为空时，该行为结束标记，该行及后续行不导入。例如 8 个输入检查前 3 个，11 个输入检查前 4 个。

0 和“否”不是空值。结束前的其他错误仍需修复。预览明确显示停止行、检查字段和待导入数量，确认后点击保存。文件表头缺少用于判断的输入列时会提示映射问题。内置示例文件位于 [导入示例](examples/import_templates/README.md)；自建模板可在“项目与模板 → 下载导入 CSV / Excel 模板”生成自己的空白输入表；Excel 附填写说明。

允许同条件不同结果独立保存。实验表可单击、Ctrl 多选、Shift 连选或拖选，确认后删除所选实验。删除记录不参与当前训练、推荐和普通导出，原数据保留在审计中；旧批次保留，常见已保存修改可用 Ctrl+Z 撤销、Ctrl+Y 重做，删除后的空缺编号可复用。完整 SQLite 备份保留全部审计。

推荐时设置总数、探索强度、专门探索名额及复测。总数包含复测；专门探索占用新条件位置，默认强度和名额都是 0。计算完成保存为待做记录，实验完成后回填对应编号。预测与趋势图的参数和响应来自当前模板，可导出当前预测与图线的完整 Excel/CSV 数据。精度页可分别设置输入、测量和派生指标的显示位数，不改变保存值和模型。

帮助文档只介绍通用软件操作，不收录具体模板的工艺参数清单。通用操作的悬停简述带蓝色详细链接，模板专有变量不自动弹出通用说明框；离开变量与弹窗后约 1 秒关闭，移入弹窗可以继续点击。帮助为静态文件，不根据模板自动生成；字段自身说明请写在模板备注中。

## 接口与验证

```bash
python cli.py --help
python cli.py create local-data/project.sqlite --template local-data/template.json
python cli.py template local-data/project.sqlite
python cli.py recommend local-data/project.sqlite examples/batch.json
python cli.py predict local-data/project.sqlite examples/prediction.json
python cli.py import local-data/project.sqlite records.xlsx --commit
python cli.py export local-data/project.sqlite records.xlsx
python cli.py backup local-data/project.sqlite backup.sqlite
```

请求中的字段名应匹配所选模板。CLI 推荐默认预览，`--commit` 才写入；导入输出包含停止行和说明。GUI 的“计算并保存”会写入项目。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q -p no:cacheprovider
python main.py --self-test local-data/self-test
```

自检输出目录须尚不存在。Linux 无桌面验证设置 `QT_QPA_PLATFORM=offscreen`。本版支持数据库版本 1 和 2；删除功能沿用版本 2 标记。能力与验证范围见上方文档，不以合成数据测试代替真实机台效果。
