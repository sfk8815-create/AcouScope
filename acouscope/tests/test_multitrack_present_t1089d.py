# SPDX-License-Identifier: GPL-3.0-only
"""T-1089 N-D：音律上下文格线（频带八度密铺）+ 「音名±cent」读数。

根因（PI-T81 DIM1 1.4/1.5/1.6）：

- ``tunings.overlay.build_overlay_lines`` 只出 **1/1 所在的那一个八度** ⇒ 208-237 Hz
  这类不含主音八度的可见频带内**一条律级线都没有**（探针[B] 0 条）；
- ``compare_diff.SEMITONE_CENTS`` 全仓零消费（注释宣称的"显示参考半音线"在呈现层无实现）；
- 悬停读数只出裸 ``#-7`` ⇒ 接了律制却读不出"这是哪个音、差多少"。

本件三处落地：① ``overlay`` 新增按频带八度密铺的**纯函数**（复用 ``TuningSystem`` 自身
的八度折叠外推·含负音级；``overlay.py`` 不在禁碰清单）；② ``compare_present`` 绘律级线
（消费 ①，间距不足一像素按整数倍抽稀）；③ 读数追加 ``音名±cent``（借 SV
``Pitch::getPitchLabel`` 口径·消费 ``SEMITONE_CENTS``），**裸 ``#<音级>`` 原样保留**
（``test_tuning_present_link.py:150/160`` 钉此子串）。

★ 边界：不改 ``compare_diff`` 让差异口径律制化（禁碰·R-1/R-6）；密铺密度是否抢戏归 N5。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.analysis.tunings.overlay import (
    build_band_overlay_lines, build_overlay_lines,
)
from acouscope.analysis.tunings.templates import get_template
from acouscope.dsp import units
from acouscope.i18n import set_language
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import (
    DIFF_BAR_MAX_ROWS, ComparePresentWidget,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SR = 8000
TEMPLATES = ("12tet", "just_major", "pythagorean_diatonic", "quarter_comma_meantone",
             "chinese_sanfen_sunyi_12", "indian_22_shruti", "arabic_24_tone")


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
        session.add_path(f"/tmp/t1089d{index}.wav", label=f"d{index}")
    return session


def _widget(ref_f0, other_f0):
    session = _session(2)
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.5, 30)
    for track, f0 in zip(session.tracks(), (ref_f0, other_f0)):
        cache.put(TrackResultCache.key(track.track_id, "pitch", None),
                  _PitchStub(times, np.asarray(f0, dtype=float)))
    widget = ComparePresentWidget(session, cache)
    widget.resize(640, 420)
    widget.refresh()
    widget.set_view_range(0.0, 1.5)
    return widget, session


@pytest.fixture(autouse=True)
def _stable(qapp, monkeypatch):
    monkeypatch.setattr(units, "_reference_hz", 440.0)
    set_language("zh_CN")
    yield


# ---------------------------------------------------------------------------
# ① 密铺纯函数：对照探针[B]（单八度 0 条 → 按频带多出八度线）
# ---------------------------------------------------------------------------


def test_band_tiling_covers_octaves_that_single_octave_misses():
    tet = get_template("12tet")
    single = build_overlay_lines(tet, min_hz=208.0, max_hz=237.0)
    tiled = build_band_overlay_lines(tet, min_hz=208.0, max_hz=237.0)
    assert single == []                                   # ★ 改前口径：带内一条也没有
    assert [round(line.freq_hz, 2) for line in tiled] == [220.0, 233.08]
    assert [line.degree for line in tiled] == [-12, -11]  # 复用模型的负音级外推
    wide = build_band_overlay_lines(tet, min_hz=40.0, max_hz=2000.0)
    assert len(build_overlay_lines(tet, min_hz=40.0, max_hz=2000.0)) == 12
    assert len(wide) == 68                                # 多八度密铺
    freqs = [line.freq_hz for line in wide]
    assert freqs == sorted(freqs)                         # 升序
    assert len(set(freqs)) == len(freqs)                  # 八度边界不重复输出


@pytest.mark.parametrize("key", TEMPLATES)
def test_band_tiling_is_monotonic_and_in_band_for_every_template(key):
    tuning = get_template(key)
    lines = build_band_overlay_lines(tuning, min_hz=110.0, max_hz=440.0)
    assert lines, key
    assert all(110.0 - 1e-6 <= line.freq_hz <= 440.0 + 1e-6 for line in lines)
    freqs = [line.freq_hz for line in lines]
    assert freqs == sorted(freqs)
    assert len({round(f, 6) for f in freqs}) == len(freqs)
    # 度/音分自洽：音分单调不减且与频率同序（12 度以上模板必然多于 12TET 的密度）
    cents = [line.cents for line in lines]
    assert cents == sorted(cents)
    if tuning.degree_count > 12:
        assert len(lines) > 30


def test_band_tiling_degrades_to_empty_never_raises():
    tet = get_template("12tet")
    assert build_band_overlay_lines(None, min_hz=40.0, max_hz=2000.0) == []
    assert build_band_overlay_lines(tet, min_hz=0.0, max_hz=2000.0) == []
    assert build_band_overlay_lines(tet, min_hz=2000.0, max_hz=-5.0) == []
    assert build_band_overlay_lines(tet, min_hz="x", max_hz=2000.0) == []

    class _Broken:
        degrees = (0.0,)

        @staticmethod
        def degree_to_cents(degree):
            return 0.0

        @staticmethod
        def degree_to_freq(degree, ref=None):
            raise RuntimeError("boom")

    assert build_band_overlay_lines(_Broken(), min_hz=40.0, max_hz=2000.0) == []
    # min>max 视为区间颠倒（不抛、按正序出）
    swapped = build_band_overlay_lines(tet, min_hz=237.0, max_hz=208.0)
    assert [round(line.freq_hz, 2) for line in swapped] == [220.0, 233.08]


# ---------------------------------------------------------------------------
# ② 呈现层：律级线只在注入了律制时出现，并按像素密度抽稀
# ---------------------------------------------------------------------------


def test_tuning_lines_appear_only_after_tuning_injected(qapp):
    widget, _session_ = _widget(np.full(30, 440.0), np.full(30, 550.0))
    widget.grab()
    assert widget.paint_stats()["tuning_lines"] == 0      # ★ 未注入律制 ⇒ 不凭空造格线
    widget.set_tuning(get_template("12tet"))
    widget.grab()
    drawn = widget.paint_stats()["tuning_lines"]
    assert drawn == len(widget._tuning_band_lines()) > 0
    lo, hi = widget.freq_range()
    assert all(lo <= line.freq_hz <= hi for line in widget._tuning_band_lines())


def test_tuning_lines_thin_out_when_pixels_are_short(qapp):
    """宽频带 + 矮控件 ⇒ 音级线间距不足一像素时按整数倍抽稀（不得糊成一片）。"""
    widget, _ = _widget(np.linspace(50.0, 4000.0, 30), np.linspace(52.0, 4200.0, 30))
    widget.set_tuning(get_template("indian_22_shruti"))
    widget.resize(640, 96)                                  # 控件最小高仍 ~192 ⇒ 带更宽
    height = widget._data_rect().height()
    available = len(widget._tuning_band_lines())
    assert available > height, (available, height)          # 前置：线数多于可用像素行
    widget.grab()
    drawn = widget.paint_stats()["tuning_lines"]
    assert 0 < drawn < available, (drawn, available)         # ★ 抽稀生效
    assert drawn <= height + 1                               # 至多一行一线


def test_grid_line_positions_follow_log_frequency_map(qapp):
    """律级线 y 与曲线 y 同一映射（口径唯一·不由本件另立一套）。"""
    widget, _ = _widget(np.full(30, 440.0), np.full(30, 550.0))
    widget.set_tuning(get_template("just_major"))
    data = widget._data_rect()
    line = [item for item in widget._tuning_band_lines()
            if abs(item.freq_hz - 550.0) < 1e-6]
    assert line
    y = widget._freq_to_y(line[0].freq_hz, data)
    curve = widget.curve_points(widget.series()[1])
    assert abs(float(curve[:, 1].max()) - y) < 1.0        # 550 Hz 的曲线点与格线同高


# ---------------------------------------------------------------------------
# ③ 读数：音名±cent（裸 #<音级> 子串逐字保留）
# ---------------------------------------------------------------------------


def test_degree_pitch_label_uses_sv_pitch_label_shape(qapp):
    widget, _ = _widget(np.full(30, 440.0), np.full(30, 550.0))
    just = get_template("just_major")
    widget.set_tuning(just)
    assert widget._degree_pitch_label(2) == "C#5-14c"     # 5/4 比 12TET 大三度低 14 音分
    tet = get_template("12tet")
    widget.set_tuning(tet)
    assert widget._degree_pitch_label(0) == "A4"          # 零偏差 ⇒ 不带 ±cent
    assert widget._degree_pitch_label(-12) == "A3"
    widget.set_tuning(None)
    assert widget._degree_pitch_label(2) == ""            # 未注入律制 ⇒ 不臆造


def test_hover_readout_keeps_degree_and_adds_note_label(qapp):
    widget, _session_ = _widget(np.full(30, 440.0), np.full(30, 550.0))
    times = np.linspace(0.0, 1.5, 30)
    widget.btn_diff_stats.click()                          # 无律制：裸读数
    plain = widget.hover_readout_at(float(times[5]))
    assert "(C#5" not in plain and "#" not in plain
    widget.set_tuning(get_template("just_major"))
    widget.btn_diff_stats.click()
    readout = widget.hover_readout_at(float(times[5]))
    assert "#2" in readout                                 # ★ 既有钉面逐字保留
    assert "C#5-14c" in readout                            # 新增音名±cent
    widget.set_tuning(get_template("12tet"))
    widget.btn_diff_stats.click()
    readout = widget.hover_readout_at(float(times[5]))
    assert "#4" in readout and "C#5" in readout
    assert "-14c" not in readout                           # 平均律下无余差


def test_no_tuning_means_no_degree_and_no_note_label(qapp):
    """反证：律制未注入 ⇒ 既无 #音级 也无音名（不拿 12TET 冒充）。"""
    widget, _ = _widget(np.full(30, 440.0), np.full(30, 550.0))
    widget.btn_diff_stats.click()
    readout = widget.hover_readout_at(0.5)
    assert readout and "#" not in readout
    assert widget.tuning() is None
    assert widget._tuning_band_lines() == []


# ---------------------------------------------------------------------------
# ④ 边界：本里程碑不碰量化层（差异值仍为客观音分差）
# ---------------------------------------------------------------------------


def test_diff_values_stay_tuning_neutral_after_injection(qapp):
    just = get_template("just_major")
    widget, _ = _widget(np.full(30, 440.0), np.full(30, 550.0))
    widget.btn_diff_stats.click()
    before = widget.diff().tracks[0]
    mean_without = before.mean_delta_cent
    widget.set_tuning(just)
    after = widget.diff().tracks[0]
    assert after.mean_delta_cent == pytest.approx(mean_without)   # ★ 律制只改上下文不改差值
    assert np.array_equal(np.asarray(before.delta_cent), np.asarray(after.delta_cent))
    assert list(after.degrees)[:3] == [2, 2, 2]
    assert DIFF_BAR_MAX_ROWS == 4                                  # 未改差异条体积口径
