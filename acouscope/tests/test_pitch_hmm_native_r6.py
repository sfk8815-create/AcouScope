# SPDX-License-Identifier: GPL-3.0-only
"""T-1062f R6：`PitchHMM._viterbi_step` 与 `decode(fixed_lag=None)` OFF/ON 对等验证。

口径（需求说明 `T-1062f` v2 §二-3）：
1. `_viterbi_step` 对等：随机 delta_log/obs_log（★ 一律按 (2, n_pitch) 构造，N-3）
   ＋ -inf/有限值混合；new（f64）Ⓐ 优先逐位、Ⓑ 归因后 max|Δnew| ≤ 1e-12；
   bp_d/bp_v ★ int8 且逐位。
2. `decode(fixed_lag=None)` 对等：f0_hz（NaN 位置一致）、voiced（bool 逐位）、
   states（dtype 与 OFF 相同且逐位）；Ⓑ 档 f0 用 max(0.1 Hz, 1 cent @ f0) ＋ Hz/cent 双打印。
3. `fixed_lag=100` 面【不变】：ON 与 OFF 的 fixed_lag=100 输出逐位相同（防无条件分派吞 R7 面）。
4. 边界例：n_frames==0 / 单帧 / 全空候选 / 清音帧 / argmax 平手（对称 delta）/ min 平手。
5. 负对照：改 log_self ⇒ new 必不等（证对等断言非恒真）。

对等经 `pitch_hmm.py` 的显式分派走真实路径：OFF（不设 ACOUSCOPE_NATIVE）= Python 参考，
ON（=1）= Rust 扩展 acouscope_core.hmm_viterbi_step / hmm_decode_full。
"""

import numpy as np
import pytest

import acouscope_core as _core  # noqa: F401  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis.pitch_hmm import PitchHMM

ENV = "ACOUSCOPE_NATIVE"


def _mk(monkeypatch, on, **kw):
    if on:
        monkeypatch.setenv(ENV, "1")
    else:
        monkeypatch.delenv(ENV, raising=False)
    return PitchHMM(**kw)


def _rand_pair(h, seed, mix_inf=True):
    """按 (2, n_pitch) 构造随机 delta_log / obs_log（N-3 甲 · 丁：C 连续）。"""
    rng = np.random.default_rng(seed)
    delta = rng.normal(-8.0, 3.0, size=(2, h.n_pitch))
    obs = rng.normal(-6.0, 2.0, size=(2, h.n_pitch))
    if mix_inf:  # -inf 与有限值混合（陷阱① 的平手/不更新路径）
        delta[rng.random(delta.shape) < 0.15] = -np.inf
        obs[rng.random(obs.shape) < 0.05] = -np.inf
    return delta, obs


def _assert_step_equal(step_off, step_on):
    """step_* = (new, bp_d, bp_v) 三元组（★ 按返回序解包）。"""
    new_off, bpd_off, bpv_off = step_off
    new_on, bpd_on, bpv_on = step_on
    # bp_d / bp_v：int8 且逐位（陷阱②）
    assert bpd_off.dtype == np.int8 and bpd_on.dtype == np.int8
    assert bpv_off.dtype == np.int8 and bpv_on.dtype == np.int8
    assert np.array_equal(bpd_off, bpd_on), "bp_d 非逐位"
    assert np.array_equal(bpv_off, bpv_on), "bp_v 非逐位"
    # new：f64；Ⓐ 优先逐位，Ⓑ 归因后 ≤1e-12（绝对档 · log 域）
    assert new_off.dtype == np.float64 and new_on.dtype == np.float64
    if not np.array_equal(new_off, new_on):
        d = float(np.nanmax(np.abs(new_off - new_on)))
        print(f"[R6] new 非逐位 ⇒ Ⓑ 档归因: max|Δnew|={d!r}")
        assert d <= 1e-12, f"Ⓑ 档超差: max|Δnew|={d!r}（禁自行放宽）"


