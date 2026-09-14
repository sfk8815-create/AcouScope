# SPDX-License-Identifier: GPL-3.0-only
"""FFT 计算模块。"""

from __future__ import annotations

from typing import Optional

import numpy as np

from acouscope.dsp.windows import WindowFunction


class FFTEngine:
    """FFT 计算引擎。

    封装 FFT 相关计算，提供幅度谱、相位谱、功率谱等。
    """

    def __init__(self, size: int = 4096, window: str = "hann"):
        """初始化 FFT 引擎。

        Args:
            size: FFT 大小（应为 2 的幂）
            window: 窗函数名称
        """
        self.size = size
        self.window_name = window
        self._window: Optional[np.ndarray] = None
        self._window_sum: float = 0.0

    @property
    def window(self) -> np.ndarray:
        """获取窗函数数组。"""
        if self._window is None:
            self._window = WindowFunction.get(self.window_name, self.size)
            self._window_sum = float(np.sum(self._window))
        return self._window

    def compute_fft(
        self,
        signal: np.ndarray,
        normalize: bool = True,
    ) -> np.ndarray:
        """计算 FFT。

        Args:
            signal: 输入信号（长度应等于 size）
            normalize: 是否归一化

        Returns:
            复数值的 FFT 结果（长度为 size）
        """
        if len(signal) != self.size:
            # 截断或补零
            if len(signal) > self.size:
                signal = signal[: self.size]
            else:
                signal = np.pad(signal, (0, self.size - len(signal)))

        # 加窗
        windowed = signal * self.window

        spectrum = np.fft.fft(windowed)

        if normalize:
            spectrum /= self._window_sum

        return spectrum

    def magnitude_spectrum(
        self,
        signal: np.ndarray,
        db_scale: bool = False,
        db_ref: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算幅度谱。

        Args:
            signal: 输入信号
            db_scale: 是否转换为 dB
            db_ref: dB 参考值

        Returns:
            (频率轴, 幅度谱)
            频率轴为归一化频率（0~0.5，单位：周期/采样点），
            转换为 Hz 需乘以采样率。
        """
        spectrum = self.compute_fft(signal)
        n_half = self.size // 2 + 1
        magnitude = np.abs(spectrum[:n_half])

        if db_scale:
            magnitude = 20 * np.log10(np.maximum(magnitude, 1e-10) / db_ref)

        freqs = np.fft.rfftfreq(self.size, d=1.0)

        return freqs, magnitude

    def power_spectrum(
        self,
        signal: np.ndarray,
        db_scale: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算功率谱。

        Args:
            signal: 输入信号
            db_scale: 是否转换为 dB

        Returns:
            (频率轴, 功率谱)
        """
        freqs, magnitude = self.magnitude_spectrum(signal, db_scale=False)
        power = magnitude ** 2

        if db_scale:
            power = 10 * np.log10(np.maximum(power, 1e-20))

        return freqs, power

    def phase_spectrum(self, signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """计算相位谱。

        Args:
            signal: 输入信号

        Returns:
            (频率轴, 相位谱)
        """
        spectrum = self.compute_fft(signal)
        n_half = self.size // 2 + 1
        phase = np.angle(spectrum[:n_half])
        freqs = np.fft.fftfreq(self.size, d=1.0)[:n_half]

        return freqs, phase
