# SPDX-License-Identifier: GPL-3.0-only
"""主体模型与主客观对照中间件测试（B3-02 / PI-P5 第 2 棒）。SUBJECT_BLIND_TEST_V1

覆盖（派活令 §判据）：
① 主体往返（Subject frozen、两栏 role）+ 旧文件（无 subjects 键）⇒ 空列表；
② 盲包全文检索 ``display_name`` 零命中（键与真名值双查），候选端降级披露；
③ 一致率手算对拍（1.0／0.0／None），两栏分算不合并。

夹具为合成主体与合成判定行：只验契约与算术，不代表任何真实主体或专家判定。
"""

import dataclasses
import json

import pytest

from acouscope.annotation.subject import (
    BLIND_LABELS,
    PACKET_FORMAT,
    ROLES,
    SUBJECTS_KEY,
    Subject,
    agreement_stats,
    export_blind_packet,
    import_blind_responses,
    subjects_from_metadata,
    subjects_to_metadata,
)
from acouscope.analysis.pitch_grid import PitchGridModel, PitchNote

REAL_NAMES = ("张三", "李四")


def _subjects():
    """两栏主体夹具（真名只应存在于本地主体表）。"""
    return [
        Subject(subject_id="Q1", role="qin_player", display_name=REAL_NAMES[0], note="琴人甲"),
        Subject(subject_id="E1", role="erhu_player", display_name=REAL_NAMES[1], note="二胡乙"),
    ]


def _model_with_runs():
    """含 stable 运行的模型（候选端走 CoreCandidate：一 run 一候选）。"""
    return PitchGridModel(
        notes=[
            PitchNote(
                start_s=0.0,
                end_s=0.5,
                f0_hz=440.0,
                conf=0.9,
                state="stable",
                state_runs=((0, 49, 0.0, 0.49, "stable"),),
                degree_index=0,
                degree_deviation_cents=1.0,
            )
        ]
    )


def test_subject_roundtrip_and_legacy_empty():
    """① 主体往返（frozen、两栏）+ 旧文件缺键 ⇒ 空列表，坏数据零崩溃。"""
    subjects = _subjects()
    metadata = subjects_to_metadata(subjects)
    # metadata 不变式：Dict[str, str]，主体列表整体进单值 JSON 串
    assert list(metadata) == [SUBJECTS_KEY]
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in metadata.items())
    assert subjects_from_metadata(metadata) == subjects  # 往返全等（含真名与备注）
    assert json.loads(metadata[SUBJECTS_KEY])[0]["role"] == "qin_player"

    # 旧文件：无 subjects 键 / None / 非 Mapping ⇒ 空列表（不抛）
    assert subjects_from_metadata({}) == []
    assert subjects_from_metadata(None) == []
    assert subjects_from_metadata({"Title": "x"}) == []
    # 坏 JSON / 结构不符 / 未登记角色 ⇒ 空列表或跳过该条（不抛）
    assert subjects_from_metadata({SUBJECTS_KEY: "not json"}) == []
    assert subjects_from_metadata({SUBJECTS_KEY: '{"a": 1}'}) == []
    assert subjects_from_metadata({SUBJECTS_KEY: "[]"}) == []
    assert subjects_from_metadata(
        {SUBJECTS_KEY: '[{"subject_id": "X1", "role": "violinist"}]'}
    ) == []
    kept = subjects_from_metadata(
        {
            SUBJECTS_KEY: json.dumps(
                [
                    {"subject_id": "Q1", "role": "qin_player", "display_name": "张三"},
                    {"subject_id": "X1", "role": "violinist"},
                    {"subject_id": "E1"},
                    "junk",
                ],
                ensure_ascii=False,
            )
        }
    )
    assert [s.subject_id for s in kept] == ["Q1"]  # 非法条目逐条跳过，不抛

    # frozen 与两栏约束
    assert ROLES == ("qin_player", "erhu_player")  # 两栏，禁合并为「专家」
    with pytest.raises(dataclasses.FrozenInstanceError):
        subjects[0].role = "erhu_player"  # type: ignore[misc]
    with pytest.raises(ValueError):
        Subject(subject_id="X9", role="expert")


