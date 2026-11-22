# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-C T07：设备时钟闭环自校准（离线仿真）判据。

覆盖：estimate/correct 纯函数；simulate_clock_drift 频率可复现；
calibrate_from_reference 结构；五档 ppm 的独立频点交叉检验残差 ≤0.01 cent；
全局 A4 前后恒 440；模块源码禁改全局 A4（零命中 + 正对照）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from acouscope.analysis.clock_calibration import (
    calibrate_from_reference,
    correct_frequency_axis,
    cross_frequency_residual,
    estimate_clock_ppm,
    simulate_clock_drift,
)
from acouscope.analysis.pitch import detect_pyin
from acouscope.dsp import units
from acouscope.dsp.pitch_tone import synthesize_tone

SR = 44100
PPM_CASES = [0.0, 50.0, -50.0, 100.0, -100.0]
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope"
_CLOCK_SRC = _SRC_ROOT / "analysis" / "clock_calibration.py"


# ----------------------------------------------------------------------
# ① 纯函数
# ----------------------------------------------------------------------

def test_estimate_clock_ppm_pure():
    assert estimate_clock_ppm(440.0, 440.0) == pytest.approx(0.0)
    assert estimate_clock_ppm(440.0, 440.0 * (1 + 100e-6)) == pytest.approx(100.0, abs=1e-6)
    assert estimate_clock_ppm(440.0, 440.0 * (1 - 50e-6)) == pytest.approx(-50.0, abs=1e-6)
    # 纯函数：相同入参恒定，不读写全局
    before = units.get_reference_hz()
    assert estimate_clock_ppm(440.0, 441.0) == estimate_clock_ppm(440.0, 441.0)
    assert units.get_reference_hz() == before


def test_correct_frequency_axis_pure_and_roundtrip():
    assert correct_frequency_axis(440.0, 0.0) == pytest.approx(440.0)
    shifted = 440.0 * (1 + 100e-6)
    assert correct_frequency_axis(shifted, 100.0) == pytest.approx(440.0, rel=1e-12)
    # estimate → correct 往返回到标称
    measured = 440.0 * (1 - 75e-6)
    ppm = estimate_clock_ppm(440.0, measured)
    assert correct_frequency_axis(measured, ppm) == pytest.approx(440.0, rel=1e-12)


# ----------------------------------------------------------------------
# ② 频率可复现 / 确定性
# ----------------------------------------------------------------------

def test_simulate_clock_drift_frequency_reproducible():
    for ppm in (0.0, 75.0, -75.0):
        sig = simulate_clock_drift(440.0, ppm, 1.0, SR)
        expected = synthesize_tone(440.0 * (1 + ppm * 1e-6), 1.0, SR)
        # 确定性：与按 ppm 缩放频率直接合成的信号逐样本一致
        assert np.array_equal(sig, expected)
        # 独立测频印证：pYIN 中位 ≈ 440*(1+ppm*1e-6)
        track = detect_pyin(sig, float(SR))
        voiced = track.f0_hz[np.isfinite(track.f0_hz)]
        med = float(np.median(voiced))
        cent = 1200.0 * np.log2(med / (440.0 * (1 + ppm * 1e-6)))
        assert abs(cent) < 0.1, (ppm, med, cent)


def test_simulate_clock_drift_ppm_zero_equals_reference():
    assert np.array_equal(
        simulate_clock_drift(440.0, 0.0, 0.5, SR),
        synthesize_tone(440.0, 0.5, SR),
    )


# ----------------------------------------------------------------------
# ③ calibrate_from_reference 结构
# ----------------------------------------------------------------------

def test_calibrate_from_reference_fields():
    sig = simulate_clock_drift(440.0, 100.0, 1.0, SR)
    calib = calibrate_from_reference(sig, SR, 440.0)
    assert set(calib) == {
        "measured_hz", "ppm", "corrected_hz", "residual_cent",
        "reference_hz", "n_frames", "method",
    }
    assert calib["method"] == "pyin_median"
    assert calib["reference_hz"] == 440.0
    assert calib["n_frames"] > 0
    assert calib["measured_hz"] == pytest.approx(440.044, abs=0.02)
    # 自洽残差（修正同一测量）恒 0；独立检验见 cross_frequency_residual
    assert abs(calib["residual_cent"]) < 1e-9
    assert calib["corrected_hz"] == pytest.approx(440.0, rel=1e-12)


# ----------------------------------------------------------------------
# ④ 判据 1：五档 ppm 的独立频点交叉检验 ≤ 0.01 cent
# ----------------------------------------------------------------------

@pytest.mark.parametrize("ppm", PPM_CASES)
def test_cross_frequency_residual_five_ppm(ppm):
    sig = simulate_clock_drift(440.0, ppm, 1.0, SR)
    calib = calibrate_from_reference(sig, SR, 440.0)
    residual = cross_frequency_residual(calib, 660.0, SR)
    print(
        f"[T07] ppm={ppm:+.0f} measured_hz={calib['measured_hz']:.6f} "
        f"ppm_est={calib['ppm']:+.4f} "
        f"cross_frequency_residual={residual:+.6f} cent"
    )
    assert abs(residual) <= 0.01, (ppm, residual)


def test_cross_frequency_defaults_to_660():
    sig = simulate_clock_drift(440.0, 0.0, 1.0, SR)
    calib = calibrate_from_reference(sig, SR, 440.0)
    # 默认 target_hz=660 与显式一致
    assert cross_frequency_residual(calib, sr=SR) == cross_frequency_residual(calib, 660.0, SR)


# ----------------------------------------------------------------------
# ⑤ 全局 A4 不变 + 模块源码零命中（配正对照）
# ----------------------------------------------------------------------

def test_global_a4_unchanged_across_calibration():
    before = units.get_reference_hz()
    assert before == 440.0
    sig = simulate_clock_drift(440.0, 100.0, 1.0, SR)
    calib = calibrate_from_reference(sig, SR, 440.0)
    cross_frequency_residual(calib, 660.0, SR)
    assert units.get_reference_hz() == 440.0
    assert units.get_reference_hz() == before


def test_clock_source_no_global_reference_setter():
    forbidden = "set_" + "reference_hz"
    src = _CLOCK_SRC.read_text(encoding="utf-8")
    # 零命中：本模块不改全局 A4
    assert forbidden not in src
    # 正对照：同一字符串在真实定义处（units.py）确实命中，证明检测有效
    units_src = (_SRC_ROOT / "dsp" / "units.py").read_text(encoding="utf-8")
    assert forbidden in units_src
    assert ("def " + forbidden) in units_src
