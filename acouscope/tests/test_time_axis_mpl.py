# SPDX-License-Identifier: GPL-3.0-only
"""NiceTicksLocator 单元测试（matplotlib Locator 子类，3D 频谱图时间轴用）。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import Locator

from acouscope.ui.widgets.time_axis import NiceTicksLocator, nice_ticks


def test_locator_is_locator_subclass():
    """NiceTicksLocator 必须真正继承 matplotlib.ticker.Locator（set_major_locator 硬检）。"""
    loc = NiceTicksLocator()
    assert isinstance(loc, Locator)


def test_locator_major_ticks_match_nice_ticks():
    """创建真实 fig/ax，挂 NiceTicksLocator，draw 后刻度位置与 nice_ticks 一致。"""
    fig, ax = plt.subplots(figsize=(9, 3))
    loc = NiceTicksLocator(min_label_px=90)
    ax.xaxis.set_major_locator(loc)
    ax.set_xlim(0, 10)
    fig.canvas.draw()
    ticks = list(ax.get_xticks())
    pixel_width = float(ax.bbox.width)
    expected = nice_ticks(0.0, 10.0, pixel_width, 90.0)
    # 过滤掉 matplotlib 可能追加的边界外刻度
    ticks_in = [t for t in ticks if -1e-6 <= t <= 10.0 + 1e-6]
    exp_in = [v for v in expected.majors if -1e-6 <= v <= 10.0 + 1e-6]
    assert len(ticks_in) == len(exp_in)
    for a, b in zip(sorted(ticks_in), sorted(exp_in)):
        assert abs(a - b) < 1e-6
    plt.close(fig)


def test_locator_minor_mode():
    """minor=True 时返回次刻度位置。"""
    fig, ax = plt.subplots(figsize=(9, 3))
    loc_minor = NiceTicksLocator(min_label_px=90, minor=True)
    ax.xaxis.set_minor_locator(loc_minor)
    ax.set_xlim(0, 10)
    fig.canvas.draw()
    pixel_width = float(ax.bbox.width)
    expected = nice_ticks(0.0, 10.0, pixel_width, 90.0)
    minor_ticks = list(ax.get_xticks(minor=True))
    # 次刻度中不与主刻度重合的值（matplotlib 可能合并，检查子集）
    for mt in minor_ticks:
        if -1e-6 <= mt <= 10.0 + 1e-6:
            assert any(abs(mt - v) < 1e-6 for v in expected.minors), \
                f"minor tick {mt} not in nice_ticks minors"
    plt.close(fig)


def test_locator_subsecond_range():
    """0–0.1s 范围走 RealFormat {1,2,5}×10ⁿ，minor_step < 1s。"""
    fig, ax = plt.subplots(figsize=(9, 3))
    loc = NiceTicksLocator()
    ax.xaxis.set_major_locator(loc)
    ax.set_xlim(0, 0.1)
    fig.canvas.draw()
    ts = nice_ticks(0.0, 0.1, float(ax.bbox.width), 90.0)
    assert ts.minor_step < 1.0
    plt.close(fig)


def test_locator_hour_range():
    """0–3600s 范围走 TimeFormat 硬编码表，minor_step >= 60s。"""
    fig, ax = plt.subplots(figsize=(9, 3))
    loc = NiceTicksLocator()
    ax.xaxis.set_major_locator(loc)
    ax.set_xlim(0, 3600)
    fig.canvas.draw()
    ts = nice_ticks(0.0, 3600.0, float(ax.bbox.width), 90.0)
    assert ts.minor_step >= 60.0
    # 3600s（=60min）应出现在主刻度
    assert any(abs(v - 3600.0) < 1e-6 for v in ts.majors)
    plt.close(fig)


def test_locator_tick_values_no_axis_fallback():
    """未挂载 axis 时 tick_values 退用 900px 默认，不抛异常。"""
    loc = NiceTicksLocator(min_label_px=90)
    # 不调 set_axis，直接 tick_values（模拟未挂载场景）
    vals = loc.tick_values(0.0, 10.0)
    expected = nice_ticks(0.0, 10.0, 900.0, 90.0)
    assert len(vals) == len(expected.majors)
    for a, b in zip(sorted(vals), sorted(expected.majors)):
        assert abs(a - b) < 1e-6


def test_locator_min_label_px_affects_density():
    """增大 min_label_px 使刻度更稀疏（步长更大或相等）。"""
    fig, ax = plt.subplots(figsize=(9, 3))
    loc_dense = NiceTicksLocator(min_label_px=30)
    ax.xaxis.set_major_locator(loc_dense)
    ax.set_xlim(0, 60)
    fig.canvas.draw()
    pixel_width = float(ax.bbox.width)
    ts_dense = nice_ticks(0.0, 60.0, pixel_width, 30.0)
    ts_sparse = nice_ticks(0.0, 60.0, pixel_width, 200.0)
    assert ts_sparse.minor_step >= ts_dense.minor_step
    plt.close(fig)


def test_tick_values_reversed_range_equals_forward():
    """反转区间（瀑布图 set_ylim(t1,t0) 场景）返回与正向完全一致的刻度。"""
    loc = NiceTicksLocator(min_label_px=90)
    fwd = sorted(float(v) for v in loc.tick_values(0.0, 8.0))
    rev = sorted(float(v) for v in loc.tick_values(8.0, 0.0))
    assert fwd, "正向区间刻度不应为空"
    assert rev, "反转区间刻度不应为空（bug 修复点）"
    assert rev == fwd


def test_tick_values_minor_reversed_range():
    """minor=True 的反转区间同样安全且与正向一致。"""
    loc = NiceTicksLocator(min_label_px=90, minor=True)
    fwd = sorted(float(v) for v in loc.tick_values(0.0, 8.0))
    rev = sorted(float(v) for v in loc.tick_values(8.0, 0.0))
    assert fwd and rev == fwd
