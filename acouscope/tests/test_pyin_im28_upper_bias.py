# SPDX-License-Identifier: GPL-3.0-only
"""T-1069（IM-28）：pYIN 上端 f0 系统性 +2.03 Hz 偏差修复验收档。

修法（(B) CMNDF 反倾斜）：``parabolic_interpolate`` 对 CMNDF 三点各除自身 tau
因子后再做抛物线插值（去 ``d·tau/cumsum`` 的 ×tau 倾斜）。Python/Rust 两侧同式。

口径（任务书 T-1069 v2 §2-3）：
1. 偏差量级：detect_pyin 9 个频率点中位 |f0−f_true| ≤ 0.5 cent（R-3）。
2. IM-24 自解：1998/1999 @fmax=2000 ⇒ voiced>0（改前 nv=0 全盲）。
3. 2000-exact（R-2）：voiced>0 ∧ 中位残差 f_median−2000 < 0（实测 nv=46/71；
   ★ 不断言全帧 voiced——25/71 帧微越界是刀口固有）。
4. 幽灵回归：3000 @fmax=2000 ⇒ nv==0（不得复发误检 1500）。
5. ON/OFF 逐位：上端＋刀口两侧＋3000 的 f0/voiced 逐位一致。
6. 负对照（R-6）：反倾斜因子设 1（退化原式）⇒ 1998 复盲（本档末尾实证）。
7. 既有档不回退：判据①合跑覆盖（本档外）。

``T1069_DEGRADE=1`` ⇒ OFF 路径 monkeypatch 回无反倾斜原式，供「退化→红」实证，
非正式跑口径（§2-3-6）。
"""

import os

import numpy as np
import pytest

import acouscope_core as _core  # noqa: F401  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis import pyin
from acouscope.analysis.pitch import detect_pyin

ENV = "ACOUSCOPE_NATIVE"
SR = 44100.0

KNIFE_LO = 1997.933657333  # AT-1007 刀口翻转区间两侧（同 native_r3）
KNIFE_HI = 1997.933657348

BIAS_FREQS = (500, 1000, 1500, 1900, 1990, 1995, 1997, 1998, 1999)
BITEXACT_FREQS = (500, 1500, 1900, 1997, KNIFE_LO, KNIFE_HI, 1998, 1999, 2000, 3000)


