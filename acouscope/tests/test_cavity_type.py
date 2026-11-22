# SPDX-License-Identifier: GPL-3.0-only
"""腔格类型学检验件测试（B3-01 / PI-P5 第 2 棒）。CAVITY_TYPE_TEST_V1

覆盖（派活令 §判据）：
① 三型规则对拍 + 正对照（两类特征组合 → 不同标签），含 τ 占位常量未自设数值；
② 复合者（两侧倾向相反）→ "未分类"，且明细留字段（votes 与两个偏离值）；
③ 读数② 占比可算（手算对拍）、读数③ τ 翻转清单非空；
④ 读数①④ 交付形态 = value None + status machine_ready_data_pending；专家行到位
   时一致率算路可跑（**本文件内的专家行是算术夹具，不是任何真实专家判定**）；
⑤ 导出 json/csv 往返一致。

夹具一律手工构造 PitchNote（不跑 HMM、不跑真语料）：本棒检验语料（古琴吟猱＋
《二泉映月》）未到，本文件只验机器与契约。
"""

import json
import math

import pytest

from acouscope.analysis.cavity_type import (
    EXPERT_LABEL_SCHEMA,
    LABELS,
    STATUS_COMPUTED,
    STATUS_PENDING,
    TAU_CENTS_PLACEHOLDER,
    cavity_type_report,
    classify_cavity_type,
    classify_detail,
    segment_features,
    tau_sweep,
)
from acouscope.analysis.pitch_grid import PitchGridModel, PitchNote

# τ 扫描用的显式档位：**测试侧验算用**，非模块标定值（模块 τ 仍为占位 None）
TAU_STEPS = (None, 5.0, 15.0, 25.0)


def _note(start_s, end_s, head=None, tail=None, degree=None, deviation=None):
    """段级夹具：手工给定 head/tail 偏离（音分）与音级归属。"""
    return PitchNote(
        start_s=start_s,
        end_s=end_s,
        f0_hz=440.0,
        conf=0.9,
        state="stable",
        degree_index=degree,
        degree_deviation_cents=deviation,
        head_deviation_cents=head,
        tail_deviation_cents=tail,
    )


def _model():
    """六段夹具：上趋 2／下趋 1／平直 2／复合（未分类）1。

    - n1 head=-20 ⇒ head 侧上趋；
    - n2 head=+20 ⇒ head 侧下趋；
    - n3 双侧 0.0 ⇒ 平直；
    - n4 head=-8 且 tail=-8 ⇒ 上趋/下趋相反 ⇒ 复合 ⇒ 未分类；
    - n5 tail=+15 ⇒ tail 侧上趋；
    - n6 双侧 None ⇒ 平直（缺值不当作有向）。
    """
    return PitchGridModel(
        notes=[
            _note(0.0, 0.5, head=-20.0, degree=0, deviation=1.5),
            _note(0.6, 1.1, head=20.0, degree=2, deviation=-2.5),
            _note(1.2, 1.7, head=0.0, tail=0.0, degree=3, deviation=0.0),
            _note(1.8, 2.3, head=-8.0, tail=-8.0, degree=4, deviation=3.0),
            _note(2.4, 2.9, tail=15.0, degree=5, deviation=-1.0),
            _note(3.0, 3.5),
        ]
    )


def test_three_way_rules_and_positive_control():
    """① 三型规则对拍 + 正对照：同函数对不同特征组合给出不同标签。"""
    rows = segment_features(_model())
    labels = [classify_cavity_type(row) for row in rows]
    assert labels == ["上趋", "下趋", "平直", "未分类", "上趋", "平直"], labels
    # 正对照：两类特征组合 → 不同标签（防常量返回）
    assert classify_cavity_type(rows[0]) != classify_cavity_type(rows[1])
    assert len(set(labels)) >= 3

    # 规则出处（成文规则、禁概率/聚类）：docstring 载沈洽《音腔论》第三章 p.37
    from acouscope.analysis import cavity_type as mod

    assert "音腔论" in (mod.__doc__ or "")
    assert "p.37" in (mod.__doc__ or "")
    assert "操作化代理" in (mod.__doc__ or "")  # 段中位 ≠ 音腔本体

    # τ 只作占位：常量存在且未自设数值（待 P2 标定）
    assert TAU_CENTS_PLACEHOLDER is None

    # 未标定 ⇒ 按符号判（|Δ|>0 即计有向）；显式 τ（测试侧数值）按容差判
    assert classify_cavity_type({"head_deviation_cents": -0.5}) == "上趋"
    assert (
        classify_cavity_type({"head_deviation_cents": -20.0}, tau_cents=25.0) == "平直"
    )
    # 缺字段 / None / 非有限 ⇒ 平直，不抛
    assert classify_cavity_type({}) == "平直"
    assert classify_cavity_type({"head_deviation_cents": None, "tail_deviation_cents": None}) == "平直"
    assert classify_cavity_type({"head_deviation_cents": float("nan")}) == "平直"
    # 段 id 口径：起讫秒三位小数（专家行按此对齐）
    assert rows[0]["segment_id"] == "0.000-0.500"
    assert [row["segment_id"] for row in rows] == [
        "0.000-0.500",
        "0.600-1.100",
        "1.200-1.700",
        "1.800-2.300",
        "2.400-2.900",
        "3.000-3.500",
    ]


