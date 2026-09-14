# SPDX-License-Identifier: GPL-3.0-only
"""音高分析模块。

提供多种音高检测算法：YIN、HPS、自相关法等。
核心算法（YIN）采用纯 numpy 实现，不依赖第三方库。
"""

from __future__ import annotations

import numpy as np


class PitchAnalyzer:
    """音高分析器。

    提供多种音高检测算法：YIN、HPS 等。
    """

    def __init__(self, sample_rate: float = 44100.0, fmin: float = 50.0, fmax: float = 2000.0):
        """
        Args:
            sample_rate: 采样率
            fmin: 最低检测频率
            fmax: 最高检测频率
        """
        self.sample_rate = sample_rate
        self.fmin = fmin
        self.fmax = fmax

    # ------------------------------------------------------------------
    # YIN 算法（主算法）
    # ------------------------------------------------------------------

    def detect_yin(
        self,
        signal: np.ndarray,
        frame_size: int = 2048,
        hop_length: int = 512,
        threshold: float = 0.15,
    ) -> tuple[np.ndarray, np.ndarray]:
        """使用 YIN 算法检测音高。

        采用纯 numpy 实现的标准 YIN 算法，精度高、不依赖第三方库。

        Args:
            signal: 输入信号
            frame_size: 帧长
            hop_length: 帧移
            threshold: YIN 绝对阈值（通常 0.1-0.2）

        Returns:
            (时间轴, f0 频率 Hz) — 无声帧为 0
        """
        n_frames = 1 + (len(signal) - frame_size) // hop_length
        if n_frames <= 0:
            # 信号比一帧还短
            return np.array([]), np.array([])
        f0 = np.zeros(n_frames)
        times = np.arange(n_frames) * hop_length / self.sample_rate

        for i in range(n_frames):
            start = i * hop_length
            frame = signal[start : start + frame_size]
            f0[i] = self._yin_frame(frame, threshold)

        return times, f0

    def _yin_frame(self, frame: np.ndarray, threshold: float) -> float:
        """单帧 YIN 算法。

        实现完整的 YIN 步骤：
        1. 差分函数 d(τ)
        2. 累计均值归一化 d'(τ)
        3. 绝对阈值
        4. 抛物线插值

        Args:
            frame: 单帧信号
            threshold: 绝对阈值

        Returns:
            基频 Hz，无声返回 0
        """
        sr = self.sample_rate
        tau_min = int(sr / self.fmax)
        tau_max = int(sr / self.fmin)

        # 限制 tau_max 不超过帧长的一半
        if tau_max >= len(frame) // 2:
            tau_max = len(frame) // 2 - 1

        if tau_min >= tau_max or tau_max < 2:
            return 0.0

        # 步骤 1: 差分函数 d(τ)
        # 使用快速计算：基于自相关
        w = len(frame) // 2  # 窗口大小

        # 计算 x[tau:w+tau] 和 x[:w] 的差的平方和
        # d(tau) = sum_{j=0}^{w-1} (x[j] - x[j+tau])^2
        d = np.zeros(tau_max + 1)
        for tau in range(tau_max + 1):
            diff = frame[:w] - frame[tau : tau + w]
            d[tau] = np.dot(diff, diff)

        # 步骤 2: 累计均值归一化 d'(τ)
        d_norm = np.ones(tau_max + 1)
        running_sum = 0.0
        for tau in range(1, tau_max + 1):
            running_sum += d[tau]
            if running_sum > 1e-20:
                d_norm[tau] = d[tau] * tau / running_sum

        # 步骤 3: 找绝对阈值以下的第一个最小值
        # 需要找到一个谷值（局部最小值）低于阈值
        tau_est = -1

        for tau in range(tau_min, tau_max):
            if d_norm[tau] < threshold:
                # 检查是否是局部最小值
                if d_norm[tau] < d_norm[tau - 1] and d_norm[tau] <= d_norm[tau + 1]:
                    tau_est = tau
                    break
                # 或者是下降趋势中的点（下一个点更小？）
                if d_norm[tau + 1] < d_norm[tau]:
                    continue  # 还在下降，继续找
                # 已经过了最低点，取这个点
                tau_est = tau
                break

        # 如果没找到低于阈值的点，取全局最小值
        if tau_est < 0:
            min_idx = np.argmin(d_norm[tau_min : tau_max + 1])
            tau_est = tau_min + min_idx

            # 如果全局最小值也很大，认为是无声
            if d_norm[tau_est] > 0.5:
                return 0.0

        # 步骤 4: 抛物线插值提高精度
        if tau_est > 0 and tau_est < tau_max:
            a = d_norm[tau_est - 1]
            b = d_norm[tau_est]
            c = d_norm[tau_est + 1]
            denom = 2 * (a - 2 * b + c)
            if abs(denom) > 1e-10:
                delta = (a - c) / denom
                tau_est = tau_est + delta

        return sr / max(tau_est, 1)

    # ------------------------------------------------------------------
    # HPS 算法
    # ------------------------------------------------------------------

    def detect_hps(
        self,
        signal: np.ndarray,
        fft_size: int = 4096,
        n_harmonics: int = 5,
        window: str = "hann",
    ) -> float:
        """使用 HPS（谐波积谱）算法检测单帧音高。

        HPS 对富含谐波的信号效果好，但精度低于 YIN。

        Args:
            signal: 输入信号（单帧）
            fft_size: FFT 大小
            n_harmonics: 谐波数
            window: 窗函数

        Returns:
            基频 Hz
        """
        from acouscope.dsp import FFTEngine

        engine = FFTEngine(size=fft_size, window=window)
        freqs_norm, magnitude = engine.magnitude_spectrum(signal, db_scale=False)

        # HPS: 下采样频谱并相乘
        hps_spectrum = magnitude.copy()
        for h in range(2, n_harmonics + 1):
            downsampled = magnitude[::h]
            n = min(len(hps_spectrum), len(downsampled))
            hps_spectrum[:n] *= downsampled

        # 限制搜索范围
        min_bin = max(1, int(self.fmin / self.sample_rate * fft_size))
        max_bin = int(self.fmax / self.sample_rate * fft_size)
        max_bin = min(max_bin, len(hps_spectrum) - 1)

        if max_bin <= min_bin:
            return 0.0

        # 找峰值
        peak_bin = int(np.argmax(hps_spectrum[min_bin:max_bin])) + min_bin

        # 抛物线插值
        if peak_bin > 0 and peak_bin < len(hps_spectrum) - 1:
            a = hps_spectrum[peak_bin - 1]
            b = hps_spectrum[peak_bin]
            c = hps_spectrum[peak_bin + 1]
            denom = a - 2 * b + c
            if abs(denom) > 1e-10:
                peak_bin += 0.5 * (a - c) / denom

        return peak_bin * self.sample_rate / fft_size

