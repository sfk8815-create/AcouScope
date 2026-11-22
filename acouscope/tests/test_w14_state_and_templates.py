# SPDX-License-Identifier: GPL-3.0-only
"""W-14-02／W-14-05／W-14-06 判据（段内状态导出・模板来源・自定义音阶）。

只做单元级判据（合成模型／临时 .scl），不跑真实录音——真实夹具的运行件与
读数由 C 阶段独立复跑（见 `03_Docs_and_Assets/platform_w14_20261102/`）。
"""

import json

import pytest

from acouscope.analysis.cavity_type import STATE_ORDER, segment_features
from acouscope.analysis.pitch_grid import PitchGridModel, PitchNote
from acouscope.analysis.readout import (
    SEGMENT_CSV_FIELDS,
    SEGMENT_STATE_FIELDS,
    RecordingCase,
    segment_rows_csv,
    template_record,
)
from acouscope.analysis.tunings.scl import format_scl, parse_scl, save_scl
from acouscope.analysis.tunings.templates import (
    CUSTOM_PREFIX,
    get_template,
    get_tuning,
    is_custom_spec,
    list_paper_templates,
    list_templates,
    template_fingerprint,
    template_metadata,
)
from acouscope.analysis.tunings.tuning_system import TuningSystem
from acouscope.analysis.type_distribution import window_segment_rows


# ---------------------------------------------------------------------------
# W-14-02 段内状态与占比导出
# ---------------------------------------------------------------------------


def _state_model():
    """两段：一段 attack+stable+inter，一段无 state_runs（旧数据/simple 分段）。"""
    return PitchGridModel(
        notes=[
            PitchNote(
                start_s=0.0, end_s=1.0, f0_hz=220.0, conf=0.8, state="attack",
                state_runs=(
                    (0, 9, 0.0, 0.2, "attack"),
                    (10, 39, 0.2, 0.8, "stable"),
                    (40, 49, 0.8, 1.0, "inter"),
                ),
                degree_index=3, degree_deviation_cents=1.5,
            ),
            PitchNote(start_s=1.0, end_s=1.5, f0_hz=230.0, conf=0.7, state=""),
        ]
    )


def test_segment_state_fields_and_ratios():
    """① 七个字段齐备；占比和为 1；state 与 NoteSegment.state 逐字相同。"""
    rows = segment_features(_state_model())
    first, second = rows
    for key in SEGMENT_STATE_FIELDS:
        assert key in first and key in second
    assert first["state"] == "attack"                       # 逐字相同（首帧态）
    assert first["dominant_state"] == "stable"              # 40 帧里 30 帧 stable
    assert first["segment_type_signal"] == first["dominant_state"]
    assert len(first["state_runs"]) == 3
    total = first["attack_ratio"] + first["stable_ratio"] + first["inter_ratio"]
    assert abs(total - 1.0) < 1e-6
    assert first["attack_ratio"] == pytest.approx(0.2)
    assert first["stable_ratio"] == pytest.approx(0.6)
    # inter_ratio 如实输出（不因「HMM 常在 inter 收束」而删字段）
    assert first["inter_ratio"] == pytest.approx(0.2)
    assert first["state_frames"]["total"] == 50

    # 无 state_runs ⇒ 全 None（禁 0 回填）
    assert second["state"] is None
    assert second["dominant_state"] is None
    assert second["attack_ratio"] is None
    assert second["stable_ratio"] is None
    assert second["inter_ratio"] is None
    assert second["segment_type_signal"] is None
    assert second["state_runs"] == []


def test_dominant_state_tie_breaks_by_fixed_order():
    """② 并列时按 attack→stable→inter 固定序（不改 HMM 判定，只定导出规则）。"""
    from acouscope.analysis.cavity_type import _dominant_state

    assert STATE_ORDER == ("attack", "stable", "inter")
    assert _dominant_state({"attack": 5, "stable": 5, "inter": 0}) == "attack"
    assert _dominant_state({"attack": 0, "stable": 5, "inter": 5}) == "stable"
    assert _dominant_state({"attack": 0, "stable": 0, "inter": 0}) is None


