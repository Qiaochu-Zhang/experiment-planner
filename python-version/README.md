# 实验规划助手 · Python 源码版 0.2

支持标准 **CPython 3.12、3.13**（`>=3.12,<3.14`，不含自由线程构建）。本目录可以独立复制使用，运行 `main.py` 打开中文桌面程序；计算、帮助文档和项目存储均可在依赖安装后离线使用。

- 第一次安装：[Windows 新手教程](Windows新手使用教程.md)。
- 界面变量、公式、探索策略的完整说明：[使用说明](src/experiment_planner/resources/help/使用说明.md)。程序中的说明按钮和蓝色悬停链接打开同一份文件。
- 原问题的新版回答：[回答.md](回答.md)；[参数与操作说明](参数与操作白话说明.md)。
- [0.2 版本改动记录](版本改动记录.md)、[验证结果](docs/validation.md)、[功能与限制](docs/coverage.md)。

## 安装与启动

在本目录创建独立环境，不与父目录旧工程共用可编辑安装：

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Python 3.12 可将首行的 `3.13` 改成 `3.12`。Linux 使用 `python3.13 -m venv .venv` 和 `.venv/bin/python`。PyCharm 打开本目录，选择此解释器，以普通 Python Run 配置运行 `main.py`，不要在 Python Console 中运行整个程序；后台任务使用 spawn 子进程。

## 常用操作

1. 新建或打开 `.sqlite` 项目。常用工作台预设精度、先验、目标、录入、回填、推荐、预测入口；“自定义常用功能”可增减其他按钮，重启后保留。
2. 录入真实实验；允许同条件、不同结果。历史数据可用 [CSV / Excel 模板](examples/import_templates/README.md)，导入先选择列对应关系并预览。
3. “推荐工艺精度”设置每项输入的 digits 或步长；“先验关系定义”选择关系、系数、强度和来源；“实验优化目标”勾选一个或多个目标。这些操作会写入项目模板快照，无需手写 JSON。
4. 新版默认目标：最大化 **A**、最小化 **|B|**、最大化 **A/B**。A、B 为两种初始厚度减剩余厚度，保留符号。A 和 A/B 不取绝对值。
5. 比值推荐前明确选择分母策略。稳定化采用保留符号的分母截断，零分母使用 `+epsilon` 的明确约定；原始比值仍独立保留。
6. “推荐下一批实验”设置总数、探索强度、专门探索名额及复测。总数 6、无复测、探索 2 时，生成 2 个专门探索点及 4 个常规评分点。数据不足时使用初始化策略并说明原因。
7. 计算后自动保存待做记录；完成后选择对应行回填，不覆盖原来的复测来源记录。“预测与趋势图”使用条件表单和变量选择按钮。
8. “更多功能 → 项目与模板”提供新建/复制模板、全部属性树形编辑、导出、从模板创建项目、备份和历史。字段、范围、公式、约束均可通过鼠标与键盘编辑；能力边界见说明。

旧项目继续使用原来的模板快照。需要改用新版目标时，在目标表单点击“应用新版 ICP 目标”后保存；旧比值绝对值字段和旧批次仍保留。字段类型、范围、单位等结构变更当前需要新项目，界面提供完整的模板保存与新建流程。

## 算法与接口

默认 GP / RBF，另支持 GP / Matérn 2.5、贝叶斯线性。每个基础响应使用全部有效完成/部分结果记录，同条件复测逐条参与拟合。512 个后验样本汇总预测；原始比值不声明有限均值或方差。预测区间为潜在响应区间。

探索强度默认 0，专门探索名额默认 0。强度改变常规候选评分中的不确定性加分；专门名额按可行性、不确定性和待做条件距离选择。算法公式、128 个探索后验样本和追溯字段见 [0.2 规范](docs/v0.2_spec.md)。这两个参数不是各实验目标的加权比例。

```bash
python cli.py --help
python cli.py builtin-template local-data/template.json
python cli.py create local-data/project.sqlite --template local-data/template.json
python cli.py template local-data/project.sqlite
python cli.py recommend local-data/project.sqlite examples/batch.json
python cli.py recommend local-data/project.sqlite examples/batch.json --commit
python cli.py predict local-data/project.sqlite examples/prediction.json
python cli.py import local-data/project.sqlite records.xlsx --commit
python cli.py export local-data/project.sqlite records.xlsx
python cli.py backup local-data/project.sqlite backup.sqlite
```

命令行更新模板仍需自行增加 `template_version`；界面自动处理。CLI 的 `recommend` 默认预览，`--commit` 才写入；GUI 的“计算并保存”会写入。`BatchRequest` 可设置 `exploration_strength`、`exploration_count`、`pool_size`、`seed`；模板默认设置由桌面读取，CLI 请求应明确填写所需覆盖值。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python main.py --self-test local-data/self-test
python examples/workflow.py --output local-data/workflow
```

输出目录须尚不存在。Linux 无桌面验证使用 `QT_QPA_PLATFORM=offscreen`。测试结果与适用边界见 [验证记录](docs/validation.md)，不以合成数据测试替代真实机台效果验证。
