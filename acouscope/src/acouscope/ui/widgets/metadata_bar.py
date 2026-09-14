# SPDX-License-Identifier: GPL-3.0-only
"""文件源数据常驻信息条：横向紧凑布局，置于分析面板顶部。

将原先占据整个分析面板的元数据视图压缩为单行信息条，
所有分析视图共享，不再随视图切换消失。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


def _fmt_size(nbytes: int) -> str:
    if nbytes >= 1024**3:
        return f"{nbytes / 1024**3:.2f} GB"
    if nbytes >= 1024**2:
        return f"{nbytes / 1024**2:.2f} MB"
    if nbytes >= 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes} B"


class MetadataBar(QWidget):
    """单行文件信息条：文件名 | 音频参数 | 信号特征。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self.setStyleSheet(
            "MetadataBar {background: #ffffff; border: 1px solid #e5e7eb;"
            " border-radius: 6px;}"
            "MetadataBar QLabel {color: #374151; background: transparent;"
            " font-size: 11px;}"
            "MetadataBar QFrame[frameShape='6'] {color: #d1d5db;}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        self.lbl_filename = QLabel("未加载文件")
        self.lbl_filename.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #111827;"
            " background: transparent;"
        )
        self.lbl_filename.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.lbl_filename)

        self.lbl_params = QLabel("")
        self.lbl_params.setStyleSheet(
            "color: #6b7280; font-size: 11px; background: transparent;"
        )
        self.lbl_params.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.lbl_params, stretch=1)

        self.lbl_signal = QLabel("")
        self.lbl_signal.setStyleSheet(
            "color: #6b7280; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self.lbl_signal)

    def set_info(self, info, data: np.ndarray | None, sample_rate: int) -> None:
        """填充文件信息与信号统计。"""
        if info is None:
            return
        path = Path(info.filepath)
        self.lbl_filename.setText(path.name)
        self.lbl_filename.setToolTip(str(path))

        channels_text = {1: "单声道", 2: "立体声"}.get(info.channels, f"{info.channels} 声道")
        self.lbl_params.setText(
            f"{info.format} · {_fmt_size(info.file_size)} · "
            f"{info.sample_rate:,} Hz · {channels_text} · "
            f"{info.bit_depth} bit · {info.duration_str}"
        )

        if data is not None and len(data) > 0:
            x = np.asarray(data, dtype=np.float64)
            peak_db = 20 * np.log10(max(float(np.max(np.abs(x))), 1e-12))
            rms_db = 20 * np.log10(max(float(np.sqrt(np.mean(x**2))), 1e-12))
            self.lbl_signal.setText(
                f"峰值 {peak_db:.1f} dBFS · RMS {rms_db:.1f} dBFS · "
                f"波峰因数 {peak_db - rms_db:.1f} dB"
            )
        else:
            self.lbl_signal.setText("")
