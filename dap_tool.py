from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QFontMetrics, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QBoxLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dap_core import (
    APP_NAME,
    DEFAULT_BIN_ADDRESS,
    DEFAULT_CONNECT_MODE,
    DEFAULT_ERASE_MODE,
    DEFAULT_FREQUENCY,
    DEFAULT_TARGET,
    PACK_FILENAME,
    PACK_URL,
    build_pyocd_load_args,
    discover_firmware,
    format_windows_command,
    validate_flash_settings,
)


class SafeComboBox(QComboBox):
    """Prevent accidental parameter changes from page scrolling."""

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API name
        line_edit_focused = self.lineEdit() is not None and self.lineEdit().hasFocus()
        if (self.hasFocus() or line_edit_focused) and self.count() > 1:
            super().wheelEvent(event)
        else:
            event.ignore()

    def showPopup(self) -> None:  # noqa: N802 - Qt API name
        if self.count() > 0:
            metrics = QFontMetrics(self.view().font())
            content_width = max(metrics.horizontalAdvance(self.itemText(index)) for index in range(self.count()))
            popup_width = max(self.width(), content_width + 54)
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                popup_width = min(popup_width, screen.availableGeometry().width() - 32)
            self.view().setMinimumWidth(popup_width)
            for index in range(self.count()):
                self.setItemData(index, self.itemText(index), Qt.ItemDataRole.ToolTipRole)
        super().showPopup()


def _run_embedded_pyocd() -> int | None:
    if len(sys.argv) < 2 or sys.argv[1] != "--pyocd-cli":
        return None
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYOCD_COLOR", "never")
    from pyocd.__main__ import PyOCDTool

    return PyOCDTool().run(sys.argv[2:])


