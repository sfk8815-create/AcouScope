# SPDX-License-Identifier: GPL-3.0-only
"""腔核候选区间本体测试（B2-01 / PI-P5 批次 2）。CAVITY_CORE_TEST_V1

覆盖（派活令 §判据）：
① 双音轮廓（220/330Hz，hmm 分段，tuning=get_template("12tet")）→ 候选非空；
   每条候选与某 stable run 起讫秒逐位相等；候选 ⊆ 段边界（不跨段）；段级归属
   继承一致；正对照并入本条：候选 deviation_cents 与来源 note 的
   degree_deviation_cents 逐位相等；另含「按 run 切、禁恒取整段」判据（M1
   守门——纯音轮廓实测每段仅一个 stable run，故补构 attack+stable 压茬 note）；
② 手工构造「无 stable run」的 note → 零候选（守门：禁整段当候选的膨胀实现）。

夹具口径照 tests/test_note_hmm.py::_dual_note_contour（本文件内自建同口径夹具，
不跨测试文件 import——仓内跨文件 import 先例仅 tests/_pin_baselines.py 辅助模块）。
"""

import dataclasses

import numpy as np
import pytest

pytest.importorskip("numpy")

from acouscope.analysis.cavity_core import CoreCandidate, core_candidates  # noqa: E402
from acouscope.analysis.pitch_grid import (  # noqa: E402
    SNAP_OFF,
    PitchGridModel,
    PitchNote,
    build_pitch_grid,
)
from acouscope.analysis.tunings import get_template  # noqa: E402

DT = 0.01


def _dual_note_contour():
    """220Hz 0.5s + 0.15s 静音 + 330Hz 0.5s（口径同 test_note_hmm._dual_note_contour）。"""
    t1 = np.arange(0.0, 0.5, DT)
    tg = np.arange(0.5, 0.65, DT)
    t2 = np.arange(0.65, 1.15, DT)
    times = np.concatenate([t1, tg, t2])
    f0 = np.concatenate(
        [np.full(t1.size, 220.0), np.full(tg.size, np.nan), np.full(t2.size, 330.0)]
    )
    return times, f0


def _owners_of(cand, notes):
    """持有该候选的 note 列表：其 state_runs 含同起讫秒的 stable run。"""
    return [
        n
        for n in notes
        if any(
            r[4] == "stable" and r[2] == cand.start_s and r[3] == cand.end_s
            for r in n.state_runs
        )
    ]


def test_candidates_from_stable_runs():
    """① 双音轮廓 hmm 分段 + 12tet → 候选非空、逐位对齐 stable run、不跨段、归属继承。"""
    times, f0 = _dual_note_contour()
    model = build_pitch_grid(
        times, f0, None, SNAP_OFF, segmenter="hmm", tuning=get_template("12tet")
    )
    candidates = core_candidates(model)
    assert candidates, "双音轮廓 hmm 分段应产出腔核候选（stable 运行非空）"
    assert all(isinstance(c, CoreCandidate) for c in candidates)

    # 候选数 == 全模型 stable run 数（一 run 一候选，不多不少）
    stable_runs = [
        (r[2], r[3]) for n in model.notes for r in n.state_runs if r[4] == "stable"
    ]
    assert stable_runs, "夹具自身须含 stable 运行（正对照）"
    assert len(candidates) == len(stable_runs)

    # 每条候选恰属单一 note（不跨段），且起讫秒逐位相等
    owned = []
    for cand in candidates:
        owners = _owners_of(cand, model.notes)
        assert len(owners) == 1, (
            f"候选 {cand.start_s}-{cand.end_s}s 不属单一 note（跨段或来路不明）"
        )
        owned.append((cand, owners[0]))
        assert (cand.start_s, cand.end_s) in stable_runs

    for cand, note in owned:
        # 候选 ⊆ 段边界
        assert note.start_s <= cand.start_s
        assert cand.end_s <= note.end_s
        # 段级归属继承一致（正对照：与来源 note 的字段逐位相等）
        assert cand.degree_index == note.degree_index
        assert cand.deviation_cents == note.degree_deviation_cents
        assert cand.conf == note.conf
        # 正对照：12tet 传入时归属非 None（防「全 None 也过」）
        assert note.degree_index is not None
        assert note.degree_deviation_cents is not None

    # 按 run 切（禁恒取整段）：实测纯音轮廓的 hmm 分段每段只压茬出一个 stable
    # run（起音处 attack 帧孤立出现即被 min_dur 丢弃，见 test_note_hmm 夹具），
    # 故另构一个含 attack + stable 压茬 runs 的 note，把「按 run 切」性质
    # 判据化（M1「候选恒取全段」守门）。
    split_model = PitchGridModel(
        notes=[
            PitchNote(
                start_s=0.0,
                end_s=0.5,
                f0_hz=220.0,
                conf=0.9,
                state="attack",
                state_runs=(
                    (0, 9, 0.0, 0.09, "attack"),
                    (10, 49, 0.10, 0.49, "stable"),
                ),
                degree_index=-12,
                degree_deviation_cents=0.0,
            )
        ]
    )
    split = core_candidates(split_model)
    assert len(split) == 1, "仅 stable run 产候选（attack run 不产）"
    only = split[0]
    assert (only.start_s, only.end_s) == (0.10, 0.49)  # 逐位等于 stable run 起讫秒
    assert only.start_s > 0.0 and only.end_s < 0.5  # 严格窄于整段（禁膨胀实现）
    assert only.degree_index == -12
    assert only.deviation_cents == 0.0
    assert only.conf == 0.9


def test_no_stable_run_yields_no_candidates():
    """② 手工构造「无 stable run」的 note → 零候选（守门：禁整段当候选的膨胀实现）。"""
    model = PitchGridModel(
        notes=[
            # runs 非空但无 stable：attack + inter 交替（禁启发式回退整段）
            PitchNote(
                start_s=0.0,
                end_s=0.5,
                f0_hz=220.0,
                conf=0.9,
                state="attack",
                state_runs=(
                    (0, 10, 0.0, 0.1, "attack"),
                    (11, 20, 0.11, 0.2, "inter"),
                    (21, 50, 0.21, 0.5, "attack"),
                ),
                degree_index=0,
                degree_deviation_cents=2.0,
            ),
            # 旧数据 / simple 分段：state_runs 为空 tuple（段级 state 也不得泄漏为候选）
            PitchNote(
                start_s=0.6,
                end_s=1.2,
                f0_hz=330.0,
                conf=0.8,
                state="stable",
                state_runs=(),
                degree_index=7,
                degree_deviation_cents=-3.5,
            ),
        ]
    )
    assert core_candidates(model) == []

    # 空模型亦零候选（不抛）
    assert core_candidates(PitchGridModel(notes=[])) == []

    # CoreCandidate 形制定死：五字段、顺序与派活令一致；frozen（不可变候选）
    assert [f.name for f in dataclasses.fields(CoreCandidate)] == [
        "start_s",
        "end_s",
        "degree_index",
        "deviation_cents",
        "conf",
    ]
    cand = CoreCandidate(
        start_s=0.0, end_s=0.1, degree_index=None, deviation_cents=None, conf=0.5
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        cand.start_s = 1.0  # type: ignore[misc]
