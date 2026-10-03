# SPDX-License-Identifier: GPL-3.0-only
"""T-1062a R1：YIN 基元四函数 OFF/ON 对等验证（本件的证伪器）。

口径（需求说明 §二-3 v2）：
- difference_function：FFT 路径（手写 radix-2 vs numpy pocketfft）⇒ 放宽档 max|Δ| ≤ 1e-9，
  逐位相同则最佳（打印实测值）。
- 其余三函数：np.array_equal 逐位档（含 dtype 一致），不许放宽。
- 负对照：证明 equal 断言非恒真。
- 边界例：空数组 / 单元素 / tau 端点。
- 默认 OFF 回归：不设环境变量时形状/类型与原实现一致。

对等经 pyin.py 的显式分派走真实路径：OFF（不设 ACOUSCOPE_NATIVE）= numpy 参考，
ON（=1）= Rust 扩展。
"""

import numpy as np
import pytest

import acouscope_core as _core  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis import pyin

ENV = "ACOUSCOPE_NATIVE"


def _sine(freq, n=2048, sr=44100.0, amp=0.5):
    t = np.arange(n) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def _inputs():
    rng = np.random.default_rng(20260919)
    return [
        _sine(220.0),
        _sine(440.0, n=1024),
        0.5 * _sine(110.0) + 0.25 * _sine(220.0),
        rng.uniform(-1.0, 1.0, 2048),
    ]


def _off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _on(monkeypatch):
    monkeypatch.setenv(ENV, "1")


class TestEquivalence:
    def test_difference_function_max_abs(self, monkeypatch):
        """⒜ 放宽档：max|Δ| ≤ 1e-9（逐位相同则最佳，打印实测值）。"""
        for x in _inputs():
            _off(monkeypatch)
            a = pyin.difference_function(x)  # numpy 参考
            _on(monkeypatch)
            b = pyin.difference_function(x)  # Rust
            assert a.shape == b.shape
            assert b.dtype == np.float64
            max_abs = float(np.max(np.abs(a - b)))
            print(f"[diff-fn] max|Δ| = {max_abs:.3e}  bit_exact = {np.array_equal(a, b)}")
            assert max_abs <= 1e-9

    def test_cumulative_mean_normalized_bitexact(self, monkeypatch):
        """⒝ 逐位档：np.cumsum 顺序累加同序 ⇒ 要求逐位。"""
        _off(monkeypatch)
        for x in _inputs():
            d = pyin.difference_function(x)  # OFF 参考输入
            a = pyin.cumulative_mean_normalized(d)
            _on(monkeypatch)
            b = pyin.cumulative_mean_normalized(d)
            _off(monkeypatch)
            assert np.array_equal(a, b), "bit-exact fail"
            assert a.dtype == b.dtype == np.float64

    def test_local_minima_bitexact(self, monkeypatch):
        _off(monkeypatch)
        for x in _inputs():
            dn = pyin.cumulative_mean_normalized(pyin.difference_function(x))
            for tmin, tmax in [(2, 100), (5, 500), (1, 1024)]:
                a = pyin.local_minima(dn, tmin, tmax)
                _on(monkeypatch)
                b = pyin.local_minima(dn, tmin, tmax)
                _off(monkeypatch)
                assert np.array_equal(a, b)
                assert a.dtype == b.dtype == np.int64

    def test_parabolic_interpolate_bitexact(self, monkeypatch):
        _off(monkeypatch)
        for x in _inputs():
            dn = pyin.cumulative_mean_normalized(pyin.difference_function(x))
            for tau in [1, 2, 50, 100, 512, 1023, 1024]:
                a = pyin.parabolic_interpolate(dn, tau)
                _on(monkeypatch)
                b = pyin.parabolic_interpolate(dn, tau)
                _off(monkeypatch)
                assert a == b, f"{tau}: {a!r} vs {b!r}"
                assert type(a) is float and type(b) is float


