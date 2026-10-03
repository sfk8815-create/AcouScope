# SPDX-License-Identifier: GPL-3.0-only
"""T-1062b R2：Beta CDF 三函数 OFF/ON 对等验证（本件的证伪器）。

口径（需求说明 §二-3 v2.2）：
- 三函数**统一逐位档** `np.array_equal`：R-2 路线 (b) = Rust 复刻 CPython `m_lgamma`
  ⇒ 与 Python `math.lgamma` 逐位等价；worst max|Δ| 必须 ≤ 1e-14（打印实测值）。
- 负对照：证明 equal 断言非恒真（含「ON 分派确实命中 Rust」）。
- 边界例：`_beta_cdf` 端点 / 空数组 / `max_iter` 极端值。
- 收窄面负对照（R-7）：ON 下 `float32` / 2D 输入须抛**明确异常**，不得静默错值。
- 默认 OFF 回归：不设环境变量时形状/类型与原实现一致（float32/2D 仍按旧行为）。

对等经 pyin.py 的显式分派走真实路径：OFF（不设 ACOUSCOPE_NATIVE）= math/numpy 参考，
ON（=1）= Rust 扩展。
"""

import numpy as np
import pytest

import acouscope_core as _core  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis import pyin

ENV = "ACOUSCOPE_NATIVE"


def _off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _on(monkeypatch):
    monkeypatch.setenv(ENV, "1")


def _cases():
    """(a, b, xs)：覆盖对称分支分界 x < (a+1)/(a+b+2) 两侧 + 极参。"""
    rng = np.random.default_rng(20260919)
    return [
        (2.0, 3.0, np.linspace(0.0, 1.0, 51)),
        (0.5, 0.5, rng.uniform(0.0, 1.0, 128)),
        (5.0, 1.5, np.array([1e-12, 0.01, 0.2, 0.5, 0.75, 0.99, 1.0 - 1e-12])),
        (50.0, 0.3, np.linspace(0.0, 0.3, 31)),
        (1.0, 1.0, np.array([0.0, 0.25, 0.5, 0.75, 1.0])),
        (0.3, 50.0, np.linspace(0.7, 1.0, 31)),
        (1000.0, 2000.0, np.linspace(0.3, 0.7, 41)),  # 大参数：lgamma 量级 ~2e4（1ulp 放大敏感）
    ]


class TestEquivalence:
    def test_betacf_bitexact(self, monkeypatch):
        """Ⓐ `_betacf`（逐位档）：纯算术连分式 ⇒ 须逐位；含 max_iter 极端值。"""
        worst = 0.0
        for a, b, x in [(2.0, 3.0, 0.3), (0.5, 0.5, 0.7), (5.0, 1.5, 0.95), (50.0, 0.3, 0.01)]:
            for mi in (300, 1, 2, 7, 1000):
                _off(monkeypatch)
                ref = pyin._betacf(a, b, x, mi)
                _on(monkeypatch)
                got = pyin._betacf(a, b, x, mi)
                _off(monkeypatch)
                d = abs(ref - got)
                worst = max(worst, d)
                print(f"[betacf] a={a} b={b} x={x} max_iter={mi} max|Δ|={d:.3e} bit_exact={ref == got}")
                assert d <= 1e-14, "max|Δ| > 1e-14 ⇒ 停并报（铁律：精度只可提升）"
                assert ref == got, "bit-exact fail"
        print(f"[betacf] worst max|Δ| = {worst:.3e}")

    def test_betacf_default_max_iter(self, monkeypatch):
        """`_core._betacf(a,b,x)` 走 signature 默认 300 ⇒ 与 Python 默认参数逐位一致。"""
        _off(monkeypatch)
        ref = pyin._betacf(2.0, 3.0, 0.3)
        _on(monkeypatch)
        got = pyin._betacf(2.0, 3.0, 0.3)
        _off(monkeypatch)
        assert ref == got == _core._betacf(2.0, 3.0, 0.3)

    def test_beta_cdf_bitexact(self, monkeypatch):
        """Ⓑ `_beta_cdf`（逐位档）：复刻 m_lgamma ⇒ 与 math.lgamma 逐位等价。"""
        worst = 0.0
        for a, b, xs in _cases():
            for x in xs:
                xf = float(x)
                _off(monkeypatch)
                ref = pyin._beta_cdf(xf, a, b)
                _on(monkeypatch)
                got = pyin._beta_cdf(xf, a, b)
                _off(monkeypatch)
                d = abs(ref - got)
                worst = max(worst, d)
                assert d <= 1e-14, f"a={a} b={b} x={xf}: max|Δ| > 1e-14 ⇒ 停并报"
                assert ref == got, f"bit-exact fail: a={a} b={b} x={xf} {ref!r} vs {got!r}"
        print(f"[beta_cdf] worst max|Δ| = {worst:.3e} (逐位档, 全例 bit_exact=True)")

    def test_beta_cdf_arr_bitexact(self, monkeypatch):
        """Ⓑ `_beta_cdf_arr`（逐位档）：逐元素 = 标量版 ⇒ array_equal 且 dtype float64。"""
        worst = 0.0
        for a, b, xs in _cases():
            _off(monkeypatch)
            ref = pyin._beta_cdf_arr(xs, a, b)
            _on(monkeypatch)
            got = pyin._beta_cdf_arr(xs, a, b)
            _off(monkeypatch)
            assert got.shape == ref.shape
            assert got.dtype == ref.dtype == np.float64
            d = float(np.max(np.abs(ref - got))) if ref.size else 0.0
            worst = max(worst, d)
            print(f"[beta_cdf_arr] a={a} b={b} n={xs.size} max|Δ|={d:.3e} array_equal={np.array_equal(ref, got)}")
            assert d <= 1e-14, f"a={a} b={b}: max|Δ| > 1e-14 ⇒ 停并报"
            assert np.array_equal(ref, got), "bit-exact fail"
        print(f"[beta_cdf_arr] worst max|Δ| = {worst:.3e}")


