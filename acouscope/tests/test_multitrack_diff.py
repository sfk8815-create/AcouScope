# SPDX-License-Identifier: GPL-3.0-only
"""T-1005 多轨差异自动测量回归（全离屏：量化层 + 呈现接线 + CSV 出口）。

数值口径声明：本文全部 Δcent / dB 断言均为**构造数值容差验证**（合成序列逐帧已知），
不构成任何测量精度或标准的「符合/达标」结论；阈值是**报警线**，非精度承诺。
不构造主窗口显示调用（离屏 grab 触发绘制）。
"""

import csv
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.i18n import get_language, set_language, tr
from acouscope.analysis.tunings.templates import get_template
from acouscope.ui.widgets.multitrack import compare_diff
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import (
    DIFF_BAR_GAP, DIFF_BAR_ROW_H, ComparePresentWidget, TrackSeries,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

NEW_I18N_KEYS = (
    "multitrack.compare.diff_stats",
    "multitrack.compare.diff_tip",
    "multitrack.compare.diff_unit_cents",
    "multitrack.compare.diff_unit_tip",
    "multitrack.compare.diff_threshold_note",
    "multitrack.compare.diff_summary",
    "multitrack.compare.diff_no_pair",
    "multitrack.compare.diff_pairing_note",
    "multitrack.compare.diff_export",
    "multitrack.compare.diff_export_tip",
    "multitrack.compare.diff_export_title",
    "multitrack.compare.diff_export_done",
    "multitrack.compare.diff_export_failed",
    "multitrack.compare.diff_export_empty",
)

REF = "ref-track"
OTH = "other-track"


class _PitchStub:
    """逐轨音高结果桩（呈现层/量化层只消费 times / f0_hz）。"""

    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _series(track_id, times, f0, label=None, color_index=0):
    return TrackSeries(
        track_id=track_id, label=label or track_id, color_index=color_index,
        times=np.asarray(times, dtype=float), f0_hz=np.asarray(f0, dtype=float),
    )


def _cents_shift(f0, cents):
    """把频率整体偏移 cents（构造用：Δcent 即偏移量）。"""
    return np.asarray(f0, dtype=float) * (2.0 ** (float(cents) / 1200.0))


def _pair(offset_cents=50.0, frames=30, span=1.0, f0=440.0):
    times = np.linspace(0.0, span, frames)
    return (_series(REF, times, np.full(frames, f0)),
            _series(OTH, times, np.full(frames, _cents_shift(f0, offset_cents))))


def _session(n=2, duration=2.0, sr=8000) -> MultitrackSession:
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
        session.add_path(f"/tmp/diff{index}.wav", label=f"track{index}")
    return session


def _widget(session=None, cache=None, **kwargs):
    widget = ComparePresentWidget(session, cache, **kwargs)
    widget.resize(480, 260)
    return widget


def _seed(cache, track_id, *, times, f0, kind="pitch"):
    result = _PitchStub(times, f0)
    cache.put(TrackResultCache.key(track_id, kind, None), result)
    return result


def _two_track_cache(session, offset_cents=50.0, kind="pitch"):
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.5, 30)
    _seed(cache, session.tracks()[0].track_id, times=times,
          f0=np.full(30, 440.0), kind=kind)
    _seed(cache, session.tracks()[1].track_id, times=times,
          f0=np.full(30, _cents_shift(440.0, offset_cents)), kind=kind)
    return cache


# ----------------------------------------------------------------------
# 量化层：Δcent / ΔHz / 超阈 / 防御 / 帧率交集
# ----------------------------------------------------------------------


def test_delta_cents_of_constructed_shift_is_within_numeric_tolerance():
    """构造 +50c 偏移 → Δcent 数值容差（非任何标准符合性结论）。"""
    ref, other = _pair(50.0)
    result = compare_diff.compare_track(ref, other)
    assert result.pairs == 30
    assert result.mean_delta_cent == pytest.approx(50.0, abs=1e-6)
    assert result.mean_abs_delta_cent == pytest.approx(50.0, abs=1e-6)
    assert result.delta_hz[0] == pytest.approx(440.0 * (2 ** (50 / 1200)) - 440.0,
                                              abs=1e-6)


