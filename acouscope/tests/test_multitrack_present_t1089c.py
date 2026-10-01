# SPDX-License-Identifier: GPL-3.0-only
"""T-1089 N-C：多轨对比呈现的坐标轴与网格（改前整幅**零 Y 刻度 / 零网格 / 零时间轴 / 零单位**）。

根因（PI-T81 DIM2 2.2/2.3）：``paintEvent`` 只画曲线、图例与差异条，读者无法把折线折成
音高值；同仓单轨 ``pitch.py`` 的轴/网格/音名刻度/A4 参考线七项俱全却**未接线**。本件按
「复用现成口径」落地：音名与换算走 ``dsp.units``（与 ``freq_axis.note_name_ticks`` 同一
命名口径·本模块不引 pyqtgraph），时间标注走 ``track_model.format_seconds``，疏密档位与
防叠字分别借 SV ``ScaleTickIntervals`` / ``HorizontalFrequencyScale``。

判据全部离屏可判（构件存在 + 画线数 + 真实落笔像素）；好不好看归 N5。
反证：抽掉避让间距 ⇒ 标签数必降；无结果时零轴；改前不存在轴构件（``_y_axis_ticks``
在窄带只出音名、宽带自动降档到八度 C）。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor

from acouscope.dsp import units
from acouscope.i18n import set_language
from acouscope.ui import theme
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import (
    AXIS_LABEL_GUTTER_W, AXIS_TIME_BAND_H, ComparePresentWidget,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession
from tests._pin_baselines import ICONS_LOGICAL_NAME_COUNT

_SR = 8000
_AXIS_KEYS = ("y_ticks", "grid_lines", "time_ticks", "reference_line")


class _PitchStub:
    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _session(n=2, duration=1.5, sr=_SR) -> MultitrackSession:
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": sr, "channels": 1,
                                   "duration": duration},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, duration, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(sr * duration)), sr),
    )
    for index in range(n):
        session.add_path(f"/tmp/t1089c{index}.wav", label=f"c{index}")
    return session


def _widget(tracks=2, *, times=None, f0s=None, size=(640, 420)):
    session = _session(tracks)
    cache = TrackResultCache()
    points = 30
    times = np.linspace(0.0, 1.5, points) if times is None else np.asarray(times)
    f0s = f0s or [np.linspace(430.0, 470.0, points),
                  np.linspace(540.0, 560.0, points)]
    for index in range(min(tracks, len(f0s))):
        cache.put(
            TrackResultCache.key(session.tracks()[index].track_id, "pitch", None),
            _PitchStub(times, np.asarray(f0s[index], dtype=float)),
        )
    widget = ComparePresentWidget(session, cache)
    widget.resize(*size)
    widget.refresh()
    widget.set_view_range(0.0, 1.5)
    return widget


def _pixels_in(widget, rect, *, match: int | None = None) -> int:
    """部件矩形带内的落笔像素数（``match=None`` ⇒ 凡不同于 panel 底色都算）。"""
    image = widget.grab().toImage()
    ratio_x = image.width() / max(1, widget.width())
    ratio_y = image.height() / max(1, widget.height())
    base = QColor(theme.colors()["panel"]).rgb()
    target = base if match is None else match
    same = match is None
    ink = 0
    for y in range(int(rect.top() * ratio_y), int(rect.bottom() * ratio_y) + 1):
        for x in range(int(rect.left() * ratio_x), int(rect.right() * ratio_x) + 1):
            if not (0 <= x < image.width() and 0 <= y < image.height()):
                continue
            hit = (image.pixel(x, y) != target) if same else (image.pixel(x, y) == target)
            ink += int(hit)
    return ink


@pytest.fixture(autouse=True)
def _zh(qapp, monkeypatch):
    """语言 + A4 参考钉死（A4 只经 monkeypatch 注入，禁写参考频率接口）。"""
    monkeypatch.setattr(units, "_reference_hz", 440.0)
    set_language("zh_CN")
    yield


# ---------------------------------------------------------------------------
# ① 轴构件存在且真落笔（改前探针[14] 三项全 0）
# ---------------------------------------------------------------------------


def test_axes_are_painted_and_inked(qapp):
    from PyQt6.QtCore import QRectF

    widget = _widget()
    widget.grab()
    stats = widget.paint_stats()
    assert stats["y_ticks"] > 0 and stats["grid_lines"] > 0
    assert stats["time_ticks"] > 0
    assert stats["reference_line"] == 1                  # A4=440 落在 430-560 带内
    data = widget._data_rect()
    gutter = QRectF(data.left() - AXIS_LABEL_GUTTER_W, data.top(),
                    AXIS_LABEL_GUTTER_W - 3.0, data.height())
    band = QRectF(data.left() + 4.0, data.bottom() + 1.0,
                  data.width() - 8.0, AXIS_TIME_BAND_H - 2.0)
    assert _pixels_in(widget, gutter) > 0               # 左带确有音名/单位落笔
    assert _pixels_in(widget, band) > 0                 # 下带确有时间标注落笔


def test_curves_and_playhead_share_data_rect(qapp):
    """轴带让位后映射口径唯一：t0/t1 落在数据区左右界、面板矩形也在其内。"""
    widget = _widget()
    data = widget._data_rect()
    assert widget.x_at(0.0) == pytest.approx(data.left())
    assert widget.x_at(1.5) == pytest.approx(data.right())
    assert widget.t_at(widget.x_at(0.75)) == pytest.approx(0.75)
    for info in widget.panels():
        assert info.rect.left() >= data.left() - 1e-6
        assert info.rect.right() <= data.right() + 1e-6
        assert info.rect.bottom() <= data.bottom() + 1e-6
    widget.set_selection((0.25, 1.0))
    widget.grab()
    assert widget.paint_stats()["curves"] == 2           # 让位后曲线照画


# ---------------------------------------------------------------------------
# ② 刻度口径：音名（复用 units）+ 疏密自适应降档
# ---------------------------------------------------------------------------


def test_y_ticks_use_note_names_within_visible_band(qapp):
    widget = _widget()
    lo, hi = widget.freq_range()
    ticks = widget._y_axis_ticks(widget._data_rect())
    assert ticks
    assert all(lo <= freq <= hi for freq, _label, _major in ticks)
    for freq, label, major in ticks:
        if major and label:
            assert label == units.midi_note_name(int(round(float(units.hz_to_midi(freq)))))
    # 音名一律语言中立（不随 zh/en 变更）
    assert any(label == "A4" for _f, label, _m in ticks)


def test_y_tick_step_coarsens_for_wide_band(qapp, monkeypatch):
    """宽带（40-2000 Hz）⇒ 自动降档到八度 C；窄带 ⇒ 逐半音。"""
    def label_gaps(widget):
        labels = [t for t in widget._y_axis_ticks(widget._data_rect()) if t[2] and t[1]]
        cents = [float(units.hz_to_cents(freq)) for freq, _n, _m in labels]
        return labels, [b - a for a, b in zip(cents, cents[1:])]

    widget = _widget(f0s=[np.full(30, 440.0), np.full(30, 440.0)])
    widget._freq_range = (40.0, 2000.0)
    wide_labels, wide_gaps = label_gaps(widget)
    assert wide_labels, "宽带仍应有标注"
    assert min(wide_gaps) >= 500.0, wide_gaps            # ★ 降档到三全音/八度而非半音
    assert len(wide_labels) < 20                          # 40-2000 Hz 共 ~78 半音
    narrow = _widget()                              # 默认素材：430-560 Hz（窄带）
    narrow_labels, narrow_gaps = label_gaps(narrow)
    assert len(narrow_labels) > 1
    assert max(narrow_gaps) < 200.0, narrow_gaps          # 窄带逐半音标注

    widget.grab()
    before = widget.paint_stats()
    monkeypatch.setattr(
        "acouscope.ui.widgets.multitrack.compare_present.AXIS_MIN_LABEL_SPACING", 1.0e6,
    )
    widget.update()
    widget.grab()
    after = widget.paint_stats()
    assert after["y_ticks"] < before["y_ticks"]           # ★ 反证：间距阈值确有约束力
    assert after["grid_lines"] > 0                        # 网格与标签解耦（仍画线）


def test_time_ticks_are_nice_steps_and_capped(qapp):
    widget = _widget()
    for span, cap in ((1.5, 12), (37.0, 12), (0.03, 12), (600.0, 20)):
        widget.set_view_range(0.0, span)
        ticks = widget._time_axis_ticks()
        assert 0 < len(ticks) <= cap, (span, len(ticks))
        steps = {round(b - a, 9) for a, b in zip(ticks, ticks[1:])}
        assert len(steps) == 1
        step = steps.pop()
        mantissa = step / (10.0 ** np.floor(np.log10(step) + 1e-9))
        assert round(mantissa * 10) in (10, 20, 50), (span, step)   # 1/2/5 档


# ---------------------------------------------------------------------------
# ③ 多图分离：逐面板画轴 + 跨面板避让不叠字
# ---------------------------------------------------------------------------


def test_grid_mode_draws_axes_per_panel_with_avoidance(qapp):
    widget = _widget(tracks=12, size=(640, 180))
    widget.set_mode("grid")
    widget.grab()
    stats = widget.paint_stats()
    assert stats["panels"] == 12
    assert stats["grid_lines"] >= 12                     # 网格逐格线各画各的（映射不同）
    # 子图高 ~9px < 文字高 ⇒ 跨面板避让游标必须抽稀（否则 12 条标签糊成一坨）
    assert stats["y_ticks"] <= 7, stats["y_ticks"]


# ---------------------------------------------------------------------------
# ④ 边界与不越权：只用现成 token / 无结果不画轴 / 图例有底衬
# ---------------------------------------------------------------------------


def test_no_axes_painted_without_results(qapp):
    """反证：空态只呈引导文案，轴带不落笔（也不与空态文字打架）。"""
    session = _session(2)
    widget = ComparePresentWidget(session, TrackResultCache())
    widget.resize(640, 420)
    widget.refresh()
    widget.grab()
    stats = widget.paint_stats()
    assert all(stats[key] == 0 for key in _AXIS_KEYS)
    assert widget.has_results() is False


def test_legend_has_backing_plate(qapp):
    """图例底衬：改前直叠曲线之上读不出（DIM2 2.5）⇒ 现按整块 tint 落底。"""
    widget = _widget()
    widget.grab()
    assert widget.paint_stats()["legend"] == 2
    data = widget._data_rect()
    from PyQt6.QtCore import QRectF

    tint = QColor(theme.data_ink("tint")).rgb()
    box = QRectF(data.right() - 120.0, data.top(), 118.0, 60.0)
    assert _pixels_in(widget, box, match=tint) > 50      # ★ 底衬成片落笔（非仅文字笔画）


def test_only_existing_tokens_and_inks_are_used(qapp):
    """不新增 icon/token：所用角色键在既有 TOKENS/theme 出口内可解析。"""
    assert theme.data_ink("ref_line")
    assert theme.data_ink("tint")
    assert "ref_line" in theme.TOKENS["data"]["dark"]
    assert len(theme.ICONS) == ICONS_LOGICAL_NAME_COUNT  # 图标扩容红线（本件零碰）


def test_axis_text_survives_language_switch(qapp):
    """轴文案与刻度不受语言切换影响（音名语言中立·单位走三语 tr）。"""
    widget = _widget()
    for lang in ("en_US", "zh_CN", "zh_TW"):
        set_language(lang)
        widget.grab()
        assert widget.paint_stats()["y_ticks"] > 0
    set_language("zh_CN")