class TestNegativeControl:
    """负对照：证明上面的 equal 断言具判别力（非恒真）。"""

    def test_betacf_input_shift_differs(self):
        a = _core._betacf(2.0, 3.0, 0.3, 300)
        b = _core._betacf(2.0, 3.0, 0.300001, 300)
        assert a != b

    def test_beta_cdf_input_shift_differs(self):
        xs = np.linspace(0.05, 0.95, 33)
        a = _core._beta_cdf_arr(xs, 2.0, 3.0)
        b = _core._beta_cdf_arr(xs + 1e-9, 2.0, 3.0)
        assert not np.array_equal(a, b)

    def test_beta_cdf_param_swap_differs(self):
        xs = np.linspace(0.05, 0.95, 33)
        assert not np.array_equal(
            _core._beta_cdf_arr(xs, 2.0, 3.0), _core._beta_cdf_arr(xs, 3.0, 2.0)
        )

    def test_dispatch_on_really_reaches_rust(self, monkeypatch):
        """ON 时三函数确实走 Rust：打补丁 _core，分派必须命中补丁。"""
        called = {}

        def _boom(*a, **k):
            called["hit"] = True
            return np.zeros(1)

        for name in ("_betacf", "_beta_cdf", "_beta_cdf_arr"):
            monkeypatch.setattr(_core, name, _boom)
        monkeypatch.setattr(pyin, "_betacf", pyin._betacf, raising=True)
        _on(monkeypatch)
        pyin._betacf(2.0, 3.0, 0.3, 300)
        pyin._beta_cdf(0.3, 2.0, 3.0)
        pyin._beta_cdf_arr(np.array([0.3]), 2.0, 3.0)
        assert called.get("hit"), "ON 分派未走 acouscope_core"


