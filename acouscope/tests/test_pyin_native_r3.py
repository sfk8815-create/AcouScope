# SPDX-License-Identifier: GPL-3.0-only
"""T-1062c R3：`pyin_frame` OFF/ON 对等验证（本件的证伪器）。

口径（任务书 `T-1062c` v2 §二-3）：
- Ⓐ 优先逐位档 `np.array_equal`（candidates 的 f0 列 / prob 列 ＋ voiced_prob）。
- Ⓑ 若实测非逐位：先归因（预期继承源 = `difference_function`，R1 放宽档 max|Δ| ≤ 1e-9）
  ⇒ 允许 `max|Δf0| ≤ max(0.1 Hz, 1 cent @ f0)`（`AT1007_threshold_review.md:135-137` 定稿）
  ／ `max|Δprob| ≤ 1e-3` ／ voiced 一致率 ≥ 99%；且判据输出**同时打印 Hz 与 cent 两值**
  （`review:142` 附录约束）。
- 刀口例（强制）：`AT-1007` 翻转区间两侧 `1997.933657333` / `1997.933657348` Hz
  ＋ `3000 Hz` 幽灵回归例（改后须仍**不**误检为 `1500 Hz`）。
- 负对照（强制）：证明对等断言**非恒真**。
- 边界例：帧长退化（`tau_max <= tau_min + 2` → `([], 0.0)`）· 清音帧 · 常规 fmin/fmax。
- 默认 OFF 回归：不设环境变量时形状/类型与原实现一致。

对等经 `pyin.py` 的显式分派走真实路径：OFF（不设 `ACOUSCOPE_NATIVE`）= Python 参考，
ON（=1）= Rust 扩展 `acouscope_core.pyin_frame`。
"""

import math

import numpy as np
import pytest

import acouscope_core as _core  # 未装 Rust 扩展 ⇒ 收集期即报错（禁 skipped）
from acouscope.analysis import pyin

ENV = "ACOUSCOPE_NATIVE"

# 1 cent 在 f0 处的 Hz 当量：tol = max(0.1 Hz, f0 * CENT_RATIO)
CENT_RATIO = 2.0 ** (1.0 / 1200.0) - 1.0

# AT-1007 刀口翻转区间两侧（AT1007_threshold_review.md:46 逐字）
KNIFE_LO = 1997.933657333
KNIFE_HI = 1997.933657348

_RECORDS = []


