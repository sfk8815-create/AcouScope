# SPDX-License-Identifier: GPL-3.0-only
"""AudacityTimeAxis / apply_time_axis 接入测试（nice_ticks → pyqtgraph 底轴）。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

import pyqtgraph as pg

from acouscope.ui.widgets.time_axis import (
    AudacityTimeAxis,
    TickSet,
    apply_time_axis,
    format_seconds,
    _tickset_to_pgticks,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def plot(qapp):
    w = pg.PlotWidget()
    w.resize(900, 500)
    apply_time_axis(w)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


# ---------------- _tickset_to_pgticks 纯转换（无需视图） ----------------

def test_converter_two_levels_and_dedupe():
    ts = TickSet(
        majors=[0.0, 10.0],
        minors=[0.0, 5.0, 10.0],
        major_step=10.0,
        minor_step=5.0,
        digits=0,
    )
    levels = _tickset_to_pgticks(ts)
    assert len(levels) == 2
    assert levels[0] == [(0.0, "0"), (10.0, "10")]
    # 与主刻度重合的 0/10 被剔除，仅余 5；次刻度无文字标签
    assert levels[1] == [(5.0, None)]


def test_converter_mmss_labels():
    ts = TickSet(
        majors=[0.0, 60.0],
        minors=[0.0, 60.0],
        major_step=60.0,
        minor_step=60.0,
        digits=0,
    )
    levels = _tickset_to_pgticks(ts)
    assert levels[0] == [(0.0, "0"), (60.0, "01:00")]
    assert levels[1] == []


def test_converter_empty_tickset():
    ts = TickSet([], [], 0.0, 0.0, 0)
    assert _tickset_to_pgticks(ts) == [[], []]


# ---------------- AudacityTimeAxis / apply_time_axis 集成 ----------------

def test_apply_installs_audacity_axis(plot):
    axis = plot.getPlotItem().getAxis("bottom")
    assert isinstance(axis, AudacityTimeAxis)
    axis.refresh_ticks()
    assert isinstance(axis._tickLevels, list)
    assert len(axis._tickLevels) == 2


def test_min_label_px_parameter_passed_through(qapp):
    w = pg.PlotWidget()
    apply_time_axis(w, min_label_px=200.0)
    axis = w.getPlotItem().getAxis("bottom")
    assert isinstance(axis, AudacityTimeAxis)
    assert axis._min_label_px == 200.0
    w.close()


def test_second_range_tick_structure(plot, qapp):
    plot.setXRange(0.0, 10.0, padding=0)
    qapp.processEvents()
    axis = plot.getPlotItem().getAxis("bottom")
    axis.refresh_ticks()
    ts = axis._last_tickset
    assert ts is not None and ts.minor_step > 0 and ts.major_step > 0
    levels = axis._tickLevels
    # 主刻度：(float, str)，标签与 format_seconds 完全一致
    for pos, label in levels[0]:
        assert isinstance(pos, float)
        assert label == format_seconds(pos)
    # 次刻度：(float, None)，只画线不出字
    for pos, label in levels[1]:
        assert isinstance(pos, float)
        assert label is None
    # 0-10s 窗口内次刻度至少 2 个（5s 步长 → 5、10），位置不越界
    assert len(levels[1]) >= 2
    positions = [p for p, _ in levels[0]] + [p for p, _ in levels[1]]
    assert all(-1e-6 <= p <= 10.0 + 1e-6 for p in positions)


def test_ticks_recompute_on_zoom(plot, qapp):
    axis = plot.getPlotItem().getAxis("bottom")
    # 放大到 0.1s：子秒 {1,2,5}×10ⁿ 引擎，minor_step < 1s
    plot.setXRange(0.0, 0.1, padding=0)
    qapp.processEvents()
    axis.refresh_ticks()
    ts_zoom = axis._last_tickset
    assert ts_zoom.minor_step < 1.0
    # 缩小到 1 小时：硬编码时间表，minor_step >= 60s
    plot.setXRange(0.0, 3600.0, padding=0)
    qapp.processEvents()
    axis.refresh_ticks()
    ts_wide = axis._last_tickset
    assert ts_wide.minor_step >= 60.0
    # 3600s 必为主刻度位置，标签走 format_seconds → "60:00"
    labels = [label for _, label in axis._tickLevels[0]]
    assert "60:00" in labels


def test_refresh_without_linked_view_is_safe(qapp):
    axis = AudacityTimeAxis(orientation="bottom")
    axis.refresh_ticks()  # 未挂 ViewBox：静默返回，不抛异常
    assert axis._tickLevels is None