def test_segment_rows_csv_and_window_rows():
    """③ 段行 CSV 列序定死；窗行透传状态字段（不改口径）。"""
    rows = window_segment_rows(_state_model())
    assert rows[0]["dominant_state"] == "stable"
    csv_rows = segment_rows_csv(rows)
    assert list(csv_rows[0]) == list(SEGMENT_CSV_FIELDS)
    # state_runs 以紧凑 JSON 文本落列（CSV 无嵌套类型）
    assert json.loads(csv_rows[0]["state_runs"]) == rows[0]["state_runs"]
    assert csv_rows[1]["state"] is None


# ---------------------------------------------------------------------------
# W-14-05 模板学术来源入运行记录
# ---------------------------------------------------------------------------


def test_template_record_carries_source_and_fingerprint():
    """④ 5 个字段齐备；qin_lu 来源含「黄翔鹏」与 1986；指纹 64 hex。"""
    block = template_record("qin_lu", recording_id="gq_liangxiaoyin_guanpinghu")
    assert block["template_key"] == "qin_lu"
    assert "黄翔鹏" in block["template_source"] and "1986" in block["template_source"]
    # 音级数＝隐含 1/1 之外的音数（qin_lu 9、三分损益 12）
    assert block["template_degree_count"] == get_template("qin_lu").degree_count == 9
    assert get_template("chinese_sanfen_sunyi_12").degree_count == 12
    assert len(block["template_fingerprint"]) == 64
    assert block["recording_id"] == "gq_liangxiaoyin_guanpinghu"
    # 三分损益来源可断言（A 应见要求）
    assert "三分损益" in get_template("chinese_sanfen_sunyi_12").source


def test_source_change_changes_fingerprint_and_run_id():
    """⑤ source 变 ⇒ 指纹变 ⇒ run_id 变；仅值不变时指纹不变（历史件不受影响）。"""
    base = get_template("qin_lu")
    altered = TuningSystem(
        name=base.name, source=base.source + "（来源改写对照）", degrees=base.degrees
    )
    assert template_fingerprint("qin_lu", base) == template_fingerprint("qin_lu", base)
    assert template_fingerprint("qin_lu", base) != template_fingerprint("qin_lu", altered)

    from acouscope.analysis.readout_extras import run_config_block
    from acouscope.analysis.type_distribution import run_descriptor, run_id

    def _rid(record):
        cfg = run_config_block(
            window_s=30.0, min_window_s=5.0, fmin=60.0, fmax=1500.0,
            segmenter="hmm", template="qin_lu", overlap_ratio=0.5, smooth_k=5,
            min_thr=10.0, tonic_window_s=30.0, tau_values=(None,), tau_analysis=None,
            ref_modes=("absolute",), templates=[record],
        )
        desc = run_descriptor(inputs=[], segment_source={}, tau_values=(None,),
                              ref_modes=("absolute",), config=cfg)
        return run_id(desc)

    assert _rid(template_record("qin_lu")) != _rid(
        template_metadata("qin_lu", tuning=altered)
    )


def test_template_metadata_key_enters_run_id():
    """⑤b **新键** ``config.template_metadata[]`` 直接进 ``run_id``。

    与 ⑤ 的区别：⑤ 走的是旧键 ``templates``；本测试只用新键，且**两配置其余
    逐字相同**（含 ``template`` 键），因此 ``run_id`` 的差异只能来自本键——
    证明 W-14-05 的来源面确实落在内容定址面上，而非只写在件里给人看。
    """
    from acouscope.analysis.readout_extras import run_config_block
    from acouscope.analysis.type_distribution import run_descriptor, run_id

    base = get_template("qin_lu")
    altered = TuningSystem(
        name=base.name, source=base.source + "（来源改写对照）", degrees=base.degrees
    )

    def _cfg(record) -> dict:
        return run_config_block(
            window_s=30.0, min_window_s=5.0, fmin=60.0, fmax=1500.0,
            segmenter="hmm", template="qin_lu", overlap_ratio=0.5, smooth_k=5,
            min_thr=10.0, tonic_window_s=30.0, tau_values=(None,), tau_analysis=None,
            ref_modes=("absolute",), template_metadata=[record],
        )

    def _rid(cfg: dict) -> str:
        desc = run_descriptor(
            inputs=[], segment_source={}, tau_values=(None,),
            ref_modes=("absolute",), config=cfg,
        )
        return run_id(desc)

    good = _cfg(template_metadata("qin_lu"))
    same = _cfg(template_metadata("qin_lu"))
    tampered = _cfg(template_metadata("qin_lu", tuning=altered))

    assert "template_metadata" in good                    # 新键出现
    assert "templates" not in good                        # 旧键缺省仍不出现
    assert good["template_metadata"][0]["template_fingerprint"] != (
        tampered["template_metadata"][0]["template_fingerprint"]
    )
    assert _rid(good) == _rid(same)                       # 同值 ⇒ 同 run_id
    assert _rid(good) != _rid(tampered)                   # 仅本键变 ⇒ 换 run_id