def _sine(freq, dur=0.5, sr=44100.0, amp=0.5):
    t = np.arange(int(sr * dur)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def _frames():
    """(name, frame, sr, kwargs) —— 覆盖常规 / 刀口 / 幽灵 / 清音 / 短帧。"""
    rng = np.random.default_rng(20260919)
    return [
        ("pure440", _sine(440.0), 44100.0, {}),
        ("pure174.9", _sine(174.9), 44100.0, {}),
        ("low82.4", _sine(82.4), 44100.0, {}),
        ("short_frame_440", _sine(440.0, dur=0.05), 44100.0, {}),
        ("band_100_1000", _sine(440.0), 44100.0, {"fmin": 100.0, "fmax": 1000.0}),
        ("beta_custom", _sine(300.0), 44100.0, {"beta_mean": 0.3, "beta_a": 1.5}),
        ("knife_lo", _sine(KNIFE_LO), 44100.0, {}),
        ("knife_hi", _sine(KNIFE_HI), 44100.0, {}),
        ("ghost3000", _sine(3000.0), 44100.0, {}),
        ("silence", np.zeros(2048), 44100.0, {}),
        ("noise", rng.normal(0.0, 0.2, 4096), 44100.0, {}),
    ]


CASES = _frames()


def _run(monkeypatch, frame, sr, kwargs):
    monkeypatch.delenv(ENV, raising=False)
    off = pyin.pyin_frame(frame, sr, **kwargs)
    monkeypatch.setenv(ENV, "1")
    on = pyin.pyin_frame(frame, sr, **kwargs)
    monkeypatch.delenv(ENV, raising=False)
    return off, on


def _metrics(ref, got):
    """三量：max|Δf0|（Hz 与 cent 双值）/ max|Δprob| / voiced 一致率（+ 是否逐位）。"""
    cr, vr = ref
    cg, vg = got
    m = {
        "n_off": len(cr),
        "n_on": len(cg),
        "len_match": len(cr) == len(cg),
        "bit_exact": bool(cr == cg and vr == vg),
        "voiced_off": float(vr),
        "voiced_on": float(vg),
        "voiced_d": abs(float(vr) - float(vg)),
        "max_df0_hz": 0.0,
        "max_df0_cent": 0.0,
        "max_df0_ratio": 0.0,
        "max_dprob": 0.0,
    }
    if not m["len_match"]:
        m["max_df0_ratio"] = float("inf")
        return m
    for (fr, pr), (fg, pg) in zip(cr, cg):
        dh = abs(fg - fr)
        tol = max(0.1, fr * CENT_RATIO)
        dc = abs(1200.0 * math.log2(fg / fr)) if (fr > 0.0 and fg > 0.0) else float("inf")
        m["max_df0_hz"] = max(m["max_df0_hz"], dh)
        m["max_df0_cent"] = max(m["max_df0_cent"], dc)
        m["max_df0_ratio"] = max(m["max_df0_ratio"], dh / tol)
        m["max_dprob"] = max(m["max_dprob"], abs(pg - pr))
    return m


def _report(name, m):
    print(
        f"[R3 {name}] n_off={m['n_off']} n_on={m['n_on']} bit_exact={m['bit_exact']} "
        f"max|Δf0|={m['max_df0_hz']:.3e} Hz / {m['max_df0_cent']:.3e} cent "
        f"(tol=max(0.1Hz,1cent@f0), worst占比={m['max_df0_ratio']:.3f}) "
        f"max|Δprob|={m['max_dprob']:.3e} Δvoiced={m['voiced_d']:.3e}"
    )


def _check(name, ref, got):
    m = _metrics(ref, got)
    _RECORDS.append((name, m))
    _report(name, m)
    assert m["len_match"], f"{name}: 候选数不等 ⇒ 停并报"
    assert m["max_df0_ratio"] <= 1.0, f"{name}: max|Δf0| 超出 Ⓑ 档 ⇒ 停并报（禁自行放宽）"
    assert m["max_dprob"] <= 1e-3, f"{name}: max|Δprob| > 1e-3 ⇒ 停并报"
    assert m["voiced_d"] <= 1e-3, f"{name}: voiced 不一致 ⇒ 停并报"
    return m


class TestEquivalence:
    def test_all_cases_equivalent(self, monkeypatch):
        """全部用例 OFF/ON 对等（Ⓐ 优先逐位；非逐位须落 Ⓑ 档）。"""
        for name, frame, sr, kwargs in CASES:
            ref, got = _run(monkeypatch, frame, sr, kwargs)
            _check(name, ref, got)

    def test_candidate_structure_matches(self, monkeypatch):
        """候选结构：类型 list[tuple[float, float]]、prob 降序、f0 在 [fmin, fmax]（两侧同形同档）。"""
        ref, got = _run(monkeypatch, _sine(440.0), 44100.0, {})
        for cands in (ref[0], got[0]):
            assert isinstance(cands, list) and cands
            assert all(isinstance(t, tuple) and len(t) == 2 for t in cands)
            assert all(type(f) is float and type(p) is float for f, p in cands)
            probs = [p for _, p in cands]
            assert probs == sorted(probs, reverse=True)
            assert all(40.0 <= f <= 2000.0 for f, _ in cands)
        _check("candidate_structure", ref, got)

    def test_knife_edge_both_sides_equivalent(self, monkeypatch):
        """AT-1007 刀口：翻转区间两侧（1.49e-08 Hz 宽）必须同时对齐。"""
        outs = {}
        for name in ("knife_lo", "knife_hi"):
            frame, sr, kwargs = [(n, f, s, k) for n, f, s, k in CASES if n == name][0][1:]
            ref, got = _run(monkeypatch, frame, sr, kwargs)
            _check(name, ref, got)
            outs[name] = (ref, got)
        print(f"[R3 knife] OFF(lo)==OFF(hi) = {outs['knife_lo'][0] == outs['knife_hi'][0]}")

    def test_ghost_3000_not_detected_as_1500(self, monkeypatch):
        """3000 Hz 幽灵回归例：改后须仍不误检为 1500 Hz（AT-07-3）。

        正对照：1500 Hz 纯音**确实**会被检出 1500 Hz 候选 ⇒ 本断言具判别力（非恒真）。
        """
        pos, _ = _run(monkeypatch, _sine(1500.0), 44100.0, {})
        hit_pos = [f for f, _ in pos[0] if abs(1200.0 * math.log2(f / 1500.0)) <= 50.0]
        print(f"[R3 ghost3000 正对照] 1500Hz 输入 ⇒ 1500Hz±50cent 命中={len(hit_pos)}")
        assert hit_pos, "1500Hz 输入未检出 1500Hz ⇒ 幽灵例无判别力"
        ref, got = _run(monkeypatch, _sine(3000.0), 44100.0, {})
        for tag, (cands, _vp) in (("OFF", ref), ("ON", got)):
            bad = [f for f, _ in cands if abs(1200.0 * math.log2(f / 1500.0)) <= 50.0]
            print(f"[R3 ghost3000 {tag}] n={len(cands)} 1500Hz±50cent 命中={len(bad)}")
            assert not bad, f"{tag}: 3000Hz 被误检为半频 1500Hz 幽灵"


class TestNegativeControl:
    """负对照：证明上面的对等断言具判别力（非恒真）。"""

    def test_different_input_differs(self, monkeypatch):
        ref, _ = _run(monkeypatch, _sine(440.0), 44100.0, {})
        _, got = _run(monkeypatch, _sine(880.0), 44100.0, {})
        assert ref[0] != got[0], "不同输入结果相同 ⇒ 对等断言无判别力"

    def test_metric_flags_mismatch(self):
        """度量本身有判别力：故意偏移 ⇒ bit_exact=False 且超档。"""
        m = _metrics(([(440.0, 0.9)], 0.9), ([(445.0, 0.5)], 0.5))
        assert m["bit_exact"] is False
        assert m["max_df0_hz"] == pytest.approx(5.0)
        assert m["max_df0_ratio"] > 1.0
        assert m["max_dprob"] == pytest.approx(0.4)

    def test_metric_flags_length_mismatch(self):
        m = _metrics(([(440.0, 0.9)], 0.9), ([], 0.0))
        assert m["len_match"] is False and m["max_df0_ratio"] == float("inf")

    def test_dispatch_on_really_reaches_rust(self, monkeypatch):
        """ON 时确实走 Rust：打补丁 `_core.pyin_frame`，分派必须命中补丁。"""
        called = {}

        def _boom(*a, **k):
            called["hit"] = True
            return ([(123.0, 0.5)], 0.5)

        monkeypatch.setattr(_core, "pyin_frame", _boom)
        monkeypatch.setenv(ENV, "1")
        out = pyin.pyin_frame(_sine(440.0), 44100.0)
        monkeypatch.delenv(ENV, raising=False)
        assert called.get("hit"), "ON 分派未走 acouscope_core.pyin_frame"
        assert out == ([(123.0, 0.5)], 0.5)


class TestEdgeCases:
    def test_degenerate_short_frame(self, monkeypatch):
        """帧长退化：tau_max <= tau_min + 2 ⇒ ([], 0.0)（两侧同形）。"""
        for frame in (np.zeros(8), np.zeros(16)):
            ref, got = _run(monkeypatch, frame, 44100.0, {})
            assert ref == ([], 0.0) and got == ([], 0.0)

    def test_degenerate_fmin_equals_fmax(self, monkeypatch):
        """fmin=fmax=2000 ⇒ tau_min=tau_max ⇒ 退化 ([], 0.0)。"""
        ref, got = _run(monkeypatch, _sine(440.0), 44100.0, {"fmin": 2000.0, "fmax": 2000.0})
        assert ref == ([], 0.0) and got == ([], 0.0)

    def test_unvoiced_frame_low_voiced_prob(self, monkeypatch):
        """清音帧（静音）⇒ voiced_prob 近 0，两侧同档。"""
        ref, got = _run(monkeypatch, np.zeros(2048), 44100.0, {})
        print(f"[R3 unvoiced] voiced_off={ref[1]:.6e} voiced_on={got[1]:.6e}")
        assert ref[0] == [] and got[0] == []
        assert ref[1] < 0.2 and got[1] < 0.2
        assert abs(ref[1] - got[1]) <= 1e-3

    def test_normal_fmin_fmax_range(self, monkeypatch):
        """常规 fmin/fmax：候选 f0 全部落在量程内且两侧一致。"""
        ref, got = _run(monkeypatch, _sine(440.0), 44100.0, {"fmin": 40.0, "fmax": 2000.0})
        assert ref[0] and all(40.0 <= f <= 2000.0 for f, _ in ref[0])
        _check("normal_range", ref, got)

    def test_sr_48000(self, monkeypatch):
        """非默认采样率 48000：分派参数直通、两侧一致。"""
        ref, got = _run(monkeypatch, _sine(440.0, sr=48000.0), 48000.0, {})
        _check("sr48000", ref, got)


class TestDefaultOffRegression:
    """默认 OFF（不设环境变量）⇒ 走原 Python 分支，行为零变化。"""

    def test_off_shapes_types(self, monkeypatch):
        monkeypatch.delenv(ENV, raising=False)
        cands, vp = pyin.pyin_frame(_sine(440.0), 44100.0)
        assert isinstance(cands, list) and cands
        assert all(isinstance(t, tuple) and len(t) == 2 for t in cands)
        assert type(vp) is float
        assert isinstance(pyin.pyin_frame(np.zeros(8), 44100.0), tuple)

    def test_off_never_touches_core(self, monkeypatch):
        """OFF 时打补丁 `_core.pyin_frame` 不得被触发（分派短路于 is_native_enabled）。"""

        def _boom(*a, **k):
            raise AssertionError("native called while OFF")

        monkeypatch.setattr(_core, "pyin_frame", _boom)
        monkeypatch.delenv(ENV, raising=False)
        pyin.pyin_frame(_sine(440.0), 44100.0)


class TestSummary:
    def test_print_aggregate(self):
        """汇总：全部用例的逐位情况与三量上确界（供报告逐字引用）。"""
        assert _RECORDS, "无记录 ⇒ 前置用例未执行"
        bit_all = all(m["bit_exact"] for _, m in _RECORDS)
        worst_hz = max(m["max_df0_hz"] for _, m in _RECORDS)
        worst_cent = max(m["max_df0_cent"] for _, m in _RECORDS)
        worst_ratio = max(m["max_df0_ratio"] for _, m in _RECORDS)
        worst_prob = max(m["max_dprob"] for _, m in _RECORDS)
        worst_voiced = max(m["voiced_d"] for _, m in _RECORDS)
        n_bitexact = sum(1 for _, m in _RECORDS if m["bit_exact"])
        print(
            f"[R3 SUMMARY] cases={len(_RECORDS)} bit_exact={n_bitexact}/{len(_RECORDS)} "
            f"all_bit_exact={bit_all} "
            f"worst max|Δf0|={worst_hz:.3e} Hz / {worst_cent:.3e} cent "
            f"(worst占比={worst_ratio:.3f}) "
            f"worst max|Δprob|={worst_prob:.3e} worst Δvoiced={worst_voiced:.3e}"
        )
        assert worst_ratio <= 1.0 and worst_prob <= 1e-3 and worst_voiced <= 1e-3
