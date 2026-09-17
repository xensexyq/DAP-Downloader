@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

python -m PyInstaller --noconfirm --clean --windowed --onefile --name DAP-Downloader --collect-submodules pyocd --collect-data pyocd --copy-metadata pyocd --collect-all cmsis_pack_manager --collect-all libusb_package --hidden-import hid --hidden-import usb.backend.libusb1 --exclude-module IPython --exclude-module matplotlib --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 dap_tool.py
if errorlevel 1 exit /b 1

echo.
echo 打包完成：%~dp0dist\DAP-Downloader.exe
pause
