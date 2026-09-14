# SPDX-License-Identifier: GPL-3.0-only
"""T-1024 回归守卫：语谱图控件源码不得含第三类禁词（历史注释已清理，防止复发）。

词面量一律拼接构造，避免守卫文件自身被静态扫描命中。
"""

from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "acouscope"

_TARGET = _SRC_DIR / "ui" / "widgets" / "spectrogram.py"

# 第三类禁词（同领域科研音频竞品名）：拼接构造，禁止写成完整字面量
_BANNED = (
    "M" + "elodyne",
    "Rea" + "per",
    "Sonic " + "Visualiser",
)


def _variants(word: str):
    """覆盖大小写变体。"""
    return (word, word.lower(), word.upper(), word.title())


def test_spectrogram_source_has_no_banned_words():
    assert _TARGET.exists(), f"源文件缺失：{_TARGET}"
    src = _TARGET.read_text(encoding="utf-8")
    low = src.lower()
    for word in _BANNED:
        for variant in _variants(word):
            assert variant.lower() not in low, f"spectrogram.py 命中第三类禁词（{variant}）"


def test_guard_itself_has_no_banned_literal():
    """守卫文件自身也必须 0 命中（词面量仅以拼接形式存在）。"""
    this = Path(__file__).read_text(encoding="utf-8").lower()
    for word in _BANNED:
        assert word.lower() not in this, "守卫文件自身出现完整禁词字面量"


def test_banned_list_is_effective():
    """正例自检：拼接结果确实能命中，避免守卫空转。"""
    assert len(_BANNED) == 3
    assert all(w.strip() for w in _BANNED)
    sample = "prefix " + _BANNED[0].lower() + " suffix"
    assert _BANNED[0].lower() in sample.lower()
