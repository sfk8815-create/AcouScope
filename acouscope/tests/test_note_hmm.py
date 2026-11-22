# SPDX-License-Identifier: GPL-3.0-only
"""音符分段三态 HMM 单元测试（T-803）。NOTE_HMM_TEST_V1

覆盖：① 双稳态音分段 ② 单稳音 ③ NaN/零 f0 安全 ④ min_dur 丢弃
⑤ NOTE_HMM_PARAMS 参数逐字 ⑥ build_pitch_grid segmenter 双路径
⑦ 相邻异音高无缝切换必分 2 段（T-803b 架构师审计增补）
⑨ 未知 segmenter 回落 simple ⑩ conf 透传。
"""

import numpy as np
import pytest

pytest.importorskip("numpy")

from acouscope.analysis.note_hmm import NOTE_HMM_PARAMS, NoteHMM  # noqa: E402
from acouscope.analysis.pitch_grid import (  # noqa: E402
    SNAP_OFF,
    build_pitch_grid,
)

DT = 0.01


def _dual_note_contour():
    """220Hz 0.5s + 0.15s 静音 + 330Hz 0.5s。"""
    t1 = np.arange(0.0, 0.5, DT)
    tg = np.arange(0.5, 0.65, DT)
    t2 = np.arange(0.65, 1.15, DT)
    times = np.concatenate([t1, tg, t2])
    f0 = np.concatenate(
        [np.full(t1.size, 220.0), np.full(tg.size, np.nan), np.full(t2.size, 330.0)]
    )
    return times, f0


def test_dual_note_segments():
    """① 双稳态音 → ≥2 段，各段 f0 中位数接近真值。"""
    times, f0 = _dual_note_contour()
    segs = NoteHMM().segment(times, f0)
    assert len(segs) >= 2
    f0s = [s.f0_hz for s in segs]
    assert min(abs(f - 220.0) for f in f0s) < 2.0
    assert min(abs(f - 330.0) for f in f0s) < 2.0
    # 段边界：第一段起于 0，第二段起于 0.65 邻域
    assert segs[0].start_s == pytest.approx(0.0, abs=DT)
    assert abs(segs[1].start_s - 0.65) < 0.05
    assert segs[0].end_s < segs[1].start_s


def test_single_note_one_segment():
    """② 单稳音 → 恰 1 段，f0 = 段内原始中位数。"""
    t = np.arange(0.0, 0.5, DT)
    segs = NoteHMM().segment(t, np.full(t.size, 440.0))
    assert len(segs) == 1
    assert segs[0].f0_hz == pytest.approx(440.0, abs=1e-6)
    assert segs[0].start_s == pytest.approx(0.0, abs=DT)
    assert segs[0].end_s == pytest.approx(0.49, abs=DT)
    assert segs[0].midi == 69  # 参考字段


def test_nan_zero_f0_safe():
    """③ NaN/零 f0 帧安全：首尾 40 帧 NaN/0，中段 220Hz 出 1 段，不抛异常。"""
    t = np.arange(0.0, 0.5, DT)
    f0 = np.full(t.size, 220.0)
    f0[:40] = np.nan
    f0[80:] = 0.0
    segs = NoteHMM().segment(t, f0)
    assert len(segs) == 1
    assert segs[0].f0_hz == pytest.approx(220.0, abs=1e-6)
    assert segs[0].start_s >= 0.40 - DT
    assert segs[0].end_s <= 0.79 + DT


def test_min_dur_drop():
    """④ min_dur 丢弃：0.09s 短段在 min_dur_s=0.5 下被丢弃。"""
    t = np.arange(0.0, 0.5, DT)
    f0 = np.full(t.size, 220.0)
    f0[:40] = np.nan
    f0[80:] = 0.0
    assert NoteHMM().segment(t, f0)  # 默认 min_dur=0.08 保留
    assert NoteHMM().segment(t, f0, None, min_dur_s=0.5) == []


