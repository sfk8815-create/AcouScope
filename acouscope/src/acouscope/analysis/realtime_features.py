# SPDX-License-Identifier: GPL-3.0-only
"""实时音频特征分析：借鉴 Realtime_PyAudio_FFT 的算法。

提供：
- 三频段（低/中/高）能量包络：STFT 分帧 → 频段功率 RMS →
  非对称指数包络（快攻慢放）→ tanh 自动缩放到 [0, 1]
- 128-bin 对数频率平均频谱（30 Hz ~ Nyquist 几何分布）
- 逐频段 onset 检测：快/慢双包络差分新颖性 + 自适应阈值 +
  Schmitt 触发 + 不应期
- BPM 估计：低频 onset 间隔（IOI）中位数 + 离群值拒绝 + 八度折叠

只用 numpy：一次分块 STFT 同时产出频段包络与对数频谱，
内存与文件长度解耦（分块累积）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Realtime_PyAudio_FFT 的频段划分与配色约定
BAND_RANGES = {
    "low":  (40.0, 250.0),
    "mid":  (250.0, 2000.0),
    "high": (2000.0, 16000.0),
}
BAND_COLORS = {"low": "#5a8dee", "mid": "#79d17a", "high": "#e8a857"}
BAND_LABELS = {"low": "低频 40–250 Hz", "mid": "中频 250–2k Hz", "high": "高频 2k–16k Hz"}

# onset 检测参数（对应原项目 onset.py 默认值）
ONSET_FAST_TAU = 0.012          # 快包络时间常数 (s)
ONSET_SLOW_TAU = {"low": 0.30, "mid": 0.20, "high": 0.15}
ONSET_THRESHOLD_TAU = 1.0       # 自适应阈值 EMA 时间常数 (s)
ONSET_K_HIGH = 1.8              # 触发阈值 = K_HIGH × 阈值均值
ONSET_K_LOW = 0.6               # 释放阈值 = K_LOW × 阈值均值
ONSET_ABS_FLOOR = 0.10          # 触发阈值绝对下限
ONSET_MIN_IOI = {"low": 0.25, "mid": 0.18, "high": 0.12}  # 不应期 (s)

# 包络与自动缩放参数（对应原项目 features.py 默认值）
ENV_ATTACK_TAU = 0.05
ENV_RELEASE_TAU = 0.35
PEAK_ATTACK_TAU = 0.255
PEAK_RELEASE_TAU = 30.0
NOISE_FLOOR = 3.21e-5

_STFT_WINDOW = 1024
_CHUNK_SECONDS = 30.0


def tau_to_alpha(dt: float, tau: float) -> float:
    """离散化一阶指数平滑系数：alpha = 1 - exp(-dt/tau)。"""
    return 1.0 - math.exp(-dt / max(tau, 1e-3))


def _mono(data: np.ndarray) -> np.ndarray:
    x = np.asarray(data, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x


def _stft_power_chunk(x: np.ndarray, window: np.ndarray, hop: int) -> np.ndarray:
    """单个数据块的加窗帧功率谱：返回 (n_frames, n_rfft)。"""
    n_fft = len(window)
    n_frames = max(0, (len(x) - n_fft) // hop + 1)
    if n_frames == 0:
        return np.empty((0, n_fft // 2 + 1))
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = x[idx] * window
    spec = np.fft.rfft(frames, axis=1)
    return np.abs(spec) ** 2


def compute_band_envelopes(
    data: np.ndarray,
    sample_rate: float,
    hop_ms: float = 10.0,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """三频段能量包络：STFT 频段功率 → 非对称包络 → tanh 自动缩放。

    Returns:
        (times, bands)：帧时间与各频段 [0,1] 包络。
    """
    x = _mono(data)
    sr = float(sample_rate)
    hop = max(1, int(sr * hop_ms / 1000.0))
    n_fft = min(_STFT_WINDOW, max(256, 1 << int(math.log2(max(len(x), 256)))))
    n_fft = min(n_fft, _STFT_WINDOW)
    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)

    bin_masks = {}
    for name, (lo, hi) in BAND_RANGES.items():
        bin_masks[name] = (freqs >= lo) & (freqs <= min(hi, sr / 2.0))

    band_rms: dict[str, list[np.ndarray]] = {name: [] for name in BAND_RANGES}
    times_list: list[np.ndarray] = []

    chunk_len = max(n_fft, int(sr * _CHUNK_SECONDS))
    for start in range(0, len(x), chunk_len - n_fft if chunk_len > n_fft else chunk_len):
        block = x[start: start + chunk_len]
        power = _stft_power_chunk(block, window, hop)
        if power.shape[0] == 0:
            break
        n_frames = power.shape[0]
        times_list.append((start / sr) + (np.arange(n_frames) + 0.5) * hop / sr)
        for name, mask in bin_masks.items():
            if not mask.any():
                band_rms[name].append(np.zeros(n_frames))
            else:
                band_pw = power[:, mask].mean(axis=1)
                band_rms[name].append(np.sqrt(band_pw))

    if not times_list:
        return np.zeros(0), {name: np.zeros(0) for name in BAND_RANGES}

    times = np.concatenate(times_list)
    n = len(times)
    dt = hop / sr
    a_env_atk = tau_to_alpha(dt, ENV_ATTACK_TAU)
    a_env_rel = tau_to_alpha(dt, ENV_RELEASE_TAU)
    a_pk_atk = tau_to_alpha(dt, PEAK_ATTACK_TAU)
    a_pk_rel = tau_to_alpha(dt, PEAK_RELEASE_TAU)
    nf = NOISE_FLOOR

    bands: dict[str, np.ndarray] = {}
    for name in BAND_RANGES:
        rms = np.concatenate(band_rms[name])[:n]
        vals = np.empty(n)
        s_prev = 0.0
        peak = nf
        nf2 = nf * nf
        for i in range(n):
            c = rms[i] * rms[i] - nf2
            v = math.sqrt(c) if c > 0.0 else 0.0

            d = v - s_prev
            s_prev += (a_env_atk if d > 0 else a_env_rel) * d

            dp = s_prev - peak
            peak += (a_pk_atk if dp > 0 else a_pk_rel) * dp

            denom = peak if peak > nf else nf
            vals[i] = math.tanh(s_prev / denom)

        bands[name] = np.clip(vals, 0.0, 1.0)

    return times, bands


def compute_frame_log_spectrogram(
    data: np.ndarray,
    sample_rate: float,
    n_bins: int = 128,
    f_min: float = 30.0,
    hop_ms: float = 20.0,
    db_floor: float = -90.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """逐帧 128-bin 对数频谱矩阵（供播放时实时取帧）。

    一次预计算，播放期间只做数组切片——这正是离线文件实现
    Realtime_PyAudio_FFT 实时观感的关键：动态刷新零 FFT 开销。

    Returns:
        (times, centers_hz, db_matrix)：帧中心时间 (n_frames,)、
        对数 bin 中心 (n_bins,)、dB 矩阵 (n_frames, n_bins) float32。
    """
    x = _mono(data)
    sr = float(sample_rate)
    n_fft = min(_STFT_WINDOW, max(256, 1 << int(math.log2(max(len(x), 256)))))
    window = np.hanning(n_fft)
    n_rfft = n_fft // 2 + 1
    hop = max(1, int(sr * hop_ms / 1000.0))

    assign, counts, centers = log_bin_map(n_rfft, sr, n_bins, f_min)
    # 线性 bin → 对数 bin 的平均矩阵（每列除以计数，直接矩阵乘出平均功率）
    m_avg = np.zeros((n_rfft, n_bins), dtype=np.float32)
    valid = assign >= 0
    np.add.at(m_avg, (np.where(valid)[0], assign[valid]), 1.0)
    nz = counts > 0
    m_avg[:, nz] /= counts[nz]

    rows: list[np.ndarray] = []
    times_rows: list[np.ndarray] = []
    chunk_len = max(n_fft, int(sr * _CHUNK_SECONDS))
    step = chunk_len - n_fft if chunk_len > n_fft else chunk_len
    for start in range(0, len(x), step):
        block = x[start: start + chunk_len]
        power = _stft_power_chunk(block, window, hop)
        if power.shape[0] == 0:
            break
        # (n_frames, n_bins) 平均功率 → dB
        dbm = 10.0 * np.log10(np.maximum(power @ m_avg, 1e-20))
        rows.append(np.maximum(dbm, db_floor).astype(np.float32))
        times_rows.append(
            (start / sr) + (np.arange(power.shape[0]) + 0.5) * hop / sr
        )

    if not rows:
        return (np.zeros(0), centers, np.zeros((0, n_bins), dtype=np.float32))

    return np.concatenate(times_rows), centers, np.vstack(rows)


def compute_log_spectrum(
    data: np.ndarray,
    sample_rate: float,
    n_bins: int = 128,
    f_min: float = 30.0,
    db_floor: float = -90.0,
) -> tuple[np.ndarray, np.ndarray]:
    """128-bin 对数频率平均功率谱（Welch 风格，分块累积）。

    Returns:
        (centers_hz, db)：对数 bin 中心频率与 dB 值（钳位到 db_floor）。
    """
    x = _mono(data)
    sr = float(sample_rate)
    n_fft = min(_STFT_WINDOW, max(256, 1 << int(math.log2(max(len(x), 256)))))
    window = np.hanning(n_fft)
    n_rfft = n_fft // 2 + 1

    power_sum = np.zeros(n_rfft)
    n_frames_total = 0
    chunk_len = max(n_fft, int(sr * _CHUNK_SECONDS))
    for start in range(0, len(x), chunk_len - n_fft if chunk_len > n_fft else chunk_len):
        block = x[start: start + chunk_len]
        power = _stft_power_chunk(block, window, hop=n_fft // 2)
        if power.shape[0] == 0:
            break
        power_sum += power.sum(axis=0)
        n_frames_total += power.shape[0]

    if n_frames_total == 0:
        return np.array([f_min]), np.array([db_floor])

    power = power_sum / n_frames_total
    assign, counts, centers = log_bin_map(n_rfft, sr, n_bins, f_min)

    bins = np.zeros(n_bins)
    mask = assign >= 0
    np.add.at(bins, assign[mask], power[mask])
    nz = counts > 0
    bins[nz] /= counts[nz]

    db = 10.0 * np.log10(np.maximum(bins, 1e-20))
    return centers, np.maximum(db, db_floor)


def log_bin_map(
    n_rfft: int,
    sample_rate: float,
    n_bins: int = 128,
    f_min: float = 30.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """线性 rFFT bin → 对数 bin 映射。

    Returns:
        (assign, counts, centers)：每个 rFFT bin 所属对数 bin（-1 为
        范围外）、每个对数 bin 的线性 bin 计数、对数 bin 中心频率。
    """
    freqs = np.linspace(0.0, sample_rate / 2.0, n_rfft)
    f_max = sample_rate / 2.0
    if f_max <= f_min:
        f_max = f_min * 2.0

    edges = np.logspace(np.log10(f_min), np.log10(f_max), n_bins + 1)
    assign = np.full(n_rfft, -1, dtype=np.int64)
    valid = (freqs >= f_min) & (freqs <= f_max)
    assign[valid] = np.searchsorted(edges, freqs[valid], side="right") - 1
    assign[assign >= n_bins] = n_bins - 1

    counts = np.bincount(assign[assign >= 0], minlength=n_bins)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return assign, counts, centers


@dataclass
class OnsetResult:
    """单频段 onset 检测结果。"""
    times: np.ndarray      # onset 时刻 (s)
    novelty: np.ndarray    # 新颖性函数（快-慢包络正差）


def detect_onsets(
    envelope: np.ndarray,
    hop_ms: float,
    band: str = "low",
) -> OnsetResult:
    """双包络差分 onset 检测。

    新颖性 = max(0, fast_env - slow_env)；对新颖性做慢速 EMA 得自适应
    阈值，Schmitt 触发（上沿 K_HIGH×阈值，下沿 K_LOW×阈值）加不应期。
    """
    dt = hop_ms / 1000.0
    a_fast = tau_to_alpha(dt, ONSET_FAST_TAU)
    a_slow = tau_to_alpha(dt, ONSET_SLOW_TAU.get(band, 0.2))
    a_thr = tau_to_alpha(dt, ONSET_THRESHOLD_TAU)
    min_ioi = ONSET_MIN_IOI.get(band, 0.2)

    n = len(envelope)
    novelty = np.zeros(n)
    fast = slow = thr_avg = 0.0
    armed = False
    last_fire = -1e9
    fires: list[float] = []

    for i in range(n):
        xv = float(envelope[i])
        fast += a_fast * (xv - fast)
        slow += a_slow * (xv - slow)
        nov = fast - slow
        if nov < 0.0:
            nov = 0.0
        novelty[i] = nov

        thr_avg += a_thr * (nov - thr_avg)
        th = max(ONSET_K_HIGH * thr_avg, ONSET_ABS_FLOOR)
        tl = ONSET_K_LOW * thr_avg

        t = i * dt
        if not armed:
            if nov > th and (t - last_fire) > min_ioi:
                fires.append(t)
                armed = True
                last_fire = t
        elif nov < tl:
            armed = False

    return OnsetResult(times=np.asarray(fires), novelty=novelty)


def estimate_bpm(
    onset_times: np.ndarray,
    ring_size: int = 12,
    min_bpm: float = 60.0,
    max_bpm: float = 180.0,
) -> float:
    """由 onset 间隔估计 BPM：IOI 中位数 + 离群值拒绝 + 八度折叠。

    返回 0.0 表示样本不足（少于 4 个 onset）。
    """
    ot = list(onset_times)[-ring_size:]
    if len(ot) < 4:
        return 0.0

    iois = sorted(ot[i + 1] - ot[i] for i in range(len(ot) - 1))
    m = iois[len(iois) // 2]
    if m <= 0.0:
        return 0.0

    kept = [v for v in iois if 0.5 * m < v < 2.0 * m]
    if len(kept) < 2:
        return 0.0

    med = kept[len(kept) // 2]
    bpm = 60.0 / med
    while bpm < min_bpm:
        bpm *= 2.0
    while bpm > max_bpm:
        bpm *= 0.5
    return bpm


def analyze_all(
    data: np.ndarray,
    sample_rate: float,
    hop_ms: float | None = None,
    n_bins: int = 128,
) -> dict:
    """一键计算全部实时特征（供 UI 调用）。

    hop_ms 缺省时自适应：总帧数封顶 ~4000，避免长文件
    Python 逐帧循环造成打开卡顿（>40s 文件逐步加大步长）。
    """
    if hop_ms is None:
        duration_s = len(_mono(data)) / float(sample_rate)
        hop_ms = min(50.0, max(10.0, duration_s * 1000.0 / 4000.0))
    times, bands = compute_band_envelopes(data, sample_rate, hop_ms=hop_ms)
    onsets = {
        name: detect_onsets(bands[name], hop_ms, name)
        for name in BAND_RANGES
    }
    centers, db = compute_log_spectrum(data, sample_rate, n_bins=n_bins)
    bpm = estimate_bpm(onsets["low"].times)
    return {
        "times": times,
        "bands": bands,
        "onsets": onsets,
        "spectrum_freqs": centers,
        "spectrum_db": db,
        "bpm": bpm,
        "hop_ms": hop_ms,
    }
