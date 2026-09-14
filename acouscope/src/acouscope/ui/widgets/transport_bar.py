# SPDX-License-Identifier: GPL-3.0-only
"""传输条：播放/录音传输控制（独立控件，置于中央画布底部横贯全宽）。

信号与原 WaveformWidget 的 Transport 信号同名，主窗口槽函数签名不变。
"""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget,
)

from acouscope.i18n import tr
from acouscope.ui.theme import TOKENS, style_when_theme

_UNKNOWN_TIME = "--:--:--.---"


def format_transport_clock(sec) -> str:
    """秒数 → HH:MM:SS.mmm（毫秒精度，CB-013 D-1 DAW 大号读数）。

    None / NaN / 负数视为总时长未知，显示 ``--:--:--.---``。
    """
    if sec is None:
        return _UNKNOWN_TIME
    try:
        f = float(sec)
    except (TypeError, ValueError):
        return _UNKNOWN_TIME
    if math.isnan(f) or f < 0:
        return _UNKNOWN_TIME
    ms = int(round(f * 1000.0))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


class TransportBar(QWidget):
    """独立传输条。

    控件顺序：⏮ / ▶ / ■ / ⏭ / 分隔 / ●录音 / 输入设备 / 录音采样率 /
    ⟳循环 / 速率 / 当前时间 / 进度滑条（stretch=1）。
    """

    # Transport 信号（与原 waveform 同名，保持 main_window 槽函数签名不变）
    playToggled = pyqtSignal(bool)       # 播放切换
    playStop = pyqtSignal()              # 停止
    skipToStart = pyqtSignal()           # 跳到开头
    skipToEnd = pyqtSignal()             # 跳到结尾
    recordToggled = pyqtSignal(bool)     # 录音切换
    loopToggled = pyqtSignal(bool)       # 循环播放切换
    speedChanged = pyqtSignal(float)     # 播放速率变化
    seekPreview = pyqtSignal(int)        # 拖动进度条预览（0-1000）
    seekCommit = pyqtSignal()            # 释放进度条定位

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 0)
        layout.setSpacing(2)
        self.layout = layout

        # --- 按钮样式（从 waveform.py 原样搬；录音钮为红色变体）---
        tb_btn = (
            "QPushButton{font-size:11px;padding:2px 6px;min-width:22px;"
            "color:#6b7280;border:1px solid #e5e7eb;border-radius:3px;"
            "background:white;}"
            "QPushButton:hover{background:#f9fafb;color:#1f2937;border-color:#d1d5db;}"
            "QPushButton:checked{background:#2563eb;color:white;border-color:#2563eb;}"
            "QPushButton:disabled{color:#d1d5db;background:#f9fafb;}"
        )

        # 跳到开头
        self.btn_skip_start = QPushButton("⏮")
        self.btn_skip_start.setToolTip("跳到开头 (Home)")
        self.btn_skip_start.setStyleSheet(tb_btn)
        self.btn_skip_start.clicked.connect(lambda: self.skipToStart.emit())
        layout.addWidget(self.btn_skip_start)

        # 播放/暂停
        self.btn_play = QPushButton("▶")
        self.btn_play.setToolTip("播放 / 暂停 (Space)")
        self.btn_play.setCheckable(True)
        self.btn_play.setStyleSheet(tb_btn)
        self.btn_play.toggled.connect(lambda v: self.playToggled.emit(v))
        layout.addWidget(self.btn_play)

        # 停止
        self.btn_stop = QPushButton("■")
        self.btn_stop.setToolTip("停止 (Esc)")
        self.btn_stop.setStyleSheet(tb_btn)
        self.btn_stop.clicked.connect(lambda: self.playStop.emit())
        layout.addWidget(self.btn_stop)

        # 跳到结尾
        self.btn_skip_end = QPushButton("⏭")
        self.btn_skip_end.setToolTip("跳到结尾 (End)")
        self.btn_skip_end.setStyleSheet(tb_btn)
        self.btn_skip_end.clicked.connect(lambda: self.skipToEnd.emit())
        layout.addWidget(self.btn_skip_end)

        # 分隔线
        sep = QLabel("|")
        style_when_theme(sep, lambda c: f"color: {c['sub']}; padding: 0 2px;")
        layout.addWidget(sep)

        # 录音（红色变体）
        self.btn_record = QPushButton("●")
        self.btn_record.setToolTip("录音 (R)")
        self.btn_record.setCheckable(True)
        self.btn_record.setStyleSheet(
            tb_btn.replace("#2563eb", "#dc2626").replace("#6b7280", "#dc2626")
        )
        self.btn_record.toggled.connect(lambda v: self.recordToggled.emit(v))
        layout.addWidget(self.btn_record)

        # 录音输入设备
        self.cmb_input_device = QComboBox()
        self.cmb_input_device.setToolTip("选择录音输入设备")
        self.cmb_input_device.setMaximumWidth(140)
        layout.addWidget(self.cmb_input_device)

        # 录音采样率
        self.cmb_record_rate = QComboBox()
        self.cmb_record_rate.setToolTip("录音采样率")
        self.cmb_record_rate.setMaximumWidth(80)
        for rate in [8000, 16000, 22050, 44100, 48000, 96000]:
            self.cmb_record_rate.addItem(f"{rate//1000}k" if rate >= 1000 else str(rate), rate)
        self.cmb_record_rate.setCurrentIndex(3)  # 44100
        layout.addWidget(self.cmb_record_rate)

        # 循环播放
        self.btn_loop = QPushButton("⟳")
        self.btn_loop.setToolTip("循环播放选中区域（未选区域则无效）(L)")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setStyleSheet(tb_btn)
        self.btn_loop.toggled.connect(lambda v: self.loopToggled.emit(v))
        layout.addWidget(self.btn_loop)

        # 播放速率
        self.cmb_speed = QComboBox()
        for label, val in [
            ("0.5x", 0.5), ("0.75x", 0.75), ("1.0x", 1.0),
            ("1.25x", 1.25), ("1.5x", 1.5), ("2.0x", 2.0),
        ]:
            self.cmb_speed.addItem(label, val)
        self.cmb_speed.setCurrentIndex(2)  # 1.0x
        self.cmb_speed.setToolTip("播放速率（变速变调）")
        self.cmb_speed.setMaximumWidth(70)
        self.cmb_speed.currentIndexChanged.connect(
            lambda _: self.speedChanged.emit(float(self.cmb_speed.currentData()))
        )
        layout.addWidget(self.cmb_speed)

        # CB-013 D-1：显式速度读数（只读，随 cmb_speed 更新；颜色/字号走令牌派生）
        self.lbl_speed_readout = QLabel("1.00x")
        self.lbl_speed_readout.setToolTip(tr("transport.speed_readout"))
        self.lbl_speed_readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style_when_theme(
            self.lbl_speed_readout,
            lambda c: (
                f"font-family: {TOKENS['typography']['mono']};"
                f" font-size: {TOKENS['typography']['body']}px;"
                f" color: {c['sub']};"
            ),
        )
        self.cmb_speed.currentIndexChanged.connect(self._sync_speed_readout)
        layout.addWidget(self.lbl_speed_readout)

        layout.addSpacing(6)

        # CB-013 D-1：当前时间/总时长大号读数（HH:MM:SS.mmm 毫秒级，随主题派生色）
        self.lbl_current_time = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_current_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style_when_theme(
            self.lbl_current_time,
            lambda c: (
                f"font-family: {TOKENS['typography']['mono']};"
                f" font-size: {TOKENS['typography']['h3']}px;"
                f" color: {c['text']}; background: {c['input']};"
                f" padding: 1px 8px;"
                f" border-radius: {TOKENS['radius']['sm']}px;"
            ),
        )
        layout.addWidget(self.lbl_current_time)

        layout.addSpacing(6)

        # 播放进度条（占弹性空间）
        self.slider_position = QSlider(Qt.Orientation.Horizontal)
        self.slider_position.setRange(0, 1000)
        self.slider_position.setValue(0)
        self.slider_position.setToolTip("播放位置")
        self.slider_position.setStyleSheet(
            "QSlider{max-height:18px;}"
        )
        self.slider_position.sliderMoved.connect(self.seekPreview.emit)
        self.slider_position.sliderReleased.connect(self.seekCommit.emit)
        layout.addWidget(self.slider_position, stretch=1)

        # 与原 toolbar 一致的高度上限
        self.setMaximumHeight(30)

    # ------------------------------------------------------------------
    # 按钮状态同步（与原 waveform 同名同行为，blockSignals 不触发信号）
    # ------------------------------------------------------------------

    def set_play_button_state(self, playing: bool):
        """设置播放按钮状态。"""
        self.btn_play.blockSignals(True)
        self.btn_play.setChecked(playing)
        self.btn_play.setText("⏸" if playing else "▶")
        self.btn_play.blockSignals(False)

    def set_record_button_state(self, recording: bool):
        """设置录音按钮状态（录音中变身「■ 停止」，空闲恢复「● 录音」）。"""
        self.btn_record.blockSignals(True)
        self.btn_record.setChecked(recording)
        if recording:
            self.btn_record.setText("■")
            self.btn_record.setToolTip("停止录音 (R)")
        else:
            self.btn_record.setText("●")
            self.btn_record.setToolTip("录音 (R)")
        self.btn_record.blockSignals(False)

    def set_loop_state(self, checked: bool):
        """设置循环播放按钮状态（不触发信号）。"""
        self.btn_loop.blockSignals(True)
        self.btn_loop.setChecked(checked)
        self.btn_loop.blockSignals(False)

    # ------------------------------------------------------------------
    # 进度/时间显示
    # ------------------------------------------------------------------

    def set_seek_percent(self, permille: int):
        """设置进度滑条（0-1000 千分比，不触发信号）。"""
        self.slider_position.blockSignals(True)
        self.slider_position.setValue(int(permille))
        self.slider_position.blockSignals(False)

    def _sync_speed_readout(self):
        """速率下拉变化 → 只读读数刷新（如 1.00x / 0.50x）。"""
        data = self.cmb_speed.currentData()
        text = f"{float(data):.2f}x" if data is not None else "1.00x"
        if self.lbl_speed_readout.text() != text:
            self.lbl_speed_readout.setText(text)

    def set_time_label(self, current_sec: float, total_sec: float):
        """显示 当前时间/总时长（HH:MM:SS.mmm 毫秒级，DAW 大号读数）。

        无音频时显示 00:00:00.000 / 00:00:00.000（控件初始文本）；
        总时长未知（None/NaN/负数）显示 ``--:--:--.---``。
        """
        self.lbl_current_time.setText(
            f"{format_transport_clock(current_sec)} / "
            f"{format_transport_clock(total_sec)}"
        )