def test_delta_cents_is_independent_of_a4_reference_setting():
    """同一 A4 参考分别换算后相减 → 差值抵消（口径与律制/参考无关）。"""
    from acouscope.dsp import units

    ref, other = _pair(50.0)
    original = units.get_reference_hz()
    try:
        units.set_reference_hz(440.0)
        base = compare_diff.compare_track(ref, other).mean_delta_cent
        assert units.set_reference_hz(442.0) is True
        shifted = compare_diff.compare_track(ref, other).mean_delta_cent
    finally:
        units.set_reference_hz(original)
    assert shifted == pytest.approx(base, abs=1e-9)


def test_compare_track_skips_nan_zero_and_negative_frames():
    """unvoiced / 0 Hz / NaN 帧跳过：配对只在两侧都有声帧上进行（不产错误数值）。"""
    times = np.array([0.0, 0.01, 0.02, 0.03, 0.04])
    ref = _series(REF, times, [440.0, np.nan, 0.0, 441.0, 442.0])
    other = _series(OTH, times, [440.0, 441.0, 0.0, np.nan, 442.0])
    result = compare_diff.compare_track(ref, other)
    # 参考有声 {0.00, 0.03, 0.04}；比对轨有声 {0.00, 0.01, 0.04} → 共同可比 = 2
    assert result.pairs == 2
    assert result.skipped_unvoiced_ref == 2
    assert result.skipped_unvoiced_other == 2
    assert result.dropped_frames == 1
    assert np.all(np.isfinite(result.delta_cent))
    assert np.all(result.delta_hz == 0.0)


def test_compare_track_with_negative_and_zero_only_frames_yields_no_pairs():
    """两侧均无可比有声帧（0 Hz / 负值 / NaN）→ 零配对且不产出任何数值。"""
    times = np.array([0.0, 0.01])
    ref = _series(REF, times, [0.0, np.nan])
    other = _series(OTH, times, [-1.0, 0.0])
    result = compare_diff.compare_track(ref, other)
    assert result.pairs == 0
    assert result.over_ratio is None
    assert result.mean_delta_cent is None


def test_over_threshold_ratio_reacts_to_configurable_alarm_threshold():
    """超阈 = |Δcent| > 阈值（构造 +60c；阈值可配置，非精度承诺）。"""
    ref, other = _pair(60.0)
    strict = compare_diff.compare_track(ref, other, threshold_cents=50.0)
    loose = compare_diff.compare_track(ref, other, threshold_cents=100.0)
    assert strict.over_count == 30
    assert strict.over_ratio == pytest.approx(1.0, abs=1e-9)
    assert loose.over_count == 0
    assert loose.over_ratio == pytest.approx(0.0, abs=1e-9)
    assert strict.threshold_cents == 50.0


def test_over_threshold_is_strict_so_exact_boundary_is_not_flagged():
    """恰在阈值上不计入（构造 50c / 阈值 50）——避免浮点边界翻转。"""
    ref, other = _pair(50.0)
    result = compare_diff.compare_track(ref, other, threshold_cents=50.0)
    assert result.over_count == 0
    assert result.mean_abs_delta_cent == pytest.approx(50.0, abs=1e-6)
    mask = compare_diff.over_threshold_mask([50.0, 50.001, 49.999], 50.0)
    assert list(mask) == [False, True, False]


def test_threshold_normalization_falls_back_outside_configurable_range():
    assert compare_diff.normalize_threshold(80.0) == 80.0
    assert compare_diff.normalize_threshold(5.0) == compare_diff.DEFAULT_THRESHOLD_CENTS
    assert compare_diff.normalize_threshold(500.0) == compare_diff.DEFAULT_THRESHOLD_CENTS
    assert compare_diff.normalize_threshold("x") == compare_diff.DEFAULT_THRESHOLD_CENTS
    assert compare_diff.normalize_threshold(np.nan) == compare_diff.DEFAULT_THRESHOLD_CENTS