def test_params_verbatim():
    """⑤ NOTE_HMM_PARAMS 七参数（PITCH_analysis §1.5）逐字断言。"""
    assert NOTE_HMM_PARAMS["p_stable_selftrans"] == 0.99
    assert NOTE_HMM_PARAMS["p_silent_selftrans"] == 0.9999
    assert NOTE_HMM_PARAMS["max_jump_semitones"] == 13
    assert NOTE_HMM_PARAMS["min_semitone_distance"] == 0.5
    assert NOTE_HMM_PARAMS["sigma_yin_pitch_stable"] == 0.8
    assert NOTE_HMM_PARAMS["yin_trust"] == 0.1
    assert NOTE_HMM_PARAMS["prior_pitched_prob"] == 0.7
    assert NOTE_HMM_PARAMS["min_pitch_midi"] == 35
    assert NOTE_HMM_PARAMS["bins_per_semitone"] == 3


def test_build_pitch_grid_hmm_and_simple():
    """⑥ segmenter="hmm" 与 "simple" 经 build_pitch_grid 均可出段，
    且原始 f0 不被网格改写（各段 f0_hz 属真值邻域）。"""
    times, f0 = _dual_note_contour()
    g_simple = build_pitch_grid(times, f0, None, SNAP_OFF, segmenter="simple")
    g_hmm = build_pitch_grid(times, f0, None, SNAP_OFF, segmenter="hmm")
    for g, truth in ((g_simple, (220.0, 330.0)), (g_hmm, (220.0, 330.0))):
        assert len(g.notes) >= 2
        f0s = [n.f0_hz for n in g.notes]
        assert min(abs(f - 220.0) for f in f0s) < 2.0
        assert min(abs(f - 330.0) for f in f0s) < 2.0
    # 反量化铁律：SNAP_OFF 下 snapped == 原始 f0 中位数
    assert all(n.snapped_f0_hz == n.f0_hz for n in g_hmm.notes)


def test_seamless_adjacent_pitch_change_splits():
    """⑦ 相邻异音高无缝切换（T-803b 审计增补）：220Hz 0.3s 直连 330Hz 0.3s，
    无静音无间隙 → 必须 2 段，各段 f0 分别接近 220/330（禁混合中位数一段）。"""
    t1 = np.arange(0.0, 0.3, DT)
    t2 = np.arange(0.3, 0.6, DT)
    times = np.concatenate([t1, t2])
    f0 = np.concatenate([np.full(t1.size, 220.0), np.full(t2.size, 330.0)])
    segs = NoteHMM().segment(times, f0)
    assert len(segs) >= 2
    f0s = [s.f0_hz for s in segs]
    assert min(abs(f - 220.0) for f in f0s) < 2.0
    assert min(abs(f - 330.0) for f in f0s) < 2.0
    # 第一段全程 220、第二段全程 330，边界在 0.3s 邻域
    seg_220 = min((s for s in segs if abs(s.f0_hz - 220.0) < 2.0), key=lambda s: s.start_s)
    seg_330 = min((s for s in segs if abs(s.f0_hz - 330.0) < 2.0), key=lambda s: s.start_s)
    assert seg_220.start_s == pytest.approx(0.0, abs=DT)
    assert abs(seg_220.end_s - 0.3) < 0.05
    assert abs(seg_330.start_s - 0.3) < 0.05
    assert seg_330.end_s == pytest.approx(0.59, abs=DT)


def test_build_pitch_grid_unknown_segmenter_falls_back():
    """⑨ 未知 segmenter 值回落 simple（与 simple 路径同段数）。"""
    times, f0 = _dual_note_contour()
    g = build_pitch_grid(times, f0, None, SNAP_OFF, segmenter="nope")
    g_ref = build_pitch_grid(times, f0, None, SNAP_OFF, segmenter="simple")
    assert len(g.notes) == len(g_ref.notes)
    assert [n.f0_hz for n in g.notes] == [n.f0_hz for n in g_ref.notes]


def test_conf_passthrough_median():
    """⑩ conf 参数透传：段 conf = 段内原始 conf 中位数。"""
    t = np.arange(0.0, 0.5, DT)
    conf = np.full(t.size, 0.9)
    segs = NoteHMM().segment(t, np.full(t.size, 220.0), conf)
    assert len(segs) == 1
    assert segs[0].conf == pytest.approx(0.9)


