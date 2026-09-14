# SPDX-License-Identifier: GPL-3.0-only
"""FixedRingBuffer 单元测试（纯逻辑，无 Qt 依赖）。"""

import numpy as np
import pytest

from acouscope.audio.ring_buffer import FixedRingBuffer


def test_capacity_from_seconds():
    rb = FixedRingBuffer(1.0, 1000)
    assert rb.capacity == 1000
    assert rb.sample_rate == 1000
    assert rb.available_to_read() == 0
    assert rb.available_to_write() == 1000


def test_empty_drain_returns_float32_empty():
    rb = FixedRingBuffer(1.0, 1000)
    out = rb.drain_all()
    assert out.dtype == np.float32
    assert len(out) == 0


def test_put_and_drain_basic():
    rb = FixedRingBuffer(1.0, 1000)
    acc, drop = rb.put(np.arange(100, dtype=np.float32))
    assert (acc, drop) == (100, 0)
    assert rb.available_to_read() == 100
    out = rb.drain_all()
    assert len(out) == 100
    assert np.allclose(out, np.arange(100))
    assert rb.available_to_read() == 0
    # 再 drain 一次为空
    assert len(rb.drain_all()) == 0


def test_wrap_around_preserves_order():
    """写游标回绕跨界后，drain 顺序仍严格等于写入顺序。"""
    rb = FixedRingBuffer(1.0, 1000)
    rb.put(np.arange(950, dtype=np.float32))
    rb.drain_all()  # 清空，_write_pos 停在 950
    rb.put(np.arange(100, dtype=np.float32) + 1000)  # 50 落 [950,1000)，50 回绕到 [0,50)
    out = rb.drain_all()
    assert len(out) == 100
    assert np.allclose(out, np.arange(100) + 1000)


def test_overflow_counts_dropped():
    rb = FixedRingBuffer(1.0, 1000)
    acc, drop = rb.put(np.arange(1500, dtype=np.float32))
    assert acc == 1000
    assert drop == 500
    assert rb.dropped_samples() == 500
    assert abs(rb.dropped_seconds() - 0.5) < 1e-9
    out = rb.drain_all()
    assert len(out) == 1000
    assert np.allclose(out, np.arange(1000))  # 保留前 1000 个


def test_overflow_after_partial_drain():
    """消费清空后再写导致满溢，计数与内容正确。"""
    rb = FixedRingBuffer(1.0, 1000)
    rb.put(np.arange(800, dtype=np.float32))
    rb.drain_all()
    acc, drop = rb.put(np.arange(1200, dtype=np.float32) + 1)
    assert acc == 1000
    assert drop == 200
    assert rb.dropped_samples() == 200
    out = rb.drain_all()
    assert len(out) == 1000
    assert np.allclose(out, np.arange(1000) + 1)


def test_small_chunks_repeated_no_oob():
    """远小于容量的块反复写/读 100 轮，不越界、不丢样。"""
    rb = FixedRingBuffer(0.01, 1000)  # cap = 10
    for i in range(100):
        acc, drop = rb.put(np.full(3, i, dtype=np.float32))
        assert drop == 0
        assert acc == 3
        out = rb.drain_all()
        assert len(out) == 3
        assert np.all(out == i)


def test_reset_clears_state():
    rb = FixedRingBuffer(1.0, 1000)
    rb.put(np.arange(500, dtype=np.float32))
    assert rb.available_to_read() == 500
    rb.reset()
    assert rb.available_to_read() == 0
    assert rb.dropped_samples() == 0
    assert len(rb.drain_all()) == 0


def test_put_empty_is_noop():
    rb = FixedRingBuffer(1.0, 1000)
    acc, drop = rb.put(np.zeros(0, dtype=np.float32))
    assert (acc, drop) == (0, 0)
    assert rb.available_to_read() == 0


def test_multichannel_input_flattened():
    """二维输入按展平处理（调用方负责混音），不报错。"""
    rb = FixedRingBuffer(1.0, 1000)
    stereo = np.ones((10, 2), dtype=np.float32)
    acc, drop = rb.put(stereo)
    assert acc == 20 and drop == 0
    assert rb.available_to_read() == 20


def test_invalid_constructor_args():
    with pytest.raises(ValueError):
        FixedRingBuffer(0, 1000)
    with pytest.raises(ValueError):
        FixedRingBuffer(1.0, 0)
    with pytest.raises(ValueError):
        FixedRingBuffer(0.0001, 100)  # 容量 < 1 采样