def test_threshold_constants_agree_with_settings_clamp():
    """阈值入 Settings（定案 H′）：默认 50、范围 10–200，两处口径必须一致。"""
    from acouscope.utils.config import Settings, get_config_dir

    assert (compare_diff.THRESHOLD_MIN_CENTS, compare_diff.THRESHOLD_MAX_CENTS,
            compare_diff.DEFAULT_THRESHOLD_CENTS) == (10.0, 200.0, 50.0)
    assert Settings().multitrack_diff_threshold_cents == 50.0

    config_dir = Path(get_config_dir())
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / "settings.json"
    try:
        target.write_text('{"multitrack_diff_threshold_cents": 5.0}', encoding="utf-8")
        assert Settings.load().multitrack_diff_threshold_cents == 50.0
        target.write_text('{"multitrack_diff_threshold_cents": 120.0}', encoding="utf-8")
        assert Settings.load().multitrack_diff_threshold_cents == 120.0
        target.write_text('{"multitrack_diff_threshold_cents": "oops"}', encoding="utf-8")
        assert Settings.load().multitrack_diff_threshold_cents == 50.0
    finally:
        target.unlink(missing_ok=True)


def test_pair_frames_intersection_branch_reports_unequal_frame_rates():
    """定案 I′：帧率不一致取交集时间轴 + 最近帧配对（不插值、不升采样）。"""
    ref_times = np.arange(0.0, 1.0 + 1e-9, 0.01)
    other_times = np.arange(0.0, 1.0 + 1e-9, 0.02)
    pairing = compare_diff.pair_frames(ref_times, other_times)
    assert pairing["mode"] == compare_diff.PAIR_MODE_INTERSECTION
    assert pairing["frame_rates_equal"] is False
    assert pairing["hop_ref_s"] == pytest.approx(0.01, abs=1e-6)
    assert pairing["hop_other_s"] == pytest.approx(0.02, abs=1e-6)
    assert pairing["tolerance_s"] == pytest.approx(0.01, abs=1e-6)
    assert pairing["overlap_start"] == pytest.approx(0.0, abs=1e-9)
    assert pairing["overlap_end"] == pytest.approx(1.0, abs=1e-9)
    assert pairing["pairs"] == ref_times.size
    # 配对点必须落在较粗轨的真实帧上（无插值产物）
    ratios = np.asarray(pairing["other_times"], dtype=float) / 0.02
    assert np.allclose(ratios, np.round(ratios), atol=1e-6)


def test_pair_frames_handles_empty_and_disjoint_inputs():
    empty = np.zeros(0, dtype=float)
    assert compare_diff.pair_frames(empty, empty)["pairs"] == 0
    assert compare_diff.pair_frames(np.arange(0.0, 1.0, 0.1), empty)["pairs"] == 0
    disjoint = compare_diff.pair_frames(np.arange(0.0, 1.0, 0.1),
                                        np.arange(5.0, 6.0, 0.1))
    assert disjoint["pairs"] == 0
    assert disjoint["overlap_start"] is None


def test_equal_frame_rate_pairing_marks_rates_equal():
    times = np.linspace(0.0, 1.0, 40)
    pairing = compare_diff.pair_frames(times, times)
    assert pairing["frame_rates_equal"] is True
    assert pairing["pairs"] == times.size
    assert pairing["dropped_frames"] == 0


def test_overall_rms_db_and_diff_from_constructed_amplitudes():
    """构造正弦幅度比 2:1 → 电平差约 -6 dB（数值容差验证）。"""
    sr = 8000
    t = np.arange(0, sr, dtype=float) / sr
    loud = 0.5 * np.sin(2 * np.pi * 220.0 * t)
    quiet = 0.25 * np.sin(2 * np.pi * 220.0 * t)
    diff = compare_diff.rms_diff_db(loud, quiet, sr, window_ms=50.0)
    assert diff == pytest.approx(-6.02, abs=0.6)
    assert compare_diff.overall_rms_db(loud, sr, window_ms=50.0) is not None


def test_overall_rms_db_returns_none_when_unmeasurable():
    assert compare_diff.overall_rms_db(None, 8000) is None
    assert compare_diff.overall_rms_db(np.zeros(10), 0) is None
    assert compare_diff.overall_rms_db(np.zeros(10), 8000) is None
    assert compare_diff.rms_diff_db(None, np.zeros(100), 8000) is None


