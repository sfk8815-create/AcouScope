# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-A T02/T03：不确定度数据模型与文案契约（纯 numpy，零 Qt 依赖）。

覆盖：
  ① pitch_stats 旧 9 键逐位不变、新 5 键齐、无浊音分支补同名键；
  ② cent_std / cent_p95 / lag-1 自相关 r 裁剪 / n_eff / cent_sem 公式
     （独立 numpy 复算对照）、confidence_mean 有/无 confidence；
  ③ SNR20 条件下 cent_sem ≥2 cent（逐帧相对真值 p95 落在 1.79–2.70 cent），
     消灭「±42 cent 误差却显示 0.1 cent」的虚假精度；
  ④ 与 uncertainties.ufloat 独立观测合成 u 对拍差 ≤1e-6 cent
     （开发期对拍件，pytest.importorskip；零依赖时 skip 不算失败）；
  ⑤ i18n 新 2 键三语文案逐字、旧 full / dt_only 键逐字不改。

对拍依赖由 PYTHONPATH 指向 /tmp/pi_p7_unc 提供，零运行时依赖声明。
"""

import math

import numpy as np
import pytest

from acouscope.dsp import units
from acouscope.i18n import _STRINGS, get_language, set_language, tr
from acouscope.ui.region_stats import pitch_stats

OLD_KEYS = ("frames", "voiced", "voiced_ratio", "f0_mean", "f0_median",
            "f0_min", "f0_max", "f0_range", "cent_mean")
NEW_KEYS = ("cent_std", "cent_p95", "cent_sem", "n_eff", "confidence_mean")
ALL_KEYS = set(OLD_KEYS) | set(NEW_KEYS)


@pytest.fixture(autouse=True)
def _fixed_a4(monkeypatch):
    """钉死 A4=440，避免跨用例参考频率状态影响音分复算。"""
    monkeypatch.setattr(units, "_reference_hz", 440.0)


def _independent_uncertainty(f0):
    """按契约公式独立复算 5 个新键（不使用 pitch_stats）。"""
    cent = np.asarray(units.hz_to_cents(np.asarray(f0, dtype=float)), dtype=float)
    n = int(cent.size)
    std = float(np.std(cent, ddof=1)) if n > 1 else 0.0
    p95 = float(np.percentile(np.abs(cent - cent.mean()), 95))
    if n > 2:
        c0, c1 = cent[:-1], cent[1:]
        s0, s1 = float(c0.std()), float(c1.std())
        r = (float(np.mean((c0 - c0.mean()) * (c1 - c1.mean()))) / (s0 * s1)
             if s0 > 0 and s1 > 0 else 0.0)
    else:
        r = 0.0
    r = min(0.99, max(0.0, float(r)))
    n_eff = max(1.0, n * (1.0 - r) / (1.0 + r))
    return std, p95, r, n_eff, float(std / math.sqrt(n_eff))


# ----------------------------------------------------------------------
# ① 旧 9 键零改动 / 新 5 键齐 / 无浊音分支
# ----------------------------------------------------------------------

def test_pitch_stats_old_nine_keys_bitwise_unchanged():
    """与 test_region_stats.py 既有数值口径逐位一致。"""
    times = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    f0 = np.array([0, 0, 440, 440, 440, 0, 660, 660, 0, 0], dtype=np.float64)
    s = pitch_stats(times, f0, 0.2, 0.7)
    assert s is not None
    assert s["frames"] == 6 and s["voiced"] == 5
    assert s["voiced_ratio"] == pytest.approx(5 / 6)
    assert s["f0_mean"] == pytest.approx(528.0)
    assert s["f0_median"] == pytest.approx(440.0)
    assert s["f0_min"] == pytest.approx(440.0)
    assert s["f0_max"] == pytest.approx(660.0)
    assert s["f0_range"] == pytest.approx(220.0)
    cent_660 = 1200.0 * math.log2(660.0 / 440.0)
    assert s["cent_mean"] == pytest.approx((3 * 0.0 + 2 * cent_660) / 5, abs=1e-3)


def test_pitch_stats_new_five_keys_present_and_exact_keyset():
    times = np.arange(20) * 0.01
    f0 = np.full(20, 440.0)
    s = pitch_stats(times, f0, 0.0, 0.19)
    assert set(s) == ALL_KEYS
    for key in NEW_KEYS:
        assert key in s
    assert s["confidence_mean"] is None           # 无 confidence
    assert s["cent_std"] == 0.0 and s["cent_sem"] == 0.0
    assert s["n_eff"] == pytest.approx(20.0)      # r 裁剪到 0 → n_eff == n


def test_pitch_stats_no_voiced_adds_same_keys():
    times = np.arange(5, dtype=np.float64) * 0.1
    s = pitch_stats(times, np.zeros(5), 0.0, 0.4)
    assert set(s) == ALL_KEYS
    assert s["voiced"] == 0 and s["voiced_ratio"] == 0.0
    assert s["cent_sem"] is None and s["confidence_mean"] is None
    assert s["f0_mean"] is None and s["cent_mean"] is None


def test_pitch_stats_empty_and_no_overlap_still_none():
    assert pitch_stats(np.array([]), np.array([]), 0.0, 1.0) is None
    times = np.arange(5) * 0.1
    assert pitch_stats(times, np.full(5, 440.0), 2.0, 3.0) is None


# ----------------------------------------------------------------------
# ② 公式：std / p95 / r 裁剪 / n_eff / sem / confidence_mean
# ----------------------------------------------------------------------

def test_pitch_stats_cent_std_and_p95_formula():
    rng = np.random.RandomState(7)
    dev = rng.normal(0.0, 3.0, 60)                 # 音分偏差
    f0 = 440.0 * 2 ** (dev / 1200.0)
    s = pitch_stats(np.arange(60) * 0.01, f0, 0.0, 0.59)
    std, p95, _r, _ne, _sem = _independent_uncertainty(f0)
    assert s["cent_std"] == pytest.approx(std, abs=1e-12)
    assert s["cent_p95"] == pytest.approx(p95, abs=1e-12)


def test_pitch_stats_autocorr_neff_and_sem_formula():
    """强正自相关（随机游走）→ r 裁剪 0.99 → n_eff 显著小于 n。"""
    rng = np.random.RandomState(11)
    dev = np.cumsum(rng.normal(0.0, 0.8, 80))
    f0 = 440.0 * 2 ** (dev / 1200.0)
    s = pitch_stats(np.arange(80) * 0.01, f0, 0.0, 0.79)
    std, p95, r, n_eff, sem = _independent_uncertainty(f0)
    assert r <= 0.99
    assert s["n_eff"] == pytest.approx(n_eff, abs=1e-12)
    assert s["n_eff"] < 80                          # 自相关确实生效
    assert s["cent_sem"] == pytest.approx(sem, abs=1e-12)
    assert s["cent_sem"] == pytest.approx(s["cent_std"] / math.sqrt(s["n_eff"]), abs=1e-12)
    assert s["cent_std"] == pytest.approx(std, abs=1e-12)
    assert s["cent_p95"] == pytest.approx(p95, abs=1e-12)


def test_pitch_stats_confidence_mean_only_when_provided():
    rng = np.random.RandomState(3)
    f0 = 440.0 * 2 ** (rng.normal(0, 2, 50) / 1200.0)
    f0[::7] = 0.0                                  # 部分 unvoiced
    times = np.arange(50) * 0.01
    conf = np.linspace(0.1, 0.9, 50)
    s_yes = pitch_stats(times, f0, 0.0, 0.49, confidence=conf)
    s_no = pitch_stats(times, f0, 0.0, 0.49)
    assert s_no["confidence_mean"] is None
    assert s_yes["confidence_mean"] == pytest.approx(float(np.mean(conf[f0 > 0])))
    # 旧 9 键不因新增可选参数而改动
    for key in OLD_KEYS:
        assert s_yes[key] == s_no[key], key


# ----------------------------------------------------------------------
# ③ SNR20：cent_sem 不得给出虚假精度
# ----------------------------------------------------------------------

def test_snr20_cent_sem_not_falsely_precise():
    """SNR20 主体逐帧抖动（相对真值 p95 1.79–2.70 cent）+ 偶发连续倍频漂移。

    若错误地把所有帧当独立观测（n_eff=n），SEM 会被平均到 <1 cent，出现
    「±42 cent 误差却显示 0.1 cent」的虚假精度；契约的 lag-1 自相关裁剪
    使 n_eff 收缩，cent_sem 保持 ≥2 cent。
    """
    n = 100
    rng = np.random.RandomState(20)
    noise = rng.normal(0.0, 1.2, n)               # SNR20 主体抖动（音分）
    frame_p95 = float(np.percentile(np.abs(noise), 95))
    dev = noise.copy()
    dev[50:55] = 40.0                             # 偶发连续倍频漂移（5 帧）
    f0 = 440.0 * 2 ** (dev / 1200.0)
    times = np.arange(n) * 0.01
    s = pitch_stats(times, f0, 0.0, float(times[-1]))
    print("SNR20 frame_p95=%.4f cent cent_p95=%.4f cent cent_sem=%.4f cent n_eff=%.2f"
          % (frame_p95, s["cent_p95"], s["cent_sem"], s["n_eff"]))
    assert 1.79 <= frame_p95 <= 2.70, frame_p95
    assert s["cent_sem"] >= 2.0, s
    assert s["cent_sem"] <= s["cent_std"]          # n_eff>=1，禁止放大
    assert s["n_eff"] < n


# ----------------------------------------------------------------------
# ④ uncertainties.ufloat 独立观测合成 u 对拍
# ----------------------------------------------------------------------

def test_uncertainties_ufloat_parity():
    """独立观测（r 裁剪到 0 → n_eff=n）时 cent_sem == ufloat 合成 u。"""
    pytest.importorskip("uncertainties")
    from uncertainties import ufloat

    n = 40
    dev = np.array([1.0 if i % 2 == 0 else -1.0 for i in range(n)])
    f0 = 440.0 * 2 ** (dev / 1200.0)
    times = np.arange(n) * 0.01
    s = pitch_stats(times, f0, 0.0, float(times[-1]))
    std, _p95, r, n_eff, sem = _independent_uncertainty(f0)
    assert r == 0.0                                # 交替序列 → 负自相关裁剪到 0
    assert s["n_eff"] == pytest.approx(float(n), abs=1e-9)
    assert n_eff == pytest.approx(float(n), abs=1e-9)

    # n 个独立观测，每个 1σ = std；均值的合成不确定度 = std/sqrt(n)
    observations = [ufloat(0.0, std) for _ in range(n)]
    combined = sum(observations) / n
    u_ufloat = float(combined.std_dev)
    diff = abs(u_ufloat - s["cent_sem"])
    print("UFLOAT_PARITY_PASS diff=%.3e cent u_ufloat=%.12f cent_sem=%.12f"
          % (diff, u_ufloat, s["cent_sem"]))
    assert diff <= 1e-6
    assert abs(u_ufloat - sem) <= 1e-6


# ----------------------------------------------------------------------
# ⑤ i18n 契约
# ----------------------------------------------------------------------

def test_i18n_new_keys_three_languages_and_old_keys_untouched():
    for key in ("region_stats.r_uncertainty", "measure_result.full_u"):
        entry = _STRINGS[key]
        for lang in ("en_US", "zh_CN", "zh_TW"):
            assert entry[lang].strip(), (key, lang)
    # 旧键逐字不改
    assert _STRINGS["measure_result.full"] == {
        "en_US": "Δt {dt} s | ΔHz {df} | Δcent {dc} | ratio {ratio}",
        "zh_CN": "Δt {dt} s | ΔHz {df} | Δ音分 {dc} | 频率比 {ratio}",
        "zh_TW": "Δt {dt} s | ΔHz {df} | Δ音分 {dc} | 頻率比 {ratio}",
    }
    assert _STRINGS["measure_result.dt_only"]["en_US"] == "Δt {dt} s"
    # full_u 给死的三语文案
    assert _STRINGS["measure_result.full_u"]["en_US"] == (
        "Δt {dt} s | ΔHz {df} | Δcent {dc} ± {u} | ratio {ratio}")
    assert _STRINGS["measure_result.full_u"]["zh_CN"] == (
        "Δt {dt} s | ΔHz {df} | Δ音分 {dc} ± {u} | 频率比 {ratio}")
    assert "頻率比" in _STRINGS["measure_result.full_u"]["zh_TW"]


def test_i18n_full_u_format_contract():
    original = get_language()
    try:
        set_language("en_US")
        new_text = tr("measure_result.full_u").format(
            dt="0.300", df="220.0", dc="702", u="7.2", ratio="1.500")
        assert "±" in new_text and "7.2" in new_text and "702" in new_text
        assert "{" not in new_text
        old_text = tr("measure_result.full").format(
            dt="0.300", df="220.0", dc="702.0", ratio="1.500")
        assert "±" not in old_text and "702.0" in old_text
        row = tr("region_stats.r_uncertainty").format(u="2.55", n="12")
        assert "2.55" in row and "12" in row and "{" not in row
    finally:
        set_language(original)
