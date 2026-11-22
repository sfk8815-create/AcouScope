# SPDX-License-Identifier: GPL-3.0-only
"""合成音高生成器对话框（工具菜单 ▸ 合成音高生成器，PI-P6-PITCH-01）。

按已落盘的国际/历史/乐团音高标准合成参考音或指定音名，导出 WAV，
并可将合成音频载入主窗口。所有配色 / 间距 / 圆角一律取自 ``theme``，
无硬编码 hex / px；错误写入状态行，不弹模态提示框。
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from acouscope.dsp.pitch_tone import (
    NOTE_NAMES,
    load_standards,
    synthesize_tone,
    tone_frequency,
    write_wave,
)
from acouscope.dsp.units import hz_to_cents
from acouscope.i18n import get_language, tr
from acouscope.ui import theme

_USER = Qt.ItemDataRole.UserRole


class _PreviewWidget(QWidget):
    """波形预览：自绘前 20 ms 波形 + 中线（颜色一律 theme 派生）。"""

    def __init__(self, owner: "PitchGeneratorDialog") -> None:
        super().__init__(owner)
        self._owner = owner
        self.setMinimumHeight(int(theme.TOKENS["spacing"]["xxl"]) * 2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        c = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        rect = QRectF(0.0, 0.0, w, h).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = float(theme.TOKENS["radius"]["md"])
        bg = QPainterPath()
        bg.addRoundedRect(rect, radius, radius)
        p.fillPath(bg, QColor(c["bg2"]))
        edge = float(theme.TOKENS["elevation"]["border"])
        mid = h / 2.0
        p.setPen(QPen(QColor(c["border"]), edge))
        p.drawLine(QPointF(0.0, mid), QPointF(w, mid))
        data = getattr(self._owner, "_preview_data", None)
        if data is not None and len(data) >= 2:
            n = len(data)
            scale = (h / 2.0) * 0.9
            step = max(1, n // max(1, int(w)))
            path = QPainterPath()
            path.moveTo(0.0, mid - float(data[0]) * scale)
            for i in range(step, n, step):
                x = (i / (n - 1)) * w if n > 1 else 0.0
                path.lineTo(x, mid - float(data[i]) * scale)
            p.setPen(QPen(QColor(theme.data_ink("trace")), edge * 2))
            p.drawPath(path)
        p.end()


class PitchGeneratorDialog(QDialog):
    """合成音高生成器：标准 → 音符/参数 → 读数 → 预览 → 导出/载入。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        controller: object | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._standards = load_standards()
        self._preview_data: np.ndarray | None = None
        self.setObjectName("pitch_generator_dialog")
        self.setWindowTitle(tr("pitchgen.title"))

        sp = theme.TOKENS["spacing"]
        root = QVBoxLayout(self)
        root.setContentsMargins(sp["md"], sp["md"], sp["md"], sp["md"])
        root.setSpacing(sp["sm"])

        root.addWidget(self._build_standard_box())
        root.addWidget(self._build_tone_box())
        root.addWidget(self._build_readout_box())

        self.preview_widget = _PreviewWidget(self)
        self.preview_widget.setObjectName("preview_widget")
        root.addWidget(self.preview_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_export = QPushButton(tr("pitchgen.btn.export"))
        self.btn_export.setObjectName("btn_export")
        self.btn_load = QPushButton(tr("pitchgen.btn.load"))
        self.btn_load.setObjectName("btn_load")
        self.btn_close = QPushButton(tr("pitchgen.btn.close"))
        self.btn_close.setObjectName("btn_close")
        for button in (self.btn_export, self.btn_load, self.btn_close):
            btn_row.addWidget(button)
        root.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status_label")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.btn_export.clicked.connect(self._on_export)
        self.btn_load.clicked.connect(self._on_load)
        self.btn_close.clicked.connect(self.reject)
        self.btn_load.setEnabled(controller is not None)

        for combo in (
            self.standards_combo,
            self.note_combo,
            self.sample_rate_combo,
            self.waveform_combo,
            self.depth_combo,
        ):
            combo.currentIndexChanged.connect(self._refresh)
        for spin in (
            self.octave_spin,
            self.duration_spin,
            self.amplitude_spin,
            self.fade_spin,
        ):
            spin.valueChanged.connect(self._refresh)

        self._refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_standard_box(self) -> QGroupBox:
        box = QGroupBox(tr("pitchgen.box.standard"))
        v = QVBoxLayout(box)
        v.setSpacing(theme.TOKENS["spacing"]["xs"])

        # 三组分组标题（可见 + 竖向分隔；historical/orchestral 明确非 ISO）
        legend = QHBoxLayout()
        specs = (
            ("group_label_formal", "pitchgen.group.formal"),
            ("group_label_historical", "pitchgen.group.historical"),
            ("group_label_orchestral", "pitchgen.group.orchestral"),
        )
        for idx, (name, key) in enumerate(specs):
            if idx:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                legend.addWidget(sep)
            label = QLabel(tr(key))
            label.setObjectName(name)
            label.setWordWrap(True)
            legend.addWidget(label, 1)
        v.addLayout(legend)

        self.standards_combo = QComboBox()
        self.standards_combo.setObjectName("standards_combo")
        for standard in self._standards:
            self.standards_combo.addItem(self._std_label(standard), standard["id"])
        v.addWidget(self.standards_combo)

        self.source_browser = QTextBrowser()
        self.source_browser.setObjectName("source_browser")
        self.source_browser.setReadOnly(True)
        self.source_browser.setMaximumHeight(int(theme.TOKENS["spacing"]["xxl"]) * 2)
        v.addWidget(self.source_browser)

        self.caveat_label = QLabel()
        self.caveat_label.setObjectName("caveat_label")
        self.caveat_label.setWordWrap(True)
        palette = self.caveat_label.palette()
        palette.setColor(
            QPalette.ColorRole.WindowText,
            QColor(theme.TOKENS["semantic"]["warning"]),
        )
        self.caveat_label.setPalette(palette)
        caveat_font = self.caveat_label.font()
        caveat_font.setBold(True)
        self.caveat_label.setFont(caveat_font)
        v.addWidget(self.caveat_label)
        return box

    def _build_tone_box(self) -> QGroupBox:
        box = QGroupBox(tr("pitchgen.box.tone"))
        form = QFormLayout(box)
        form.setSpacing(theme.TOKENS["spacing"]["xs"])

        self.note_combo = QComboBox()
        self.note_combo.setObjectName("note_combo")
        for note in NOTE_NAMES:
            self.note_combo.addItem(note, note)
        self.note_combo.setCurrentIndex(NOTE_NAMES.index("A"))  # 默认 A4
        form.addRow(tr("pitchgen.note"), self.note_combo)

        self.octave_spin = QSpinBox()
        self.octave_spin.setObjectName("octave_spin")
        self.octave_spin.setRange(0, 9)
        self.octave_spin.setValue(4)
        form.addRow(tr("pitchgen.octave"), self.octave_spin)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setObjectName("duration_spin")
        self.duration_spin.setRange(0.1, 30.0)
        self.duration_spin.setSingleStep(0.1)
        self.duration_spin.setValue(2.0)
        form.addRow(tr("pitchgen.duration"), self.duration_spin)

        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.setObjectName("sample_rate_combo")
        for sr in (22050, 44100, 48000, 96000):
            self.sample_rate_combo.addItem(str(sr), sr)
        self.sample_rate_combo.setCurrentIndex(1)  # 44100
        form.addRow(tr("pitchgen.sample_rate"), self.sample_rate_combo)

        self.amplitude_spin = QDoubleSpinBox()
        self.amplitude_spin.setObjectName("amplitude_spin")
        self.amplitude_spin.setRange(0.05, 1.0)
        self.amplitude_spin.setSingleStep(0.05)
        self.amplitude_spin.setValue(0.8)
        form.addRow(tr("pitchgen.amplitude"), self.amplitude_spin)

        self.waveform_combo = QComboBox()
        self.waveform_combo.setObjectName("waveform_combo")
        self.waveform_combo.addItem(tr("pitchgen.waveform.sine"), "sine")
        self.waveform_combo.addItem(tr("pitchgen.waveform.harmonic"), "harmonic")
        form.addRow(tr("pitchgen.waveform"), self.waveform_combo)

        self.depth_combo = QComboBox()
        self.depth_combo.setObjectName("depth_combo")
        self.depth_combo.addItem(tr("pitchgen.depth.pcm16"), "pcm16")
        self.depth_combo.addItem(tr("pitchgen.depth.pcm24"), "pcm24")
        self.depth_combo.addItem(tr("pitchgen.depth.float32"), "float32")
        form.addRow(tr("pitchgen.depth"), self.depth_combo)

        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setObjectName("fade_spin")
        self.fade_spin.setRange(0.0, 0.1)
        self.fade_spin.setSingleStep(0.005)
        self.fade_spin.setValue(0.01)
        form.addRow(tr("pitchgen.fade"), self.fade_spin)
        return box

    def _build_readout_box(self) -> QGroupBox:
        box = QGroupBox(tr("pitchgen.box.readout"))
        v = QVBoxLayout(box)
        self.readout_label = QLabel()
        self.readout_label.setObjectName("readout_label")
        self.readout_label.setWordWrap(True)
        font = theme.ui_mono_font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(int(theme.TOKENS["typography"]["h2"]))
        font.setBold(True)
        self.readout_label.setFont(font)
        v.addWidget(self.readout_label)
        return box

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    @staticmethod
    def _std_label(standard: dict) -> str:
        labels = standard.get("label", {}) or {}
        return labels.get(get_language()) or labels.get("en_US") or str(standard.get("id", ""))

    def current_standard(self) -> dict:
        sid = self.standards_combo.currentData(_USER)
        for standard in self._standards:
            if standard["id"] == sid:
                return standard
        return self._standards[0]

    def current_frequency_hz(self) -> float:
        standard = self.current_standard()
        note = str(self.note_combo.currentData(_USER) or "A")
        octave = int(self.octave_spin.value())
        return tone_frequency(note, octave, float(standard["a4_hz"]))

    def current_cents_vs_a440(self) -> float:
        """当前音名相对 A440 体系下**同音名**频率的音分偏差。

        恒等于 ``1200 * log2(a4_hz / 440)``，与音名 / 八度无关：读数语义是
        「所选标准整体偏高/偏低多少音分」，而非「该音相对 440 Hz 的音程」。
        """
        note = str(self.note_combo.currentData(_USER) or "A")
        octave = int(self.octave_spin.value())
        ref = tone_frequency(note, octave, 440.0)
        return float(hz_to_cents(self.current_frequency_hz(), ref_freq=ref))

    def build_audio(self) -> tuple[np.ndarray, int]:
        sample_rate = int(self.sample_rate_combo.currentData(_USER))
        data = synthesize_tone(
            self.current_frequency_hz(),
            float(self.duration_spin.value()),
            sample_rate=sample_rate,
            amplitude=float(self.amplitude_spin.value()),
            waveform=str(self.waveform_combo.currentData(_USER)),
            fade_s=float(self.fade_spin.value()),
        )
        return data, sample_rate

    def export_wave(self, path) -> "object":
        data, sample_rate = self.build_audio()
        return write_wave(
            path, data, sample_rate, depth=str(self.depth_combo.currentData(_USER))
        )

    def set_standard(self, standard_id: str) -> None:
        for index in range(self.standards_combo.count()):
            if self.standards_combo.itemData(index, _USER) == standard_id:
                self.standards_combo.setCurrentIndex(index)
                self._refresh()
                return
        raise ValueError(f"未知标准 id: {standard_id!r}")

    # ------------------------------------------------------------------
    # 刷新 / 交互
    # ------------------------------------------------------------------
    def _refresh(self, *_args) -> None:
        standard = self.current_standard()
        freq = self.current_frequency_hz()
        note = str(self.note_combo.currentData(_USER) or "A")
        octave = int(self.octave_spin.value())
        a4 = float(standard["a4_hz"])
        cents = self.current_cents_vs_a440()
        self.readout_label.setText(
            f"{freq:.2f} Hz    {note}{octave}    A4={a4:g} Hz    "
            f"{tr('pitchgen.cents')}: {cents:+.2f} cent"
        )
        refs = ", ".join(str(r) for r in standard.get("source_refs", []))
        self.source_browser.setPlainText(
            f"{standard.get('reference', '')}\n\n"
            f"{standard.get('evidence', '')}\n\n"
            f"{tr('pitchgen.source')}: {refs}"
        )
        self.caveat_label.setText(
            f"{tr('pitchgen.caveat')}: {standard.get('caveat', '')}"
        )
        preview_dur = 0.02
        try:
            sample_rate = int(self.sample_rate_combo.currentData(_USER))
            fade_s = min(float(self.fade_spin.value()), preview_dur / 4)
            self._preview_data = np.asarray(
                synthesize_tone(
                    self.current_frequency_hz(),
                    duration_s=preview_dur,
                    sample_rate=sample_rate,
                    amplitude=float(self.amplitude_spin.value()),
                    waveform=str(self.waveform_combo.currentData(_USER)),
                    fade_s=fade_s,
                ),
                dtype=np.float64,
            )
        except ValueError:
            self._preview_data = np.zeros(2, dtype=np.float64)
        self.preview_widget.update()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("pitchgen.btn.export"), "", tr("pitchgen.filter")
        )
        if not path:
            return
        try:
            written = self.export_wave(path)
            self.status_label.setText(tr("pitchgen.saved").format(path=written))
        except Exception as exc:  # 错误写状态行，禁弹模态框
            self.status_label.setText(tr("pitchgen.err.export").format(error=exc))

    def _on_load(self) -> None:
        if self._controller is None:
            return
        try:
            data, sample_rate = self.build_audio()
            standard = self.current_standard()
            note = str(self.note_combo.currentData(_USER) or "A")
            octave = int(self.octave_spin.value())
            name = f"pitchgen_{standard['id']}_{note}{octave}"
            self._controller.load_from_array(data, sample_rate, name=name)
            self.status_label.setText(tr("pitchgen.loaded").format(name=name))
        except Exception as exc:  # 错误写状态行，禁弹模态框
            self.status_label.setText(tr("pitchgen.err.load").format(error=exc))
