"""Headless GUI and CLI integration checks; these tests never flash a device."""

from __future__ import annotations

import importlib.metadata
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import dap_tool


class GUIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication(["test_gui"])
        cls.qt_app.setQuitOnLastWindowClosed(False)
        dap_tool._apply_styles(cls.qt_app)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.application_dir = self.root / "application"
        self.application_dir.mkdir()
        # Both platforms get isolated user data, including Windows' portable data.
        patches = [
            mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(self.root / "config"),
                    "XDG_CACHE_HOME": str(self.root / "cache"),
                    "LOCALAPPDATA": str(self.root / "local"),
                },
            ),
            mock.patch("dap_tool._application_dir", return_value=self.application_dir),
            mock.patch.object(dap_tool.DAPDownloaderApp, "refresh_firmware"),
            mock.patch.object(dap_tool.DAPDownloaderApp, "refresh_probes"),
            mock.patch.object(dap_tool.QTimer, "singleShot"),
            mock.patch.object(dap_tool.DAPDownloaderApp, "_show_message"),
            mock.patch.object(dap_tool.DAPDownloaderApp, "_confirm_simple", return_value=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.window = dap_tool.DAPDownloaderApp()
        self.window._poll_timer.stop()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_language_switch_preserves_parameters_and_persists_settings(self) -> None:
        combos = (self.window.frequency_combo, self.window.connect_combo, self.window.erase_combo)
        selected = [combo.currentData() for combo in combos]
        self.assertEqual(self.window.language, "zh")

        self.window.toggle_language()

        self.assertEqual(self.window.language_button.text(), "Language: English")
        self.assertEqual([combo.currentData() for combo in combos], selected)
        saved = json.loads(self.window.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["language"], "en")
        self.assertEqual(self.window._load_settings()["language"], "en")

        self.window.toggle_language()

        self.assertEqual(self.window.language_button.text(), "语言：中文")
        self.assertEqual([combo.currentData() for combo in combos], selected)
        saved = json.loads(self.window.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["language"], "zh")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux XDG layout")
    def test_linux_keeps_settings_and_downloads_outside_application_directory(self) -> None:
        self.window._save_settings()

        self.assertEqual(
            self.window.settings_file,
            self.root / "config" / "dap-downloader" / "settings.json",
        )
        self.assertEqual(
            self.window.default_pack.parent,
            self.root / "cache" / "dap-downloader" / "packs",
        )
        self.assertTrue(self.window.settings_file.is_file())
        self.assertTrue(self.window.default_pack.parent.is_dir())
        self.assertEqual(list(self.application_dir.iterdir()), [])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux USB permissions guidance")
    def test_no_probe_help_mentions_linux_permissions_in_both_languages(self) -> None:
        for language in ("zh", "en"):
            with self.subTest(language=language):
                if self.window.language != language:
                    self.window.toggle_language()
                self.window.events.put(("probes", []))

                self.window._poll_events()

                self.assertEqual(self.window.probe_combo.count(), 0)
                # Check the displayed guidance rather than a translation helper.
                labels = self.window.findChildren(dap_tool.QLabel)
                guidance = "\n".join(label.text() for label in labels)
                self.assertIn("udev", guidance.lower())
                self.assertNotIn("USB driver", guidance)

    def test_styled_form_controls_fit_their_rows_at_supported_window_sizes(self) -> None:
        self.window.show()
        for language in ("zh", "en"):
            if self.window.language != language:
                self.window.toggle_language()
            for width, height in ((1120, 820), (900, 620), (1120, 900), (900, 620)):
                with self.subTest(language=language, size=(width, height)):
                    self.window.resize(width, height)
                    self.window.events.put(("probes", []))
                    self.window._poll_events()
                    # Startup timers are mocked, so perform their text/layout pass.
                    QTest.qWait(50)  # Allow X11's asynchronous resize notifications to settle.
                    self.window._refresh_text_minimum_heights()
                    QTest.qWait(50)
                    self.assertLessEqual(
                        self.window.height(), max(height, self.window.minimumSizeHint().height())
                    )
                    for row, control in enumerate((
                        self.window.firmware_combo, self.window.probe_combo, self.window.target_combo
                    )):
                        cell = self.window.firmware_grid.cellRect(row, 1)
                        self.assertGreaterEqual(control.geometry().top(), cell.top())
                        self.assertLessEqual(
                            control.geometry().bottom(), cell.bottom(),
                            f"font={control.font().family()}, compact={self.window._compact_mode}, "
                            f"section={control.parentWidget().geometry()}, cell={cell}, "
                            f"control={control.geometry()}",
                        )
                    for grid in (self.window.firmware_grid, self.window.pack_grid, self.window.options_grid):
                        widgets = [grid.itemAt(i).widget() for i in range(grid.count())]
                        visible = [widget for widget in widgets if widget is not None and widget.isVisible()]
                        for index, first in enumerate(visible):
                            self.assertTrue(first.parentWidget().rect().contains(first.geometry()))
                            for second in visible[index + 1:]:
                                self.assertFalse(
                                    first.geometry().intersects(second.geometry()),
                                    f"Overlapping controls: {first.geometry()} and {second.geometry()}",
                                )

    def _drain_events(self) -> list[tuple[str, object]]:
        events = []
        while True:
            try:
                events.append(self.window.events.get_nowait())
            except queue.Empty:
                return events

    def test_worker_streams_utf8_and_stderr_and_reports_exit_status(self) -> None:
        code = "import sys; print('连接成功'); print('diagnostic', file=sys.stderr); sys.exit(7)"

        self.window._flash_worker([sys.executable, "-u", "-c", code])

        events = self._drain_events()
        log = "".join(str(payload) for event, payload in events if event == "log")
        self.assertIn("连接成功", log)
        self.assertIn("diagnostic", log)
        self.assertIn(("flash_started", None), events)
        self.assertIn(("flash_done", 7), events)
        self.assertFalse(any(event == "error" for event, _ in events))
        self.assertIsNone(self.window.flash_process)

    def test_stop_terminates_worker_process_and_reaps_it(self) -> None:
        # This child only prints and sleeps. No pyOCD or connected hardware is used.
        command = [sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(30)"]
        worker = threading.Thread(target=self.window._flash_worker, args=(command,), daemon=True)
        worker.start()
        process = None
        try:
            while True:
                event, payload = self.window.events.get(timeout=10)
                if event == "error":
                    self.fail(str(payload))
                if event == "log" and "ready" in str(payload):
                    break
            process = self.window.flash_process
            self.assertIsNotNone(process)

            self.window.stop_flash()
            worker.join(timeout=10)

            self.assertFalse(worker.is_alive(), "Stopping must release the subprocess worker")
            self.assertIsNotNone(process.poll())
            self.assertIsNone(self.window.flash_process)
            exits = [payload for event, payload in self._drain_events() if event == "flash_done"]
            self.assertEqual(len(exits), 1)
            self.assertNotEqual(exits[0], 0)
        finally:
            # A failed assertion must never leave the test child alive.
            process = process or self.window.flash_process
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            worker.join(timeout=10)


    def test_close_prevents_pending_worker_from_starting_a_process(self) -> None:
        self.window._set_busy(True, "Connecting", "flash")

        def pending_worker() -> None:
            # Reproduce closing after the UI is busy but before Popen is reached.
            self.window._flash_cancel.wait(timeout=5)
            self.window._flash_worker([sys.executable, "-c", "pass"])

        worker = threading.Thread(target=pending_worker, daemon=True)
        self.window._flash_thread = worker
        event = QCloseEvent()
        with mock.patch("dap_tool.subprocess.Popen") as popen:
            worker.start()
            try:
                self.window.closeEvent(event)

                self.assertTrue(event.isAccepted())
                self.assertFalse(worker.is_alive())
                popen.assert_not_called()
                self.assertIsNone(self.window.flash_process)
            finally:
                self.window._flash_cancel.set()
                worker.join(timeout=10)
                self.window._flashing = False


class CLIIntegrationTests(unittest.TestCase):
    def test_embedded_cli_version_without_qt_or_a_display(self) -> None:
        script = Path(dap_tool.__file__).resolve()
        # Reject Qt imports to catch regressions even on machines with working Qt.
        runner = """
import importlib.abc
import runpy
import sys

class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PySide6' or fullname.startswith('PySide6.'):
            raise ImportError('Qt is unavailable in this headless CLI test')
        return None

sys.meta_path.insert(0, NoQt())
sys.argv = [sys.argv[1], '--pyocd-cli', '--version']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        environment = os.environ.copy()
        environment.pop("DISPLAY", None)
        environment.pop("WAYLAND_DISPLAY", None)
        environment["QT_QPA_PLATFORM"] = "nonexistent-test-platform"

        result = subprocess.run(
            [sys.executable, "-c", runner, str(script)],
            cwd=script.parent,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(importlib.metadata.version("pyocd"), result.stdout)


if __name__ == "__main__":
    unittest.main()
