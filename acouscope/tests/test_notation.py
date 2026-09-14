# SPDX-License-Identifier: GPL-3.0-only
"""工尺谱 / 简谱 谱名映射层单元测试（T-923）。NOTATION_TEST_V1

口径：纯计算、无 Qt；七声等八度音律给出 1–7 / 上尺工凡六五乙 记名（含八度修饰）；
十二音音律按七声骨架记名（骨架外音级简谱加升降号、工尺谱显式不适用）；
非七声/非八度音律 applicable=False 且 note 非空（禁硬凑）；
每个 NoteName.cents 与 tuning.degree_to_cents 一致；映射表逐条附文献依据。
本文件不含背书类表述（静态断言见文件末），品牌禁词 0（拼接构造自扫）。
"""

import math
import re
from pathlib import Path

import pytest

from acouscope.analysis.tunings.notation import (
    MAPPING_SOURCES,
    NoteName,
    available_systems,
    degree_to_name,
)
from acouscope.analysis.tunings.templates import TEMPLATE_KEYS, get_template
from acouscope.analysis.tunings.tuning_system import TuningSystem

# 八度记号（与实现约定一致：组合上/下加点）
UP = "\u0307"
DOWN = "\u0323"

SEVEN_DEGREE_KEYS = ("just_major", "pythagorean_diatonic")
TWELVE_DEGREE_KEYS = ("12tet", "quarter_comma_meantone", "chinese_sanfen_sunyi_12")
# 三个十二音模板的七声骨架音级下标（与十二平均律大调七声位置的最近对应）
TWELVE_SKELETON = (0, 2, 4, 5, 7, 9, 11)

JIANPU_7 = ("1", "2", "3", "4", "5", "6", "7")
GONGCHE_7 = ("上", "尺", "工", "凡", "六", "五", "乙")


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# 1. 体系出口与入参校验


def test_available_systems_and_unknown_system():
    assert available_systems() == ("jianpu", "gongche")
    with pytest.raises(ValueError):
        degree_to_name(get_template("12tet"), 0, system="staff")


