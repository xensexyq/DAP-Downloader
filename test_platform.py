from __future__ import annotations

import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dap_platform import format_command, get_app_paths


class AppPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.app_dir = self.root / "application"
        # Never consult or write the test runner's actual user directories.
        home_patch = patch("dap_platform.Path.home", return_value=self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        env_patch = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": "",
            "XDG_CACHE_HOME": "",
            "LOCALAPPDATA": str(self.root / "local-app-data"),
        })
        env_patch.start()
        self.addCleanup(env_patch.stop)
        platform_patch = patch("dap_platform.sys.platform", "linux")
        platform_patch.start()
        self.addCleanup(platform_patch.stop)

    def assert_directories_ready(self, paths) -> None:
        self.assertTrue(paths.settings_file.parent.is_dir())
        self.assertTrue(paths.pack_dir.is_dir())
        self.assertTrue(paths.settings_file.is_relative_to(self.root))
        self.assertTrue(paths.pack_dir.is_relative_to(self.root))
        self.assertFalse(paths.settings_file.exists())

    def test_linux_absolute_xdg_overrides(self) -> None:
        config = self.root / "配置 目录"
        cache = self.root / "缓存 目录"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config), "XDG_CACHE_HOME": str(cache)}):
            paths = get_app_paths(self.app_dir)

        self.assertEqual(paths.settings_file, config / "dap-downloader" / "settings.json")
        self.assertEqual(paths.pack_dir, cache / "dap-downloader" / "packs")
        self.assert_directories_ready(paths)
        self.assertFalse(self.app_dir.exists())

    def test_linux_empty_xdg_uses_home_defaults_without_app_writes(self) -> None:
        with patch("dap_platform.tempfile.TemporaryFile") as probe:
            paths = get_app_paths(self.app_dir)

        self.assertEqual(paths.settings_file, self.home / ".config" / "dap-downloader" / "settings.json")
        self.assertEqual(paths.pack_dir, self.home / ".cache" / "dap-downloader" / "packs")
        self.assert_directories_ready(paths)
        self.assertFalse(self.app_dir.exists())
        probe.assert_not_called()

    def test_linux_relative_xdg_values_fall_back_independently(self) -> None:
        config = self.root / "config"
        cache = self.root / "cache"
        for config_value, cache_value, expected_config, expected_cache in (
            ("relative-config", str(cache), self.home / ".config", cache),
            (str(config), "relative-cache", config, self.home / ".cache"),
            ("relative-config", "relative-cache", self.home / ".config", self.home / ".cache"),
        ):
            with self.subTest(config=config_value, cache=cache_value):
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": config_value, "XDG_CACHE_HOME": cache_value}):
                    paths = get_app_paths(self.app_dir)
                self.assertEqual(paths.settings_file, expected_config / "dap-downloader" / "settings.json")
                self.assertEqual(paths.pack_dir, expected_cache / "dap-downloader" / "packs")
                self.assert_directories_ready(paths)
        self.assertFalse(self.app_dir.exists())

    def test_windows_writable_installation_keeps_portable_data(self) -> None:
        # Patch sys.platform only: changing os.name makes pathlib instantiate
        # WindowsPath on a POSIX test runner and hides the behavior under test.
        with patch("dap_platform.sys.platform", "win32"):
            paths = get_app_paths(self.app_dir)

        self.assertEqual(paths.settings_file, self.app_dir / "data" / "settings.json")
        self.assertEqual(paths.pack_dir, self.app_dir / "data" / "packs")
        self.assert_directories_ready(paths)
        self.assertFalse((self.root / "local-app-data").exists())
        self.assertEqual(list((self.app_dir / "data").iterdir()), [paths.pack_dir])

    def test_windows_unwritable_installation_uses_localappdata(self) -> None:
        with patch("dap_platform.sys.platform", "win32"):
            with patch("dap_platform.tempfile.TemporaryFile", side_effect=PermissionError("Read-only install")):
                paths = get_app_paths(self.app_dir)

        data = self.root / "local-app-data" / "DAP-Downloader"
        self.assertEqual(paths.settings_file, data / "settings.json")
        self.assertEqual(paths.pack_dir, data / "packs")
        self.assert_directories_ready(paths)
        self.assertFalse((self.app_dir / "data" / "settings.json").exists())

    def test_windows_blocked_data_directory_falls_back_to_home(self) -> None:
        self.app_dir.mkdir()
        (self.app_dir / "data").write_text("existing user file", encoding="utf-8")
        with patch("dap_platform.sys.platform", "win32"):
            with patch.dict(os.environ, {"LOCALAPPDATA": ""}):
                paths = get_app_paths(self.app_dir)

        self.assertEqual(paths.settings_file, self.home / "DAP-Downloader" / "settings.json")
        self.assertEqual(paths.pack_dir, self.home / "DAP-Downloader" / "packs")
        self.assert_directories_ready(paths)
        self.assertEqual((self.app_dir / "data").read_text(encoding="utf-8"), "existing user file")


class CommandDisplayTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX shell quoting")
    def test_posix_command_round_trips_unicode_spaces_and_shell_metacharacters(self) -> None:
        command = [
            "/opt/下载 工具/python",
            "固件 build/设备's app.BIN",
            "--uid",
            'probe; $HOME $(printf unsafe) `echo unsafe` "quoted" & * [a] \\ end',
            "",
            "line one\nline two",
        ]

        self.assertEqual(shlex.split(format_command(command)), command)


if __name__ == "__main__":
    unittest.main()
