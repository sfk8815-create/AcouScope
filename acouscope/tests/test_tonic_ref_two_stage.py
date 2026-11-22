# SPDX-License-Identifier: GPL-3.0-only
"""主音两阶段拟合与 ref_mode 贯通（任务-20261025-主音两阶段）。

学理（任务件 §六）：偏移属演奏实践／文献，主音属乐学判断。两量同时未知时
整体平移等价、主音不可识别；两阶段把偏移作为**显式输入**先固定，主音才在
受限范围内可辨。故本文件的判据分三组：

1. 正对照：已知主音＋已知偏移（F ＋ 90 音分，合成值，不等于四例任何一例），
   有锚两阶段须还原 F 且 ``offset_cents`` ＝ 锚＋残差；
2. 负对照：锚偏过大／临界时，不得静默给出与正确锚相同的读数；
3. 回归：无锚时保持联合搜索（``stage="joint"``），旧读不变；``absolute`` 行不变。
"""

import numpy as np
import pytest

from acouscope.analysis.pitch_grid import _segment_degree, build_pitch_grid
from acouscope.analysis.tonic_ref import (
    JOINT_SEARCH_CENTS,
    REF_ABSOLUTE,
    REF_MAIN_TONE,
    TONIC_NAMES,
    TWO_STAGE_SEARCH_CENTS,
    degree_rows,
    degree_rows_both,
    degree_rows_for_model,
    fit_tonic,
    fit_tonic_from_audio,
)
from acouscope.analysis.tunings.templates import get_template

# 合成夹具：F 五声、三个八度、整体偏高 90 音分（不等于四例的任何锚值）
TRUE_TONIC = "F"
TRUE_OFFSET = 90.0
N_PER = 60


def _penta(tonic: str, offset_cents: float = 0.0, octaves=(0, 1, 2)) -> np.ndarray:
    base = 440.0 * 2.0 ** ((TONIC_NAMES.index(tonic) - 9) / 12.0)
    parts = [
        np.full(
            N_PER,
            base * 2.0 ** (oc + off / 12.0) * 2.0 ** (offset_cents / 1200.0),
        )
        for oc in octaves
        for off in (0, 2, 4, 7, 9)
    ]
    return np.concatenate(parts)


@pytest.fixture(scope="module")
def f0():
    return _penta(TRUE_TONIC, TRUE_OFFSET)


@pytest.fixture(scope="module")
def fit_two_stage(f0):
    return fit_tonic(
        f0, anchor_offset_cents=TRUE_OFFSET, anchor_source="synthetic-F+90"
    )


# ---------------- 1. 正对照：有锚两阶段 ----------------


def test_two_stage_recovers_tonic_and_total_offset(fit_two_stage):
    """有锚：主音＝F；``offset_cents`` ＝ 锚＋残差；残差落在受限搜索内。"""
    best = fit_two_stage["best"]
    assert fit_two_stage["method"]["stage"] == "two_stage"
    assert best["tonic"] == TRUE_TONIC
    assert best["offset_cents"] == pytest.approx(TRUE_OFFSET, abs=1e-9)
    assert best["offset_cents"] == pytest.approx(
        TRUE_OFFSET + best["residual_offset_cents"], abs=1e-9
    )
    assert abs(best["residual_offset_cents"]) <= TWO_STAGE_SEARCH_CENTS
    assert fit_two_stage["margin"] > 0.05, (
        f"有锚时主音应可辨，实得 margin={fit_two_stage['margin']}"
    )


def test_two_stage_method_fields(fit_two_stage):
    """method 须登记阶段、锚与搜索参数（可审计，缺一不可）。"""
    m = fit_two_stage["method"]
    assert m["stage"] == "two_stage"
    assert m["anchor_offset_cents"] == pytest.approx(TRUE_OFFSET)
    assert m["anchor_source"] == "synthetic-F+90"
    assert m["search_cents"] == TWO_STAGE_SEARCH_CENTS
    assert m["step_cents"] == 2
    assert m["scale"] == "pentatonic"
    assert m["hist_bins"] == 1200
    assert m["bin_cents"] == 1
    assert m["template_sigma_cents"] == 30.0
    for row in fit_two_stage["ranking"]:
        assert {"tonic", "offset_cents", "residual_offset_cents", "score"} <= set(row)


def test_two_stage_does_not_mutate_input(f0):
    """两阶段归一只在本地副本上做，入参 f0 不得被改写（反量化铁律）。"""
    before = np.array(f0, dtype=float, copy=True)
    fit_tonic(f0, anchor_offset_cents=TRUE_OFFSET)
    assert np.array_equal(f0, before)


def test_search_cents_override_is_honoured(f0):
    """显式 search_cents 覆盖默认：放宽到 150 时 method 记 150（并可改变主音判定）。"""
    fit = fit_tonic(f0, anchor_offset_cents=TRUE_OFFSET, search_cents=150)
    assert fit["method"]["search_cents"] == 150
    assert abs(fit["best"]["residual_offset_cents"]) <= 150


# ---------------- 2. 负对照：锚错 ----------------


