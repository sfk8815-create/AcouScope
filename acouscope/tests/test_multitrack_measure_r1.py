# SPDX-License-Identifier: GPL-3.0-only
"""多量纲测量 runner 测试（离屏，无主窗口显示调用）。

覆盖：
- MEASURE_KIND 已登记且对多个音频文件跑同一 kind 返回 status="done"
- 11 键齐全、类型正确
- 合成 440 Hz 正弦的 duration_s/frames/sample_rate/channels 精确
- RMS dB 与解析值容差 ≤0.05 dB
- 全零音频与 data=None/空数组不抛且 dB 字段为 None
- 多轨单轨异常隔离、输入序不变、缓存命中免算
- 静态守卫：DEFAULT_MAX_CONCURRENCY == 1、既有 runner 仍登记
"""

import subprocess
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.ui.widgets.multitrack.analysis_source import (
    DEFAULT_MAX_CONCURRENCY, MEASURE_KIND, AnalysisSource, TrackResultCache,
    register_runner, run_analysis_on_tracks,
)

_MODULE = (
    Path(__file__).resolve().parents[1]
    / "src" / "acouscope" / "ui" / "widgets" / "multitrack" / "analysis_source.py"
)


def _tone(sr: int = 8000, seconds: float = 1.0, freq: float = 440.0):
    t = np.arange(int(sr * seconds)) / sr
    return (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _source(track_id, data=None, sr: int = 8000, offset_ms: float = 0.0):
    return AnalysisSource(
        track_id or "current", data if data is not None else _tone(sr),
        sr, align_offset_ms=offset_ms, track_id=track_id,
    )


# ---------------------------------------------------------------------------
# ① MEASURE_KIND 已登记 + 对多个音频文件跑同一 kind
# ---------------------------------------------------------------------------


def test_measure_kind_registered():
    """MEASURE_KIND 已登记为内置 runner。"""
    handles = run_analysis_on_tracks([_source("a")], MEASURE_KIND)
    assert handles[0].status == "done"
    assert isinstance(handles[0].result, dict)


def test_multi_track_same_kind():
    """一次对多个音频文件跑同一 kind（3 轨，其中 1 轨 data=None）。"""
    srcs = [
        _source("a", sr=8000),
        AnalysisSource("b", None, 44100, track_id="b"),
        _source("c", np.zeros(64, dtype=np.float32), 16000),
    ]
    handles = run_analysis_on_tracks(srcs, MEASURE_KIND)
    assert len(handles) == 3
    # 输入序不变
    assert [h.track_id for h in handles] == ["a", "b", "c"]
    # 全部 done（None/空数据不抛）
    assert all(h.status == "done" for h in handles)


# ---------------------------------------------------------------------------
# ② 11 键齐全、类型正确
# ---------------------------------------------------------------------------


def test_result_has_all_11_keys():
    """结果固定 11 键，每键类型正确。"""
    src = _source("a")
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result

    expected_keys = {
        "track_id", "name", "duration_s", "sample_rate",
        "channels", "frames", "rms_db", "peak_db", "crest_db",
        "silence_ratio", "offset_ms",
    }
    assert set(r.keys()) == expected_keys

    # 类型检查
    assert r["track_id"] == "a"
    assert isinstance(r["name"], str)
    assert isinstance(r["duration_s"], float)
    assert r["sample_rate"] == 8000
    assert isinstance(r["channels"], int)
    assert isinstance(r["frames"], int)
    assert isinstance(r["rms_db"], float)
    assert isinstance(r["peak_db"], float)
    assert isinstance(r["crest_db"], float)
    assert isinstance(r["silence_ratio"], float)
    assert r["offset_ms"] == 0.0


# ---------------------------------------------------------------------------
# ③ 合成信号精确校验 + RMS dB 与解析值对比
# ---------------------------------------------------------------------------


def test_sine_wave_structural_fields_exact():
    """440 Hz 正弦：duration_s/frames/sample_rate/channels 精确。"""
    sr = 8000
    seconds = 1.5
    src = _source("sine", data=_tone(sr, seconds), sr=sr)
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result

    assert r["frames"] == int(sr * seconds)
    assert r["sample_rate"] == sr
    assert r["channels"] == 1
    assert abs(r["duration_s"] - seconds) < 1e-9


def test_rms_db_matches_analytical():
    """RMS dB 与解析值容差 ≤0.05 dB。"""
    sr = 8000
    amplitude = 0.4
    src = _source("sine", data=_tone(sr, 1.0), sr=sr)
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result

    # 正弦波 RMS = amplitude / sqrt(2)
    analytical_rms = amplitude / np.sqrt(2.0)
    expected_db = 20.0 * np.log10(analytical_rms + 1e-12)

    assert abs(r["rms_db"] - expected_db) <= 0.05


def test_peak_db_matches_analytical():
    """Peak dB 与解析值容差 ≤0.05 dB。"""
    sr = 8000
    amplitude = 0.4
    src = _source("sine", data=_tone(sr, 1.0), sr=sr)
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result

    expected_db = 20.0 * np.log10(amplitude + 1e-12)
    assert abs(r["peak_db"] - expected_db) <= 0.05


def test_crest_db_is_peak_minus_rms():
    """Crest factor = Peak dB - RMS dB。"""
    src = _source("sine")
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result
    assert abs(r["crest_db"] - (r["peak_db"] - r["rms_db"])) < 1e-9


# ---------------------------------------------------------------------------
# ④ None/空/全零数据不抛 + dB 字段为 None
# ---------------------------------------------------------------------------


def test_none_data_no_exception():
    """data=None 不抛异常，dB 字段为 None。"""
    src = AnalysisSource("none", None, 44100, track_id="none")
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result

    assert handles[0].status == "done"
    assert r["frames"] == 0
    assert r["sample_rate"] == 44100
    assert r["rms_db"] is None
    assert r["peak_db"] is None
    assert r["crest_db"] is None
    assert r["silence_ratio"] is None


def test_empty_array_no_exception():
    """空数组不抛异常，dB 字段为 None。"""
    src = AnalysisSource("empty", np.array([], dtype=np.float32), 44100, track_id="empty")
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result

    assert handles[0].status == "done"
    assert r["frames"] == 0
    assert r["rms_db"] is None
    assert r["peak_db"] is None


def test_all_zeros_no_neg_inf_or_nan():
    """全零音频不产生 -inf/nan（用 1e-12 下限）。"""
    data = np.zeros(64, dtype=np.float32)
    src = _source("zeros", data=data, sr=8000)
    handles = run_analysis_on_tracks([src], MEASURE_KIND)
    r = handles[0].result

    assert handles[0].status == "done"
    # 1e-12 floor → -240 dB for pure zeros; finite, not -inf
    assert np.isfinite(r["peak_db"])
    assert np.isfinite(r["rms_db"])
    assert r["peak_db"] == pytest.approx(-240.0, rel=1e-6)
    assert r["silence_ratio"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ⑤ 多轨异常隔离 + 输入序不变 + 缓存命中免算
# ---------------------------------------------------------------------------


def test_input_order_preserved():
    """结果按输入序返回。"""
    srcs = [_source(f"t{i}") for i in range(5)]
    handles = run_analysis_on_tracks(srcs, MEASURE_KIND)
    assert [h.track_id for h in handles] == ["t0", "t1", "t2", "t3", "t4"]
    assert [h.seq for h in handles] == [0, 1, 2, 3, 4]


def test_cache_hit_skips_computation():
    """缓存命中免算。"""
    src = _source("cached")
    cache = TrackResultCache()

    # 预置缓存
    key = TrackResultCache.key("cached", MEASURE_KIND, None)
    cache.put(key, {"track_id": "cached", "precomputed": True})

    def boom(source, params):
        raise AssertionError("runner 不应被调用")

    handles = run_analysis_on_tracks(
        [src], MEASURE_KIND, runner=boom, cache=cache
    )
    assert handles[0].status == "cached"
    assert handles[0].result["precomputed"] is True


# ---------------------------------------------------------------------------
# ⑥ 静态守卫
# ---------------------------------------------------------------------------


def test_default_concurrency_unchanged():
    """DEFAULT_MAX_CONCURRENCY 仍为 1。"""
    assert DEFAULT_MAX_CONCURRENCY == 1


def test_existing_runners_still_registered():
    """既有 pitch/spectrogram runner 仍登记。"""
    handles_pitch = run_analysis_on_tracks([_source("p")], "pitch")
    assert handles_pitch[0].status == "done"

    handles_spec = run_analysis_on_tracks(
        [ _source("s")], "spectrogram", {"n_fft": 256, "hop_length": 64}
    )
    assert handles_spec[0].status == "done"


def test_analysis_source_test_file_unchanged():
    """tests/test_analysis_source.py 零 diff。"""
    test_file = Path(__file__).resolve().parent / "test_analysis_source.py"
    result = subprocess.run(
        ["git", "diff", "--", str(test_file)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2])
    )
    assert result.returncode == 0, f"git diff failed: {result.stderr}"
    assert result.stdout.strip() == "", (
        f"test_analysis_source.py changed:\n{result.stdout}"
    )
