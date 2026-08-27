from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dap_core import build_pyocd_load_args, discover_firmware, validate_flash_settings


class DAPCoreTests(unittest.TestCase):
    def test_discovery_prefers_release_elf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            debug_hex = root / "build" / "slave-debug" / "app.hex"
            release_elf = root / "build" / "slave-release" / "app.elf"
            debug_hex.parent.mkdir(parents=True)
            release_elf.parent.mkdir(parents=True)
            debug_hex.write_bytes(b"hex")
            release_elf.write_bytes(b"elf")

            result = discover_firmware([root / "build"])

            self.assertEqual(result[0].path, release_elf.resolve())

    def test_elf_command_does_not_add_base_address(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            firmware = root / "app.elf"
            pack = root / "device.pack"
            firmware.write_bytes(b"elf")
            pack.write_bytes(b"pack")

            args = build_pyocd_load_args(
                firmware,
                pack,
                "STM32H562VGTx",
                "probe-id",
                "1m",
                "under-reset",
                "sector",
            )

            self.assertNotIn("--base-address", args)
            self.assertIn("STM32H562VGTx", args)

    def test_bin_command_adds_base_address(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            firmware = root / "app.bin"
            pack = root / "device.pack"
            firmware.write_bytes(b"bin")
            pack.write_bytes(b"pack")

            args = build_pyocd_load_args(
                firmware,
                pack,
                "STM32H562VGTx",
                "probe-id",
                "500k",
                "under-reset",
                "sector",
                "0x08000000",
            )

            index = args.index("--base-address")
            self.assertEqual(args[index + 1], "0x08000000")

    def test_invalid_frequency_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            firmware = root / "app.elf"
            firmware.write_bytes(b"elf")

            with self.assertRaisesRegex(ValueError, "频率"):
                validate_flash_settings(
                    firmware,
                    root / "missing.pack",
                    "STM32H562VGTx",
                    "probe-id",
                    "fast",
                    "under-reset",
                    "sector",
                    "0x08000000",
                    require_pack=False,
                )


if __name__ == "__main__":
    unittest.main()
