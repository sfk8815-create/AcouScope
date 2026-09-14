# SPDX-License-Identifier: GPL-3.0-only
"""T-1002 菜单信息架构 + 主工具栏重构回归测试（全离屏，禁 MainWindow.show()）。

覆盖：
① 7 菜单齐全（文件/编辑/视图/分析/工具/设置/帮助，菜单栏顶层）；
② 视图 7 项 radio 与 analysis_tab_bar 双向同步（同一切换路径，无第二套状态机）；
③ 「分析此区域」enable 规则（无选区 disabled / 有选区 enabled，真实选区链路）；
④ 「批处理」enable = BatchWorkspace 注册表非空；留位两项（T-924/T-1002 布局 reset）禁用；
⑤ 主工具栏含新建/打开/保存项目三按钮 + 批处理入口（同 QAction 实例）；
⑥ 快捷键中枢：窗口内全部 QAction 键位唯一性扫描（白名单为空）；
⑦ standardIcon 0 命中；纪律自断言（禁词 / 无新增 hex、px / 不新建 QDialog 类）。
"""

import ast
import inspect
import pathlib
import re
import sys

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QToolBar, QWidget

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui.main_window import MainWindow

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_MW_PY = _SRC / "ui" / "main_window.py"
_I18N_PY = _SRC / "i18n" / "__init__.py"

_BANNED = "Mel" + "odyne"
# 键位冲突白名单（同键位合法共存例外）。T-1002 新增 Ctrl+N / Ctrl+Shift+R
# 均无冲突 → 本表为空：任何键位重复即失败。
_SHORTCUT_WHITELIST: frozenset = frozenset()
# 既有硬编码像素白名单（本任务改动前已存在；新增任一 px 即失败）
_PX_WHITELIST = frozenset({"1px", "14px", "20px", "28px", "44px", "700px"})
# 既有硬编码颜色白名单（现状为空：main_window 颜色一律 theme 派生）
_HEX_WHITELIST: frozenset = frozenset()

_MENU_KEYS = (
    "menu.file", "menu.edit", "menu.view", "menu.analysis",
    "menu.tools", "menu.settings", "menu.help",
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的 MainWindow（离屏构建，不 show()；teardown close）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440 * t), sr)

    w = MainWindow(controller)
    w.waveform_widget.set_data(t, 0.5 * np.sin(2 * np.pi * 440 * t), sample_rate=sr)
    yield w
    w.close()


def _stub_build_views(window) -> None:
    """懒构建替换为轻量登记（只喂结构路径，不触发真实分析计算）。"""

    def _fake_build(index: int) -> None:
        page = QWidget()
        page.setObjectName(f"fakeView{index}")
        window._view_widgets[index] = page
        window.view_container.addWidget(page)
        window.view_container.setCurrentWidget(page)

    window._build_analysis_view = _fake_build


def _top_menus(window) -> dict:
    return {
        act.menu().title(): act.menu()
        for act in window.menuBar().actions()
        if act.menu() is not None
    }


def _file_toolbar(window) -> QToolBar:
    tb = window.btn_toggle_right_panel.parent()
    assert isinstance(tb, QToolBar)
    return tb


# ---------------------------------------------------------------------------
# ① 菜单存在性
# ---------------------------------------------------------------------------


def test_seven_top_level_menus(window):
    menus = _top_menus(window)
    assert list(menus) == [tr(k) for k in _MENU_KEYS], f"菜单栏顶层菜单不符: {list(menus)}"


def test_view_and_tools_menus_present_in_all_menus(window):
    """视图/工具菜单同时可经 findChildren(QMenu) 命中原生对象。"""
    from PyQt6.QtWidgets import QMenuBar

    titles = {m.title() for m in window.findChildren(QMenu) if m.title()}
    assert tr("menu.view") in titles
    assert tr("menu.tools") in titles
    assert isinstance(window.menuBar(), QMenuBar)


def test_placeholder_items_are_disabled(window):
    """留位项（T-924~925/布局 reset）一律禁用占位，零槽函数。

    T-1003 归因：``action_export_report`` 已由 T-1003 接线启用（有音频即可导出
    报告），不再属留位项，故从本断言移除；其启用口径由下方
    ``test_export_report_action_enabled_by_audio`` 覆盖。
    T-1004 归因（非静默）：``action_multitrack_compare`` 已由 T-1004 接线为
    **可勾选的多轨态入口**（进入轨道区），不再属留位项，故从本断言移除；
    其 enable 口径由 ``test_multitrack_action_enabled_by_audio_or_tracks`` 覆盖。
    """
    for name in (
        "action_annotation_mode",
        "action_restore_layout",
    ):
        act = getattr(window, name)
        assert act.isEnabled() is False, f"{name} 留位项应为禁用"