class TestEdgeCases:
    def test_beta_cdf_endpoints(self, monkeypatch):
        """端点：x<=0 ⇒ 0.0；x>=1 ⇒ 1.0（两侧逐位一致）。"""
        for x, want in [(-0.5, 0.0), (0.0, 0.0), (-0.0, 0.0), (1.0, 1.0), (1.5, 1.0)]:
            _off(monkeypatch)
            ref = pyin._beta_cdf(x, 2.0, 3.0)
            _on(monkeypatch)
            got = pyin._beta_cdf(x, 2.0, 3.0)
            _off(monkeypatch)
            assert ref == got == want, f"x={x}: {ref!r} vs {got!r}"

    def test_beta_cdf_arr_empty(self, monkeypatch):
        """空数组 ⇒ 空 float64（形状/类型两侧一致）。"""
        e = np.array([], dtype=np.float64)
        _off(monkeypatch)
        ref = pyin._beta_cdf_arr(e, 2.0, 3.0)
        _on(monkeypatch)
        got = pyin._beta_cdf_arr(e, 2.0, 3.0)
        _off(monkeypatch)
        assert ref.shape == got.shape == (0,)
        assert ref.dtype == got.dtype == np.float64

    def test_beta_cdf_arr_single_element(self, monkeypatch):
        s = np.array([0.3])
        _off(monkeypatch)
        ref = pyin._beta_cdf_arr(s, 2.0, 3.0)
        _on(monkeypatch)
        got = pyin._beta_cdf_arr(s, 2.0, 3.0)
        _off(monkeypatch)
        assert ref.shape == got.shape == (1,)
        assert np.array_equal(ref, got)

    def test_betacf_extreme_max_iter(self, monkeypatch):
        """max_iter=0 / 负数 ⇒ 循环不执行（两侧同形）。"""
        for mi in (0, -5):
            _off(monkeypatch)
            ref = pyin._betacf(2.0, 3.0, 0.3, mi)
            _on(monkeypatch)
            got = pyin._betacf(2.0, 3.0, 0.3, mi)
            _off(monkeypatch)
            assert ref == got

    def test_beta_cdf_arr_float32_raises_when_on(self, monkeypatch):
        """R-7 收窄面：ON 下 float32 ⇒ 须抛明确异常（不得静默错值）。"""
        f32 = np.linspace(0.1, 0.9, 9, dtype=np.float32)
        _on(monkeypatch)
        with pytest.raises((TypeError, ValueError)) as ei:
            pyin._beta_cdf_arr(f32, 2.0, 3.0)
        print(f"[R-7] float32 -> {type(ei.value).__name__}: {ei.value}")
        assert str(ei.value)

    def test_beta_cdf_arr_2d_raises_when_on(self, monkeypatch):
        """R-7 收窄面：ON 下 2D ⇒ 须抛明确异常（不得静默错值）。"""
        two_d = np.linspace(0.1, 0.9, 9).reshape(3, 3)
        _on(monkeypatch)
        with pytest.raises((TypeError, ValueError)) as ei:
            pyin._beta_cdf_arr(two_d, 2.0, 3.0)
        print(f"[R-7] 2D -> {type(ei.value).__name__}: {ei.value}")
        assert str(ei.value)


class TestDefaultOffRegression:
    """默认 OFF（不设环境变量）⇒ 走原 math/numpy 分支，行为零变化。"""

    def test_off_shapes_types(self, monkeypatch):
        _off(monkeypatch)
        xs = np.linspace(0.0, 1.0, 21)
        arr = pyin._beta_cdf_arr(xs, 2.0, 3.0)
        assert arr.shape == (21,) and arr.dtype == np.float64
        assert type(pyin._beta_cdf(0.3, 2.0, 3.0)) is float
        assert type(pyin._betacf(2.0, 3.0, 0.3)) is float

    def test_off_accepts_float32_and_2d(self, monkeypatch):
        """OFF 保持旧行为：float32 / 2D 静默转换（R-7 只约束 ON 面）。"""
        _off(monkeypatch)
        f32 = np.linspace(0.1, 0.9, 9, dtype=np.float32)
        a = pyin._beta_cdf_arr(f32, 2.0, 3.0)
        assert a.shape == (9,) and a.dtype == np.float64
        two_d = np.linspace(0.1, 0.9, 9).reshape(3, 3)
        b = pyin._beta_cdf_arr(two_d, 2.0, 3.0)
        assert b.shape == (3, 3) and b.dtype == np.float64

    def test_off_never_touches_core(self, monkeypatch):
        """OFF 时打补丁 _core 不得被触发（分派短路于 is_native_enabled）。"""
        def _boom(*a, **k):
            raise AssertionError("native called while OFF")

        for name in ("_betacf", "_beta_cdf", "_beta_cdf_arr"):
            monkeypatch.setattr(_core, name, _boom)
        _off(monkeypatch)
        pyin._betacf(2.0, 3.0, 0.3, 300)
        pyin._beta_cdf(0.3, 2.0, 3.0)
        pyin._beta_cdf_arr(np.linspace(0.1, 0.9, 9), 2.0, 3.0)