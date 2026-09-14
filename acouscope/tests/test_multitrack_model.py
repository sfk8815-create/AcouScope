# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 多轨数据层回归（纯逻辑，无 Qt 窗口）。

覆盖：懒加载状态机（元数据 → 粗包络 → 全量样本）、数据引用不复制、
LRU 释放保当前轨、S/M 可闻语义、音量夹紧、偏移字段往返、移除/撤销槽、
内存估算与健康提示口径、真实文件元数据 + 粗包络读取、时间格式。
"""

import numpy as np
import pytest
import soundfile as sf

from acouscope.ui.widgets.multitrack.track_model import (
    COARSE_POINTS, READY, UNLOADED, MultitrackSession, TrackModel, format_seconds,
)


def _readers(duration: float = 2.0, sr: int = 8000, peak: float = 0.5):
    """伪读取器三元组：元数据 / 粗包络 / 全量样本（零磁盘）。"""
    calls = {"meta": 0, "env": 0, "load": 0}

    def meta(path):
        calls["meta"] += 1
        return {"sample_rate": sr, "channels": 1, "duration": duration}

    def env(path, points):
        calls["env"] += 1
        return np.linspace(0.0, duration, points), np.full(
            points, peak, dtype=np.float32
        )

    def load(path):
        calls["load"] += 1
        return np.zeros(int(sr * duration), dtype=np.float64), sr

    return meta, env, load, calls


def _session(**kwargs) -> MultitrackSession:
    meta, env, load, calls = _readers()
    session = MultitrackSession(
        metadata_reader=meta, envelope_reader=env, loader=load, **kwargs
    )
    session._test_calls = calls  # 测试用计数（不参与生产逻辑）
    return session


def test_lazy_state_machine_metadata_envelope_then_full():
    session = _session()
    track = session.add_path("/tmp/a.wav")
    # 第一级：元数据已读、粗包络已算，但全量样本未载入
    assert track.metadata_ready is True
    assert track.envelope_ready is True
    assert track.state == UNLOADED
    assert track.has_data is False
    assert track.sample_rate == 8000 and track.duration == 2.0
    assert session._test_calls == {"meta": 1, "env": 1, "load": 0}

    # 第三级：切为当前轨才载入全量样本
    data = session.load_full(track.track_id)
    assert data is not None and track.state == READY and track.has_data is True
    assert session._test_calls["load"] == 1
    assert session.load_full(track.track_id) is data     # 二次调用零重载
    assert session._test_calls["load"] == 1

    # 释放回未载入；元数据/粗包络保留
    assert track.release_data() is True
    assert track.state == UNLOADED and track.has_data is False
    assert track.metadata_ready and track.envelope_ready
    assert track.release_data() is False                 # 幂等


def test_data_reference_not_copied_by_default():
    track = TrackModel("/tmp/b.wav", metadata_reader=lambda p: {}, envelope_reader=None)
    arr = np.linspace(-1.0, 1.0, 64)
    track.set_data(arr, sample_rate=8)
    assert track.data is arr                             # 同源引用，无复制
    assert np.shares_memory(track.data, arr)
    other = np.ones(8)
    track.set_data(other, sample_rate=8, copy=True)
    assert track.data is not other and np.array_equal(track.data, other)


def test_envelope_reader_failure_is_non_fatal():
    def bad_env(path, points):
        raise OSError("decode failed")

    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": 1, "channels": 1, "duration": 0.0},
        envelope_reader=bad_env,
        loader=lambda p: (np.zeros(0), 1),
    )
    track = session.add_path("/tmp/broken.wav")
    assert track.envelope_ready is False
    assert "decode failed" in (track.error or "")
    assert len(session) == 1                             # 轨道仍在（可移除/重试）


def test_solo_mute_audibility_semantics():
    session = _session()
    ids = [session.add_path(f"/tmp/{i}.wav").track_id for i in range(3)]
    assert session.audible_ids() == ids                  # 无 solo：全部未静音者
    session.set_solo(ids[1], True)
    assert session.audible_ids() == [ids[1]]             # 任一 solo → 其余静音
    session.set_solo(ids[2], True)
    assert session.audible_ids() == [ids[1], ids[2]]
    session.set_mute(ids[1], True)
    assert session.audible_ids() == [ids[2]]             # solo + mute → 排除
    session.set_solo(ids[1], False)
    session.set_solo(ids[2], False)
    assert session.audible_ids() == [ids[0], ids[2]]     # 回到 mute 语义


def test_volume_clamped_label_and_offset_roundtrip():
    session = _session()
    track = session.add_path("/tmp/v.wav")
    tid = track.track_id
    assert session.set_volume(tid, 2.5) == 1.0
    assert session.set_volume(tid, -1.0) == 0.0
    assert session.set_volume(tid, 0.4) == pytest.approx(0.4)
    assert session.set_label(tid, "  take-2  ") == "take-2"
    assert session.set_label(tid, "   ") == "v"           # 空名回落文件名词干
    assert session.set_offset_ms(tid, 123.5) == pytest.approx(123.5)
    assert track.offset_ms == pytest.approx(123.5)        # T-1006 对齐算法前置字段
    assert track.shifted_duration() == pytest.approx(2.1235)
    assert session.total_duration() == pytest.approx(2.1235)
    assert session.set_offset_ms("nope", 1.0) is None


def test_lru_release_keeps_current_track_and_bounds_memory():
    session = _session(max_loaded=2)
    tracks = [session.add_path(f"/tmp/lru{i}.wav") for i in range(4)]
    session.set_current(tracks[2].track_id)
    for track in tracks:                                # 手工全载（绕过自动裁剪）
        track.set_data(np.zeros(4000, dtype=np.float64), sample_rate=8000)
    assert len(session.loaded_ids()) == 4

    released = session.unload_inactive()
    assert set(released) == {tracks[0].track_id, tracks[1].track_id}
    assert len(session.loaded_ids()) <= 2               # 释放到预算内
    assert tracks[2].track_id in session.loaded_ids()   # 当前轨永不被释放
    assert session.load_full(tracks[0].track_id) is not None
    assert len(session.loaded_ids()) <= 2               # 再次载入仍受预算约束


def test_estimate_bytes_and_health_hint_scale():
    session = _session()
    empty = session.estimate_bytes()
    assert empty == 0                                     # 空会话：零占用
    track = session.add_path("/tmp/m.wav")
    track.set_data(np.zeros(8000, dtype=np.float64), sample_rate=8000)
    loaded = session.estimate_bytes()
    assert loaded > empty
    assert session.estimate_mb() == pytest.approx(loaded / (1024.0 * 1024.0))
    assert session.loaded_ids() == [track.track_id]


def test_remove_pending_and_restore_in_place():
    session = _session()
    a, b, c = (session.add_path(f"/tmp/r{i}.wav") for i in range(3))
    removed = session.remove(b.track_id)
    assert removed is b and len(session) == 2
    assert session.pending_removal is b                   # D9 撤销槽（单条）
    assert [t.track_id for t in session.tracks()] == [a.track_id, c.track_id]
    assert session.restore_pending() is b                 # 原位回插
    assert [t.track_id for t in session.tracks()] == [
        a.track_id, b.track_id, c.track_id,
    ]
    assert session.pending_removal is None
    session.remove(a.track_id)
    session.clear_pending()
    assert session.pending_removal is None
    assert session.restore_pending() is None


def test_remove_current_falls_back_to_neighbour():
    session = _session()
    a = session.add_path("/tmp/n0.wav")
    b = session.add_path("/tmp/n1.wav")
    session.set_current(b.track_id)
    session.remove(b.track_id)
    assert session.current_id == a.track_id
    session.remove(a.track_id)
    assert session.current_id is None
    assert session.set_current("missing") is False


def test_clear_releases_and_empties():
    session = _session()
    track = session.add_path("/tmp/clr.wav")
    session.load_full(track.track_id)
    session.clear()
    assert len(session) == 0 and session.current_id is None
    assert track.has_data is False and track.state == UNLOADED


def test_real_file_metadata_and_coarse_envelope(tmp_path):
    path = tmp_path / "real.wav"
    sr = 8000
    t = np.arange(sr) / sr
    wave = 0.25 * np.sin(2 * np.pi * 250 * t)
    sf.write(str(path), wave, sr)

    session = MultitrackSession()                # 真实读取器（AudioIO/soundfile）
    track = session.add_path(path)
    assert track.metadata_ready is True
    assert track.sample_rate == sr
    assert track.duration == pytest.approx(1.0, abs=1e-3)
    times, peaks = track.envelope()
    assert 0 < len(times) <= COARSE_POINTS
    assert len(times) == len(peaks)
    assert peaks.max() == pytest.approx(0.25, abs=0.02)   # 读文件峰值口径
    assert track.level_peak() == pytest.approx(0.25, abs=0.02)


def test_format_seconds_is_absolute_clock():
    assert format_seconds(0.0) == "0:00.000"
    assert format_seconds(61.5) == "1:01.500"
    assert format_seconds(3600.0) == "60:00.000"
    assert format_seconds(None) == "0:00.000"
