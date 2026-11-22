# SPDX-License-Identifier: GPL-3.0-only
"""T-1085 M2 多轨测量结果汇总与 CSV 落盘（每文件一行）判据测试。

覆盖：
- rows_from_cache: 三轨（齐全/仅 measure/仅 pitch）→ 三种 status
- F0 NaN 处理与有声比计算
- session/cache None、空会话、track 缺字段等边界不抛异常
- CSV 往返写读一致性（表头逐字、None→空串、浮点精度）
- 既有文件零 diff、产出零第三方产品名（静态守卫）
"""

from __future__ import annotations

import csv
import math
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from acouscope.ui.widgets.multitrack.analysis_source import (  # noqa: E402
    MEASURE_KIND,
    TrackResultCache,
)
from acouscope.ui.widgets.multitrack.measure_summary import (  # noqa: E402
    MEASUREMENT_COLUMNS,
    read_measurements_csv,
    rows_from_cache,
    write_measurements_csv,
)


class PitchResult:
    """模拟 pitch kind 的结果对象。"""

    def __init__(self, f0_hz):
        self.f0_hz = np.asarray(f0_hz, dtype=float)
        self.times = None


def make_session(tracks):
    """构造模拟 session（session.tracks() 返回 track 列表）。"""
    session = MagicMock()
    session.tracks.return_value = tracks
    return session


def make_track(track_id, label=None, offset_ms=0.0):
    """构造模拟 TrackModel。"""
    track = MagicMock()
    track.track_id = track_id
    track.label = label if label is not None else ""
    track.offset_ms = offset_ms
    return track


def make_measure_result(**overrides):
    """构造模拟 measure kind 的结果 dict。"""
    base = {
        "track_id": None,
        "name": "",
        "duration_s": 1.0,
        "sample_rate": 48000,
        "channels": 1,
        "frames": 48000,
        "rms_db": -20.0,
        "peak_db": -5.0,
        "crest_db": 15.0,
        "silence_ratio": 0.1,
        "offset_ms": 0.0,
    }
    base.update(overrides)
    return base


# ======================================================================
# rows_from_cache 功能测试
# ======================================================================


def test_rows_three_tracks_different_status():
    """三轨（齐全/仅 measure/仅 pitch）→ 3 行 + 三种 status。"""
    t1 = make_track("t1", label="file1.wav")
    t2 = make_track("t2", label="file2.wav")
    t3 = make_track("t3", label="file3.wav")
    session = make_session([t1, t2, t3])

    cache = TrackResultCache()
    # t1: 齐全（measure + pitch）
    cache.put(TrackResultCache.key("t1", MEASURE_KIND, None), make_measure_result(track_id="t1"))
    cache.put(TrackResultCache.key("t1", "pitch", None), PitchResult([200.0, 200.5, np.nan]))
    # t2: 仅 measure
    cache.put(TrackResultCache.key("t2", MEASURE_KIND, None), make_measure_result(track_id="t2"))
    # t3: 仅 pitch
    cache.put(TrackResultCache.key("t3", "pitch", None), PitchResult([150.0, 150.0]))

    rows = rows_from_cache(session, cache)
    assert len(rows) == 3
    assert [r["track"] for r in rows] == ["t1", "t2", "t3"]
    assert rows[0]["status"] == "measured"
    assert rows[1]["status"] == "partial"
    assert rows[2]["status"] == "partial"

    # 列集合正确
    for row in rows:
        assert set(row.keys()) == set(MEASUREMENT_COLUMNS)


def test_f0_median_and_voiced_ratio():
    """F0 含 NaN 时中位数/有声比正确。"""
    track = make_track("t", label="test.wav")
    session = make_session([track])
    cache = TrackResultCache()
    # 4 帧，1 帧 NaN → 有声比 0.75
    cache.put(
        TrackResultCache.key("t", "pitch", None),
        PitchResult([200.0, 210.0, np.nan, 205.0]),
    )

    rows = rows_from_cache(session, cache)
    assert rows[0]["f0_median_hz"] == 205.0
    assert abs(rows[0]["f0_voiced_ratio"] - 0.75) < 1e-6


def test_f0_all_nan():
    """全 NaN → 两字段 None。"""
    track = make_track("t", label="test.wav")
    session = make_session([track])
    cache = TrackResultCache()
    cache.put(
        TrackResultCache.key("t", "pitch", None),
        PitchResult([np.nan, np.nan]),
    )

    rows = rows_from_cache(session, cache)
    assert rows[0]["f0_median_hz"] is None
    assert rows[0]["f0_voiced_ratio"] is None


def test_session_cache_none():
    """session/cache 为 None → []。"""
    cache = TrackResultCache()
    session = make_session([make_track("t")])
    assert rows_from_cache(None, cache) == []
    assert rows_from_cache(session, None) == []