def test_wrong_anchor_beyond_search_does_not_echo_right_answer(f0, fit_two_stage):
    """锚偏 90 音分（> 默认 50）⇒ 不得静默给出与正确锚相同的读数。

    实测形态：主音落到 F#（同音级类等价位置），总偏移 −10；与正确锚的 F／+90
    相差一个半音——即「锚错则主音错」，且结果仍带 ranking／margin 供审计。
    """
    wrong = fit_tonic(f0, anchor_offset_cents=0.0, anchor_source="synthetic-wrong")
    same_tonic = wrong["best"]["tonic"] == fit_two_stage["best"]["tonic"]
    same_offset = wrong["best"]["offset_cents"] == pytest.approx(
        fit_two_stage["best"]["offset_cents"], abs=1e-9
    )
    assert not (same_tonic and same_offset), "锚错却给出与正确锚完全相同的读数（静默失败）"
    assert wrong["best"]["tonic"] != TRUE_TONIC
    assert len(wrong["ranking"]) == len(TONIC_NAMES)
    assert wrong["margin"] is not None


def test_near_boundary_anchor_collapses_margin(f0, fit_two_stage):
    """锚偏恰 50 音分（搜索边界）⇒ 主音仍对，但残差撞边界、margin 塌到 0。"""
    near = fit_tonic(
        f0, anchor_offset_cents=TRUE_OFFSET - TWO_STAGE_SEARCH_CENTS,
        anchor_source="synthetic-near",
    )
    assert near["best"]["tonic"] == TRUE_TONIC
    assert near["best"]["residual_offset_cents"] == pytest.approx(
        float(TWO_STAGE_SEARCH_CENTS), abs=1e-9
    )
    assert near["margin"] < fit_two_stage["margin"], (
        f"锚偏临界时 margin 应下降：near={near['margin']} vs ok={fit_two_stage['margin']}"
    )


def test_nonfinite_anchor_rejected():
    """锚值非有限 ⇒ 直接报错，不得当 0 处理（否则退化为联合搜索而无声）。"""
    with pytest.raises(ValueError):
        fit_tonic(_penta(TRUE_TONIC), anchor_offset_cents=float("nan"))


# ---------------- 3. 回归：无锚联合搜索 ----------------


def test_joint_stage_kept_and_marked(f0):
    """无锚 ⇒ ``stage="joint"``、搜索半径 150、method 无锚值（旧行为不变）。"""
    joint = fit_tonic(f0)
    assert joint["method"]["stage"] == "joint"
    assert joint["method"]["search_cents"] == JOINT_SEARCH_CENTS
    assert joint["method"]["anchor_offset_cents"] is None
    assert joint["method"]["anchor_source"] is None
    assert joint["best"]["offset_cents"] == joint["best"]["residual_offset_cents"]


def test_joint_is_unidentifiable_while_two_stage_is_not(f0, fit_two_stage):
    """联合搜索在同一夹具上 margin=0（平移等价、主音不可辨），两阶段 margin>0。

    这是「无锚结果不得当作已确认主音」的直接证据，也是两阶段存在的理由。
    """
    joint = fit_tonic(f0)
    assert joint["margin"] == pytest.approx(0.0, abs=1e-9)
    assert fit_two_stage["margin"] > joint["margin"]


def test_joint_ranking_offsets_within_search_range(f0):
    """联合搜索候选偏移仍落在 ±150、步长 2 的格点上（旧读数面不变）。"""
    joint = fit_tonic(f0)
    grid = set(range(-JOINT_SEARCH_CENTS, JOINT_SEARCH_CENTS + 1, 2))
    assert {int(row["offset_cents"]) for row in joint["ranking"]} <= grid


# ---------------- 4. 两口径贯通 ----------------


class _Note:
    def __init__(self, start_s, end_s, f0_hz):
        self.start_s = start_s
        self.end_s = end_s
        self.f0_hz = f0_hz


class _Model:
    def __init__(self, notes):
        self.notes = notes


def test_absolute_rows_unaffected():
    """absolute 行：``offset_applied_cents==0``，degree／deviation 与段级归属逐位一致。"""
    tpl = get_template("12tet")
    model = _Model([_Note(0.0, 0.5, 440.0), _Note(0.6, 1.1, 261.63)])
    rows = degree_rows(model, tpl, ref_mode=REF_ABSOLUTE)
    expect = [_segment_degree(note.f0_hz, tpl) for note in model.notes]
    assert [(r["degree_index"], r["deviation_cents"]) for r in rows] == expect
    assert all(r["ref_mode"] == REF_ABSOLUTE for r in rows)
    assert all(r["offset_applied_cents"] == 0.0 for r in rows)


