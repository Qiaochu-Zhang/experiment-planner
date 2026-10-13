# Python 源码版验证报告

## 可选输入不确定度 · 2026-10-13

本目录 Linux / Python 3.12 / Qt offscreen 环境验证 **363 项不同测试**：59 项单元、256 项集成、48 项相关界面测试。包括本次新增的 **47 项**（38 项计算/集成、9 项界面）。

首次综合运行结果为 **362 passed、1 failed**，236.64 秒：[日志](evidence/input-uncertainty-2026-10-13/tests.txt)、[JUnit](evidence/input-uncertainty-2026-10-13/tests.xml)。唯一失败是通用帮助文档的既有材料名称例子不符合“通用说明不绑定内置模板”的检查；将其改成通用厚度例子后，仅重跑该项，结果 **1 passed**，4.74 秒：[复查日志](evidence/input-uncertainty-2026-10-13/help-recheck.txt)、[JUnit](evidence/input-uncertainty-2026-10-13/help-recheck.xml)。最终上述 363 项均有通过结果，不将重复运行累计为新测试。综合运行含 21 条依赖弃用、矩阵 jitter 和合成布尔约束全不满足的采集函数提示，没有将警告屏蔽或把失败日志改写为通过。

综合运行覆盖全部 `tests/unit`、`tests/integration`，以及 GUI 的 `test_input_uncertainty_ui.py`、`test_template_workflow.py`、`test_general_templates.py`、`test_plot_ranges.py`、`test_failure_diagnostics.py`。使用 `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest ... -q -p no:cacheprovider`。未重跑其他 GUI 文件。

新增验证包括：

- 开关默认关闭，与没有新配置的模板得到完全相同的预测和推荐；只扰动勾选输入，关闭后保存已有设置。
- 正态/均匀条件采样、边界均值解析对照、相同种子复现、线性约束、无可行体积时的明确失败及非法尺度拒绝。
- 线性均匀分布解析分位数对照；非线性目标先逐样本变换再平均；合成窄峰名义值更高、宽峰平均表现更好的对照。
- GP/RBF、GP/Matérn、贝叶斯线性 × 单目标/加权/Pareto 的九种组合，含输出约束、探索、多候选及待做点；布尔与数值混合响应、派生公式和严格 JSON 序列化。
- 真实后台进程的预测/推荐返回、新配置保存/撤销/重做、字段改名、JSON/Excel 模板往返、两种预测口径导出及趋势图；训练记录及原始输入保持不变。
- 鼠标开启与逐项勾选、非法输入提示、模板页面重建、150% 字体与缩小窗口的保存按钮可用性。

已查看 [默认关闭](evidence/input-uncertainty-2026-10-13/default-off.png)、[仅时间开启](evidence/input-uncertainty-2026-10-13/selected-input.png)、[放大字体](evidence/input-uncertainty-2026-10-13/font150-small.png)、[预测对照页面](evidence/input-uncertainty-2026-10-13/prediction.png)、[含输入波动的趋势图](evidence/input-uncertainty-2026-10-13/trend.png)。放大字体时表格可滚动，窗口受既有工具栏最小宽度限制。合成预测的完整 [JSON](evidence/input-uncertainty-2026-10-13/prediction.json)、[CSV](evidence/input-uncertainty-2026-10-13/prediction.csv)、[Excel](evidence/input-uncertainty-2026-10-13/prediction.xlsx) 也已保存；无用户实验数据。

结果表示有限输入采样与模型后验传播，尾部分位数会受采样数/种子影响；推荐按平均目标而非最坏情况评分。历史输入误差训练、输入相关噪声、真实机台标定、Windows 实机及 Python 3.13 本轮未验证。当前边界条件见 [功能边界](coverage.md)，不能据合成验证宣称实际预测一定更准。

## 非有限预测区间显示与诊断 · 2026-10-13

在本目录独立 Linux / Python 3.12 / Qt offscreen 环境完成 **143 项不同测试，0 失败、0 跳过**，包含 33 项新增回归：

| 验证组 | 实际结果 |
| --- | --- |
| 非有限预测、预测正确性、目标策略、历史导出及趋势范围 | **91 passed**，17.23 秒，6 条既有依赖弃用与矩阵 jitter 警告 |
| 失败诊断界面、精度与导出界面、绘图范围界面、后台失败/绘图、源码版入口、真实模型及时间响应 | **50 passed**，104.09 秒，10 条既有依赖弃用与矩阵 jitter 警告 |
| 后补的有限样本均值/分位数溢出边界 | **2 passed**；仅运行这两个新增用例，不重复累计前述测试 |

所有组均使用 `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest ... -q -p no:cacheprovider`。第一组文件：`test_prediction_nonfinite.py`、`test_prediction_validity.py`、`test_v02_strategy.py`、`test_history_exchange.py`、`test_trend_ranges.py`；第二组：`test_failure_diagnostics.py`、`test_history_export_ui.py`、`test_plot_ranges.py`、`test_worker_failures.py`、`test_worker_plots.py`、`test_python_edition.py`、`test_models.py`、`test_time_dependence.py`；最后一组使用 `test_prediction_nonfinite.py -k statistics_overflow`。测试进程均正常退出；未重跑整个仓库测试集。

使用合成联合后验样本 `(SiO2, SiN) = (2,0), (4,2), (9,3), (16,4)`、有效区域策略及两位显示小数，直接加载修改前的汇总与显示代码复现：目标区间为 `[2.075, 3.5, NaN]`，显示抛出 `ValidationError: 不能显示非法数值`。修改后明确报告 3/4 有限样本，对有限比值 `[2,3,4]` 的分位数为 `[2.05,3,3.95]`，可行概率仍使用全部样本并保持 75%。[复现前后记录](evidence/prediction-nonfinite-2026-10-13/reproduction.json)。

