# SPDX-License-Identifier: GPL-3.0-only
"""窗函数模块。"""

from __future__ import annotations

import numpy as np


class WindowFunction:
    """窗函数工厂。

    提供常用窗函数及其属性。
    """

    # 支持的窗函数列表
    SUPPORTED = [
        "rectangular",
        "hann",
        "hamming",
        "blackman",
        "blackman-harris",
        "flattop",
        "kaiser",
        "gaussian",
    ]

    @staticmethod
    def get(name: str, size: int, **kwargs) -> np.ndarray:
        """获取窗函数。

        Args:
            name: 窗函数名称
            size: 窗长（采样点数）
            **kwargs: 额外参数（如 kaiser 的 beta）

        Returns:
            窗函数数组
        """
        name = name.lower().replace("_", "-")

        if name in ("rectangular", "boxcar", "rect"):
            return np.ones(size)
        elif name == "hann":
            return np.hanning(size)
        elif name == "hamming":
            return np.hamming(size)
        elif name == "blackman":
            return np.blackman(size)
        elif name == "blackman-harris":
            return WindowFunction._blackman_harris(size)
        elif name == "flattop":
            return WindowFunction._flattop(size)
        elif name == "kaiser":
            beta = kwargs.get("beta", 14.0)
            return np.kaiser(size, beta)
        elif name == "gaussian":
            sigma = kwargs.get("sigma", 0.4)
            return WindowFunction._gaussian(size, sigma)
        else:
            # 默认 hann
            return np.hanning(size)

    @staticmethod
    def _blackman_harris(size: int) -> np.ndarray:
        """Blackman-Harris 窗。"""
        n = np.arange(size)
        a0 = 0.35875
        a1 = 0.48829
        a2 = 0.14128
        a3 = 0.01168
        return (
            a0
            - a1 * np.cos(2 * np.pi * n / (size - 1))
            + a2 * np.cos(4 * np.pi * n / (size - 1))
            - a3 * np.cos(6 * np.pi * n / (size - 1))
        )

    @staticmethod
    def _flattop(size: int) -> np.ndarray:
        """平顶窗（用于精确幅度测量）。"""
        n = np.arange(size)
        a0 = 0.21557895
        a1 = 0.41663158
        a2 = 0.277263158
        a3 = 0.083578947
        a4 = 0.006947368
        return (
            a0
            - a1 * np.cos(2 * np.pi * n / (size - 1))
            + a2 * np.cos(4 * np.pi * n / (size - 1))
            - a3 * np.cos(6 * np.pi * n / (size - 1))
            + a4 * np.cos(8 * np.pi * n / (size - 1))
        )

    @staticmethod
    def _gaussian(size: int, sigma: float = 0.4) -> np.ndarray:
        """高斯窗。"""
        n = np.arange(size) - (size - 1) / 2
        return np.exp(-0.5 * (n / (sigma * (size - 1) / 2)) ** 2)