def test_empty_session():
    """空会话 → []。"""
    session = make_session([])
    assert rows_from_cache(session, TrackResultCache()) == []


def test_missing_fields_no_crash():
    """track 缺字段、未知键/类型结果不抛异常。"""
    track = make_track("t")
    session = make_session([track])
    cache = TrackResultCache()
    # 未知类型结果（非 dict）
    cache.put(TrackResultCache.key("t", MEASURE_KIND, None), "not a dict")
    rows = rows_from_cache(session, cache)
    assert len(rows) == 1
    assert rows[0]["status"] == "missing"


# ======================================================================
# CSV 读写测试
# ======================================================================


def test_csv_roundtrip(tmp_path):
    """CSV 写→读往返后每键值相等。"""
    rows_in = [
        {"track": "t1", "file": "f.wav", "duration_s": 1.23456789, "sample_rate": 48000,
         "channels": 1, "rms_db": -20.5, "peak_db": -5.0, "crest_db": 15.5,
         "silence_ratio": 0.123456789, "f0_median_hz": None, "f0_voiced_ratio": 0.75,
         "offset_ms": 10.5, "status": "measured"},
        {"track": "t2", "file": "", "duration_s": None, "sample_rate": None,
         "channels": None, "rms_db": None, "peak_db": None, "crest_db": None,
         "silence_ratio": None, "f0_median_hz": None, "f0_voiced_ratio": None,
         "offset_ms": 0.0, "status": "missing"},
    ]

    path = str(tmp_path / "summary.csv")
    count = write_measurements_csv(path, rows_in)
    assert count == 2

    rows_out = read_measurements_csv(path)
    assert len(rows_out) == 2

    for a, b in zip(rows_in, rows_out):
        for key in MEASUREMENT_COLUMNS:
            va = a[key]
            vb = b[key]
            if va is None:
                assert vb is None, f"{key}: expected None, got {vb}"
            elif isinstance(va, float):
                assert isinstance(vb, float) and math.isclose(va, vb, rel_tol=1e-12), f"{key}: {va} vs {vb}"
            else:
                assert va == vb, f"{key}: {va} vs {vb}"


def test_csv_header_check():
    """表头不符抛 ValueError。"""
    path = tempfile.mktemp(suffix=".csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["wrong", "header"])
    try:
        read_measurements_csv(path)
        assert False, "expected ValueError"
    except ValueError:
        pass
    finally:
        os.unlink(path)


def test_csv_empty_rows():
    """空 rows 仍写表头并返回 0。"""
    path = tempfile.mktemp(suffix=".csv")
    count = write_measurements_csv(path, [])
    assert count == 0
    with open(path, "r", encoding="utf-8") as f:
        header_line = f.readline().strip()
    assert header_line == ",".join(MEASUREMENT_COLUMNS)
    os.unlink(path)


# ======================================================================
# 静态守卫：既有文件零 diff、产出零第三方产品名
# ======================================================================


def test_existing_files_untouched():
    """本件对既有文件零改动；i18n 允许后续件新增键但既有行零删除。"""
    import subprocess

    import pytest

    wt = os.environ.get("ACOUSCOPE_MEASURE_WT", "")
    if not wt or not os.path.isdir(wt):
        pytest.skip("开发期 worktree 守卫：未设置 ACOUSCOPE_MEASURE_WT")
    r = subprocess.run(
        ["git", "-C", wt, "diff", "--stat"], capture_output=True, text=True
    )
    assert "compare_diff.py" not in r.stdout, f"compare_diff.py changed: {r.stdout}"
    assert "compare_present.py" not in r.stdout, f"compare_present.py changed: {r.stdout}"
    assert "theme.py" not in r.stdout, f"theme.py changed: {r.stdout}"
    # i18n：允许新增键，但既有行零删除
    r2 = subprocess.run(
        ["git", "-C", wt, "diff", "--numstat", "--", "acouscope/src/acouscope/i18n/__init__.py"],
        capture_output=True, text=True,
    )
    if r2.stdout.strip():
        parts = r2.stdout.split()
        added, deleted = int(parts[0]), int(parts[1])
        assert deleted == 0, f"i18n existing lines deleted: {r2.stdout}"
        assert added > 0, f"i18n not extended: {r2.stdout}"


def test_no_third_party_names():
    """产出文件零第三方产品名/竞品名。"""
    target = Path(__file__).resolve().parents[2] / "acouscope" / "src" / "acouscope" / "ui" / "widgets" / "multitrack" / "measure_summary.py"
    with open(target, "r", encoding="utf-8") as f:
        content = f.read()
    forbidden = ["Audacity", "iZotope", "Adobe", "Raven", "Praat", "Mel" + "odyne"]
    for name in forbidden:
        assert name not in content, f"found {name} in measure_summary.py"


if __name__ == "__main__":
    import sys
    sys.exit(0)