新增覆盖带符号/绝对值比值、四种比值策略、有无显示位数、部分及全部零分母、一般自定义公式、基础响应 `NaN` / 正负无穷大、旧报告非法区间、有限样本统计溢出、严格 JSON 序列化、CSV 说明、绘图失败定位和真实窗口完成回调。两种 GP 与贝叶斯线性模型的既有真实拟合/推荐/后台流程也通过。真实窗口测试确认分析没有改写实验数据，结束后按钮与计时器状态正常。

已实际查看 [部分样本不可用的结果页](evidence/prediction-nonfinite-2026-10-13/partial-prediction.png)、[比值全部不可用的结果页](evidence/prediction-nonfinite-2026-10-13/unavailable-prediction.png)、[带有限样本警告的趋势图](evidence/prediction-nonfinite-2026-10-13/partial-trend.png)。截图与数值均为合成复现，没有用户原始实验数据；未做 Windows 实机验证，不能据此断定用户这一次的具体分母或指标。

## 基准误差与高可信实验的组合设置 · 2026-10-13

在本目录独立环境 Linux / Python 3.12.3 / Qt offscreen 下完成 **271 项不同测试，0 失败、0 跳过**；两组进程退出码均为 0：

| 验证组 | 实际结果与证据 |
| --- | --- |
| 全部单元与集成测试，排除本次未修改的后台失败及后台取消/绘图两个文件 | **237 passed**，78.86 秒，14 条既有依赖弃用与矩阵 jitter 警告。[日志](evidence/relative-uncertainty-2026-10-13/core-tests.txt)、[JUnit](evidence/relative-uncertainty-2026-10-13/core-tests.xml)。 |
| 误差设置、撤销导出、失败诊断及原型窗口 GUI | **34 passed**，88.69 秒。[日志](evidence/relative-uncertainty-2026-10-13/gui-tests.txt)、[JUnit](evidence/relative-uncertainty-2026-10-13/gui-tests.xml)。 |

两个误差设置测试文件最终共 49 项，包含本次新增 18 项；早期 47 项定向检查已经包含于最终回归，不重复累加。布局压缩后新增了小窗口及 1.5 倍字体两项检查，验证表单可滚动、汇总与应用按钮保持可见。[定向日志](evidence/relative-uncertainty-2026-10-13/focused-tests.txt)。

验证包含：一次事务同时应用基准与高可信误差；仅补齐其他实验的未知误差；高可信记录更小/相等误差保留；输入非法比例、范围外高可信编号时不修改数据；备注追加与保存重开；一步撤销/重做；重复相同设置不生成新备注和版本；按嵌套公式追溯原始测量；读取共同 1σ；逐项预览及真实按钮提交。两个 GP 核的实际训练验证了组合补齐后不再触发混合噪声检查，并保持原始测量值不变。

[已实际查看的最终界面截图](evidence/relative-uncertainty-2026-10-13/dialog.png) 使用 4 条合成记录：快速选择 SiO2 刻蚀量所需的 2 项测量，基准 1 nm、高可信比例 0.5；实验 1 使用 0.5 nm，实验 2 原有 0.1 nm 被保留，实验 3/4 补齐 1 nm。因此预览显示修改 3 条实验 / 6 项测量，保留 2 项已知误差。截图生成的离屏平台及字体缓存提示没有妨碍显示和保存。

