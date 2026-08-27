@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10 或更高版本。
    pause
    exit /b 1
)

python -c "import pyocd" >nul 2>nul
if errorlevel 1 (
    echo 首次运行，正在安装 pyOCD...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] pyOCD 安装失败。
        pause
        exit /b 1
    )
)

python -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo Installing PySide6...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install PySide6.
        pause
        exit /b 1
    )
)

where pythonw >nul 2>nul
if errorlevel 1 (
    python dap_tool.py
) else (
    start "" pythonw "%~dp0dap_tool.py"
)
