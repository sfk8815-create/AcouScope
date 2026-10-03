# SPDX-License-Identifier: GPL-3.0-only
"""T-1091 帮助文档三语一致守卫测（纯离屏，不起窗、不改产品码）。

覆盖开发任务单 T-1091 判据②③：
① 三语 `MANUAL` 各含「20. 音律标尺」新节、三语 `<h3>` 节数一致；`QUICK_START` 三语
   各含音律标尺条目且「去哪看更多」的节数文案已随新节更新；
② §13 轨道身份色为 12 色、旧「8 色」字样在三语手册中绝迹；
③ ★ R-4 反向守卫：§5 语谱图「7 种色板」（colormap 数·与轨身份色不同义）逐字未改；
④ §18 固定绑定表三语各含 Ctrl+M / F9 / F10 / Ctrl+Shift+S / Ctrl+Shift+P 行；
⑤ 被钉行（打时间点 T / 撤销上一打点 Shift+T / 试听选区 P / A/B 循环选区 L）逐字在；
⑥ 文案禁 `QDialog` / `QDialogButtonBox` / `.exec(` 字面量，且 `{sc_*}` 占位符仍可被
   `_format_shortcuts` 完整替换（防新节写进花括号而 format 时炸）；
⑦ 反证：删掉某语的新节标题 ⇒ ① 必红；§13 的 12 色退回 8 色 ⇒ ② 必红
   （同一断言函数跑变异副本，证明断言有牙）。
"""

import pathlib

import pytest

pytest.importorskip("PyQt6")

from acouscope.ui.widgets import help_dialogs
from acouscope.ui.widgets.help_dialogs import MANUAL, QUICK_START, _format_shortcuts
from tests._pin_baselines import HELP_SECTIONS_PER_LANG

LANGS = ("zh_CN", "zh_TW", "en_US")
HELP_SOURCE = pathlib.Path(help_dialogs.__file__)

# 三语「音律标尺」新节标题（§20）、快速入门条目关键词与节数文案
SEC20_TITLE = {
    "zh_CN": "<h3>20. 音律标尺</h3>",
    "zh_TW": "<h3>20. 音律標尺</h3>",
    "en_US": "<h3>20. Tuning Ruler</h3>",
}
RULER_HINT = {"zh_CN": "音律标尺", "zh_TW": "音律標尺", "en_US": "Tuning Ruler"}
QS_SECTION_COUNT = {
    "zh_CN": "含 20 节完整说明",
    "zh_TW": "含 20 節完整說明",
    "en_US": "a full 20-section guide",
}
# §13 轨道身份色（theme.track_palette 12 轮转）与 §5 语谱图色板数（7）
TRACK_COLOR_12 = {"zh_CN": "12 色", "zh_TW": "12 色", "en_US": "12-color"}
TRACK_COLOR_8 = {"zh_CN": "8 色", "zh_TW": "8 色", "en_US": "8-color"}
COLORMAP_SEVEN = {
    "zh_CN": "7 种色板",
    "zh_TW": "7 種色板",
    "en_US": "7 colormaps",
}
FIXED_BINDING_KEYS = ("Ctrl+M", "F9", "F10", "Ctrl+Shift+S", "Ctrl+Shift+P")
# 既有冻结测逐字钉住的行（test_playhead_annotate / test_selection_quick_play）
PINNED_ROWS = (
    "<tr><td>打时间点</td><td>T</td></tr>",
    "<tr><td>撤销上一打点</td><td>Shift+T</td></tr>",
    "<tr><td>打時間點</td><td>T</td></tr>",
    "<tr><td>撤銷上一打點</td><td>Shift+T</td></tr>",
    "<tr><td>Add time mark</td><td>T</td></tr>",
    "<tr><td>Undo last mark</td><td>Shift+T</td></tr>",
    "试听选区</td><td>P</td>",
    "A/B 循环选区（开/关）</td><td>L</td>",
    "試聽選區</td><td>P</td>",
    "A/B 循環選區（開/關）</td><td>L</td>",
    "Preview selection</td><td>P</td>",
    "A/B loop selection (toggle)</td><td>L</td>",
)


def _assert_sec20_present(book: dict[str, str]) -> None:
    for lang in LANGS:
        assert SEC20_TITLE[lang] in book[lang], f"{lang} 缺 §20 音律标尺新节"
    counts = {book[lang].count("<h3>") for lang in LANGS}
    assert counts == {HELP_SECTIONS_PER_LANG}, f"三语 <h3> 节数须一致且为 20，实得 {counts}"


def _assert_track_color_is_12(book: dict[str, str]) -> None:
    for lang in LANGS:
        assert TRACK_COLOR_12[lang] in book[lang], f"{lang} §13 未订正为 12 色"
        assert TRACK_COLOR_8[lang] not in book[lang], f"{lang} 仍残留 8 色字样"


def test_manual_has_tuning_ruler_section_in_all_three_languages():
    _assert_sec20_present(MANUAL)


def test_quick_start_lists_tuning_ruler_in_all_three_languages():
    for lang in LANGS:
        qs = QUICK_START[lang]
        assert RULER_HINT[lang] in qs, f"{lang} 快速入门缺音律标尺条目"
        assert QS_SECTION_COUNT[lang] in qs, f"{lang} 快速入门节数未随新节更新"


def test_sec13_track_identity_colors_are_twelve():
    _assert_track_color_is_12(MANUAL)


def test_sec5_colormap_count_wording_untouched():
    """R-4：§5 语谱图「7 种色板」与 §13 轨身份色不同义，禁被 8→12 顺带改掉。"""
    for lang in LANGS:
        assert MANUAL[lang].count(COLORMAP_SEVEN[lang]) == 1


def test_sec18_fixed_table_lists_the_five_new_bindings():
    for lang in LANGS:
        body = MANUAL[lang]
        for key in FIXED_BINDING_KEYS:
            assert f"<td>{key}</td>" in body, f"{lang} §18 缺 {key} 行"


def test_pinned_manual_rows_preserved_verbatim():
    src = HELP_SOURCE.read_text(encoding="utf-8")
    for row in PINNED_ROWS:
        assert row in src, f"被钉行被改动：{row}"


def test_copy_keeps_dialog_literals_out_and_placeholders_intact():
    src = HELP_SOURCE.read_text(encoding="utf-8")
    for literal in ("QDialog", "QDialogButtonBox", ".exec("):
        assert literal not in src, f"帮助文案禁出现字面量 {literal}"
    for lang in LANGS:
        for book in (MANUAL, QUICK_START):
            assert "{sc_" not in _format_shortcuts(book[lang]), f"{lang} 占位符未替换干净"


def test_reverse_proof_mutations_make_the_guards_go_red():
    """反证：删新节标题 / 12 色退回 8 色，两处断言各自必红。"""
    no_sec20 = dict(MANUAL)
    no_sec20["en_US"] = MANUAL["en_US"].replace(SEC20_TITLE["en_US"], "<h3>20. X</h3>")
    with pytest.raises(AssertionError):
        _assert_sec20_present(no_sec20)

    back_to_8 = dict(MANUAL)
    back_to_8["zh_CN"] = MANUAL["zh_CN"].replace(
        TRACK_COLOR_12["zh_CN"], TRACK_COLOR_8["zh_CN"], 1
    )
    with pytest.raises(AssertionError):
        _assert_track_color_is_12(back_to_8)