def test_argument_type_validation():
    tuning = get_template("12tet")
    with pytest.raises(TypeError):
        degree_to_name(tuning, "3")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        degree_to_name(tuning, True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        degree_to_name(tuning, 0, tonic_degree=1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        degree_to_name(object(), 0)  # type: ignore[arg-type]


def test_note_name_invariants():
    with pytest.raises(ValueError):
        NoteName("shakuhachi", "x", 0, 0, 0.0, True, "")
    with pytest.raises(ValueError):
        NoteName("jianpu", "", 0, 0, 0.0, False, "")
    with pytest.raises(ValueError):
        NoteName("jianpu", "1", 0, 0, 0.0, False, "原因")
    with pytest.raises(TypeError):
        NoteName("jianpu", "1", 0, 0.5, 0.0, True, "")  # type: ignore[arg-type]


# 2. 七声模板：简谱


@pytest.mark.parametrize("key", SEVEN_DEGREE_KEYS)
def test_jianpu_seven_degrees_use_digits(key):
    tuning = get_template(key)
    for degree, expected in enumerate(JIANPU_7):
        result = degree_to_name(tuning, degree)
        assert result.applicable is True
        assert result.system == "jianpu"
        assert result.text == expected
        assert result.octave_offset == 0
        assert result.note == ""
        assert result.cents == pytest.approx(tuning.degree_to_cents(degree))


@pytest.mark.parametrize("key", SEVEN_DEGREE_KEYS)
def test_jianpu_octave_marks(key):
    tuning = get_template(key)
    assert degree_to_name(tuning, 7).text == "1" + UP
    assert degree_to_name(tuning, 7).octave_offset == 1
    assert degree_to_name(tuning, 14).text == "1" + UP * 2
    assert degree_to_name(tuning, 14).octave_offset == 2
    assert degree_to_name(tuning, -1).text == "7" + DOWN
    assert degree_to_name(tuning, -1).octave_offset == -1
    assert degree_to_name(tuning, -8).text == "7" + DOWN * 2
    assert degree_to_name(tuning, -8).octave_offset == -2


def test_jianpu_relative_to_non_zero_tonic():
    tuning = get_template("just_major")  # 音级 4 = 3/2 = 701.96 音分（主音）
    assert degree_to_name(tuning, 4, tonic_degree=4).text == "1"
    assert degree_to_name(tuning, 4, tonic_degree=4).octave_offset == 0
    # 主音上方：la(5) / ti(6) / re(8 = 主音上方五度) / mi(9)
    assert degree_to_name(tuning, 5, tonic_degree=4).text == "2"
    assert degree_to_name(tuning, 6, tonic_degree=4).text == "3"
    assert degree_to_name(tuning, 8, tonic_degree=4).text == "5"
    assert degree_to_name(tuning, 9, tonic_degree=4).text == "6"
    # 主音下方（同一均之内为 do/fa，其下各音归入低八度）
    assert degree_to_name(tuning, 3, tonic_degree=4).text == "7" + DOWN
    assert degree_to_name(tuning, 0, tonic_degree=4).text == "4" + DOWN
    assert degree_to_name(tuning, 0, tonic_degree=4).octave_offset == -1
    assert degree_to_name(tuning, 7, tonic_degree=4).text == "4"
    assert degree_to_name(tuning, 7, tonic_degree=4).octave_offset == 0
    assert degree_to_name(tuning, 1, tonic_degree=4).text == "5" + DOWN
    assert degree_to_name(tuning, 1, tonic_degree=4).octave_offset == -1
    # 主音按音级数取模：主音 -3 与主音 4 等价（7 声音律）
    assert degree_to_name(tuning, 3, tonic_degree=-3).text == "7" + DOWN


# 3. 七声模板：工尺谱


@pytest.mark.parametrize("key", SEVEN_DEGREE_KEYS)
def test_gongche_seven_names_and_octaves(key):
    tuning = get_template(key)
    for degree, expected in enumerate(GONGCHE_7):
        result = degree_to_name(tuning, degree, system="gongche")
        assert result.applicable is True
        assert result.text == expected
        assert result.octave_offset == 0
    assert degree_to_name(tuning, 7, system="gongche").text == "亻上"
    assert degree_to_name(tuning, 7, system="gongche").octave_offset == 1
    assert degree_to_name(tuning, 8, system="gongche").text == "亻尺"
    assert degree_to_name(tuning, 14, system="gongche").text == "亻亻上"
    assert degree_to_name(tuning, 14, system="gongche").octave_offset == 2
    # 低八度三音用传统专用字 合 四 一（徵/羽/变宫的低八度）
    assert degree_to_name(tuning, -1, system="gongche").text == "一"
    assert degree_to_name(tuning, -2, system="gongche").text == "四"
    assert degree_to_name(tuning, -3, system="gongche").text == "合"
    assert degree_to_name(tuning, -1, system="gongche").octave_offset == -1
    # 低八度的 上尺工凡 以曳尾记号（本层以组合下点承载）
    assert degree_to_name(tuning, -4, system="gongche").text == "凡" + DOWN
    assert degree_to_name(tuning, -4, system="gongche").octave_offset == -1
    assert degree_to_name(tuning, -8, system="gongche").text == "乙" + DOWN * 2
    assert degree_to_name(tuning, -8, system="gongche").octave_offset == -2


def test_gongche_relative_to_non_zero_tonic():
    tuning = get_template("just_major")
    assert degree_to_name(tuning, 4, system="gongche", tonic_degree=4).text == "上"
    assert degree_to_name(tuning, 0, system="gongche", tonic_degree=4).text == "凡" + DOWN
    assert degree_to_name(tuning, 7, system="gongche", tonic_degree=4).text == "凡"
    assert degree_to_name(tuning, 8, system="gongche", tonic_degree=4).text == "六"
    assert degree_to_name(tuning, 8, system="gongche", tonic_degree=4).octave_offset == 0
    # 主音下方五度 = 低八度徵，用传统低音字「合」
    assert degree_to_name(tuning, 1, system="gongche", tonic_degree=4).text == "合"
    assert degree_to_name(tuning, 1, system="gongche", tonic_degree=4).octave_offset == -1


# 4. 十二音等八度音律：七声骨架 + 升降


def test_twelve_tone_jianpu_uses_digits_with_accidentals():
    tuning = get_template("12tet")
    expected = ("1", "#1", "2", "#2", "3", "4", "#4", "5", "#5", "6", "#6", "7")
    for degree, text in enumerate(expected):
        result = degree_to_name(tuning, degree)
        assert result.applicable is True, degree
        assert result.text == text, degree
        assert result.octave_offset == 0
    assert degree_to_name(tuning, 12).text == "1" + UP
    assert degree_to_name(tuning, 12).octave_offset == 1


def test_twelve_tone_gongche_denies_chromatic_degrees():
    tuning = get_template("12tet")
    for degree, text in zip(TWELVE_SKELETON, GONGCHE_7):
        result = degree_to_name(tuning, degree, system="gongche")
        assert result.applicable is True
        assert result.text == text
    assert degree_to_name(tuning, 12, system="gongche").text == "亻上"
    for degree in (1, 3, 6, 8, 10):
        result = degree_to_name(tuning, degree, system="gongche")
        assert result.applicable is False, degree
        assert result.text == ""
        assert result.note
        assert "工尺谱" in result.note


# 骨架外音级在各模板中的记名（按该音律自身音分与最近骨架音级的偏差方向定升降）
CHROMATIC_EXPECTED = {
    "quarter_comma_meantone": {1: "#1", 3: "b3", 6: "#4", 8: "#5", 10: "b7"},
    "chinese_sanfen_sunyi_12": {1: "b2", 3: "b3", 6: "b5", 8: "b6", 10: "b7"},
}


@pytest.mark.parametrize("key", tuple(CHROMATIC_EXPECTED))
def test_twelve_tone_unequal_templates_use_same_skeleton(key):
    tuning = get_template(key)
    for index, degree in enumerate(TWELVE_SKELETON):
        result = degree_to_name(tuning, degree)
        assert result.applicable is True
        assert result.text == JIANPU_7[index]
        assert result.octave_offset == 0
        assert result.cents == pytest.approx(tuning.degree_to_cents(degree))
    # 骨架外音级：简谱给升降号 + note 注明实际音分偏差（不折算为十二平均律值）
    for degree, text in CHROMATIC_EXPECTED[key].items():
        chromatic = degree_to_name(tuning, degree)
        assert chromatic.applicable is True, degree
        assert chromatic.text == text, degree
        assert "骨架" in chromatic.note and "音分" in chromatic.note
        # 工尺谱对骨架外音级显式不适用（不臆造升降谱字）
        denied = degree_to_name(tuning, degree, system="gongche")
        assert denied.applicable is False
        assert denied.text == ""
        assert denied.note


def test_twelve_tone_tonic_off_skeleton_is_inapplicable():
    tuning = get_template("12tet")
    result = degree_to_name(tuning, 1, tonic_degree=1)  # 主音为骨架外的升降音级
    assert result.applicable is False
    assert result.text == ""
    assert "骨架" in result.note


# 5. 非七声 / 非八度：显式不适用（禁硬凑）


@pytest.mark.parametrize("key", ("indian_22_shruti", "arabic_24_tone"))
@pytest.mark.parametrize("system", ("jianpu", "gongche"))
def test_non_heptatonic_templates_are_inapplicable(key, system):
    tuning = get_template(key)
    for degree in (0, 1, 5, tuning.degree_count - 1):
        result = degree_to_name(tuning, degree, system=system)
        assert result.applicable is False
        assert result.text == ""
        assert result.octave_offset == 0
        assert str(tuning.degree_count) in result.note
        assert result.cents == pytest.approx(tuning.degree_to_cents(degree))


def test_non_octave_repeating_is_inapplicable():
    tuning = TuningSystem.from_cents("非八度示意音阶", "单元测试构造（非文献音律）", [100.0, 300.0])
    assert tuning.is_octave_repeating is False
    result = degree_to_name(tuning, 1)
    assert result.applicable is False
    assert result.text == ""
    assert "八度" in result.note


# 6. 一致性与文献依据


def test_cents_always_match_tuning_system():
    for key in TEMPLATE_KEYS:
        tuning = get_template(key)
        for degree in range(-3, 16):
            for system in available_systems():
                result = degree_to_name(tuning, degree, system=system)
                assert result.cents == pytest.approx(tuning.degree_to_cents(degree))
                assert result.degree == degree
                assert result.system == system
                assert result.applicable is True or result.text == ""


def test_mapping_sources_are_declared_per_entry():
    assert MAPPING_SOURCES, "映射表须逐条附文献依据"
    for item in MAPPING_SOURCES:
        assert len(item) == 3
        identifier, claim, source = item
        assert identifier and claim and source
        assert "http" in source, identifier
        assert len(claim) > 20, identifier


def test_static_no_standard_claim_and_no_banned_words():
    root = Path(__file__).resolve().parents[1]
    targets = [root / "src" / "acouscope" / "analysis" / "tunings" / "notation.py", Path(__file__)]
    banned = ("M" + "elodyne", "Rea" + "per", "Sonic " + "Visualiser")
    claimed = ("".join(["符", "合"]), "".join(["覆盖", "标准"]))
    for path in targets:
        src = _src(path)
        for word in banned:
            assert word.lower() not in src.lower(), f"{path.name} 命中禁词"
        for phrase in claimed:
            assert phrase not in src, f"{path.name} 出现背书类表述"
        assert "QD" + "ialog" not in src, f"{path.name} 不得新建对话框"
        hex_color = re.compile("#[0-9a-fA-F]{6}")
        assert not hex_color.search(src), f"{path.name} 不得含硬编码颜色"


def test_float_boundary_octave_offsets_are_consistent():
    """八度边界上的浮点归位：偏移与记名必须自洽。"""
    tuning = get_template("just_major")
    result = degree_to_name(tuning, 7)
    assert result.octave_offset == 1
    assert math.isclose(result.cents - tuning.degree_to_cents(0), 1200.0)
    assert result.text == "1" + UP
