# SPDX-License-Identifier: GPL-3.0-only
"""T-1089 N-E：可解释指标（呈现层**只读**派生·量化层零改）。

根因（PI-T81 DIM1 1.6 / DIM3 3.4）：量化层给的 ``TrackDiff`` 只有 ``mean``/``mean_abs``/
``max`` 三个集中量，缺**分布**（p50/p95）、**方向**（系统偏差 vs 抖动）、**共同音**
（``degrees`` 只对非参考轨算 ⇒ 现字段拿不到基准侧音级）与**微分音余差**（相对最近半音
的偏离）。本件全部在呈现层派生：

- ``|Δ|`` p50/p95 与系统偏差比 = ``mean/mean_abs`` ⇒ 只读 ``TrackDiff.delta_cent`` 数组；
- 共同音级占比 ⇒ 参考轨音级由 ``tuning.freq_to_degree`` **自算**（``TrackDiff.times``
  即参考轨配对帧时间），八度归一后比对；
- 微分音余差 ⇒ 逐帧音级的 ``degree_to_cents`` 相对最近半音（``SEMITONE_CENTS``）的偏离中位数。

★ 边界：``pcp.py`` / ``compare_diff.py`` **零改**（只 import ⇒ 禁碰测只查 porcelain）；
指标只落既有 hint（不新建面板/控件·L-3）；CSV 表头结构逐字不动（``test_multitrack_diff.py:369``
钉 ``CSV_HEADER`` ⇒ 扩列即撞未授权档）。逐帧派生按 :data:`DIFF_ANALYSIS_MAX_FRAMES`
均匀抽样，避免主线程回填时吃全帧循环（M7 后台化的初衷）。
"""

from __future__ import annotations

import csv

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.analysis.tunings.templates import get_template
from acouscope.dsp import units
from acouscope.i18n import set_language, tr
from acouscope.ui.widgets.multitrack import compare_diff
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import (
    DIFF_ANALYSIS_MAX_FRAMES, ComparePresentWidget,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SR = 8000
_POINTS = 30


class _PitchStub:
    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _widget(f0s):
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": _SR, "channels": 1,
                                   "duration": 1.5},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, 1.5, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(_SR * 1.5)), _SR),
    )
    for index in range(len(f0s)):
        session.add_path(f"/tmp/t1089e{index}.wav", label=f"e{index}")
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.5, _POINTS)
    for track, f0 in zip(session.tracks(), f0s):
        cache.put(TrackResultCache.key(track.track_id, "pitch", None),
                  _PitchStub(times, np.asarray(f0, dtype=float)))
    widget = ComparePresentWidget(session, cache)
    widget.resize(640, 420)
    widget.refresh()
    widget.set_view_range(0.0, 1.5)
    widget.btn_diff_stats.click()                       # 既有按钮路径拿 diff（不依赖 N-A）
    assert widget.diff() is not None
    return widget, session


@pytest.fixture(autouse=True)
def _stable(qapp, monkeypatch):
    monkeypatch.setattr(units, "_reference_hz", 440.0)
    set_language("zh_CN")
    yield


# ---------------------------------------------------------------------------
# ① 分布与方向：由呈现层自算，数值可与 numpy 独立复核
# ---------------------------------------------------------------------------


def test_percentiles_and_bias_match_independent_numpy(qapp):
    rng = np.random.default_rng(20260923)
    offsets = rng.normal(30.0, 25.0, _POINTS)             # 有正有负的抖动 + 系统性偏高
    other = 440.0 * (2.0 ** (offsets / 1200.0))
    widget, _ = _widget([np.full(_POINTS, 440.0), other])
    delta = np.log2(other / 440.0) * 1200.0
    metrics = widget._diff_analysis_metrics(widget.diff())
    assert metrics["p50"] == pytest.approx(float(np.percentile(np.abs(delta), 50)))
    assert metrics["p95"] == pytest.approx(float(np.percentile(np.abs(delta), 95)))
    assert metrics["bias"] == pytest.approx(
        float(np.mean(delta)) / float(np.mean(np.abs(delta))), abs=1e-9
    )
    assert -1.0 <= metrics["bias"] <= 1.0
    text = widget.lbl_hint.text()
    assert f"{metrics['p50']:.1f}c" in text and f"{metrics['p95']:.1f}c" in text
    assert f"{metrics['bias']:+.2f}" in text               # ★ 算了也看得见


def test_bias_sign_separates_systematic_from_jitter(qapp):
    flat_low = 440.0 * (2.0 ** (-100.0 / 1200.0)) * np.ones(_POINTS)
    widget, _ = _widget([np.full(_POINTS, 440.0), flat_low])
    metrics = widget._diff_analysis_metrics(widget.diff())
    assert metrics["bias"] == pytest.approx(-1.0)         # 全负 ⇒ 纯系统偏差
    jitter = np.where(np.arange(_POINTS) % 2 == 0, 1.03, 0.97) * 440.0
    widget2, _ = _widget([np.full(_POINTS, 440.0), jitter])
    metrics2 = widget2._diff_analysis_metrics(widget2.diff())
    assert abs(metrics2["bias"]) < 0.2                     # 对称抖动 ⇒ 比值近零


# ---------------------------------------------------------------------------
# ② 共同音级占比（参考轨音级由呈现层自算·八度归一）
# ---------------------------------------------------------------------------


