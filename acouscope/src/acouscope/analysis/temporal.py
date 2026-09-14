# SPDX-License-Identifier: GPL-3.0-only
"""时域分析模块。"""

from __future__ import annotations

import numpy as np


class TemporalAnalyzer:
    """时域特征分析器。

    计算波形、包络、能量、过零率等时域特征。
    """

    def __init__(self, sample_rate: float = 44100.0):
        self.sample_rate = sample_rate

    def envelope(self, signal: np.ndarray, frame_size: int = 1024, hop_size: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """计算信号包络（峰值包络）。

        Args:
            signal: 输入信号
            frame_size: 帧长
            hop_size: 帧移

        Returns:
            (时间轴, 包络值)
        """
        n_frames = 1 + (len(signal) - frame_size) // hop_size
        if n_frames <= 0:
            return np.array([]), np.array([])
        envelope = np.zeros(n_frames)

        for i in range(n_frames):
            start = i * hop_size
            frame = signal[start : start + frame_size]
            envelope[i] = np.max(np.abs(frame))

        times = np.arange(n_frames) * hop_size / self.sample_rate
        return times, envelope

    def rms(self, signal: np.ndarray, frame_size: int = 1024, hop_size: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """计算 RMS 能量。

        Args:
            signal: 输入信号
            frame_size: 帧长
            hop_size: 帧移

        Returns:
            (时间轴, RMS 值)
        """
        n_frames = 1 + (len(signal) - frame_size) // hop_size
        if n_frames <= 0:
            return np.array([]), np.array([])
        rms = np.zeros(n_frames)

        for i in range(n_frames):
            start = i * hop_size
            frame = signal[start : start + frame_size]
            rms[i] = np.sqrt(np.mean(frame**2))

        times = np.arange(n_frames) * hop_size / self.sample_rate
        return times, rms

    def rms_db(self, signal: np.ndarray, frame_size: int = 1024, hop_size: int = 512, ref: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
        """计算 RMS 能量（dB 标度）。

        Args:
            signal: 输入信号
            frame_size: 帧长
            hop_size: 帧移
            ref: 参考值

        Returns:
            (时间轴, RMS dB 值)
        """
        times, rms = self.rms(signal, frame_size, hop_size)
        rms_db = 20 * np.log10(np.maximum(rms, 1e-10) / ref)
        return times, rms_db

    def attack_time(self, signal: np.ndarray, threshold_db: float = -20.0) -> float:
        """估算起振时间。

        Args:
            signal: 输入信号
            threshold_db: 起振阈值（dB）

        Returns:
            起振时间（秒）
        """
        # 找到峰值位置
        peak_idx = np.argmax(np.abs(signal))
        peak_val = np.abs(signal[peak_idx])

        # 找到阈值交叉点（从前往后）
        threshold = peak_val * 10 ** (threshold_db / 20.0)

        # 从信号起始位置向前找第一个超过阈值的点
        above_threshold = np.where(np.abs(signal) >= threshold)[0]
        if len(above_threshold) == 0:
            return 0.0

        start_idx = above_threshold[0]
        attack_samples = peak_idx - start_idx

        return max(0.0, attack_samples / self.sample_rate)