复现（工作目录 `python-version`，设置 `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen`）：

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/integration --ignore=tests/integration/test_worker_failures.py --ignore=tests/integration/test_worker_plots.py
.venv/bin/python -m pytest -q -p no:cacheprovider tests/gui/test_measurement_uncertainty_ui.py tests/gui/test_history_export_ui.py tests/gui/test_failure_diagnostics.py tests/gui/test_window.py
```

本次没有重跑被排除的 9 项后台测试及其他 GUI 文件；其上一次结果见下节。没有 Windows 实机、Python 3.13 或用户真实实验数据验证。比例和自动备注代表用户明确设定的假设，不是测量误差标定，也不改变现有模型对混合噪声和共享误差的能力限制。

## 统一设置测量误差 · 2026-10-13

在本目录独立环境 Linux / CPython 3.12.3 / PySide6 6.12.0 / Qt offscreen 下完成 **279 项不同测试，0 失败、0 跳过**。依赖版本及环境见 [环境记录](evidence/uniform-uncertainty-2026-10-13/environment.json)。最终按下面四组运行，各组进程退出码均为 0：

| 验证组 | 实际结果与证据 |
| --- | --- |
| 全部单元与集成测试，先分离两个后台进程文件 | **224 passed**，66.13 秒；14 条警告为依赖弃用与原有矩阵 jitter 提示。[日志](evidence/uniform-uncertainty-2026-10-13/core-tests.txt)、[JUnit](evidence/uniform-uncertainty-2026-10-13/core-tests.xml)。 |
| 后台异常、进程意外退出、警告保留 | **6 passed**，20.31 秒，2 条依赖弃用警告。[日志](evidence/uniform-uncertainty-2026-10-13/worker-tests.txt)、[JUnit](evidence/uniform-uncertainty-2026-10-13/worker-tests.xml)。 |
| 取消后台任务与一/二维绘图 | **3 passed**，8.49 秒。[日志](evidence/uniform-uncertainty-2026-10-13/plot-tests.txt)、[JUnit](evidence/uniform-uncertainty-2026-10-13/plot-tests.xml)。 |
| 新设置弹窗、失败诊断、窗口布局、撤销导出、多选删除及原型窗口 | **46 passed**，209.06 秒。[日志](evidence/uniform-uncertainty-2026-10-13/gui-tests.txt)、[JUnit](evidence/uniform-uncertainty-2026-10-13/gui-tests.xml)。 |

新增测试共 **31 项**（服务/模型 18 项，GUI 13 项），已包含在上述 279 项中，不重复累加。定向测试先通过 31 项；检查截图后，修正标准按钮在显示时被自动改回“保存”的问题，改用明确的“应用设置”，再完成 13 项 GUI 定向复测与上面的最终回归。[初次定向日志](evidence/uniform-uncertainty-2026-10-13/focused-tests.txt)、[按钮修正后的日志](evidence/uniform-uncertainty-2026-10-13/final-ui-tests.txt)。

验证内容包含：选中/全部范围及测量字段选择；仅补齐未知、保留可换算误差、替换区间含义、跳过未测；保留实际测量、备注、记录身份、导入身份、批次/复测信息及共享误差来源；独立/相关差值误差重算；一次版本变化与整批撤销/重做；中途写入失败整批回滚；预览过期拒绝提交；无修改不产生历史；桌面工作副本保存与重新打开。界面通过真实按钮进入弹窗，验证应用、取消、单位与预览数量。

两种真实 GP（RBF 与 Matérn）均验证了：部分已知时错误包含已知/未知实验编号；显式补齐后拟合成功；同条件 10/14 的合成测量，把较小误差分别赋予其中一条后，预测分别靠近该条记录（距离小于 0.5），原始测量值保持不变。这仅证明设置进入似然并影响预测，不是实际设备误差或预测准确率的标定。

[已实际查看的弹窗截图](evidence/uniform-uncertainty-2026-10-13/dialog.png) 使用合成数据，显示 3 条实验 / 10 项将修改、保留已有误差 2 项、跳过未测 4 项。截图生成有离屏平台和字体缓存提示，图片与“应用设置”按钮已检查。

首轮测试因两个新增文件同名而发生 pytest 收集冲突，已将 GUI 文件改名为 `test_measurement_uncertainty_ui.py`：[初次诊断](evidence/uniform-uncertainty-2026-10-13/initial-collection.txt)。随后两次较大组合运行以退出码 143 中止，日志没有给出终止原因，未产生最终 JUnit 汇总，**不计作通过**；保留 [组合运行输出](evidence/uniform-uncertainty-2026-10-13/interrupted-regression.txt) 与 [核心组合输出](evidence/uniform-uncertainty-2026-10-13/interrupted-core.txt)。拆分后的四组覆盖原计划全部 279 项并取得上表通过结果，没有跳过相关测试。

复现四组（工作目录 `python-version`，设置 `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen`）：

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/integration --ignore=tests/integration/test_worker_failures.py --ignore=tests/integration/test_worker_plots.py
.venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_worker_failures.py
.venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_worker_plots.py
.venv/bin/python -m pytest -q -p no:cacheprovider tests/gui/test_measurement_uncertainty_ui.py tests/gui/test_failure_diagnostics.py tests/gui/test_window_layout.py tests/gui/test_history_export_ui.py tests/gui/test_v021_desktop.py tests/gui/test_window.py
```

没有 Windows 实机、Python 3.13 或用户真实项目数据验证；未运行上述文件之外的其他 GUI 测试。全部未知/全部已知噪声的建模限制、相关似然限制及显式保存机制保持现有行为。

## GP 拟合诊断与恢复 · 2026-10-13

在 `python-version/.venv` 的 Linux / CPython 3.12.3 / PySide6 6.12.0 / Qt offscreen 环境验证，BoTorch 0.18.1、GPyTorch 1.15.2、PyTorch 2.8.0+cpu、SciPy 1.18.1。[环境记录](evidence/gp-fitting-diagnostics-2026-10-13/environment.json)。

| 验证 | 实际结果 |
| --- | --- |
| 全部单元测试、全部集成测试、失败诊断与绘图范围 GUI 测试 | **227 passed，0 failed，0 skipped**，87.85 秒；进程退出码 0。[日志](evidence/gp-fitting-diagnostics-2026-10-13/tests.txt)、[JUnit](evidence/gp-fitting-diagnostics-2026-10-13/tests.xml)。涵盖预测、推荐、误差传播、保存、导入导出、后台进程及相关界面。 |
| 最终诊断排版复测 | 将具体失败信息放在长堆栈前后，重新执行 GP 诊断、后台失败和诊断 GUI 测试，**33 passed，0 failed，0 skipped**，34.38 秒；进程退出码 0。这 33 项包含于上面的回归范围，不累加为不同测试数。[日志](evidence/gp-fitting-diagnostics-2026-10-13/final-diagnostics.txt)、[JUnit](evidence/gp-fitting-diagnostics-2026-10-13/final-diagnostics.xml)。 |
| 真实 GP 与模板端点 | RBF/Matérn × 已知/未知噪声 × 普通紧范围/宽度约 `1e-9` 的范围，共 **8 种真实拟合**均返回有限后验；实验点恰好位于两个端点，编码分别为 0 和 1，诊断标记两个边界点且没有越界点。 |
| 恢复路径 | 在合成数据上控制前两次优化失败、第三次执行真实 SciPy 拟合；覆盖变化输入和恒定输入两种情况，确认核参数初值不同、已知观测方差逐项保持不变、原记录未修改、恢复过程可序列化并有提示。不是用户原失败的复现。 |
| 失败与界面证据 | 保留优化器异常前警告、BoTorch 内部捕获的矩阵异常和 DEBUG 日志、原始异常链与数据上下文；非有限输入/响应/方差定位到实验编号，非有限优化目标不作为成功结果，接口错误不反复重试。展开、复制及顶部重看均通过实际 Qt 控件测试。[合成诊断文本](evidence/gp-fitting-diagnostics-2026-10-13/synthetic-diagnostic.txt)、[已查看的展开弹窗截图](evidence/gp-fitting-diagnostics-2026-10-13/expanded-training-diagnostic.png)。 |

