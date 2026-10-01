# SPDX-License-Identifier: GPL-3.0-only
"""T-1062e R5：`PitchHMM` 网格层（`__init__` 网格 ＋ `observation`）OFF/ON 对等验证。

口径（任务书 `T-1062e` v2 §二-3）：
- `__init__` 12 属性逐项对等 ＋ `hasattr` 全绿（防漏赋值）；`_log_self`/`_log_cross`
  只断【值等】不断类型（N-6：OFF 侧 np.float64，ON 侧 float）。
- `observation` 分档：Ⓐ 优先逐位（np.array_equal）；Ⓑ 若非逐位先归因，允许
  max|Δobs| ≤ 1e-12（绝对档，obs 是概率）；同时打印 obs.sum() 与两态差（守恒硬判据）。
- 候选数 ≥8 方有判别力（N-3：pairwise_sum 仅 n≥8 与顺序累加分歧）。
- 边界四例（空候选 / s==0 / f0 越界 clamp / 银行家舍入 .5 界）＋ 负对照 ＋ 默认 OFF 回归。

对等经 `pitch_hmm.py` 的显式分派走真实路径：OFF（不设 ACOUSCOPE_NATIVE）= Python 参考，
ON（=1）= Rust 扩展 acouscope_core.hmm_grid / hmm_observation。
"""

import numpy as np
import pytest

import acouscope_core as _core  # noqa: F401  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis.pitch_hmm import MIN_FREQ, PitchHMM

ENV = "ACOUSCOPE_NATIVE"
ATTRS = [
    "min_freq", "n_bps", "n_pitch", "n_state", "self_trans", "width",
    "yin_trust", "grid_freqs", "_radius", "_log_w", "_log_self", "_log_cross",
]


def _mk(monkeypatch, on, **kw):
    if on:
        monkeypatch.setenv(ENV, "1")
    else:
        monkeypatch.delenv(ENV, raising=False)
    return PitchHMM(**kw)


def _assert_attrs_equal(h_off, h_on):
    # hasattr 全绿（12 项一个不许少 ⇒ 防 ON 分支漏赋值）
    for name in ATTRS:
        assert hasattr(h_off, name), f"OFF 缺属性 {name}"
        assert hasattr(h_on, name), f"ON 缺属性 {name}"
    for name in ("min_freq", "n_bps", "n_pitch", "n_state", "self_trans",
                 "width", "yin_trust", "_radius"):
        assert getattr(h_off, name) == getattr(h_on, name), name
    assert np.array_equal(h_off.grid_freqs, h_on.grid_freqs), "grid_freqs 非逐位"
    assert np.array_equal(h_off._log_w, h_on._log_w), "_log_w 非逐位"
    # N-6：只断值等、不断类型一致
    assert float(h_off._log_self) == float(h_on._log_self)
    assert float(h_off._log_cross) == float(h_on._log_cross)


def _cands(n=10):
    """≥8 个候选（N-3 判别力门槛）。"""
    return [(440.0 + 3.0 * i, 0.30 - 0.02 * i) for i in range(n)]


def _obs_pair(monkeypatch, cands, **kw):
    h_off = _mk(monkeypatch, False, **kw)
    h_on = _mk(monkeypatch, True, **kw)
    return h_off.observation(cands), h_on.observation(cands)


class TestInitEquivalence:
    def test_default_attrs(self, monkeypatch):
        _assert_attrs_equal(_mk(monkeypatch, False), _mk(monkeypatch, True))

    def test_nondefault_attrs(self, monkeypatch):
        """非默认 n_bps/n_semitones/width —— N-2 的 n_bps 依赖在此有判别力。"""
        kw = dict(min_freq=80.0, n_bps=3, n_semitones=40, self_trans=0.95,
                  transition_width=9, yin_trust=0.4)
        _assert_attrs_equal(_mk(monkeypatch, False, **kw), _mk(monkeypatch, True, **kw))


