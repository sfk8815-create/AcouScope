# SPDX-License-Identifier: GPL-3.0-only
"""T-1081 Tips 目录守卫测试。

断言：tip.1..60 三语齐全无缺译回退；无 tip.61+ 孤儿编号键；
main_window 轮播取键范围与目录一致（_tip_keys 长度 == 60）。
"""

import re
from pathlib import Path

import pytest

from acouscope.i18n import _STRINGS, get_language, set_language, tr

LANGS = ("en_US", "zh_CN", "zh_TW")
MAIN_PY = Path(__file__).resolve().parent.parent / "src" / "acouscope" / "ui" / "main_window.py"


def _numbered_tip_keys():
    pat = re.compile(r"^tip\.(\d+)$")
    return {int(m.group(1)): k for k in _STRINGS if (m := pat.match(k))}


@pytest.fixture
def restore_lang():
    saved = get_language()
    yield
    set_language(saved)


def test_tip_catalog_is_exactly_1_to_60():
    assert set(_numbered_tip_keys()) == set(range(1, 61))


@pytest.mark.parametrize("n", range(1, 61))
def test_each_tip_has_all_three_languages(restore_lang, n):
    entry = _STRINGS[f"tip.{n}"]
    assert set(entry) >= set(LANGS), f"tip.{n} 缺语言键"
    for lang in LANGS:
        assert entry[lang].strip(), f"tip.{n} [{lang}] 为空"


@pytest.mark.parametrize("n", range(1, 61))
def test_tr_returns_translation_not_key(restore_lang, n):
    for lang in LANGS:
        set_language(lang)
        text = tr(f"tip.{n}")
        assert text and text != f"tip.{n}", f"tip.{n} [{lang}] 缺译/回退为键名"


def test_tip56_zhtw_typo_fixed():
    assert "一併" in _STRINGS["tip.56"]["zh_TW"]
    assert "ㄢ" not in _STRINGS["tip.56"]["zh_TW"]


def test_no_legacy_tips_above_60():
    assert not [k for k in _STRINGS if re.match(r"^tip\.(6[1-9]|[7-9]\d|1\d\d)$", k)]


def test_carousel_tip_keys_length_60():
    src = MAIN_PY.read_text(encoding="utf-8")
    m = re.search(r'self\._tip_keys = \[f"tip\.\{i\}" for i in range\(1, (\d+)\)\]', src)
    assert m, "未找到轮播取键语句"
    tip_keys = [f"tip.{i}" for i in range(1, int(m.group(1)))]
    assert len(tip_keys) == 60
    assert all(k in _STRINGS for k in tip_keys), "轮播取键与目录不一致"