def test_composite_marked_unclassified_keeps_fields():
    """② 复合者 → "未分类" 并留字段（两侧倾向相反才算复合；同向不算）。"""
    detail = classify_detail({"head_deviation_cents": -20.0, "tail_deviation_cents": -20.0})
    assert detail["label"] == "未分类"
    assert detail["composite"] is True
    assert detail["head_vote"] == "上趋"
    assert detail["tail_vote"] == "下趋"
    assert detail["head_deviation_cents"] == -20.0
    assert detail["tail_deviation_cents"] == -20.0
    assert classify_cavity_type({"head_deviation_cents": -20.0, "tail_deviation_cents": -20.0}) == "未分类"
    # 另一复合方向：head 高（下趋）+ tail 高（上趋）
    other = classify_detail({"head_deviation_cents": 20.0, "tail_deviation_cents": 20.0})
    assert other["label"] == "未分类"
    assert (other["head_vote"], other["tail_vote"]) == ("下趋", "上趋")
    # 非复合同向对照：head 低 + tail 高 ⇒ 双方都指上趋 ⇒ 非复合
    same = classify_detail({"head_deviation_cents": -20.0, "tail_deviation_cents": 20.0})
    assert same["composite"] is False
    assert same["label"] == "上趋"

    # 报告内留字段：records 带 votes、composite 标志与两个偏离值
    report = cavity_type_report(_model())
    rec = [r for r in report["records"] if r["label"] == "未分类"]
    assert len(rec) == 1
    assert rec[0]["segment_id"] == "1.800-2.300"
    assert rec[0]["composite"] is True
    assert rec[0]["head_vote"] == "上趋"
    assert rec[0]["tail_vote"] == "下趋"
    assert rec[0]["head_deviation_cents"] == -8.0
    assert rec[0]["tail_deviation_cents"] == -8.0


def test_reading2_share_and_reading3_tau_flips():
    """③ 读数② 占比可算（手算对拍）＋ 读数③ τ 翻转清单非空。"""
    report = cavity_type_report(_model(), tau_values=TAU_STEPS)

    r2 = report["reading_2_composite_share"]
    assert r2["status"] == STATUS_COMPUTED
    value = r2["value"]
    assert value["n_segments"] == 6
    assert value["counts"] == {"上趋": 2, "下趋": 1, "平直": 2, "未分类": 1}
    assert value["n_composite"] == 1
    assert value["n_unclassified"] == 1
    assert value["share"]["未分类"] == pytest.approx(1 / 6)
    assert value["share"]["上趋"] == pytest.approx(2 / 6)
    assert value["share_unclassified"] == pytest.approx(1 / 6)
    assert value["share_composite"] == pytest.approx(1 / 6)
    assert math.isclose(sum(value["share"].values()), 1.0)

    r3 = report["reading_3_failure_boundary"]
    flips = r3["tau_flips"]
    assert flips["status"] == STATUS_COMPUTED
    assert flips["flip_count"] > 0, f"τ 扫描应出翻转（手算档位 {TAU_STEPS}）"
    assert flips["value"], "翻转清单不得为空"
    # 逐条翻转可核：τ 变大只会把「有向」压成「平直」，不会反向
    for item in flips["value"]:
        assert item["label_from"] != item["label_to"]
        assert item["label_to"] == "平直"
        assert abs(item["tau_from"] if item["tau_from"] is not None else 0.0) < abs(
            item["tau_to"] or 0.0
        )
    assert "0.000-0.500" in flips["unstable_segment_ids"]  # |Δh|=20 在 τ=25 档落平直
    assert "1.800-2.300" in flips["unstable_segment_ids"]  # |Δ|=8 在 τ=15 档落平直
    # 跨录音不稳：缺多录音 ⇒ pending
    assert r3["cross_recording_instability"]["status"] == STATUS_PENDING
    assert r3["cross_recording_instability"]["value"] is None

    # 单档扫（缺省 = 只按占位 τ）⇒ 无翻转（同档自身不产生翻转），且与②的标签一致
    single = cavity_type_report(_model())["reading_3_failure_boundary"]["tau_flips"]
    assert single["flip_count"] == 0
    assert single["labels_by_tau"]["None"] == [
        row["label"] for row in cavity_type_report(_model())["records"]
    ]

    # tau_sweep 直调：空模型 ⇒ 空清单不抛
    empty = tau_sweep(PitchGridModel(notes=[]), TAU_STEPS)
    assert empty["n_segments"] == 0 and empty["flips"] == [] and empty["flip_count"] == 0


