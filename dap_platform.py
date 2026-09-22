"""Platform-specific paths and command display, without GUI dependencies."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class AppPaths:
    settings_file: Path
    pack_dir: Path


def _xdg_dir(variable: str, default: Path) -> Path:
    value = os.environ.get(variable, "")
    path = Path(value)
    return path if value and path.is_absolute() else default


def get_app_paths(app_dir: Path) -> AppPaths:
    """Use per-user Linux directories and retain Windows portable data storage."""
    if sys.platform.startswith("linux"):
        config = _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config") / "dap-downloader"
        cache = _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache") / "dap-downloader"
        paths = AppPaths(config / "settings.json", cache / "packs")
    else:
        data = app_dir / "data"
        try:
            data.mkdir(parents=True, exist_ok=True)
            # A unique probe avoids overwriting files or racing another instance.
            with tempfile.TemporaryFile(dir=data):
                pass
        except OSError:
            data = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DAP-Downloader"
        paths = AppPaths(data / "settings.json", data / "packs")
    paths.settings_file.parent.mkdir(parents=True, exist_ok=True)
    paths.pack_dir.mkdir(parents=True, exist_ok=True)
    return paths


def path_key(path: Path) -> str:
    """Fold case only on platforms where os.path defines it as insignificant."""
    return os.path.normcase(str(path.resolve()))


def format_command(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))
    return shlex.join(command)
