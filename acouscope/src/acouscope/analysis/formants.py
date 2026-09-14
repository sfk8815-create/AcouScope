# SPDX-License-Identifier: GPL-3.0-only
"""共振峰分析模块。"""

from __future__ import annotations

import numpy as np


class FormantAnalyzer:
    """共振峰分析器。

    提供 LPC 法等共振峰提取算法。
    """

    def __init__(self, sample_rate: float = 44100.0, n_formants: int = 4):
        """
        Args:
            sample_rate: 采样率
            n_formants: 要提取的共振峰数量
        """
        self.sample_rate = sample_rate
        self.n_formants = n_formants

    def extract_lpc(
        self,
        signal: np.ndarray,
        order: int | None = None,
        frame_size: int = 1024,
        hop_length: int = 512,
        pre_emphasis: float = 0.97,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """使用 LPC 法提取共振峰。

        Args:
            signal: 输入信号
            order: LPC 阶数，默认采样率/1000 + 2
            frame_size: 帧长
            hop_length: 帧移
            pre_emphasis: 预加重系数

        Returns:
            (时间轴, 共振峰频率矩阵 [n_frames, n_formants], 共振峰带宽矩阵)
        """
        if len(signal) < 2:
            return np.array([]), np.zeros((0, self.n_formants)), np.zeros((0, self.n_formants))

        if order is None:
            order = int(self.sample_rate / 1000) + 2

        # 预加重
        if pre_emphasis > 0:
            signal = np.append(signal[0], signal[1:] - pre_emphasis * signal[:-1])

        n_frames = 1 + (len(signal) - frame_size) // hop_length
        if n_frames <= 0:
            # 信号比一帧还短，无法分析
            return np.array([]), np.zeros((0, self.n_formants)), np.zeros((0, self.n_formants))
        formant_freqs = np.zeros((n_frames, self.n_formants))
        formant_bw = np.zeros((n_frames, self.n_formants))
        times = np.arange(n_frames) * hop_length / self.sample_rate

        for i in range(n_frames):
            start = i * hop_length
            frame = signal[start : start + frame_size]

            # 加窗
            windowed = frame * np.hanning(frame_size)

            # LPC 分析
            lpc_coeffs = self._levinson_durbin(windowed, order)

            # 求根
            roots = np.roots(lpc_coeffs)

            # 只保留上半平面的根
            roots = roots[np.imag(roots) >= 0]

            # 计算频率和带宽
            angles = np.angle(roots)
            magnitudes = np.abs(roots)

            freqs = angles * self.sample_rate / (2 * np.pi)
            bws = -np.log(magnitudes) * self.sample_rate / np.pi

            # 过滤：频率在合理范围，带宽合理
            valid = (freqs > 50) & (freqs < self.sample_rate / 2) & (bws > 10) & (bws < 1000)
            freqs = freqs[valid]
            bws = bws[valid]

            # 按频率排序
            sort_idx = np.argsort(freqs)
            freqs = freqs[sort_idx]
            bws = bws[sort_idx]

            # 取前 n 个
            n = min(self.n_formants, len(freqs))
            formant_freqs[i, :n] = freqs[:n]
            formant_bw[i, :n] = bws[:n]

        return times, formant_freqs, formant_bw

    @staticmethod
    def _levinson_durbin(signal: np.ndarray, order: int) -> np.ndarray:
        """Levinson-Durbin 算法求解 LPC 系数。

        Args:
            signal: 输入信号帧
            order: LPC 阶数

        Returns:
            LPC 系数数组（长度为 order+1，第一个为 1.0）
        """
        # 计算自相关
        r = np.correlate(signal, signal, mode="full")
        mid = len(r) // 2
        r = r[mid : mid + order + 1]

        if r[0] == 0:
            return np.ones(order + 1)

        # Levinson-Durbin 递推
        a = np.zeros(order + 1)
        a[0] = 1.0
        e = r[0]
        k = np.zeros(order)

        for i in range(order):
            # 反射系数
            sum_val = np.sum(a[1 : i + 1] * r[i:0:-1])
            k[i] = -(r[i + 1] + sum_val) / e

            # 更新预测系数
            a_new = a.copy()
            for j in range(1, i + 2):
                a_new[j] = a[j] + k[i] * a[i + 1 - j]
            a = a_new

            # 更新预测误差
            e = e * (1 - k[i] ** 2)

        return a
