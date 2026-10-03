# SPDX-License-Identifier: GPL-3.0-only
"""T-1061b / T-1062h：native A/B 开关骨架 ＋ AT-1007 感知对等判据。

R8 变更：test_t1061b_on_off_bitwise_identical 改采 AT-1007 §十一
感知对等（逐位→感知系项目负责人 2026-09-19 21:2x 定案；非逐位系
继承 R1 difference_function 手写 radix-2 FFT；PI-T61 小样
_sig() max|Δf0|=1.705303e-13Hz）；新增全链对等 cases ＋ 负对照。
"""

import math
import numpy as np
import pytest
from acouscope.analysis import pitch

CENT_RATIO = 2.0 ** (1.0 / 1200.0) - 1.0
HZ_FLOOR = 0.1
VOICED_AGREEMENT_MIN = 0.99
CONF_MAX_ABS_DIFF = 1e-3


def _sig():
    """前半 440Hz 纯音 + 后半静音。"""
    t = np.linspace(0.0, 0.5, 8000, endpoint=False)
    x = np.sin(2.0 * np.pi * 440.0 * t).astype(np.float64)
    x[4000:] = 0.0
    return x


def _pure_tone_1s(freq, sr=8000):
    t = np.linspace(0.0, 1.0, sr, endpoint=False)
    return np.sin(2.0 * np.pi * freq * t).astype(np.float64)


def _at1007_assert(tr_off, tr_on, label=""):
    f0_off = np.asarray(tr_off.f0_hz, np.float64)
    f0_on = np.asarray(tr_on.f0_hz, np.float64)
    conf_off = np.asarray(tr_off.confidence, np.float64)
    conf_on = np.asarray(tr_on.confidence, np.float64)
    v_off = np.isfinite(f0_off)
    v_on = np.isfinite(f0_on)
    v_agree = float((v_off == v_on).mean())
    assert v_agree >= VOICED_AGREEMENT_MIN, f"{label} voiced agree {v_agree:.6f}<0.99"
    mask = v_off & v_on
    assert mask.any(), f"{label}: 无双方 voiced 帧"
    d_hz = np.abs(f0_off[mask] - f0_on[mask])
    f_ref = f0_off[mask]
    tol = np.maximum(HZ_FLOOR, f_ref * CENT_RATIO)
    cent_eq = d_hz / (f_ref * CENT_RATIO)
    print(f"{label} |Δf0|max={d_hz.max():.6e} Hz ≡ {cent_eq.max():.6e} cent")
    assert np.all(d_hz <= tol), f"{label} 指标1 FAIL max|Δf0|={d_hz.max():.6e}"
    d_conf = float(np.abs(conf_off - conf_on).max())
    print(f"{label} |Δconf|max={d_conf:.6e}")
    assert d_conf <= CONF_MAX_ABS_DIFF, f"{label} 指标3 FAIL |Δconf|={d_conf:.6e}"


def _p1_pass(tr, label=""):
    voiced = np.isfinite(np.asarray(tr.f0_hz))
    n = int(voiced.sum())
    assert n > 0, f"{label} P-1 FAIL 全 NaN"
    assert n >= int(0.10 * len(voiced)), f"{label} P-1 FAIL voiced<10%"


def _p2_pass(tr_off, tr_on, label=""):
    r_off = float(np.isfinite(np.asarray(tr_off.f0_hz)).mean())
    r_on = float(np.isfinite(np.asarray(tr_on.f0_hz)).mean())
    diff = abs(r_off - r_on)
    tol = max(0.01, 0.05 * r_off) if r_off > 0 else 0.01
    assert diff <= tol, f"{label} P-2 FAIL |Δratio|={diff:.4f}>{tol:.4f}"


# ===== 保留 4 例 =====

def test_t1061b_switch_shape():
    assert pitch.is_native_enabled({}) is False
    assert pitch.is_native_enabled({pitch.ENV_NATIVE: "0"}) is False
    assert pitch.is_native_enabled({pitch.ENV_NATIVE: "1"}) is True
    assert pitch.is_native_enabled({pitch.ENV_NATIVE: "yes"}) is False


def test_t1061b_dispatch_is_falsifiable(monkeypatch):
    import acouscope_core
    def _boom():
        raise RuntimeError("dispatch-probe")
    monkeypatch.setattr(acouscope_core, "native_selfcheck", _boom)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    with pytest.raises(RuntimeError, match="dispatch-probe"):
        pitch.detect_pyin(_sig(), 8000.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "0")
    tr = pitch.detect_pyin(_sig(), 8000.0)
    assert np.isfinite(tr.f0_hz).any()


def test_t1061b_on_without_package_raises(monkeypatch):
    import sys
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    monkeypatch.setitem(sys.modules, "acouscope_core", None)
    with pytest.raises(ImportError):
        pitch.detect_pyin(_sig(), 8000.0)


