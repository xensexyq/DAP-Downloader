from __future__ import annotations

import sys
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

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux case-sensitive paths")
    def test_discovery_preserves_case_distinct_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upper = root / "APP.elf"
            lower = root / "app.elf"
            upper.write_bytes(b"upper")
            lower.write_bytes(b"lower")
            if upper.samefile(lower):
                self.skipTest("Temporary filesystem is case-insensitive")

            result = discover_firmware([root, root, root / "."])

            self.assertEqual(len(result), 2)
            self.assertEqual({item.path for item in result}, {upper.resolve(), lower.resolve()})

    def test_discovery_deduplicates_overlapping_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = root / "build"
            build.mkdir()
            firmware = build / "app.hex"
            firmware.write_bytes(b"hex")

            result = discover_firmware([root, build, root])

            self.assertEqual([item.path for item in result], [firmware.resolve()])

    def test_uppercase_extensions_have_explicit_format_and_do_not_wait(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "device.pack"
            pack.write_bytes(b"pack")
            for suffix, expected_format in (("AXF", "elf"), ("ELF", "elf"), ("HEX", "hex"), ("BIN", "bin")):
                with self.subTest(suffix=suffix):
                    firmware = root / f"固件 release.{suffix}"
                    firmware.write_bytes(b"firmware")
                    args = build_pyocd_load_args(
                        firmware, pack, "STM32H562VGTx", "probe-id", "1m", "under-reset", "sector",
                    )

                    self.assertEqual(args[args.index("--format") + 1], expected_format)
                    self.assertIn("--no-wait", args)
                    self.assertEqual(args[1], str(firmware))
                    if suffix == "BIN":
                        self.assertEqual(args[args.index("--base-address") + 1], "0x08000000")
                    else:
                        self.assertNotIn("--base-address", args)

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