首轮扩大回归发现直接 Python 接口可能传入没有数据库编号的记录，新增诊断读取编号时引入了兼容性失败；已改为明确的输入行号标签并增加回归。首次结果为 224 passed / 1 failed，不计作最终通过结果：[初次日志](evidence/gp-fitting-diagnostics-2026-10-13/initial-tests.txt)、[初次 JUnit](evidence/gp-fitting-diagnostics-2026-10-13/initial-tests.xml)。随后完成上表通过的整组重跑。最终排版复测仅调整错误信息展示次序，没有再修改拟合策略。

测试中 14 条警告为依赖弃用及库自动加入 `1e-8` jitter 的数值提示；最终分组为 2 条依赖弃用警告。截图生成还出现离屏平台/字体缓存提示，截图已生成并实际检查。没有 Windows 实机、Python 3.13 或用户原始实验数据验证；本轮没有运行其余 GUI 文件。恢复策略不保证所有数据都能拟合成功，仍失败时保留具体诊断，不生成伪造的预测结果。

复现（在 `python-version`）：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/integration tests/gui/test_failure_diagnostics.py tests/gui/test_plot_ranges.py
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_gp_diagnostics.py tests/integration/test_worker_failures.py tests/gui/test_failure_diagnostics.py
```

实现：[GP 拟合与诊断](../src/experiment_planner/engine/gp_fitting.py)、[模型接入](../src/experiment_planner/engine/models.py)、[后台警告保留](../src/experiment_planner/worker/process.py)。新增数值验证：[GP 诊断测试](../tests/integration/test_gp_diagnostics.py)。

## 计算失败原始诊断 · 2026-10-13

改动范围仅 `python-version`。使用本目录独立虚拟环境，在 Linux / CPython 3.12.3 / PySide6 6.12.0 / Qt offscreen 下分组验证：**74 项相关测试通过，0 失败，0 错误，0 跳过，两组进程退出码均为 0**。依赖检查 `pip check` 通过，加载的源码来自本目录。[环境](evidence/failure-diagnostics-2026-10-13/environment.json)、[结果汇总](evidence/failure-diagnostics-2026-10-13/summary.json)。

| 验证 | 结果与覆盖内容 |
| --- | --- |
| 完整 GUI 测试目录 | **64 项通过**，308.11 秒。包括新增 9 项诊断界面测试，以及原有模板、保存、撤销、选择、帮助、预测范围、普通/小窗口/最大化/全屏/恢复及放大字体回归。[日志](evidence/failure-diagnostics-2026-10-13/gui-tests.txt)、[JUnit](evidence/failure-diagnostics-2026-10-13/gui-tests.xml)。 |
| 后台和启动相关集成测试 | **10 项通过**，32.37 秒。包括新增 4 项真实子进程测试，以及原有取消、正常预测、单/双变量绘图、独立启动和界面清理检查。[日志](evidence/failure-diagnostics-2026-10-13/worker-tests.txt)、[JUnit](evidence/failure-diagnostics-2026-10-13/worker-tests.xml)。 |
| 新诊断交互 | 实际点击弹窗展开按钮与复制按钮，核对原始 Unicode 文本和剪贴板全文，关闭后通过顶部按钮重看；连续失败更新最近诊断，成功计算保留最近失败，缺失诊断时显示明确说明。覆盖校验、启动、管道读取、结果展示与批次提交失败。 |
| 后台错误内容 | 推荐与分析的真实 spawn 子进程返回异常类型、原始消息及调用堆栈；主动终止子进程后返回 PID、退出码和缺失堆栈说明，锁释放、项目快照不变。 |
| 独立启动与预览 | `main.py --smoke` 退出码 0，[启动日志](evidence/failure-diagnostics-2026-10-13/smoke.txt)。实际查看 [顶部重新打开入口](evidence/failure-diagnostics-2026-10-13/reopen-button.png) 和 [展开后的诊断窗口](evidence/failure-diagnostics-2026-10-13/expanded-diagnostic.png)，再次核对展开和复制内容；截图使用合成错误，不是用户实际故障。 |

最初尝试运行整个测试集合时，进程以退出码 143 中断，没有产生完整结果；[中断日志](evidence/failure-diagnostics-2026-10-13/full-suite-interrupted.txt) 不计入通过数量。随后完成上述分组相关验证，本轮不声明全部模型及数值测试通过，也未进行 Windows 实机或 Python 3.13 验证。原始诊断入口已验证，不代表已确定或解决用户原先计算失败的具体原因。

新增测试：[诊断交互](../tests/gui/test_failure_diagnostics.py)、[真实后台失败](../tests/integration/test_worker_failures.py)。操作见 [回答.md](../回答.md) 第 49 节。

复现（在 `python-version`，已安装依赖的独立环境）：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider tests/gui
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_worker_failures.py tests/integration/test_worker_plots.py tests/integration/test_python_edition.py
QT_QPA_PLATFORM=offscreen .venv/bin/python main.py --smoke
```

