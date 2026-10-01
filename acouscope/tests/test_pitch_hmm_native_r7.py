# SPDX-License-Identifier: GPL-3.0-only
"""T-1062g R7：`PitchHMM.decode(fixed_lag=int)` 在线回溯＋收尾 OFF/ON 对等验证。

口径（任务书 `T-1062g` v2 §二-3）：
1. `decode(fixed_lag=100)` 对等：Ⓐ 逐位（★ states 逐位是唯一能抓错实现的判据 · N-2）
   ＋ 决定性构造（尾段双候选 · f0/states 两面同时暴露 · Δ≈702 cent）。
2. 跨路径一致性（强制 · N-7）：ON 态 `fixed_lag=100`（R7 在线）× `fixed_lag=None`（R6 全序列）
   ⇒ 稳态输入 ≤20 cent；输入给死 `_const_cands(300.0, n)`；另配 n < lag 例打「未 pop」面。
3. `fixed_lag=None` 面【不变】（强制）：ON 与 OFF 的 fixed_lag=None 逐位相同（防吞 R6 面）。
4. 边界七例：n_frames==0 / fixed_lag>=n_frames / fixed_lag=1 / fixed_lag=0（N-5）/
   单帧 / 全空候选 / 中途空候选段（后两例 n_frames > lag+1 ⇒ 打到 emit 两调用点）。
5. 负对照：改 log_cross（self_trans）⇒ states 必不等（对等断言非恒真）。

对等经 `pitch_hmm.py` 的显式分派走真实路径：OFF（不设 ACOUSCOPE_NATIVE）= Python 参考，
ON（=1）= Rust 扩展 acouscope_core.hmm_decode_lag。
"""

import numpy as np

import acouscope_core as _core  # noqa: F401  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis.pitch_hmm import PitchHMM

ENV = "ACOUSCOPE_NATIVE"


def _mk(monkeypatch, on, **kw):
    if on:
        monkeypatch.setenv(ENV, "1")
    else:
        monkeypatch.delenv(ENV, raising=False)
    return PitchHMM(**kw)


def _const_cands(f0, n, prob=0.9):
    return [[(f0, prob)] for _ in range(n)]


def cent(f, ref):
    return 1200.0 * np.log2(np.asarray(f) / ref)


def _assert_decode_equal(r_off, r_on, msg=""):
    """OFF/ON 三件逐位（Ⓐ 档 · ★ states 是唯一判据面 · N-2）。"""
    # f0_hz：NaN 位置一致 + 逐位
    assert np.array_equal(np.isnan(r_off.f0_hz), np.isnan(r_on.f0_hz)), f"{msg} NaN 位置不一致"
    assert np.array_equal(r_off.f0_hz, r_on.f0_hz, equal_nan=True), f"{msg} f0 非逐位"
    # voiced：bool 且逐位
    assert r_off.voiced.dtype == bool and r_on.voiced.dtype == bool, f"{msg} voiced dtype 不齐"
    assert np.array_equal(r_off.voiced, r_on.voiced), f"{msg} voiced 非逐位"
    # states：dtype 与 OFF 相同且逐位
    assert r_on.states.dtype == r_off.states.dtype, f"{msg} states dtype 不齐"
    assert np.array_equal(r_off.states, r_on.states), f"{msg} states 非逐位"


