# SPDX-License-Identifier: GPL-3.0-only
"""T-327 Pε 选区区间统计：纯 numpy 数据驱动，零分析重算。

仅对「既有结果」做切片统计：
- 时长/起止：由选区绝对时间差给出（T-917 口径，调用方传入）。
- 能量：对音频样本片段做 RMS/峰值（dB + 线性）——纯数值统计，
  不触发任何 STFT/音高/共振峰分析（禁重算铁律）。
- 音高：对 (times, f0) 时间轴做帧中心归属切片（[t0, t1] 含边界），
  仅在 voiced（f0>0）帧上计算均值/中位/最小/最大/范围与相对当前 A4
  12TET 音分均值；unvoiced 计入分母（voiced 占比口径同 T-905）。

本模块不做 i18n / UI，返回数值 dict；格式化成文案由 main_window 负责。
"""

from __future__ import annotations

from typing import Optional

import numpy as np

_EPS = 1e-12


def slice_in_region(
    times: np.ndarray, values: np.ndarray, t0: float, t1: float
) -> tuple[np.ndarray, np.ndarray]:
    """按帧中心归属切出 [t0, t1] 的帧（含边界）；无覆盖返回空数组。"""
    times = np.asarray(times, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if times.size == 0 or values.size == 0:
        return np.array([]), np.array([])
    if times.shape != values.shape:
        raise ValueError("times/values 形状不一致")
    mask = (times >= float(t0)) & (times <= float(t1))
    return times[mask], values[mask]


def region_rms(samples: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    """音频片段 RMS（线性 + dB）。空片段或静音 → (None, None)。"""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.size == 0:
        return None, None
    rms = float(np.sqrt(np.mean(np.square(samples))))
    if rms <= _EPS:
        return None, None
    return rms, 20.0 * np.log10(rms)


def region_peak(samples: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    """音频片段峰值（线性 + dB）。空片段或静音 → (None, None)。"""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.size == 0:
        return None, None
    peak = float(np.max(np.abs(samples)))
    if peak <= _EPS:
        return None, None
    return peak, 20.0 * np.log10(peak)


def _cents(f0: np.ndarray) -> np.ndarray:
    """相对当前 A4 的 12TET 音分（仅对 f0>0 调用方保证）。"""
    from acouscope.dsp import units
    return units.hz_to_cents(f0)


def pitch_stats(
    times: np.ndarray, f0: np.ndarray, t0: float, t1: float
) -> Optional[dict]:
    """对选区 [t0,t1] 内 f0 帧做统计（帧中心归属，含边界）。

    返回 dict（voiced==0 时各数值字段为 None）：
      frames/voiced/voiced_ratio/f0_mean/f0_median/f0_min/f0_max/f0_range/
      cent_mean
    times 为空或区间无任何帧 → None（调用方据此区分「无结果」与「有结果但
    无浊音」）。
    """
    times = np.asarray(times, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)
    if times.size == 0 or f0.size == 0 or times.shape != f0.shape:
        return None
    mask = (times >= float(t0)) & (times <= float(t1))
    if not bool(np.any(mask)):
        return None
    seg = f0[mask]
    total = int(seg.size)
    voiced_mask = seg > 0
    voiced = int(np.count_nonzero(voiced_mask))
    ratio = voiced / total if total else None
    if voiced == 0:
        return {
            "frames": total, "voiced": 0, "voiced_ratio": 0.0,
            "f0_mean": None, "f0_median": None, "f0_min": None,
            "f0_max": None, "f0_range": None, "cent_mean": None,
        }
    v = seg[voiced_mask]
    cent = _cents(v)
    return {
        "frames": total,
        "voiced": voiced,
        "voiced_ratio": ratio,
        "f0_mean": float(np.mean(v)),
        "f0_median": float(np.median(v)),
        "f0_min": float(np.min(v)),
        "f0_max": float(np.max(v)),
        "f0_range": float(np.max(v) - np.min(v)),
        "cent_mean": float(np.mean(cent)),
    }