def test_build_diff_summary_defaults_reference_to_first_series():
    ref, other = _pair(30.0)
    third = _series("third", np.linspace(0.0, 1.0, 30),
                    _cents_shift(np.full(30, 440.0), 20.0), label="track-third")
    summary = compare_diff.build_diff_summary([ref, other, third])
    assert summary.reference_id == REF
    assert summary.reference_label == REF
    assert [track.track_id for track in summary.tracks] == [OTH, "third"]
    assert summary.threshold_cents == 50.0
    stats = summary.consistency()
    assert stats["tracks_total"] == 2
    assert stats["compared_tracks"] == 2
    assert summary.tracks[0].over_count == 0      # 30c 在 50c 报警线内
    assert summary.tracks[1].over_count == 0      # 20c 在报警线内
    assert stats["tracks_with_any_over"] == 0
    assert stats["all_within_alarm_threshold"] is True
    assert stats["max_over_ratio"] == pytest.approx(0.0, abs=1e-9)


def test_build_diff_summary_honours_explicit_reference():
    ref, other = _pair(50.0)
    third = _series("third", np.linspace(0.0, 1.0, 30),
                    _cents_shift(np.full(30, 660.0), 900.0), label="track-third")
    summary = compare_diff.build_diff_summary([ref, other, third],
                                              reference_id="third")
    assert summary.reference_id == "third"
    assert sorted(track.track_id for track in summary.tracks) == sorted([REF, OTH])


def test_build_diff_summary_reports_rms_and_duration_when_provided():
    ref, other = _pair(50.0)
    sr = 8000
    audio = np.sin(2 * np.pi * 220.0 * np.arange(sr, dtype=float) / sr)
    summary = compare_diff.build_diff_summary(
        [ref, other],
        rms_provider=lambda track_id: (audio * (0.5 if track_id == REF else 0.25), sr),
        duration_provider=lambda track_id: 2.0 if track_id == REF else 3.0,
    )
    entry = summary.tracks[0]
    assert entry.rms_diff_db == pytest.approx(-6.02, abs=0.6)
    assert entry.duration_s == pytest.approx(3.0)
    assert entry.duration_diff_s == pytest.approx(1.0)


def test_consistency_summary_empty_state_is_explicit():
    summary = compare_diff.build_diff_summary([])
    stats = summary.consistency()
    assert summary.reference_id is None
    assert summary.has_data() is False
    assert stats["compared_tracks"] == 0
    assert stats["max_over_ratio"] is None
    assert stats["all_within_alarm_threshold"] is None


def test_no_comparable_frames_yields_empty_entry():
    ref = _series(REF, [0.0, 0.5, 1.0], [440.0, 440.0, 440.0])
    other = _series(OTH, [5.0, 5.5, 6.0], [440.0, 440.0, 440.0])
    result = compare_diff.compare_track(ref, other)
    assert result.pairs == 0
    assert result.over_ratio is None
    assert np.asarray(result.delta_cent).size == 0
    summary = compare_diff.build_diff_summary([ref, other])
    assert summary.has_data() is False


# ----------------------------------------------------------------------
# CSV 出口（定案 J′：csv.writer + repr）
# ----------------------------------------------------------------------


def test_summary_pairing_uses_track_with_most_pairs():
    """汇总帧率口径取「可比帧最多的轨」（混合帧率时不得取到零配对轨）。"""
    dense_times = np.arange(0.0, 1.0 + 1e-9, 0.02)
    ref = _series(REF, np.arange(0.0, 1.0 + 1e-9, 0.01),
                  np.full(np.arange(0.0, 1.0 + 1e-9, 0.01).size, 440.0))
    dense = _series(OTH, dense_times, np.full(dense_times.size, 440.0))
    sparse = _series("sparse", np.array([0.0, 0.5]), np.array([440.0, 440.0]))
    summary = compare_diff.build_diff_summary([ref, dense, sparse])
    assert {track.track_id: track.pairs for track in summary.tracks}[OTH] > 0
    assert summary.pairing["pairs"] == max(track.pairs for track in summary.tracks)
    assert summary.pairing["frame_rates_equal"] is False
    assert summary.pairing["unit"] == compare_diff.DEFAULT_UNIT


