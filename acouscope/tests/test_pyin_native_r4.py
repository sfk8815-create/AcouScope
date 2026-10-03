# SPDX-License-Identifier: GPL-3.0-only
"""T-1062d R4：`pyin_candidates` OFF/ON 对等验证（本件的证伪器）。

口径（需求说明 `T-1062d` v2 §二-3）：
- Ⓐ 优先逐位档：`times` 逐位 `np.array_equal` · `voiced` 逐位 · `cand_lists` 逐元素逐位
  （长度 + 每个 (f0, prob) 两列）。
- Ⓑ 若实测非逐位：先归因（预期继承源 = `difference_function`；R3 已实测 `pyin_frame`
  非逐位系继承该源）⇒ 允许 `max|Δf0| ≤ max(0.1 Hz, 1 cent @ f0)` ／ `max|Δprob| ≤ 1e-3`
  ／ voiced 一致率 ≥ 99%；判据输出**同时打印 Hz 与 cent 两值**（禁自行放宽）。
- ON 态「帧间 = 帧内」一致性（强制 · N-2 升级）：抽三帧（首/中/末）逐位断言
  `cand_lists[i] == pyin_frame(sig[i*hop : i*hop+frame_size], sr, fmin, fmax, 0.3, 2.0)[0]`
  （显式非默认 beta_mean=0.3、beta_a=2.0）⇒「必须复用 Rust pyin_frame」的判据化。
- 等价档至少各含一例非默认 hop_length（256 与 512）⇒ 覆盖分帧层。
- 负对照（强制）：证明对等断言非恒真。
- 边界例：退化（len<frame_size ⇒ 空 ndarray + 空 list + 空 ndarray）· 恰 1 帧 · 静音整段。
- 默认 OFF 回归：不设环境变量时形状/类型与原实现一致。

对等经 `pyin.py` 的显式分派走真实路径：OFF（不设 `ACOUSCOPE_NATIVE`）= Python 参考，
ON（=1）= Rust 扩展 `acouscope_core.pyin_candidates`。
"""

import math

import numpy as np
import pytest

import acouscope_core as _core  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis import pyin

ENV = "ACOUSCOPE_NATIVE"
CENT_RATIO = 2.0 ** (1.0 / 1200.0) - 1.0
_RECORDS = []