def test_main_tone_rows_use_total_offset(fit_two_stage):
    """main_tone 行：``offset_applied_cents`` ＝ 总偏移（锚＋残差），不是残差。"""
    tpl = get_template("12tet")
    hz = 349.23 * 2.0 ** (TRUE_OFFSET / 1200.0)  # F4 偏高 90 音分
    model = _Model([_Note(0.0, 0.5, hz)])
    rows = degree_rows(model, tpl, ref_mode=REF_MAIN_TONE, fit=fit_two_stage)
    best = fit_two_stage["best"]
    assert best["residual_offset_cents"] != best["offset_cents"], "夹具未区分总偏移与残差"
    assert rows[0]["ref_mode"] == REF_MAIN_TONE
    assert rows[0]["offset_applied_cents"] == pytest.approx(round(best["offset_cents"], 2))
    assert rows[0]["offset_applied_cents"] == pytest.approx(TRUE_OFFSET, abs=1e-6)
    assert rows[0]["offset_applied_cents"] != pytest.approx(
        best["residual_offset_cents"], abs=1e-6
    )


def test_degree_rows_both_keeps_modes_separate(fit_two_stage):
    """两口径一次取回：分键、行数相等、ref_mode 各半，不合并成一个列表。"""
    tpl = get_template("12tet")
    model = _Model([_Note(0.0, 0.5, 466.16), _Note(0.6, 1.1, 415.30)])
    both = degree_rows_both(model, tpl, fit=fit_two_stage)
    assert set(both) == {REF_ABSOLUTE, REF_MAIN_TONE}
    assert len(both[REF_ABSOLUTE]) == len(both[REF_MAIN_TONE]) == 2
    assert {r["ref_mode"] for r in both[REF_ABSOLUTE]} == {REF_ABSOLUTE}
    assert {r["ref_mode"] for r in both[REF_MAIN_TONE]} == {REF_MAIN_TONE}
    assert all(r["offset_applied_cents"] == 0.0 for r in both[REF_ABSOLUTE])
    assert all(
        r["offset_applied_cents"] == pytest.approx(TRUE_OFFSET, abs=1e-6)
        for r in both[REF_MAIN_TONE]
    )


def test_main_tone_requires_fit():
    """main_tone 缺 fit ⇒ 报错（不得静默按 absolute 处理）。"""
    tpl = get_template("12tet")
    with pytest.raises(ValueError):
        degree_rows(_Model([_Note(0.0, 0.5, 440.0)]), tpl, ref_mode=REF_MAIN_TONE)


def test_fit_from_audio_pins_standard_take(tmp_path):
    """录音取数三项须写死在代码里：30 s 窗、不过 HMM、只取有声帧。"""
    import soundfile as sf

    sr = 44100
    base = 349.23 * 2.0 ** (TRUE_OFFSET / 1200.0)  # F4 偏高 90 音分（合成值）
    parts = []
    for semi in (0, 2, 4, 7, 9):  # 五声音级各 0.8 s：单音不足以定主音，故用音阶片段
        t = np.arange(int(sr * 0.8)) / sr
        parts.append(0.2 * np.sin(2 * np.pi * base * 2.0 ** (semi / 12.0) * t))
    path = tmp_path / "penta.wav"
    sf.write(str(path), np.concatenate(parts), sr)

    result = fit_tonic_from_audio(
        path, anchor_offset_cents=TRUE_OFFSET, anchor_source="synthetic-F+90"
    )
    source = result["source"]
    assert source["window_start_s"] == 0.0 and source["window_s"] == 30.0
    assert source["hmm"] is False
    assert "isfinite" in source["silence_rule"]
    assert 0 < source["voiced_frames"] <= source["total_frames"]
    assert result["method"]["stage"] == "two_stage"
    assert result["best"]["tonic"] == TRUE_TONIC


def test_fit_from_audio_rejects_out_of_range_window(tmp_path):
    """窗口越界 ⇒ 报错（不静默给空帧拟合）。"""
    import soundfile as sf

    path = tmp_path / "short.wav"
    sf.write(str(path), 0.2 * np.sin(2 * np.pi * 440.0 * np.arange(4410) / 44100.0), 44100)
    with pytest.raises(ValueError):
        fit_tonic_from_audio(path, window_start_s=10.0, window_s=30.0)


def test_public_path_works_on_build_pitch_grid_model(fit_two_stage):
    """公开调用路径在真实构建的模型上可用（pitch_grid → degree_rows_for_model）。"""
    tpl = get_template("12tet")
    n = 400
    sr_frame = 44100.0 / 256.0
    times = np.arange(n) / sr_frame
    f0 = np.full(n, 349.23 * 2.0 ** (TRUE_OFFSET / 1200.0))
    conf = np.ones(n)
    model = build_pitch_grid(times, f0, conf, segmenter="simple", tuning=tpl)
    assert model.notes, "合成夹具未分段，判据失去意义"

    abs_rows = degree_rows_for_model(model, tpl, ref_mode=REF_ABSOLUTE)
    mt_rows = degree_rows_for_model(model, tpl, ref_mode=REF_MAIN_TONE, fit=fit_two_stage)
    assert len(abs_rows) == len(mt_rows) == len(model.notes)
    assert {r["ref_mode"] for r in abs_rows} == {REF_ABSOLUTE}
    assert {r["ref_mode"] for r in mt_rows} == {REF_MAIN_TONE}
    # 平均律下 F+90 音分在 absolute 下不在 F 上，归一到 main_tone 后应落 F
    assert abs_rows[0]["degree_index"] != mt_rows[0]["degree_index"], (
        "两口径未产生差异，判据退化"
    )