def test_write_diff_csv_header_and_rows(tmp_path):
    ref, other = _pair(60.0)
    summary = compare_diff.build_diff_summary([ref, other], threshold_cents=50.0)
    target = tmp_path / "diff.csv"
    rows = compare_diff.write_diff_csv(target, summary)
    assert target.exists()
    assert rows == sum(track.pairs for track in summary.tracks) == 30

    with open(target, encoding="utf-8", newline="") as handle:
        table = list(csv.reader(handle))
    assert tuple(table[0]) == compare_diff.CSV_HEADER
    assert tuple(table[0]) == ("track", "time_s", "delta_hz", "delta_cent",
                               "over_threshold", "reference_track")
    first = table[1]
    assert len(first) == len(compare_diff.CSV_HEADER)
    assert first[0] == OTH
    assert float(first[1]) == pytest.approx(0.0, abs=1e-9)
    assert float(first[3]) == pytest.approx(60.0, abs=1e-6)
    assert first[4] == "1"
    assert first[5] == REF


def test_csv_column_name_mapping_covers_header():
    assert set(compare_diff.CSV_COLUMN_NAMES) == set(compare_diff.CSV_HEADER)
    assert all(compare_diff.CSV_COLUMN_NAMES[key] for key in compare_diff.CSV_HEADER)


def test_write_diff_csv_without_pairs_writes_header_only(tmp_path):
    target = tmp_path / "empty.csv"
    summary = compare_diff.build_diff_summary([])
    assert compare_diff.write_diff_csv(target, summary) == 0
    assert target.read_text(encoding="utf-8").strip() == ",".join(
        compare_diff.CSV_HEADER)


# ----------------------------------------------------------------------
# 呈现接线：预留槽 / 差异条 / 悬停读数 / 单位切换 / 导出
# ----------------------------------------------------------------------


def test_diff_stats_slot_requires_two_tracks_and_non_reference_result(qapp):
    alone = _widget(_session(1), None)
    alone.refresh()
    assert alone.diff_available() is False
    assert alone.btn_diff_stats.isEnabled() is False

    session = _session(2)
    without = _widget(session, TrackResultCache())
    without.refresh()
    assert without.diff_available() is False

    partial = TrackResultCache()
    times = np.linspace(0.0, 1.0, 10)
    _seed(partial, session.tracks()[0].track_id, times=times, f0=np.full(10, 440.0))
    only_reference = _widget(session, partial)
    only_reference.refresh()
    assert only_reference.diff_available() is False

    full = _two_track_cache(session)
    widget = _widget(session, full)
    widget.refresh()
    assert widget.diff_available() is True
    assert widget.btn_diff_stats.isEnabled() is True
    assert widget.btn_diff_csv.isEnabled() is False        # 未计算前不可导出


def test_diff_stats_button_computes_summary_and_wires_export(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    widget.btn_diff_stats.click()
    summary = widget.diff()
    assert summary is not None
    assert [track.track_id for track in summary.tracks] == [session.tracks()[1].track_id]
    assert summary.reference_id == session.tracks()[0].track_id
    assert summary.tracks[0].mean_delta_cent == pytest.approx(50.0, abs=1e-6)
    assert widget.btn_diff_csv.isEnabled() is True
    assert widget.lbl_hint.isHidden() is False
    text = widget.lbl_hint.text()
    assert tr("multitrack.compare.diff_threshold_note") in text
    assert "50" in text


def test_threshold_from_settings_is_used_by_widget(qapp, monkeypatch):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session, offset_cents=60.0))
    widget.refresh()
    monkeypatch.setattr(compare_diff, "settings_threshold", lambda: 80.0)
    widget.btn_diff_stats.click()
    assert widget.diff_threshold_cents() == 80.0
    assert widget.diff().tracks[0].over_count == 0        # 60c < 80c 报警线


