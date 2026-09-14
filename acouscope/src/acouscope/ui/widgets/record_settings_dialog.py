# SPDX-License-Identifier: GPL-3.0-only
"""录音设置面板（点击录音时打开，参考 Audacity；T-504c 起为可嵌入抽屉的非模态面板）。

选择输出文件路径、格式（WAV 默认，支持 MP3/OGG/FLAC/AIFF）、
采样率（默认 44.1kHz）、采样深度（默认 16-bit）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# 格式 → (扩展名, 支持的深度列表, 默认深度)
# MP3/OGG 为有损压缩，无位深概念（深度列表为空 → 控件禁用）
RECORD_FORMATS = {
    "WAV":  (".wav",  ["PCM_16", "PCM_24", "FLOAT"], "PCM_16"),
    "FLAC": (".flac", ["PCM_16", "PCM_24"],           "PCM_16"),
    "AIFF": (".aiff", ["PCM_16", "PCM_24", "FLOAT"],  "PCM_16"),
    "MP3":  (".mp3",  [],                             None),
    "OGG":  (".ogg",  [],                             None),
}

DEPTH_LABELS = {
    "PCM_16": "16-bit PCM",
    "PCM_24": "24-bit PCM",
    "FLOAT": "32-bit 浮点",
}

RATE_OPTIONS = [44100, 48000, 96000, 32000, 22050, 16000, 8000]

# 会话内记忆上次选择（None = 尚无记忆，首次用调用方当前值）
_last_dir: str | None = None
_last_fmt = "WAV"
_last_depth = "PCM_16"
_last_rate: int | None = None


class RecordSettingsDialog(QWidget):
    """录音输出设置面板（非模态，T-504c：可嵌入抽屉）。

    由 accepted/cancelled 信号驱动宿主（main_window 抽屉）；面板自身不
    自关、不模态。覆盖文件存在的确认（破坏性操作）保留模态 question。
    """

    accepted = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent=None, current_rate: int = 44100):
        super().__init__(parent)
        self.setWindowTitle("录音设置")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ----- 输出位置 -----
        loc_label = QLabel("输出位置")
        loc_label.setStyleSheet("font-weight: bold; color: #111827;")
        layout.addWidget(loc_label)

        row_path = QHBoxLayout()
        self.edit_dir = QLineEdit()
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.clicked.connect(self._on_browse)
        row_path.addWidget(self.edit_dir, stretch=1)
        row_path.addWidget(self.btn_browse)
        layout.addLayout(row_path)

        self.edit_filename = QLineEdit()
        self.edit_filename.setPlaceholderText("文件名（不含扩展名）")
        layout.addWidget(self.edit_filename)

        # ----- 参数 -----
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cmb_format = QComboBox()
        for name, (_, _, _) in RECORD_FORMATS.items():
            self.cmb_format.addItem(name, name)
        self.cmb_format.currentIndexChanged.connect(self._on_format_changed)
        form.addRow("格式", self.cmb_format)

        self.cmb_depth = QComboBox()
        form.addRow("采样深度", self.cmb_depth)

        self.cmb_rate = QComboBox()
        for r in RATE_OPTIONS:
            self.cmb_rate.addItem(f"{r/1000:g} kHz", r)
        form.addRow("采样率", self.cmb_rate)

        layout.addLayout(form)

        # ----- 结果预览 -----
        self.lbl_preview = QLabel("")
        self.lbl_preview.setStyleSheet(
            "color: #6b7280; font-size: 11px; background: #f3f4f6;"
            " padding: 4px 8px; border-radius: 3px;"
        )
        self.lbl_preview.setWordWrap(True)
        layout.addWidget(self.lbl_preview)

        # 说明：MP3/OGG 压缩格式
        self.lbl_note = QLabel("")
        self.lbl_note.setStyleSheet("color: #b45309; font-size: 11px;")
        self.lbl_note.setWordWrap(True)
        layout.addWidget(self.lbl_note)

        layout.addStretch()

        # 自定义按钮行（非模态面板：宿主决定开合，面板不自关）
        row_buttons = QHBoxLayout()
        self.btn_start = QPushButton("开始录音")
        self.btn_cancel = QPushButton("取消")
        self.btn_start.clicked.connect(self._on_accept)
        self.btn_cancel.clicked.connect(self._on_cancel)
        row_buttons.addWidget(self.btn_start)
        row_buttons.addWidget(self.btn_cancel)
        layout.addLayout(row_buttons)

        self._accepted = False
        self._init_defaults(current_rate)

    # ------------------------------------------------------------------
    # 初始化与联动
    # ------------------------------------------------------------------

    def _init_defaults(self, current_rate: int) -> None:
        global _last_dir, _last_fmt, _last_depth, _last_rate

        # 目录：上次选择 → 音乐目录 → 主目录
        if _last_dir is None:
            from PyQt6.QtCore import QStandardPaths
            music = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.MusicLocation
            )
            _last_dir = music if music else str(Path.home())
        self.edit_dir.setText(_last_dir)

        # 文件名：时刻戳
        self.edit_filename.setText(
            f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        # 格式 / 深度
        self.cmb_format.setCurrentText(_last_fmt)
        self._on_format_changed()

        # 采样率：记忆值 → 工具栏当前值 → 44.1kHz
        rate = _last_rate if _last_rate in RATE_OPTIONS else (
            current_rate if current_rate in RATE_OPTIONS else 44100
        )
        idx = self.cmb_rate.findData(rate)
        self.cmb_rate.setCurrentIndex(max(idx, 0))

        for combo, slot in ((self.cmb_format, self._on_format_changed),):
            combo.currentIndexChanged.connect(self._update_preview)
        self.cmb_rate.currentIndexChanged.connect(self._update_preview)
        self.edit_dir.textChanged.connect(self._update_preview)
        self.edit_filename.textChanged.connect(self._update_preview)
        self._update_preview()

    def _on_format_changed(self) -> None:
        fmt = self.cmb_format.currentData()
        _, depths, default = RECORD_FORMATS[fmt]

        self.cmb_depth.blockSignals(True)
        self.cmb_depth.clear()
        if depths:
            for d in depths:
                self.cmb_depth.addItem(DEPTH_LABELS[d], d)
            idx = self.cmb_depth.findData(_last_depth if _last_depth in depths else default)
            self.cmb_depth.setCurrentIndex(max(idx, 0))
            self.cmb_depth.setEnabled(True)
            self.lbl_note.setText("")
        else:
            self.cmb_depth.addItem("压缩格式（自动质量）", None)
            self.cmb_depth.setEnabled(False)
            self.lbl_note.setText(
                f"{fmt} 为有损压缩格式，不设采样深度；以默认质量编码。"
            )
        self.cmb_depth.blockSignals(False)
        self._update_preview()

    def _update_preview(self) -> None:
        path = self.file_path()
        if path:
            self.lbl_preview.setText(f"停止录音后将自动保存到：\n{path}")
        else:
            self.lbl_preview.setText("请填写目录与文件名。")

    def _on_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self.edit_dir.text())
        if d:
            self.edit_dir.setText(d)

    def _on_cancel(self) -> None:
        """取消：仅发信号，面板保持打开，由宿主决定关闭/复位。"""
        self.cancelled.emit()

    # ------------------------------------------------------------------
    # 结果
    # ------------------------------------------------------------------

    def file_path(self) -> str:
        name = self.edit_filename.text().strip()
        if not name:
            return ""
        ext = RECORD_FORMATS[self.cmb_format.currentData()][0]
        if not name.lower().endswith(ext):
            name += ext
        return str(Path(self.edit_dir.text().strip()) / name)

    def _on_accept(self) -> None:
        global _last_dir, _last_fmt, _last_depth, _last_rate
        if not self.edit_filename.text().strip():
            self.lbl_note.setText("请填写文件名。")
            return
        if not Path(self.edit_dir.text().strip()).is_dir():
            self.lbl_note.setText("目录不存在，请重新选择。")
            return

        path = self.file_path()
        if Path(path).exists():
            from PyQt6.QtWidgets import QMessageBox
            ret = QMessageBox.question(
                self, "文件已存在",
                f"{path}\n已存在，是否覆盖？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        # 记忆本次选择
        _last_dir = self.edit_dir.text().strip()
        _last_fmt = self.cmb_format.currentData()
        _last_depth = self.cmb_depth.currentData() or "PCM_16"
        _last_rate = self.cmb_rate.currentData()

        # 非模态面板：置位并发信号（校验失败/覆盖拒绝路径只 return，
        # 不发任何信号，面板保持打开）
        self._accepted = True
        self.accepted.emit()

    # ---- 信号与状态 ----

    def was_accepted(self) -> bool:
        """本次面板是否已完成一次合法 accept。"""
        return self._accepted

    def closeEvent(self, event) -> None:  # noqa: N803 (Qt 命名)
        """未 accepted 即关闭 → 发 cancelled（独立使用兜底）。

        抽屉 hide() 不触发 closeEvent，宿主侧不受影响；_accepted=True
        后关闭不得再发 cancelled。
        """
        if not self._accepted:
            self.cancelled.emit()
        super().closeEvent(event)

    # ---- 对外取值 ----

    def format_name(self) -> str:
        return self.cmb_format.currentData()

    def depth(self) -> str | None:
        return self.cmb_depth.currentData()

    def sample_rate(self) -> int:
        return int(self.cmb_rate.currentData())

    def channels(self) -> int:
        return 1  # 采集声道：立体声在 recorder 内混音为单声道存储