## 绘图范围与预测问答 · 2026-10-12

改动范围仅 `python-version`。在 Linux / CPython 3.12.3 / PySide6 6.11.2 / Qt offscreen 环境执行完整测试：**247 项通过，0 失败，0 跳过，退出码 0**，耗时 254.02 秒；14 条依赖弃用或数值稳定提示。[完整日志](evidence/trend-ranges-2026-10-12/tests.txt)、[JUnit](evidence/trend-ranges-2026-10-12/tests.xml)。

| 验证 | 覆盖内容 |
| --- | --- |
| 绘图范围 | 一维/二维上下限、默认全范围、固定条件保持不变、模板不被修改；拒绝反序、相等、越界、非有限值和不属于图轴的范围字段。 |
| 合法采样 | 取整后不超出自定义边界；整数输入与线性约束有效；没有合法条件或某轴不足两个不同取值时提示调整。 |
| 界面与后台 | 范围输入与恢复默认、变量切换、项目关闭清理、界面向后台传参、分析进程实际出图且项目快照不变。 |
| 图形输出 | 实际生成一维、二维 PNG；检查图轴上下限与请求一致，包括基准点位于窗口外的情形。导出仍沿用已有的缓存预测/图线导出路径。 |
| 窗口布局 | 既有普通、小窗口、最大化、全屏、恢复、长名称、多字段及字号回归全部通过；增加对第二个绘图变量上限框可滚动访问的检查。另实际查看了 [1024×650 窗口的范围控件截图](evidence/trend-ranges-2026-10-12/range-controls.png)。 |
| GP 训练点与范围 | 两种 GP 在 5 条响应标准不确定度为 0.05 的合成数据上，已测点解析均值距真值小于 0.1，中央 95% 区间宽度小于 0.25；离开另一个固定输入的训练切片后方差大于原值的 4 倍。宽/窄绘图窗口中同一条件的解析均值和方差一致。 |

新增与扩展测试：[范围校验](../tests/unit/test_trend_ranges.py)、[范围表单及请求](../tests/gui/test_plot_ranges.py)、[出图](../tests/integration/test_worker_plots.py)、[后台分析](../tests/integration/test_python_edition.py)、[GP 机制](../tests/integration/test_prediction_validity.py)、[窗口布局](../tests/gui/test_window_layout.py)。回答见 [回答.md](../回答.md) 第 38–43 节。

这些结果验证实现与受控场景；本轮没有取得问题中出现大偏差的真实项目，不能据此认定其预测可靠或确定异常原因。没有新增 GP 单调先验、自动异常点剔除或解析分位数显示。未执行 Windows 实机、Python 3.13 验证或重新构建安装包。

复现（在 `python-version`，使用已安装依赖的解释器）：

```bash
python -m pytest -q -p no:cacheprovider --junitxml=docs/evidence/trend-ranges-2026-10-12/tests.xml
```

## 0.4.2 · 2026-10-10

在 Linux / CPython 3.12.3 / PySide6 6.11.2 / Qt offscreen 环境验证中文布尔选项、项目保存修复与窗口布局；仅修改 `python-version`。

| 验证 | 结果与证据 |
| --- | --- |
| 完整回归 | **223 项通过，0 失败，0 跳过，退出码 0**，277.76 秒；14 条依赖弃用/数值提示。[日志](evidence/v0.4.2/python312-tests.txt)、[JUnit](evidence/v0.4.2/python312-tests.xml)。 |
| 项目保存 | 对只读描述符进行零字节写入以模拟 Windows 同步限制，修改前新建/已存在项目均复现 Errno 9；修改后通过。完整回归覆盖连续保存、同步故障不覆盖原文件、保留待保存状态、重试及原有另存/关闭保存行为。 |
| Excel 文件 | 布尔类型仅“是否”、开关和布尔值仅“是/否”，旧英文布尔读回兼容，固定/离散布尔限制保留；上下端点实际导入通过，相同上下限被拒绝。四份示例重新生成，公式读回及与旧 CSV 的数据一致检查通过。[检查记录](evidence/v0.4.2/excel-check.json)、[复现脚本](../scripts/validate_excel_guidance.py)。 |
| 窗口布局 | 11 项 GUI 回归覆盖普通、1024×650 小窗口、最大化、全屏、恢复；从选中实验复制条件后检查 28 个输入、长名称、900×600 大图，校验无标签重叠/高度不足、末项和分析控件可滚动访问。完整回归后加强字体检查，确认标签实际使用 1.5/2 倍字号，最终 11 项再次通过，退出码 0。[最终日志](evidence/v0.4.2/layout-tests.txt)、[JUnit](evidence/v0.4.2/layout-tests.xml)、[布局检查](evidence/v0.4.2/layout-check.json)、[截图复现脚本](../scripts/validate_window_layout.py)。 |
| 桌面启动 | `main.py --smoke` 正常退出，退出码 0。[日志](evidence/v0.4.2/smoke.txt)。 |
| 安装包 | 0.4.2 wheel 构建成功，全部 57 个包内源码/资源与当前文件逐字节一致。[检查记录](evidence/v0.4.2/wheel-check.json)、[构建日志](evidence/v0.4.2/wheel-build.txt)。 |

