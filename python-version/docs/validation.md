# Python 源码版 0.2 验证报告

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

无桌面 Linux 设置 `QT_QPA_PLATFORM=offscreen`，后两项输出目录必须尚不存在。新增 GitHub Actions 对 Ubuntu/Windows 和 Python 3.12/3.13 组成矩阵；这里报告的是本地实际完成的 Linux 结果。

尚未在本环境完成 Windows/macOS 人工操作、PyCharm 人工点击、真实机台回测或自由线程 Python 验证。当前功能边界见 [coverage.md](coverage.md)。

原 0.1 测试原始材料继续保存在 evidence 及历史审计文档中，其测试数量与绝对值目标不能作为 0.2 当前行为或验收结论。
