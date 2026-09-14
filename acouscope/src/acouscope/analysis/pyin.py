# SPDX-License-Identifier: GPL-3.0-only
"""概率化 YIN 基频检测（pYIN 的单帧候选层）。

PYIN_CLEANROOM_V1 — 本模块依据以下论文与数学原理 clean-room 重写：
- de Cheveigné & Kawahara (2002) YIN: 差分函数 d(tau)、累计均值归一化 d'(tau)、
  绝对阈值、抛物线插值。
- Mauch & Dixon (2014, ICASSP) pYIN: 将 YIN 的绝对阈值视为随机变量
  t ~ Beta(a, a(1-m)/m)（均值 m），对每个局部谷底 tau_i 计算其被经典 YIN
  选中的概率 P(d'_i < t <= b_i)，其中 b_i = min(tau 序在前的谷底值)，
  得到多候选 (f0, p) 及有声概率。

禁止将本实现回译为任何 C++ 参考品的逐行对应。
"""

from __future__ import annotations

import numpy as np

PYIN_MARKER = "PYIN_CLEANROOM_V1"
PYIN_MIN_FREQ = 61.735  # HMM 音高网格基频（MIDI 35），20 cent 网格下界


def difference_function(frame: np.ndarray) -> np.ndarray:
    """YIN 差分函数 d(tau), tau = 0..W（W = len(frame)//2），FFT 互相关法。

    d(tau) = sum_{j=0}^{W-1} (x[j] - x[j+tau])^2
           = E_head + E_shift(tau) - 2*c(tau)
    其中 c(tau) = sum_{j=0}^{W-1} x[j]*x[j+tau] 为**固定 W 窗互相关**
    （x[:W] 与 x 的 FFT 互相关；de Cheveigné & Kawahara 2002 式(1)-(2)），
    零填充至 >= N+W 防循环卷积混叠；E_* 为平方和（能量前缀和）。
    注意：不可用全帧线性自相关替代（其窗长随 tau 收缩，会使 d(tau) 出现
    人为的零截断假谷底）。
    """
    x = np.asarray(frame, dtype=np.float64)
    n = x.size
    w = n // 2
    fft_len = 1 << int(np.ceil(np.log2(n + w)))
    fa = np.fft.rfft(x[:w], fft_len)
    fb = np.fft.rfft(x, fft_len)
    corr = np.fft.irfft(np.conj(fa) * fb, fft_len)[: w + 1]
    power = np.concatenate(([0.0], np.cumsum(x * x)))
    e_head = power[w] - power[0]
    idx = np.arange(w + 1)
    e_shift = power[w + idx] - power[idx]
    d = np.maximum(e_head + e_shift - 2.0 * corr, 0.0)
    return d


def cumulative_mean_normalized(d: np.ndarray) -> np.ndarray:
    """累计均值归一化 d'(tau) = d(tau) * tau / sum_{j=1..tau} d(j)。

    （YIN 步骤 2；tau=0 处定义为 1）
    """
    w = d.size
    dnorm = np.ones(w, dtype=np.float64)
    csum = np.cumsum(d[1:])
    denom = np.where(csum > 1e-20, csum, 1e-20)
    dnorm[1:] = d[1:] * np.arange(1, w) / denom
    return dnorm


def local_minima(dnorm: np.ndarray, tau_min: int, tau_max: int) -> np.ndarray:
    """[tau_min, tau_max) 内 d' 的局部谷底索引（谷值 < 左邻 且 <= 右邻）。"""
    lo, hi = max(1, tau_min), min(tau_max, dnorm.size - 1)
    if hi - lo < 2:
        return np.array([], dtype=int)
    seg = dnorm[lo - 1 : hi + 1]
    inner = np.where((seg[1:-1] < seg[:-2]) & (seg[1:-1] <= seg[2:]))[0]
    return inner + lo


def parabolic_interpolate(dnorm: np.ndarray, tau: int) -> float:
    """抛物线插值细化周期（亚采样精度）。"""
    if tau <= 0 or tau >= dnorm.size - 1:
        return float(tau)
    a, b, c = dnorm[tau - 1], dnorm[tau], dnorm[tau + 1]
    denom = 2.0 * (a - 2.0 * b + c)
    if abs(denom) < 1e-12:
        return float(tau)
    delta = float(np.clip((a - c) / denom, -1.0, 1.0))
    return float(tau) + delta


# ---- Beta 分布 CDF（纯 math/numpy 实现）----
# 依据标准数学定义：正则化不完全 Beta 函数 I_x(a,b)，连分式展开 + Lentz 加速。
# 当前 venv 的 scipy 与 numpy 组合不可用（实测 import 即崩），故零 scipy 依赖。
def _betacf(a: float, b: float, x: float, max_iter: int = 300) -> float:
    """正则化不完全 Beta 的连分式核（Lentz 加速收敛）。"""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def _beta_cdf(x: float, a: float, b: float) -> float:
    """Beta(a, b) 分布 CDF = I_x(a, b)（标准数学定义，连续分式求值）。"""
    from math import exp, lgamma, log

    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        lgamma(a + b) - lgamma(a) - lgamma(b)
        + a * log(x) + b * log(1.0 - x)
    )
    front = exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_cdf_arr(xs: np.ndarray, a: float, b: float) -> np.ndarray:
    """Beta CDF 的逐元素版本（候选数量级小，标量循环即可）。"""
    arr = np.asarray(xs, dtype=np.float64)
    out = [_beta_cdf(float(v), a, b) for v in arr.ravel()]
    return np.array(out).reshape(arr.shape)


