# SPDX-License-Identifier: GPL-3.0-only
"""`.scl` 解析器单元测试（T-918）。TUNINGS_SCL_TEST_V1

期望数据 = Huygens-Fokker 官方 .scl 格式说明页的合法文件样例 meanquar.scl
（https://www.huygens-fokker.org/scala/scl_format.html ），以字符串内联在测试内
（工作区无任何 .scl 样例文件，禁用下载/入库）。
"""

import math
from fractions import Fraction

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.tunings.scl import (  # noqa: E402
    KIND_CENTS,
    KIND_RATIO,
    parse_scl,
    parse_scl_file,
)

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


def test_meanquar_description_and_note_count():
    scale = parse_scl(MEANQUAR_SCL)
    assert scale.description == "1/4-comma meantone scale. Pietro Aaron's temperament (1523)"
    assert scale.note_count == 12
    assert len(scale.values) == 12


def test_meanquar_cents_entries_known_expectation():
    """官方样例的音分条目逐值核对（±1e-5，样例给到小数点后 5 位）。"""
    scale = parse_scl(MEANQUAR_SCL)
    cents_entries = [scale.values[0], scale.values[1], scale.values[2], scale.values[4]]
    expected = [76.04900, 193.15686, 310.26471, 503.42157]
    for value, want in zip(cents_entries, expected):
        assert value.kind == KIND_CENTS
        assert value.ratio is None
        assert value.cents == pytest.approx(want, abs=1e-5)


def test_meanquar_ratio_entries_use_exact_fraction():
    """比值条目：5/4、25/16、2/1 由 Fraction 承载并按 1200*log2 换算音分。"""
    scale = parse_scl(MEANQUAR_SCL)
    ratios = [(scale.values[3], Fraction(5, 4)), (scale.values[7], Fraction(25, 16))]
    for value, want_ratio in ratios:
        assert value.kind == KIND_RATIO
        assert value.ratio == want_ratio
        assert value.cents == pytest.approx(1200.0 * math.log2(float(want_ratio)), abs=1e-9)
    assert scale.values[3].cents == pytest.approx(386.3137138648348, abs=1e-9)
    assert scale.values[7].cents == pytest.approx(772.6274277296692, abs=1e-9)
    assert scale.values[11].ratio == Fraction(2, 1)
    assert scale.values[11].cents == pytest.approx(1200.0, abs=1e-9)


def test_meanquar_cent_sequence_from_scale():
    """cents() 返回 N 个音级（未含隐含 1/1），逐位与官方样例核对。"""
    scale = parse_scl(MEANQUAR_SCL)
    seq = list(scale.cents())
    assert len(seq) == 12
    want = [
        76.04900,
        193.15686,
        310.26471,
        386.3137138648348,
        503.42157,
        579.47057,
        696.57843,
        772.6274277296692,
        889.73529,
        1006.84314,
        1082.89214,
        1200.0,
    ]
    assert seq == pytest.approx(want, abs=1e-9)


def test_comments_and_blank_lines_are_skipped():
    text = "\n".join(
        [
            "! 文件头注释",
            "",
            "! 描述前的注释",
            "测试音阶",
            "",
            "! 音数前的注释",
            "2",
            "! 音高前的注释",
            "",
            "3/2",
            "2/1",
        ]
    )
    scale = parse_scl(text)
    assert scale.description == "测试音阶"
    assert scale.note_count == 2
    assert [value.ratio for value in scale.values] == [Fraction(3, 2), Fraction(2, 1)]


def test_missing_description_line_is_empty_string():
    """官方规则：无描述时应为空行（空行即空描述），不是跳过该行。"""
    scale = parse_scl("\n3\n3/2\n5/4\n2/1\n")
    assert scale.description == ""
    assert scale.note_count == 3


def test_integer_token_is_ratio_to_one():
    scale = parse_scl("整数比值\n3\n2\n5\n4\n")
    assert scale.values[0].kind == KIND_RATIO
    assert scale.values[0].ratio == Fraction(2, 1)
    assert scale.values[0].cents == pytest.approx(1200.0, abs=1e-9)
    assert scale.values[1].ratio == Fraction(5, 1)
    assert scale.values[1].cents == pytest.approx(1200.0 * math.log2(5.0), abs=1e-9)


