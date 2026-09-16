# Python 源码版验证

日期：2026-09-16。环境：Ubuntu / Python 3.12；依赖实际版本见 [environment.json](evidence/environment.json)。

本次仅使用合成数据，GUI 使用 Qt offscreen。测试通过不等于真实实验效果、Windows/macOS 人工操作或所有 V1.1 要求验收通过。

| 验证 | 结果 |
| --- | --- |
| 原有核心、模型、存储、GUI 回归 | 65 项通过 |
| Python 版完整测试集 | **68 项通过，0 失败，37.23 秒**；[JUnit XML](evidence/python-version-tests.xml) |
| 将 main.py、cli.py 和 src 复制到独立中文/空格目录 | 从不同工作目录启动成功；创建合成项目、读取、修订、历史、GUI 冒烟通过 |
| 后台分析 | spawn 拟合、预测、绘图；并发锁与只读数据库快照检查通过 |
| Python 桌面扩展 | 四个页面、条件复制、交叉布局请求、关闭清理检查通过 |
| examples/workflow.py | 拟合、n=2 推荐、回填、PNG、CSV/XLSX/JSON、备份恢复成功 |
| Python wheel 构建 | 无依赖下载的本地构建成功；检查包含源码、ICP 模板及字体 |
| main.py --self-test | GP-RBF、GP-Matérn、贝叶斯线性、spawn 批次、SQLite 恢复成功 |

复现（在 `python-version` 目录中，使用已安装依赖的 Python 3.12）：

```bash
python -m pytest -q
python examples/workflow.py --output local-data/validation-workflow
python main.py --self-test local-data/validation-selftest
```

后两项输出目录需要不存在。启动与预测命令在 [README](../README.md) 中。
测试环境出现第三方 PyTorch/Ax 弃用告警及模型数值 Cholesky jitter 告警；未将告警隐藏。最初单独执行新增 GUI 测试时因无桌面导致 Qt 退出，已为该测试模块显式设置 offscreen，随后执行完整回归。

尚未验证：全新 Windows/macOS 依赖安装、PyCharm 人工点击流程、跨机器恢复、断网干净机与出网监测。还未实现的需求逐项列于 [coverage.md](coverage.md)。