def pyin_frame(
    frame: np.ndarray,
    sr: float,
    fmin: float = 40.0,
    fmax: float = 2000.0,
    beta_mean: float = 0.15,
    beta_a: float = 2.0,
) -> tuple[list[tuple[float, float]], float]:
    """单帧概率化 YIN。

    Returns:
        (candidates, voiced_prob)
        candidates: [(f0_hz, prob), ...]，f0 经抛物线插值，按概率降序；
        voiced_prob: 候选概率之和（清音帧接近 0）。

    概率模型（Mauch & Dixon 2014）：阈值 t ~ Beta(a, a(1-m)/m)。
    经典 YIN 选"第一个 d' 低于阈值 t 的谷底"，故谷底 tau_i（按 tau 升序）
    被选中当且仅当 d'_i < t <= b_i，b_i = min(tau 序在前的谷底 d' 值)，
    p_i = BetaCDF(b_i) - BetaCDF(d'_i)。
    """
    d = difference_function(frame)
    dnorm = cumulative_mean_normalized(d)
    tau_min = max(2, int(sr / fmax))
    tau_max = min(dnorm.size - 2, int(sr / fmin))
    if tau_max <= tau_min + 2:
        return [], 0.0
    minima = local_minima(dnorm, tau_min, tau_max + 1)
    if minima.size == 0:
        return [], 0.0
    # 次谐波幽灵抑制（超量程基频，AT-07-3）：按 YIN 绝对阈值原理
    # （de Cheveigné & Kawahara 2002），真实周期性 = 全范围第一个
    # d' < 0.1 的谷底。若该谷底频率 > fmax（真实基频在量程外），
    # 量程内 tau ≈ k·tau1（k≥2）的等深谷是其次谐波幽灵，剔除之，
    # 否则 3000Hz 纯音会被误检为其半频 1500Hz（2026-09-04 沙箱实测）。
    deep = local_minima(dnorm, 2, dnorm.size - 2)
    deep = deep[dnorm[deep] < 0.1]
    if deep.size and sr / int(deep[0]) > fmax:
        # tau1 取亚采样精度（抛物线插值）：整数索引舍入误差会随 k 放大，
        # 3000Hz 的 k=5 幽灵 600Hz 曾因此漏检（15×5=75 vs 实际 73.5，
        # 2026-09-04 沙箱实测）
        tau1 = parabolic_interpolate(dnorm, int(deep[0]))
        if tau1 > 0 and sr / tau1 > fmax:
            k = np.round(minima / tau1)
            tol = np.maximum(1.0, 0.02 * minima)
            ghost = np.abs(minima - k * tau1) <= tol
            minima = minima[~ghost]
            if minima.size == 0:
                return [], 0.0
    vals = dnorm[minima]
    running_min = np.minimum.accumulate(vals)
    upper = np.concatenate(([1.0], running_min[:-1]))
    b_param = beta_a * (1.0 - beta_mean) / beta_mean
    probs = _beta_cdf_arr(upper, beta_a, b_param) - _beta_cdf_arr(vals, beta_a, b_param)
    probs = np.clip(np.where(upper > vals, probs, 0.0), 0.0, 1.0)
    total = float(probs.sum())
    candidates: list[tuple[float, float]] = []
    for tau_i, p in zip(minima, probs):
        if p <= 0.0:
            continue
        tau_f = parabolic_interpolate(dnorm, int(tau_i))
        if tau_f <= 0:
            continue
        f0 = sr / tau_f
        if fmin <= f0 <= fmax:
            candidates.append((f0, float(p)))
    candidates.sort(key=lambda t: -t[1])
    return candidates, min(total, 1.0)


def pyin_candidates(
    signal: np.ndarray,
    sr: float,
    frame_size: int = 2048,
    hop_length: int = 256,
    fmin: float = 40.0,
    fmax: float = 2000.0,
    beta_mean: float = 0.15,
) -> tuple[np.ndarray, list, np.ndarray]:
    """整段信号逐帧概率化 YIN。

    帧内向量化（FFT 自相关 + 向量谷底检测）；帧间循环保留
    （自适应候选逻辑难以跨帧向量化）。

    Returns:
        (times, cand_lists, voiced_probs)
        times[i] = (i*hop + frame_size//4) / sr（pYIN 帧中心语义）
    """
    signal = np.asarray(signal, dtype=np.float64)
    if signal.size < frame_size:
        return np.array([]), [], np.array([])
    n_frames = 1 + (signal.size - frame_size) // hop_length
    times = (np.arange(n_frames) * hop_length + frame_size // 4) / sr
    strided = np.lib.stride_tricks.as_strided(
        signal,
        shape=(n_frames, frame_size),
        strides=(signal.strides[0] * hop_length, signal.strides[0]),
    )
    cand_lists: list = []
    voiced = np.zeros(n_frames, dtype=np.float64)
    for i in range(n_frames):
        cands, vp = pyin_frame(strided[i], sr, fmin, fmax, beta_mean)
        cand_lists.append(cands)
        voiced[i] = vp
    return times, cand_lists, voiced
