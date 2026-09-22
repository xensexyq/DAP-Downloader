#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
    cat <<'HELP'
用法：./run_tool.sh [--pyocd-cli <pyOCD 参数...>]
默认启动图形界面；--pyocd-cli list 在终端检查探针。
优先级：PYTHON > 已激活的 venv/非 base Conda > 项目 .venv（自动创建）。
首次使用会在选中的独立环境安装 requirements.txt，不执行 sudo。
HELP
    exit 0
fi
if [[ "$(uname -s)" != Linux ]]; then
    echo '[错误] 此入口用于 Linux，Windows 请使用 run_tool.bat。' >&2
    exit 1
fi
if [[ "${1:-}" != '--pyocd-cli' && -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" \
    && "${QT_QPA_PLATFORM:-}" != offscreen && "${QT_QPA_PLATFORM:-}" != minimal ]]; then
    echo '[错误] 未找到桌面显示会话。请在 Linux 桌面终端运行，或用 --pyocd-cli list 检查探针。' >&2
    exit 1
fi
# shellcheck source=scripts/linux_common.sh
source "$APP_DIR/scripts/linux_common.sh"
select_python
ensure_runtime_requirements
# Qt 6.8 aborts the process when xcb-cursor cannot load; report an actionable error first.
# CLI, Wayland and headless test platforms do not require the XCB plugin.
if [[ "${1:-}" != '--pyocd-cli' ]] && { [[ "${QT_QPA_PLATFORM:-}" == xcb || "${QT_QPA_PLATFORM:-}" == xcb:* ]] \
    || [[ -z "${QT_QPA_PLATFORM:-}" && -n "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; }; then
    "$DAP_PYTHON" - <<'PYTHON'
import ctypes
import sys
from pathlib import Path
from PySide6.QtCore import QLibraryInfo
try:
    plugin_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    ctypes.CDLL(str(plugin_dir / "platforms" / "libqxcb.so"))
except OSError as exc:
    print("[错误] 无法加载 Qt X11 插件：" + str(exc), file=sys.stderr)
    print("缺少 libxcb-cursor.so.0 时，Ubuntu/Debian 请执行 sudo apt install libxcb-cursor0；完整依赖见 README.md 的 Linux 快速运行。", file=sys.stderr)
    sys.exit(1)
PYTHON
fi
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
exec "$DAP_PYTHON" "$APP_DIR/dap_tool.py" "$@"
