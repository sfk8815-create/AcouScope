# SPDX-License-Identifier: GPL-3.0-only
"""内置音律模板与 .scl 加载单元测试（T-918）。TUNINGS_TEMPLATES_TEST_V1

口径：每个模板 source 必填且标注学术出处（R8），不出现“符合/覆盖标准”类表述；
模板音级序列自 1/1（0 音分）到 2/1（1200 音分）升序。
"""

import math
from fractions import Fraction

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.tunings.templates import (  # noqa: E402
    TEMPLATE_KEYS,
    TEMPLATES,
    get_template,
    list_templates,
    load_scl,
)
from acouscope.analysis.tunings.tuning_system import TuningSystem  # noqa: E402

MEANQUAR_SCL = """! meanquar.scl
!
1/4-comma meantone scale. Pietro Aaron's temperament (1523)
 12
!
 76.04900
 193.15686
 310.26471
 5/4
 503.42157
 579.47057
 696.57843
 25/16
 889.73529
 1006.84314
 1082.89214
 2/1
"""

EXPECTED_KEYS = (
    "12tet",
    "just_major",
    "pythagorean_diatonic",
    "quarter_comma_meantone",
    "chinese_sanfen_sunyi_12",
    "indian_22_shruti",
    "arabic_24_tone",
)

FORBIDDEN_PHRASES = ("符合", "覆盖", "认证", "合规")


def test_template_keys_and_lookup():
    assert list_templates() == list(EXPECTED_KEYS)
    assert TEMPLATE_KEYS == EXPECTED_KEYS
    assert set(TEMPLATES) == set(EXPECTED_KEYS)
    for key in EXPECTED_KEYS:
        assert isinstance(get_template(key), TuningSystem)
        assert TEMPLATES[key] is get_template(key)


def test_unknown_template_key_raises():
    with pytest.raises(KeyError):
        get_template("no_such_tuning")


@pytest.mark.parametrize("key", EXPECTED_KEYS)
def test_every_template_has_source_and_ascending_degrees(key):
    tuning = get_template(key)
    assert tuning.name
    assert tuning.source
    assert "R8" in tuning.source  # 学术出处（RESEARCH_JOURNAL R8）标注
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in tuning.source
        assert phrase not in tuning.name
    assert tuning.degrees[0] == 0.0
    assert tuning.degrees[-1] == pytest.approx(1200.0, abs=1e-9)
    assert tuning.is_octave_repeating is True
    assert list(tuning.degrees) == sorted(tuning.degrees)
    assert tuning.degree_to_freq(0) == pytest.approx(tuning.reference_freq, rel=1e-12)


@pytest.mark.parametrize(
    "key,expected_count",
    [
        ("12tet", 12),
        ("just_major", 7),
        ("pythagorean_diatonic", 7),
        ("quarter_comma_meantone", 12),
        ("chinese_sanfen_sunyi_12", 12),
        ("indian_22_shruti", 22),
        ("arabic_24_tone", 24),
    ],
)
def test_template_degree_counts(key, expected_count):
    assert get_template(key).degree_count == expected_count


def test_twelve_tet_is_100_cent_grid():
    tuning = get_template("12tet")
    assert tuning.degrees[1] == pytest.approx(100.0, abs=1e-12)
    assert tuning.degree_to_cents(7) == pytest.approx(700.0, abs=1e-12)
    assert tuning.cents_to_degree(160.0) == 2
    assert tuning.cents_to_degree(140.0) == 1
    assert tuning.degree_to_freq(12) == pytest.approx(880.0, rel=1e-12)


def test_just_major_is_five_limit_ratios():
    tuning = get_template("just_major")
    assert tuning.degree_to_cents(2) == pytest.approx(386.3137138648348, abs=1e-9)  # 5/4
    assert tuning.degree_to_cents(4) == pytest.approx(701.9550008653874, abs=1e-9)  # 3/2
    assert tuning.degree_to_cents(6) == pytest.approx(1088.2687147302222, abs=1e-9)  # 15/8


def test_pythagorean_diatonic_is_three_limit_chain():
    tuning = get_template("pythagorean_diatonic")
    assert tuning.degree_to_cents(1) == pytest.approx(203.91000173077484, abs=1e-9)  # 9/8
    assert tuning.degree_to_cents(3) == pytest.approx(498.0449991346125, abs=1e-9)  # 4/3
    assert tuning.degree_to_cents(5) == pytest.approx(905.8650025961623, abs=1e-9)  # 27/16


