# DAP-Downloader

面向 STM32H5 的 Windows CMSIS-DAP 固件下载工具。当前默认配置用于 TC-GU-01 的 STM32H562VGT6：

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

## 创建独立 Conda 环境

推荐使用单独的 `dap-downloader` 环境：

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

基本使用流程：

1. 将 CMSIS-DAP 调试器的 `SWDIO`、`SWCLK`、`GND`、`NRST` 和 `VDD_TARGET` 接到目标板。
2. 选择固件、DAP 探针和目标芯片参数。
3. 点击“开始下载”，核对确认窗口后继续。

优先选择 ELF 文件，因为 ELF 自带烧录地址。选择 BIN 文件时，默认基地址为 `0x08000000`。

CMSIS Pack 文件不会提交到 Git 仓库。首次使用时工具会从官方地址下载到 `data/packs`，之后可直接复用。

## 打包独立 EXE

双击 `build_exe.bat`。输出目录为：

```text
dist\DAP-Downloader\
```

将整个 `DAP-Downloader` 文件夹复制到其他 Windows 电脑即可运行。

## 下载结果判断

出现以下信息并且 pyOCD 返回码为 `0`，表示下载成功：

```text
Erased ... bytes, programmed ... bytes
下载成功，MCU 已复位。
```

如果出现 `Unexpected ACK '0'`、`SWD/JTAG communication failure` 或返回码 `1`，说明本次下载失败。请检查 USB、目标板供电、共地、SWD 接线和 NRST，并尝试把 SWD 频率降低到 `500 kHz` 或 `100 kHz`。

## 安全说明

下载操作会擦除并覆盖目标 MCU 的相关 Flash 区域。开启读保护或安全产品状态时，请先使用 STM32CubeProgrammer 检查 Option Bytes，不要盲目执行整片擦除。
