#!/usr/bin/env bash
# Shared by the Linux launch and build entry points; source after setting APP_DIR.

select_python() {
    if [[ -n "${PYTHON:-}" ]]; then
        DAP_PYTHON="$PYTHON"
    elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
        DAP_PYTHON="$VIRTUAL_ENV/bin/python"
    elif [[ -n "${CONDA_PREFIX:-}" && "${CONDA_DEFAULT_ENV:-}" != base ]]; then
        DAP_PYTHON="$CONDA_PREFIX/bin/python"
    elif [[ -x "$APP_DIR/.venv/bin/python" ]]; then
        DAP_PYTHON="$APP_DIR/.venv/bin/python"
    else
        if ! command -v python3 >/dev/null 2>&1; then
            echo '[错误] 未找到 Python 3，请先安装 Python 3.10–3.13 和 venv。' >&2
            return 1
        fi
        if ! python3 -m venv "$APP_DIR/.venv"; then
            echo '[错误] 无法创建 .venv。Ubuntu/Debian 请安装 python3-venv，或激活 Conda 环境。' >&2
            return 1
        fi
        DAP_PYTHON="$APP_DIR/.venv/bin/python"
    fi
    if ! command -v "$DAP_PYTHON" >/dev/null 2>&1; then
        printf '[错误] Python 不可执行：%s\n' "$DAP_PYTHON" >&2
        return 1
    fi
    "$DAP_PYTHON" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info < (3, 14) else "[错误] 固定依赖要求 Python 3.10–3.13，推荐 3.11。")'
}

install_requirements() {
    local requirement_file="$1"
    # Never turn a launcher into a system-wide pip install (PEP 668).
    if ! "$DAP_PYTHON" -c 'import os, sys; sys.exit(0 if sys.prefix != sys.base_prefix or os.path.isdir(os.path.join(sys.prefix, "conda-meta")) else 1)'; then
        echo '[错误] 需要安装依赖，但当前 Python 不是 venv/Conda 环境。请创建并激活独立环境后重试。' >&2
        return 1
    fi
    "$DAP_PYTHON" -m pip install -r "$APP_DIR/$requirement_file"
}

ensure_runtime_requirements() {
    if ! "$DAP_PYTHON" - <<'PY'
import importlib.metadata
import sys
try:
    ready = all(importlib.metadata.version(name) == version for name, version in (
        ("pyocd", "0.45.1"), ("PySide6", "6.8.3")))
except importlib.metadata.PackageNotFoundError:
    ready = False
sys.exit(0 if ready else 1)
PY
    then
        echo '正在为独立 Python 环境安装运行依赖…'
        install_requirements requirements.txt
    fi
}