布局截图：[普通窗口](evidence/v0.4.2/prediction-normal.png)、[小窗口](evidence/v0.4.2/prediction-small.png)、[最大化](evidence/v0.4.2/prediction-maximized.png)、[全屏](evidence/v0.4.2/prediction-fullscreen.png)、[恢复](evidence/v0.4.2/prediction-restored.png)、[预测页 1.5 倍字体](evidence/v0.4.2/prediction-font150.png)、[模板编辑 1.5 倍字体](evidence/v0.4.2/template-font150.png)。离屏虚拟屏幕为 800×800，窗口最大化可用尺寸为 796×796；普通及恢复状态使用指定窗口尺寸。

保存故障验证模拟只读描述符限制，并非在用户 Windows 机器执行。窗口覆盖上述状态和字体，未逐一验证所有操作系统、分辨率及任意文字长度；内容超出可见区域时需要滚动，长输入值可在输入框内移动光标查看。本轮不包含 Microsoft Excel 人工操作、Python 3.13 或真实机台实验。环境及总结果见 [总记录](evidence/v0.4.2/summary.json)，问答见 [回答.md](../回答.md) 第 32–37 节。

复现：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m pytest -q -p no:cacheprovider
python scripts/validate_excel_guidance.py
QT_QPA_PLATFORM=offscreen python scripts/validate_window_layout.py
```

## 0.4.1 · 2026-10-10

在 Linux / CPython 3.12.3 / PySide6 6.11.2 / Qt offscreen 环境验证，新增两类 Excel 的填写提示、限定选项下拉及范围校验；仅修改 `python-version`。

| 验证 | 结果与证据 |
| --- | --- |
| 完整回归 | **206 项通过，0 失败，0 跳过，退出码 0**，161.19 秒；14 条依赖弃用/数值提示。[日志](evidence/v0.4.1/python312-tests.txt)、[JUnit](evidence/v0.4.1/python312-tests.xml)。 |
| Excel 文件 | 四份示例重新生成，模板定义读回公式正确；新版 Excel 合成导入与旧 CSV 的条件、测量、不确定度一致，空表导入为 0 条。[检查记录](evidence/v0.4.1/excel-check.json)、[复现脚本](../scripts/validate_excel_guidance.py)。 |
| 桌面启动 | `main.py --smoke` 正常退出，退出码 0。[日志](evidence/v0.4.1/smoke.txt)。 |
| 安装包 | 0.4.1 wheel 构建成功，全部 57 个包内源码/资源与当前文件逐字节一致，含新增 Excel 公共模块。[检查记录](evidence/v0.4.1/wheel-check.json)。 |

新增 13 项回归覆盖：填写提示/批注与实际范围、固定/离散/类别/是否下拉、测量单位和误差列、长文字/逗号/字面等号选项、整数与严格数值边界、粘贴非法值后由软件拒绝且不写记录、实际值不受推荐执行网格限制、带提示格式的实际错误/停止行、模板设置模式/模型与类型、自由单位编辑、空白模板第 3 行填写，以及保留旧基础响应/场景假设元数据时实际模型仍使用新字段。原有手写首行列名 Excel、CSV、GUI、模型和显式保存测试均保留。

本轮验证导出文件的数据验证定义及实际读写/导入，不包含 Microsoft Excel/Windows 人工操作、Python 3.13 或真实机台实验。Excel 数据验证可被粘贴绕过；软件校验为准。隐藏的命名选项表避免直接列表的长度与逗号限制；校验覆盖 10000 条。更换模板设置属性路径后，原行附带的 Excel 下拉仍对应导出时的属性。环境、退出码和示例总记录见 [总记录](evidence/v0.4.1/summary.json)。

复现：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -m pytest -c python-version/pyproject.toml python-version/tests -q -p no:cacheprovider
.venv/bin/python python-version/scripts/validate_excel_guidance.py
```

## 0.4.0 · 2026-10-10

在 Linux / CPython 3.12.3 / Qt offscreen 环境验证。新增 Excel 模板定义、批量字段、文字输入、三个精度批量操作及桌面显式保存；仅修改 `python-version`。

| 验证 | 结果与证据 |
| --- | --- |
| 完整回归 | **189 项通过，0 失败，退出码 0**，189.30 秒，14 条依赖弃用/数值提示。[日志](evidence/v0.4.0/python312-tests.txt)、[JUnit](evidence/v0.4.0/python312-tests.xml)。 |
| 最终定向验证 | **24 项通过，0 失败，退出码 0**，22.53 秒；在完整回归启动后补充的 4 项边界测试也包括在内。覆盖 Excel 隐含模型角色不变、保存失败保留原文件、替换当前同名项目、另存覆盖且来源不变。与完整回归合计覆盖当前 193 个不同测试。[结果与环境](evidence/v0.4.0/summary.json)。 |
| 桌面启动与退出 | `main.py --smoke` 正常退出，退出码 0。结构化字段剪贴板在退出前移交为 Qt 文本，避免 Python MIME 对象清理崩溃。 |
| Excel 与界面 | 生成空白/完整 [Excel 示例](../examples/template_definitions/README.md)，实际导出再导入并计算公式；确认关闭放弃保留原项目文件。[脚本结果](evidence/v0.4.0/artifact-check.json)。已检查 [精度页](evidence/v0.4.0/precision.png)、[字段列表](evidence/v0.4.0/fields.png)、[文字输入](evidence/v0.4.0/text-field.png)、[项目保存入口](evidence/v0.4.0/save-project.png)、[保存提示](evidence/v0.4.0/save-prompt.png)。 |
| 安装包 | 0.4.0 wheel 构建成功，全部 56 个包内源码/资源与当前目录逐字节一致。[检查记录](evidence/v0.4.0/wheel-check.json)。 |

