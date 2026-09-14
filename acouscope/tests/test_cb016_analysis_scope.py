# SPDX-License-Identifier: GPL-3.0-only
"""CB-016-3：检查器分析范围数值化 + waveform.analysisPositionChanged 信号。

契约：
  ① InspectorPanel.set_analysis_scope(position, frame_size)（旧的按二元组
     region 显示的方法已删除）→ 文本「分析位置 X.XXXs · 窗口 Y.YYYs」
     （i18n 模板 + .format），无 region 二元组残留；
  ② waveform 新增 analysisPositionChanged = pyqtSignal(float)，在
     _on_cursor_moved 钳位后 emit（防死信号回潮：不得再出现声明零 emit）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.i18n import tr
from acouscope.ui.widgets.panels import InspectorPanel
from acouscope.ui.widgets.waveform import WaveformWidget


def test_inspector_set_analysis_scope_numeric_text(qapp):
    """直接构造 InspectorPanel（离屏）→ set_analysis_scope(1.234, 0.046)。"""
    panel = InspectorPanel()
    try:
        panel.set_analysis_scope(1.234, 0.046)
        text = panel.lbl_analysis.text()
        assert "1.234" in text, f"缺分析位置读数: {text!r}"
        assert "0.046" in text, f"缺窗口读数: {text!r}"
        assert text == tr("inspector.analysis_scope").format(
            pos=1.234, win=0.046
        ), f"文本未按 i18n 模板: {text!r}"
        assert "–" not in text, f"region 二元组残留: {text!r}"
    finally:
        panel.close()


def test_analysis_position_changed_signal_emits_once(qapp):
    """离屏 WaveformWidget → set_analysis_position → analysisPositionChanged
    恰 emit 一次且值正确（防死信号回潮）。"""
    w = WaveformWidget()
    try:
        sr, n = 1000, 5000
        t = np.arange(n, dtype=np.float32) / np.float32(sr)
        x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
        w.set_data(t, x, sample_rate=sr)

        got = []
        w.analysisPositionChanged.connect(got.append)
        w.set_analysis_position(2.0)  # emit=True 默认
        assert got == [2.0], f"analysisPositionChanged 应恰 emit 一次（got={got}）"
        assert abs(w.get_analysis_position() - 2.0) < 1e-6
    finally:
        w.close()