def test_large_integer_numerator_and_denominator():
    """官方要求分子分母至少支持到 2^31-1（本实现用 Fraction + log2 精确承载）。"""
    scale = parse_scl("大整数\n1\n2147483647/2147483646\n")
    value = scale.values[0]
    assert value.ratio == Fraction(2147483647, 2147483646)
    assert value.cents == pytest.approx(1200.0 * math.log2(2147483647 / 2147483646), abs=1e-9)


def test_content_after_valid_pitch_value_is_ignored():
    """官方规则：一行内有效音高值之后的内容忽略（如 `100.0 C#`、`5/4 E\\`）。"""
    scale = parse_scl("行尾内容\n3\n 100.0 C#\n 5/4 E\\\n 408. \n")
    assert scale.values[0].cents == pytest.approx(100.0, abs=1e-9)
    assert scale.values[1].ratio == Fraction(5, 4)
    assert scale.values[2].cents == pytest.approx(408.0, abs=1e-9)


def test_ratio_smaller_than_one_and_negative_cents_are_accepted():
    """官方合法音高行示例：`10/20`（比值可小于 1）与 `-5.0`（负音分）。"""
    scale = parse_scl("边界样例\n2\n10/20\n-5.0\n")
    assert scale.values[0].ratio == Fraction(1, 2)
    assert scale.values[0].cents == pytest.approx(-1200.0, abs=1e-9)
    assert scale.values[1].kind == KIND_CENTS
    assert scale.values[1].cents == pytest.approx(-5.0, abs=1e-9)


def test_zero_note_count_is_allowed():
    """官方规则：音数下限为 0（1/1 隐含）。"""
    scale = parse_scl("空音阶\n0\n")
    assert scale.note_count == 0
    assert scale.values == ()
    assert scale.cents() == ()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "! 只有注释\n! 没有描述与音数\n",
    ],
)
def test_files_without_content_raise(text):
    with pytest.raises(ValueError):
        parse_scl(text)


@pytest.mark.parametrize(
    "text",
    [
        "-3/2\n",  # 负比值（官方：应报读错）
        "3/-2\n",
        "0/1\n",  # 零比值
        "5/0\n",
        "abc\n",  # 无斜杠非整数
        "3/2/4\n",  # 斜杠多于一个
        "700.0xyz\n",  # 非法音分
        "nan\n",
    ],
)
def test_invalid_pitch_lines_raise(text):
    with pytest.raises(ValueError):
        parse_scl(f"非法音高\n1\n{text}")


@pytest.mark.parametrize(
    "text",
    [
        "描述\n12.5\n",  # 音数非整数
        "描述\n-1\n",  # 音数负
        "描述\nx\n",
        "描述\n2\n3/2\n",  # 音高值不足
        "描述\n1\n3/2\n5/4\n",  # 音高值多于声明
        "描述\n",  # 缺音数行
    ],
)
def test_invalid_structure_raises(text):
    with pytest.raises(ValueError):
        parse_scl(text)


def test_extra_comments_after_values_are_tolerated():
    text = "描述\n1\n3/2\n! 文件尾注释\n\n"
    scale = parse_scl(text)
    assert scale.note_count == 1
    assert scale.values[0].ratio == Fraction(3, 2)


def test_parse_scl_rejects_non_string():
    with pytest.raises(ValueError):
        parse_scl(None)


def test_parse_scl_file_roundtrip_utf8(tmp_path):
    path = tmp_path / "meanquar.scl"
    path.write_text(MEANQUAR_SCL, encoding="utf-8")
    scale = parse_scl_file(path)
    assert scale.note_count == 12
    assert scale.cents() == pytest.approx(parse_scl(MEANQUAR_SCL).cents(), abs=1e-9)


def test_parse_scl_file_latin1_fallback(tmp_path):
    """官方脚注 1：文件可为 ASCII/Latin-1；非 UTF-8 内容按 Latin-1 回退读取。"""
    path = tmp_path / "latin1.scl"
    path.write_bytes("caf\xe9 \xe4\xf6\xfc\n1\n3/2\n".encode("latin-1"))
    scale = parse_scl_file(path)
    assert scale.description == "café äöü"
    assert scale.values[0].ratio == Fraction(3, 2)


def test_parse_scl_file_bom_is_ignored(tmp_path):
    path = tmp_path / "bom.scl"
    path.write_text("\ufeff描述\n1\n3/2\n", encoding="utf-8")
    assert parse_scl_file(path).description == "描述"


def test_parse_scl_file_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        parse_scl_file("/nonexistent/path/to/scale.scl")