验证包含真实 Qt 鼠标 Shift/Ctrl 多选、快捷键跨区域粘贴、批量删除与引用清理、滚轮滚动外层容器而不改变控件值、说明互斥、统一显示位数不改执行精度、关闭模板/项目的保存/放弃/继续编辑、文字条件真实模型预测与 Ax 跟踪，以及手写中文 Excel、字面公式文本、草稿导入、会话保存/放弃、同名覆盖、外部改动保护和保存故障。

本轮未重新验证 Python 3.13 或 Windows/macOS 人工图形操作。自定义单位仍按同名量纲处理，不自动解释复合单位；文字输入不进入数值模型。桌面显式保存使用工作副本，CLI/Python 记录服务继续立即提交事务。

复现完整回归：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -m pytest -c python-version/pyproject.toml python-version/tests -q -p no:cacheprovider
```

定向回归指定 `python-version/tests/integration/test_template_excel_session.py` 与 `python-version/tests/gui/test_template_workflow.py`。示例与截图复现：`QT_QPA_PLATFORM=offscreen .venv/bin/python python-version/scripts/validate_template_workflow.py`。

## 0.3.0 历史验证

本轮在 Linux x86_64、Qt offscreen 下使用合成数据验证，范围包括通用模板设计、字段增删改名、导入结束标记及原有功能回归。

| 验证 | 结果与证据 |
| --- | --- |
| Python 3.12.3 完整回归 | **152 项通过，0 失败，退出码 0**，约 108.59 秒。[日志](evidence/v0.3.0/python312-tests.txt)、[JUnit](evidence/v0.3.0/python312-tests.xml)、[环境](evidence/v0.3.0/python312-environment.json)。 |
| Python 3.13.15 完整回归 | **152 项通过，0 失败，退出码 0**，约 108.11 秒。[日志](evidence/v0.3.0/python313-tests.txt)、[JUnit](evidence/v0.3.0/python313-tests.xml)、[环境](evidence/v0.3.0/python313-environment.json)。 |
| 安装包 | 0.3.0 wheel 构建，并逐文件核对全部包内源码和资源。[检查记录](evidence/v0.3.0/wheel-check.json)。 |
| 界面 | 已查看[空白模板](evidence/v0.3.0/blank-template.png)、[字段列表](evidence/v0.3.0/fields.png)、[字段表单](evidence/v0.3.0/field-form.png)、[通用帮助](evidence/v0.3.0/general-help.png)、[导入停止预览](evidence/v0.3.0/import-end.png)。 |

新增 25 项回归覆盖：CSV/XLSX 前 30% 输入全空停止，模板顺序与文件列顺序不同，1/3/4/8/10/11 个输入的向上取整规则，真实空行和格式尾行，零/否不判空，缺少表头映射和部分缺项报错；空白及本地模板编辑，输入改名后的引用同步与删除依赖，空项目换结构和有数据项目另存修改，真实录入后的模型预测，固定类别/是否输入，自定义单位与属性保留，以及无有效基础响应时的保存提示。

两套回归各保留 13 条依赖弃用或数值稳定提示，原始日志中可查看。文档改为通用帮助并清理外部链接说明。源文件摘要、包内一致性与本地文档链接核对见 [总记录](evidence/v0.3.0/summary.json)。

复现：在 `python-version` 使用相应环境运行 `python -m pytest -q -p no:cacheprovider`，无桌面时设置 `QT_QPA_PLATFORM=offscreen`。本地验证不代表 Windows/macOS 人工操作或真实机台收益已验收。

## 0.2.1 历史验证（不覆盖本轮新增功能）

日期：2026-09-29。当前版本在 Linux x86_64、Qt offscreen 下用合成数据验证。首次删除会更新数据库版本，测试同时覆盖旧项目读取和删除后的项目恢复。

| 验证 | 结果与证据 |
| --- | --- |
| Python 3.12.3 完整回归 | **127 项通过，0 失败，进程退出码 0**，约 79.39 秒。[日志](evidence/v0.2.1/python312-tests.txt)、[JUnit](evidence/v0.2.1/python312-tests.xml)、[环境与退出码](evidence/v0.2.1/python312-environment.json)。 |
| Python 3.13.15 完整回归 | **127 项通过，0 失败，进程退出码 0**，约 78.43 秒。[日志](evidence/v0.2.1/python313-tests.txt)、[JUnit](evidence/v0.2.1/python313-tests.xml)、[环境与退出码](evidence/v0.2.1/python313-environment.json)。 |
| 安装包 | 0.2.1 wheel 构建成功，逐文件核对包内源码和资源与当前目录一致，元数据支持 Python 3.13。[检查记录](evidence/v0.2.1/wheel-check.json)。 |
| 界面 | 已检查合成数据的[常用页导入入口](evidence/v0.2.1/home.png)、[鼠标多选](evidence/v0.2.1/records.png)、[删除确认框](evidence/v0.2.1/delete-confirmation.png)。 |

本轮新增 12 项回归，覆盖单条/多条选择、确认/取消、写入失败整批回滚、旧确认版本拒绝、删除标记与数据库版本一起回滚、编号不复用、基准/复测默认值清理、旧批次保留、备份恢复、重新导入、模型/Ax/导出排除删除记录、悬停离开延迟关闭、返回变量和进入弹窗取消关闭、表头换列，以及常用配置升级和取消导入后的持久化。

两套完整测试各保留 13 条依赖弃用和数值稳定警告，详情见原始日志。核对通过不代表 Windows/macOS 人工点击或真实机台效果已经验收。仅修改 `python-version`；导入空行机制、静态帮助生成方式和混合噪声算法没有改动，相关解释见 [回答.md](../回答.md)。源码摘要及文档链接检查见 [总记录](evidence/v0.2.1/summary.json)。

复现：在 `python-version` 目录使用对应 Python 环境运行 `python -m pytest -q -p no:cacheprovider`；无桌面 Linux 设置 `QT_QPA_PLATFORM=offscreen`。

## 0.2.0 历史验证（以下证据未覆盖本轮新功能）

日期：2026-09-29。环境：Linux x86_64，Qt offscreen；测试使用合成数据。源文件摘要和退出码见 [机器可读总报告](evidence/v0.2/summary.json)。

| 验证 | 结果与证据 |
| --- | --- |
| Python 3.12.3 完整回归 | **115 项通过，0 失败，进程退出码 0**；约 61.92 秒。[日志](evidence/v0.2/python312-tests.txt)、[JUnit](evidence/v0.2/python312-tests.xml)、[环境](evidence/v0.2/python312-environment.json)。 |
| Python 3.13.15 完整回归 | **115 项通过，0 失败，进程退出码 0**；约 60.70 秒。[日志](evidence/v0.2/python313-tests.txt)、[JUnit](evidence/v0.2/python313-tests.xml)、[环境](evidence/v0.2/python313-environment.json)。 |
| 界面退出生命周期复核 | 修复 Qt 对象释放顺序后，两种解释器各连续 3 次界面测试，每次 6 项通过且正常退出。[记录](evidence/v0.2/gui-lifecycle-recheck.json)。 |
| Python 3.13 自检 | GP/RBF、GP/Matérn、贝叶斯线性、spawn 推荐及 SQLite 恢复通过。[记录](evidence/v0.2/self-test-python313.json)。 |
| Python 3.13 完整示例 | examples/workflow.py 完成拟合、推荐、回填、预测、趋势图、CSV/XLSX/JSON 导出和备份恢复。 |
| 安装包构建 | 0.2.0 wheel 构建成功；逐文件比较安装包内全部源码、帮助、字体、模板与当前源目录一致；版本约束包含 3.13。[检查记录](evidence/v0.2/wheel-check.json)。 |
| 文档 / 配置 | 本地 Markdown 链接、JSON 文件及 git diff 空白检查通过。 |

完整回归覆盖旧功能、旧绝对值模板、新带符号目标、负分母/零分母、比值单位换算、探索强度排序、三个数值模型的专门名额、复测/历史/待做去重、备份恢复、Qt 表单保存、帮助链接与定位、自定义常用功能持久化，以及相同条件不同结果的界面录入。

本轮曾发现“测试断言通过但 Qt 在解释器退出时崩溃”的问题，修复了应用、窗口和翻译对象的生命周期，最终证据同时要求断言通过和进程退出码 0。最终测试日志仍保留 13 条依赖弃用/数值稳定告警；应用后台将相应提示汇总为中文并保留原始技术诊断。

## 界面检查

以下为合成数据的离屏截图，已检查布局、中文文字和目标设置：

- [常用工作台](evidence/v0.2/home.png)
- [推荐与探索设置](evidence/v0.2/recommend.png)
- [工艺精度表单](evidence/v0.2/precision.png)
- [多目标表单](evidence/v0.2/objectives.png)
- [离线说明](evidence/v0.2/help.png)

## 复现

在 python-version 目录，分别使用对应环境执行：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python main.py --self-test local-data/self-test
python examples/workflow.py --output local-data/workflow
```

