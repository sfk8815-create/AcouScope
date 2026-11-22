# SPDX-License-Identifier: GPL-3.0-only
"""T-1117 数值表达式解析器：正例（算式/单位）+ 恶意面一律 None。"""

import math

import pytest

from acouscope.utils.number_expr import parse_number


@pytest.mark.parametrize("text,expect", [
    ("2*pi", 2 * math.pi),
    ("min(4,3)", 3.0),
    ("max(1, 2, 3)", 3.0),
    ("abs(-7)", 7.0),
    ("round(2.6)", 3.0),
    ("sqrt(9)", 3.0),
    ("(1+2)*3", 9.0),
    ("440*2**(1/12)", 440 * 2 ** (1 / 12)),
    ("-2.5", -2.5),
    ("1e3", 1000.0),
    (" 42 ", 42.0),
])
def test_arithmetic_ok(text, expect):
    got = parse_number(text)
    assert got is not None
    assert got == pytest.approx(expect, rel=1e-12)


@pytest.mark.parametrize("text,expect", [
    ("1.5k", 1500.0),
    ("1.5 K", 1500.0),
    ("3 kHz", 3000.0),
    ("50 ms", 0.05),
    ("10%", 0.1),
    ("1/3", 1 / 3),
    ("100 Hz", 100.0),
])
def test_units_ok(text, expect):
    assert parse_number(text) == pytest.approx(expect, rel=1e-12)


@pytest.mark.parametrize("bad", [
    "__import__('os')",
    "open('/etc/passwd')",
    "[i for i in range(3)]",
    "{'a': 1}",
    "a.b",
    "lambda: 1",
    "(1).__class__",
    "print(1)",
    "min(1,2, key=3)",
    "min(*[1,2])",
    "f'{1}'",
    "1 if 1 else 2",
    "x",
    "9**9**9",
    "1/0",
    "1,5",
    "",
    "   ",
    "2*",
    "_" * 80,
])
def test_rejects(bad):
    assert parse_number(bad) is None


def test_no_eval_in_source():
    """安全面自证：源文件不得出现 eval/compile/exec/__builtins__ 调用形式。"""
    from pathlib import Path

    import acouscope.utils.number_expr as mod

    import re

    src = Path(mod.__file__).read_text()
    for token in ("eval(", "exec(", "__builtins__"):
        assert token not in src, f"出现禁用形式：{token}"
    # re.compile 是正则编译，不算；裸 compile( 才算
    assert not re.search(r"(?<!re\.)\bcompile\(", src), "出现裸 compile("
