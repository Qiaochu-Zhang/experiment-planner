# 实验规划助手：Python 源码版

**第一次使用、没有编程基础：请先看 [Windows 新手使用教程](Windows新手使用教程.md)。** 教程按 1、2、3 等步骤说明安装 PyCharm、新建 Python 3.12 环境、复制文件、安装依赖和操作程序。

**想弄懂预测能否删除、epsilon、比值目标、变化模式、双变量和各项参数：请看 [参数与操作白话说明](参数与操作白话说明.md)。** 说明按当前代码逐项解释，并附数值例子和操作步骤。

使用 PyCharm 打开本文件夹，选择 **Python 3.12** 解释器，安装
`requirements.txt` 中的依赖，然后运行 **`main.py`**。本文件夹包含独立的应用源码、
字体、ICP 模板、测试和示例，可脱离父级仓库单独复制使用，无需 EXE 或 PyInstaller。

这是可以直接在 Python / PyCharm 中运行的完整源码工程。桌面界面使用中文，计算在本机完成。
功能基线是 [项目说明 V1.1](docs/project_spec.md)。本版复用已有计算核心，并增加模板编辑、导入映射、交叉布局、预测与趋势图入口。
**“完整源码”不等于全部需求已完成验收**：尚未实现的科学计算组合和界面功能列在 [功能对照与限制](docs/coverage.md)，不能把本版称为通过全部 A01–A50 的正式软件。

所有 Markdown 文档均提供中文说明。中文文档目录、已完成工作和验证记录见 [开发工作记录](docs/开发工作记录.md)。命令、文件名、接口字段和软件名称保留原文，以便直接使用。

## PyCharm 启动（Windows）

1. 将整个 `python-version` 文件夹复制到本机，使用 PyCharm 的 **Open（打开）** 打开该文件夹。
2. 为项目创建 **Python 3.12 的虚拟环境**。本工程的版本约束是 `>=3.12,<3.13`。
3. 在 PyCharm 的 Terminal（终端）中确认 `python --version` 为 3.12，然后执行：

   ```powershell
   python -m pip install --upgrade pip
   python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
   python -m pip install -r requirements.txt
   ```

4. 右键 `main.py` → **Run 'main'（运行 main）**。使用普通 Python 运行配置，不使用 Python Console（Python 控制台）执行整个脚本；后台计算使用 `multiprocessing` 的 spawn 进程启动方式。
5. 点击「新建项目」，选择一个新 `.sqlite` 文件，即可开始录入实验。

也可不用 PyCharm，从终端创建环境并运行：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

`requirements.txt` 已逐项列出全部直接运行依赖及用途（包括 `filelock`），版本约束与 `pyproject.toml` 一致；间接依赖由 pip 自动安装。末尾的 `-e .` 用于安装本项目。测试依赖另见 `requirements-dev.txt`。如果安装后仍提示 `No module named ...`，请确认终端安装依赖使用的 Python 与 PyCharm 运行配置选择的解释器一致。

依赖安装需要网络或预先准备的本地 wheel。**安装完成后的实验计算、绘图、存储不需要在线服务**。不要将父目录的虚拟环境直接复制到另一台机器。
两个版本的包名均为 `experiment-planner`，请为这个文件夹使用独立虚拟环境。

## Linux / macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

Linux CPU 环境可先用上面的 PyTorch CPU 源安装 `torch`。Qt 图形窗口需要桌面显示环境及系统图形库；Ubuntu 缺少相关库时可安装 `libgl1`、`libegl1`、`libxcb-cursor0`、`libxkbcommon-x11-0`。无桌面的服务器可以运行命令行与离屏测试。macOS、Windows 的完整人工操作尚未在本次环境验证。

## 一次完整练习

在工程目录执行，以下文件必须使用尚不存在的新路径：

```bash
python main.py --demo local-data/demo.sqlite
python main.py --project local-data/demo.sqlite
```

1. 示例有 12 条明确标识的合成记录，不代表真实机台物理规律。
2. 「下一批实验」先选择并保存分母策略；使用有效区域或稳定化策略时必须填写正数 epsilon，单位 nm。
3. 选择 GP-RBF、GP-Matérn 2.5 或贝叶斯线性模型，设置本轮总数 `n`、基准、变化模式和复测编号。
4. 单变量每点改变一项；双变量可选择最多/恰好两项；交叉布局输入两个变量的新值，例如 `{"cl2_sccm":20,"rf_w":30}`。基准复测、单 A、单 B、AB 都计入 `n`。
5. 生成结果自动保存为待做记录。选择实验行并「更正选中实验 / 回填」，填写实际条件和测量结果。原建议与旧预测保留。
6. 「预测 / 趋势图」从选中实验复制条件，可以修改数值；留空图变量只做预测，填写一/两项数值变量则保存 PNG 并显示图形。使用「下一批实验」选择的模型。
7. 「模板 / 公式 / 先验」通过 JSON 编辑配置。保存自动递增版本、校验公式与角色，并重算派生值。结构/范围变更需要从导出的新模板创建新项目。
8. 导入 CSV/XLSX 可配置表头映射，先校验和预览再保存。导出保留完整精度；迁移项目使用「一致性备份」，再在另一环境打开备份数据库。

