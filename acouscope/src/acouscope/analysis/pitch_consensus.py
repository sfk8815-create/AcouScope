# SPDX-License-Identifier: GPL-3.0-only
"""T08 多算法音高一致性（纯 numpy，无 Qt；只用仓内三个检测后端）。

三个相互独立的仓内算法：YIN（时域差分）、pYIN（候选 + HMM 平滑）、
HPS（频域谐波积谱）。返回三算法读数、两两音分差、一致性判定，以及
基于 rFFT 谱峰的多声部适用性判定（整数倍谐波列视为单音，不判多声部）。

本模块只消费 ``acouscope.analysis.pitch`` 暴露的既有函数，不引入任何
外部音高后端，也不改任何全局状态。
"""
from __future__ import annotations

import numpy as np

from acouscope.analysis.pitch import PitchAnalyzer, detect_pyin

_CENT = 1200.0
_CONSISTENT_MAX_CENT = 50.0
_PEAK_THRESHOLD = 0.3
_HARMONIC_INTEGER_TOL = 0.04
_SUBHARMONIC_TOL = 0.05
_N_ALGORITHMS = 3


def _voiced_median_pyin(signal: np.ndarray, sr: float) -> "float | None":
    """pYIN voiced 帧中位 f0；全清音返回 None。"""
    track = detect_pyin(np.asarray(signal, dtype=np.float64), float(sr))
    voiced = track.f0_hz[np.isfinite(track.f0_hz)]
    return float(np.median(voiced)) if voiced.size else None


def _voiced_median_yin(analyzer: PitchAnalyzer, signal: np.ndarray) -> "float | None":
    """YIN 有声帧（f0>0）中位；全无声返回 None。"""
    _, f0 = analyzer.detect_yin(signal)
    voiced = f0[f0 > 0]
    return float(np.median(voiced)) if voiced.size else None


def _cent_diff(a: float, b: float) -> float:
    """a 相对 b 的音分差（要求两者均为正有限值）。"""
    return float(_CENT * np.log2(a / b))


def _local_peaks(signal: np.ndarray, sr: float, threshold: float = _PEAK_THRESHOLD) -> list[float]:
    """rFFT 幅度谱中幅度 > threshold*max 的局部峰频率（Hz，升序）。"""
    mag = np.abs(np.fft.rfft(np.asarray(signal, dtype=np.float64)))
    if mag.size < 3:
        return []
    peak = float(mag.max())
    if peak <= 0.0:
        return []
    freqs = np.fft.rfftfreq(len(signal), 1.0 / float(sr))
    out: list[float] = []
    for k in range(1, len(mag) - 1):
        if mag[k] > threshold * peak and mag[k] >= mag[k - 1] and mag[k] > mag[k + 1]:
            out.append(float(freqs[k]))
    return out


def _is_integer_multiple(ratio: float) -> bool:
    """比值是否接近 >=2 的整数（2.0 / 3.0 / …）——单音谐波列特征。"""
    k = round(ratio)
    return k >= 2 and abs(ratio - k) <= _HARMONIC_INTEGER_TOL


def _multi_pitch_reason(peaks: list[float], pyin_hz: float) -> "str | None":
    """谱峰多声部判定：命中返回 reason，否则 None（视为单音）。"""
    if not peaks:
        return None
    base = peaks[0]
    # 整数倍比（2.0 / 3.0 / …）视为单音谐波，先从候选峰里剔除
    candidates = [
        p for p in peaks if base <= 0.0 or not _is_integer_multiple(p / base)
    ]
    hit = False
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            lo, hi = candidates[i], candidates[j]
            if lo <= 0.0:
                continue
            ratio = hi / lo
            # 整数倍比再次显式排除（单音谐波），不判多声部
            if _is_integer_multiple(ratio):
                continue
            if (1.4 <= ratio <= 1.6 or 1.2 <= ratio <= 1.35) and (hi - lo) > 100.0:
                hit = True
                break
        if hit:
            break
    if not hit:
        return None
    reason = "multi-pitch"
    # pYIN 中位接近某峰的 1/2（±5%）→ 次谐波证据
    for p in peaks:
        half = p / 2.0
        if half > 0.0 and abs(pyin_hz - half) <= _SUBHARMONIC_TOL * half:
            reason += ";sub-harmonic"
            break
    return reason


def multi_algorithm_f0(signal: np.ndarray, sr: int) -> dict:
    """多算法音高一致性与多声部适用性。

    Returns:
        dict：``pyin_hz`` / ``yin_hz`` / ``hps_hz``（三算法读数）、
        ``pairwise_cent_diffs``（三对音分差）、``consistent``（纯音一致性）、
        ``applicable`` / ``reason``（多声部与静音适用性）、``n_algorithms``。

    纯音：``consistent = max(|pairwise_cent_diffs|) <= 50.0``、``applicable=True``、
    ``reason="ok"``；多声部：``applicable=False``；静音/无有效 f0：``no-voiced``。
    """
    x = np.asarray(signal, dtype=np.float64)
    analyzer = PitchAnalyzer(sample_rate=float(sr))
    pyin_hz = _voiced_median_pyin(x, sr)
    yin_hz = _voiced_median_yin(analyzer, x)
    # 纯音缺乏高次谐波，HPS 在 n_harmonics>=2 时会把乘积谱锁到次谐波；
    # 取 n_harmonics=1 使其退化为带抛物线插值的谱峰读数，仍是独立频域后端。
    hps_hz = float(analyzer.detect_hps(x, n_harmonics=1))

    if pyin_hz is None or yin_hz is None:
        return {
            "pyin_hz": pyin_hz,
            "yin_hz": yin_hz,
            "hps_hz": hps_hz,
            "pairwise_cent_diffs": [],
            "consistent": False,
            "applicable": False,
            "reason": "no-voiced",
            "n_algorithms": _N_ALGORITHMS,
        }

    diffs = [
        _cent_diff(pyin_hz, yin_hz),
        _cent_diff(pyin_hz, hps_hz),
        _cent_diff(yin_hz, hps_hz),
    ]
    consistent = max(abs(d) for d in diffs) <= _CONSISTENT_MAX_CENT

    reason = _multi_pitch_reason(_local_peaks(x, sr), pyin_hz)
    if reason is None:
        applicable, reason = True, "ok"
    else:
        applicable = False

    return {
        "pyin_hz": pyin_hz,
        "yin_hz": yin_hz,
        "hps_hz": hps_hz,
        "pairwise_cent_diffs": diffs,
        "consistent": consistent,
        "applicable": applicable,
        "reason": reason,
        "n_algorithms": _N_ALGORITHMS,
    }