def _sine(freq, dur=0.5, sr=SR, amp=0.5):
    t = np.arange(int(sr * dur)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def _median_abs_cent(f0, f_true):
    return float(np.median(np.abs(1200.0 * np.log2(f0 / f_true))))


def _parabolic_factor_one(dnorm, tau):
    """反倾斜因子设 1 ⇒ 退化原式（R-6 负对照；T-1069 改前逐字体）。"""
    if tau <= 0 or tau >= dnorm.size - 1:
        return float(tau)
    a, b, c = dnorm[tau - 1], dnorm[tau], dnorm[tau + 1]
    denom = 2.0 * (a - 2.0 * b + c)
    if abs(denom) < 1e-12:
        return float(tau)
    delta = float(np.clip((a - c) / denom, -1.0, 1.0))
    return float(tau) + delta


def _track(monkeypatch, f, *, native, fmax=2000.0):
    if native:
        monkeypatch.setenv(ENV, "1")
    else:
        monkeypatch.delenv(ENV, raising=False)
        if os.environ.get("T1069_DEGRADE") == "1":
            monkeypatch.setattr(pyin, "parabolic_interpolate", _parabolic_factor_one)
    return detect_pyin(_sine(f), SR, fmax=fmax)


# ---- §2-3-1 偏差量级 ≤0.5 cent（R-3）------------------------------------
@pytest.mark.parametrize("f", BIAS_FREQS)
def test_bias_matrix_half_cent(f, monkeypatch):
    tr = _track(monkeypatch, float(f), native=False)
    f0 = tr.f0_hz[np.isfinite(tr.f0_hz)]
    assert f0.size > 0, f"{f} Hz 全盲（IM-24 未自解）"
    assert _median_abs_cent(f0, float(f)) <= 0.5


# ---- §2-3-2 IM-24 自解：1998/1999 必须有声 --------------------------------
@pytest.mark.parametrize("f", (1998, 1999))
def test_im24_voiced(f, monkeypatch):
    tr = _track(monkeypatch, float(f), native=False)
    nv = int(np.isfinite(tr.f0_hz).sum())
    assert nv > 0, f"{f} Hz 仍全盲"


# ---- §2-3-3 2000-exact（R-2）：voiced>0 ∧ 中位残差 < 0 --------------------
def test_2000_exact_voiced_and_negative_residual(monkeypatch):
    tr = _track(monkeypatch, 2000.0, native=False)
    f0 = tr.f0_hz[np.isfinite(tr.f0_hz)]
    assert f0.size > 0  # ★ 仅断言有声，不断言全帧（实测 46/71）
    residual = float(np.median(f0)) - 2000.0
    assert residual < 0.0
    assert float(np.max(f0)) <= 2000.0  # 不触量程闸 :247 丢弃


# ---- §2-3-4 幽灵回归：3000 仍抑 -------------------------------------------
def test_ghost_3000_suppressed(monkeypatch):
    tr = _track(monkeypatch, 3000.0, native=False)
    assert int(np.isfinite(tr.f0_hz).sum()) == 0


# ---- §2-3-5 ON/OFF 逐位（上端＋刀口两侧＋3000）----------------------------
# 两层口径：
# ⒜ (B) 函数级：同一 CMNDF 底物 ⇒ Python/Rust 抛物插值结果必须 float 逐位相等
#    （纯算术同式同序·PI-T68 M-3）；
# ⒝ track 级：voiced 掩码严格逐位；f0 仅允许 difference_function FFT 的 R1
#    继承 ULP 噪声（max|Δd|≤1e-9 档·实测 f0 ≤6.83e-13 Hz·远在 AT-1007 的
#    max(0.1Hz,1cent) 档内 9 个数量级），(B) 本身零分叉。
INHERITED_ULP_BOUND_HZ = 1e-9
CENT_RATIO = 2.0 ** (1.0 / 1200.0) - 1.0


@pytest.mark.parametrize("f", BITEXACT_FREQS)
def test_parabolic_detilt_bitexact_same_substrate(f, monkeypatch):
    """⒜ 同底物函数级逐位：(B) 反倾斜两侧同式的直接证据。"""
    x = _sine(float(f))
    monkeypatch.delenv(ENV, raising=False)
    dn = pyin.cumulative_mean_normalized(pyin.difference_function(x))
    tau0 = max(2, int(round(SR / float(f))))
    taus = [0, 1, 2, tau0 - 2, tau0 - 1, tau0, tau0 + 1, tau0 + 2, dn.size - 1]
    taus = sorted({t for t in taus if 0 <= t < dn.size})
    off_vals = [pyin.parabolic_interpolate(dn, int(t)) for t in taus]
    on_vals = [_core.parabolic_interpolate(dn, int(t)) for t in taus]
    assert off_vals == on_vals, f"{f} Hz 同底物插值非逐位（两侧未同式）"
    assert all(type(v) is float for v in off_vals)


@pytest.mark.parametrize("f", BITEXACT_FREQS)
def test_on_off_track_parity(f, monkeypatch):
    """⒝ track 级：voiced 逐位；f0 差异仅 R1 继承 ULP 且在 AT-1007 档内。"""
    off = _track(monkeypatch, float(f), native=False)
    on = _track(monkeypatch, float(f), native=True)
    mo, mn = np.isfinite(off.f0_hz), np.isfinite(on.f0_hz)
    assert np.array_equal(mo, mn), f"{f} Hz voiced 掩码非逐位"
    common = mo & mn
    if common.any():
        d = np.abs(on.f0_hz[common] - off.f0_hz[common])
        tol_at1007 = max(0.1, float(off.f0_hz[common].min()) * CENT_RATIO)
        assert d.max() <= INHERITED_ULP_BOUND_HZ
        assert d.max() <= tol_at1007


# ---- §2-3-6 负对照（R-6）：因子设 1 ⇒ 1998 复盲 ----------------------------
def test_negative_control_factor_one_reblinds_1998(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(pyin, "parabolic_interpolate", _parabolic_factor_one)
    tr = detect_pyin(_sine(1998.0), SR)
    assert int(np.isfinite(tr.f0_hz).sum()) == 0  # 退化原式 ⇒ 1998 重新全盲