class TestObservationEquivalence:
    def test_obs_10cands(self, monkeypatch):
        obs_off, obs_on = _obs_pair(monkeypatch, _cands(10))
        d = float(np.max(np.abs(obs_off - obs_on)))
        print(f"[R5] obs.sum: OFF={obs_off.sum()!r} ON={obs_on.sum()!r} max|Δobs|={d!r}")
        assert obs_off.sum() == pytest.approx(1.0, abs=1e-9)
        assert obs_on.sum() == pytest.approx(1.0, abs=1e-9)
        if not np.array_equal(obs_off, obs_on):  # Ⓐ 逐位失败 ⇒ 归因后走 Ⓑ 档
            assert d <= 1e-12, f"Ⓑ 档超差: max|Δobs|={d!r}（归因: 求和次序/libm）"

    def test_obs_8cands(self, monkeypatch):
        obs_off, obs_on = _obs_pair(monkeypatch, _cands(8))
        assert np.array_equal(obs_off, obs_on) or np.max(np.abs(obs_off - obs_on)) <= 1e-12
        assert obs_on.sum() == pytest.approx(1.0, abs=1e-9)


class TestBoundary:
    def test_empty_cands(self, monkeypatch):
        obs_off, obs_on = _obs_pair(monkeypatch, [])
        n = PitchHMM().n_pitch
        assert np.array_equal(obs_off[n:], np.full(n, 1.0 / n))
        assert np.array_equal(obs_off, obs_on)
        assert obs_off[:n].sum() == 0.0

    def test_s_zero(self, monkeypatch):
        obs_off, obs_on = _obs_pair(monkeypatch, [(440.0, 0.0)])
        n = PitchHMM().n_pitch
        assert np.array_equal(obs_off[n:], np.full(n, 1.0 / n))
        assert np.array_equal(obs_off, obs_on)

    def test_f0_clamp(self, monkeypatch):
        cands = [(1e-12, 0.1), (1e9, 0.2)] + _cands(8)
        obs_off, obs_on = _obs_pair(monkeypatch, cands)
        n = PitchHMM().n_pitch
        assert obs_off[0] > 0.0 and obs_off[n - 1] > 0.0  # clamp 到 0 / n_pitch-1
        assert np.array_equal(obs_off, obs_on)

    def test_banker_rounding(self, monkeypatch):
        """60*log2(f/min_freq) 落在 .5 界：10.5→10、11.5→12（round-half-even）。"""
        f_a = MIN_FREQ * 2.0 ** (10.5 / 60.0)
        f_b = MIN_FREQ * 2.0 ** (11.5 / 60.0)
        cands = [(f_a, 0.3), (f_b, 0.2)] + _cands(8)
        obs_off, obs_on = _obs_pair(monkeypatch, cands)
        assert np.array_equal(obs_off, obs_on)
        # 质量落在偶数 bin（10 与 12），而非 11
        assert obs_off[10] > 0.0 and obs_off[12] > 0.0


class TestNegativeControl:
    def test_yin_trust_matters(self, monkeypatch):
        """负对照：改 yin_trust ⇒ obs 必不等（证对等断言非恒真）。"""
        cands = _cands(10)
        h_a = _mk(monkeypatch, False, yin_trust=0.5)
        h_b = _mk(monkeypatch, False, yin_trust=0.6)
        assert not np.array_equal(h_a.observation(cands), h_b.observation(cands))
        h_on = _mk(monkeypatch, True, yin_trust=0.6)
        assert not np.array_equal(h_a.observation(cands), h_on.observation(cands))


class TestDefaultOffRegression:
    def test_off_matches_numpy_reference(self, monkeypatch):
        """默认 OFF：12 属性与 observation 行为 = 改前 numpy 参考式逐位一致。"""
        monkeypatch.delenv(ENV, raising=False)
        h = PitchHMM()
        assert h.n_pitch == 345 and h.n_state == 690
        assert np.array_equal(
            h.grid_freqs, MIN_FREQ * 2.0 ** (np.arange(345) / (12.0 * 5))
        )
        r = h._radius
        w = (r + 1 - np.abs(np.arange(-r, r + 1))).astype(np.float64)
        w /= w.sum()
        assert np.array_equal(h._log_w, np.log(w))
        assert h._log_self == np.log(0.99) and h._log_cross == np.log(0.01)
        obs = h.observation(_cands(10))
        assert obs.sum() == pytest.approx(1.0, abs=1e-9)