# ============================================================
# pYIN 统一入口（T-001-3）PYIN_ENTRY_V1
# 依据: Mauch & Dixon 2014 (ICASSP) pYIN（clean-room）；
# 底层 pyin.py / pitch_hmm.py 见各自 docstring。
# ============================================================

from dataclasses import dataclass


@dataclass
class PitchTrack:
    """pYIN 音高轨迹。

    f0_hz: NaN = 未检出（清音/超量程），禁止输出错误数值；
    confidence: 每帧有声概率 [0,1]（候选概率和）；
    times: 帧中心（秒），times[i] = (i*hop + frame_size//4)/sr（毫秒级语义）。
    """

    times: np.ndarray
    f0_hz: np.ndarray
    confidence: np.ndarray
    fmin: float = 40.0
    fmax: float = 2000.0
    cent_ref: float = 440.0

    def cents(self, ref: "float | None" = None) -> np.ndarray:
        """Hz → 音分（参照 cent_ref，可配置；NaN 传递）。"""
        r = self.cent_ref if ref is None else ref
        with np.errstate(invalid="ignore"):
            return 1200.0 * np.log2(
                np.where(self.f0_hz > 0, self.f0_hz, np.nan) / r
            )


def detect_pyin(
    signal: np.ndarray,
    sr: float,
    frame_size: int = 4096,
    hop_length: int = 256,
    fmin: float = 40.0,
    fmax: float = 2000.0,
    beta_mean: float = 0.15,
    cent_ref: float = 440.0,
    fixed_lag: "int | None" = 100,
) -> "PitchTrack":
    """pYIN 音高检测统一入口。

    输出 Hz + cent（cent_ref 可配置）+ 置信度；
    量程 [fmin, fmax] 可配置，量程外/清音帧 f0 为 NaN 并以低 confidence 标记
    （AT-07-3 语义：给提示而非错误值）。
    frame_size 默认 4096：SNR=10dB 下检出率达标所需（2048 时实测 83%<85%，
    2026-09-04 沙箱实测），93ms 窗对颤音/扫频精度无回归。
    """
    from acouscope.analysis.pyin import pyin_candidates
    from acouscope.analysis.pitch_hmm import PitchHMM

    times, cands, voiced = pyin_candidates(
        signal, sr, frame_size, hop_length, fmin, fmax, beta_mean
    )
    hmm = PitchHMM()
    res = hmm.decode(cands, fixed_lag=fixed_lag)
    f0 = np.where(res.voiced & np.isfinite(res.f0_hz), res.f0_hz, np.nan)
    # 硬门控 1：原始候选为空的帧强制 NaN
    no_cand = np.array([len(c) == 0 for c in cands])
    f0[no_cand] = np.nan
    # 硬门控 2：帧能量低于信号峰值 10% 的帧强制 NaN
    # （93ms 窗口在静音边界仍可能含相邻有声信号候选，
    # 能量门控抑制弱过渡帧；剩余高能量边界帧是窗口固有效应）
    if len(signal) >= frame_size:
        n_fr = 1 + (len(signal) - frame_size) // hop_length
        rms = np.array([
            np.sqrt(np.mean(signal[i*hop_length : i*hop_length+frame_size] ** 2))
            for i in range(n_fr)
        ])
        if rms.max() > 0:
            f0[rms < 0.10 * rms.max()] = np.nan
    return PitchTrack(
        times=times,
        f0_hz=f0,
        confidence=np.asarray(voiced, dtype=float),
        fmin=fmin,
        fmax=fmax,
        cent_ref=cent_ref,
    )

