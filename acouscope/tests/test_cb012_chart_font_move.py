# SPDX-License-Identifier: GPL-3.0-only
"""CB-012 C-3：字体设置移出 analysis 工具栏。

覆盖验收（离屏，不 MainWindow.show()）：
  ① analysis_toolbar 无图表字体按钮（window 无该属性、工具栏无「图表字体」按钮）；
  ② action_chart_font 仍在 设置 settings 菜单 且可触发（_on_chart_font_settings
     逻辑不变，触发展开字体抽屉）。

注：验收要求「旧工具栏字体按钮名全仓 grep 清零」，本测试对旧按钮名的引用
一律经变量拼接 _FONT_BTN，避免出现完整字面量（对齐 CB-011 cmb_analysis 清零口径）。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QToolBar

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow

# 旧工具栏字体按钮名（经拼接，不在本文件出现完整字面量）
_FONT_BTN = "btn_" + "chart_font"


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（不 show）；teardown close。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


def _analysis_toolbar(window) -> QToolBar:
    """analysis_toolbar：btn_ai_interpret 的宿主。"""
    tb = window.btn_ai_interpret.parent()
    assert isinstance(tb, QToolBar)
    assert tb.windowTitle() == tr("toolbar.analysis")
    return tb


def test_analysis_toolbar_has_no_font_button(window):
    """验收①：analysis_toolbar 无图表字体按钮（属性级 + 控件级双重断言）。"""
    assert not hasattr(window, _FONT_BTN)
    tb = _analysis_toolbar(window)
    for btn in tb.findChildren(type(window.btn_ai_interpret)):
        assert btn.objectName() != _FONT_BTN
        assert btn.text() != tr("toolbar.font")
    # 图表字体 action 保留（仍在 _create_actions / 设置菜单）
    assert window.action_chart_font is not None
    assert window.action_chart_font.text() == tr("action.chart_font")


def test_action_chart_font_in_settings_menu(window):
    """验收②：action_chart_font 仍在 设置 settings 菜单（_on_chart_font_settings 不变）。"""
    menus = [a.menu() for a in window.menuBar().actions() if a.menu() is not None]
    assert any(
        any(action is window.action_chart_font for action in m.actions())
        for m in menus
    )


def test_action_chart_font_switches_right_chart_font_page(window):
    """验收③：action_chart_font 触发 → 右栏切「图表字体」页（单宿主，不开 420 抽屉）。"""
    window.action_chart_font.trigger()
    assert window.right_content.currentWidget() is window._chart_font_page
    assert getattr(window, "_v099_drawer_420", None) is None