def test_blind_packet_has_no_display_name():
    """② 盲包全文检索 display_name 零命中（键 + 真名值双查），降级候选端披露。"""
    subjects = _subjects()
    packet = export_blind_packet(_model_with_runs(), subjects, packet_id="P1")
    text = json.dumps(packet, ensure_ascii=False)
    # 键零命中（M4 守门）
    assert "display_name" not in text
    assert all("display_name" not in rater for rater in packet["raters"])
    # 真名值零命中（防以别的键把真名带进包）
    for name in REAL_NAMES:
        assert name not in text
    # 包结构与匿名化口径
    assert packet["format"] == PACKET_FORMAT
    assert packet["version"] == 1
    assert packet["packet_id"] == "P1"
    assert packet["labels"] == list(BLIND_LABELS)
    assert packet["roles"] == list(ROLES)
    assert packet["raters"] == [
        {"rater_id": "Q1", "role": "qin_player"},
        {"rater_id": "E1", "role": "erhu_player"},
    ]
    # 候选端默认消费 CoreCandidate
    assert packet["candidate_source"] == "core_candidate"
    assert [seg["blind_segment_id"] for seg in packet["segments"]] == ["S0001"]
    # 不给机器判定（免锚定）
    assert all(set(seg) == {"blind_segment_id", "start_s", "end_s"} for seg in packet["segments"])

    # 降级：无 state_runs 的 PitchNote 列表 ⇒ PitchNote 口径并披露
    degraded = export_blind_packet(
        [PitchNote(start_s=0.0, end_s=0.5, f0_hz=440.0, conf=0.9)],
        subjects,
        packet_id="P2",
    )
    assert degraded["candidate_source"] == "pitch_note"
    assert len(degraded["segments"]) == 1
    assert "display_name" not in json.dumps(degraded, ensure_ascii=False)


def test_agreement_stats_hand_calc():
    """③ 一致率手算对拍（1.0／0.0／None）＋ 两栏分算＋盲判回读契约。"""
    packet = export_blind_packet(_model_with_runs(), _subjects(), packet_id="P1")
    candidates = [{"segment_id": "0.000-0.490", "label": "上趋"}]

    agree_rows = import_blind_responses(
        packet,
        [
            {"rater_id": "Q1", "blind_segment_id": "S0001", "label": "上趋", "note": ""},
            {"rater_id": "E1", "blind_segment_id": "S0001", "label": "上趋"},
        ],
    )
    assert agree_rows[0] == {
        "subject_id": "Q1",
        "role": "qin_player",
        "recording_id": "P1",
        "segment_id": "0.000-0.490",
        "blind_segment_id": "S0001",
        "label": "上趋",
        "note": "",
    }
    stats = agreement_stats(candidates, agree_rows)
    assert stats is not None
    assert stats["n_candidates"] == 1 and stats["n_responses"] == 2
    assert stats["n_matched"] == 2 and stats["n_agree"] == 2
    assert stats["agreement"] == pytest.approx(1.0)  # 手算 2/2
    assert stats["by_role"]["qin_player"]["agreement"] == pytest.approx(1.0)
    assert stats["by_role"]["erhu_player"]["agreement"] == pytest.approx(1.0)

    # 0.0：两栏都判「平直」，与机器「上趋」全不一致
    disagree_rows = import_blind_responses(
        packet,
        [
            {"rater_id": "Q1", "blind_segment_id": "S0001", "label": "平直"},
            {"rater_id": "E1", "blind_segment_id": "S0001", "label": "平直"},
        ],
    )
    stats0 = agreement_stats(candidates, disagree_rows)
    assert stats0["n_agree"] == 0
    assert stats0["agreement"] == pytest.approx(0.0)  # 手算 0/2

    # 分栏手算：一栏一致、一栏不一致 ⇒ 栏内 1.0 / 0.0，总值 1/2（跨栏参照）
    mixed = import_blind_responses(
        packet,
        [
            {"rater_id": "Q1", "blind_segment_id": "S0001", "label": "上趋"},
            {"rater_id": "E1", "blind_segment_id": "S0001", "label": "下趋"},
        ],
    )
    statsm = agreement_stats(candidates, mixed)
    assert statsm["by_role"]["qin_player"] == {"n": 1, "n_agree": 1, "agreement": 1.0}
    assert statsm["by_role"]["erhu_player"] == {"n": 1, "n_agree": 0, "agreement": 0.0}
    assert statsm["agreement"] == pytest.approx(0.5)

    # 零候选 / 零响应 ⇒ None（禁 0.0 冒充）
    assert agreement_stats([], agree_rows) is None
    assert agreement_stats(candidates, []) is None
    assert agreement_stats([], []) is None
    # 有数据但无匹配段 ⇒ None（诚实缺值）
    assert agreement_stats([{"segment_id": "9.999-9.999", "label": "上趋"}], agree_rows) is None

    # 回读契约：包外评者／包外段／标签越界一律 ValueError（禁静默丢行）
    with pytest.raises(ValueError):
        import_blind_responses(packet, [{"rater_id": "Z9", "blind_segment_id": "S0001", "label": "上趋"}])
    with pytest.raises(ValueError):
        import_blind_responses(packet, [{"rater_id": "Q1", "blind_segment_id": "S9999", "label": "上趋"}])
    with pytest.raises(ValueError):
        import_blind_responses(packet, [{"rater_id": "Q1", "blind_segment_id": "S0001", "label": "上扬"}])
    # 空响应 ⇒ 空列表（不抛）
    assert import_blind_responses(packet, []) == []