def _sine(freq, dur=1.0, sr=44100.0, amp=0.5):
    t = np.arange(int(sr * dur)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def _cases():
    """(name, signal, kwargs) —— 覆盖 hop 256/512、非默认参数、静音、恰 1 帧。"""
    return [
        ("sine440_hop256", _sine(440.0, 1.0), {"hop_length": 256}),
        ("sine300_hop512", _sine(300.0, 1.0), {"hop_length": 512}),
        ("sine174_hop256_beta", _sine(174.9, 0.6), {"hop_length": 256, "beta_mean": 0.3}),
        ("band_100_1000_hop512", _sine(440.0, 0.6), {"hop_length": 512, "fmin": 100.0, "fmax": 1000.0}),
        ("exactly_one_frame", _sine(440.0, 2048 / 44100.0), {"hop_length": 256}),
        ("silence", np.zeros(int(44100 * 0.5)), {"hop_length": 512}),
    ]


CASES = _cases()


def _run(monkeypatch, signal, kwargs):
    monkeypatch.delenv(ENV, raising=False)
    off = pyin.pyin_candidates(signal, 44100.0, **kwargs)
    monkeypatch.setenv(ENV, "1")
    on = pyin.pyin_candidates(signal, 44100.0, **kwargs)
    monkeypatch.delenv(ENV, raising=False)
    return off, on


def _cand_metrics(ref_lists, got_lists):
    """跨帧三量（Ⓑ 档配对：f0 贪心匹配，容差 = max(0.1Hz, 1cent@f0)）。

    归因（实测）：OFF/ON 候选数可不等 —— Python 保留 prob≈1e-29 量级的次正规候选，
    Rust 侧 `probs` 浮点舍入使其越过 `p <= 0.0` 过滤被丢弃。该差异**继承自 R3 的
    `pyin_frame`（根源 `difference_function`）**，非 R4 帧间循环引入（单帧直接对比已
    复现）。配对后：匹配候选漂移入三量；未匹配候选 prob 上界入 `max_dropped_prob`。
    """
    m = {"n_frames_ref": len(ref_lists), "n_frames_got": len(got_lists),
         "len_match": len(ref_lists) == len(got_lists), "bit_exact": True,
         "max_df0_hz": 0.0, "max_df0_cent": 0.0, "max_df0_ratio": 0.0, "max_dprob": 0.0,
         "max_dropped_prob": 0.0}
    if not m["len_match"]:
        m["bit_exact"] = False
    for cr, cg in zip(ref_lists, got_lists):
        if cr != cg:
            m["bit_exact"] = False
        used = set()
        for fr, pr in cr:
            tol = max(0.1, fr * CENT_RATIO)
            best = None
            for j, (fg, _pg) in enumerate(cg):
                if j in used:
                    continue
                if abs(fg - fr) <= tol:
                    best = j
                    break
            if best is None:
                m["max_dropped_prob"] = max(m["max_dropped_prob"], pr)
                continue
            used.add(best)
            fg, pg = cg[best]
            dh = abs(fg - fr)
            dc = abs(1200.0 * math.log2(fg / fr)) if (fr > 0.0 and fg > 0.0) else float("inf")
            m["max_df0_hz"] = max(m["max_df0_hz"], dh)
            m["max_df0_cent"] = max(m["max_df0_cent"], dc)
            m["max_df0_ratio"] = max(m["max_df0_ratio"], dh / tol)
            m["max_dprob"] = max(m["max_dprob"], abs(pg - pr))
        for j, (_fg, pg) in enumerate(cg):
            if j not in used:
                m["max_dropped_prob"] = max(m["max_dropped_prob"], pg)
    return m


def _check(name, ref, got):
    """分档判定：Ⓐ 优先逐位；非逐位 ⇒ 归因 difference_function 后按 Ⓑ 档断言。"""
    t_ref, c_ref, v_ref = ref
    t_got, c_got, v_got = got
    times_bit = np.array_equal(t_ref, t_got)
    voiced_bit = np.array_equal(v_ref, v_got)
    cm = _cand_metrics(c_ref, c_got)
    m = {"name": name, "times_bit": times_bit, "voiced_bit": voiced_bit, **cm,
         "voiced_max_d": float(np.max(np.abs(v_ref - v_got))) if v_ref.size else 0.0,
         "voiced_agree_rate": 1.0}
    if v_ref.size:
        agree = int(np.sum(np.abs(v_ref - v_got) <= 1e-3))
        m["voiced_agree_rate"] = agree / v_ref.size
    _RECORDS.append(m)
    print(f"[R4 {name}] times_bit={times_bit} voiced_bit={voiced_bit} "
          f"cands_bit={cm['bit_exact']} max|Δf0|={cm['max_df0_hz']:.3e} Hz / "
          f"{cm['max_df0_cent']:.3e} cent (worst占比={cm['max_df0_ratio']:.3f}) "
          f"max|Δprob|={cm['max_dprob']:.3e} 丢弃候选prob上界={cm['max_dropped_prob']:.3e} "
          f"voiced一致率={m['voiced_agree_rate']:.4f}")
    assert times_bit, f"{name}: times 非逐位（分帧层偏离）⇒ 停并报"
    assert cm["len_match"], f"{name}: 帧数不等 ⇒ 停并报"
    # Ⓑ 档断言（归因：继承 difference_function 非逐位，R3 已实测；Ⓐ 逐位时自然满足）
    assert cm["max_df0_ratio"] <= 1.0, f"{name}: max|Δf0| 超 Ⓑ 档 ⇒ 停并报（禁自行放宽）"
    assert cm["max_dprob"] <= 1e-3, f"{name}: max|Δprob| > 1e-3 ⇒ 停并报"
    # 丢弃候选（prob≈1e-29 次正规，继承 R3）：prob 上界须 ≪ 1e-3 档
    assert cm["max_dropped_prob"] <= 1e-3, f"{name}: 丢弃候选 prob 超档 ⇒ 停并报"
    assert m["voiced_agree_rate"] >= 0.99, f"{name}: voiced 一致率 < 99% ⇒ 停并报"
    return m


class TestEquivalence:
    def test_all_cases_equivalent(self, monkeypatch):
        """全部用例 OFF/ON 对等（Ⓐ 优先逐位；非逐位归因 difference_function 后落 Ⓑ 档）。"""
        for name, sig, kwargs in CASES:
            ref, got = _run(monkeypatch, sig, kwargs)
            _check(name, ref, got)

    def test_hop256_and_512_covered(self, monkeypatch):
        """非默认 hop 两例（256/512）各至少一例已入等价档（分帧层覆盖 · N-2-③）。"""
        hops = {k.get("hop_length") for _, _, k in CASES}
        assert 256 in hops and 512 in hops
        sig = _sine(300.0, 0.8)
        for hop in (256, 512):
            ref, got = _run(monkeypatch, sig, {"hop_length": hop})
            n_frames = 1 + (sig.size - 2048) // hop
            assert len(ref[1]) == n_frames and len(got[1]) == n_frames
            _check(f"hop{hop}", ref, got)


class TestBatchMatchesFrame:
    """ON 态「帧间 = 帧内」一致性（强制 · 三帧 · 显式非默认参数 · N-2）。"""

    def test_three_frames_bitwise_on(self, monkeypatch):
        monkeypatch.setenv(ENV, "1")
        sig = _sine(300.0, 1.0)
        sr, fmin, fmax, beta_mean, beta_a, hop = 44100.0, 60.0, 1800.0, 0.3, 2.0, 512
        _, cands, _ = pyin.pyin_candidates(sig, sr, 2048, hop, fmin, fmax, beta_mean)
        n_frames = len(cands)
        for i in (0, n_frames // 2, n_frames - 1):
            frame = np.ascontiguousarray(sig[i * hop: i * hop + 2048], dtype=np.float64)
            c1, _v1 = pyin.pyin_frame(frame, sr, fmin, fmax, beta_mean, beta_a)
            assert cands[i] == c1, f"帧 {i}（首/中/末）批量 ≠ 单帧 ⇒ 疑帧内逻辑被重写"
        monkeypatch.delenv(ENV, raising=False)
        print(f"[R4 batch=frame] 三帧(0/{n_frames // 2}/{n_frames - 1}) 逐位一致 ✓")


class TestNegativeControl:
    def test_shifted_hop_differs(self, monkeypatch):
        """故意偏移 hop_length ⇒ 结果必不等（对等断言非恒真）。"""
        sig = _sine(440.0, 1.0)
        monkeypatch.delenv(ENV, raising=False)
        a = pyin.pyin_candidates(sig, 44100.0, 2048, 256)
        b = pyin.pyin_candidates(sig, 44100.0, 2048, 512)
        assert not np.array_equal(a[0], b[0]), "hop 偏移后 times 仍相同 ⇒ 断言恒真"

    def test_metric_flags_mismatch(self):
        """度量有判别力：偏移超出 Ⓑ 档容差 ⇒ bit_exact=False 且丢弃 prob 超档。"""
        m = _cand_metrics([[(440.0, 0.9)]], [[(445.0, 0.5)]])
        assert m["bit_exact"] is False
        # 445Hz 超出 440Hz 的容差 max(0.1, 1cent) ⇒ 不配对 ⇒ 记入丢弃侧
        assert m["max_dropped_prob"] == pytest.approx(0.9)

    def test_dispatch_on_really_reaches_rust(self, monkeypatch):
        called = {}

        def _boom(*a, **k):
            called["hit"] = True
            return (np.array([1.0]), [[(123.0, 0.5)]], np.array([0.5]))

        monkeypatch.setattr(_core, "pyin_candidates", _boom)
        monkeypatch.setenv(ENV, "1")
        out = pyin.pyin_candidates(_sine(440.0, 0.5), 44100.0)
        monkeypatch.delenv(ENV, raising=False)
        assert called.get("hit"), "ON 分派未走 acouscope_core.pyin_candidates"
        assert out[1] == [[(123.0, 0.5)]]


class TestEdgeCases:
    def test_degenerate_short_signal_types(self, monkeypatch):
        """退化 len<frame_size ⇒ 三件逐字：空 ndarray + 空 list + 空 ndarray（两侧同形）。"""
        for mode in ("off", "on"):
            monkeypatch.delenv(ENV, raising=False) if mode == "off" else monkeypatch.setenv(ENV, "1")
            t, c, v = pyin.pyin_candidates(np.zeros(1000), 44100.0, 2048, 256)
            assert isinstance(t, np.ndarray) and t.size == 0 and t.dtype == np.float64
            assert isinstance(c, list) and c == []
            assert isinstance(v, np.ndarray) and v.size == 0 and v.dtype == np.float64
        monkeypatch.delenv(ENV, raising=False)

    def test_exactly_one_frame(self, monkeypatch):
        ref, got = _run(monkeypatch, np.zeros(2048), {})
        assert len(ref[1]) == 1 and len(got[1]) == 1
        _check("one_frame", ref, got)

    def test_silence_voiced_near_zero(self, monkeypatch):
        ref, got = _run(monkeypatch, np.zeros(int(44100 * 0.5)), {"hop_length": 512})
        assert float(np.max(ref[2])) < 0.2 and float(np.max(got[2])) < 0.2
        _check("silence_voiced", ref, got)


class TestDefaultOffRegression:
    def test_off_shapes_types(self, monkeypatch):
        monkeypatch.delenv(ENV, raising=False)
        t, c, v = pyin.pyin_candidates(_sine(440.0, 0.6), 44100.0, 2048, 256)
        assert isinstance(t, np.ndarray) and t.dtype == np.float64
        assert isinstance(c, list) and all(isinstance(x, list) for x in c)
        assert isinstance(v, np.ndarray) and v.dtype == np.float64
        assert t.shape == v.shape == (len(c),)

    def test_off_never_touches_core(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("native called while OFF")

        monkeypatch.setattr(_core, "pyin_candidates", _boom)
        monkeypatch.delenv(ENV, raising=False)
        pyin.pyin_candidates(_sine(440.0, 0.6), 44100.0, 2048, 256)


class TestSummary:
    def test_print_aggregate(self):
        assert _RECORDS, "无记录 ⇒ 前置用例未执行"
        n_bit = sum(1 for m in _RECORDS if m["times_bit"] and m["voiced_bit"] and m["bit_exact"])
        worst_hz = max(m["max_df0_hz"] for m in _RECORDS)
        worst_cent = max(m["max_df0_cent"] for m in _RECORDS)
        worst_ratio = max(m["max_df0_ratio"] for m in _RECORDS)
        worst_prob = max(m["max_dprob"] for m in _RECORDS)
        worst_voiced = min(m["voiced_agree_rate"] for m in _RECORDS)
        print(f"[R4 SUMMARY] cases={len(_RECORDS)} all_bit_exact={n_bit}/{len(_RECORDS)} "
              f"worst max|Δf0|={worst_hz:.3e} Hz / {worst_cent:.3e} cent (worst占比={worst_ratio:.3f}) "
              f"worst max|Δprob|={worst_prob:.3e} worst voiced一致率={worst_voiced:.4f}")
        assert worst_ratio <= 1.0 and worst_prob <= 1e-3 and worst_voiced >= 0.99
