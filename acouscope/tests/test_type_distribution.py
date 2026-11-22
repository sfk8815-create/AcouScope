# SPDX-License-Identifier: GPL-3.0-only
"""三型分布读数层测试（任务件-20261026 · T-1／T-2／T-5）。TYPE_DISTRIBUTION_TEST_V1

覆盖（来对位任务件 §二 字段名）：
① τ 由平台声明：``tau_declaration()`` 取占位常量，未标定 ⇒ ``unspecified_sign_based``；
② 扫描 τ **不得**冒充标定：``scan_tau_status(数值) = assumed_for_scan``（不在枚举面内）；
③ ``counts_per_recording`` 四值＋合计与平台分类器逐段对拍；
④ τ 敏感性：``flip_count``／``flip_rate``／``flip_direction_counts`` 可手算对拍；
⑤ ``label_gloss`` 覆盖全部标签且「未分类」明写复合型；
⑥ 两口径配对：matched／unmatched 计数；图件分面数据带 run_id 与 τ；
⑦ ``run_id`` 内容定址且可复算（同描述符 ⇒ 同 id）。
"""

import json

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.cavity_type import (  # noqa: E402
    LABELS,
    LABEL_UNCLASSIFIED,
    TAU_CENTS_PLACEHOLDER,
)
from acouscope.analysis.type_distribution import (  # noqa: E402
    DEFAULT_TAU_VALUES,
    LABEL_GLOSS,
    TAU_STATUSES,
    TAU_STATUS_SCAN_ASSUMED,
    TAU_STATUS_UNSPECIFIED,
    count_labels,
    distribution_payload,
    pair_segments,
    panels_payload,
    run_descriptor,
    run_id as compute_run_id,
    scan_tau_status,
    segment_source_snapshot,
    sweep_summary,
    tau_declaration,
    tau_key,
    tau_sweep_payload,
)


def _row(seg, head=None, tail=None, turns=0):
    return {
        "segment_id": seg,
        "start_s": float(seg.split("-")[0]),
        "end_s": float(seg.split("-")[1]),
        "head_deviation_cents": head,
        "tail_deviation_cents": tail,
        "turns": turns,
        "turns_valid": turns is not None,
        "pp_cents": 0.0,
        "rate_hz": 0.0,
    }


ROWS = [
    _row("0.000-1.000", head=-20.0),  # 上趋
    _row("1.000-2.000", head=20.0),  # 下趋
    _row("2.000-3.000", head=0.0, tail=0.0),  # 平直
    _row("3.000-4.000", head=-8.0, tail=-8.0),  # 复合 ⇒ 未分类
    _row("4.000-5.000", tail=15.0, turns=3),  # 上趋
]


def test_tau_declaration_takes_platform_placeholder():
    """① τ 由平台声明：值取占位常量，未标定 ⇒ unspecified_sign_based。"""
    assert TAU_CENTS_PLACEHOLDER is None
    assert tau_declaration() == {
        "tau_cents": None,
        "tau_status": TAU_STATUS_UNSPECIFIED,
    }
    assert TAU_STATUS_UNSPECIFIED in TAU_STATUSES


def test_scan_tau_status_does_not_fake_calibration():
    """② 扫描用 τ 一律记 assumed_for_scan，**不得**落入标定枚举。"""
    assert scan_tau_status(None) == TAU_STATUS_UNSPECIFIED
    for value in (10.0, 20.0, 30.0):
        assert scan_tau_status(value) == TAU_STATUS_SCAN_ASSUMED
        assert scan_tau_status(value) not in TAU_STATUSES


def test_count_labels_matches_classifier_verbatim():
    """③ counts_per_recording 四值＋合计：逐段与平台分类器对拍。"""
    counts = count_labels(ROWS)
    assert counts == {"上趋": 2, "下趋": 1, "平直": 1, "未分类": 1, "合计": 5}, counts
    # 显式 τ（扫描档）⇒ 容差内不计有向，逐段应回落平直
    assert count_labels(ROWS, tau_cents=20.0)["平直"] == 5


def test_tau_sweep_flip_count_rate_and_direction():
    """④ τ 敏感性：flip_count／flip_rate／方向计数可手算对拍。"""
    sweep = tau_sweep_payload(ROWS, tau_values=DEFAULT_TAU_VALUES)
    assert sweep["tau_values"] == [None, 10.0, 20.0, 30.0]
    assert sweep["n_segments"] == 5
    # None→10：未分类→平直 1；10→20：上趋→平直 2、下趋→平直 1；20→30：0
    assert sweep["flip_count"] == 4, sweep["flips"]
    assert sweep["flip_rate"] == pytest.approx(4 / 15)
    assert sweep["flip_direction_counts"]["未分类→平直"] == 1
    assert set(sweep["flip_direction_counts"]) == {"未分类→平直", "上趋→平直", "下趋→平直"}
    # 每条翻转都带全字段（T-2 字段面）
    for flip in sweep["flips"]:
        assert set(flip) == {"segment_id", "tau_from", "tau_to", "label_from", "label_to"}
    # 扫描值状态不得记为标定（防冒充）
    assert sweep["tau_status_by_tau"]["20.0"] == TAU_STATUS_SCAN_ASSUMED
    assert sweep["tau_status_by_tau"]["None"] == TAU_STATUS_UNSPECIFIED
    # 平台自身的标定态单列，且不受扫描值影响
    assert sweep["tau_declaration"]["tau_status"] == TAU_STATUS_UNSPECIFIED