def test_segment_state_labels_present():
    """B1-01①：音符段带段型标签（attack/stable/inter），非空串。"""
    times, f0 = _dual_note_contour()
    segs = NoteHMM().segment(times, f0)
    assert segs, "应至少分出两段"
    for s in segs:
        assert s.state in ("attack", "stable", "inter"), (
            f"段型非法：{s.state!r}（须为 attack/stable/inter 之一）"
        )
    # 正对照：段型非常量（稳定段应被解出）——防 state 写死骗过
    assert any(s.state == "stable" for s in segs), (
        f"应至少有一段 stable，实际 {[s.state for s in segs]}"
    )
    # 反量化铁律：f0 仍在原始真值邻域（未被网格污染）
    f0s = [s.f0_hz for s in segs]
    assert min(abs(f - 220.0) for f in f0s) < 2.0
    assert min(abs(f - 330.0) for f in f0s) < 2.0


def test_from_dict_legacy_file_without_state_ok():
    """B1-01②：旧项目文件（无 state 键）反序列化成功，state 落空串且不抛。"""
    from acouscope.analysis.pitch_grid import PitchGridModel

    legacy = {
        "snap_mode": "off",
        "grid_cents": None,
        "notes": [{"start_s": 0.0, "end_s": 0.5, "f0_hz": 220.0, "conf": 0.9}],
    }
    model = PitchGridModel.from_dict(legacy)  # 不得抛
    assert model.notes[0].state == ""  # 缺字段 ⇒ 空串
    # 未知键也必须忽略（白名单构造）
    legacy2 = dict(legacy)
    legacy2["notes"] = [dict(legacy["notes"][0], future_key=1)]
    assert PitchGridModel.from_dict(legacy2).notes[0].state == ""


def test_segment_state_runs_cover_segment():
    """B1-01a①：段内状态序列 state_runs 压茬正确——覆盖全段、首运行态=段级 state。

    每段 runs 非空；run = (起帧, 讫帧, 起秒, 讫秒, 态名)，态名 ∈ 三态；
    首运行态名 == 段级 state（段内首帧口径，防 runs 与段级标签漂移）；
    runs 拼接覆盖全段（±1 帧精度）且相邻 run 帧区间相接；
    正对照：至少一段含 stable 运行（防 state_runs 写死单值骗过）。
    """
    times, f0 = _dual_note_contour()
    segs = NoteHMM().segment(times, f0)
    assert segs, "应至少分出两段"
    seen_stable_run = False
    for s in segs:
        runs = s.state_runs
        assert runs, f"段 {s.start_s:.2f}-{s.end_s:.2f}s 的 state_runs 为空"
        for run in runs:
            assert len(run) == 5, f"run 须为五元组，得到 {run!r}"
            sf, ef, ss, es, name = run
            assert name in ("attack", "stable", "inter"), f"run 态名非法：{name!r}"
            assert isinstance(sf, int) and isinstance(ef, int)
            assert 0 <= sf <= ef  # 帧为全局帧索引（0 起）
            assert ss == pytest.approx(float(times[sf]), abs=1e-12)  # 秒取 times 原值
            assert es == pytest.approx(float(times[ef]), abs=1e-12)
            if name == "stable":
                seen_stable_run = True
        # 首运行态名 == 段级 state（段内首帧口径）
        assert runs[0][4] == s.state, (
            f"首运行态 {runs[0][4]!r} 与段级 state {s.state!r} 漂移"
        )
        # runs 拼接覆盖全段（±1 帧精度）
        assert runs[0][2] == pytest.approx(s.start_s, abs=DT)
        assert runs[-1][3] == pytest.approx(s.end_s, abs=DT)
        # 相邻 run 帧区间相接（前 run.end_frame + 1 == 后 run.start_frame）
        for prev, nxt in zip(runs, runs[1:]):
            assert prev[1] + 1 == nxt[0], (
                f"run 帧区间不相接：{prev[1]!r} → {nxt[0]!r}"
            )
    # 正对照：态名非常量——防 state_runs 写死单值
    assert seen_stable_run, (
        f"应至少一段含 stable 运行，实际 {[[r[4] for r in s.state_runs] for s in segs]}"
    )


def test_from_dict_legacy_without_state_runs_ok():
    """B1-01a②：旧项目文件（notes 无 state_runs 键）反序列化成功，落 () 且不抛。"""
    from acouscope.analysis.pitch_grid import PitchGridModel

    legacy = {
        "snap_mode": "off",
        "grid_cents": None,
        "notes": [{"start_s": 0.0, "end_s": 0.5, "f0_hz": 220.0, "conf": 0.9}],
    }
    model = PitchGridModel.from_dict(legacy)  # 不得抛
    assert model.notes[0].state_runs == ()  # 缺键 ⇒ 空 tuple
    # 未知键也必须忽略（白名单机制复锁）
    legacy2 = dict(legacy)
    legacy2["notes"] = [dict(legacy["notes"][0], future_key=1)]
    assert PitchGridModel.from_dict(legacy2).notes[0].state_runs == ()


