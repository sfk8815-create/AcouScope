# SPDX-License-Identifier: GPL-3.0-only
"""W-14-01 腔核候选完整流程 v2 判据（``analysis/cavity_core_v2.py``）。

覆盖：① 同音级连续成组、不跨 degree、无 stable 运行不产候选；② 字段面
（帧占比/时长/稳定运行/中位 MAD/CI95/params/rejected）；③ 过滤参数为显式阈值、
未给即 ``not_applied``、被拒候选不进 ``candidates``；④ ``candidate_id`` 两次运行
逐字相同（确定性）；⑤ 旧 :func:`cavity_core.core_candidates` 行为不变。
"""

import pytest

from acouscope.analysis.cavity_core import core_candidates
from acouscope.analysis.cavity_core_v2 import (
    CANDIDATES_FORMAT,
    core_candidates_v2,
    export_candidates_json,
)
from acouscope.analysis.pitch_grid import PitchGridModel, PitchNote


def _note(start, end, *, degree, dev=0.0, conf=0.9, runs=None, head=None, tail=None,
          state="stable"):
    """构造一个段（runs 为 (起帧, 讫帧, 起秒, 讫秒, 态名)）。"""
    return PitchNote(
        start_s=float(start),
        end_s=float(end),
        f0_hz=220.0,
        conf=float(conf),
        state=state,
        state_runs=tuple(runs or ()),
        degree_index=degree,
        degree_deviation_cents=dev,
        head_deviation_cents=head,
        tail_deviation_cents=tail,
    )


def _model():
    """两段同音级相邻（成组）＋ 一段异音级 ＋ 一段无 stable run。"""
    return PitchGridModel(
        notes=[
            _note(0.0, 1.0, degree=3, dev=4.0, runs=[(0, 49, 0.0, 1.0, "stable")]),
            _note(
                1.1, 2.0, degree=3, dev=6.0,
                runs=[(50, 70, 1.1, 1.5, "attack"), (71, 94, 1.5, 2.0, "stable")],
                head=-3.0, tail=5.0,
            ),
            _note(6.0, 7.0, degree=7, dev=-2.0, runs=[(95, 125, 6.0, 7.0, "stable")]),
            _note(9.0, 10.0, degree=9, dev=1.0, runs=[(126, 146, 9.0, 10.0, "attack")]),
        ]
    )


def test_grouping_and_field_surface():
    """① 同音级成组、不跨 degree；字段面齐备且取值自洽。"""
    payload = core_candidates_v2(_model(), template="qin_lu", max_gap_s=0.5,
                                 recording_id="fixture")
    assert payload["format"] == CANDIDATES_FORMAT
    assert payload["filter_status"] == "not_applied"
    assert payload["n_rejected"] == 0
    assert payload["n_candidates"] == 2  # degree 3 组（2 段合一）＋ degree 7

    first = payload["candidates"][0]
    assert first["degree_index"] == 3
    assert first["start_s"] == pytest.approx(0.0)
    assert first["end_s"] == pytest.approx(2.0)      # 末段 stable 的讫秒
    assert first["duration_s"] == pytest.approx(2.0)
    assert first["n_stable_runs"] == 2
    assert len(first["stable_runs"]) == 2
    for start, end in first["stable_runs"]:
        assert first["start_s"] <= start <= end <= first["end_s"]
    assert 0.0 < first["frame_share"] <= 1.0
    assert first["median_ci95_cents"] is not None
    assert first["median_mad_cents"] is not None
    assert first["params"]["max_gap_s"] == pytest.approx(0.5)

    # 无 stable run 的组（degree 9）不产候选；每候选只在单一 degree 内
    assert all(c["degree_index"] in (3, 7) for c in payload["candidates"])
    assert payload["candidates"] == sorted(
        payload["candidates"], key=lambda c: (c["start_s"], c["candidate_id"])
    )


def test_no_degree_no_candidate_and_no_12tet_fallback():
    """④ 无 degree（未传律制）⇒ 不产候选；template 缺省 ⇒ 显式报错。"""
    model = PitchGridModel(
        notes=[_note(0.0, 1.0, degree=None, runs=[(0, 10, 0.0, 1.0, "stable")])]
    )
    payload = core_candidates_v2(model, template="qin_lu", max_gap_s=0.5)
    assert payload["candidates"] == []
    with pytest.raises(ValueError):
        core_candidates_v2(model, template="", max_gap_s=0.5)
    with pytest.raises(ValueError):
        core_candidates_v2(model, template="qin_lu", max_gap_s=None)


def test_filters_are_explicit_and_rejected_stay_out():
    """③ 过滤：显式阈值命中进 ``rejected``；不悄悄并入 ``candidates``。"""
    payload = core_candidates_v2(
        _model(), template="qin_lu", max_gap_s=0.5,
        min_frame_share=0.5, min_duration_s=1.5,
    )
    assert payload["filter_status"] == "applied"
    kept = {c["candidate_id"] for c in payload["candidates"]}
    rejected = {r["candidate_id"] for r in payload["rejected"]}
    assert kept and rejected
    assert kept.isdisjoint(rejected)
    assert all(r["reason"] in {
        "frame_share_below_min", "duration_below_min", "median_mad_above_max",
    } for r in payload["rejected"])


def test_candidate_id_deterministic():
    """④ 两次运行 ``candidate_id`` 逐字相同（内容定址，非时间戳）。"""
    a = core_candidates_v2(_model(), template="qin_lu", max_gap_s=0.5, recording_id="r1")
    b = core_candidates_v2(_model(), template="qin_lu", max_gap_s=0.5, recording_id="r1")
    assert [c["candidate_id"] for c in a["candidates"]] == [
        c["candidate_id"] for c in b["candidates"]
    ]
    # 换 recording_id ⇒ id 变（id 含录音标识，可跨例区分）
    c = core_candidates_v2(_model(), template="qin_lu", max_gap_s=0.5, recording_id="r2")
    assert [x["candidate_id"] for x in a["candidates"]] != [
        x["candidate_id"] for x in c["candidates"]
    ]


def test_legacy_core_candidates_unchanged():
    """⑤ 旧 ``core_candidates`` 行为不变（每 stable run 一个候选，语义零改动）。"""
    legacy = core_candidates(_model())
    assert len(legacy) == 3  # 3 个 stable run（degree 3 两段 + degree 7 一段）
    assert [c.start_s for c in legacy] == [0.0, 1.5, 6.0]
    new = core_candidates_v2(_model(), template="qin_lu", max_gap_s=0.5)
    assert new["n_candidates"] == 2  # 成组后合并为一个


def test_export_json(tmp_path):
    """JSON 导出可回读且字段齐（GUI／CLI 同一件面）。"""
    import json

    payload = core_candidates_v2(_model(), template="qin_lu", max_gap_s=0.5)
    path = export_candidates_json(payload, tmp_path / "candidates.json")
    back = json.loads(path.read_text(encoding="utf-8"))
    assert back["format"] == CANDIDATES_FORMAT
    assert len(back["candidates"]) == payload["n_candidates"]
    assert back["params"]["deviation_sample"]
    assert "只给候选，不给判定" in back["decision_scope"]
