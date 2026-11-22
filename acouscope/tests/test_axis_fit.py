# SPDX-License-Identifier: GPL-3.0-only
"""axis_fit.best_tickset 单元测试（G4a-3 判据 A4/A5 相关；零 GUI 启动）。

- fm=None 回退 min_label_px=22（纯函数，无需 Qt）
- 从密到疏取首个满足「相邻主标签间距 ≥ 最宽标签 + gap_px」的档
- 全不满足退最疏档（90）
- t0>=t1 / pixel_width<=0 边界返回空刻度集
- 跨 60 s 走 MM:SS 并自动降密度
- 真 QFontMetrics.horizontalAdvance 下 A4 间距约束成立
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from acouscope.ui.widgets.axis_fit import (
    CANDIDATE_MIN_LABEL_PX,
    DEFAULT_GAP_PX,
    FALLBACK_MIN_LABEL_PX,
    best_tickset,
    _fits,
)
from acouscope.ui.widgets.time_axis import (
    TickSet,
    format_seconds,
    nice_ticks,
)


class _FixedWidthFM:
    """鸭子类型字体度量：horizontalAdvance 返回固定像素宽度。"""

    def __init__(self, width_px: float):
        self.width_px = float(width_px)

    def horizontalAdvance(self, text: str) -> float:  # noqa: ARG002
        return self.width_px


# ---------------- 极简边界（无需 Qt） ----------------


def test_best_tickset_invalid_range_returns_empty():
    ts = best_tickset(5.0, 5.0, 900.0, None, format_seconds)
    assert ts.majors == [] and ts.minors == []
    ts = best_tickset(10.0, 5.0, 900.0, None, format_seconds)
    assert ts.majors == [] and ts.minors == []


def test_best_tickset_invalid_width_returns_empty():
    ts = best_tickset(0.0, 10.0, 0.0, None, format_seconds)
    assert ts.majors == [] and ts.minors == []
    ts = best_tickset(0.0, 10.0, -100.0, None, format_seconds)
    assert ts.majors == [] and ts.minors == []


def test_best_tickset_fm_none_falls_back_to_22():
    ts = best_tickset(0.0, 60.0, 900.0, None, format_seconds)
    # units = 22 * 60 / 900 = 1.466 -> units<5.0 -> minor=5, major=15
    assert ts.minor_step == pytest.approx(5.0)
    assert ts.major_step == pytest.approx(15.0)
    assert ts.majors == [pytest.approx(v) for v in (0.0, 15.0, 30.0, 45.0, 60.0)]


def test_constants():
    assert CANDIDATE_MIN_LABEL_PX == (12, 16, 20, 24, 30, 36, 44, 60, 90)
    assert FALLBACK_MIN_LABEL_PX == 22.0
    assert DEFAULT_GAP_PX == 8


# ---------------- 从密到疏取首个满足 / 全不满足退最疏 ----------------


def test_best_tickset_picks_densest_fitting_arch():
    # 0-10s @1000px，恒宽 8px，gap 8 → need=16；cand=12 → units=0.12 -> RealFormat (0.5, 1.0)
    # 间距 1s×100px/s=100px 远超 need → 取最密档 12
    ts = best_tickset(0.0, 10.0, 1000.0, _FixedWidthFM(8.0), format_seconds)
    assert ts.minor_step == pytest.approx(0.5)
    assert ts.major_step == pytest.approx(1.0)
    assert ts.majors == [pytest.approx(float(v)) for v in range(0, 11)]


def test_best_tickset_all_unfit_falls_back_to_sparsest():
    # 恒宽 1000px，gap 8 → need=1008；间距最大 500px → 全不满足 → 退最疏档 90
    # units = 90 * 10 / 1000 = 0.9 -> 时间表 units<1.0 -> minor=1, major=5 → majors 0,5,10
    ts = best_tickset(0.0, 10.0, 1000.0, _FixedWidthFM(1000.0), format_seconds)
    assert ts.minor_step == pytest.approx(1.0)
    assert ts.major_step == pytest.approx(5.0)
    assert ts.majors == [pytest.approx(v) for v in (0.0, 5.0, 10.0)]


def test_best_tickset_returns_candidate_arch():
    # 全不满足 → 90：units = 90 * 60 / 100 = 54 -> 时间表 units<60 -> minor=60, major=300
    ts = best_tickset(0.0, 60.0, 100.0, _FixedWidthFM(10000.0), format_seconds)
    assert ts.minor_step == pytest.approx(60.0)
    assert ts.major_step == pytest.approx(300.0)
    assert ts.majors == [pytest.approx(0.0)]


def test_fits_under_two_labels_is_vacuously_true():
    # 相邻主标签 < 2 时无重叠可能，恒视为满足（即使间距算起来不足 need）
    ts = TickSet(majors=[0.0], minors=[], major_step=5.0, minor_step=1.0, digits=0)
    assert _fits(ts, 0.0, 8.0, 801.0, _FixedWidthFM(900.0), format_seconds, 8.0) is True


def test_fits_rejects_too_dense_majors():
    """反例：相邻主标签像素间距 < 最宽标签 + gap 时，_fits 必须返回 False。

    构造：majors=[0,1,2]，span=2s，pixel_width=100px → px_per_sec=50px/s；
    相邻间距 1s = 50px；label 恒宽 60px（_FixedWidthFM），gap=8 → need=68px；
    50 < 68 ⇒ 不满足，必须返回 False。
    删掉 _fits 内间距判断 ⇒ 本用例必红（D1 验收）。
    """
    ts = TickSet(majors=[0.0, 1.0, 2.0], minors=[], major_step=1.0, minor_step=0.5, digits=0)
    assert _fits(ts, 0.0, 2.0, 100.0, _FixedWidthFM(60.0), format_seconds, 8.0) is False


# ---------------- A4：间距 ≥ 最宽标签 + gap（真字体度量） ----------------


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_adjacent_spacing_ge_label_width_plus_gap(qapp):
    """A4：best_tickset 选出的档，任意相邻主标签间距 ≥ 最宽标签宽 + 8。"""
    from PyQt6.QtGui import QFontMetrics, QFont

    fm = QFontMetrics(QFont())
    for span, width_px in ((8.0, 900.0), (8.0, 560.0), (60.0, 900.0), (120.0, 900.0)):
        ts = best_tickset(0.0, span, width_px, fm, format_seconds, DEFAULT_GAP_PX)
        if len(ts.majors) < 2:
            continue
        px_per_sec = width_px / span
        max_w = max(fm.horizontalAdvance(format_seconds(float(v))) for v in ts.majors)
        need = max_w + DEFAULT_GAP_PX
        for a, b in zip(ts.majors, ts.majors[1:]):
            assert (float(b) - float(a)) * px_per_sec >= need - 1e-6, (
                f"span={span} w={width_px} step={ts.major_step} "
                f"gap={(float(b)-float(a))*px_per_sec:.1f}px need={need:.1f}px"
            )


# ---------------- A5：跨 60 s 的 MM:SS 与自动降密度 ----------------


def test_best_tickset_crosses_60s_uses_mmss():
    ts = best_tickset(0.0, 120.0, 900.0, _FixedWidthFM(8.0), format_seconds)
    labels = [format_seconds(float(v)) for v in ts.majors]
    assert any("01:00" in lab for lab in labels), labels
    assert len(ts.majors) >= 2


def test_best_tickset_wider_range_does_not_get_dense():
    """同一字体下，跨 60 s 的范围不应比 60 s 范围更密（MM:SS 标签更宽 ⇒ 降密度）。"""
    fm = _FixedWidthFM(24.0)
    ts_60 = best_tickset(0.0, 60.0, 900.0, fm, format_seconds)
    ts_120 = best_tickset(0.0, 120.0, 900.0, fm, format_seconds)
    assert ts_120.major_step >= ts_60.major_step, (ts_60.major_step, ts_120.major_step)
