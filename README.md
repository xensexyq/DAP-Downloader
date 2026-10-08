<div align="center">

# DAP-Downloader

**面向 STM32H5 的 Windows / Linux CMSIS-DAP 固件下载工具**

[功能](#功能) · [安装](#安装) · [基本使用](#基本使用) · [文档](#文档) · [安全说明](#安全说明)

</div>

面向 STM32H5 的 Windows / Linux CMSIS-DAP 固件下载工具。当前默认配置用于 TC-GU-01 的 STM32H562VGT6：

当前版本：`v0.0.1`

- Target：`STM32H562VGTx`
- SWD 频率：`1 MHz`
- 连接方式：`under-reset`
- 擦除方式：`sector`
- Device Pack：Keil STM32H5xx DFP 2.3.1

## 功能

- 自动检测 CMSIS-DAP 探针和常见 ELF、AXF、HEX、BIN 固件。
- 自动下载并缓存官方 STM32H5 CMSIS Device Pack。
- 中文、英文界面一键切换，单个界面不会混用两种语言。
- 参数、下拉列表和确认窗口使用正常固定字号，不通过压缩字体适配窗口。
- 主界面无整体滚动条；长路径可将鼠标停留在控件上查看完整内容。
- 下拉框未获得焦点时，鼠标滚轮不会意外修改参数。
- 下载进度条仅在烧录固件时显示，并根据擦除、编程、校验和复位阶段从 0% 前进到 100%。
- 下载前显示高对比度参数确认窗口，默认开启安全确认。

## 系统架构

PySide6 界面负责固件选择、参数确认和结果显示；`dap_core.py` 与 pyOCD 完成探针及烧录流程；`dap_platform.py` 管理平台路径。CMSIS Device Pack 按需下载并缓存，不随源码提交。

**烧录会擦写目标 Flash，不是只读诊断。** 使用前核对目标芯片、供电、接线和固件地址，保留[安全说明](#安全说明)。

## 安装

先获取源码，再选择下方 Conda 环境或对应系统启动脚本。Linux 还需准备[系统图形库与 USB 权限](#linux-快速运行)。

```bash
git clone https://github.com/xensexyq/DAP-Downloader.git
cd DAP-Downloader
```

## 创建独立 Conda 环境

Windows 和 Linux 都可以使用单独的 `dap-downloader` 环境（推荐 Python 3.11；固定依赖使用 Python 3.10–3.13）：

```powershell
conda env create -f environment.yml
conda activate dap-downloader
python dap_tool.py
```

也可以手动创建：

```powershell
conda create -n dap-downloader python=3.11 -y
conda activate dap-downloader
python -m pip install -r requirements.txt
python dap_tool.py
```

## Windows 快速运行

双击 `run_tool.bat`。脚本会检查 Python、pyOCD 和 PySide6，并在缺少依赖时安装 `requirements.txt`。

## Linux 快速运行

以下系统安装命令适用于 Ubuntu 22.04 / 24.04、Debian 12 的桌面环境。其他发行版需安装对应的软件包；ARM64 需确认固定 Python 依赖有可用 wheel，尚未进行硬件实测。X11 和 Wayland 由 Qt 选择，无需更改烧录参数。

先安装系统运行库和中文字体（管理员执行一次）：

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip libusb-1.0-0 \
  libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 \
  libxcb-randr0 libxcb-shape0 libxcb-xfixes0 libxcb-sync1 libxcb-xkb1 \
  libx11-xcb1 libfontconfig1 libdbus-1-3 fonts-noto-cjk
```

进入项目目录，在桌面终端执行：

```bash
./run_tool.sh
```

脚本会创建项目内的 `.venv` 并安装 `requirements.txt`，随后启动界面。已激活的 venv / 非 `base` Conda 环境优先使用；自动激活的 Conda `base` 会跳过，改用项目 `.venv`；也可以用 `PYTHON=/绝对路径/到/python ./run_tool.sh` 指定解释器。脚本不会向系统 Python 安装依赖，也不会自动执行 `sudo`。Python 版本不适合时，可使用上方的 Conda Python 3.11 环境。脚本以 `bash run_tool.sh` 运行也可以。

手动安装和运行的等效步骤：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python dap_tool.py
```

Python wheel 自带 Qt，但仍依赖系统图形库。依赖选择参照 [Qt 6.8 X11 运行库说明](https://doc.qt.io/qt-6.8/linux-requirements.html) 和 [Qt for Python 安装说明](https://doc.qt.io/qtforpython-6.8/gettingstarted.html)。

### 配置 USB 访问权限

pyOCD 在 Linux 下需要 udev 授权后才能以普通用户访问探针。项目附带的规则授权产品名包含 `CMSIS-DAP` 的设备，以及 DAPLink `0d28:0204`；同时覆盖 USB 节点和可选 HID 后端的 `hidraw` 节点。默认授权当前本地桌面会话用户，不向所有用户开放写权限。规则参考 [pyOCD 的 Linux 安装说明](https://pyocd.io/docs/installing#udev-rules-on-linux) 和 [pyOCD 0.45.1 的探针 ID](https://github.com/pyocd/pyOCD/blob/v0.45.1/udev/50-cmsis-dap.rules)。

先预览，再由管理员安装一次：

```bash
./scripts/install_udev_rules.sh --dry-run
sudo ./scripts/install_udev_rules.sh
```

安装会写入 `/etc/udev/rules.d/60-dap-downloader.rules` 并重载规则。**拔下并重新插入探针**，随后以普通用户运行：

```bash
./run_tool.sh --pyocd-cli list
./run_tool.sh
```

部分探针只在 USB 接口描述中标注 CMSIS-DAP，产品名不包含该字符串，默认规则可能无法匹配。先用 `lsusb` 确认探针的 `VID:PID`，然后指定准确的 ID，例如以下命令中的 `1234:abcd` 必须替换为实际值：

```bash
sudo ./scripts/install_udev_rules.sh --vid 1234 --pid abcd
```

脚本只匹配指定设备的四位 VID / PID，不会放开所有 USB 或 HID 设备。重新执行安装会替换这个项目的规则文件；需要保留自定义规则时先备份。

默认的 `uaccess` 授权依赖 systemd-logind 的本地活动会话。SSH 或没有 logind 的系统可指定一个已有的专用用户组：

```bash
sudo groupadd -f dapusers
sudo usermod -aG dapusers "$USER"
sudo ./scripts/install_udev_rules.sh --group dapusers
# 产品名无法匹配时，同时加上 --vid 1234 --pid abcd
```

加入组后注销并重新登录，再拔插探针。只有权限规则安装、系统依赖安装和用户组配置需要管理员权限，图形程序和 pyOCD 始终用普通用户运行。

### Linux 设置与 Pack 缓存

| 内容 | 默认路径 | 可覆盖的环境变量 |
| --- | --- | --- |
| 界面设置 | `~/.config/dap-downloader/settings.json` | `XDG_CONFIG_HOME` |
| Device Pack | `~/.cache/dap-downloader/packs/` | `XDG_CACHE_HOME` |

XDG 变量必须是绝对路径；相对路径会被忽略。程序目录可以只读。离线使用前，先完成依赖安装，并把 `Keil.STM32H5xx_DFP.2.3.1.pack` 放入上述 Pack 目录；也可以从 Windows 的 `data/packs` 复制同名文件。

### Linux 常见问题

- **USB 能看到、界面找不到探针或提示 Access denied**：先用 `lsusb` 确认 USB 枚举，安装匹配的 udev 规则并拔插。检查是否在本地活动会话，SSH 使用上面的组授权。CMSIS-DAP 不是串口设备，仅加入 `dialout` 组通常不能解决 USB 权限问题。
- **`No backend available` / libusb 无法加载**：确认已安装 `libusb-1.0-0`，Python 依赖来自同一个环境；用 `./run_tool.sh --pyocd-cli list` 复查。不需要强制切换 pyOCD USB 后端。
- **`Could not load the Qt platform plugin "xcb"`**：确认系统运行库已经安装，尤其是 `libxcb-cursor0` 和 `libxkbcommon-x11-0`。用 `QT_DEBUG_PLUGINS=1 ./run_tool.sh` 查看具体缺失库。如果旧环境设置了 `QT_PLUGIN_PATH` 或 `QT_QPA_PLATFORM_PLUGIN_PATH`，先取消它们后重试，避免加载不匹配的 Qt 插件。
- **`could not connect to display` / 未找到桌面显示会话**：在有图形桌面的本地终端启动；纯 SSH 可以运行 `--pyocd-cli list`。Wayland 下若插件或桌面集成异常，可在已经安装 XWayland 的会话中试用 `QT_QPA_PLATFORM=xcb ./run_tool.sh`。
- **中文显示为方框**：安装 `fonts-noto-cjk` 后重新启动程序。
- **`externally-managed-environment`**：请使用 `.venv` / Conda 安装，不使用 `sudo pip` 或 `--break-system-packages`。
- **WSL / 容器检测不到探针**：宿主 USB 设备必须显式传入运行环境；这些环境未纳入当前适配验证范围。

## 基本使用

Windows 和 Linux 使用相同界面和下载流程：

1. 将 CMSIS-DAP 调试器的 `SWDIO`、`SWCLK`、`GND`、`NRST` 和 `VDD_TARGET` 接到目标板。
2. 选择固件、DAP 探针和目标芯片参数。
3. 点击“开始下载”，核对确认窗口后继续。

优先选择 ELF 文件，因为 ELF 自带烧录地址。选择 BIN 文件时，默认基地址为 `0x08000000`。

CMSIS Pack 文件不会提交到 Git 仓库。首次使用时工具会从官方地址下载并缓存，之后可直接复用。Windows 使用 `data/packs`，Linux 缓存目录见下文。

## 项目结构

```text
dap_tool.py         PySide6 图形入口
dap_core.py         固件、探针与下载逻辑
dap_platform.py     平台目录与运行支持
run_tool.*          源码运行入口
build_linux.sh      Linux 分发包构建
build_exe.bat       Windows EXE 构建
scripts/ + udev/    Linux 设备访问规则
test_*.py           核心、平台与 GUI 回归测试
```

## 文档

[Windows 运行](#windows-快速运行) · [Linux 运行及排障](#linux-快速运行) · [Linux 打包](#打包-linux-独立程序) · [Windows 打包](#打包独立-exe) · [结果判断](#下载结果判断)

## 打包 Linux 独立程序

在 Linux 本机运行：

```bash
./build_linux.sh
```

脚本复用运行脚本的 Python 环境选择逻辑，安装 `requirements-build.txt`，然后使用 PyInstaller 构建目录分发包。打包不会下载 Device Pack，也不会写入系统 udev 规则。x86_64 当前版本输出：

```text
dist/DAP-Downloader-v0.0.1-linux-x86_64/
  DAP-Downloader-v0.0.1-linux-x86_64
  _internal/
  README.md
  scripts/install_udev_rules.sh
  udev/60-dap-downloader.rules
dist/DAP-Downloader-v0.0.1-linux-x86_64.tar.gz
```

向其他电脑分发完整 `.tar.gz`，保留整个解压目录及 `_internal`，然后运行：

```bash
tar -xzf DAP-Downloader-v0.0.1-linux-x86_64.tar.gz
cd DAP-Downloader-v0.0.1-linux-x86_64
./DAP-Downloader-v0.0.1-linux-x86_64
# 无桌面时检查内置 pyOCD：
./DAP-Downloader-v0.0.1-linux-x86_64 --pyocd-cli list
```

分发包自带 Python 和 Python 依赖；目标系统仍需上述 USB / Qt 运行库及设备访问权限。可以直接使用包内的 `scripts/install_udev_rules.sh` 配置权限。源码运行示例中的 `run_tool.sh` 不包含在独立包中，改用可执行文件本身。

PyInstaller 不跨平台或跨 CPU 架构编译，Linux 包必须在 Linux 上构建。glibc 通常不能向旧版本兼容，因此应在计划支持的最旧发行版上构建，并在目标系统上验证；Ubuntu 24.04 构建的包不能据此宣称兼容 Ubuntu 22.04。参见 [PyInstaller Linux 兼容性说明](https://pyinstaller.org/en/stable/usage.html#making-linux-apps-forward-compatible)。

## 打包独立 EXE

双击 `build_exe.bat`。输出目录为：

```text
dist\DAP-Downloader-v0.0.1.exe
```

这是一个独立的 Windows 单文件程序，可直接复制到其他 Windows 电脑运行。首次运行后，程序会在 EXE 同目录创建 `data` 目录，用于保存设置和 CMSIS Pack 缓存；若该目录不可写，则改用当前用户的本地应用数据目录。

## 开发验证

安装 `requirements-build.txt` 后可以执行不连接目标板的回归检查：

```bash
python -m unittest discover -v
python dap_tool.py --pyocd-cli --version
```

测试覆盖平台目录、固件扫描与参数、界面语言、子进程日志和停止/退出回收；GUI 测试默认使用 Qt offscreen。GitHub Actions 配置了 Windows / Ubuntu 的测试，以及 Ubuntu 22.04 上的 Linux 打包、内置 CLI 和 X11 窗口启动检查。

本次本地验证环境为 Ubuntu 24.04 x86_64、Python 3.12：源码界面与打包程序均完成 X11 启动验证。尚未进行目标板实际烧录、Windows 本地运行、Wayland 原生运行和 ARM64 验证。测试与探针枚举不会擦写 MCU；真实烧录需连接探针与目标板后人工验证。

## 下载结果判断

出现以下信息并且 pyOCD 返回码为 `0`，表示下载成功：

```text
Erased ... bytes, programmed ... bytes
下载成功，MCU 已复位。
```

如果出现 `Unexpected ACK '0'`、`SWD/JTAG communication failure` 或返回码 `1`，说明本次下载失败。请检查 USB、目标板供电、共地、SWD 接线和 NRST，并尝试把 SWD 频率降低到 `500 kHz` 或 `100 kHz`。

## 安全说明

下载操作会擦除并覆盖目标 MCU 的相关 Flash 区域。开启读保护或安全产品状态时，请先使用 STM32CubeProgrammer 检查 Option Bytes，不要盲目执行整片擦除。

## 致谢与许可

### 致谢与参考项目

- [pyOCD](https://pyocd.io/docs/installing#udev-rules-on-linux)：探针访问与烧录后端，Linux 权限配置参考其官方说明。
- [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6.8/gettingstarted.html)：图形界面依赖；运行库参照 [Qt 6.8 Linux 说明](https://doc.qt.io/qt-6.8/linux-requirements.html)。
- [PyInstaller](https://pyinstaller.org/en/stable/usage.html#making-linux-apps-forward-compatible)：独立程序打包工具；打包不改变依赖授权。
- Keil STM32H5 CMSIS Device Pack：目标芯片支持资源，按需下载，不作为本仓库自有代码重新授权。

### 许可

当前仓库未声明统一许可证；现有第三方代码、模型和依赖的署名及许可仍须分别遵守。本次文档整理不新增或变更授权。