# ---------------------------------------------------------------------------
# W-14-06 自定义音阶保存/载入主分析路径
# ---------------------------------------------------------------------------

_FIVE = [0.0, 150.0, 350.0, 700.0, 1200.0]


def _custom_tuning():
    return TuningSystem.from_cents(
        name="自定义五音（测试）", source="用户提供（测试夹具）", cents=_FIVE[1:]
    )


def test_save_load_scl_roundtrip(tmp_path):
    """⑥ save→load 逐值差 ≤1e-6；文件为合法 .scl（可被 parse_scl 回读）。"""
    tuning = _custom_tuning()
    path = save_scl(tuning, tmp_path / "custom5.scl")
    text = path.read_text(encoding="utf-8")
    assert "2/1" in text and "!" in text
    scale = parse_scl(text)
    assert scale.note_count == len(tuning.degrees) - 1
    back = get_tuning(str(path))
    assert len(back.degrees) == len(tuning.degrees)
    assert max(abs(a - b) for a, b in zip(back.degrees, tuning.degrees)) <= 1e-6
    # 描述＝name、注释含 source
    assert tuning.name in text and "用户提供" in text
    # 末值为八度：写比值形，往返精确
    assert back.degrees[-1] == pytest.approx(1200.0, abs=1e-9)


def test_get_tuning_dispatch_and_no_fallback(tmp_path):
    """⑦ 内置 key／custom:／裸路径三路可判；未知 spec 显式报错（禁回退 12TET）。"""
    assert get_tuning("qin_lu").name == get_template("qin_lu").name
    path = save_scl(_custom_tuning(), tmp_path / "c5.scl")
    assert is_custom_spec(str(path)) and is_custom_spec(f"{CUSTOM_PREFIX}{path}")
    assert not is_custom_spec("qin_lu")
    for spec in (str(path), f"{CUSTOM_PREFIX}{path}"):
        tuning = get_tuning(spec)
        assert tuning.degree_count == 4
        assert "用户提供" in tuning.source
    with pytest.raises(KeyError):
        get_tuning("no_such_template")
    with pytest.raises(ValueError):
        get_tuning("")
    with pytest.raises((ValueError, FileNotFoundError)):
        get_tuning(str(tmp_path / "missing.scl"))


def test_custom_scl_record_and_case_spec(tmp_path):
    """⑧ 自定义音阶进记录：template_key 带 custom 前缀、带 .scl 文件哈希。"""
    path = save_scl(_custom_tuning(), tmp_path / "c5.scl")
    block = template_record(str(path), recording_id="case1")
    assert block["template_key"].startswith(CUSTOM_PREFIX)
    assert block["template_key"].endswith("c5.scl")
    assert block["template_custom"] is True
    assert len(block["template_sha256"]) == 64
    assert block["template_degree_count"] == 4
    # RecordingCase 接受 .scl 路径（与内置 key 同字段）
    case = RecordingCase(recording_id="case1", audio_path="x.wav", template=str(path))
    assert case.template == str(path)


def test_templates_table_untouched():
    """⑨ 模板表八项与 source 双向守卫（B6 前置；本单不得删/清空）。"""
    keys = list_templates()
    assert len(keys) == 8
    assert "indian_22_shruti" in keys and "arabic_24_tone" in keys
    assert len(list_paper_templates()) == 6
    assert all(get_template(key).source for key in keys)
    # format_scl 不改模板对象（纯写出）
    before = get_template("qin_lu").degrees
    format_scl(get_template("qin_lu"))
    assert get_template("qin_lu").degrees == before
