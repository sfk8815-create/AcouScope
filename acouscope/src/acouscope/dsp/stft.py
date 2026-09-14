# SPDX-License-Identifier: GPL-3.0-only
"""STFT 计算模块（纯 numpy 实现）。"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import as_strided

from acouscope.dsp.windows import WindowFunction


class STFTEngine:
    """短时傅里叶变换引擎。

    计算语谱图（spectrogram）等时频表示。
    使用 as_strided + 批量 rfft 向量化计算，性能远优于逐帧循环。
    """

    def __init__(
        self,
        n_fft: int = 2048,
        hop_length: int = 512,
        window: str = "hann",
        center: bool = True,
    ):
        """初始化 STFT 引擎。

        Args:
            n_fft: FFT 窗口大小
            hop_length: 帧移（相邻帧的采样点数）
            window: 窗函数名称
            center: 是否对信号进行居中填充
        """
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.window_name = window
        self.center = center

    def _frame_signal(self, signal: np.ndarray) -> np.ndarray:
        """用 as_strided 将 1D 信号切分为 (n_frames, n_fft) 的帧矩阵。

        零拷贝，仅操作 strides。
        """
        n_frames = 1 + (len(signal) - self.n_fft) // self.hop_length
        if n_frames <= 0:
            return np.zeros((0, self.n_fft), dtype=signal.dtype)

        # as_strided: 每行长度 n_fft，行间距 hop_length 个采样点
        return as_strided(
            signal,
            shape=(n_frames, self.n_fft),
            strides=(signal.strides[0] * self.hop_length, signal.strides[0]),
            writeable=False,
        )

    def compute(
        self,
        signal: np.ndarray,
        sample_rate: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算 STFT（向量化批量 FFT）。

        Args:
            signal: 输入信号（单声道）
            sample_rate: 采样率

        Returns:
            (频率轴 Hz, 时间轴 s, 复数值 STFT 矩阵)
            STFT 矩阵形状为 (n_freq, n_time)。
            center=True 时第 i 帧中心对齐原始信号 i*hop_length 处。
        """
        window = WindowFunction.get(self.window_name, self.n_fft)

        # 居中填充
        if self.center:
            pad = self.n_fft // 2
            padded = np.pad(signal, (pad, pad), mode="reflect")
        else:
            padded = signal

        n_freq = self.n_fft // 2 + 1

        # 信号过短
        if len(padded) < self.n_fft:
            return (
                np.fft.rfftfreq(self.n_fft, d=1.0 / sample_rate),
                np.array([]),
                np.zeros((n_freq, 0), dtype=np.complex128),
            )

        # 用 as_strided 批量切帧（零拷贝）
        frames = self._frame_signal(padded)  # (n_frames, n_fft)

        # 加窗 + 批量 FFT
        # frames * window 广播乘法 → (n_frames, n_fft)
        # rfft 沿最后一维计算 → (n_frames, n_freq)
        stft_matrix = np.fft.rfft(frames * window, axis=1)

        # 转置为 (n_freq, n_frames)，与原接口一致
        stft_matrix = stft_matrix.T

        # 频率轴和时间轴
        freqs = np.fft.rfftfreq(self.n_fft, d=1.0 / sample_rate)
        n_frames = frames.shape[0]
        times = np.arange(n_frames) * self.hop_length / sample_rate

        return freqs, times, stft_matrix

    def magnitude(
        self,
        signal: np.ndarray,
        sample_rate: float,
        db_scale: bool = True,
        db_ref: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算幅度语谱图。

        Args:
            signal: 输入信号
            sample_rate: 采样率
            db_scale: 是否转换为 dB
            db_ref: dB 参考值

        Returns:
            (频率轴, 时间轴, 幅度谱矩阵)
        """
        freqs, times, S = self.compute(signal, sample_rate)
        mag = np.abs(S)

        if db_scale:
            mag = 20 * np.log10(np.maximum(mag, 1e-10) / db_ref)

        return freqs, times, mag

    def power(
        self,
        signal: np.ndarray,
        sample_rate: float,
        db_scale: bool = True,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算功率谱图。

        Args:
            signal: 输入信号
            sample_rate: 采样率
            db_scale: 是否转换为 dB

        Returns:
            (频率轴, 时间轴, 功率谱矩阵)
        """
        freqs, times, S = self.compute(signal, sample_rate)
        power = np.abs(S) ** 2

        if db_scale:
            power = 10 * np.log10(np.maximum(power, 1e-20))

        return freqs, times, power