def test_reading1_and_reading4_delivery_form():
    """④ 读数①④ 交付形态：无专家 ⇒ value=None + machine_ready_data_pending。"""
    report = cavity_type_report(_model())
    r1 = report["reading_1_agreement_band"]
    assert r1["value"] is None
    assert r1["status"] == STATUS_PENDING
    assert r1["n_expert_labels"] == 0
    assert r1["uncertainty_band"]["value"] is None
    assert r1["uncertainty_band"]["status"] == STATUS_PENDING
    assert set(EXPERT_LABEL_SCHEMA) <= set(r1["input_schema"])
    assert set(EXPERT_LABEL_SCHEMA) == {
        "subject_id",
        "role",
        "recording_id",
        "segment_id",
        "label",
        "note",
    }
    r4 = report["reading_4_cross_recording_stability"]
    assert r4["value"] is None
    assert r4["status"] == STATUS_PENDING
    assert r4["input_schema"], "读数④须交输入 schema"
    assert report["tau_cents"] is None  # τ 未自设数值
    assert report["labels"] == list(LABELS)
    assert report["roles"] == ["qin_player", "erhu_player"]  # 两栏，禁合并

    # 专家行到位时的算路（**合成算术夹具**，非真实专家判定）：一致率手算
    expert = [
        {
            "subject_id": "Q1",
            "role": "qin_player",
            "recording_id": "r1",
            "segment_id": "0.000-0.500",
            "label": "上趋",
            "note": "",
        },
        {
            "subject_id": "E1",
            "role": "erhu_player",
            "recording_id": "r1",
            "segment_id": "0.600-1.100",
            "label": "上趋",
            "note": "",
        },
    ]
    filled = cavity_type_report(_model(), expert=expert)["reading_1_agreement_band"]
    assert filled["status"] == STATUS_COMPUTED
    assert filled["n_expert_labels"] == 2
    value = filled["value"]
    assert value["n"] == 2 and value["n_agree"] == 1
    assert value["agreement"] == pytest.approx(0.5)
    assert value["by_role"]["qin_player"] == {"n": 1, "n_agree": 1, "agreement": 1.0}
    assert value["by_role"]["erhu_player"] == {"n": 1, "n_agree": 0, "agreement": 0.0}
    # 越界行被丢弃（label 越界 / role 未登记 / 段 id 不匹配不计入）
    bad = expert + [
        dict(expert[0], label="上扬"),
        dict(expert[0], role="expert"),
        dict(expert[0], segment_id="9.999-9.999"),
    ]
    bad_report = cavity_type_report(_model(), expert=bad)["reading_1_agreement_band"]
    # schema/枚举越界两行被丢弃（只剩合规 3 行），其中段 id 不匹配者不计入一致率
    assert bad_report["n_expert_labels"] == 3
    assert bad_report["value"]["n"] == 2
    assert bad_report["value"]["agreement"] == pytest.approx(0.5)