无需操作界面的完整代码示例：

```bash
python examples/workflow.py --output local-data/workflow
```

该脚本完成建项目、合成测量录入、拟合、推荐、回填、预测、绘图、CSV/XLSX/JSON 导出及 SQLite 备份恢复。输出目录必须尚不存在。

## Python 和命令行接口

`src/experiment_planner/` 是完整业务源码；入口不依赖父目录代码。
可从 Python 导入 `Project`、`PlannerService`、`BatchRequest`、`generate`、`analyze`。
可执行示例见 [workflow.py](examples/workflow.py)。

```bash
python cli.py --help
python cli.py records local-data/demo.sqlite
python cli.py builtin-template local-data/template.json
python cli.py template local-data/demo.sqlite --input local-data/template.json
python cli.py recommend local-data/demo.sqlite examples/batch.json
python cli.py recommend local-data/demo.sqlite examples/batch.json --commit
python cli.py predict local-data/demo.sqlite examples/prediction.json
python cli.py export local-data/demo.sqlite local-data/records.xlsx
python cli.py backup local-data/demo.sqlite local-data/backup.sqlite
python cli.py history local-data/demo.sqlite
```

模板更新前要编辑 `template_version` 为大于当前版本的整数；刚导出的内置模板版本为 1，不能不加修改地覆盖已有版本。
`recommend` 默认只返回预览，`--commit` 才保存待做批次；含比值推荐前仍须明确保存分母策略。

`record` 命令的 JSON 格式：

```json
{
  "conditions": {"cl2_sccm":20,"bcl3_sccm":10,"ar_sccm":10,"icp_w":300,"rf_w":30,"pressure_mt":5,"electrode_temp_c":20,"etch_time_s":60},
  "observations": {
    "sio2_initial_nm":{"value":100,"uncertainty":{"kind":"std","amount":1}},
    "sio2_remaining_nm":{"value":90,"uncertainty":{"kind":"std","amount":1}},
    "sin_initial_nm":100,
    "sin_remaining_nm":99
  },
  "status":"completed",
  "note":"实验备注",
  "field_notes":{"cl2_sccm":"参数备注"}
}
```

执行 `python cli.py record 项目.sqlite record.json` 新增；加 `--id 1` 更正/回填编号 1。更正 JSON 必须包含想保留的完整测量和备注。
导入预览为 `python cli.py import 项目.sqlite 数据.xlsx`，加 `--mapping mapping.json` 指定映射，加 `--commit` 提交。映射格式为 `{"原表头":"模板字段名"}`。
`predict` 请求可额外带 `plot_path`、`variables`、`metric`、`points`（2–30），详见示例脚本。

## 计算口径

- `A = SiO2 初始厚度 − 剩余厚度`，`B = SiN 初始厚度 − 剩余厚度`，均保留符号。
- 默认 Pareto 目标为最大化 `abs(A)`、最小化 `abs(B)`、最大化 `abs(A/B)`。
- 原始比值和稳定化指标分别保留；原始比值后验只报告样本分位数，不声明均值/方差存在。
- 显示取整不改变原始数据；缺失、零、False、失败、比值无效互相区分。
- 测量 ± 值须注明标准不确定度、SEM、误差界限等含义；未知误差不视为零。
- 模型区间表示潜在响应，不自动包含未来量测误差。数据不足时输出初始化条件，不伪造预测。
- 不支持的模型/先验/误差组合会报出能力限制，详见 [功能对照](docs/coverage.md)。

## 验证与文件结构

2026-09-20 新增预测可信度专项验证：[测试计划](实验预测测试计划.md)、[实际结果与适用边界](实验预测测试结果.md)、[全部改动记录](实验预测测试改动记录.md)。本轮包含独立留出误差与区间覆盖检查；合成验证不能替代真实机台回测。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python main.py --self-test local-data/self-test
```

Linux 服务器 GUI 冒烟检查：`QT_QPA_PLATFORM=offscreen python main.py --smoke`。
`--self-test` 输出目录必须尚不存在，会检查三个数值模型、后台进程和备份恢复。
本次验证记录见 [validation.md](docs/validation.md)。

```text
main.py                 PyCharm / GUI 启动入口
cli.py                  命令行入口
pyproject.toml          Python 3.12、依赖与包配置
requirements*.txt       应用与测试依赖安装入口
src/experiment_planner/ 完整业务、模型、数据库、界面代码和字体/模板
examples/               完整工作流和 JSON 请求
tests/                  核心、模型、存储、后台、GUI 与独立运行测试
docs/                   原项目说明、需求对照与验证说明
```

源码与资源均随文件夹提供；Python 解释器和第三方依赖不在其中。离线部署时，在相同系统/架构、Python 3.12 的联网机器上先准备依赖 wheel，再通过 `pip install --no-index --find-links wheelhouse .` 安装；wheelhouse 还需包含构建依赖 setuptools。实际离线安装必须在目标机器验证。
