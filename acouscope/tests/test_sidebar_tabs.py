# SPDX-License-Identifier: GPL-3.0-only
"""T-1012 侧栏内容宿主（无 tab 条：图标切换同一内容区）+ 入口路由。

唯一宿主原则（ARCH_sidebar_ai_panel §六）：
  左栏内容（QStackedWidget 无 tab 条）= 文件(默认，FileBrowser)/ 设置(SettingsDialog 懒构建)；
  右栏内容 = 检查器(默认，InspectorPanel)/ AI 释图（_ai_host 宿主，每次新建实例）；
  左栏默认收起 / 右栏默认展开；ribbon 顶部文件/设置图标切换左栏内容；
  ribbon 底部帮助? 接「快速入门」、手册/关于仍走菜单 action；右抽屉不再承载
  AI/检查器/设置/帮助；AnalysisNavigator 已整体删除（T-1013，覆盖裁决 A，
  模块/导出/接线守卫见 test_ui_smoke.test_navigator_removed）。

fixture 参照 tests/test_inspector_panel.py：qapp（conftest）+ window + 门控 +
HOME=tmp_path + 合成音频，window 不 show()，QT_QPA_PLATFORM=offscreen。
"""

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QMenu, QStackedWidget

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.ai_interpret import AIInterpretDialog
from acouscope.ui.widgets.file_browser import FileBrowser
from acouscope.ui.widgets.panels import InspectorPanel
from acouscope.ui.widgets.settings_dialog import SettingsDialog

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
# 批4d：抽屉实现整档删除（`_v099_drawer_*` 注册族随之失去实现）
_DRAWER_PY = _REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "drawer.py"


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控；不 show）。"""

    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    sweep = 0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t)
    controller.load_from_array(sweep, sr)

    w = MainWindow(controller)
    yield w
    w.close()


# ----------------------------------------------------------------------
# 左右栏内容宿主（无 tab 条）
# ----------------------------------------------------------------------


def test_left_content_default_files_and_collapsed(window):
    """左栏默认内容=文件浏览器且默认收起（启动无布局记录）；无 QTabWidget 条。"""
    assert isinstance(window.left_content, QStackedWidget)
    assert window.left_content.count() == 5
    assert window.left_content.currentWidget() is window.file_browser
    assert isinstance(window.file_browser, FileBrowser)
    assert window.file_browser.parent() is not None
    # 默认收起（T-1012：restore 无记录 → collapsed=True）
    assert window.left_panel.is_collapsed()
    # 懒构建：打开设置前为占位页（index4，index0-3 为文件/快速入门/手册/录音设置）
    assert window._settings_panel is None
    assert window.left_content.widget(4) is window._settings_placeholder
    assert not hasattr(window, "left_tabs")


def test_right_content_default_inspector_expanded(window):
    """右栏默认内容=检查器且默认展开；AI 页为常驻宿主（打开前无实例）。"""
    assert isinstance(window.right_content, QStackedWidget)
    assert window.right_content.count() == 3
    assert window.right_content.currentWidget() is window.inspector_panel
    assert isinstance(window.inspector_panel, InspectorPanel)
    assert not window.right_panel.is_collapsed()
    assert window._ai_panel is None
    assert not hasattr(window, "right_tabs")


def test_settings_route_lazy_build_and_expand(window):
    """设置入口（action_settings/ribbon ⚙）→ 懒构建并切到左栏设置内容 + 展开。"""
    assert window.left_panel.is_collapsed()
    window.action_settings.trigger()
    assert isinstance(window._settings_panel, SettingsDialog)
    assert window._settings_placeholder is None
    assert window.left_content.currentWidget() is window._settings_panel
    assert not window.left_panel.is_collapsed()
    # 折叠左栏后入口重入 → 自动展开（实例不再重建；批1b 设置页入口为 ribbon 置底 ⚙）
    panel = window._settings_panel
    window.left_panel.set_collapsed(True)
    window.ribbon_btn_settings.click()
    assert window._settings_panel is panel
    assert not window.left_panel.is_collapsed()
    assert window.left_content.currentWidget() is window._settings_panel
    # 文件图标 → 切回文件内容（无 tab 条）
    window.btn_header_files.click()
    assert window.left_content.currentWidget() is window.file_browser


def test_ai_route_builds_panel_in_right_content(window, qapp):
    """AI 入口（检查器 aiRequested / 菜单 action）→ 右栏切 AI 宿主内容。"""
    window.inspector_panel.aiRequested.emit()
    qapp.processEvents()
    assert isinstance(window._ai_panel, AIInterpretDialog)
    assert window.right_content.count() == 3
    assert window.right_content.currentWidget() is window._ai_host
    assert window._ai_panel.parent() is window._ai_host
    assert not hasattr(window, "_v099_drawer_640")   # 批4d：弱式断言升级 + 实现档已删
    assert not _DRAWER_PY.exists()
    window._ai_panel.close()

    # 再开一次 → 每次入口新建实例（旧实例已 close 移出宿主）
    old = window._ai_panel
    window.action_ai_interpret.trigger()
    qapp.processEvents()
    assert window._ai_panel is not old
    assert isinstance(window._ai_panel, AIInterpretDialog)
    assert window._ai_panel.parent() is window._ai_host
    window._ai_panel.close()


def test_ai_route_expands_collapsed_right_panel(window, qapp):
    window.right_panel.set_collapsed(True)
    assert window.right_panel.is_collapsed()
    window.inspector_panel.aiRequested.emit()
    qapp.processEvents()
    assert not window.right_panel.is_collapsed()
    assert window.right_content.currentWidget() is window._ai_host
    assert isinstance(window._ai_panel, AIInterpretDialog)
    window._ai_panel.close()


def test_no_drawer_hub_registry_after_routes(window, qapp):
    """AI/设置入口不再创建任何抽屉实例（_v099_drawer_* 不出现）。"""
    window.action_ai_interpret.trigger()
    qapp.processEvents()
    window.action_settings.trigger()
    qapp.processEvents()
    drawers = [k for k in window.__dict__ if k.startswith("_v099_drawer_")]
    assert drawers == []
    assert not _DRAWER_PY.exists()          # 批4d：抽屉实现整档删除（防复活）
    if window._ai_panel is not None:
        window._ai_panel.close()


def test_help_only_in_menus(window):
    """帮助三入口走菜单 action（快速入门/手册/关于）。"""
    bar = window.menuBar()

    def _in_any_menu(action) -> bool:
        for m in bar.findChildren(QMenu):
            if action in m.actions():
                return True
        return False

    for act in (
        window.action_quickstart,
        window.action_manual,
        window.action_about,
    ):
        assert act is not None
        assert _in_any_menu(act), f"action 未挂入任何菜单: {act.text()}"


# ----------------------------------------------------------------------
# 回归锚点：既有分析/文件/播放链路关键控件仍在
# ----------------------------------------------------------------------


def test_existing_flow_controls_intact(window):
    assert window.waveform_widget is not None
    assert window.transport_bar is not None
    assert window.analysis_tab_bar is not None
    assert window.view_container is not None
    assert window.file_browser.fileActivated is not None
    # inspector aiRequested → _on_ai_interpret 接线在 _build_side_tabs 内完成
    assert window.inspector_panel.aiRequested is not None


# ----------------------------------------------------------------------
# 静态纪律（本文件 + main_window 侧栏改造代码）
# ----------------------------------------------------------------------


def test_sidebar_symbols_in_main_window():
    mw = (_REPO_ROOT / "src" / "acouscope" / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    # 旧 QTabWidget 化/抽屉 hub 符号已删净
    assert "self.left_tabs" not in mw
    assert "self.right_tabs" not in mw
    assert "btn_toggle_ribbon" not in mw
    assert "ribbon_account_placeholder" not in mw
    assert "def _on_toggle_left_ribbon" not in mw
    assert "btn_toggle_drawer" not in mw
    assert "def _on_toggle_right_drawer" not in mw
    # 批4d：抽屉实现整档删除 + main_window 抽屉族标识符零出现（防复活）
    assert not _DRAWER_PY.exists()
    assert "open_drawer" not in mw
    assert "_drawer_entries" not in mw
    assert "_room_drawer" not in mw
    # 新架构符号存在
    assert "def _build_side_tabs" in mw
    assert "self.left_content" in mw
    assert "self.right_content" in mw
    assert "def _activate_ai_tab" in mw
    assert "def _activate_settings_tab" in mw
    assert "def _activate_files_tab" in mw
    # T-1013：导航器整删（无实例/无接线/无方法）+ 帮助? → 快速入门
    assert "analysis_navigator" not in mw
    assert "AnalysisNavigator" not in mw
    # T-1054 批4b：帮助? 改 toggled 接唯一槽 _on_left_page_toggled(c, 1)（左栏页）
    assert "ribbon_btn_help.toggled.connect(" in mw
    assert "_on_left_page_toggled(c, 1)" in mw
    assert "ribbon_btn_help = _icon_btn(\"help-circle\", tr(\"action.quickstart\"))" in mw


def test_this_file_static_discipline():
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    # 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）
    assert ("MainWindow" + ".show()") not in src
    assert ("Q" + "Dialog") not in src
    assert (".ex" + "ec(") not in src
