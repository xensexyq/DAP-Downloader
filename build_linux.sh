#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
    echo '用法：./build_linux.sh'
    echo '在当前 Linux 架构构建独立程序目录及 tar.gz；Python 选择方式同 run_tool.sh。'
    exit 0
fi
if [[ $# -ne 0 || "$(uname -s)" != Linux ]]; then
    echo '[错误] 请在 Linux 上无参数运行 build_linux.sh。' >&2
    exit 1
fi
# shellcheck source=scripts/linux_common.sh
source "$APP_DIR/scripts/linux_common.sh"
select_python
install_requirements requirements-build.txt
cd -- "$APP_DIR"
APP_VERSION="$("$DAP_PYTHON" -c 'from dap_core import APP_VERSION; print(APP_VERSION)')"
APP_BUNDLE="DAP-Downloader-v${APP_VERSION}-linux-$(uname -m)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export PYINSTALLER_CONFIG_DIR="$APP_DIR/build/pyinstaller-cache"

# A venv may still use a Conda Python and its native libraries. Prefer that
# matching ABI during dependency collection (notably pyexpat/libexpat), while
# preserving caller-supplied paths for additional system/Qt runtime libraries.
DAP_CONDA_LIB="$("$DAP_PYTHON" - <<'PYTHON'
import sys
from pathlib import Path
base = Path(sys.base_prefix)
if (base / "conda-meta").is_dir() and (base / "lib").is_dir():
    print(base / "lib")
PYTHON
)"
if [[ -n "$DAP_CONDA_LIB" ]]; then
    export LD_LIBRARY_PATH="$DAP_CONDA_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

"$DAP_PYTHON" -m PyInstaller \
    --noconfirm --clean --onedir --noupx \
    --name "$APP_BUNDLE" \
    --collect-submodules pyocd --collect-data pyocd --copy-metadata pyocd \
    --collect-all cmsis_pack_manager --collect-all libusb_package \
    --hidden-import hid --hidden-import usb.backend.libusb1 \
    --exclude-module IPython --exclude-module matplotlib \
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 \
    dap_tool.py

# Keep the optional system setup script beside the program for offline deployment.
mkdir -p "dist/$APP_BUNDLE/scripts" "dist/$APP_BUNDLE/udev"
cp README.md "dist/$APP_BUNDLE/README.md"
cp scripts/install_udev_rules.sh "dist/$APP_BUNDLE/scripts/"
cp udev/60-dap-downloader.rules "dist/$APP_BUNDLE/udev/"
tar -czf "dist/$APP_BUNDLE.tar.gz" -C dist "$APP_BUNDLE"
printf '\n构建完成：%s/dist/%s.tar.gz\n运行：%s/dist/%s/%s\n' \
    "$APP_DIR" "$APP_BUNDLE" "$APP_DIR" "$APP_BUNDLE" "$APP_BUNDLE"