def test_quarter_comma_meantone_matches_official_sample():
    tuning = get_template("quarter_comma_meantone")
    assert tuning.name.startswith("1/4-comma meantone")
    assert tuning.degree_to_cents(1) == pytest.approx(76.04900, abs=1e-9)
    assert tuning.degree_to_cents(4) == pytest.approx(386.3137138648348, abs=1e-9)
    assert tuning.degree_to_cents(8) == pytest.approx(772.6274277296692, abs=1e-9)  # 25/16
    assert tuning.degree_to_cents(9) == pytest.approx(889.73529, abs=1e-9)  # A
    assert tuning.degree_to_cents(12) == pytest.approx(1200.0, abs=1e-9)
    assert tuning.degree_to_freq(4) == pytest.approx(550.0, rel=1e-9)


def test_chinese_twelve_lu_is_pythagorean_twelve_class_set():
    """三分损益十二律＝3/2 相生十二次的 3-limit 音级集合。

    独立对照：测试内直接枚举 3 的幂次比值（Fraction 精确）折八度后排序，
    与模板音级逐位比较；另核对 大吕（2187/2048）与 林钟（3/2）音分。
    """
    tuning = get_template("chinese_sanfen_sunyi_12")
    lattice = []
    for exponent in range(1, 12):  # 相生 1~11 次的非零音级（0 度 1/1 隐含、2/1 收尾）
        ratio = Fraction(3, 2) ** exponent
        while ratio >= 2:
            ratio /= 2
        while ratio < 1:
            ratio *= 2
        lattice.append(1200.0 * math.log2(ratio.numerator / ratio.denominator))
    lattice.append(1200.0)
    lattice.sort()
    actual = list(tuning.degrees[1:13])
    assert actual == pytest.approx(lattice, abs=1e-9)
    assert tuning.degree_to_cents(1) == pytest.approx(113.68500605771192, abs=1e-9)  # 大吕
    assert tuning.degree_to_cents(7) == pytest.approx(701.9550008653874, abs=1e-9)  # 林钟


def test_indian_22_shruti_sampling_is_equal_division():
    tuning = get_template("indian_22_shruti")
    assert tuning.degree_to_cents(1) == pytest.approx(1200.0 / 22, abs=1e-9)
    assert tuning.degree_to_cents(11) == pytest.approx(600.0, abs=1e-9)
    assert tuning.degree_to_cents(22) == pytest.approx(1200.0, abs=1e-9)
    assert "等程采样" in tuning.source


def test_arabic_24_tone_sampling_is_equal_division():
    tuning = get_template("arabic_24_tone")
    assert tuning.degree_to_cents(1) == pytest.approx(50.0, abs=1e-12)
    assert tuning.degree_to_cents(12) == pytest.approx(600.0, abs=1e-12)
    assert "等程采样" in tuning.source


def test_load_scl_from_user_file(tmp_path):
    path = tmp_path / "meanquar.scl"
    path.write_text(MEANQUAR_SCL, encoding="utf-8")
    tuning = load_scl(path)
    assert isinstance(tuning, TuningSystem)
    assert tuning.degree_count == 12
    assert tuning.name == "1/4-comma meantone scale. Pietro Aaron's temperament (1523)"
    assert "meanquar.scl" in tuning.source
    assert "用户提供" in tuning.source


def test_load_scl_accepts_name_source_and_reference_override(tmp_path):
    path = tmp_path / "meanquar.scl"
    path.write_text(MEANQUAR_SCL, encoding="utf-8")
    tuning = load_scl(
        path,
        source="Huygens-Fokker 官方 .scl 格式说明页样例",
        name="中庸律（四分一 comma）",
        reference_freq=442.0,
    )
    assert tuning.name == "中庸律（四分一 comma）"
    assert tuning.source == "Huygens-Fokker 官方 .scl 格式说明页样例"
    assert tuning.degree_to_freq(0) == pytest.approx(442.0, rel=1e-12)


def test_load_scl_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_scl(tmp_path / "absent.scl")


def test_templates_are_immutable_and_shareable():
    tuning = get_template("12tet")
    with pytest.raises(Exception):
        tuning.name = "改名"  # type: ignore[misc]
