# SPDX-License-Identifier: GPL-3.0-only
"""T07 设备时钟闭环自校准（离线仿真；纯 numpy，无 Qt、零新增依赖）。

模型：设备采样时钟相对标称有 ppm 级偏差时，同一物理音的观测频率整体按
``1 + ppm*1e-6`` 缩放，等价于时间轴按同一因子缩放。本模块用参考音估计该
比例，再在**另一个独立频点**上做交叉检验，避免「测量 → 反推 ppm → 修正
同一测量」的自证循环。

校准结果只是普通 dict，由调用方按需放进 measurement_record.extra；
本模块不改全局 A4 参考、不写任何校准状态位、不碰既有状态机。
"""
from __future__ import annotations

import numpy as np

from acouscope.analysis.pitch import detect_pyin
from acouscope.dsp.pitch_tone import synthesize_tone

_PPM_SCALE = 1e-6


def simulate_clock_drift(
    reference_hz: float = 440.0,
    ppm: float = 0.0,
    duration_s: float = 1.0,
    sr: int = 44100,
) -> np.ndarray:
    """生成「设备时钟偏差下的观测信号」。

    物理音频率 ``reference_hz`` 在 ppm 偏差的时钟下被观测为
    ``reference_hz * (1 + ppm*1e-6)``；用该频率合成波形即可复现。
    这等价于把时间轴按 ``(1 + ppm*1e-6)`` 缩放（采样间隔整体变长/变短），
    因为 ``sin(2*pi*f*(1+e)*t)`` 与把 ``t`` 替换为 ``t*(1+e)`` 同形。
    """
    observed_hz = float(reference_hz) * (1.0 + float(ppm) * _PPM_SCALE)
    return synthesize_tone(observed_hz, float(duration_s), int(sr))


def estimate_clock_ppm(reference_hz: float, measured_hz: float) -> float:
    """由参考频率与实测频率估计时钟偏差（ppm）。纯函数。"""
    return (float(measured_hz) / float(reference_hz) - 1.0) * 1e6


def correct_frequency_axis(f_hz: float, ppm: float) -> float:
    """把受 ppm 偏差的频率读数修正回标称时钟。纯函数。"""
    return float(f_hz) / (1.0 + float(ppm) * _PPM_SCALE)


def _voiced_median(signal: np.ndarray, sr: float) -> tuple[float, int]:
    """pYIN voiced 帧中位 f0，以及参与中位统计的帧数。"""
    track = detect_pyin(np.asarray(signal, dtype=np.float64), float(sr))
    voiced = track.f0_hz[np.isfinite(track.f0_hz)]
    if voiced.size == 0:
        raise ValueError("信号无有效 voiced 帧，无法估计时钟偏差")
    return float(np.median(voiced)), int(voiced.size)


def calibrate_from_reference(
    signal: np.ndarray,
    sr: int,
    reference_hz: float = 440.0,
) -> dict:
    """用参考音估计时钟 ppm，返回自洽校准字典。

    ``residual_cent`` 是「修正同一测量」的自洽残差（恒 0），**不是**独立
    检验；真正的独立交叉检验请用 :func:`cross_frequency_residual`。
    """
    measured_hz, n_frames = _voiced_median(signal, sr)
    ppm = estimate_clock_ppm(reference_hz, measured_hz)
    corrected_hz = correct_frequency_axis(measured_hz, ppm)
    residual_cent = float(1200.0 * np.log2(corrected_hz / float(reference_hz)))
    return {
        "measured_hz": measured_hz,
        "ppm": ppm,
        "corrected_hz": corrected_hz,
        "residual_cent": residual_cent,
        "reference_hz": float(reference_hz),
        "n_frames": n_frames,
        "method": "pyin_median",
    }


def cross_frequency_residual(
    calibration: dict,
    target_hz: float = 660.0,
    sr: int = 44100,
) -> float:
    """独立频点交叉检验（防自证）。

    用 ``calibration["ppm"]``（从参考音测得）在**另一个**目标频率
    ``target_hz`` 上生成受同一偏差的观测信号，独立测其 f0，再用同一 ppm
    修正，返回它与 ``target_hz`` 的音分残差。若 ppm 只反映参考频点的测量
    噪声、无法迁移到其它频点，残差会显著偏离 0。
    """
    ppm = float(calibration["ppm"])
    observed = simulate_clock_drift(float(target_hz), ppm, sr=sr)
    measured_target, _ = _voiced_median(observed, sr)
    corrected = correct_frequency_axis(measured_target, ppm)
    return float(1200.0 * np.log2(corrected / float(target_hz)))