def test_multitrack_action_enabled_by_audio_or_tracks(window):
    """T-1004：多轨入口 enable = 有音频或会话已有轨；可勾选（非留位占位）。"""
    act = window.action_multitrack_compare
    assert act.objectName() == "multitrack_compare"
    assert act.isCheckable() is True
    assert act.isEnabled() is window._can_enter_multitrack()
    assert act.isEnabled() is True          # 本 fixture 已加载音频
    assert act.shortcut().isEmpty() is True  # 零快捷键（不与既有键位冲突）


def test_export_report_action_enabled_by_audio(window):
    """T-1003：「导出报告 PDF…」enable = 有音频（同 _update_measure_actions 口径）。"""
    act = window.action_export_report
    assert act.objectName() == "export_report"
    assert act.isEnabled() is bool(window.controller.has_audio())


def test_batch_action_enabled_by_registry(window):
    """「批处理」enable 由 BatchWorkspace 注册表非空驱动（T-913/914 已注册模块）。"""
    from acouscope.ui.widgets.batch_workspace import registered_modules

    assert bool(registered_modules()) is True
    assert window.action_batch.isEnabled() is True


# ---------------------------------------------------------------------------
# ② 视图菜单 ↔ 标签卡双向同步
# ---------------------------------------------------------------------------


def test_view_menu_seven_checkable_radio_group(window):
    acts = window._view_actions
    assert len(acts) == 7
    assert all(a.isCheckable() for a in acts)
    assert window.view_action_group.isExclusive() is True
    assert [a.text() for a in acts] == [
        tr(k) for k in (
            "cmb.waveform", "cmb.fft", "cmb.spectrogram", "cmb.pitch",
            "cmb.formants", "cmb.timbre", "cmb.spectrogram3d",
        )
    ]
    assert sum(1 for a in acts if a.isChecked()) == 1


def test_tab_switch_checks_menu_item(window, qapp):
    """切标签卡 → 对应菜单项勾选（勾选态唯一来源 = 标签卡索引）。"""
    _stub_build_views(window)
    assert window.analysis_tab_bar.currentIndex() == 0
    assert window._view_actions[0].isChecked()

    window.analysis_tab_bar.setCurrentIndex(3)
    qapp.processEvents()
    assert window._view_actions[3].isChecked()
    assert sum(1 for a in window._view_actions if a.isChecked()) == 1


def test_menu_trigger_switches_tab(window, qapp):
    """触发菜单项 → 标签卡切到对应索引（不引入第二套切换入口）。"""
    _stub_build_views(window)
    window.analysis_tab_bar.setCurrentIndex(2)
    qapp.processEvents()

    window._view_actions[5].trigger()
    qapp.processEvents()
    assert window.analysis_tab_bar.currentIndex() == 5
    assert window._view_actions[5].isChecked()
    assert window._view_actions[2].isChecked() is False


def test_view_nav_items_reuse_existing_i18n_keys(window):
    """适应窗口/复位键收编既有 menu.view_all / menu.reset_x / menu.reset_view 键。"""
    assert window.action_view_fit.text() == tr("menu.view_all")
    assert window.action_view_reset_x.text() == tr("menu.reset_x")
    assert window.action_view_reset_view.text() == tr("menu.reset_view")


# ---------------------------------------------------------------------------
# ③ 分析此区域 enable 规则
# ---------------------------------------------------------------------------


def test_analyze_region_disabled_without_selection(window):
    assert window.waveform_widget.get_selection() is None
    assert window.action_analyze_region.isEnabled() is False


def test_analyze_region_enabled_with_selection(window):
    window.waveform_widget.set_selection(0.2, 0.8)  # 真实链路 → selectionChanged
    assert window.action_analyze_region.isEnabled() is True


def test_analyze_region_menu_item_calls_t915_slot(window, monkeypatch):
    """菜单项 → 同一 T-915 槽：选区经归一化后传入（无选区则 toast 防御）。"""
    window.waveform_widget.set_selection(0.9, 0.3)  # 反向输入（归一化后 0.3/0.9）
    seen = []
    monkeypatch.setattr(window, "_on_analyze_region", lambda t0, t1: seen.append((t0, t1)))
    window.action_analyze_region.trigger()
    assert seen == [(0.3, 0.9)]


