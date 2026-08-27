from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


APP_NAME = "DAP-Downloader"
DEFAULT_TARGET = "STM32H562VGTx"
DEFAULT_FREQUENCY = "1m"
DEFAULT_CONNECT_MODE = "under-reset"
DEFAULT_ERASE_MODE = "sector"
DEFAULT_BIN_ADDRESS = "0x08000000"

PACK_VERSION = "2.3.1"
PACK_FILENAME = f"Keil.STM32H5xx_DFP.{PACK_VERSION}.pack"
PACK_URL = f"https://www.keil.com/pack/{PACK_FILENAME}"

SUPPORTED_FIRMWARE_SUFFIXES = {".elf", ".hex", ".bin", ".axf"}
FREQUENCY_PATTERN = re.compile(r"^\d+(?:\.\d+)?(?:[kKmM](?:[hH][zZ])?|[hH][zZ])?$")


@dataclass(frozen=True)
class FirmwareCandidate:
    path: Path
    label: str
    modified_time: float
    score: int


def _firmware_kind(path: Path) -> str:
    lowered = str(path).lower().replace("\\", "/")
    name = path.name.lower()
    if "master" in name or "/master" in lowered:
        role = "主爪"
    elif "slave" in name or "/slave" in lowered:
        role = "从爪"
    else:
        role = "固件"

    if "release" in lowered:
        variant = "Release"
    elif "debug" in lowered:
        variant = "Debug"
    else:
        variant = ""
    return f"{role} {variant}".strip()


def _firmware_score(path: Path) -> int:
    lowered = str(path).lower().replace("\\", "/")
    score = 0
    if path.suffix.lower() in {".elf", ".axf"}:
        score += 100
    elif path.suffix.lower() == ".hex":
        score += 70
    else:
        score += 30
    if "release" in lowered:
        score += 50
    if "debug" in lowered:
        score -= 10
    return score


def discover_firmware(search_roots: Iterable[Path]) -> list[FirmwareCandidate]:
    """Return firmware files, with the most useful/recent files first."""
    found: dict[str, FirmwareCandidate] = {}
    for root in search_roots:
        root = Path(root)
        if not root.exists() or not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                try:
                    if not path.is_file() or path.suffix.lower() not in SUPPORTED_FIRMWARE_SUFFIXES:
                        continue
                    stat = path.stat()
                except OSError:
                    continue
                key = str(path.resolve()).casefold()
                kind = _firmware_kind(path)
                label = f"{kind} | {path.name} | {path.parent}"
                found[key] = FirmwareCandidate(
                    path=path.resolve(),
                    label=label,
                    modified_time=stat.st_mtime,
                    score=_firmware_score(path),
                )
        except OSError:
            continue

    return sorted(
        found.values(),
        key=lambda item: (item.score, item.modified_time),
        reverse=True,
    )


def validate_flash_settings(
    firmware: Path,
    pack: Path,
    target: str,
    probe_uid: str,
    frequency: str,
    connect_mode: str,
    erase_mode: str,
    bin_address: str,
    *,
    require_pack: bool = True,
) -> None:
    firmware = Path(firmware)
    pack = Path(pack)
    if not firmware.is_file():
        raise ValueError(f"固件文件不存在：{firmware}")
    if firmware.suffix.lower() not in SUPPORTED_FIRMWARE_SUFFIXES:
        raise ValueError("仅支持 ELF、AXF、HEX 和 BIN 固件。")
    if require_pack and not pack.is_file():
        raise ValueError(f"CMSIS-Pack 不存在：{pack}")
    if not target.strip():
        raise ValueError("Target 不能为空。")
    if not probe_uid.strip():
        raise ValueError("请选择一个 DAP 探针。")
    if not FREQUENCY_PATTERN.fullmatch(frequency.strip()):
        raise ValueError("SWD 频率格式无效，例如可填写 100k、1m 或 2.5m。")
    if connect_mode not in {"under-reset", "halt", "pre-reset", "attach"}:
        raise ValueError("连接模式无效。")
    if erase_mode not in {"sector", "chip", "auto"}:
        raise ValueError("擦除模式无效。")
    if firmware.suffix.lower() == ".bin":
        try:
            address = int(bin_address, 0)
        except ValueError as exc:
            raise ValueError("BIN 基地址格式无效，例如 0x08000000。") from exc
        if address < 0:
            raise ValueError("BIN 基地址不能为负数。")


def build_pyocd_load_args(
    firmware: Path,
    pack: Path,
    target: str,
    probe_uid: str,
    frequency: str,
    connect_mode: str,
    erase_mode: str,
    bin_address: str = DEFAULT_BIN_ADDRESS,
) -> list[str]:
    validate_flash_settings(
        firmware,
        pack,
        target,
        probe_uid,
        frequency,
        connect_mode,
        erase_mode,
        bin_address,
    )
    args = [
        "load",
        str(Path(firmware)),
        "--pack",
        str(Path(pack)),
        "--target",
        target.strip(),
        "--uid",
        probe_uid.strip(),
        "--frequency",
        frequency.strip(),
        "--connect",
        connect_mode,
        "--erase",
        erase_mode,
        "--color",
        "never",
    ]
    if Path(firmware).suffix.lower() == ".bin":
        args.extend(["--base-address", bin_address.strip()])
    return args


def format_windows_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))
