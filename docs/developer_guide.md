# 开发与构建

## 目录与入口

`src/experiment_planner` 按 domain、precision、metrics、storage、application、engine、knowledge、io、worker、plots、ui 分层。模板 JSON 是从权威规格第 6.2 节提取的原始内容，随 Python 包安装。

`python -m experiment_planner` 启动最小桌面原型；`--demo 新文件.sqlite` 建立合成记录；`--self-test 新目录` 执行三个数值模型、qLog 推荐、spawn 后台与备份恢复验证；`--smoke` 运行 Qt 最小窗口后退出。

Linux 的无桌面测试使用 `QT_QPA_PLATFORM=offscreen`。Qt 需要 libGL、libEGL、libOpenGL、libxkbcommon 和 libdbus 系统运行库。开发环境已安装这些库。Noto Sans CJK 未修改字体集合及 OFL 随包提供，不依赖运行时联网下载字体。

## 检查

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
QT_QPA_PLATFORM=offscreen .venv/bin/python -m experiment_planner --smoke
```

测试只用临时目录与合成数据。测试编号及结果见 acceptance_results.md。模型的低秩联合协方差可能触发 GPyTorch 数值 jitter 提示；此为求解稳定化，不应解释为真实量测噪声。

## 依赖

已实际安装 Python 3.12、Ax 1.3.1、BoTorch 0.18.1、PyTorch 2.14.0+cpu。此处记录实际 Linux 结果，未将规格的 Torch 2.8 候选版本伪报为当前 Linux 环境版本。

`requirements/linux-resolved.txt` 为 Linux 实际冻结，排除本地 editable 路径。CPU Torch 来源为 https://download.pytorch.org/whl/cpu 。Windows 输入文件单独使用候选 Torch 2.8.0，Windows CI 成功安装后生成 `windows-resolved.txt`，不复制 Linux 锁到 Windows。

## 数据一致性

SQLite 记录完整 JSON 单元与版本化模板；数据库 schema 版本独立于模板 schema v2。未知数据库版本明确报错。暂不支持 schema v1 迁移，旧文件不改写。

每次计算读取一致性快照，子进程不持有可写数据库连接。保存批次使用 BEGIN IMMEDIATE，并检查源 revision。修订/新增/配置/批次均递增 revision；历史批次与预测不会删除。备份用 SQLite backup API。

## Windows 原型构建

PowerShell 7、64 位 Python 3.12：

```powershell
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements/windows.in
python -m pip install --no-deps -e .
./packaging/windows/build.ps1
```

构建脚本先运行测试，后生成 PyInstaller 目录包，再直接运行冻结程序的模型/spawn/恢复与 Qt 冒烟检查。工作流 `.github/workflows/windows-prototype.yml` 可在独立开发分支运行，产物包含测试报告、Windows 解析依赖、冻结验证证据和 SHA-256。

这是原型构建。CI 主机有 Python 且通常联网；不能替代 Windows 10/11 无 Python、断网、普通用户、主程序和子进程出网监测验收。未生成或未下载的 EXE 不记为已交付。
