# 实验规划助手

按仓库内 V1.1 规格与开发流程建设的中文本地桌面软件。当前版本 **0.1 开发原型**，不是正式 Windows 离线发布。

已实现可运行的 ICP 模板、公式/精度/误差计算、SQLite 修订与备份、CSV/XLSX 导入导出、三个数值模型、布尔概率适配、受限多目标推荐，以及最小 Qt 操作闭环。65 项 Ubuntu 测试及完整合成后台闭环已通过。完整需求完成度以验收记录为准。

## 开发环境启动

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m experiment_planner
```

本工作目录依赖已安装，可直接执行 `.venv/bin/python -m experiment_planner`。无图形桌面的服务器仅运行离屏测试；交互窗口需要桌面显示环境。

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m experiment_planner --demo /tmp/planner-demo.sqlite
.venv/bin/python -m experiment_planner --self-test /tmp/planner-validation-new
```

- [中文使用说明](docs/user_guide.md)
- [实际验收与未完成项](docs/acceptance_results.md)
- [开发与构建说明](docs/developer_guide.md)
- [模型能力边界](docs/model_capabilities.md)
- [开发流程](docs/development_workflow.md)
- [需求基线 V1.1](experiment_planner_ax_project_spec_v1_0%20%282%29.md)

Windows 脚本和 GitHub Actions 工作流只构建开发原型。Windows Server CI 启动不等于 Windows 10/11 的无 Python、断网验收。应用运行时不安装依赖、不下载模型。
