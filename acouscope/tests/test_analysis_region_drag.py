# SPDX-License-Identifier: GPL-3.0-only
"""CB-016-1 改写：原「分析区域（浅蓝块）边界可拖动测试」随蓝条移除整删。

蓝条（LinearRegionItem 实体）及其边缘/整体拖动语义已不复存在（用户决策
2026-09-07）。本文件改写为红针/选区的存续语义断言：
  ① 分析位置指针（红针）类型/可拖属性存续；
  ② set_analysis_position 数值往返 + emit 时 analysisPositionChanged 信号触发
     （CB-016-3 新信号；红针移动驱动检查器读数）；
  ③ 选区 API 存续（set/get/clear 往返）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.ui.widgets.waveform import ShiftDragInfiniteLine, WaveformWidget


@pytest.fixture
def widget(qapp):
    """已 set_data 的 WaveformWidget（5s 正弦波，不 show）。"""
    w = WaveformWidget()
    w.resize(1200, 400)
    sr = 1000
    n = 5000
    t = np.arange(n, dtype=np.float32) / np.float32(sr)
    x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
    w.set_data(t, x, sample_rate=sr)
    qapp.processEvents()
    yield w
    w.close()


def test_analysis_cursor_type_and_movable_preserved(widget):
    """红针为 ShiftDragInfiniteLine 且默认 movable=False（蓝条移除后存续）。"""
    assert isinstance(widget.analysis_cursor, ShiftDragInfiniteLine)
    assert widget.analysis_cursor.movable is False


def test_set_analysis_position_roundtrip_and_signal(widget):
    """set_analysis_position(emit=True) → 红针位置更新 + analysisPositionChanged 恰一次。"""
    got = []
    widget.analysisPositionChanged.connect(got.append)
    widget.set_analysis_position(1.25)
    assert abs(widget.get_analysis_position() - 1.25) < 1e-6
    assert got == [1.25], f"analysisPositionChanged 应恰 emit 一次（got={got}）"


def test_selection_api_roundtrip_preserved(widget):
    """选区 set/get/clear 往返（拖选交互存续，蓝条移除不改动）。"""
    assert widget.get_selection() is None
    widget.set_selection(1.0, 2.5)
    assert widget.get_selection() == (1.0, 2.5)
    widget.clear_selection()
    assert widget.get_selection() is None
