# SPDX-License-Identifier: GPL-3.0-only
"""固定容量环形缓冲（采集/消费解耦）。

Audacity RingBuffer（au3-audio-io/RingBuffer.h）的 Python 简化移植：
- C++ 版用两个缓存行对齐的原子游标（mStart/mEnd）做 SPSC 无锁同步；
  CPython 有 GIL，这里用一把 threading.Lock 替代，语义等价且足够快。
- put() 在缓冲满时只接受能放下的部分，多余采样计入 dropped（dropout 检测，
  对应 Audacity 的欠载/丢样诊断），返回 (accepted, dropped)。
- drain_all() 按写入顺序一次取走全部已缓冲数据，正确处理写游标回绕跨界。

用途：录音采集线程（QTimer readAll → put）与数据累积/消费之间解耦，
UI 线程偶发卡顿不超过容量（默认 2s）时不丢样。
"""

from __future__ import annotations

import threading

import numpy as np


class FixedRingBuffer:
    """单声道 float32 固定容量环形缓冲。

    容量（采样数）= round(capacity_seconds * sample_rate)。
    生产者 put() 写入；消费者 drain_all() 取走全部已缓冲数据。
    """

    def __init__(self, capacity_seconds: float, sample_rate: int):
        if capacity_seconds <= 0:
            raise ValueError("capacity_seconds must be > 0")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be > 0")
        self._sample_rate = int(sample_rate)
        self._capacity = int(round(float(capacity_seconds) * self._sample_rate))
        if self._capacity < 1:
            raise ValueError("capacity too small for given sample_rate")
        self._buf = np.zeros(self._capacity, dtype=np.float32)
        self._write_pos = 0        # 下一个写入位置（环内索引）
        self._filled = 0           # 当前已占用采样数
        self._total_dropped = 0    # 累计因满溢丢弃的采样数
        self._lock = threading.Lock()

    # -- 属性 --
    @property
    def capacity(self) -> int:
        """缓冲总容量（采样数）。"""
        return self._capacity

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def available_to_read(self) -> int:
        """当前可读采样数。"""
        with self._lock:
            return self._filled

    def available_to_write(self) -> int:
        """当前可写入空间（采样数）。"""
        with self._lock:
            return self._capacity - self._filled

    def dropped_samples(self) -> int:
        """累计丢弃采样数。"""
        with self._lock:
            return self._total_dropped

    def dropped_seconds(self) -> float:
        """累计丢弃时长（秒）。"""
        with self._lock:
            return self._total_dropped / self._sample_rate

    # -- 生产者 --
    def put(self, data: np.ndarray) -> tuple[int, int]:
        """写入数据。

        Args:
            data: 一维音频采样（任意数值类型，内部转 float32 展平）。

        Returns:
            (accepted, dropped)：实际写入采样数 / 因缓冲满丢弃采样数。
        """
        x = np.asarray(data, dtype=np.float32).ravel()
        n = len(x)
        if n == 0:
            return (0, 0)
        with self._lock:
            free = self._capacity - self._filled
            accepted = min(n, free)
            dropped = n - accepted
            self._total_dropped += dropped
            if accepted > 0:
                self._write_in_locked(x[:accepted])
            return (accepted, dropped)

    def _write_in_locked(self, x: np.ndarray) -> None:
        """把 x（调用方保证 len(x) <= 空闲空间）写入环，处理回绕。调用方持锁。"""
        n = len(x)
        first = min(n, self._capacity - self._write_pos)
        self._buf[self._write_pos:self._write_pos + first] = x[:first]
        if first < n:
            self._buf[0:n - first] = x[first:]
        self._write_pos = (self._write_pos + n) % self._capacity
        self._filled += n

    # -- 消费者 --
    def drain_all(self) -> np.ndarray:
        """按写入顺序取走全部已缓冲数据并清空缓冲。

        Returns:
            float32 一维数组；无数据时返回长度 0 的 float32 数组。
        """
        with self._lock:
            if self._filled == 0:
                return np.zeros(0, dtype=np.float32)
            start = (self._write_pos - self._filled) % self._capacity
            if start + self._filled <= self._capacity:
                out = self._buf[start:start + self._filled].copy()
            else:
                # 回绕跨界：尾部一段 + 头部一段
                first = self._capacity - start
                out = np.concatenate([
                    self._buf[start:start + first],
                    self._buf[0:self._filled - first],
                ])
            self._filled = 0  # 取走后全部空间可用；_write_pos 保持不动
            return out.astype(np.float32, copy=False)

    # -- 复位 --
    def reset(self) -> None:
        """清空缓冲与丢样计数。"""
        with self._lock:
            self._filled = 0
            self._write_pos = 0
            self._total_dropped = 0
            self._buf.fill(0.0)