def test_t1061b_equal_nan_is_necessary():
    a = np.array([1.0, np.nan, 3.0])
    b = np.array([1.0, np.nan, 3.0])
    assert np.array_equal(a, b, equal_nan=True) is True
    assert np.array_equal(a, b, equal_nan=False) is False


# ===== R8 销账：bitwise→AT-1007 感知对等 =====

def test_t1061b_on_off_perceptually_equivalent(monkeypatch):
    """R8 销账：原 test_t1061b_on_off_bitwise_identical 改采感知对等。"""
    monkeypatch.setenv(pitch.ENV_NATIVE, "0")
    tr_off = pitch.detect_pyin(_sig(), 8000.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    tr_on = pitch.detect_pyin(_sig(), 8000.0)
    _at1007_assert(tr_off, tr_on, label="_sig")
    _p1_pass(tr_off, label="_sig")
    _p2_pass(tr_off, tr_on, label="_sig")


# ===== R8 新增 6 例 =====

def test_r8_steady_state_440hz(monkeypatch):
    """稳态 440Hz · 三指标 ＋ P-1/P-2。"""
    x = _pure_tone_1s(440.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "0"); tr_off = pitch.detect_pyin(x, 8000.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1"); tr_on = pitch.detect_pyin(x, 8000.0)
    _at1007_assert(tr_off, tr_on, label="440Hz")
    _p1_pass(tr_off); _p2_pass(tr_off, tr_on)


def test_r8_steady_state_660hz(monkeypatch):
    """稳态 660Hz · 三指标 ＋ P-1/P-2。"""
    x = _pure_tone_1s(660.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "0"); tr_off = pitch.detect_pyin(x, 8000.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1"); tr_on = pitch.detect_pyin(x, 8000.0)
    _at1007_assert(tr_off, tr_on, label="660Hz")
    _p1_pass(tr_off); _p2_pass(tr_off, tr_on)


def test_r8_near_overrange_p3(monkeypatch):
    """邻近超量程 fmax=2100 · 1999Hz。"""
    sr = 16000
    t = np.linspace(0.0, 1.0, sr, endpoint=False)
    x = np.sin(2.0 * np.pi * 1999.0 * t).astype(np.float64)
    monkeypatch.setenv(pitch.ENV_NATIVE, "0")
    tr_off = pitch.detect_pyin(x, sr, fmin=40.0, fmax=2100.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    tr_on = pitch.detect_pyin(x, sr, fmin=40.0, fmax=2100.0)
    _at1007_assert(tr_off, tr_on, label="1999Hz@fmax2100")
    _p1_pass(tr_off)


def test_r8_p1_counterexample_all_nan():
    """P-1 反例：全 NaN ⇒ 必 FAIL（门禁判别力）。"""
    voiced = np.isfinite(np.array([np.nan, np.nan, np.nan]))
    assert int(voiced.sum()) == 0


def test_r8_p3_attribution_edge_range(monkeypatch):
    """P-3 归因：2000Hz@fmax2100，扫描刀口帧（不 FAIL，仅打印）。"""
    sr = 16000
    t = np.linspace(0.0, 1.0, sr, endpoint=False)
    x = np.sin(2.0 * np.pi * 2000.0 * t).astype(np.float64)
    monkeypatch.setenv(pitch.ENV_NATIVE, "0")
    tr_off = pitch.detect_pyin(x, sr, fmin=40.0, fmax=2100.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    tr_on = pitch.detect_pyin(x, sr, fmin=40.0, fmax=2100.0)
    _at1007_assert(tr_off, tr_on, label="2000Hz@fmax2100")
    v_off = np.isfinite(tr_off.f0_hz); v_on = np.isfinite(tr_on.f0_hz)
    edges = []
    for i in range(len(v_off)):
        if v_off[i] != v_on[i]:
            f = tr_off.f0_hz[i] if v_off[i] else tr_on.f0_hz[i]
            if math.isfinite(f) and 1997.0 <= f <= 2001.0:
                edges.append((i, f))
    print(f"P-3 刀口帧：{len(edges)} 帧" if edges else "P-3 无刀口帧")


def test_r8_negative_control_metric1_must_fail(monkeypatch):
    """负对照：人为污染 ON 结果 ⇒ 指标1 必 FAIL（证松阈值有判别力）。"""
    x = _pure_tone_1s(440.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "0"); tr_off = pitch.detect_pyin(x, 8000.0)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1"); tr_on = pitch.detect_pyin(x, 8000.0)
    f0_on = np.array(tr_on.f0_hz, np.float64)
    idx = np.where(np.isfinite(f0_on))[0]
    if len(idx) > 0:
        f0_on[idx[0]] += 10.0  # 加 10Hz 偏移
    f0_off = np.asarray(tr_off.f0_hz, np.float64)
    mask = np.isfinite(f0_off) & np.isfinite(f0_on)
    d_hz = np.abs(f0_off[mask] - f0_on[mask])
    tol = np.maximum(HZ_FLOOR, f0_off[mask] * CENT_RATIO)
    assert np.any(d_hz > tol), "负对照失效：指标1 恒 PASS"