def test_bin_boundary_jitter_yields_segment():
    """P5-3a①：bin 等分点（旧版 0 段点）必须出段且段级归属正确。"""
    from acouscope.analysis.tunings.templates import get_template

    tpl = get_template("arabic_24_tone")
    times = np.arange(30) * DT
    for degree in (1, 3, 5, 7):
        f0 = np.full(times.size, float(tpl.degree_to_freq(degree)))
        model = build_pitch_grid(times, f0, segmenter="hmm", tuning=tpl)
        assert len(model.notes) == 1, (
            f"degree {degree} 应出 1 段，实得 {len(model.notes)}"
        )
        assert model.notes[0].degree_index == degree


def test_semitone_jump_still_splits():
    """P5-3a②：半音跳进（100 音分）必须切两段——防容差过宽并段。"""
    f0 = np.concatenate([np.full(40, 440.0), np.full(40, 466.16)])
    segs = NoteHMM().segment(np.arange(f0.size) * DT, f0)
    assert len(segs) == 2, f"半音跳进应 2 段，实得 {len(segs)}"
    assert abs(segs[0].f0_hz - 440.0) < 1.0
    assert abs(segs[1].f0_hz - 466.16) < 1.0


def test_sine_vibrato_single_segment():
    """P5-3a③：同音正弦吟猱（±30 音分、周期 0.3s）保持一段。"""
    t = np.arange(60) * DT
    f0 = 440.0 * 2.0 ** (30.0 * np.sin(2 * np.pi * t / 0.3) / 1200.0)
    segs = NoteHMM().segment(t, f0)
    assert len(segs) == 1, f"吟猱应一段，实得 {len(segs)}"