def test_hover_readout_reports_constructed_delta_and_unit_switch(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    assert widget.hover_readout_at(0.5) == ""             # 未计算 → 空
    widget.set_view_range(0.0, 1.5)
    widget.btn_diff_stats.click()
    readout = widget.hover_readout_at(0.5)
    assert "t=0.500s" in readout
    assert session.tracks()[1].label in readout
    assert "50.0 cents" in readout
    widget.set_diff_unit(compare_diff.UNIT_HZ)
    assert "Hz" in widget.hover_readout_at(0.5)
    widget.set_diff_unit("bogus")                          # 非法单位忽略
    assert widget.diff_unit() == compare_diff.UNIT_HZ
    widget.set_diff_unit(compare_diff.UNIT_CENTS)
    assert widget.chk_diff_cents.isChecked() is True


def test_hover_readout_without_pair_marker(qapp):
    session = _session(2)
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.0, 10)
    _seed(cache, session.tracks()[0].track_id, times=times, f0=np.full(10, 440.0))
    _seed(cache, session.tracks()[1].track_id, times=times + 5.0,
          f0=np.full(10, 440.0))
    widget = _widget(session, cache)
    widget.refresh()
    widget.set_view_range(0.0, 1.0)
    widget.btn_diff_stats.click()
    assert tr("multitrack.compare.diff_no_pair") in widget.hover_readout_at(0.5)
    assert widget.btn_diff_csv.isEnabled() is False


def test_diff_bar_geometry_is_token_derived_and_reserves_space(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    before = widget._plot_rect()
    assert widget.diff_bar_geometry()["rows"] == 0
    widget.btn_diff_stats.click()
    after = widget._plot_rect()
    geometry = widget.diff_bar_geometry()
    assert geometry["rows"] == 1
    assert geometry["row_height"] == DIFF_BAR_ROW_H
    assert geometry["height"] == pytest.approx(DIFF_BAR_ROW_H, abs=1e-6)
    assert before.height() - after.height() == pytest.approx(
        DIFF_BAR_ROW_H + DIFF_BAR_GAP, abs=1e-6)
    assert after.bottom() <= before.bottom()


def test_diff_layer_is_painted_and_counted(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session, offset_cents=80.0))
    widget.refresh()
    widget.set_view_range(0.0, 1.5)
    widget.grab()
    assert widget.paint_stats()["diff_rows"] == 0
    widget.btn_diff_stats.click()
    widget.grab()
    stats = widget.paint_stats()
    assert stats["diff_rows"] == 1
    assert stats["diff_over_segments"] >= 1


def test_export_diff_csv_uses_path_and_reports_via_toast(qapp, tmp_path):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    messages = []
    widget._toast = lambda message, **kwargs: messages.append((message, kwargs))
    target = tmp_path / "export_diff"
    result = widget.export_diff_csv(target)
    assert result == f"{target}.csv"
    assert Path(result).exists()
    assert messages and messages[-1][1]["level"] == "success"
    header = Path(result).read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(compare_diff.CSV_HEADER)


def test_export_diff_csv_without_data_toasts_warning(qapp, tmp_path):
    widget = _widget(_session(2), TrackResultCache())
    widget.refresh()
    messages = []
    widget._toast = lambda message, **kwargs: messages.append((message, kwargs))
    assert widget.export_diff_csv(tmp_path / "none.csv") is None
    assert messages[0][0] == tr("multitrack.compare.diff_export_empty")
    assert messages[0][1]["level"] == "warning"


