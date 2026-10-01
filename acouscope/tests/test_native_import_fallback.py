# SPDX-License-Identifier: GPL-3.0-only
"""T-1073：native 缺 .so 降级三向守卫（①降级不崩·②在场仍 native·③真异常上抛）。"""
import sys

import numpy as np
import pytest

from acouscope.analysis import pitch
from acouscope.audio.player import AudioPlayer

CENT = 2.0 ** (1.0 / 1200.0) - 1.0
_sig = lambda: np.sin(2.0 * np.pi * 440.0 * np.linspace(0, 0.5, 8000, endpoint=False))  # noqa: E731
def _rs(data, target): return AudioPlayer._resample_chunk(None, data, target)  # 免 Qt/self

def test_missing_core_degrades_to_numpy(monkeypatch):
    monkeypatch.setattr(pitch, "_CORE_OK", None)
    monkeypatch.setenv(pitch.ENV_NATIVE, "0")
    off, data = pitch.detect_pyin(_sig(), 8000.0), np.linspace(-1.0, 1.0, 120)
    ref = _rs(data, 60)
    monkeypatch.setitem(sys.modules, "acouscope_core", None)
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    assert pitch.is_native_enabled() is False  # 裸调用：.so 可导入门拦下
    assert pitch.is_native_enabled({pitch.ENV_NATIVE: "1"}) is True  # 显式 env 纯逻辑
    on = pitch.detect_pyin(_sig(), 8000.0)
    assert np.array_equal(np.asarray(off.f0_hz, float), np.asarray(on.f0_hz, float), equal_nan=True)
    assert np.array_equal(np.asarray(off.confidence, float), np.asarray(on.confidence, float))
    assert np.array_equal(_rs(data, 60), ref)  # player 旁路同降级

def test_core_present_still_native(monkeypatch):
    import acouscope_core as cc
    monkeypatch.setattr(pitch, "_CORE_OK", None)
    h, g = [], cc.pyin_hard_gate
    monkeypatch.setattr(cc, "pyin_hard_gate", lambda *a, **k: h.append(1) or g(*a, **k))
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    assert pitch.is_native_enabled() is True
    on = pitch.detect_pyin(_sig(), 8000.0)
    assert h, "ON 分派未走 acouscope_core"
    monkeypatch.setenv(pitch.ENV_NATIVE, "0")
    off = pitch.detect_pyin(_sig(), 8000.0)
    f_off, f_on = np.asarray(off.f0_hz, float), np.asarray(on.f0_hz, float)
    m = np.isfinite(f_off) & np.isfinite(f_on)
    assert m.any() and np.array_equal(np.isfinite(f_off), np.isfinite(f_on))  # voiced 掩码全同
    assert np.all(np.abs(f_off[m] - f_on[m]) <= np.maximum(0.1, f_off[m] * CENT))  # AT-1007 指标1
    assert np.abs(np.asarray(off.confidence) - np.asarray(on.confidence)).max() <= 1e-3  # 指标3

def test_native_error_propagates(monkeypatch):
    import acouscope_core as cc

    def _boom(*_a, **_k):
        raise ValueError("native-calc-probe")
    monkeypatch.setenv(pitch.ENV_NATIVE, "1")
    for name, call in (("native_selfcheck", lambda: pitch.detect_pyin(_sig(), 8000.0)),
                       ("resample_chunk_native", lambda: _rs(np.ones(100), 50))):
        monkeypatch.setattr(cc, name, _boom)
        with pytest.raises(ValueError, match="native-calc-probe"):
            call()