def test_head_tail_deviation_hand_calc():
    """B3-01 2A①：窗口口径可手算——段内线性上行 30 音分，head 负、tail 正。

    夹具：30 帧（0.3s）从 -15 音分线性升到 +15 音分，跨度 30 音分 < 1 bin，
    不触发 3a 切段；窗口 = min(0.10s, 段长/3) = 10 帧。
    - head = 前 10 帧中位 − 段中位 < 0；
    - tail = 末 10 帧中位 − 段中位 > 0。
    正对照：符号相反，防常量返回或符号写死。
    """
    n = 30
    t = np.arange(n) * DT
    cents = np.linspace(-15.0, 15.0, n)
    f0 = 440.0 * 2.0 ** (cents / 1200.0)
    segs = NoteHMM().segment(t, f0)
    assert len(segs) == 1, f"应恰 1 段，实得 {len(segs)}"
    seg = segs[0]
    win = max(2, min(int(round(0.10 / DT)), n // 3))
    expect_head = 1200.0 * np.log2(float(np.median(f0[:win])) / seg.f0_hz)
    expect_tail = 1200.0 * np.log2(float(np.median(f0[n - win :])) / seg.f0_hz)
    assert seg.head_deviation_cents == pytest.approx(expect_head, abs=1e-9)
    assert seg.tail_deviation_cents == pytest.approx(expect_tail, abs=1e-9)
    assert seg.head_deviation_cents < -5.0, "上行轮廓 head 应显著为负"
    assert seg.tail_deviation_cents > 5.0, "上行轮廓 tail 应显著为正"

    # 段级 → PitchNote 透传（hmm 分支）：逐位相等
    model = build_pitch_grid(t, f0, None, SNAP_OFF, segmenter="hmm")
    assert len(model.notes) == len(segs) >= 1
    for seg_i, note in zip(segs, model.notes):
        assert note.head_deviation_cents == seg_i.head_deviation_cents
        assert note.tail_deviation_cents == seg_i.tail_deviation_cents
    assert any(
        note.head_deviation_cents not in (None, 0.0) for note in model.notes
    ), "透传值全为 0/None —— 与窗口口径不符"

    # to_dict / from_dict 往返保真（白名单含两键）
    data = model.to_dict()
    assert set(data["notes"][0]) >= {"head_deviation_cents", "tail_deviation_cents"}
    back = type(model).from_dict(data)
    assert [n.head_deviation_cents for n in back.notes] == [
        n.head_deviation_cents for n in model.notes
    ]
    assert [n.tail_deviation_cents for n in back.notes] == [
        n.tail_deviation_cents for n in model.notes
    ]


def test_head_tail_short_segment_and_legacy_roundtrip():
    """B3-01 2A②：短段窗口退化不为 None；simple 分支未接保持 None；旧文件缺键 None。

    夹具：静音 2 帧 + [430Hz, 450Hz]（min_dur_s=0.0）→ 2 个单帧段；窗口退化
    到全段 ⇒ 偏离约 0 且非 None（证明窗口口径不依赖 stable run）。
    simple 分支未接窗口口径 ⇒ 两字段保持 None（口径一致：无段内状态不填）。
    旧工程文件（notes 无该两键）from_dict 落 None 且不抛，未知键忽略。
    """
    from acouscope.analysis.pitch_grid import PitchGridModel

    gap = np.full(2, np.nan)
    f0 = np.concatenate([gap, np.asarray([430.0, 450.0])])
    segs = NoteHMM().segment(np.arange(f0.size) * DT, f0, min_dur_s=0.0)
    assert len(segs) == 2, f"应 2 段，实得 {len(segs)}"
    for seg in segs:
        assert seg.head_deviation_cents is not None
        assert seg.tail_deviation_cents is not None
        assert abs(seg.head_deviation_cents) < 1e-6
        assert abs(seg.tail_deviation_cents) < 1e-6

    # simple 分段：notes 非空（正对照）且两字段恒 None（未接窗口口径）
    times, f0_dual = _dual_note_contour()
    simple = build_pitch_grid(times, f0_dual, None, SNAP_OFF, segmenter="simple")
    assert simple.notes, "simple 分段应出段（正对照）"
    assert all(n.state_runs == () for n in simple.notes)
    assert all(n.head_deviation_cents is None for n in simple.notes)
    assert all(n.tail_deviation_cents is None for n in simple.notes)

    # 旧项目文件（缺两键）→ None 且不抛；未知键忽略
    legacy = {
        "snap_mode": "off",
        "grid_cents": None,
        "notes": [{"start_s": 0.0, "end_s": 0.5, "f0_hz": 220.0, "conf": 0.9}],
    }
    model = PitchGridModel.from_dict(legacy)  # 不得抛
    assert model.notes[0].head_deviation_cents is None
    assert model.notes[0].tail_deviation_cents is None
    legacy2 = dict(legacy)
    legacy2["notes"] = [dict(legacy["notes"][0], future_key=1)]
    assert PitchGridModel.from_dict(legacy2).notes[0].head_deviation_cents is None
    # None 值往返仍为 None（不落 0.0）
    assert PitchGridModel.from_dict(model.to_dict()).notes[0].tail_deviation_cents is None


def test_vibrato_merged_single_segment():
    """P5-B3-01b①：吟猱（±50／±80 音分，周期 0.3s）合并为一段。"""
    t = np.arange(60) * DT
    for amp in (50.0, 80.0):
        f0 = 440.0 * 2.0 ** (amp * np.sin(2 * np.pi * t / 0.3) / 1200.0)
        segs = NoteHMM().segment(t, f0)
        assert len(segs) == 1, f"±{amp} 音分吟猱应 1 段，实得 {len(segs)}"


def test_step_jump_not_merged():
    """P5-B3-01b②：半音／全音跳进不得被合并（单调形态无往复）。"""
    t = np.arange(60) * DT
    for semi in (1.0, 2.0):
        f0 = 440.0 * 2.0 ** (np.r_[np.zeros(30), np.full(30, semi)] / 12.0)
        segs = NoteHMM().segment(t, f0)
        assert len(segs) == 2, f"{semi} 半音跳进应 2 段，实得 {len(segs)}"


def test_arpeggio_not_merged():
    """P5-B3-01b③：三音上行琶音保持 3 段（防把上行串当吟猱合并）。"""
    t = np.arange(60) * DT
    semi = np.r_[np.zeros(20), np.full(20, 1.0), np.full(20, 2.0)]
    f0 = 440.0 * 2.0 ** (semi / 12.0)
    segs = NoteHMM().segment(t, f0)
    assert len(segs) == 3, f"琶音应 3 段，实得 {len(segs)}"