def _application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _data_dir(app_dir: Path) -> Path:
    preferred = app_dir / "data"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        test_file = preferred / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return preferred
    except OSError:
        fallback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DAP-Downloader"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class DAPDownloaderApp(QMainWindow):
    """Simple Qt front-end for the existing pyOCD workflow."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 620)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            min_width = max(760, min(900, available.width() - 32))
            min_height = max(540, min(620, available.height() - 48))
            self.setMinimumSize(min_width, min_height)
            initial_width = min(1120, max(min_width, int(available.width() * 0.84)))
            initial_height = min(820, max(min_height, int(available.height() * 0.84)))
            self.resize(initial_width, initial_height)
        else:
            self.resize(1120, 760)

        self.app_dir = _application_dir()
        self.data_dir = _data_dir(self.app_dir)
        self.settings_file = self.data_dir / "settings.json"
        self.default_pack = self.data_dir / "packs" / PACK_FILENAME
        self.default_pack.parent.mkdir(parents=True, exist_ok=True)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.flash_process: subprocess.Popen[str] | None = None
        self.firmware_by_label: dict[str, Path] = {}
        self.probe_by_label: dict[str, str] = {}
        self.settings = self._load_settings()
        self._busy = False
        self._flashing = False
        self._compact_mode = False
        self.language = str(self.settings.get("language", "zh")).lower()
        if self.language not in {"zh", "en"}:
            self.language = "zh"
        self._language_widgets: list[tuple[object, str, str]] = []
        self._combo_options: list[tuple[QComboBox, tuple[tuple[str, str, str], ...]]] = []

        self._build_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_events)
        self._poll_timer.start(100)
        QTimer.singleShot(150, self.refresh_firmware)
        QTimer.singleShot(300, self.refresh_probes)
        self._update_pack_status()
        self._set_operation_state("idle")
        self._set_status_state("idle")
        self._update_responsive_layout(force=True)
        self._apply_language()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.root_widget = root
        self.setCentralWidget(root)
        self.outer = QVBoxLayout(root)
        outer = self.outer
        outer.setContentsMargins(24, 22, 24, 18)
        outer.setSpacing(16)

        header = QFrame()
        header.setObjectName("Header")
        self.header_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, header)
        header_layout = self.header_layout
        header_layout.setContentsMargins(24, 18, 24, 18)
        header_layout.setSpacing(16)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_label = self._register_text(QLabel(), APP_NAME, APP_NAME)
        self.title_label.setObjectName("Title")
        subtitle = self._register_text(QLabel(), "面向 STM32H562VGT6 的安全固件下载工具", "Safe firmware downloader for STM32H562VGT6")
        self.subtitle_label = subtitle
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(self.title_label)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        self.badge = self._register_text(QLabel(), "CMSIS-DAP  •  STM32H5", "CMSIS-DAP  •  STM32H5")
        self.badge.setObjectName("Badge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.language_button = QPushButton()
        self.language_button.setObjectName("LanguageButton")
        self.language_button.clicked.connect(self.toggle_language)
        header_layout.addWidget(self.language_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(header)

        self.content = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        content = self.content
        content.setSpacing(16)
        outer.addLayout(content, 1)

        form = self._register_text(QGroupBox(), "下载配置", "Download Configuration")
        form.setObjectName("Card")
        self.form_layout = QVBoxLayout(form)
        form_layout = self.form_layout
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(12)
        self.form_card = form
        self.form_card.setMinimumWidth(690)
        content.addWidget(form, 5)

        firmware_section = self._register_text(QGroupBox(), "固件与目标", "Firmware & Target")
        firmware_section.setObjectName("InnerCard")
        self.firmware_grid = QGridLayout(firmware_section)
        firmware_grid = self.firmware_grid
        firmware_grid.setContentsMargins(12, 10, 12, 10)
        firmware_grid.setHorizontalSpacing(8)
        firmware_grid.setVerticalSpacing(8)
        firmware_grid.setColumnStretch(1, 1)

        firmware_grid.addWidget(self._field_label("固件文件", "Firmware File"), 0, 0)
        self.firmware_combo = SafeComboBox()
        self.firmware_combo.setEditable(True)
        firmware_grid.addWidget(self.firmware_combo, 0, 1)
        browse_firmware_button = self._secondary_button("浏览", self.browse_firmware, "Browse")
        firmware_grid.addWidget(browse_firmware_button, 0, 2)
        firmware_grid.addWidget(self._secondary_button("扫描", self.refresh_firmware, "Scan"), 0, 3)

        firmware_grid.addWidget(self._field_label("DAP 探针", "DAP Probe"), 1, 0)
        self.probe_combo = SafeComboBox()
        self.probe_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        firmware_grid.addWidget(self.probe_combo, 1, 1)
        refresh_probe_button = self._secondary_button("刷新探针", self.refresh_probes, "Refresh Probe")
        firmware_grid.addWidget(refresh_probe_button, 1, 2, 1, 2)

        firmware_grid.addWidget(self._field_label("MCU Target", "MCU Target"), 2, 0)
        self.target_combo = SafeComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.addItems(("STM32H562VGTx", "STM32H562VITx", "STM32H562ZITx"))
        self.target_combo.setCurrentText(str(self.settings.get("target", DEFAULT_TARGET)))
        firmware_grid.addWidget(self.target_combo, 2, 1, 1, 3)
        self.target_hint = self._register_text(QLabel(), "默认目标：STM32H562VGTx", "Default target: STM32H562VGTx")
        self.target_hint.setObjectName("Hint")
        firmware_grid.addWidget(self.target_hint, 3, 1, 1, 3)
        form_layout.addWidget(firmware_section)

        pack_section = self._register_text(QGroupBox(), "CMSIS-Pack", "CMSIS-Pack")
        pack_section.setObjectName("InnerCard")
        self.pack_grid = QGridLayout(pack_section)
        pack_grid = self.pack_grid
        pack_grid.setContentsMargins(12, 10, 12, 10)
        pack_grid.setHorizontalSpacing(8)
        pack_grid.setVerticalSpacing(8)
        pack_grid.setColumnStretch(1, 1)
        pack_grid.addWidget(self._field_label("Pack 文件", "Pack File"), 0, 0)
        self.pack_edit = QLineEdit(str(self.settings.get("pack", self.default_pack)))
        pack_grid.addWidget(self.pack_edit, 0, 1)
        pack_grid.addWidget(self._secondary_button("选择", self.browse_pack, "Browse"), 0, 2)
        pack_grid.addWidget(self._secondary_button("准备 Pack", self.prepare_pack, "Prepare Pack"), 0, 3)
        self.pack_status_label = QLabel()
        self.pack_status_label.setObjectName("Hint")
        pack_grid.addWidget(self.pack_status_label, 1, 1, 1, 3)
        form_layout.addWidget(pack_section)

        options = self._register_text(QGroupBox(), "连接参数", "Connection Settings")
        options.setObjectName("InnerCard")
        self.options_grid = QGridLayout(options)
        options_grid = self.options_grid
        options_grid.setContentsMargins(12, 10, 12, 10)
        options_grid.setHorizontalSpacing(8)
        options_grid.setVerticalSpacing(8)
        options_grid.setColumnStretch(1, 1)
        options_grid.setColumnStretch(3, 1)

        self.frequency_combo = SafeComboBox()
        self.frequency_combo.setEditable(True)
        frequency_options = (("100 kHz", "100 kHz", "100k"), ("500 kHz", "500 kHz", "500k"), ("1 MHz", "1 MHz", "1m"), ("2 MHz", "2 MHz", "2m"), ("5 MHz", "5 MHz", "5m"), ("10 MHz", "10 MHz", "10m"))
        for label, _en, value in frequency_options:
            self.frequency_combo.addItem(label, value)
        self._combo_options.append((self.frequency_combo, frequency_options))
        self._set_combo_value(self.frequency_combo, str(self.settings.get("frequency", DEFAULT_FREQUENCY)))
        self.connect_combo = SafeComboBox()
        connect_options = (
            ("复位下连接", "Under Reset", "under-reset"),
            ("暂停后连接", "Halt", "halt"),
            ("复位前连接", "Pre-reset", "pre-reset"),
            ("直接连接", "Attach", "attach"),
        )
        for label, _en, value in connect_options:
            self.connect_combo.addItem(label, value)
        self._combo_options.append((self.connect_combo, connect_options))
        self._set_combo_value(self.connect_combo, str(self.settings.get("connect", DEFAULT_CONNECT_MODE)))
        self.erase_combo = SafeComboBox()
        erase_options = (
            ("按扇区擦除", "Sector Erase", "sector"),
            ("整片擦除", "Chip Erase", "chip"),
            ("自动选择", "Auto Select", "auto"),
        )
        for label, _en, value in erase_options:
            self.erase_combo.addItem(label, value)
        self._combo_options.append((self.erase_combo, erase_options))
        self._set_combo_value(self.erase_combo, str(self.settings.get("erase", DEFAULT_ERASE_MODE)))
        self.frequency_combo.setMinimumWidth(150)
        self.connect_combo.setMinimumWidth(200)
        self.erase_combo.setMinimumWidth(210)
        self.bin_address_edit = QLineEdit(str(self.settings.get("bin_address", DEFAULT_BIN_ADDRESS)))
        self.bin_address_edit.setMinimumWidth(190)
        for combo in (self.frequency_combo, self.connect_combo, self.erase_combo):
            combo.setMinimumContentsLength(10)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setView(QListView())
            combo.view().setMinimumWidth(280)
            combo.view().setSpacing(4)
        options_grid.addWidget(self._field_label("SWD 频率", "Frequency"), 0, 0)
        options_grid.addWidget(self.frequency_combo, 0, 1)
        options_grid.addWidget(self._field_label("连接方式", "Connection"), 0, 2)
        options_grid.addWidget(self.connect_combo, 0, 3)
        options_grid.addWidget(self._field_label("擦除方式", "Erase"), 1, 0)
        options_grid.addWidget(self.erase_combo, 1, 1)
        options_grid.addWidget(self._field_label("BIN 地址", "BIN Base"), 1, 2)
        options_grid.addWidget(self.bin_address_edit, 1, 3)
        form_layout.addWidget(options)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        self.confirm_checkbox = self._register_text(QCheckBox(), "下载前确认", "Confirm before download")
        self.confirm_checkbox.setChecked(bool(self.settings.get("confirm", True)))
        actions.addWidget(self.confirm_checkbox)
        actions.addStretch(1)
        self.stop_button = self._register_text(QPushButton(), "停止下载", "Stop Download")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.clicked.connect(self.stop_flash)
        self.stop_button.setEnabled(False)
        actions.addWidget(self.stop_button)
        self.flash_button = self._register_text(QPushButton(), "开始下载", "Start Download")
        self.flash_button.setObjectName("PrimaryButton")
        self.flash_button.clicked.connect(self.start_flash)
        actions.addWidget(self.flash_button)
        form_layout.addLayout(actions)

        self.operation_card = QFrame()
        self.operation_card.setObjectName("OperationCard")
        self.operation_layout = QHBoxLayout(self.operation_card)
        operation_layout = self.operation_layout
        operation_layout.setContentsMargins(12, 9, 12, 9)
        operation_layout.setSpacing(9)
        self.operation_icon = QLabel("●")
        self.operation_icon.setObjectName("OperationIcon")
        self.operation_icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        operation_layout.addWidget(self.operation_icon)
        operation_text = QVBoxLayout()
        operation_text.setContentsMargins(0, 0, 0, 0)
        operation_text.setSpacing(1)
        self.operation_label = QLabel("等待操作")
        self.operation_label.setObjectName("OperationTitle")
        self.operation_detail = QLabel("请先选择固件文件，确认已连接 DAP 探针，再点击“开始下载”。")
        self.operation_detail.setObjectName("OperationDetail")
        self.operation_detail.setWordWrap(True)
        operation_text.addWidget(self.operation_label)
        operation_text.addWidget(self.operation_detail)
        operation_layout.addLayout(operation_text, 1)
        form_layout.addWidget(self.operation_card)

        log_frame = self._register_text(QGroupBox(), "运行日志", "Operation Log")
        log_frame.setObjectName("Card")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(12, 12, 12, 12)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(10)
        self.log.setFont(mono)
        self.log.setMaximumBlockCount(3000)
        self.log.setPlaceholderText(self._tr("连接、擦除、写入和校验信息会显示在这里。", "Connection, erase, programming, and verify messages appear here."))
        self.log.setObjectName("Log")
        log_layout.addWidget(self.log)
        self.log_frame = log_frame
        self.log_frame.setMinimumWidth(160)
        content.addWidget(log_frame, 6)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(12)
        self.progress.setVisible(False)
        footer.addWidget(self.progress, 1)
        self.status_label = QLabel("正在初始化…")
        self.status_label.setObjectName("Status")
        self.status_label.setMinimumWidth(220)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self.status_label)
        outer.addLayout(footer)

        for combo in (
            self.firmware_combo,
            self.probe_combo,
            self.target_combo,
            self.frequency_combo,
            self.connect_combo,
            self.erase_combo,
        ):
            combo.currentTextChanged.connect(self._update_control_tooltips)
        for edit in (self.pack_edit, self.bin_address_edit):
            edit.textChanged.connect(self._update_control_tooltips)
        self._update_control_tooltips()

    def _field_label(self, zh: str, en: str) -> QLabel:
        label = self._register_text(QLabel(), zh, en)
        label.setObjectName("FieldLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _secondary_button(self, zh: str, slot, en: str | None = None) -> QPushButton:
        button = self._register_text(QPushButton(), zh, en or zh)
        button.setObjectName("SecondaryButton")
        button.clicked.connect(slot)
        return button

    def _update_control_tooltips(self, *_args) -> None:
        firmware = self._selected_firmware_text() if hasattr(self, "firmware_combo") else ""
        tooltip_values = (
            (getattr(self, "firmware_combo", None), firmware),
            (getattr(self, "probe_combo", None), self.probe_combo.currentText().strip()),
            (getattr(self, "target_combo", None), self.target_combo.currentText().strip()),
            (getattr(self, "frequency_combo", None), self.frequency_combo.currentText().strip()),
            (getattr(self, "connect_combo", None), self.connect_combo.currentText().strip()),
            (getattr(self, "erase_combo", None), self.erase_combo.currentText().strip()),
            (getattr(self, "pack_edit", None), self.pack_edit.text().strip()),
            (getattr(self, "bin_address_edit", None), self.bin_address_edit.text().strip()),
        )
        for widget, value in tooltip_values:
            if widget is not None:
                widget.setToolTip(value)
                widget.setToolTipDuration(15000)

    def _register_text(self, widget, zh: str, en: str):
        self._language_widgets.append((widget, zh, en))
        if isinstance(widget, QGroupBox):
            widget.setTitle(zh)
        elif hasattr(widget, "setText"):
            widget.setText(zh)
        return widget

    def _tr(self, zh: str, en: str) -> str:
        return en if self.language == "en" else zh

    def _localized_error(self, message: str) -> str:
        if self.language != "en":
            return message
        replacements = {
            "固件文件不存在：": "Firmware file does not exist: ",
            "仅支持 ELF、AXF、HEX 和 BIN 固件。": "Only ELF, AXF, HEX, and BIN firmware files are supported.",
            "CMSIS-Pack 不存在：": "CMSIS-Pack does not exist: ",
            "Target 不能为空。": "Target cannot be empty.",
            "请选择一个 DAP 探针。": "Select a DAP probe.",
            "SWD 频率格式无效，例如可填写 100k、1m 或 2.5m。": "Invalid SWD frequency. Examples: 100k, 1m, or 2.5m.",
            "连接模式无效。": "Invalid connection mode.",
            "擦除模式无效。": "Invalid erase mode.",
            "BIN 基地址格式无效，例如 0x08000000。": "Invalid BIN base address. Example: 0x08000000.",
            "BIN 基地址不能为负数。": "BIN base address cannot be negative.",
        }
        for zh, en in replacements.items():
            if message.startswith(zh):
                return en + message[len(zh):]
        return message

    def toggle_language(self) -> None:
        self.language = "en" if self.language == "zh" else "zh"
        self._apply_language()
        self._save_settings()

    def _apply_language(self) -> None:
        for widget, zh, en in self._language_widgets:
            text = en if self.language == "en" else zh
            if isinstance(widget, QGroupBox):
                widget.setTitle(text)
            else:
                widget.setText(text)
        for combo, options in self._combo_options:
            current = self._combo_value(combo)
            combo.blockSignals(True)
            combo.clear()
            for zh, en, value in options:
                combo.addItem(en if self.language == "en" else zh, value)
            self._set_combo_value(combo, current)
            combo.blockSignals(False)
        if hasattr(self, "language_button"):
            self.language_button.setText("Language: English" if self.language == "en" else "语言：中文")
        if not self._busy:
            self.setWindowTitle(APP_NAME)
        if hasattr(self, "log"):
            self.log.setPlaceholderText(
                self._tr(
                    "连接、擦除、写入和校验信息会显示在这里。",
                    "Connection, erase, programming, and verify messages appear here.",
                )
            )
        if hasattr(self, "firmware_combo") and self.firmware_by_label:
            selected_path = Path(self._selected_firmware_text())
            paths = list(dict.fromkeys(self.firmware_by_label.values()))
            self.firmware_by_label = {self._firmware_label(path): path for path in paths}
            self.firmware_combo.clear()
            self.firmware_combo.addItems(list(self.firmware_by_label))
            for label, path in self.firmware_by_label.items():
                if path == selected_path:
                    self.firmware_combo.setCurrentText(label)
                    break
        if hasattr(self, "pack_status_label"):
            self._update_pack_status()
        if hasattr(self, "firmware_combo"):
            self._update_control_tooltips()
        self._update_language_dynamic_text()
        if hasattr(self, "content"):
            QTimer.singleShot(0, self._refresh_text_minimum_heights)

    def _update_language_dynamic_text(self) -> None:
        if not hasattr(self, "operation_label"):
            return
        if self._busy:
            return
        firmware_selected = bool(self._selected_firmware_text())
        probe_connected = bool(self.probe_by_label)
        if not firmware_selected:
            self.status_label.setText(self._tr("未选择固件", "No firmware selected"))
            self._set_status_state("warning")
            self._set_operation_message(
                self._tr("需要选择固件", "Firmware Required"),
                self._tr("请点击“浏览”选择 ELF、HEX 或 BIN 文件。", "Click Browse and select an ELF, HEX, or BIN file."),
                "warning",
                "!",
            )
        elif not probe_connected:
            self.status_label.setText(self._tr("未检测到 DAP 探针", "No DAP probe detected"))
            self._set_status_state("warning")
            self._set_operation_message(
                self._tr("等待连接 DAP 探针", "Waiting for DAP Probe"),
                self._tr("请连接 CMSIS-DAP 调试器，并检查 USB 驱动和 SWD 接线。", "Connect a CMSIS-DAP probe and check the USB driver and SWD wiring."),
                "warning",
                "!",
            )
        else:
            self.status_label.setText(self._tr("已准备好", "Ready"))
            self._set_status_state("success")
            self._set_operation_message(
                self._tr("可以开始下载", "Ready to Download"),
                self._tr(
                    "已选择固件并检测到 DAP 探针，请确认参数后开始下载。",
                    "Firmware and a DAP probe are ready. Confirm the settings and start the download.",
                ),
                "success",
                "✓",
            )

    @staticmethod
    def _combo_value(combo: QComboBox) -> str:
        value = combo.currentData()
        return str(value) if value is not None else combo.currentText().strip()

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentText(value)

    def _show_message(self, title: str, message: str, level: str = "info") -> None:
        dialog = QDialog(self)
        dialog.setObjectName("AppDialog")
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        icon = QLabel({"error": "!", "warning": "!", "success": "✓"}.get(level, "i"))
        icon.setObjectName("DialogIcon")
        icon.setProperty("level", level)
        heading.addWidget(icon)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        heading.addWidget(title_label, 1)
        layout.addLayout(heading)

        body = QLabel(message)
        body.setObjectName("DialogMessage")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText(self._tr("知道了", "OK"))
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _confirm_flash(self, firmware: Path, probe_uid: str) -> bool:
        dialog = QDialog(self)
        dialog.setObjectName("AppDialog")
        dialog.setWindowTitle(self._tr("确认下载", "Confirm Download"))
        dialog.setModal(True)
        dialog.setMinimumSize(620, 430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        icon = QLabel("?")
        icon.setObjectName("DialogIcon")
        icon.setProperty("level", "warning")
        heading.addWidget(icon)
        title_label = QLabel(self._tr("请确认下载参数", "Confirm Download Settings"))
        title_label.setObjectName("DialogTitle")
        heading.addWidget(title_label, 1)
        layout.addLayout(heading)

        details = QFrame()
        details.setObjectName("DialogDetails")
        grid = QGridLayout(details)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        values = (
            (self._tr("固件文件", "Firmware File"), firmware.name),
            (self._tr("目标芯片", "Target MCU"), self.target_combo.currentText().strip()),
            (self._tr("DAP 探针", "DAP Probe"), probe_uid or self._tr("未选择", "Not selected")),
            (self._tr("擦除方式", "Erase Mode"), self.erase_combo.currentText().strip()),
        )
        for row, (key, value) in enumerate(values):
            key_label = QLabel(key)
            key_label.setObjectName("DialogKey")
            value_label = QLabel(value)
            value_label.setObjectName("DialogValue")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(key_label, row, 0)
            grid.addWidget(value_label, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(details)

        warning = QLabel(
            self._tr(
                "下载会擦除并覆盖目标 MCU 的相关 Flash 区域。\n"
                "请确认目标板已供电、SWD 接线正确，并且下载过程中不要断开 USB。",
                "This operation erases and overwrites the relevant target MCU Flash regions.\n"
                "Confirm target power and SWD wiring, and do not disconnect USB during download.",
            )
        )
        warning.setObjectName("DialogWarning")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QDialogButtonBox()
        continue_button = buttons.addButton(self._tr("继续下载", "Continue"), QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(self._tr("取消", "Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        continue_button.setObjectName("DialogPrimaryButton")
        cancel_button.setObjectName("DialogCancelButton")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _confirm_simple(self, title: str, message: str, accept_text: str) -> bool:
        dialog = QDialog(self)
        dialog.setObjectName("AppDialog")
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        icon = QLabel("?")
        icon.setObjectName("DialogIcon")
        icon.setProperty("level", "warning")
        heading.addWidget(icon)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        heading.addWidget(title_label, 1)
        layout.addLayout(heading)
        body = QLabel(message)
        body.setObjectName("DialogMessage")
        body.setWordWrap(True)
        layout.addWidget(body)
        buttons = QDialogButtonBox()
        accept_button = buttons.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
        reject_button = buttons.addButton(self._tr("取消", "Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        accept_button.setObjectName("DialogPrimaryButton")
        reject_button.setObjectName("DialogCancelButton")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _load_settings(self) -> dict[str, object]:
        try:
            settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
            saved_pack = Path(str(settings.get("pack", "")))
            if saved_pack.name == PACK_FILENAME and not saved_pack.is_file():
                settings["pack"] = str(self.default_pack)
            return settings
        except (OSError, ValueError, TypeError):
            return {}

    def _save_settings(self) -> None:
        payload = {
            "firmware": self._selected_firmware_text(),
            "target": self.target_combo.currentText().strip(),
            "pack": self.pack_edit.text().strip(),
            "frequency": self._combo_value(self.frequency_combo),
            "connect": self._combo_value(self.connect_combo),
            "erase": self._combo_value(self.erase_combo),
            "bin_address": self.bin_address_edit.text().strip(),
            "confirm": self.confirm_checkbox.isChecked(),
            "language": self.language,
        }
        try:
            self.settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _candidate_roots(self) -> list[Path]:
        roots: list[Path] = []
        seen: set[str] = set()
        for start in [self.app_dir, Path.cwd()]:
            for parent in [start, *list(start.parents)[:5]]:
                for candidate in [parent / "tc-gu-01" / "build", parent / "build"]:
                    key = str(candidate).casefold()
                    if key not in seen and candidate.is_dir():
                        roots.append(candidate)
                        seen.add(key)
        return roots

    def _firmware_label(self, path: Path) -> str:
        lowered = str(path).lower().replace("\\", "/")
        name = path.name.lower()
        if "master" in name or "/master" in lowered:
            role = self._tr("主爪", "Master")
        elif "slave" in name or "/slave" in lowered:
            role = self._tr("从爪", "Slave")
        else:
            role = self._tr("固件", "Firmware")
        variant = "Release" if "release" in lowered else "Debug" if "debug" in lowered else ""
        return f"{role} {variant} | {path.name} | {path.parent}".replace("  |", " |")

    def refresh_firmware(self) -> None:
        self.status_label.setText(self._tr("正在扫描本地固件…", "Scanning local firmware…"))
        self._set_status_state("busy")
        candidates = discover_firmware(self._candidate_roots())
        self.firmware_by_label = {self._firmware_label(candidate.path): candidate.path for candidate in candidates}
        labels = list(self.firmware_by_label)
        self.firmware_combo.clear()
        self.firmware_combo.addItems(labels)

        saved = str(self.settings.get("firmware", ""))
        current = self._selected_firmware_text()
        if current and Path(current).is_file():
            selected = current
        elif saved and Path(saved).is_file():
            selected = saved
        else:
            selected = labels[0] if labels else ""
        self.firmware_combo.setCurrentText(selected)
        if candidates:
            self.status_label.setText(self._tr(f"已找到 {len(candidates)} 个固件", f"Found {len(candidates)} firmware files"))
            self._set_status_state("success")
            self._append_log(self._tr(f"已扫描固件目录，默认选择：{candidates[0].path}\n", f"Firmware scan complete. Default: {candidates[0].path}\n"))
        else:
            self.status_label.setText(self._tr("未找到固件", "No firmware found"))
            self._set_status_state("warning")
            self._set_operation_message(
                self._tr("需要选择固件", "Firmware Required"),
                self._tr("未自动找到固件，请点击“浏览”选择 ELF、HEX 或 BIN 文件。", "No firmware was found automatically. Click Browse and select an ELF, HEX, or BIN file."),
                "warning",
                "!",
            )

    def _selected_firmware_text(self) -> str:
        value = self.firmware_combo.currentText().strip()
        return str(self.firmware_by_label.get(value, Path(value))) if value else ""

    def browse_firmware(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("选择固件", "Select Firmware"),
            "",
            self._tr(
                "支持的固件 (*.elf *.axf *.hex *.bin);;ELF 固件 (*.elf *.axf);;HEX 固件 (*.hex);;BIN 固件 (*.bin);;所有文件 (*.*)",
                "Supported Firmware (*.elf *.axf *.hex *.bin);;ELF Firmware (*.elf *.axf);;HEX Firmware (*.hex);;BIN Firmware (*.bin);;All Files (*.*)",
            ),
        )
        if filename:
            self.firmware_combo.setCurrentText(filename)

    def browse_pack(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("选择 CMSIS-Pack", "Select CMSIS-Pack"),
            "",
            self._tr("CMSIS-Pack (*.pack);;所有文件 (*.*)", "CMSIS-Pack (*.pack);;All Files (*.*)"),
        )
        if filename:
            self.pack_edit.setText(filename)
            self._update_pack_status()

    def refresh_probes(self) -> None:
        if self.flash_process is not None:
            return
        self.probe_combo.clear()
        self.status_label.setText(self._tr("正在检测 DAP 探针…", "Detecting DAP probes…"))
        self._set_status_state("busy")
        threading.Thread(target=self._probe_worker, daemon=True).start()

    def _probe_worker(self) -> None:
        try:
            from pyocd.core.helpers import ConnectHelper

            probes = ConnectHelper.get_all_connected_probes(blocking=False)
            result = [(probe.description or "CMSIS-DAP", probe.unique_id) for probe in probes]
            self.events.put(("probes", result))
        except Exception as exc:
            self.events.put(("error", self._tr(f"探针检测失败：{exc}", f"Probe detection failed: {exc}")))

    def _update_pack_status(self) -> None:
        pack = Path(self.pack_edit.text().strip())
        if pack.is_file():
            size_mb = pack.stat().st_size / (1024 * 1024)
            self.pack_status_label.setText(self._tr(f"已就绪 · {size_mb:.1f} MB", f"Ready · {size_mb:.1f} MB"))
            state = "success"
        else:
            self.pack_status_label.setText(self._tr("未找到 Pack · 点击“准备 Pack”下载官方组件", "Pack not found · Click Prepare Pack to download it"))
            state = "warning"
        self.pack_status_label.setProperty("state", state)
        self.pack_status_label.style().unpolish(self.pack_status_label)
        self.pack_status_label.style().polish(self.pack_status_label)

    def prepare_pack(self) -> None:
        pack = Path(self.pack_edit.text().strip() or self.default_pack)
        self.pack_edit.setText(str(pack))
        if pack.is_file():
            self._update_pack_status()
            self._show_message(
                self._tr("CMSIS-Pack 已就绪", "CMSIS-Pack Ready"),
                self._tr("CMSIS-Pack 已经准备完成，可以开始下载固件。", "CMSIS-Pack is ready. You can start the firmware download."),
                "success",
            )
            return
        self._set_busy(True, self._tr("正在下载 CMSIS-Pack，请保持网络连接…", "Downloading CMSIS-Pack. Keep the network connected…"), "pack")
        threading.Thread(target=self._download_pack_worker, args=(pack, False), daemon=True).start()

    def _download_pack_worker(self, destination: Path, continue_flash: bool) -> None:
        partial = destination.with_suffix(destination.suffix + ".part")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)

            def report(block_count: int, block_size: int, total_size: int) -> None:
                downloaded = block_count * block_size
                if total_size > 0:
                    percent = min(100, int(downloaded * 100 / total_size))
                    self.events.put(("pack_progress", percent))

            urllib.request.urlretrieve(PACK_URL, partial, reporthook=report)
            if partial.stat().st_size == 0:
                raise OSError(self._tr("下载文件为空", "Downloaded file is empty"))
            partial.replace(destination)
            self.events.put(("pack_ready", (destination, continue_flash)))
        except Exception as exc:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            self.events.put(("error", self._tr(f"CMSIS-Pack 下载失败：{exc}", f"CMSIS-Pack download failed: {exc}")))

    def start_flash(self) -> None:
        if self.flash_process is not None:
            return
        firmware = Path(self._selected_firmware_text())
        pack = Path(self.pack_edit.text().strip() or self.default_pack)
        self.pack_edit.setText(str(pack))
        probe_uid = self.probe_by_label.get(self.probe_combo.currentText(), "")
        try:
            validate_flash_settings(
                firmware,
                pack,
                self.target_combo.currentText(),
                probe_uid,
                self._combo_value(self.frequency_combo),
                self._combo_value(self.connect_combo),
                self._combo_value(self.erase_combo),
                self.bin_address_edit.text(),
                require_pack=False,
            )
        except ValueError as exc:
            self._show_message(self._tr("配置无法使用", "Invalid Configuration"), self._localized_error(str(exc)), "error")
            return

        if self.confirm_checkbox.isChecked():
            if not self._confirm_flash(firmware, probe_uid):
                return

        self._save_settings()
        if not pack.is_file():
            if pack.name != PACK_FILENAME:
                self._show_message(
                    self._tr("找不到 CMSIS-Pack", "CMSIS-Pack Not Found"),
                    self._tr(f"指定的 Pack 文件不存在：\n{pack}", f"The selected Pack file does not exist:\n{pack}"),
                    "error",
                )
                return
            self._set_busy(True, self._tr("首次使用，正在下载 CMSIS-Pack…", "First use: downloading CMSIS-Pack…"), "pack")
            self._append_log(
                self._tr(
                    f"正在从官方地址下载 {PACK_FILENAME}…\n",
                    f"Downloading {PACK_FILENAME} from the official source…\n",
                ),
                "command",
            )
            threading.Thread(target=self._download_pack_worker, args=(pack, True), daemon=True).start()
            return
        self._launch_flash(firmware, pack, probe_uid)

    def _pyocd_command(self, args: list[str]) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--pyocd-cli", *args]
        return [sys.executable, str(Path(__file__).resolve()), "--pyocd-cli", *args]

    def _launch_flash(self, firmware: Path, pack: Path, probe_uid: str) -> None:
        try:
            args = build_pyocd_load_args(
                firmware,
                pack,
                self.target_combo.currentText(),
                probe_uid,
                self._combo_value(self.frequency_combo),
                self._combo_value(self.connect_combo),
                self._combo_value(self.erase_combo),
                self.bin_address_edit.text(),
            )
        except ValueError as exc:
            self._set_busy(False, self._tr("配置错误", "Configuration error"), "error")
            self._show_message(self._tr("配置无法使用", "Invalid Configuration"), self._localized_error(str(exc)), "error")
            return

        command = self._pyocd_command(args)
        self.log.clear()
        self._append_log(self._tr("执行命令：\n", "Command:\n") + format_windows_command(command) + "\n\n", "command")
        self._set_busy(True, self._tr("正在连接目标板，请勿断开 USB 或目标板电源…", "Connecting to target. Do not disconnect USB or target power…"), "flash")
        threading.Thread(target=self._flash_worker, args=(command,), daemon=True).start()

    def _flash_worker(self, command: list[str]) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYOCD_COLOR"] = "never"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self.flash_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
            self.events.put(("flash_started", None))
            assert self.flash_process.stdout is not None
            for line in self.flash_process.stdout:
                self.events.put(("log", line))
            return_code = self.flash_process.wait()
            self.events.put(("flash_done", return_code))
        except Exception as exc:
            self.events.put(("error", self._tr(f"无法启动 pyOCD：{exc}", f"Unable to start pyOCD: {exc}")))
        finally:
            self.flash_process = None

    def stop_flash(self) -> None:
        process = self.flash_process
        if process is not None and process.poll() is None:
            process.terminate()
            self._append_log(self._tr("\n用户已请求停止。\n", "\nStop requested by user.\n"), "error")

    def _set_busy(self, busy: bool, status: str, state_hint: str = "") -> None:
        self._busy = busy
        self.status_label.setText(status)
        self.flash_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy and self.flash_process is not None)
        self.language_button.setEnabled(not busy)
        if busy:
            self._flashing = state_hint == "flash"
            self.progress.setVisible(self._flashing)
            if self._flashing:
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
            if state_hint == "pack":
                title = self._tr("正在准备下载组件", "Preparing Download Components")
                detail = status
            else:
                title = self._tr("正在下载固件", "Downloading Firmware")
                detail = self._tr(f"{status} 下载期间请勿断开连接。", f"{status} Do not disconnect during download.")
            self._set_operation_message(title, detail, "busy", "●")
            self._set_status_state("busy")
            self.setWindowTitle(self._tr(f"{APP_NAME} · 下载进行中", f"{APP_NAME} · Downloading"))
        else:
            if state_hint == "success":
                self.progress.setValue(100)
                QTimer.singleShot(1000, self._hide_flash_progress)
            elif self._flashing:
                self._hide_flash_progress()
            self._flashing = False
            if state_hint in {"success", "pack_ready"}:
                state, icon = "success", "✓"
                if state_hint == "pack_ready":
                    title = self._tr("下载组件已就绪", "Download Components Ready")
                    detail = self._tr("CMSIS-Pack 已准备完成，可以继续下载固件。", "CMSIS-Pack is ready. Firmware download can continue.")
                else:
                    title = self._tr("固件下载成功", "Firmware Download Successful")
                    detail = self._tr("固件已写入并完成校验，MCU 已复位。", "Firmware was programmed and verified. The MCU has been reset.")
            elif state_hint == "error":
                state, title, icon = "error", self._tr("下载未完成", "Download Incomplete"), "!"
                detail = self._tr(
                    f"{status}。请查看运行日志，并检查供电、接线和 SWD 频率。",
                    f"{status}. Check the operation log, target power, wiring, and SWD frequency.",
                )
            else:
                state, title, icon = "idle", self._tr("等待操作", "Ready"), "●"
                detail = status
            self._set_operation_message(title, detail, state, icon)
            self._set_status_state(state)
            self.setWindowTitle(APP_NAME)

    def _hide_flash_progress(self) -> None:
        self.progress.setVisible(False)
        self.progress.setValue(0)

    def _set_operation_message(self, title: str, detail: str, state: str, icon: str) -> None:
        self.operation_icon.setText(icon)
        self.operation_label.setText(title)
        self.operation_detail.setText(detail)
        self._set_operation_state(state)

    def _set_operation_state(self, state: str) -> None:
        for widget in (self.operation_card, self.operation_icon, self.operation_label, self.operation_detail):
            widget.setProperty("state", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _set_status_state(self, state: str) -> None:
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _update_flash_stage(self, line: str) -> None:
        if not self._busy:
            return
        lowered = line.lower()
        if "error" in lowered or "critical" in lowered or "failure" in lowered:
            stage = self._tr("检测到通信异常，正在结束当前操作…", "Communication error detected. Ending the operation…")
            progress = max(self.progress.value(), 10)
        elif "programmed" in lowered and "bytes" in lowered:
            stage = self._tr("固件写入完成，正在完成最后处理…", "Firmware programmed. Finishing the operation…")
            progress = 95
        elif "programming" in lowered or "writing" in lowered:
            stage = self._tr("正在写入固件，请勿断开连接…", "Programming firmware. Do not disconnect…")
            progress = 65
        elif "erasing" in lowered or "erase" in lowered:
            stage = self._tr("正在擦除目标 Flash，请勿断开连接…", "Erasing target Flash. Do not disconnect…")
            progress = 30
        elif "verifying" in lowered or "verify" in lowered:
            stage = self._tr("正在校验已写入的固件…", "Verifying programmed firmware…")
            progress = 90
        elif "reset" in lowered:
            stage = self._tr("写入完成，正在复位 MCU…", "Programming complete. Resetting MCU…")
            progress = 97
        elif "loading" in lowered:
            stage = self._tr("已连接目标板，正在准备固件数据…", "Target connected. Preparing firmware data…")
            progress = 15
        else:
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(max(self.progress.value(), progress))
        self.operation_detail.setText(stage)
        self.status_label.setText(stage)

    def _append_log(self, text: str, tag: str | None = None) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        colors = {
            "error": "#ff9e98",
            "success": "#70e3b2",
            "warning": "#ffd27a",
            "command": "#8fc9ff",
        }
        if tag in colors:
            fmt.setForeground(QColor(colors[tag]))
        cursor.insertText(text, fmt)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "probes":
                    probes = payload
                    assert isinstance(probes, list)
                    self.probe_by_label = {f"{description} | {uid}": uid for description, uid in probes}
                    labels = list(self.probe_by_label)
                    self.probe_combo.clear()
                    self.probe_combo.addItems(labels)
                    if labels:
                        self.probe_combo.setCurrentIndex(0)
                        self.status_label.setText(self._tr(f"已连接 {len(labels)} 个 DAP 探针", f"{len(labels)} DAP probe(s) connected"))
                        self._set_status_state("success")
                        self._set_operation_message(
                            self._tr("可以开始下载", "Ready to Download"),
                            self._tr(
                                "已检测到 DAP 探针。请确认固件、目标芯片和擦除方式后开始下载。",
                                "A DAP probe was detected. Confirm the firmware, target MCU, and erase mode before downloading.",
                            ),
                            "success",
                            "✓",
                        )
                        self._append_log(self._tr(f"检测到探针：{labels[0]}\n", f"Probe detected: {labels[0]}\n"))
                    else:
                        self.status_label.setText(self._tr("未检测到 DAP 探针", "No DAP probe detected"))
                        self._set_status_state("warning")
                        self._set_operation_message(
                            self._tr("等待连接 DAP 探针", "Waiting for DAP Probe"),
                            self._tr(
                                "请连接 CMSIS-DAP 调试器，并确认 USB 驱动和 SWD 接线正常。",
                                "Connect a CMSIS-DAP probe and check the USB driver and SWD wiring.",
                            ),
                            "warning",
                            "!",
                        )
                elif event == "log":
                    line = str(payload)
                    lowered = line.lower()
                    if "error" in lowered or "critical" in lowered:
                        tag = "error"
                    elif "warning" in lowered or "warn" in lowered:
                        tag = "warning"
                    else:
                        tag = None
                    self._append_log(line, tag)
                    self._update_flash_stage(line)
                elif event == "flash_started":
                    self.stop_button.setEnabled(True)
                elif event == "pack_progress":
                    percent = int(payload)
                    self.status_label.setText(self._tr(f"正在下载 CMSIS-Pack：{percent}%", f"Downloading CMSIS-Pack: {percent}%"))
                    self._set_status_state("busy")
                    self._set_operation_message(
                        self._tr("正在准备下载组件", "Preparing Download Components"),
                        self._tr(
                            f"正在下载 CMSIS-Pack，已完成 {percent}%。请保持网络连接。",
                            f"Downloading CMSIS-Pack: {percent}% complete. Keep the network connected.",
                        ),
                        "busy",
                        "●",
                    )
                elif event == "pack_ready":
                    destination, continue_flash = payload
                    self.pack_edit.setText(str(destination))
                    self._update_pack_status()
                    self._append_log(self._tr(f"CMSIS-Pack 已准备完成：{destination}\n", f"CMSIS-Pack ready: {destination}\n"), "success")
                    self._set_busy(False, self._tr("CMSIS-Pack 已就绪", "CMSIS-Pack ready"), "pack_ready")
                    if continue_flash:
                        firmware = Path(self._selected_firmware_text())
                        probe_uid = self.probe_by_label.get(self.probe_combo.currentText(), "")
                        try:
                            validate_flash_settings(
                                firmware,
                                Path(destination),
                                self.target_combo.currentText(),
                                probe_uid,
                                self._combo_value(self.frequency_combo),
                                self._combo_value(self.connect_combo),
                                self._combo_value(self.erase_combo),
                                self.bin_address_edit.text(),
                            )
                        except ValueError as exc:
                            self._append_log(self._tr(f"准备 Pack 期间配置发生变化：{exc}\n", f"Settings changed while preparing the Pack: {exc}\n"), "error")
                            self._show_message(self._tr("配置已发生变化", "Settings Changed"), self._localized_error(str(exc)), "error")
                        else:
                            self._launch_flash(firmware, Path(destination), probe_uid)
                elif event == "flash_done":
                    return_code = int(payload)
                    if return_code == 0:
                        self._append_log(self._tr("\n下载成功，MCU 已复位。\n", "\nDownload successful. MCU reset complete.\n"), "success")
                        self._set_busy(False, self._tr("下载成功", "Download successful"), "success")
                        self._show_message(
                            self._tr("固件下载成功", "Firmware Download Successful"),
                            self._tr("已完成固件写入和校验，目标 MCU 已复位。", "Firmware programming and verification completed. The target MCU was reset."),
                            "success",
                        )
                    else:
                        self._append_log(self._tr(f"\n下载失败，pyOCD 返回码：{return_code}\n", f"\nDownload failed. pyOCD exit code: {return_code}\n"), "error")
                        self._set_busy(False, self._tr("下载失败", "Download failed"), "error")
                        self._show_message(
                            self._tr("固件下载失败", "Firmware Download Failed"),
                            self._tr(
                                "请查看运行日志，并检查：\n"
                                "1. 目标板是否供电；\n"
                                "2. SWDIO、SWCLK、NRST、GND 是否接好；\n"
                                "3. 必要时将 SWD 频率降至 500k 或 100k。",
                                "Check the operation log and verify:\n"
                                "1. The target board is powered;\n"
                                "2. SWDIO, SWCLK, NRST, and GND are connected;\n"
                                "3. Reduce SWD frequency to 500 kHz or 100 kHz if needed.",
                            ),
                            "error",
                        )
                elif event == "error":
                    message = str(payload)
                    self._append_log(message + "\n", "error")
                    self._set_busy(False, self._tr("发生错误", "An error occurred"), "error")
                    self._show_message(self._tr("操作发生错误", "Operation Error"), message, "error")
        except queue.Empty:
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        if hasattr(self, "content"):
            self._update_responsive_layout()

    def _update_responsive_layout(self, force: bool = False) -> None:
        # The normal layout needs substantially more vertical room once Windows
        # font scaling is applied. Use the dense layout based on both dimensions
        # so Qt never resolves the shortage by flattening text-bearing widgets.
        compact = self.width() < 1080 or self.height() < 800
        stacked = self.width() < 860 and self.height() >= 850
        short_header = self.width() < 980 or self.height() < 680
        layout_mode = (compact, stacked, short_header)
        previous_mode = getattr(self, "_layout_mode", None)
        if not force and layout_mode == previous_mode:
            return
        self._layout_mode = layout_mode
        self._compact_mode = compact
        if stacked:
            self.root_widget.setProperty("compact", True)
            self.root_widget.style().unpolish(self.root_widget)
            self.root_widget.style().polish(self.root_widget)
            self.content.setDirection(QBoxLayout.Direction.TopToBottom)
            self.content.setSpacing(8)
            self.content.setStretch(0, 0)
            self.content.setStretch(1, 1)
            self.form_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.log_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.log.setMinimumHeight(130)
            self.log_frame.setMaximumHeight(190)
            self.outer.setContentsMargins(10, 8, 10, 8)
            self.outer.setSpacing(8)
            self.form_layout.setContentsMargins(8, 5, 8, 5)
            self.form_layout.setSpacing(5)
            for grid in (self.firmware_grid, self.pack_grid, self.options_grid):
                grid.setContentsMargins(6, 4, 6, 4)
                grid.setVerticalSpacing(4)
        else:
            self.root_widget.setProperty("compact", compact)
            self.root_widget.style().unpolish(self.root_widget)
            self.root_widget.style().polish(self.root_widget)
            self.content.setDirection(QBoxLayout.Direction.LeftToRight)
            self.content.setSpacing(10 if compact else 16)
            self.content.setStretch(0, 5)
            self.content.setStretch(1, 6)
            self.form_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            self.log_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.log.setMinimumHeight(0)
            self.log_frame.setMaximumHeight(16777215)
            self.outer.setContentsMargins(*((12, 12, 12, 12) if compact else (24, 22, 24, 18)))
            self.outer.setSpacing(10 if compact else 16)
            self.form_layout.setContentsMargins(*((8, 5, 8, 5) if compact else (16, 14, 16, 14)))
            self.form_layout.setSpacing(5 if compact else 12)
            for grid in (self.firmware_grid, self.pack_grid, self.options_grid):
                grid.setContentsMargins(*((6, 4, 6, 4) if compact else (12, 10, 12, 10)))
                grid.setVerticalSpacing(4 if compact else 8)

        self.form_card.setMinimumWidth(690)
        self.log_frame.setMinimumWidth(160 if compact else 240)

        self.subtitle_label.setVisible(not short_header)
        self.badge.setVisible(not short_header)
        self.target_hint.setVisible(self.height() >= 700)
        self.header_layout.setSpacing(10 if compact else 16)
        self.operation_layout.setContentsMargins(*(8, 5, 8, 5) if compact else (12, 9, 12, 9))

        narrow_header = self.width() < 700
        self.header_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow_header else QBoxLayout.Direction.LeftToRight
        )
        self.title_label.setProperty("compact", narrow_header)
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)
        self.header_layout.setAlignment(
            self.badge,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if narrow_header
            else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self.header_layout.setContentsMargins(*(14, 8, 14, 8) if compact else (24, 18, 24, 18))
        self._refresh_text_minimum_heights()

    def _refresh_text_minimum_heights(self) -> None:
        """Keep every text control tall enough for its resolved screen font."""
        if not hasattr(self, "root_widget"):
            return

        controls = [
            *self.root_widget.findChildren(QLineEdit),
            *self.root_widget.findChildren(QComboBox),
            *self.root_widget.findChildren(QPushButton),
            *self.root_widget.findChildren(QCheckBox),
        ]
        labels = self.root_widget.findChildren(QLabel)

        # Clear previous programmatic values first because compact-mode style
        # changes can legitimately reduce padding while keeping the same font.
        for widget in (*controls, *labels):
            widget.setMinimumHeight(0)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        for widget in controls:
            font_height = QFontMetrics(widget.font()).lineSpacing()
            widget.setMinimumHeight(max(widget.sizeHint().height(), font_height + 4))

        for label in labels:
            font_height = QFontMetrics(label.font()).lineSpacing()
            if label.wordWrap():
                required_height = max(label.sizeHint().height(), font_height)
            else:
                required_height = max(label.sizeHint().height(), font_height)
            label.setMinimumHeight(required_height)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self.flash_process is not None and self.flash_process.poll() is None:
            if not self._confirm_simple(
                self._tr("确认退出", "Confirm Exit"),
                self._tr("固件仍在下载，确定要停止并退出吗？", "Firmware download is still running. Stop it and exit?"),
                self._tr("停止并退出", "Stop and Exit"),
            ):
                event.ignore()
                return
            self.flash_process.terminate()
        self._save_settings()
        event.accept()


def _configure_application_font(app: QApplication) -> None:
    """Select a readable UI font and explicitly load Windows fallbacks if needed."""
    preferred_families = (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Segoe UI",
        "Arial",
    )
    available = set(QFontDatabase.families())

    # Some restricted or off-screen Qt environments do not enumerate Windows
    # fonts even though the files exist. Register the common UI fonts directly
    # so the application still has real Latin and CJK glyphs.
    if os.name == "nt" and not available.intersection(preferred_families):
        for font_path in (
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyhbd.ttc",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "consola.ttf",
        ):
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
        available = set(QFontDatabase.families())

    ui_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    for family in preferred_families:
        if family in available:
            ui_font.setFamily(family)
            break
    ui_font.setPointSizeF(10.0)
    app.setFont(ui_font)


def _apply_styles(app: QApplication) -> None:
    app.setStyle("Fusion")
    _configure_application_font(app)
    app.setStyleSheet(
        """
        QWidget { font-size: 10pt; color: #172b3f; }
        QWidget#Root { background: #f1f5f9; }
        QFrame#Header { background: #102a43; border-radius: 12px; }
        QLabel#Title { color: #ffffff; font-size: 20pt; font-weight: 700; }
        QLabel#Subtitle { color: #d5e4f2; font-size: 10pt; }
        QLabel#Badge { background: #285782; color: #f0f7ff; border-radius: 7px; padding: 7px 11px; font-size: 9pt; font-weight: 600; }
        QPushButton#LanguageButton { background: #ffffff; color: #17324d; border: 1px solid #b8cce0; border-radius: 7px; padding: 6px 12px; font-weight: 700; }
        QPushButton#LanguageButton:hover { background: #e8f3ff; border-color: #7eacd3; }
        QGroupBox#Card, QGroupBox#InnerCard { background: #ffffff; border: 1px solid #c5d2df; border-radius: 10px; margin-top: 10px; padding-top: 8px; }
        QGroupBox#Card { font-size: 11pt; font-weight: 700; }
        QGroupBox#InnerCard { border-color: #d2deea; color: #334e68; font-size: 10pt; font-weight: 700; }
        QWidget#Root[compact="true"] QGroupBox#Card, QWidget#Root[compact="true"] QGroupBox#InnerCard { margin-top: 8px; padding-top: 6px; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
        QLabel#FieldLabel { color: #17324d; font-weight: 600; }
        QLabel#Hint { color: #425b70; font-size: 10pt; }
        QLabel#Hint[state="success"] { color: #13704e; font-weight: 700; }
        QLabel#Hint[state="warning"] { color: #985208; font-weight: 700; }
        QLineEdit, QComboBox { background: #ffffff; border: 1px solid #9fb3c6; border-radius: 6px; padding: 7px 8px; color: #172b3f; selection-background-color: #2878d4; selection-color: #ffffff; }
        QLineEdit:focus, QComboBox:focus { border: 2px solid #2878d4; padding: 6px 7px; }
        QLineEdit:disabled, QComboBox:disabled { background: #edf2f7; color: #6b7c8d; }
        QWidget#Root[compact="true"] QLineEdit, QWidget#Root[compact="true"] QComboBox { padding: 4px 6px; min-height: 18px; }
        QWidget#Root[compact="true"] QLineEdit:focus, QWidget#Root[compact="true"] QComboBox:focus { padding: 3px 5px; }
        QComboBox::drop-down { border: 0; width: 24px; }
        QComboBox QAbstractItemView { background: #ffffff; color: #172b3f; border: 1px solid #7f9db8; selection-background-color: #1769c2; selection-color: #ffffff; outline: 0; padding: 4px; }
        QComboBox QAbstractItemView::item { min-height: 34px; padding: 6px 10px; }
        QComboBox QAbstractItemView::item:hover { background: #dceeff; color: #123b60; }
        QWidget#Root[compact="true"] QComboBox QAbstractItemView::item { min-height: 30px; padding: 5px 8px; }
        QPushButton { border: 1px solid transparent; border-radius: 6px; padding: 8px 12px; min-height: 20px; font-weight: 600; }
        QPushButton#SecondaryButton { background: #dceaf7; color: #123b60; border-color: #b4cde4; }
        QPushButton#SecondaryButton:hover { background: #cbe0f2; border-color: #82add3; }
        QPushButton#SecondaryButton:pressed { background: #b9d4ec; }
        QPushButton#PrimaryButton { background: #1769c2; color: #ffffff; font-weight: 700; padding: 10px 18px; }
        QPushButton#PrimaryButton:hover { background: #1e67bd; }
        QPushButton#PrimaryButton:pressed { background: #15579f; }
        QPushButton#PrimaryButton:disabled { background: #94a9bf; color: #edf3f8; }
        QPushButton#DangerButton { background: #fff0ef; color: #a52525; border-color: #e4aaa5; }
        QPushButton#DangerButton:hover { background: #ffe2df; border-color: #d97972; }
        QWidget#Root[compact="true"] QPushButton { padding: 4px 8px; min-height: 18px; }
        QWidget#Root[compact="true"] QPushButton#PrimaryButton { padding: 6px 12px; }
        QCheckBox { spacing: 7px; color: #17324d; font-weight: 600; }
        QFrame#OperationCard { background: #eef4fa; border: 2px solid #9bb9d5; border-radius: 8px; }
        QFrame#OperationCard[state="busy"] { background: #e8f3ff; border-color: #2d7bd2; }
        QFrame#OperationCard[state="success"] { background: #eaf8f1; border-color: #2e9e73; }
        QFrame#OperationCard[state="warning"] { background: #fff7e8; border-color: #d49a37; }
        QFrame#OperationCard[state="error"] { background: #fff0ef; border-color: #d25b55; }
        QLabel#OperationIcon { color: #1769c2; font-size: 16pt; font-weight: 700; min-width: 18px; }
        QLabel#OperationIcon[state="busy"] { color: #1769c2; }
        QLabel#OperationIcon[state="success"] { color: #13704e; }
        QLabel#OperationIcon[state="warning"] { color: #985208; }
        QLabel#OperationIcon[state="error"] { color: #a52525; }
        QLabel#OperationTitle { color: #17324d; font-size: 10.5pt; font-weight: 700; }
        QLabel#OperationTitle[state="busy"] { color: #12549a; }
        QLabel#OperationTitle[state="success"] { color: #126243; }
        QLabel#OperationTitle[state="warning"] { color: #7a4205; }
        QLabel#OperationTitle[state="error"] { color: #8f2020; }
        QLabel#OperationDetail { color: #38536b; font-size: 10pt; }
        QLabel#OperationDetail[state="busy"] { color: #174f83; }
        QLabel#OperationDetail[state="success"] { color: #24674d; }
        QLabel#OperationDetail[state="warning"] { color: #7a4b12; }
        QLabel#OperationDetail[state="error"] { color: #8f302c; }
        QPlainTextEdit#Log { background: #101c2b; color: #f4f8fc; border: 1px solid #233b54; border-radius: 8px; padding: 10px; selection-background-color: #2878d4; selection-color: #ffffff; }
        QPlainTextEdit#Log QScrollBar:vertical { background: #172b3e; width: 12px; margin: 2px; }
        QPlainTextEdit#Log QScrollBar::handle:vertical { background: #5e7d9d; border-radius: 5px; min-height: 28px; }
        QProgressBar { background: #d6e1ec; border: 0; border-radius: 5px; height: 18px; color: #17324d; font-size: 9pt; font-weight: 700; text-align: center; }
        QProgressBar::chunk { background: #1769c2; border-radius: 5px; }
        QLabel#Status { background: #e8eef5; color: #24445f; border-radius: 6px; padding: 5px 10px; font-size: 10pt; font-weight: 700; }
        QLabel#Status[state="busy"] { background: #dceeff; color: #12549a; }
        QLabel#Status[state="success"] { background: #dff3e9; color: #126243; }
        QLabel#Status[state="warning"] { background: #fff0cf; color: #7a4205; }
        QLabel#Status[state="error"] { background: #ffe0de; color: #8f2020; }
        QDialog#AppDialog { background: #f8fbfe; }
        QDialog#AppDialog QLabel#DialogTitle { color: #17324d; font-size: 14pt; font-weight: 700; }
        QDialog#AppDialog QLabel#DialogMessage { color: #29465f; font-size: 11pt; line-height: 1.4; }
        QDialog#AppDialog QLabel#DialogIcon { background: #fff0cf; color: #7a4205; border-radius: 16px; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; font-size: 17pt; font-weight: 700; qproperty-alignment: AlignCenter; }
        QDialog#AppDialog QLabel#DialogIcon[level="success"] { background: #dff3e9; color: #126243; }
        QDialog#AppDialog QLabel#DialogIcon[level="error"] { background: #ffe0de; color: #8f2020; }
        QDialog#AppDialog QFrame#DialogDetails { background: #ffffff; border: 1px solid #b9ccde; border-radius: 8px; }
        QDialog#AppDialog QLabel#DialogKey { color: #486278; font-size: 10pt; font-weight: 700; }
        QDialog#AppDialog QLabel#DialogValue { color: #142f48; font-size: 11pt; font-weight: 600; }
        QDialog#AppDialog QLabel#DialogWarning { background: #fff5dc; border: 1px solid #e0b45a; border-radius: 7px; color: #70430c; padding: 10px; font-size: 10pt; }
        QDialog#AppDialog QPushButton { min-width: 100px; min-height: 30px; font-size: 10pt; }
        QDialog#AppDialog QPushButton#DialogPrimaryButton { background: #1769c2; color: #ffffff; border: 1px solid #12549a; }
        QDialog#AppDialog QPushButton#DialogPrimaryButton:hover { background: #12549a; }
        QDialog#AppDialog QPushButton#DialogCancelButton { background: #e6eef5; color: #23445f; border: 1px solid #aabfd1; }
        QDialog#AppDialog QPushButton#DialogCancelButton:hover { background: #d5e5f1; }
        """
    )


def main() -> int:
    cli_result = _run_embedded_pyocd()
    if cli_result is not None:
        return cli_result

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    _apply_styles(app)
    try:
        import pyocd  # noqa: F401
    except ImportError:
        QMessageBox.critical(app.activeWindow(), APP_NAME, "未安装 pyOCD。请先运行 run_tool.bat 安装依赖。")
        return 1

    window = DAPDownloaderApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