class TestViterbiStepEquivalence:
    def test_step_random(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        for seed in (1, 2, 3):
            delta, obs = _rand_pair(h_off, seed)
            _assert_step_equal(h_off._viterbi_step(delta, obs),
                               h_on._viterbi_step(delta, obs))

    def test_step_symmetric_ties(self, monkeypatch):
        """对称 delta（两行相同）⇒ 触发 `>` 平手不更新 与 `>=` 平手取 0 两路径。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        rng = np.random.default_rng(7)
        row = rng.normal(-5.0, 2.0, size=h_off.n_pitch)
        delta = np.stack([row, row])  # 两行相同 ⇒ cand_v/cand_u 平手
        obs = np.zeros((2, h_off.n_pitch))
        _assert_step_equal(h_off._viterbi_step(delta, obs),
                           h_on._viterbi_step(delta, obs))
        # 平手取 0 = 源有声行（陷阱②/乙）：行 0 全 0；行 1 对称 ⇒ 全 1
        _, _, bpv = h_off._viterbi_step(delta, obs)
        assert np.all(bpv[0] == 0)
        assert np.all(bpv[1] == 1)

    def test_step_shape_guard(self, monkeypatch):
        """（甲）形状校验：非 (2, n_pitch) ⇒ TypeError。"""
        h_on = _mk(monkeypatch, True)
        bad = np.zeros((3, h_on.n_pitch))
        with pytest.raises(TypeError):
            h_on._viterbi_step(bad, bad)


class TestDecodeFullEquivalence:
    @staticmethod
    def _cands_seq(n, f0=300.0):
        return [[(f0 + 0.5 * i, 0.4), (f0 + 2.0 * i, 0.2)] for i in range(n)]

    def test_decode_full_random(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        rng = np.random.default_rng(11)
        cands = []
        for _ in range(60):
            base = float(rng.uniform(100.0, 800.0))
            cands.append([(base + j, float(rng.uniform(0.1, 0.5))) for j in range(3)])
        r_off = h_off.decode(cands, fixed_lag=None)
        r_on = h_on.decode(cands, fixed_lag=None)
        # f0_hz：NaN 位置一致 + 逐位（Ⓐ）；否则 Ⓑ 档双打印
        assert np.array_equal(np.isnan(r_off.f0_hz), np.isnan(r_on.f0_hz)), "NaN 位置不一致"
        finite = np.isfinite(r_off.f0_hz)
        if not np.array_equal(r_off.f0_hz, r_on.f0_hz):
            dhz = float(np.max(np.abs(r_off.f0_hz[finite] - r_on.f0_hz[finite])))
            dcent = float(np.max(np.abs(1200.0 * np.log2(
                r_on.f0_hz[finite] / r_off.f0_hz[finite]))))
            print(f"[R6] f0 非逐位 ⇒ Ⓑ 档: max|Δf0|={dhz!r} Hz / {dcent!r} cent")
            # AT-1007 定稿档：max|Δf0| ≤ max(0.1 Hz, 1 cent @ f0)
            thr = float(np.maximum(0.1, r_off.f0_hz[finite] * (2.0 ** (1.0 / 1200.0) - 1.0)).min())
            assert dhz <= thr, f"Ⓑ 档超差: max|Δf0|={dhz!r} Hz（禁自行放宽）"
        # voiced：bool 且逐位
        assert r_off.voiced.dtype == bool and r_on.voiced.dtype == bool
        assert np.array_equal(r_off.voiced, r_on.voiced), "voiced 非逐位"
        # states：dtype 与 OFF 相同且逐位
        assert r_on.states.dtype == r_off.states.dtype, "states dtype 不齐"
        assert np.array_equal(r_off.states, r_on.states), "states 非逐位"

    def test_decode_full_const_tone(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = self._cands_seq(120)
        r_off = h_off.decode(cands, fixed_lag=None)
        r_on = h_on.decode(cands, fixed_lag=None)
        assert np.array_equal(r_off.voiced, r_on.voiced)
        assert np.array_equal(r_off.states, r_on.states)
        assert np.array_equal(r_off.f0_hz, r_on.f0_hz, equal_nan=True)


class TestFixedLagFaceUnchanged:
    """§二-3-3（强制）：fixed_lag=100 面本件不改 ⇒ ON 与 OFF 逐位相同。"""

    def test_fixed_lag_100_identical(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        rng = np.random.default_rng(23)
        cands = [[(float(rng.uniform(100.0, 800.0)), 0.4)] for _ in range(80)]
        r_off = h_off.decode(cands, fixed_lag=100)
        r_on = h_on.decode(cands, fixed_lag=100)
        assert np.array_equal(r_off.f0_hz, r_on.f0_hz, equal_nan=True), \
            "fixed_lag=100 面被改动（R7 面被吞）⇒ 停条件 3"
        assert np.array_equal(r_off.voiced, r_on.voiced)
        assert np.array_equal(r_off.states, r_on.states)


class TestBoundary:
    def test_zero_frames(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        r_off = h_off.decode([], fixed_lag=None)
        r_on = h_on.decode([], fixed_lag=None)
        assert r_on.f0_hz.dtype == r_off.f0_hz.dtype == np.float64
        assert r_on.voiced.dtype == r_off.voiced.dtype == bool
        assert r_on.states.dtype == r_off.states.dtype
        for a, b in ((r_off.f0_hz, r_on.f0_hz), (r_off.voiced, r_on.voiced),
                     (r_off.states, r_on.states)):
            assert a.shape == b.shape == (0,)

    def test_single_frame(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = [[(440.0, 0.5), (443.0, 0.2)]]
        r_off = h_off.decode(cands, fixed_lag=None)
        r_on = h_on.decode(cands, fixed_lag=None)
        assert np.array_equal(r_off.f0_hz, r_on.f0_hz, equal_nan=True)
        assert np.array_equal(r_off.voiced, r_on.voiced)
        assert np.array_equal(r_off.states, r_on.states)
        assert r_on.voiced.all()

    def test_all_empty_cands(self, monkeypatch):
        """全空候选（走清音）＋ :242 空候选守卫 ⇒ voiced 全 False、f0 全 NaN。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = [[] for _ in range(10)]
        r_off = h_off.decode(cands, fixed_lag=None)
        r_on = h_on.decode(cands, fixed_lag=None)
        assert not r_on.voiced.any()
        assert np.all(np.isnan(r_on.f0_hz))
        assert np.array_equal(r_off.states, r_on.states)
        assert not (r_on.states < h_on.n_pitch).any()  # 全清音态

    def test_unvoiced_gap(self, monkeypatch):
        """含空候选帧（清音）夹在有声段中。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = [[(220.0, 0.9)] for _ in range(10)] + [[]] * 3 \
            + [[(220.0, 0.9)] for _ in range(10)]
        r_off = h_off.decode(cands, fixed_lag=None)
        r_on = h_on.decode(cands, fixed_lag=None)
        assert np.array_equal(r_off.voiced, r_on.voiced)
        assert np.array_equal(r_off.states, r_on.states)
        assert np.array_equal(r_off.f0_hz, r_on.f0_hz, equal_nan=True)
        assert not r_on.voiced[10:13].any()
        assert np.all(np.isnan(r_on.f0_hz[10:13]))

    def test_min_tie_first(self, monkeypatch):
        """min(cands, key=…) 平手取首个：两候选距 grid 等距。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        g = float(h_off.grid_freqs[60])
        delta = 0.5  # < 半 bin（~0.71 Hz @ 123 Hz）⇒ 两候选 round 到同一 bin
        cands = [[(g - delta, 0.3), (g + delta, 0.3)]]
        r_off = h_off.decode(cands, fixed_lag=None)
        r_on = h_on.decode(cands, fixed_lag=None)
        assert np.array_equal(r_off.f0_hz, r_on.f0_hz, equal_nan=True)
        assert r_on.f0_hz[0] == pytest.approx(g - delta, abs=1e-9)  # 取首个


class TestNegativeControl:
    def test_log_self_matters(self, monkeypatch):
        """负对照：改 log_self（self_trans）⇒ new 必不等（对等断言非恒真）。"""
        h_a = _mk(monkeypatch, False, self_trans=0.99)
        h_b = _mk(monkeypatch, False, self_trans=0.95)
        delta, obs = _rand_pair(h_a, 42)
        new_a, _, _ = h_a._viterbi_step(delta, obs)
        new_b, _, _ = h_b._viterbi_step(delta, obs)
        assert not np.allclose(new_a, new_b, atol=1e-12)
        # ON 侧同样敏感（走 Rust 路径）
        h_on = _mk(monkeypatch, True, self_trans=0.95)
        new_on, _, _ = h_on._viterbi_step(delta, obs)
        assert not np.allclose(new_a, new_on, atol=1e-12)
