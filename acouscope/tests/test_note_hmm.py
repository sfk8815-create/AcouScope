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