def test_shared_degree_ratio_uses_self_computed_reference_degrees(qapp):
    tet = get_template("12tet")
    octave, _ = _widget([np.full(_POINTS, 440.0), np.full(_POINTS, 880.0)])
    octave.set_tuning(tet)
    octave.btn_diff_stats.click()
    assert octave._diff_analysis_metrics(octave.diff())["shared"] == pytest.approx(1.0)
    # 反证（另一音级）：+400c ⇒ 第 4 音级 ≠ 参考轨第 0 音级
    tritone, _ = _widget([np.full(_POINTS, 440.0),
                          440.0 * (2.0 ** (400.0 / 1200.0)) * np.ones(_POINTS)])
    tritone.set_tuning(tet)
    tritone.btn_diff_stats.click()
    assert tritone._diff_analysis_metrics(tritone.diff())["shared"] == pytest.approx(0.0)
    assert "100.0%" in octave.lbl_hint.text()


def test_shared_and_remainder_need_a_tuning_otherwise_blank(qapp):
    """反证：未注入律制 ⇒ 共同音级/律制余差给 ``--``，分布与方向仍算得出。"""
    widget, _ = _widget([np.full(_POINTS, 440.0), np.full(_POINTS, 550.0)])
    assert widget.tuning() is None
    metrics = widget._diff_analysis_metrics(widget.diff())
    assert metrics["shared"] is None and metrics["remainder"] is None
    assert metrics["p50"] is not None and metrics["bias"] is not None
    text = widget.lbl_hint.text()
    assert tr("multitrack.compare.diff_analysis_stats").split("{")[0].strip() in text
    assert "--" in text


def test_micro_remainder_quantifies_equal_temperament_deviation(qapp):
    just, _ = _widget([np.full(_POINTS, 440.0), np.full(_POINTS, 550.0)])
    just.set_tuning(get_template("just_major"))
    just.btn_diff_stats.click()
    expected = abs(1200.0 * np.log2(1.25) - 400.0)         # 5/4 比平均律大三度低 ~13.7c
    assert just._micro_remainder_cents(just.diff()) == pytest.approx(expected, abs=1e-6)
    tet, _ = _widget([np.full(_POINTS, 440.0), np.full(_POINTS, 550.0)])
    tet.set_tuning(get_template("12tet"))
    tet.btn_diff_stats.click()
    assert tet._micro_remainder_cents(tet.diff()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# ③ 主线程成本上界：逐帧派生一律按抽样上限走
# ---------------------------------------------------------------------------


def test_frame_sampling_is_bounded_and_monotonic(qapp):
    widget, _ = _widget([np.full(_POINTS, 440.0), np.full(_POINTS, 550.0)])
    assert widget._sampled_frames(0) == []
    assert widget._sampled_frames(30) == list(range(30))   # 小样本不抽 ⇒ 数值精确可复核
    picked = widget._sampled_frames(5000)
    assert len(picked) == DIFF_ANALYSIS_MAX_FRAMES
    assert picked == sorted(set(picked))
    assert picked[0] == 0 and picked[-1] == 4999


# ---------------------------------------------------------------------------
# ④ 边界：量化层与 CSV 出口结构零改（扩列即撞未授权测）
# ---------------------------------------------------------------------------


def test_csv_export_face_unchanged_by_new_metrics(qapp, tmp_path):
    widget, _ = _widget([np.full(_POINTS, 440.0), np.full(_POINTS, 550.0)])
    widget.set_tuning(get_template("just_major"))
    widget.btn_diff_stats.click()
    target = tmp_path / "diff.csv"
    written = widget.export_diff_csv(target)
    assert written == str(target)
    with open(target, encoding="utf-8", newline="") as handle:
        table = list(csv.reader(handle))
    assert tuple(table[0]) == compare_diff.CSV_HEADER      # ★ 表头逐字六列
    assert len(table) - 1 == sum(track.pairs for track in widget.diff().tracks)
    assert float(table[1][3]) == pytest.approx(1200.0 * np.log2(1.25), abs=1e-6)


def test_metrics_do_not_alter_quantified_values(qapp):
    """派生指标只读：注入律制前后 ``delta_cent`` / ``over_threshold`` 逐字不变。"""
    widget, _ = _widget([np.full(_POINTS, 440.0),
                         440.0 * (2.0 ** (80.0 / 1200.0)) * np.ones(_POINTS)])
    before = widget.diff().tracks[0]
    delta_before = np.asarray(before.delta_cent).copy()
    over_before = np.asarray(before.over_threshold).copy()
    mean_before = before.mean_delta_cent
    widget.set_tuning(get_template("indian_22_shruti"))
    after = widget.diff().tracks[0]
    assert np.array_equal(np.asarray(after.delta_cent), delta_before)
    assert np.array_equal(np.asarray(after.over_threshold), over_before)
    assert after.mean_delta_cent == pytest.approx(mean_before)


def test_pinned_hint_sections_survive_metric_growth(qapp):
    """既有钉面（汇总首段 / 阈值注记 / 律制名末段）不因指标扩写而移位。"""
    widget, _ = _widget([np.full(_POINTS, 440.0), np.full(_POINTS, 550.0)])
    just = get_template("just_major")
    widget.set_tuning(just)
    widget.btn_diff_stats.click()
    text = widget.lbl_hint.text()
    assert text.startswith(tr("multitrack.compare.diff_summary").split("{")[0].strip())
    assert tr("multitrack.compare.diff_threshold_note") in text
    assert just.name in text
    assert text.rstrip().endswith(just.name)