def test_label_gloss_covers_every_label():
    """⑤ label_gloss 覆盖全部标签，「未分类」明写复合型（非「未达资格」）。"""
    assert set(LABEL_GLOSS) == set(LABELS)
    assert LABEL_GLOSS[LABEL_UNCLASSIFIED] == "复合型（头尾倾向相反）"


def _two_mode_rows():
    a = [
        {"segment_id": "0.000-1.000", "start_s": 0.0, "end_s": 1.0,
         "head_deviation_cents": -20.0, "tail_deviation_cents": None},
        {"segment_id": "1.000-2.000", "start_s": 1.0, "end_s": 2.0,
         "head_deviation_cents": -20.0, "tail_deviation_cents": None},
        {"segment_id": "2.000-3.000", "start_s": 2.0, "end_s": 3.0,
         "head_deviation_cents": -20.0, "tail_deviation_cents": None},
    ]
    b = [
        {"segment_id": "0.000-1.000", "start_s": 0.0, "end_s": 1.0,
         "head_deviation_cents": -20.0, "tail_deviation_cents": None},
        {"segment_id": "1.000-2.000", "start_s": 1.0, "end_s": 2.0,
         "head_deviation_cents": 20.0, "tail_deviation_cents": None},
    ]
    return a, b


def test_pair_segments_counts_matched_and_unmatched():
    """⑥ 两口径配对：配对段数／未配对段（表 4-3 的「未配对段」列）。"""
    rows_a, rows_b = _two_mode_rows()
    pairing = pair_segments(rows_a, rows_b, overlap_ratio=0.5)
    assert pairing["matched"] == 2
    assert pairing["unmatched_a"] == 1
    assert pairing["unmatched_b"] == 0
    # 改判方向记账（同段两口径标签不同）
    assert pairing["type_flips"] == {"上趋→下趋": 1}, pairing["type_flips"]


def test_panels_payload_carries_run_id_and_tau():
    """⑥ 图件分面数据随件带 run_id 与 τ（T-3 同源断言可用）。"""
    payload = panels_payload([("甲组", ROWS)], run_id_="run-abcdef")
    assert payload["run_id"] == "run-abcdef"
    assert payload["tau_status"] == TAU_STATUS_UNSPECIFIED
    assert payload["label_gloss"] == LABEL_GLOSS
    assert [panel["label"] for panel in payload["panels"]] == ["甲组"]
    rows = payload["panels"][0]["rows"]
    assert [row["cavity_type"] for row in rows] == ["上趋", "下趋", "平直", "未分类", "上趋"]
    assert [row["turns"] for row in rows] == [0, 0, 0, 0, 3]


def test_run_id_is_deterministic_and_content_addressed():
    """⑦ 同描述符 ⇒ 同 run_id；换输入／换 τ 面 ⇒ 不同（内容定址，非时间戳）。"""
    source = segment_source_snapshot()
    inputs = [{"recording_id": "r1", "audio_name": "a.wav", "sha256": "0" * 64,
              "frames": 100, "samplerate": 44100, "duration_s": 100.0,
              "anchor_offset_cents": None, "anchor_source": ""}]
    desc = run_descriptor(inputs=inputs, segment_source=source,
                          tau_values=DEFAULT_TAU_VALUES, ref_modes=("absolute",))
    again = run_descriptor(inputs=inputs, segment_source=source,
                           tau_values=DEFAULT_TAU_VALUES, ref_modes=("absolute",))
    assert compute_run_id(desc) == compute_run_id(again)
    assert len(compute_run_id(desc)) == 16
    # run_id 不进入被哈希的描述符（否则自指、不可复算）
    assert "run_id" not in desc
    other = run_descriptor(
        inputs=[dict(inputs[0], recording_id="r2")], segment_source=source,
        tau_values=DEFAULT_TAU_VALUES, ref_modes=("absolute",),
    )
    assert compute_run_id(other) != compute_run_id(desc)
    other_tau = run_descriptor(inputs=inputs, segment_source=source,
                               tau_values=(None, 25.0), ref_modes=("absolute",))
    assert compute_run_id(other_tau) != compute_run_id(desc)


def test_distribution_payload_field_surface():
    """①／T-1 字段面：run_id／tau_cents／tau_status／segment_source／counts_per_recording／ref_mode。"""
    payload = distribution_payload(ROWS, recording_id="r1", ref_mode="absolute",
                                   run_id_="run-123456")
    for key in ("run_id", "tau_cents", "tau_status", "segment_source",
                "counts_per_recording", "ref_mode"):
        assert key in payload, key
    assert payload["tau_cents"] is None
    assert payload["tau_status"] == TAU_STATUS_UNSPECIFIED
    assert payload["ref_mode"] == "absolute"
    assert payload["counts_per_recording"]["合计"] == 5
    # T-4：A4 基准与来源语义随件
    assert payload["reference_hz"] == 440.0
    assert payload["reference_status"] == "default-nominal"
    # T-5：标签语义随件
    assert payload["label_gloss"] == LABEL_GLOSS
    # 分段快照：分段器与取数参数随件（换参即换数）
    src = payload["segment_source"]
    assert src["segmenter"] == "hmm"
    assert src["tuning_template"] == "12tet"
    assert src["params_snapshot"]["a4_reference_hz"] == 440.0


def test_tau_key_is_json_safe():
    """τ 键：None 与数值不混淆（JSON 对象键须为字符串）。"""
    assert tau_key(None) == "None"
    assert tau_key(20.0) == "20.0"
    assert tau_key(None) != tau_key(0.0)