class TestDecodeLagEquivalence:
    def test_decode_lag_random(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        rng = np.random.default_rng(31)
        cands = []
        for _ in range(250):  # > 2·lag ⇒ 打到收尾空切片面
            base = float(rng.uniform(100.0, 800.0))
            cands.append([(base + j, float(rng.uniform(0.1, 0.5))) for j in range(3)])
        _assert_decode_equal(
            h_off.decode(cands, fixed_lag=100),
            h_on.decode(cands, fixed_lag=100),
            "random n=250",
        )

    def test_decode_lag_const_steady_tail_frozen(self, monkeypatch):
        """稳态 n=300：states 尾段唯一值读数（N-2 互证）＋ OFF/ON 逐位。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = _const_cands(300.0, 300)
        r_off = h_off.decode(cands, fixed_lag=100)
        r_on = h_on.decode(cands, fixed_lag=100)
        _assert_decode_equal(r_off, r_on, "const n=300")
        tail = np.unique(r_off.states[200:300])
        print(f"[R7] 稳态尾段 states[200:300] 唯一值 = {tail.tolist()} == states[299] = {int(r_off.states[299])}")
        assert tail.size == 1 and tail[0] == r_off.states[299]  # 收尾冻结 ⇒ 单一值

    def test_decisive_tail_dual_candidates(self, monkeypatch):
        """决定性构造（尾段双候选 · 双面可捕）：头 200 帧 200Hz ＋ 尾 100 帧 [(i,0.9),(300,0.85)]。

        lag 面收尾冻结 ⇒ f0[200:300] 全 300.0、states 尾段 = 末帧 argmax 态；
        full 面正常跟踪 ⇒ 两面同时暴露（Δ≈702 cent）。ON 必须逐位复刻此「错误」语义。
        """
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = _const_cands(200.0, 200) + [
            [(float(i), 0.9), (300.0, 0.85)] for i in range(200, 300)
        ]
        lag_off = h_off.decode(cands, fixed_lag=100)
        lag_on = h_on.decode(cands, fixed_lag=100)
        # Ⓐ 对等：OFF/ON 三件逐位（★ states 面抓「正确滑窗」错实现）
        _assert_decode_equal(lag_off, lag_on, "decisive")
        # 构造决定性：lag vs full 在 f0/states 两面均不等（断言非恒真）
        full = h_off.decode(cands, fixed_lag=None)
        assert np.all(lag_off.f0_hz[200:300] == 300.0)  # 冻结态吸到干扰候选
        d = float(np.max(np.abs(cent(lag_off.f0_hz[200:300], full.f0_hz[200:300]))))
        print(f"[R7] 决定性构造 max|Δcent|(lag vs full) = {d!r}")
        assert d > 700.0  # 幕僚实证 701.955 cent ⇒ 20 cent 网可捕
        assert not np.array_equal(lag_off.states[200:300], full.states[200:300])


class TestCrossPathConsistency:
    """§二-3-2（强制 · N-7）：ON 态 R7 在线 × R6 全序列 ⇒ 稳态 ≤20 cent。"""

    def test_on_lag_vs_full_steady_gt_2lag(self, monkeypatch):
        h_on = _mk(monkeypatch, True)
        cands = _const_cands(300.0, 300)  # n > 2·lag ⇒ 打收尾空切片面
        r_lag = h_on.decode(cands, fixed_lag=100)
        r_full = h_on.decode(cands, fixed_lag=None)
        seg = slice(120, 200)
        d = np.abs(cent(r_lag.f0_hz[seg], r_full.f0_hz[seg]))
        assert np.all(d <= 20.0), f"跨路径超差: max={float(d.max())!r} cent"

    def test_on_lag_vs_full_n_lt_lag(self, monkeypatch):
        h_on = _mk(monkeypatch, True)
        cands = _const_cands(300.0, 50)  # n < lag ⇒ 打「未 pop」面
        r_lag = h_on.decode(cands, fixed_lag=100)
        r_full = h_on.decode(cands, fixed_lag=None)
        d = np.abs(cent(r_lag.f0_hz, r_full.f0_hz))
        assert np.all(d <= 20.0), f"跨路径(n<lag)超差: max={float(d.max())!r} cent"


class TestFixedLagNoneUnchanged:
    """§二-3-3（强制）：fixed_lag=None 面本件不改 ⇒ ON 与 OFF 逐位相同（镜像 R6 守卫）。"""

    def test_none_face_identical(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        rng = np.random.default_rng(41)
        cands = [[(float(rng.uniform(100.0, 800.0)), 0.4)] for _ in range(80)]
        _assert_decode_equal(
            h_off.decode(cands, fixed_lag=None),
            h_on.decode(cands, fixed_lag=None),
            "fixed_lag=None 面被改动（R6 面被吞）⇒ 停条件 3",
        )


class TestBoundary:
    """边界七例（§二-3-4）· 全部 OFF/ON 逐位。"""

    def test_zero_frames(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        r_off = h_off.decode([], fixed_lag=100)
        r_on = h_on.decode([], fixed_lag=100)
        assert r_on.f0_hz.dtype == np.float64
        assert r_on.voiced.dtype == bool
        assert r_on.states.dtype == r_off.states.dtype
        for a, b in ((r_off.f0_hz, r_on.f0_hz), (r_off.voiced, r_on.voiced),
                     (r_off.states, r_on.states)):
            assert a.shape == b.shape == (0,)

    def test_lag_ge_n_frames(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = _const_cands(300.0, 5)
        _assert_decode_equal(
            h_off.decode(cands, fixed_lag=100),
            h_on.decode(cands, fixed_lag=100), "lag>=n")
        cands2 = _const_cands(300.0, 5)
        _assert_decode_equal(
            h_off.decode(cands2, fixed_lag=5),
            h_on.decode(cands2, fixed_lag=5), "lag==n")

    def test_lag_one(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        rng = np.random.default_rng(43)
        cands = [[(float(rng.uniform(100.0, 800.0)), 0.5)] for _ in range(60)]
        _assert_decode_equal(
            h_off.decode(cands, fixed_lag=1),
            h_on.decode(cands, fixed_lag=1), "lag=1")

    def test_lag_zero(self, monkeypatch):
        """N-5 最强判别例：环恒空 ⇒ 帧 1.. 取当帧 argmax 态；帧 0 永不发射。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        rng = np.random.default_rng(47)
        cands = [[(float(rng.uniform(100.0, 800.0)), 0.5)] for _ in range(40)]
        r_off = h_off.decode(cands, fixed_lag=0)
        r_on = h_on.decode(cands, fixed_lag=0)
        _assert_decode_equal(r_off, r_on, "lag=0")
        # 三件全真（幕僚实测）
        assert r_off.states[0] == -1
        assert np.isnan(r_off.f0_hz[0])
        assert r_off.voiced[0] == False  # noqa: E712
        # lag=0 与 lag=1 的 states[1:]/f0[1:] 逐位相同（稳态构造 · 幕僚实测口径）
        steady = _const_cands(300.0, 40)
        r0 = h_off.decode(steady, fixed_lag=0)
        r1_off = h_off.decode(steady, fixed_lag=1)
        assert np.array_equal(r0.states[1:], r1_off.states[1:])
        assert np.array_equal(r0.f0_hz[1:], r1_off.f0_hz[1:], equal_nan=True)
        # ON 侧同样成立（且 OFF/ON 逐位）
        r0_on = h_on.decode(steady, fixed_lag=0)
        r1_on = h_on.decode(steady, fixed_lag=1)
        assert np.array_equal(r0_on.states[1:], r1_on.states[1:])

    def test_single_frame(self, monkeypatch):
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = [[(440.0, 0.9)]]
        _assert_decode_equal(
            h_off.decode(cands, fixed_lag=100),
            h_on.decode(cands, fixed_lag=100), "single")

    def test_all_empty_cands(self, monkeypatch):
        """全空候选（n=30 > lag+1=6 ⇒ 打 emit 两调用点）· if cands 守卫。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = [[] for _ in range(30)]
        r_off = h_off.decode(cands, fixed_lag=5)
        r_on = h_on.decode(cands, fixed_lag=5)
        _assert_decode_equal(r_off, r_on, "all-empty")
        assert not r_on.voiced.any()
        assert np.all(np.isnan(r_on.f0_hz))

    def test_gap_segment(self, monkeypatch):
        """中途空候选段（守卫档同形 · n=45 > lag+1 ⇒ 两调用点）。"""
        h_off = _mk(monkeypatch, False)
        h_on = _mk(monkeypatch, True)
        cands = _const_cands(220.0, 20) + [[]] * 5 + _const_cands(220.0, 20)
        r_off = h_off.decode(cands, fixed_lag=5)
        r_on = h_on.decode(cands, fixed_lag=5)
        _assert_decode_equal(r_off, r_on, "gap")
        assert not r_on.voiced[20:25].any()
        assert np.all(np.isnan(r_on.f0_hz[20:25]))


class TestNegativeControl:
    def test_log_cross_matters(self, monkeypatch):
        """负对照：改 log_cross（self_trans）⇒ fixed_lag 面 states 必不等（断言非恒真）。"""
        h_a = _mk(monkeypatch, False, self_trans=0.99)
        h_b = _mk(monkeypatch, False, self_trans=0.5)
        rng = np.random.default_rng(53)
        cands = []
        for _ in range(120):
            base = float(rng.uniform(100.0, 800.0))
            cands.append([(base + j, float(rng.uniform(0.1, 0.5))) for j in range(3)])
        sa = h_a.decode(cands, fixed_lag=100).states
        sb = h_b.decode(cands, fixed_lag=100).states
        assert not np.array_equal(sa, sb), "states 对 log_cross 不敏感 ⇒ 对等断言恒真"
