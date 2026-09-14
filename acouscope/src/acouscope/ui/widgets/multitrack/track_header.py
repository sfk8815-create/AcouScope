# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 轨道头（D9 区域命名 / D10 音量滑杆 + 电平条）+ T-1006 M2 对齐微调。

每个轨道头包含：颜色标记 → 轨名（可编辑）→ 对齐状态标注 → 独奏 S → 静音 M
→ 音量滑杆（D10 方案甲，作用于播放当前轨）→ 电平条（静态=读文件峰值，
播放当前轨时动态）→ 对齐偏移微调（-10 / 数值框（±1ms 步进）/ +10）→ 播放/停止 →
移除（撤销窗口由容器层提供）。

对齐微调只改「偏移元数据」（`TrackModel.offset_ms`），不改音频数据（T-1006 硬红线）。
图标按 T-1001 现有逻辑名复用（play / stop / close）；S/M 用字母标记，
本任务不新增 ICONS 逻辑名（见放行令裁定 A）。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QSlider,
    QToolButton, QVBoxLayout, QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.multitrack.align import (
    NUDGE_COARSE_MS, NUDGE_FINE_MS, OFFSET_MAX_MS, OFFSET_MIN_MS, clamp_offset_ms,
    nudge_offset_ms,
)
from acouscope.ui.widgets.multitrack.track_model import TrackModel, format_seconds

# 行高：由令牌派生（避免硬编码像素），轨道头与波形区同高
ROW_HEIGHT = TOKENS["spacing"]["xl"] + TOKENS["spacing"]["lg"]
# 轨道头列宽（令牌派生；T-1006 起容纳对齐微调组：-10 / 数值框 / +10）
COLUMN_WIDTH = TOKENS["spacing"]["xxl"] * 9
# 颜色标记条宽（令牌派生）
STRIP_WIDTH = TOKENS["spacing"]["xs"]


def track_color(index: int) -> str:
    """轨色：内容色板轮转（T-1036 身份色，与语义反馈色分家；无硬编码色值）。"""
    return theme.track_color(index)