def test_export_json_csv_roundtrip(tmp_path):
    """⑤ 导出 json/csv 往返一致（复用既有导出口径，函数级追加）。"""
    from acouscope.annotation.export import (
        CAVITY_TYPE_FIELDS,
        export_cavity_types_csv,
        export_cavity_types_json,
    )

    report = cavity_type_report(_model(), tau_values=(None, 10.0))
    rows = report["records"]
    expect = [{key: row[key] for key in CAVITY_TYPE_FIELDS} for row in rows]

    json_path = tmp_path / "cavity_types.json"
    export_cavity_types_json(json_path, rows, tau_cents=report["tau_cents"])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["format"] == "acouscope-cavity-type-export"
    assert data["version"] == 2  # v2（2026-10-25）：补 ref_mode
    assert data["tau_cents"] is None
    assert data["fields"] == list(CAVITY_TYPE_FIELDS)
    assert "ref_mode" in CAVITY_TYPE_FIELDS
    assert {row["ref_mode"] for row in data["rows"]} == {"absolute"}
    assert data["rows"] == expect  # 往返全等（浮点 repr 可逆）

    csv_path = tmp_path / "cavity_types.csv"
    export_cavity_types_csv(csv_path, rows)
    import csv as _csv

    with open(csv_path, encoding="utf-8", newline="") as f:
        table = list(_csv.reader(f))
    assert table[0] == list(CAVITY_TYPE_FIELDS)
    assert len(table) - 1 == len(expect)
    for line, want in zip(table[1:], expect):
        for cell, key in zip(line, CAVITY_TYPE_FIELDS):
            value = want[key]
            if value is None:
                assert cell == ""  # 缺值写空串，禁以 0 冒充
            elif isinstance(value, float):
                assert float(cell) == value
            else:
                assert cell == str(value)
    # CSV 里 None 列确实存在（正对照：夹具含 None 值列）
    assert any(value is None for row in expect for value in row.values())


def test_repeat_degree_descriptive_only():
    """往复度第二轴：只描述形态（反转次数、峰峰），不产生标签、不增类型。"""
    import numpy as np

    from acouscope.analysis.cavity_type import repeat_degree

    t = np.arange(60) * 0.01
    vib_f0 = 440.0 * 2.0 ** (40.0 * np.sin(2 * np.pi * t / 0.3) / 1200.0)
    steady_f0 = np.full(60, 440.0)
    vib = PitchNote(
        start_s=0.0, end_s=0.59, f0_hz=440.0, conf=0.9, state="stable",
        state_runs=((0, 59, 0.0, 0.59, "stable"),),
    )
    steady = PitchNote(
        start_s=0.6, end_s=1.19, f0_hz=440.0, conf=0.9, state="stable",
        state_runs=((60, 119, 0.6, 1.19, "stable"),),
    )
    rows = repeat_degree(PitchGridModel(notes=[vib, steady]), np.concatenate([vib_f0, steady_f0]))
    assert [r["segment_id"] for r in rows] == ["0.000-0.590", "0.600-1.190"]
    assert rows[0]["turns"] >= 2
    assert rows[0]["peak2peak_cents"] > 60.0
    assert rows[1]["turns"] == 0
    assert rows[1]["peak2peak_cents"] < 1e-6
    assert all(set(r) == {"segment_id", "turns", "peak2peak_cents"} for r in rows)


def test_repeat_degree_keeps_labels_identical():
    """验收：加第二轴前后，三型判定逐位一致（一致率分母不变）。"""
    import numpy as np

    from acouscope.analysis.cavity_type import repeat_degree

    notes = [
        PitchNote(
            start_s=0.0, end_s=0.5, f0_hz=440.0, conf=0.9, state="stable",
            head_deviation_cents=-20.0, state_runs=((0, 49, 0.0, 0.5, "stable"),),
        ),
        PitchNote(
            start_s=0.6, end_s=1.1, f0_hz=440.0, conf=0.9, state="stable",
            head_deviation_cents=20.0, state_runs=((60, 109, 0.6, 1.1, "stable"),),
        ),
        PitchNote(
            start_s=1.2, end_s=1.7, f0_hz=440.0, conf=0.9, state="stable",
            head_deviation_cents=0.0, tail_deviation_cents=0.0,
            state_runs=((120, 169, 1.2, 1.7, "stable"),),
        ),
    ]
    model = PitchGridModel(notes=notes)

    def labels():
        return [
            classify_cavity_type(
                {
                    "head_deviation_cents": n.head_deviation_cents,
                    "tail_deviation_cents": n.tail_deviation_cents,
                },
                tau_cents=15.0,
            )
            for n in model.notes
        ]

    before = labels()
    repeat_degree(model, np.full(170, 440.0))
    after = labels()
    assert before == after == ["上趋", "下趋", "平直"]
