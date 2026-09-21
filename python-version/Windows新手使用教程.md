# Windows 新手使用教程：从安装 PyCharm 到运行实验规划助手

更新日期：2026-09-20。

这份教程写给没有学过编程的人。你不需要修改程序代码，按顺序点击按钮、复制文件和命令即可。

程序运行后，关于预测能否删除、epsilon、比值策略、单／双变量、交叉布局和其他设置，见 [参数与操作白话说明](参数与操作白话说明.md)。

流程是：**安装 PyCharm → 新建项目 → 复制文件 → 安装运行所需的工具 → 运行 main.py → 使用实验规划助手。**

以下以 Windows 10/11、普通 Intel/AMD 64 位电脑为例。首次下载安装需要联网。本项目目前要求 **Python 3.12**，请不要直接选择列表中最新的 3.13、3.14 等其他版本。

## 1. 下载并安装 PyCharm

1. 打开浏览器，进入 [PyCharm 官方下载页面](https://www.jetbrains.com/pycharm/download/?section=windows)。
2. 选择 Windows 版本，下载 `.exe` 安装文件。普通 Intel/AMD 电脑选择 x64/64 位版本。
3. 双击下载好的文件，按安装窗口提示点击 **Next（下一步）**、**Install（安装）**。可以勾选创建桌面快捷方式，方便以后打开。
4. 安装完成后，从桌面或 Windows 开始菜单打开 PyCharm。

如果页面没有单独的 Community（社区版）按钮，不用反复寻找：当前 PyCharm 已合并为一个产品，基础功能可以免费使用。运行本项目使用基础功能即可。参见 [PyCharm 官方安装说明](https://www.jetbrains.com/help/pycharm/installation-guide.html)。

## 2. 在 PyCharm 中新建项目，让它建立 Python 环境

这里的“项目”可以理解成一个存放程序文件的文件夹。“Python 环境”是运行程序需要的工具，不用自己编写。

1. 在欢迎窗口点击 **New Project（新建项目）**。如果已经打开了其他项目，可以在菜单中选择 **File → New Project（文件 → 新建项目）**。
2. 如果左侧有项目类型，选择 **Pure Python（普通 Python 项目）**。
3. 在 **Location（位置）** 中填写一个容易找到的新文件夹，例如：

   ```text
   C:\Users\你的Windows用户名\PycharmProjects\ExperimentPlanner
   ```

   “你的Windows用户名”要换成自己电脑上的用户名，也可以保留 PyCharm 建议的上级目录，只把最后的项目名称改成 `ExperimentPlanner`。记住这个文件夹的位置，下一步要向里面复制文件。

4. 在 **Interpreter type（解释器类型）** 中选择 **Project venv（项目虚拟环境）**。在 **Python version（Python 版本）** 中选择 **Python 3.12**。
5. 如果没有 Python 3.12，查看是否提供 **Download and install（下载并安装）**，选择下载 3.12。PyCharm 在 Windows 上支持这个入口；已经找到 3.12 的人直接继续。
6. 保持环境文件夹为项目里面的 `.venv`。如果使用旧版 PyCharm，对应选项可能写作 **New environment using Virtualenv（新建虚拟环境）**，基础 Python 同样选 3.12。
7. 如果看到 **Create a main.py welcome script（创建示例 main.py）**，取消勾选，稍后会复制本项目自己的 `main.py`。创建 Git 仓库的选项也可以不勾选，运行程序不需要设置 Git。
8. 点击 **Create（创建）**，等待下载和环境创建完成。

上述菜单依据 [PyCharm 官方新建项目说明](https://www.jetbrains.com/help/pycharm/creating-empty-project.html)。不同版本的按钮位置可能略有不同，认准 **Python 3.12** 和 **项目自己的 `.venv`** 即可。

**这一阶段完成后，PyCharm 已帮你建立了运行环境，但实验助手需要的其他工具还要在第 5 步安装。**

如果自动下载 Python 失败，可以先手动安装，再回到这一步选择它：

1. 打开 [Python 3.12.10 官方下载页](https://www.python.org/downloads/release/python-31210/)，在下方文件表中选择 **Windows installer (64-bit)**。这是一个提供 Windows 独立安装程序的 3.12 版本示例，不是要求必须使用这一小版本；已有可用的 3.12 环境可以继续使用。
2. 双击安装文件；如果看到 **Add python.exe to PATH**，勾选它，再点击 **Install Now（立即安装）**。
3. 安装完成后重新打开 PyCharm 的新建项目窗口，选择刚安装的 Python 3.12。不要下载标为 Source release 的源码压缩包来代替 Windows 安装文件。

## 3. 把 python-version 里面的文件复制到新项目

1. 如果已经有 `python-version` 文件夹，直接打开它。如果还没有，打开 [本项目 GitHub 页面](https://github.com/Qiaochu-Zhang/experiment-planner)，点击绿色 **Code** 按钮，再点击 **Download ZIP（下载压缩包）**。下载后右键压缩包，选择 **全部解压缩**，再打开解压后的 `python-version` 文件夹。若仓库需要登录，请使用有访问权限的账号。
2. 进入 `python-version` **里面**，选中其中的文件和文件夹，按 **Ctrl+C** 复制。要包含 `main.py`、`requirements.txt`、`pyproject.toml`、`src` 等内容，不能只复制一个启动文件。
3. 打开第 2 步创建的 `ExperimentPlanner` 文件夹，按 **Ctrl+V** 粘贴。
4. 如果 PyCharm 已生成一个欢迎示例 `main.py`，这时用本项目的 `main.py` 替换它。这个说明仅针对刚创建的空项目。
5. 保留 PyCharm 自己生成的 `.venv` 和 `.idea` 文件夹；如果复制来源中也有这两个文件夹，跳过它们。每台电脑使用自己建立的运行环境。
6. 回到 PyCharm，稍等片刻，左侧文件列表应出现这些内容：

   ```text
   ExperimentPlanner
   ├─ .venv                    PyCharm 建立的运行环境
   ├─ .idea                    PyCharm 的项目设置，可能被隐藏
   ├─ main.py                  稍后要运行的文件
   ├─ cli.py
   ├─ requirements.txt         运行所需工具的清单
   ├─ requirements-dev.txt
   ├─ pyproject.toml
   ├─ src                      程序主体，必须保留
   ├─ docs
   ├─ examples
   ├─ scripts
   └─ tests
   ```

**检查重点：`main.py` 和 `requirements.txt` 应直接位于 `ExperimentPlanner` 下面。**

如果现在是 `ExperimentPlanner → python-version → main.py`，说明多套了一层文件夹。请把内层 `python-version` 的内容移动到外层 `ExperimentPlanner`，再按后续步骤操作。

## 4. 打开终端，确认 Python 版本

“终端”就是 PyCharm 里可以粘贴命令并按回车执行的区域，不需要理解编程。

1. 在 PyCharm 下方找到 **Terminal（终端）**。找不到时，点击菜单 **View → Tool Windows → Terminal（视图 → 工具窗口 → 终端）**。
2. 本教程的命令使用 Windows 的 PowerShell 或命令提示符终端。不要粘贴到 **Python Console（Python 控制台）**；那个窗口通常有 `>>>` 符号。
3. 看终端光标前的路径是否以 `ExperimentPlanner` 结尾。如果不是，输入 `cd` 加你的实际项目路径，例如：

   ```powershell
   cd "C:\Users\你的Windows用户名\PycharmProjects\ExperimentPlanner"
   ```

4. 复制下面这一行到终端，按 **Enter（回车）**：

   ```powershell
   .\.venv\Scripts\python.exe --version
   ```

5. 应看到 `Python 3.12.x`，最后一位或两位数字可以不同。如果显示其他版本，先回到第 2 步创建 Python 3.12 环境，不要继续安装。

命令中的 `.\.venv\Scripts\python.exe` 是直接使用刚才项目中的 Python。这样即使电脑装了多个 Python，也能把工具安装到正确的地方。只复制代码框里面的文字，不要复制代码框边缘的符号或终端提示符。

## 5. 安装 requirements.txt 里的运行工具

正确文件名是 **`requirements.txt`**，有字母 **s**。它是一张安装清单，不用双击运行，也不用逐项手动搜索里面的工具。

在同一个终端中，按顺序执行下面三条命令。**每次复制一行、按回车，等执行完成后再执行下一行。**

1. 更新安装工具：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   ```

2. 安装普通 CPU 版的计算工具，本教程不需要单独配置显卡：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
   ```

3. 按清单安装本程序和其余需要的工具：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

安装时窗口会出现很多英文并下载文件，第一次可能需要较长时间。等到光标前再次出现项目路径、可以输入下一条命令，表示这一条命令已经结束。成功时通常会看到 `Successfully installed`；`Requirement already satisfied` 表示已经装过，不是错误。若出现 `ERROR`，先查看第 11 步。

清单里的 `-e .` 也要保留，它负责安装这个实验助手本身。这里的点表示“当前文件夹”，所以一定要在 `main.py`、`pyproject.toml` 所在的项目文件夹执行。

如果 PyCharm 的终端已自动启用正确的项目环境，常见的简短写法也可以使用：

```powershell
python -m pip install -r requirements.txt
```

它与上面的第三条命令用途相同，不需要重复执行。本教程前面使用完整的项目 Python 路径，是为了减少“装好了却运行时找不到”的问题。平时运行软件不需要安装 `requirements-dev.txt`，那是程序测试所用的清单。

## 6. 运行 main.py，打开实验规划助手

1. 回到 PyCharm 左侧文件列表，找到项目最外层的 **`main.py`**。
2. 在 `main.py` 上点击鼠标右键，选择 **Run 'main'（运行 main）**。不要选择“在 Python Console 中运行”。
3. 第一次启动会加载计算和界面工具，等候片刻，应出现 **“实验规划助手 · Python 源码版”** 窗口。
4. 看到“实验记录”“下一批实验”“模板 / 公式 / 先验”“预测 / 趋势图”页面，就说明程序已经启动。

如果右键菜单里没有运行选项，也可以在第 4 步的终端执行：

```powershell
.\.venv\Scripts\python.exe main.py
```

窗口打开后，终端或 PyCharm 的运行窗口一直处于运行状态是正常的。关闭实验助手窗口后，程序才会结束。此时不要连续点击运行来开启很多个窗口。

如果终端可以启动、右键运行却提示缺少工具，检查 PyCharm 的 **Settings（设置）→ Python → Interpreter（解释器）**，选择本项目的 `.venv\Scripts\python.exe`；旧版位置可能叫 **Project → Python Interpreter**。运行配置中的 Python 也要选同一个环境。参见 [官方环境设置说明](https://www.jetbrains.com/help/pycharm/creating-virtual-environment.html)。

## 7. 先用练习数据熟悉界面

建议第一次先练习，不急着填写真实实验。

1. 关闭正在运行的实验助手窗口，回到 PyCharm 的终端。
2. 执行下面的命令，创建一份练习文件：

   ```powershell
   .\.venv\Scripts\python.exe main.py --demo local-data/demo.sqlite
   ```

3. 等终端显示“合成案例已保存”后，再执行：

   ```powershell
   .\.venv\Scripts\python.exe main.py --project local-data/demo.sqlite
   ```

4. 助手窗口打开后，在“实验记录”中应看到 **12 条合成练习记录**。这些数据只是练习用，不是机台测量结果。
5. 如果提示 `demo.sqlite` 已存在，说明以前创建过，直接执行上面的打开命令即可，不用删除或重新创建它。

这里的 `.sqlite` 文件可以理解为“一本保存实验记录的电子本子”。PyCharm 项目保存程序文件；实验助手里的项目保存实验数据，它们不是同一种“项目”。

## 8. 练习查看预测和生成下一批实验

1. 在“下一批实验”页面，将“数值模型”保持为 **默认 GP / RBF**。
2. 切回“实验记录”，点击任意一条练习记录。
3. 打开“预测 / 趋势图”，点击 **从选中实验复制条件**。会出现一段带英文名称和数字的条件清单，第一次可以保持原样。
4. 让“趋势图变量”保持空白，点击 **按「下一批实验」所选模型预测 / 绘图**。等待计算结束，下方会显示预测结果。
5. 如果想看 Cl2 改变时的趋势，在“趋势图变量”中填 `cl2_sccm`，“趋势图响应/指标”保持 `sio2_loss_nm`，再点击同一按钮，选择图片保存位置。其余条件保持刚才复制的数值。
6. 练习生成下一批时，回到“下一批实验”。在“比值目标”选择 **移除比值目标**，点击 **保存目标策略版本**。本次练习只优化两种刻蚀量，便于先熟悉操作；真实实验请根据用途选择目标策略。若选择“稳定化比值”或“有效区域内原始比值”，需要填写由量测口径确定的正数 `epsilon`，不能直接把教程中的任意数字当成工艺标准。
7. 将“本轮新增总数 n”设为 `1`；“变化模式”选择 **相对基准恰好改变一项**；“基准实验”选一条已有记录；“允许变化的字段”填 `cl2_sccm`；“复测实验编号”留空。
8. 点击 **计算并保存下一批实验**，等待计算结束。返回“实验记录”，新建议会显示为“待做”。

预测结果里常用字段可以这样看：

| 界面中的名称 | 可以怎样理解 |
| --- | --- |
| `sio2_loss_nm` | SiO2 的刻蚀量预测，单位 nm |
| `sin_loss_nm` | SiN 的刻蚀量预测，单位 nm |
| `mean` | 模型给出的平均估计 |
| `quantiles` | 三个数字依次是预测区间下端、中间位置、上端 |
| `raw_selectivity_abs` | 原始选择比；它的 `mean` 显示 `null` 是有意保留，并不等于程序坏了 |
| `selectivity_stable` | 选择稳定化策略后才出现的另一种比值指标 |

当前预测页面仍以文字清单显示结果。预测区间表示模型对潜在刻蚀量的不确定性，没有自动加上下一次测量的误差，不能理解为“下一次测量一定落在这里”。本项目的[预测测试结果](实验预测测试结果.md)说明了已验证情况和局限。

## 9. 建立自己的实验记录，录入和回填

1. 在实验助手顶部点击 **新建项目**，选择一个方便保存数据的位置，起一个新的文件名，例如 `我的刻蚀实验.sqlite`。这一步在实验助手里操作，不需要回 PyCharm 重新建工程。
2. 点击“实验记录”中的 **录入实验**。
3. 填写实际执行的 8 个条件：Cl2、BCl3、Ar、ICP、RF、腔室压力、电极温度、刻蚀时间。每个框会提示允许范围；数字框内只填数字，单位已写在旁边。
4. 填写 SiO2 和 SiN 的初始厚度、剩余厚度。确实没有测量的项目留空，不要用 `0` 代替“没测”。
5. 如果知道测量的误差含义，在“± 值”中填写数字，再选择对应含义。如果不知道，先留空，不要随意填写误差或当成误差为零。
6. 检查“实验状态”和备注，点击 **Save（保存）**。软件会根据两次厚度的差值计算刻蚀量。
7. 积累已有测量后，可按第 8 步查看预测或提出下一批建议。没有数据时，软件可能只给出供探索的初始条件；能输出预测也不代表已经积累了足够的真实依据。
8. 实际完成一条建议后，在“实验记录”中选中对应的“待做”行，点击 **更正选中实验 / 回填**。检查实际执行条件，填入测量结果，将状态改为“完成”，再保存。不要把预测值填成实测结果。

建议先用练习项目走通这些步骤，再单独建立真实项目。软件不能代替机台操作规程或实验人员判断。

## 10. 保存、备份，以及下次如何打开

1. 每次在录入窗口点击“保存”，记录就写入当前的 `.sqlite` 文件；不需要在 PyCharm 中另找按钮保存实验数据。
2. 定期点击助手顶部的 **一致性备份**，保存到另一个文件名，例如 `我的刻蚀实验_备份_2026-09-20.sqlite`。再把生成的备份文件复制到自己管理的备份位置。
3. 如需在 Excel 查看，点击 **导出记录**，选择 Excel 格式。完整迁移和恢复优先使用 `.sqlite` 备份文件。
4. 下次使用时，打开 PyCharm 中的 `ExperimentPlanner` 项目，右键运行 `main.py`，然后在助手中点击 **打开项目**，选择原来的 `.sqlite` 文件即可。
5. 同一台电脑、同一个环境，通常不用再次安装依赖。换电脑时，重新按第 1–6 步安装程序和环境，再复制实验备份并打开。

下载程序和安装工具时需要网络；安装完成后的实验计算、绘图和保存使用本机资源。公司电脑需要断网使用时，应先准备好环境并实际试运行。

## 11. 常见问题：先对照这张表

| 看到的情况 | 建议处理 |
| --- | --- |
| 找不到 `requirements.txt` | 检查拼写中的 `s`，并确认终端就在 `main.py` 所在文件夹；多套了一层 `python-version` 时先按第 3 步整理。 |
| 找不到 `.\.venv\Scripts\python.exe` | 环境尚未创建，或当前位置不对。检查第 2、3、4 步；如果环境被命名为 `venv`，命令中的 `.venv` 也要改成实际名称。 |
| 提示 Python 版本不符合要求、`requires a different Python` | 确认输出是 `Python 3.12.x`。需要在 PyCharm 中重新创建 3.12 环境，修改文件名不能改变 Python 版本。 |
| 提示 `No module named ...` | 使用第 5 步的完整路径安装命令，再按第 6 步确认 PyCharm 运行时也使用同一个 `.venv`。 |
| 提示不能加载 `Activate.ps1`、禁止运行脚本 | 这是终端自动启用环境时遇到的问题。可以继续使用本教程的 `.\.venv\Scripts\python.exe ...` 完整路径，不必先执行激活脚本。 |
| 下载超时、连接失败、SSL 或代理错误 | 检查网络；公司网络受限时请联系负责网络的人，或准备好离线依赖后安装。不要只看最后一行就反复改代码。 |
| `No matching distribution found` | 先检查 Python 是否为 3.12、电脑和 Python 是否为 64 位，并确认网络能访问下载源；仍失败时保留完整错误内容排查。 |
| 运行后只有 `Hi, PyCharm` 之类的欢迎文字 | 运行的是 PyCharm 自动生成的示例。确认已经用本项目的 `main.py` 替换它，并且旁边有 `src` 文件夹。 |
| 提示项目文件已存在 | 已有 `.sqlite` 应点击“打开项目”；新建时换一个未使用的文件名。 |
| 提示需要设置分母处理方式 | 到“下一批实验”选择比值策略并点击“保存目标策略版本”；需要 epsilon 的策略要填写正数。 |
| 提示数据不足，暂时不能预测 | 先录入有效历史测量。不要复制相同记录凑数量，也不要把模型预测当作测量。 |
| 提示混合已知/未知观测噪声未适配 | 同一响应有些测量填写了标准误差、有些没有，当前模型不支持这种混合。核对真实误差来源，不能为通过检查把未知误差填成 0。 |

仍无法解决时，记下失败发生在本教程第几步，并保留 PyCharm 运行窗口或终端里的完整报错。这通常比只描述“打不开”更容易定位。

## 12. 完成后检查

1. PyCharm 的项目环境是 Python 3.12。
2. `main.py`、`requirements.txt`、`pyproject.toml`、`src` 在正确的位置。
3. 第 5 步安装命令执行成功。
4. 运行 `main.py` 后看到了实验规划助手窗口。
5. 已能打开练习数据，并知道自己的 `.sqlite` 数据文件保存在哪里。

完成这五项，就可以按第 8–10 步开始练习和记录实验。

本教程的菜单和按钮已对照官方文档及当前源码核对；Windows/PyCharm 的人工点击安装流程尚未在本次 Linux 环境实机验证。现有 Linux 验证记录见[预测测试结果](实验预测测试结果.md)，更详细的工程说明见 [README](README.md)。