class LevelBar(QFrame):
    """迷你电平条：静态=读文件峰值，播放当前轨时动态刷新（D10）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("trackLevelBar")
        self.setMinimumWidth(TOKENS["spacing"]["xxl"])
        self.setFixedHeight(TOKENS["spacing"]["sm"])
        self._peak = 0.0
        self._level = 0.0
        self._refresh_style = theme.style_when_theme(self, self._on_theme_refresh)

    def set_peak(self, value: float) -> None:
        """静态幅度（读文件峰值，0~1）。"""
        self._peak = max(0.0, min(1.0, float(value)))
        if self._level <= 0.0:
            self.update()

    def set_level(self, value: float) -> None:
        """动态幅度（播放当前轨时；0 表示回落到静态峰值）。"""
        self._level = max(0.0, min(1.0, float(value)))
        self.update()

    def level(self) -> float:
        return self._level if self._level > 0.0 else self._peak

    def paintEvent(self, event):  # noqa: N802（Qt 命名）
        c = theme.colors()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(c["input"]))
        value = self.level()
        if value <= 0.0:
            p.setPen(QColor(c["border"]))
            p.drawLine(0, self.height() // 2, self.width(), self.height() // 2)
            return
        p.fillRect(
            0, 0, int(self.width() * value), self.height(),
            QColor(c["accent"]),
        )

    def _on_theme_refresh(self, c: dict) -> str:
        return ""


class TrackHeader(QWidget):
    """单轨轨道头（点击=设为当前轨）。"""

    currentRequested = pyqtSignal(str)
    renamed = pyqtSignal(str, str)
    soloToggled = pyqtSignal(str, bool)
    muteToggled = pyqtSignal(str, bool)
    volumeChanged = pyqtSignal(str, float)
    playToggled = pyqtSignal(str)
    removeRequested = pyqtSignal(str)
    offsetChanged = pyqtSignal(str, float)      # T-1006：手动微调（轨 id, 偏移 ms）

    def __init__(
        self,
        track: TrackModel,
        *,
        index: int = 0,
        current: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.track_id = track.track_id
        self.color_index = int(index)
        self.setFixedHeight(ROW_HEIGHT)
        self.setObjectName("trackHeader")

        sp = TOKENS["spacing"]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(sp["xs"], sp["xxs"], sp["xs"], sp["xxs"])
        outer.setSpacing(sp["xxs"])

        # 第一行：颜色标记 | 轨名 | S | M | 移除
        row1 = QHBoxLayout()
        row1.setSpacing(sp["xs"])
        self.color_strip = QFrame(self)
        self.color_strip.setFixedWidth(STRIP_WIDTH)
        self.color_strip.setObjectName("trackColorStrip")
        row1.addWidget(self.color_strip)

        self.edit_name = QLineEdit(track.label, self)
        self.edit_name.setFrame(False)
        self.edit_name.setObjectName("trackNameEdit")
        self.edit_name.editingFinished.connect(self._on_rename)
        row1.addWidget(self.edit_name, 1)

        self.btn_solo = QToolButton(self)
        self.btn_solo.setObjectName("trackSolo")
        self.btn_solo.setText("S")
        self.btn_solo.setCheckable(True)
        self.btn_solo.toggled.connect(
            lambda on: self.soloToggled.emit(self.track_id, bool(on))
        )
        row1.addWidget(self.btn_solo)

        self.btn_mute = QToolButton(self)
        self.btn_mute.setObjectName("trackMute")
        self.btn_mute.setText("M")
        self.btn_mute.setCheckable(True)
        self.btn_mute.toggled.connect(
            lambda on: self.muteToggled.emit(self.track_id, bool(on))
        )
        row1.addWidget(self.btn_mute)

        # 对齐状态标注（T-1006）：未跑过对齐时隐藏；已检出显示起点，未检出显示提示
        self.lbl_align = QLabel(self)
        self.lbl_align.setObjectName("trackAlignState")
        self.lbl_align.hide()
        row1.addWidget(self.lbl_align)

        self.btn_remove = QToolButton(self)
        self.btn_remove.setObjectName("trackRemove")
        self.btn_remove.setIcon(theme.get_icon("close"))
        self.btn_remove.clicked.connect(
            lambda _checked=False: self.removeRequested.emit(self.track_id)
        )
        row1.addWidget(self.btn_remove)
        outer.addLayout(row1)

        # 第二行：信息 | 音量 | 电平条 | 偏移 | 播放
        row2 = QHBoxLayout()
        row2.setSpacing(sp["xs"])
        self.lbl_info = QLabel(self)
        self.lbl_info.setObjectName("trackInfo")
        row2.addWidget(self.lbl_info)

        self.slider_volume = QSlider(Qt.Orientation.Horizontal, self)
        self.slider_volume.setObjectName("trackVolume")
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(int(round(track.volume * 100)))
        self.slider_volume.valueChanged.connect(
            lambda v: self.volumeChanged.emit(self.track_id, float(v) / 100.0)
        )
        row2.addWidget(self.slider_volume, 1)

        self.level_bar = LevelBar(self)
        row2.addWidget(self.level_bar)

        # 对齐偏移微调（T-1006）：-10ms（粗调）| 数值框（±1ms 步进）| +10ms（粗调）
        self.btn_offset_coarse_back = QToolButton(self)
        self.btn_offset_coarse_back.setObjectName("trackOffsetCoarseBack")
        self.btn_offset_coarse_back.setText(f"-{int(NUDGE_COARSE_MS)}")
        self.btn_offset_coarse_back.setAutoRepeat(True)
        self.btn_offset_coarse_back.clicked.connect(
            lambda _checked=False: self._on_nudge(-NUDGE_COARSE_MS)
        )
        row2.addWidget(self.btn_offset_coarse_back)

        self.spin_offset = QDoubleSpinBox(self)
        self.spin_offset.setObjectName("trackOffsetSpin")
        self.spin_offset.setDecimals(0)
        self.spin_offset.setRange(OFFSET_MIN_MS, OFFSET_MAX_MS)
        self.spin_offset.setSingleStep(NUDGE_FINE_MS)
        self.spin_offset.setSuffix(" ms")
        self.spin_offset.setValue(track.offset_ms)
        self.spin_offset.valueChanged.connect(self._on_offset_edited)
        row2.addWidget(self.spin_offset)

        self.btn_offset_coarse_fwd = QToolButton(self)
        self.btn_offset_coarse_fwd.setObjectName("trackOffsetCoarseFwd")
        self.btn_offset_coarse_fwd.setText(f"+{int(NUDGE_COARSE_MS)}")
        self.btn_offset_coarse_fwd.setAutoRepeat(True)
        self.btn_offset_coarse_fwd.clicked.connect(
            lambda _checked=False: self._on_nudge(NUDGE_COARSE_MS)
        )
        row2.addWidget(self.btn_offset_coarse_fwd)

        self.btn_play = QToolButton(self)
        self.btn_play.setObjectName("trackPlay")
        self.btn_play.setIcon(theme.get_icon("play"))
        self.btn_play.clicked.connect(
            lambda _checked=False: self.playToggled.emit(self.track_id)
        )
        row2.addWidget(self.btn_play)
        outer.addLayout(row2)

        self._current = bool(current)
        self._playing = False
        self._align_state = "unset"          # unset / detected / none（T-1006 对齐状态）
        self._align_onset_ms: int | None = None
        self._refresh_style = theme.style_when_theme(self, self._on_theme_refresh)
        if hasattr(theme, "on_theme_change"):
            theme.on_theme_change(self._apply_visual)
        self.refresh_from_track(track)
        self.set_current(current)
        self._apply_visual()
        self.retranslate()

    # ------------------------------------------------------------------
    # 同步
    # ------------------------------------------------------------------

    def refresh_from_track(self, track: TrackModel) -> None:
        """按轨道模型刷新显示（轨名/信息/峰值/偏移/音量）。"""
        if self.edit_name.text() != track.label:
            self.edit_name.setText(track.label)
        rate = f"{track.sample_rate / 1000.0:.1f} kHz" if track.sample_rate else "—"
        self.lbl_info.setText(
            tr(
                "multitrack.info",
                "{duration} · {rate}",
            ).format(duration=format_seconds(track.duration), rate=rate)
        )
        self.set_offset_ms(track.offset_ms)
        self.level_bar.set_peak(track.level_peak())
        if self.slider_volume.value() != int(round(track.volume * 100)):
            self.slider_volume.blockSignals(True)
            self.slider_volume.setValue(int(round(track.volume * 100)))
            self.slider_volume.blockSignals(False)
        for btn, flag in ((self.btn_solo, track.solo), (self.btn_mute, track.mute)):
            if btn.isChecked() != bool(flag):
                btn.blockSignals(True)
                btn.setChecked(bool(flag))
                btn.blockSignals(False)

    def set_current(self, current: bool) -> None:
        """当前轨高亮（点击轨头 = 设为当前轨）。"""
        changed = bool(current) != self._current
        self._current = bool(current)
        if changed:
            self._repolish()

    def is_current(self) -> bool:
        return self._current

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)
        self.btn_play.setIcon(theme.get_icon("stop" if playing else "play"))
        self.btn_play.setToolTip(
            tr("multitrack.tt.stop") if playing else tr("multitrack.tt.play")
        )

    def set_level(self, value: float) -> None:
        self.level_bar.set_level(value)

    def track_id_of(self) -> str:
        return self.track_id

    # ------------------------------------------------------------------
    # 对齐偏移（T-1006 微调）
    # ------------------------------------------------------------------

    def offset_ms(self) -> float:
        """当前显示的偏移（毫秒）。"""
        return float(self.spin_offset.value())

    def set_offset_ms(self, value, *, emit: bool = False) -> float:
        """外部刷新偏移显示（自动对齐 / 会话恢复）；默认不发信号（防回环）。"""
        clamped = clamp_offset_ms(value)
        blocked = self.spin_offset.blockSignals(True)
        self.spin_offset.setValue(clamped)
        self.spin_offset.blockSignals(blocked)
        if emit:
            self.offsetChanged.emit(self.track_id, clamped)
        return clamped

    def set_align_state(self, onset_ms) -> None:
        """对齐状态：int=已检出起点（毫秒）；None=该轨未检测到起点。"""
        self._align_state = "none" if onset_ms is None else "detected"
        self._align_onset_ms = None if onset_ms is None else int(onset_ms)
        self._render_align_state()

    def clear_align_state(self) -> None:
        """尚未跑过对齐：隐藏状态标注。"""
        self._align_state = "unset"
        self._align_onset_ms = None
        self._render_align_state()

    def align_state(self) -> str:
        return self._align_state

    def _render_align_state(self) -> None:
        if self._align_state == "unset":
            self.lbl_align.clear()
            self.lbl_align.hide()
        else:
            text = (
                tr("multitrack.align.none")
                if self._align_state == "none"
                else tr("multitrack.align.onset").format(
                    ms=int(self._align_onset_ms or 0)
                )
            )
            self.lbl_align.setText(text)
            self.lbl_align.show()
        self._apply_visual()

    def _on_offset_edited(self, value: float) -> None:
        self.offsetChanged.emit(self.track_id, clamp_offset_ms(value))

    def _on_nudge(self, delta_ms: float) -> None:
        """±10ms 粗调（±1ms 由数值框步进承担）；只改偏移元数据。"""
        self.spin_offset.setValue(
            nudge_offset_ms(self.spin_offset.value(), delta_ms)
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_rename(self) -> None:
        self.renamed.emit(self.track_id, self.edit_name.text())

    def mousePressEvent(self, event):  # noqa: N802（Qt 命名）
        self.currentRequested.emit(self.track_id)
        super().mousePressEvent(event)

    def retranslate(self) -> None:
        """i18n tooltip（三语）。"""
        self.setToolTip(tr("multitrack.tt.name"))
        self.edit_name.setToolTip(tr("multitrack.tt.rename"))
        self.btn_solo.setToolTip(tr("multitrack.tt.solo"))
        self.btn_mute.setToolTip(tr("multitrack.tt.mute"))
        self.btn_remove.setToolTip(tr("multitrack.tt.remove"))
        self.slider_volume.setToolTip(tr("multitrack.tt.volume"))
        self.level_bar.setToolTip(tr("multitrack.tt.level"))
        self.spin_offset.setToolTip(tr("multitrack.tt.offset"))
        self.btn_offset_coarse_back.setToolTip(
            tr("multitrack.tt.offset_coarse").format(step=int(NUDGE_COARSE_MS))
        )
        self.btn_offset_coarse_fwd.setToolTip(
            tr("multitrack.tt.offset_coarse").format(step=int(NUDGE_COARSE_MS))
        )
        self.lbl_align.setToolTip(tr("multitrack.tt.align"))
        self._render_align_state()
        self.set_playing(self._playing)

    def _repolish(self) -> None:
        self._apply_visual()

    def _apply_visual(self) -> None:
        """当前轨高亮 + 对齐状态配色（主题令牌驱动，零硬编码色值）。"""
        c = theme.colors()
        strip = c["accent"] if self._current else track_color(self.color_index)
        self.color_strip.setStyleSheet(
            f"#trackColorStrip {{ background: {strip}; }}"
        )
        align_color = (
            TOKENS["semantic"]["warning"] if self._align_state == "none" else c["sub"]
        )
        self.lbl_align.setStyleSheet(
            f"#trackAlignState {{ color: {align_color}; }}"
        )
        font = self.edit_name.font()
        font.setBold(self._current)
        self.edit_name.setFont(font)

    def _on_theme_refresh(self, c: dict) -> str:
        self._apply_visual()
        return ""


class TrackHeaderColumn(QWidget):
    """轨道头列：与波形区行序一一对应（行高同 ROW_HEIGHT）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("trackHeaderColumn")
        self.setFixedWidth(COLUMN_WIDTH)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._headers: dict[str, TrackHeader] = {}

    def headers(self) -> dict[str, TrackHeader]:
        return dict(self._headers)

    def rebuild(self, session) -> None:
        """按会话重建（简单重建，轨道数不设人为上限，由外层滚动区承载）。"""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._headers = {}
        for index, track in enumerate(session.tracks()):
            header = TrackHeader(
                track,
                index=index,
                current=(track.track_id == session.current_id),
                parent=self,
            )
            self._headers[track.track_id] = header
            self._layout.addWidget(header)

    def header_for(self, track_id: str) -> TrackHeader | None:
        return self._headers.get(track_id)

    def set_current(self, track_id: str | None) -> None:
        for tid, header in self._headers.items():
            header.set_current(tid == track_id)
