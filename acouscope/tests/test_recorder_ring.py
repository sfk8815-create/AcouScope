# SPDX-License-Identifier: GPL-3.0-only
"""AudioRecorder 接入 FixedRingBuffer 的单元测试（无音频设备）。"""

import numpy as np
import pytest

from acouscope.audio.recorder import AudioRecorder
from acouscope.audio.ring_buffer import FixedRingBuffer


@pytest.fixture
def rec():
    """不启动设备的 recorder：手动装配 ring 与参数。"""
    r = AudioRecorder()
    r._sample_rate = 44100
    r._channels = 1
    r._ring = FixedRingBuffer(2.0, 44100)  # 容量 88200
    r._dropped_samples = 0
    return r


def test_dropout_zero_initially(rec):
    assert rec.get_dropout_seconds() == 0.0
    assert rec._dropped_samples == 0


def test_ingest_normal_accumulates(rec):
    dropped = rec._ingest_chunk(np.arange(1000, dtype=np.float32))
    assert dropped == 0
    assert rec._total_samples == 1000
    data, sr = rec.get_recorded_data()
    assert sr == 44100
    assert len(data) == 1000
    assert np.allclose(data, np.arange(1000))


def test_ingest_multiple_chunks_order(rec):
    rec._ingest_chunk(np.full(500, 0.1, dtype=np.float32))
    rec._ingest_chunk(np.full(500, 0.2, dtype=np.float32))
    data, _ = rec.get_recorded_data()
    assert len(data) == 1000
    assert np.allclose(data[:500], 0.1)
    assert np.allclose(data[500:], 0.2)


def test_ingest_oversized_chunk_dropout(rec):
    cap = rec._ring.capacity  # 88200
    big = np.ones(cap + 500, dtype=np.float32)  # 超容量 500
    dropped = rec._ingest_chunk(big)
    assert dropped == 500
    assert rec._dropped_samples == 500
    assert abs(rec.get_dropout_seconds() - 500 / 44100) < 1e-9
    # 被接受的 cap 个采样正常累积
    assert rec._total_samples == cap
    data, _ = rec.get_recorded_data()
    assert len(data) == cap


def test_level_callback_receives_peak(rec):
    peaks = []
    rec._level_callback = lambda pv: peaks.append(pv)
    rec._ingest_chunk(np.array([0.0, 0.5, -0.8, 0.2], dtype=np.float32))
    assert len(peaks) == 1
    assert peaks[0] == pytest.approx(0.8, abs=1e-6)


def test_data_callback_receives_chunk(rec):
    got = []
    rec._data_callback = lambda c: got.append(len(c))
    rec._ingest_chunk(np.zeros(256, dtype=np.float32))
    assert got == [256]


def test_ingest_without_ring_fallback(rec):
    rec._ring = None  # 兜底分支
    dropped = rec._ingest_chunk(np.arange(10, dtype=np.float32))
    assert dropped == 0
    assert rec._total_samples == 10


def test_multichannel_mix_before_ingest(rec):
    """模拟 _poll_audio 的混音：立体声均值后入库为单声道。"""
    stereo = np.ones(200, dtype=np.float32)  # 已展平的单声道
    rec._ingest_chunk(stereo)
    assert rec._total_samples == 200
