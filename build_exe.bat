@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

python -m PyInstaller --noconfirm --clean --windowed --onedir --name DAP-Downloader --collect-submodules pyocd --collect-data pyocd --collect-all cmsis_pack_manager --collect-all libusb_package --hidden-import hid --hidden-import usb.backend.libusb1 --collect-all PySide6 dap_tool.py
if errorlevel 1 exit /b 1

copy /y README.md "dist\DAP-Downloader\README.md" >nul
if not exist "dist\DAP-Downloader\data\packs" mkdir "dist\DAP-Downloader\data\packs"

echo.
echo 打包完成：%~dp0dist\DAP-Downloader\DAP-Downloader.exe
pause
