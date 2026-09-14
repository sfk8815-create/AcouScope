# SPDX-License-Identifier: GPL-3.0-only
"""波形空态（未加载音频）修复测试：无负刻度、播放头初始隐藏。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.waveform import WaveformWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def widget(qapp):
    w = WaveformWidget()
    w.resize(1200, 400)
    qapp.processEvents()
    yield w
    w.close()


def test_empty_state_no_negative_ticks(widget, qapp):
    """未加载音频：时间轴主/次刻度均非负（修复"双 0"负刻度 bug）。"""
    qapp.processEvents()
    axis = widget.plot_widget.getPlotItem().getAxis("bottom")
    axis.refresh_ticks()
    ts = axis._last_tickset
    assert ts is not None
    assert all(v >= 0 for v in ts.majors), f"主刻度含负数: {ts.majors}"
    assert all(v >= 0 for v in ts.minors), f"次刻度含负数: {ts.minors}"


def test_empty_state_playhead_hidden(widget):
    """未加载音频：播放头初始隐藏（不参与 autoRange，不撑出负区间）。"""
    assert not widget.playhead.isVisible()


def test_set_playhead_shows(widget, qapp):
    """外部设置播放头位置后必须显示（播放/定位场景）。"""
    widget.set_playhead(0.5)
    qapp.processEvents()
    assert widget.playhead.isVisible()
    assert abs(float(widget.playhead.value()) - 0.5) < 1e-9
