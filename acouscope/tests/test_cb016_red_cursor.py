# SPDX-License-Identifier: GPL-3.0-only
"""CB-016-2：红针强化测试（宽度 6 / TOKENS 语义色 / 醒目 i18n Label）。

契约：
  - pen width 4.5 → 6；
  - 颜色走 theme.TOKENS 语义角色（禁内联 hex 断言用 TOKENS 值比对）；
  - Label 文本 i18n key 化（禁硬编码中文断言：用 tr('wave.analysis_cursor')
    取值比对）；
  - ShiftDragInfiniteLine 类型存续（Shift 拖动语义零改动）；
  - movable 默认 False 不变。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QGraphicsTextItem

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.waveform import ShiftDragInfiniteLine, WaveformWidget


def _first_text_child(item):
    """递归找首个 QGraphicsTextItem 的纯文本（跨 pyqtgraph 内部结构容错）。"""
    for child in item.childItems():
        if isinstance(child, QGraphicsTextItem):
            return child.toPlainText()
        found = _first_text_child(child)
        if found is not None:
            return found
    return None


def test_red_cursor_hardened(qapp):
    w = WaveformWidget()
    try:
        cur = w.analysis_cursor

        # 类型与可拖语义存续（Shift 才能拖）
        assert isinstance(cur, ShiftDragInfiniteLine)
        assert cur.movable is False

        # 线宽 6
        assert cur.pen.width() == pytest.approx(6.0)

        # 颜色 = TOKENS 语义 error 角色（禁硬编码 hex）
        assert cur.pen.color().name().upper() == \
            theme.TOKENS["semantic"]["error"].upper()

        # Label 文案 i18n（tr() 取值比对，禁硬编码中文）
        text = _first_text_child(cur)
        assert text is not None and text != "", "红针 Label 文本为空"
        assert text == tr("wave.analysis_cursor"), (
            f"Label 文本应等于 tr('wave.analysis_cursor')={tr('wave.analysis_cursor')!r}, "
            f"实际 {text!r}"
        )
    finally:
        w.close()


def test_red_cursor_label_becomes_numeric_after_move(qapp):
    """红针移动后数值标签仍为 `X.XXX s`（存续行为，_on_cursor_moved 文案）。"""
    import numpy as np

    w = WaveformWidget()
    try:
        sr, n = 1000, 5000
        t = np.arange(n, dtype=np.float32) / np.float32(sr)
        x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
        w.set_data(t, x, sample_rate=sr)
        w.set_analysis_position(1.5)  # emit=True → _on_cursor_moved 更新 label
        text = _first_text_child(w.analysis_cursor)
        assert text is not None and text.endswith(" s"), f"数值标签异常: {text!r}"
    finally:
        w.close()