无桌面 Linux 设置 `QT_QPA_PLATFORM=offscreen`，后两项输出目录必须尚不存在；这里报告的是本地实际完成的 Linux 结果。

尚未在本环境完成 Windows/macOS 人工操作、PyCharm 人工点击、真实机台回测或自由线程 Python 验证。当前功能边界见 [coverage.md](coverage.md)。

原 0.1 测试原始材料继续保存在 evidence 及历史审计文档中，其测试数量与绝对值目标不能作为 0.2 当前行为或验收结论。

## 2026-09-30 · 显示、撤销、数据交换与时间趋势

在 Linux / CPython 3.12、Qt offscreen、CPU PyTorch 环境执行：

```bash
.venv/bin/python -m pytest -c python-version/pyproject.toml python-version/tests -q
```

结果：**169 passed，14 warnings，117.13 秒**。警告包括依赖接口弃用和 GP 数值稳定 jitter 提示，无失败。最后两项小调整（输出使用计算时模板、导入空表头校验）相关 GUI/数据交换回归再次通过，共 12 项。本轮未重新验证 Python 3.13 或真实 Windows 图形桌面。

新增回归覆盖：删除/恢复/再次删除、编号复用及 UID、模板默认引用恢复、更正/导入/模板撤销重做、去重标识、外部窗口修改保护、撤销失败事务回滚、CSV/Excel 空表填入后的真实导入、图线缓存导出完整精度及字面文本、大小写快捷键、文字编辑与项目历史分流、测量/指标显示配置持久化、模板变量不弹帮助。

三种模型均验证：固定其他输入、变化时间、累计厚度差按人工线性规律变化时，预测随时间递增，均值数量级保持累计 nm，单变量图线点可完整导出。增加固定输入的覆盖不足提示，以及未知噪声线性回归残差自由度按有效秩计算的检查。合成案例只验证软件数学管线，不证明真实机台物理规律或用户具体数据的预测准确度。
