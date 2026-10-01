# SPDX-License-Identifier: GPL-3.0-only
"""T-1094 图表设计器菜单归类守卫测（全离屏，禁 MainWindow.show()）。

覆盖施工令 T-1094 判据②（移动配归属新断 + 文案配三语一致守卫）：
① `action_chart_designer` 的父菜单现为「工具」，且排在音律标尺之后；
② 「文件▸导出」子菜单不再含该 action（导出子菜单其余项未被动到）；
③ 分析工具栏入口②仍在、同一实例只出现一次（本件不动工具栏）；
④ 手册入口文案三语齐：QUICK_START 与 MANUAL §11 各写「工具 → 图表设计器」
   （2×3=6 处），旧「文件 → 导出 → …」路径串绝迹；
⑤ T-1091 成果不回退：§5「7 种色板」逐语恰 1、`{sc_*}` 占位符仍可完整替换、
   帮助文案零对话框字面量；
⑥ 反证：归属改回 export / 某语入口文案改回旧串 ⇒ 对应断言各自必红（断言有牙）。
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets import help_dialogs
from acouscope.ui.widgets.help_dialogs import MANUAL, QUICK_START, _format_shortcuts
from tests._pin_baselines import HELP_SECTIONS_PER_LANG

LANGS = ("zh_CN", "zh_TW", "en_US")
HELP_SOURCE = pathlib.Path(help_dialogs.__file__)

# 三语「工具 → 图表设计器」新入口串与被移除的旧「文件 → 导出 → …」串
NEW_ENTRY = {
    "zh_CN": "工具 → 图表设计器",
    "zh_TW": "工具 → 圖表設計器",
    "en_US": "Tools → Chart Designer",
}
OLD_ENTRY = {
    "zh_CN": "文件 → 导出 → 图表设计器",
    "zh_TW": "檔案 → 匯出 → 圖表設計器",
    "en_US": "File → Export → Chart Designer",
}
# §5 语谱图色板数（与 §13 轨身份色 12 不同义，T-1091 R-4 冻结面）
COLORMAP_SEVEN = {
    "zh_CN": "7 种色板",
    "zh_TW": "7 種色板",
    "en_US": "7 colormaps",
}


# ---------------------------------------------------------------------------
# 夹具 / 工具
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（不 show()）；HOME 与数据目录隔离到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.2 * np.sin(2 * np.pi * 440.0 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def _menu(window, key: str) -> QMenu:
    """按菜单标题取原生 QMenu（tools_menu/export_menu 均为局部变量，不外露）。"""
    title = tr(key)
    found = [m for m in window.findChildren(QMenu) if m.title() == title]
    assert found, f"缺少菜单 {key}（现有: {sorted({m.title() for m in window.findChildren(QMenu) if m.title()})}）"
    return found[0]


def _assert_hosted_by(window, host_key: str, absent_key: str, after_key: str | None) -> None:
    """核心断言核：action 唯一宿主 == host_key，absent_key 不含它，位置在 after_key 后。"""
    act = window.action_chart_designer
    hosts = [
        m for m in window.findChildren(QMenu)
        if any(a is act for a in m.actions())
    ]
    assert [m.title() for m in hosts] == [tr(host_key)], (
        f"chart_designer 宿主菜单须唯一且为 {host_key}，实得 {[m.title() for m in hosts]}"
    )
    host = _menu(window, host_key)
    acts = host.actions()
    assert act in acts
    assert act not in _menu(window, absent_key).actions()
    if after_key is not None:
        assert acts.index(act) > acts.index(window.action_tuning_ruler), (
            "图表设计器须排在音律标尺之后（律/图工具相邻）"
        )


# ---------------------------------------------------------------------------
# ①②③ 菜单归属移动 + 工具栏不动
# ---------------------------------------------------------------------------


def test_chart_designer_now_hosted_by_tools_menu(window):
    """① 父菜单为「工具」，且紧随音律标尺一族之后。"""
    _assert_hosted_by(window, "menu.tools", "menu.export", "action_tuning_ruler")


def test_export_menu_still_serves_actual_exports(window):
    """② 导出子菜单摘除设计器后，导出项本身一个不少。"""
    export_menu = _menu(window, "menu.export")
    texts = [a.text() for a in export_menu.actions() if not a.isSeparator()]
    assert tr("action.export") in texts, texts
    assert not any(a is window.action_chart_designer for a in export_menu.actions())
    assert window.action_export in export_menu.actions()


def test_analysis_toolbar_entry_untouched(window):
    """③ 工具栏入口②不动：同一实例仍在、且只挂一次。"""
    act = window.action_chart_designer
    analysis_tb = window.btn_ai_interpret.parent()
    assert [a for a in analysis_tb.actions() if a is act].__len__() == 1


def test_action_definition_and_slot_untouched(window):
    """零改面自证：F10 / checkable / 图标仍在，勾选仍驱动全铺页 index4（槽未换）。"""
    act = window.action_chart_designer
    assert isinstance(act, QAction)
    assert act.isCheckable() is True
    assert act.shortcut().toString().upper() == "F10"
    assert not act.icon().isNull()
    act.trigger()
    assert window.central_stack.currentIndex() == 4
    assert window.central_stack.currentWidget() is window.chart_designer_page
    act.trigger()
    assert window.central_stack.currentIndex() == 0


# ---------------------------------------------------------------------------
# ④⑤ 手册入口三语 + T-1091 成果不回退
# ---------------------------------------------------------------------------


def _assert_manual_paths(book: dict[str, str]) -> None:
    for lang in LANGS:
        assert book[lang].count(NEW_ENTRY[lang]) == 1, (
            f"{lang} 手册缺「{NEW_ENTRY[lang]}」入口"
        )
        assert OLD_ENTRY[lang] not in book[lang], f"{lang} 残留旧「{OLD_ENTRY[lang]}」路径"


def test_manual_entry_paths_point_at_tools_in_three_languages():
    """④ QUICK_START 与 MANUAL §11 各三语 1 处 = 6 处入口文案已同步。"""
    _assert_manual_paths(QUICK_START)
    _assert_manual_paths(MANUAL)


def test_t1091_manual_face_not_regressed():
    """⑤ §5 的 7 逐语恰 1 · 占位符仍可替换 · 无对话框字面量。"""
    src = HELP_SOURCE.read_text(encoding="utf-8")
    for literal in ("QDialog", "QDialogButtonBox", ".exec("):
        assert literal not in src, f"帮助文案出现被禁字面量 {literal}"
    for lang in LANGS:
        assert MANUAL[lang].count(COLORMAP_SEVEN[lang]) == 1
        assert MANUAL[lang].count("12 色") + MANUAL[lang].count("12-color") == 1
        assert MANUAL[lang].count("8 色") + MANUAL[lang].count("8-color") == 0
        for book in (MANUAL, QUICK_START):
            assert "{sc_" not in _format_shortcuts(book[lang])
    assert src.count("<h3>") == HELP_SECTIONS_PER_LANG * len(LANGS)  # 三语各 20 节（T-1091 §20 新节之后）


# ---------------------------------------------------------------------------
# ⑥ 反证（断言有牙）
# ---------------------------------------------------------------------------


def test_reverse_proof_mutations_make_the_guards_go_red(window):
    """反证：归属退回 export / 入口文案退回旧串 ⇒ 各自必红。"""
    with pytest.raises(AssertionError):
        _assert_hosted_by(window, "menu.export", "menu.tools", None)

    back_to_file = dict(QUICK_START)
    back_to_file["en_US"] = QUICK_START["en_US"].replace(
        NEW_ENTRY["en_US"], OLD_ENTRY["en_US"]
    )
    with pytest.raises(AssertionError):
        _assert_manual_paths(back_to_file)
