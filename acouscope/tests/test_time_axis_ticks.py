# SPDX-License-Identifier: GPL-3.0-only
"""nice_ticks / _time_tick_sizes 单元测试（零 Qt 依赖纯函数）。"""

import pytest

from acouscope.ui.widgets.time_axis import (
    TickSet,
    _time_tick_sizes,
    nice_ticks,
)


# ---------------- _time_tick_sizes 分支覆盖 ----------------

def test_real_format_subsecond_branch():
    # units=0.01 → RealFormat 分支；手算：minor=0.05, major=0.1, digits=2
    minor, major, digits = _time_tick_sizes(0.01)
    assert minor == pytest.approx(0.05)
    assert major == pytest.approx(0.1)
    assert digits == 2


def test_real_format_tiny_units():
    # units=1e-7 → minor=1e-6, major=5e-6, digits=6
    minor, major, digits = _time_tick_sizes(1e-7)
    assert minor == pytest.approx(1e-6)
    assert major == pytest.approx(5e-6)
    assert digits == 6


def test_real_format_just_below_half():
    # units=0.49 → RealFormat：d 推进到 0.5 时 0.49<0.5 命中 → minor=0.5, major=1.0, digits=1
    minor, major, digits = _time_tick_sizes(0.49)
    assert minor == pytest.approx(0.5)
    assert major == pytest.approx(1.0)
    assert digits == 1


def test_time_format_boundary_half_equal():
    # units=0.5 → 不 >0.5（等号），fallthrough 到 RealFormat
    # RealFormat 手算（RealFormat.cpp:26-58）：d 序列 1e-6,5e-6,1e-5,...,0.5,1.0
    # 0.5<0.5 否（等号不触发）→ d=1.0 时 0.5<1.0 命中 → minor=1.0, major=1.0*5.0=5.0, digits=0
    # （major=d*5.0 是 RealFormat 第一个分支的固定倍率，非 d*2.0）
    minor, major, digits = _time_tick_sizes(0.5)
    assert minor == pytest.approx(1.0)
    assert major == pytest.approx(5.0)
    assert digits == 0


def test_time_format_second_branch():
    # units=2 → units<5 → minor=5, major=15
    minor, major, _ = _time_tick_sizes(2.0)
    assert minor == 5.0
    assert major == 15.0


def test_time_format_minute_branch():
    # units=120 → units<300 → minor=300, major=900
    minor, major, digits = _time_tick_sizes(120.0)
    assert minor == pytest.approx(300.0)
    assert major == pytest.approx(900.0)
    assert digits == 0


def test_time_format_hour_branch():
    # units=7200 (2h) → units<6*3600=21600 → minor=6h, major=24h
    minor, major, _ = _time_tick_sizes(7200.0)
    assert minor == pytest.approx(6 * 3600.0)
    assert major == pytest.approx(24 * 3600.0)


def test_time_format_huge_units_caps_at_week():
    # units=1e9 → 超过所有阈值，返回 week/week
    minor, major, _ = _time_tick_sizes(1e9)
    week = 24.0 * 7.0 * 3600.0
    assert minor == pytest.approx(week)
    assert major == pytest.approx(week)


# ---------------- nice_ticks 端到端 ----------------

def test_nice_ticks_basic_range():
    ts = nice_ticks(0.0, 10.0, 900.0)
    # upp=10/900, units=90*10/900=1.0 → units<1.0? 否 → units<5.0 → minor=5, major=15
    assert ts.minor_step == pytest.approx(5.0)
    assert ts.major_step == pytest.approx(15.0)
    # majors=[0]，minors=[0,5,10]
    assert ts.majors == [pytest.approx(0.0)]
    assert ts.minors == [pytest.approx(0.0), pytest.approx(5.0), pytest.approx(10.0)]


def test_nice_ticks_negative_range():
    ts = nice_ticks(-5.0, 5.0, 900.0)
    # units=90*10/900=1.0 → minor=5, major=15
    assert ts.minors == [pytest.approx(-5.0), pytest.approx(0.0), pytest.approx(5.0)]
    assert ts.majors == [pytest.approx(0.0)]


def test_nice_ticks_empty_for_invalid_input():
    ts1 = nice_ticks(5.0, 5.0, 900.0)  # 零范围
    assert ts1.majors == [] and ts1.minors == []
    ts2 = nice_ticks(0.0, 10.0, 0.0)  # 零宽
    assert ts2.majors == [] and ts2.minors == []
    ts3 = nice_ticks(10.0, 5.0, 900.0)  # 反向
    assert ts3.majors == [] and ts3.minors == []


def test_nice_ticks_subsecond_resolution():
    ts = nice_ticks(0.0, 0.1, 900.0)
    # upp=0.1/900, units=90*0.1/900=0.01 → RealFormat → minor=0.05, major=0.1
    assert ts.minor_step == pytest.approx(0.05)
    assert ts.major_step == pytest.approx(0.1)
    assert ts.majors == [pytest.approx(0.0), pytest.approx(0.1)]
    assert ts.minors == [pytest.approx(0.0), pytest.approx(0.05), pytest.approx(0.1)]


def test_nice_ticks_major_step_is_minor_multiple():
    """major_step 必为 minor_step 的整数倍（Audacity 风格）。"""
    for units in [0.001, 0.01, 0.1, 0.49, 0.5, 1.0, 2.0, 5.0, 60.0, 600.0, 3600.0, 100000.0, 1e9]:
        minor, major, _ = _time_tick_sizes(units)
        ratio = major / minor
        assert abs(ratio - round(ratio)) < 1e-9, f"units={units} major/minor={ratio} 不是整数"


def test_nice_ticks_major_subset_of_minor():
    """主刻度位置必须全部出现在次刻度位置里（整数倍关系）。"""
    for t0, t1, w in [(0, 1, 800), (0, 60, 1200), (0, 3600, 2000), (-10, 100, 1000)]:
        ts = nice_ticks(t0, t1, w)
        if ts.majors and ts.minors:
            minor_set = {round(v, 9) for v in ts.minors}
            for m in ts.majors:
                assert round(m, 9) in minor_set, f"major {m} 不在 minors 内"


def test_nice_ticks_step_alignment_avoids_drift():
    """长范围下刻度严格按 step 整数倍对齐，无浮点累积漂移。"""
    ts = nice_ticks(0.0, 1000.0, 2000.0)
    for v in ts.minors:
        k = v / ts.minor_step
        assert abs(k - round(k)) < 1e-6, f"刻度 {v} 不是 minor_step 的整数倍"


def test_nice_ticks_min_label_px_changes_density():
    """增大 min_label_px 应使刻度更稀疏（步长更大或相等）。"""
    ts_dense = nice_ticks(0.0, 60.0, 1000.0, min_label_px=30)
    ts_sparse = nice_ticks(0.0, 60.0, 1000.0, min_label_px=200)
    assert ts_sparse.minor_step >= ts_dense.minor_step


def test_tickset_is_immutable_frozen():
    """frozen=True dataclass 应禁止属性赋值。"""
    ts = nice_ticks(0.0, 10.0, 900.0)
    with pytest.raises(Exception):
        ts.majors = []  # type: ignore[misc]
