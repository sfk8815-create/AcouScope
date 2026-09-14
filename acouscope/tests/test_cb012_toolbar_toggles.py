# SPDX-License-Identifier: GPL-3.0-only
"""主工具条右栏展开/折叠 toggle（CB-012 C-2 → T-1010 语义 → T-1012 收口）。

T-1012 归因：左侧图标栏（left_ribbon）**常驻不可关**，其开关按钮
`btn_toggle_ribbon` 及其槽已删除；工具栏仅保留「右栏展开/折叠」
（btn_toggle_right_panel ↔ right_panel PanelContainer 折叠态）。

覆盖验收（离屏，不 MainWindow.show()，点击驱动信号）：
  ① file_toolbar 只含 btn_toggle_right_panel（btn_toggle_ribbon 已删，hasattr False）；
  ② btn_toggle_right_panel 点击 → 右栏折叠/展开，按钮勾选态与折叠态联动；
  ③ 外部折叠（right_panel.set_collapsed(True)）→ 按钮同步回落；
  ④ left_ribbon 常驻：无 btn_toggle_ribbon 时仍可见（不隐藏）。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QToolBar

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（不 show）；teardown close。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


def _file_toolbar(window) -> QToolBar:
    """file_toolbar：右栏 toggle 按钮的宿主（addWidget 挂入主工具栏）。"""
    tb = window.btn_toggle_right_panel.parent()
    assert isinstance(tb, QToolBar)
    assert tb.windowTitle() == tr("toolbar.file")
    return tb


def test_ribbon_toggle_deleted_right_toggle_present(window):
    """验收①+④：左侧图标栏开关已删除（ribbon 常驻）；右栏 toggle 仍可用。"""
    assert not hasattr(window, "btn_toggle_ribbon")
    tb = _file_toolbar(window)
    assert window.btn_toggle_right_panel.parent() is tb
    assert window.btn_toggle_right_panel.isCheckable()
    # 默认态：右栏展开（checked）
    assert window.btn_toggle_right_panel.isChecked()
    assert not window.right_panel.is_collapsed()
    # ribbon 常驻：始终为中央区 item0，且无任何显隐开关可关闭它
    assert window.left_ribbon is not None
    central = window.centralWidget()
    assert central.layout().indexOf(window.left_ribbon) == 0
    # 图标走 get_icon 非空 + i18n tooltip
    assert window.btn_toggle_right_panel.icon().isNull() is False
    assert window.btn_toggle_right_panel.toolTip() == tr("toolbar.toggle_right_panel")


def test_toggle_right_panel_collapses_and_expands(window, monkeypatch):
    """验收②：btn_toggle_right_panel 点击 → 右栏折叠/展开，勾选态联动。"""
    assert window.btn_toggle_right_panel.isChecked()
    window.btn_toggle_right_panel.click()     # 展开 → 折叠
    assert not window.btn_toggle_right_panel.isChecked()
    assert window.right_panel.is_collapsed()

    window.btn_toggle_right_panel.click()     # 折叠 → 展开
    assert window.btn_toggle_right_panel.isChecked()
    assert not window.right_panel.is_collapsed()


def test_right_panel_external_collapse_unchecks_button(window):
    """验收③：右栏外部折叠（恢复布局/程序）→ 按钮同步回落。"""
    assert window.btn_toggle_right_panel.isChecked()
    window.right_panel.set_collapsed(True)
    assert not window.btn_toggle_right_panel.isChecked()
    window.right_panel.set_collapsed(False)
    assert window.btn_toggle_right_panel.isChecked()