def test_reference_change_and_refresh_invalidate_diff(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    widget.btn_diff_stats.click()
    assert widget.diff() is not None
    widget.set_reference(session.tracks()[1].track_id)
    assert widget.diff() is None
    assert widget.btn_diff_csv.isEnabled() is False
    widget.btn_diff_stats.click()
    assert widget.diff() is not None
    widget.refresh()
    assert widget.diff() is None


def test_grid_mode_panels_unchanged_by_diff_layer(qapp):
    """零回归：差异层不改变多图布局数（布局数 = 轨数）。"""
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    widget.set_mode("grid")
    assert len(widget.panels()) == 2
    widget.btn_diff_stats.click()
    assert len(widget.panels()) == 2
    widget.grab()
    assert widget.paint_stats()["panels"] == 2


def test_diff_unit_default_is_cents_and_checkbox_is_wired(qapp):
    widget = _widget(_session(2), None)
    assert widget.diff_unit() == compare_diff.UNIT_CENTS
    assert compare_diff.DEFAULT_UNIT == compare_diff.UNIT_CENTS     # 12TET 先行
    assert widget.chk_diff_cents.isChecked() is True
    widget.chk_diff_cents.setChecked(False)
    assert widget.diff_unit() == compare_diff.UNIT_HZ
    assert widget.chk_diff_cents.text() == tr("multitrack.compare.diff_unit_cents")


def test_i18n_new_diff_keys_available_in_three_languages(qapp):
    original = get_language()
    try:
        for lang in ("en_US", "zh_CN", "zh_TW"):
            set_language(lang)
            for key in NEW_I18N_KEYS:
                assert tr(key) != key, f"{key} missing for {lang}"
    finally:
        set_language(original)


def test_quantification_layer_has_no_third_party_dependency():
    source = Path(compare_diff.__file__).read_text(encoding="utf-8")
    for forbidden in ("scipy", "sklearn", "torch", "tensorflow"):
        assert forbidden not in source
    assert "QDialog" not in source
    assert "MainWindow" not in source


def test_present_source_has_no_hardcoded_hex_or_px_literals():
    """禁硬编码 hex/px：呈现层源码零字面色值与字面像素（差异条色走语义令牌）。"""
    import re

    from acouscope.ui.widgets.multitrack import compare_present

    source = Path(compare_present.__file__).read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source)
    assert not re.search(r"\b\d+(?:\.\d+)?px\b", source)
    assert "TOKENS[\"semantic\"]" in source


# ----------------------------------------------------------------------
# T-1034a 轮 A：可选 tuning —— 音级归属（仅量化层，未接线）
# ----------------------------------------------------------------------


def test_optional_tuning_absent_keeps_existing_output_identical():
    """不传 tuning ⇒ 新字段恒为 None，既有字段值级逐字不变（repr/asdict + 逐字段）。"""
    from dataclasses import fields

    ref, other = _pair(50.0)
    result = compare_diff.compare_track(ref, other)
    assert result.degrees is None
    assert "degrees" not in repr(result)                       # repr=False
    assert asdict(result)["degrees"] is None                   # 值级：恒为 None
    # compare=False 之外再强证值级：传与不传 tuning，既有字段逐字段逐字同
    tuned = compare_diff.compare_track(ref, other, tuning=get_template("12tet"))
    assert tuned.degrees is not None
    for spec in fields(result):
        if spec.name == "degrees":
            continue
        assert np.array_equal(getattr(tuned, spec.name), getattr(result, spec.name))
    # 唯一 app 入口不传 tuning 时也不产音级（链上不可达 ⇒ 无物入缓存）
    summary = compare_diff.build_diff_summary([ref, other])
    assert all(track.degrees is None for track in summary.tracks)


def test_tuning_given_attaches_verifiable_degree_per_frame():
    """传 12TET ⇒ 逐帧附音级归属且取值可校验（A4=440 → 0 度；+300c → 第 3 度）。"""
    tuning = get_template("12tet")
    ref, other = _pair(300.0)
    result = compare_diff.compare_track(ref, other, tuning=tuning)
    assert result.degrees is not None
    assert result.degrees.shape == (result.pairs,)
    assert set(np.unique(result.degrees).tolist()) == {3}
    assert tuning.freq_to_degree(float(other.f0_hz[0])) == 3
    # 唯一 app 入口转发：build_diff_summary 的逐轨结果同样带音级
    summary = compare_diff.build_diff_summary([ref, other], tuning=tuning)
    assert np.all(summary.tracks[0].degrees == 3)


def test_non_equal_temperament_degree_is_not_snapped_to_nearest_semitone():
    """纯律大调：+386.31c（5/4）→ 第 2 音级；同一输入在 12TET 下为第 4 音级 ⇒ 未被吸附。"""
    just_cents = 1200.0 * np.log2(1.25)                        # 440 * 5/4 = 550 Hz
    ref, other = _pair(just_cents, frames=10)
    result = compare_diff.compare_track(ref, other, tuning=get_template("just_major"))
    assert result.degrees[0] == 2
    assert result.mean_delta_cent == pytest.approx(just_cents, abs=1e-6)
    equal = compare_diff.compare_track(ref, other, tuning=get_template("12tet"))
    assert equal.degrees[0] == 4
    assert equal.degrees[0] != result.degrees[0]
