# Python 源码版 0.3.0 验证报告

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