class TestNegativeControl:
    """负对照：证明上面的 equal 断言具判别力（非恒真）。"""

    def test_different_inputs_differ(self):
        a = _core.difference_function(_sine(220.0))
        b = _core.difference_function(_sine(221.0))
        assert not np.array_equal(a, b)

    def test_local_minima_window_shift_differs(self):
        dn = _core.cumulative_mean_normalized(_core.difference_function(_sine(220.0)))
        a = _core.local_minima(dn, 2, 300)  # 仅含首个谷底 [200]
        b = _core.local_minima(dn, 2, 1024)  # 含全部五次谐波谷底
        assert a.size == 1 and b.size > 1
        assert not np.array_equal(a, b)

    def test_dispatch_on_really_reaches_rust(self, monkeypatch):
        """ON 时确实走 Rust：打补丁 _core，分派必须命中补丁。"""
        called = {}

        def _boom(frame):
            called["hit"] = True
            return np.zeros(1)

        monkeypatch.setattr(_core, "difference_function", _boom)
        _on(monkeypatch)
        pyin.difference_function(_sine(220.0))
        assert called.get("hit"), "ON 分派未走 acouscope_core"


class TestEdgeCases:
    def test_difference_function_empty_raises_overflowerror(self, monkeypatch):
        """空数组：Python 侧 log2(0)=-inf ⇒ OverflowError；Rust 侧须同类。"""
        e = np.array([], dtype=np.float64)
        _off(monkeypatch)
        with pytest.warns(RuntimeWarning):
            with pytest.raises(OverflowError):
                pyin.difference_function(e)
        with pytest.raises(OverflowError):
            _core.difference_function(e)

    def test_difference_function_single_element(self):
        x = np.array([0.5])
        a = _core.difference_function(x)
        assert np.array_equal(a, np.array([0.0]))
        assert a.shape == (1,)

    def test_local_minima_empty_window(self):
        """hi - lo < 2 ⇒ 空 int64 数组（两侧一致）。"""
        dn = np.array([1.0, 0.5, 1.0])
        a = pyin.local_minima(dn, 1, 2)  # OFF 参考
        b = _core.local_minima(dn, 1, 2)
        assert a.size == 0 and b.size == 0
        assert a.dtype == b.dtype == np.int64
        assert np.array_equal(a, b)

    def test_parabolic_tau_endpoints(self):
        dn = np.array([1.0, 0.5, 0.2, 0.5, 1.0])
        for tau in (0, -3, 4, 10):  # 早退分支：tau<=0 或 tau>=size-1
            assert pyin.parabolic_interpolate(dn, tau) == float(tau)
            assert _core.parabolic_interpolate(dn, tau) == float(tau)

    def test_parabolic_flat_denom(self):
        """|denom| < 1e-12 ⇒ 早退 float(tau)。"""
        dn = np.array([0.0, 0.0, 0.0, 0.0])
        assert pyin.parabolic_interpolate(dn, 1) == 1.0
        assert _core.parabolic_interpolate(dn, 1) == 1.0

    def test_cumulative_mean_empty_and_single(self):
        e = np.array([], dtype=np.float64)
        assert np.array_equal(pyin.cumulative_mean_normalized(e), _core.cumulative_mean_normalized(e))
        s = np.array([3.0])
        a = pyin.cumulative_mean_normalized(s)
        b = _core.cumulative_mean_normalized(s)
        assert np.array_equal(a, b)


class TestDefaultOffRegression:
    """默认 OFF（不设环境变量）⇒ 走原 numpy 分支，形状/类型逐位不变。"""

    def test_off_shapes_types(self, monkeypatch):
        _off(monkeypatch)
        x = _sine(440.0)
        d = pyin.difference_function(x)
        dn = pyin.cumulative_mean_normalized(d)
        minima = pyin.local_minima(dn, 2, 500)
        p = pyin.parabolic_interpolate(dn, int(minima[0]))
        assert d.shape == (x.size // 2 + 1,)
        assert d.dtype == np.float64 and dn.dtype == np.float64
        assert minima.dtype == np.int64
        assert type(p) is float

    def test_off_never_touches_core(self, monkeypatch):
        """OFF 时打补丁 _core 不得被触发（分派短路于 is_native_enabled）。"""
        def _boom(*a, **k):
            raise AssertionError("native called while OFF")

        for name in ("difference_function", "cumulative_mean_normalized",
                     "local_minima", "parabolic_interpolate"):
            monkeypatch.setattr(_core, name, _boom)
        _off(monkeypatch)
        x = _sine(220.0)
        d = pyin.difference_function(x)
        dn = pyin.cumulative_mean_normalized(d)
        pyin.local_minima(dn, 2, 100)
        pyin.parabolic_interpolate(dn, 50)
