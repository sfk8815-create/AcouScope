# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-A T01：共享峰值插值契约（纯 numpy，零 Qt 依赖）。

覆盖：
  ① refine_peak_frequency 公式、边界（idx=0 / 末 / 负 idx）、
     denom≈0 共线回退；
  ② n_fft=2048 / 8192 七个音分偏移（−50…+50）插值读数最大误差
     ≤4.5 / ≤1.1 cent，且相对未插值 bin 读数误差下降 ≥80%；
  ③ detect_pitch_peaks 输出（freq/magnitude/note/cents/midi）与旧
     抛物线公式逐位对照一致；
  ④ formants.freq_at 口径为时间插值而非频谱插值（静态；数值端点由
     test_measure_uncertainty_gui.py 的 Qt 用例覆盖）。

信号口径：44.1 kHz / A4=440 / Hann 窗 n_fft 点纯音 → rfft 线性幅度谱。
"""

from pathlib import Path

import numpy as np
import pytest

from acouscope.analysis.spectral import (
    SpectralAnalyzer,
    refine_peak_frequency,
)

SR = 44100.0
OFFSETS = np.linspace(-50.0, 50.0, 7)  # −50 … +50，共 7 个音分偏移
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope"


def _hann_spectrum(n_fft: int, off_cent: float):
    """注入 440 Hz ± off_cent 音分纯音，返回 (真频率, 频率轴, 线性幅度谱)。"""
    f_true = 440.0 * 2 ** (off_cent / 1200.0)
    x = np.sin(2 * np.pi * f_true * np.arange(n_fft) / SR)
    magnitude = np.abs(np.fft.rfft(x * np.hanning(n_fft)))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / SR)
    return f_true, freqs, magnitude


def _cent_errors(n_fft: int):
    """返回 (7 个插值误差音分, 7 个 bin 读数误差音分)，均取绝对值。"""
    interp, bins = [], []
    for off in OFFSETS:
        f_true, freqs, mag = _hann_spectrum(n_fft, float(off))
        k = int(np.argmax(mag))
        f_interp = refine_peak_frequency(mag, freqs, k)
        interp.append(abs(1200.0 * np.log2(f_interp / f_true)))
        bins.append(abs(1200.0 * np.log2(float(freqs[k]) / f_true)))
    return np.array(interp), np.array(bins)


# ----------------------------------------------------------------------
# ① 纯函数公式 / 边界 / 回退
# ----------------------------------------------------------------------

def test_refine_peak_frequency_matches_closed_form():
    """a/b/c → denom/delta/true_idx/peak_freq 与手算逐位一致（非 bin 值）。"""
    mag = np.array([0.2, 0.8, 1.0, 0.7, 0.1])
    freqs = np.arange(5, dtype=np.float64) * 10.0
    a, b, c = mag[1], mag[2], mag[3]
    denom = a - 2 * b + c
    delta = (a - c) / (2 * denom)
    expected = float((2 + delta) * (freqs[1] - freqs[0]))
    got = refine_peak_frequency(mag, freqs, 2)
    assert got == expected
    assert got != float(freqs[2])  # 确实发生了插值，非整 bin 读数


def test_refine_idx_zero_falls_back_to_bin():
    mag = np.array([1.0, 0.5, 0.25])
    freqs = np.array([0.0, 10.0, 20.0])
    assert refine_peak_frequency(mag, freqs, 0) == float(freqs[0])


def test_refine_last_index_falls_back_to_bin():
    mag = np.array([0.25, 0.5, 1.0])
    freqs = np.array([0.0, 10.0, 20.0])
    assert refine_peak_frequency(mag, freqs, len(mag) - 1) == float(freqs[-1])


def test_refine_negative_idx_falls_back_without_exception():
    """idx<=0 一律回退（含负索引），不越界崩溃。"""
    mag = np.array([0.25, 0.5, 1.0])
    freqs = np.array([0.0, 10.0, 20.0])
    assert refine_peak_frequency(mag, freqs, -1) == float(freqs[-1])


def test_refine_zero_denom_falls_back():
    """三点严格共线 → denom==0 → 回退 bin 频率。"""
    mag = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    freqs = np.arange(5, dtype=np.float64) * 10.0
    assert refine_peak_frequency(mag, freqs, 2) == float(freqs[2])


def test_refine_tiny_denom_falls_back():
    """|denom|<=1e-20 → 回退 bin 频率（防除零/放大噪声）。"""
    eps = 1e-22
    mag = np.array([1.0, 1.0 + eps, 1.0, 1.0 + eps, 1.0])
    freqs = np.arange(5, dtype=np.float64) * 10.0
    assert refine_peak_frequency(mag, freqs, 2) == float(freqs[2])


def test_refine_short_freq_axis_falls_back():
    """频率轴仅 1 点：无法求 freq_res，安全回退到该点（零异常/零越界）。"""
    mag = np.array([1.0, 2.0, 1.0])
    freqs = np.array([440.0])
    assert refine_peak_frequency(mag, freqs, 0) == 440.0


# ----------------------------------------------------------------------
# ② 判据 1：插值精度 / 相对 bin 误差下降
# ----------------------------------------------------------------------

def test_nfft_2048_seven_offsets_max_error_le_4p5_cent():
    interp, bins = _cent_errors(2048)
    assert interp.size == 7
    assert float(interp.max()) <= 4.5, (interp, bins)


def test_nfft_8192_seven_offsets_max_error_le_1p1_cent():
    interp, bins = _cent_errors(8192)
    assert interp.size == 7
    assert float(interp.max()) <= 1.1, (interp, bins)


def test_interp_error_drops_at_least_80pct_vs_bin():
    for n_fft in (2048, 8192):
        interp, bins = _cent_errors(n_fft)
        drop = 1.0 - float(interp.sum()) / float(bins.sum())
        assert drop >= 0.80, (n_fft, drop, interp, bins)
        assert float(interp.max()) < float(bins.max())


# ----------------------------------------------------------------------
# ③ detect_pitch_peaks 与旧公式逐位对照
# ----------------------------------------------------------------------

def _legacy_peak_dict(magnitude, freqs, abs_idx, mag_val, tuning_offset=0.0):
    """旧 :284-300 公式 + 旧输出计算（独立对照实现，非调用被测代码）。"""
    freq_res = freqs[1] - freqs[0]
    if abs_idx > 0 and abs_idx < len(magnitude) - 1:
        a = magnitude[abs_idx - 1]
        b = magnitude[abs_idx]
        c = magnitude[abs_idx + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-20:
            delta = (a - c) / (2 * denom)
            true_idx = abs_idx + delta
            peak_freq = true_idx * freq_res
            peak_mag = b - 0.25 * (a - c) * delta
        else:
            peak_freq = freqs[abs_idx]
            peak_mag = mag_val
    else:
        peak_freq = freqs[abs_idx]
        peak_mag = mag_val
    a4_freq = 440.0 * (2 ** (tuning_offset / 1200.0))
    midi_float = 69 + 12 * np.log2(peak_freq / a4_freq)
    midi = int(round(midi_float))
    cents = 100 * (midi_float - midi)
    midi = max(0, min(127, midi))
    octave = midi // 12 - 1
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return {
        "freq": float(peak_freq),
        "magnitude": float(peak_mag),
        "note": f"{names[midi % 12]}{octave}",
        "cents": float(cents),
        "midi": midi,
    }


def test_detect_pitch_peaks_single_peak_bitwise_old_formula():
    freqs = np.linspace(0.0, 8000.0, 1025)
    mag = np.full(freqs.size, 1e-6)
    mag[99], mag[100], mag[101] = 0.6, 1.0, 0.7
    peaks = SpectralAnalyzer().detect_pitch_peaks(
        mag, freqs, min_freq=0.0, max_freq=8000.0
    )
    assert len(peaks) == 1
    expected = _legacy_peak_dict(mag, freqs, 100, 1.0)
    assert peaks[0].keys() == expected.keys()
    for key in expected:
        assert peaks[0][key] == expected[key], (key, peaks[0][key], expected[key])


def test_detect_pitch_peaks_multi_peak_with_tuning_bitwise():
    """3 个峰 + tuning_offset=+30 cent：全部输出键逐位对照旧公式。"""
    freqs = np.linspace(0.0, 8000.0, 2049)
    mag = np.full(freqs.size, 1e-6)
    centers = (60, 200, 500)
    for k, idx in enumerate(centers):
        mag[idx - 1] = 0.5 + 0.1 * k
        mag[idx] = 1.0 - 0.05 * k
        mag[idx + 1] = 0.7 - 0.05 * k
    peaks = SpectralAnalyzer().detect_pitch_peaks(
        mag, freqs, min_freq=0.0, max_freq=8000.0, tuning_offset=30.0
    )
    assert [p["freq"] for p in peaks] == sorted(p["freq"] for p in peaks)
    assert len(peaks) == len(centers)
    expected = [
        _legacy_peak_dict(mag, freqs, idx, float(mag[idx]), 30.0)
        for idx in centers
    ]
    expected.sort(key=lambda d: d["freq"])
    for got, exp in zip(peaks, expected):
        for key in exp:
            assert got[key] == exp[key], (key, got[key], exp[key])


# ----------------------------------------------------------------------
# ④ formants 口径（静态 + 数值端点见 GUI 测试）
# ----------------------------------------------------------------------

def test_formants_freq_at_docstring_declares_time_interpolation():
    src = (_SRC_ROOT / "ui" / "widgets" / "formants.py").read_text(encoding="utf-8")
    assert "时间轴线性插值，非频谱插值" in src
    assert "禁臆造频谱插值" in src
