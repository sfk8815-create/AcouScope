# SPDX-License-Identifier: GPL-3.0-only
"""段长分布与下限敏感性（W-12）测试。SEGMENT_LENGTH_TEST_V1

合成音只验链路与算式，不入交付件（交付件由真实四例音频重算）。

覆盖：
① ``length_stats``：段数／中位／四分位／短段占比，边界 0.150 s 计为「不短」；
② ``scan_lower_bound``：下限升高 ⇒ 短段占比单调不增；漂移 = (max − min) × 100；
③ ``pairs_within_band``：在给定网格上能/不能找到落在区间内的两档配对；
④ ``segments_for``／``durations_for``：与 ``NoteHMM`` 同源（改下限只改分段，不改帧轨）；
⑤ CSV 长表：一例 × 一档一行，基准档恰标一次。
"""

import pytest

numpy = pytest.importorskip("numpy")


def _tone_with_gaps(path, sr=8000):
    """3 s：有声 0.6 s → 静 0.3 s → 有声 0.5 s → 静 0.2 s → 有声 0.6 s。"""
    from acouscope.audio import AudioIO

    total = 3.0
    t = numpy.arange(int(sr * total)) / float(sr)
    env = numpy.zeros_like(t)
    for a, b in ((0.2, 0.8), (1.1, 1.6), (1.8, 2.4)):
        env[(t >= a) & (t < b)] = 1.0
    sig = 0.35 * env * numpy.sin(2.0 * numpy.pi * 220.0 * t)
    AudioIO().save(sig.astype(numpy.float32), sr, str(path))
    return path


def test_length_stats_math_and_boundary():
    from acouscope.analysis.segment_length import length_stats

    stats = length_stats([0.10, 0.20, 0.30, 0.40])
    assert stats["n_segments"] == 4
    assert stats["median_s"] == pytest.approx(0.25)
    assert stats["n_short"] == 1
    assert stats["short_share"] == pytest.approx(0.25)
    # 边界：恰为 0.150 s 计为「不短」
    edge = length_stats([0.149, 0.150, 0.151])
    assert edge["n_short"] == 1
    assert length_stats([])["short_share"] is None


def test_scan_monotone_and_drift(tmp_path):
    from acouscope.analysis.segment_length import frame_tracks, scan_lower_bound

    path = _tone_with_gaps(tmp_path / "gaps.wav")
    tracks = frame_tracks(path, window_s=3.0, min_window_s=1.0)
    scan = scan_lower_bound(tracks, min_dur_values=(0.05, 0.08, 0.12))
    shares = [scan["levels"][k]["short_share"] for k in ("0.05", "0.08", "0.12")]
    assert all(s is not None for s in shares)
    assert shares[0] >= shares[1] >= shares[2], "下限升高，短段占比不应上升"
    assert scan["drift_pp"] == pytest.approx(
        round((max(shares) - min(shares)) * 100.0, 2), abs=0.02
    )
    assert scan["base_share"] == scan["levels"]["0.08"]["short_share"]


def test_segments_for_shares_frame_track(tmp_path):
    from acouscope.analysis.segment_length import (
        durations_for,
        frame_tracks,
        segments_for,
    )

    path = _tone_with_gaps(tmp_path / "gaps2.wav")
    tracks = frame_tracks(path, window_s=3.0, min_window_s=1.0)
    loose = segments_for(tracks, min_dur_s=0.05)
    strict = segments_for(tracks, min_dur_s=0.30)
    assert len(loose) >= len(strict)
    assert durations_for(tracks, min_dur_s=0.05) == [s["duration_s"] for s in loose]
    for seg in strict:
        assert seg["duration_s"] >= 0.30 - 1e-9
    # 段 id 为三位小数起讫，可回查
    assert all("-" in seg["segment_id"] for seg in loose)


def test_pairs_within_band_finds_and_rejects():
    from acouscope.analysis.segment_length import pairs_within_band

    levels = {
        "a": {
            "0.02": {"short_share": 0.40},
            "0.08": {"short_share": 0.20},
            "0.14": {"short_share": 0.05},
        },
        "b": {
            "0.02": {"short_share": 0.30},
            "0.08": {"short_share": 0.17},
            "0.14": {"short_share": 0.10},
        },
    }
    found = pairs_within_band(levels, lo_pp=10.0, hi_pp=20.0)
    pairs = [tuple(item["min_dur_pair"]) for item in found["pairs"]]
    assert (0.02, 0.08) in pairs          # 20 / 13 pp
    assert (0.02, 0.14) not in pairs      # 35 pp 越界
    assert found["n_pairs"] == len(found["pairs"])
    empty = pairs_within_band(levels, lo_pp=90.0, hi_pp=95.0)
    assert empty["n_pairs"] == 0


def test_csv_rows_one_per_case_and_level():
    from acouscope.analysis.segment_length import (
        build_segment_length_payload,
        segment_length_csv_rows,
    )

    levels = {
        "0.04": {"n_segments": 12, "median_s": 0.2, "p25_s": 0.1, "p75_s": 0.3,
                 "n_short": 5, "short_share": 0.4},
        "0.08": {"n_segments": 10, "median_s": 0.25, "p25_s": 0.12, "p75_s": 0.35,
                 "n_short": 2, "short_share": 0.2},
    }
    scan = {
        "scan_grid": [0.04, 0.08],
        "base_min_dur_s": 0.08,
        "short_s": 0.15,
        "levels": levels,
        "drift_pp": 20.0,
    }
    payload = build_segment_length_payload(
        [{"recording_id": "x", "label": "例", "ref_mode": "absolute",
          "duration_s": 10.0, "scan": scan}],
        run_id_="run-AAAA",
        caliber={"fmin": 60.0, "fmax": 1500.0},
    )
    assert payload["run_id"] == "run-AAAA"
    assert payload["provenance"]["run_id"] == "run-AAAA"
    assert payload["per_recording"][0]["n_segments"] == 10
    assert payload["per_recording"][0]["median_s"] == 0.25
    rows = segment_length_csv_rows(payload)
    assert len(rows) == 2
    assert sum(row["is_base"] for row in rows) == 1
    base = next(row for row in rows if row["is_base"])
    assert base["min_dur_s"] == 0.08
    assert base["n_segments"] == 10
