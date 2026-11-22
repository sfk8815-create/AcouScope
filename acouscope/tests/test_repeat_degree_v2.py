# SPDX-License-Identifier: GPL-3.0-only
"""往复度修正版判据：正负夹具（约定-20261025 往复度有效性）。"""

import numpy as np
import pytest

from acouscope.analysis.cavity_type import repeat_degree_v2

SR_FRAME = 44100.0 / 256.0  # 帧率 172.27 Hz


class _Note:
    def __init__(self, start_s, end_s, runs):
        self.start_s = start_s
        self.end_s = end_s
        self.state_runs = runs


class _Model:
    def __init__(self, notes):
        self.notes = notes


def _model_with(f0: np.ndarray):
    n = f0.size
    runs = ((0, n - 1, 0.0, n / SR_FRAME, "stable"),)
    return _Model([_Note(0.0, n / SR_FRAME, runs)]), f0


def _vib(freq_hz: float, pp_cents: float, dur: float = 1.0) -> np.ndarray:
    n = int(dur * SR_FRAME)
    t = np.arange(n) / SR_FRAME
    cents = (pp_cents / 2.0) * np.sin(2 * np.pi * freq_hz * t)
    return 440.0 * 2.0 ** (cents / 1200.0)


def _turns(f0, mode):
    model, arr = _model_with(f0)
    row = repeat_degree_v2(model, arr, mode=mode)[0]
    return row


@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
@pytest.mark.parametrize("freq", [3.0, 5.0, 8.0])
@pytest.mark.parametrize("pp", [20.0, 50.0, 100.0])
def test_positive_vibrato_turns(mode, freq, pp):
    """正向：合成吟猱，反转数与理论值（2fT−1）相差 ≤1。"""
    row = _turns(_vib(freq, pp), mode)
    expect = round(2 * freq * 1.0 - 1)
    assert row["valid"] is True
    assert abs(row["turns"] - expect) <= 1, (
        f"{mode} {freq}Hz {pp}c: turns={row['turns']} expect={expect} thr={row['thr_cents']}"
    )


@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
def test_negative_noise_zero_turns(mode):
    """负向：纯噪声（同长度、SNR 20 dB 相对最小正向幅度）⇒ 反转数须为 0。"""
    for seed in range(4):
        rng = np.random.default_rng(seed)
        n = int(1.0 * SR_FRAME)
        std = (20.0 / 2.0) / 10.0  # 最小正向 A=10 音分，SNR 20 dB
        cents = rng.normal(0.0, std, n)
        f0 = 440.0 * 2.0 ** (cents / 1200.0)
        row = _turns(f0, mode)
        assert row["turns"] == 0, f"{mode} seed={seed}: turns={row['turns']} thr={row['thr_cents']}"


def test_invalid_gate_flags_high_rate():
    """有效性闸：>12 Hz 的反转率标 valid=False。"""
    row = _turns(_vib(20.0, 100.0), "fixed")
    assert row["valid"] is False
    assert row["rate_hz"] > 12.0


@pytest.mark.parametrize("freq", [3.0, 5.0, 8.0])
@pytest.mark.parametrize("pp", [20.0, 50.0, 100.0])
def test_adaptive_clamp_bounds(freq, pp):
    """自适应阈值双端 clamp：``thr ∈ [10, 0.5×(p95−p5)]``。

    上限必须是**稳健峰峰 p95−p5**，不是合成输入的名义峰峰：3 Hz／20 c 例
    thr=10.38 > 0.5×20=10，按名义峰峰设判据会误判越界（2026-10-25 核验记录项 2）。
    """
    row = _turns(_vib(freq, pp), "adaptive")
    robust = row["pp_robust_cents"]
    assert robust is not None and robust > 0, f"{freq}Hz {pp}c: 无稳健峰峰"
    assert row["thr_cents"] >= 10.0, f"{freq}Hz {pp}c: thr 低于下限 10"
    assert row["thr_cents"] <= max(0.5 * robust, 10.0) + 1e-6, (
        f"{freq}Hz {pp}c: thr={row['thr_cents']} 超 0.5×稳健峰峰={0.5 * robust}"
    )


def test_adaptive_upper_bound_uses_robust_pp_not_nominal():
    """3 Hz／20 c：上限由稳健峰峰（≈20.76）决定，非名义 20 音分。

    thr 落在 (0.5×名义, 0.5×稳健] 区间内——这一格是「按名义峰峰写判据」的
    反例，若无此例，越界判定无法与名义峰峰区分。
    """
    row = _turns(_vib(3.0, 20.0), "adaptive")
    robust = row["pp_robust_cents"]
    assert row["thr_cents"] > 0.5 * 20.0, "thr 未越过名义上限，本用例失去区分力"
    assert row["thr_cents"] <= 0.5 * robust + 1e-6
    assert abs(row["turns"] - 4) <= 1, f"turns={row['turns']} 与理论 5 差超 1"


@pytest.mark.parametrize("freq", [3.0, 5.0, 8.0])
@pytest.mark.parametrize("pp", [20.0, 50.0, 100.0])
def test_adaptive_not_above_fixed(freq, pp):
    """两版并报的读法约束：adaptive 一律不高于 fixed，差至多 1。

    阈值上移只会漏计不会多计；若出现 adaptive > fixed，说明阈值或
    平滑路径被改动，并报表不再可对读。
    """
    fixed = _turns(_vib(freq, pp), "fixed")["turns"]
    adaptive = _turns(_vib(freq, pp), "adaptive")["turns"]
    assert adaptive <= fixed, f"{freq}Hz {pp}c: adaptive={adaptive} > fixed={fixed}"
    assert fixed - adaptive <= 1, f"{freq}Hz {pp}c: 差 {fixed - adaptive} 超过 1"