# ---------------------------------------------------------------------------
# ④/⑤ 工具栏
# ---------------------------------------------------------------------------


def test_main_toolbar_has_project_buttons_and_batch(window):
    tb = _file_toolbar(window)
    actions = tb.actions()
    for act in (
        window.action_new_project,
        window.action_open_project,
        window.action_save_project,
        window.action_open,
        window.action_undo,
        window.action_redo,
        window.action_export,
    ):
        assert act in actions, f"主工具栏缺少 {act.text()}"
    assert window.btn_toggle_right_panel.parent() is tb
    # T-1054 批0：批处理从工具栏 QAction 撤下，改以 checkable 开关驻留工具栏
    assert window.btn_toggle_batch_workspace.parent() is tb


def test_new_project_icon_from_theme(window):
    for act in (window.action_new_project, window.action_open_project,
                window.action_save_project, window.action_batch):
        icon = act.icon()
        assert icon is not None and not icon.isNull(), f"{act.text()} 图标为空"


def test_toolbar_button_style_unified(window):
    """主/分析工具栏按钮风格统一（TextBesideIcon），禁混合。"""
    from PyQt6.QtCore import Qt

    main_tb = _file_toolbar(window)
    analysis_tb = window.btn_ai_interpret.parent()
    assert isinstance(analysis_tb, QToolBar)
    style = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert main_tb.toolButtonStyle() == style
    assert analysis_tb.toolButtonStyle() == style


# ---------------------------------------------------------------------------
# ⑥ 快捷键中枢
# ---------------------------------------------------------------------------


def test_action_shortcuts_are_unique(window):
    """全部 QAction 键位唯一性扫描（白名单为空 → 任一重复即失败）。"""
    seen: dict = {}
    conflicts = []
    for act in window.findChildren(QAction):
        for seq in act.shortcuts():
            key = seq.toString()
            if not key:
                continue
            if key in _SHORTCUT_WHITELIST:
                continue
            holder = f"{act.objectName() or act.text()}"
            if key in seen and seen[key] != holder:
                conflicts.append((key, seen[key], holder))
            else:
                seen[key] = holder
    assert not conflicts, f"键位冲突: {conflicts}"


def test_shortcuts_overview_lists_shortcuts(window):
    """帮助·快捷键总览：展开时以窗口 QAction 实时重建（零硬编码清单）。"""
    assert isinstance(window.menu_shortcuts_overview, QMenu)
    window._rebuild_shortcuts_overview()
    entries = [a.text() for a in window.menu_shortcuts_overview.actions()]
    assert len(entries) >= 5
    assert all("(" in e for e in entries)
    assert any(tr("action.open").replace("&", "") in e for e in entries)


# ---------------------------------------------------------------------------
# ⑦ 纪律自断言
# ---------------------------------------------------------------------------


def test_standard_icon_zero_hits():
    module = sys.modules[MainWindow.__module__]
    assert "standardIcon" not in inspect.getsource(module)


def test_no_banned_word_in_touched_files():
    for path in (_MW_PY, _I18N_PY, pathlib.Path(__file__)):
        assert _BANNED.lower() not in path.read_text(encoding="utf-8").lower()


def test_no_new_hardcoded_hex_or_px():
    src = _MW_PY.read_text(encoding="utf-8")
    px = set(re.findall(r"\b\d+(?:\.\d+)?px\b", src))
    hex_colors = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", src))
    assert px <= _PX_WHITELIST, f"新增硬编码像素: {px - _PX_WHITELIST}"
    assert hex_colors <= _HEX_WHITELIST, f"新增硬编码颜色: {hex_colors - _HEX_WHITELIST}"


def test_no_qdialog_class_added():
    """禁新建 QDialog 子类（菜单/工具栏改造不得引回模态对话框）。"""
    tree = ast.parse(_MW_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = {
                getattr(b, "id", None) or getattr(b, "attr", None)
                for b in node.bases
            }
            assert "QDialog" not in bases, f"新增 QDialog 子类: {node.name}"


def test_menu_restructure_test_does_not_show_main_window():
    """本测试文件自身纪律：禁对主窗口调用 show()（离屏构建，不落真实窗口）。"""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert ("window" + ".show()") not in src
