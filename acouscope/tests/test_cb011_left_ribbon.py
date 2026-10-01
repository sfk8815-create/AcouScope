# SPDX-License-Identifier: GPL-3.0-only
"""CB-011 B-2 → T-1012：主窗最左窄图标栏（left_ribbon，常驻不可关）。

覆盖验收（结构断言，离屏，不 MainWindow.show()）：
  ① 中央区外层为 QHBoxLayout：item0 = left_ribbon（窄固定宽），
     其后为原水平三栏工作区（其 widget(1) 即 central_stack：index0 常规页
     原垂直 splitter——波形上/分析面板下；index1 批处理工作区，T-913；
     index2 房间模态页；index3 房间声学页，T-1054b3）；
  ② ribbon 内 QVBoxLayout 结构：顶部 文件/设置 图标（左栏内容入口，T-1012
     上移占位）→ 中部弹性留白（spacer）→ 底部 帮助?；
  ③ 顶部/底部图标按钮 get_icon 非空 + i18n tooltip、objectName ribbonIconBtn。

断言纪律：禁硬编码绝对像素（固定宽断言 = min==max>0，不落具体像素值）；
图标非空断言走 isNull()；ribbon 无显隐开关（btn_toggle_ribbon 已删除）。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
)

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（构造即建 left_ribbon；不 show）；teardown close。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


def _row_items(layout) -> list:
    """按布局顺序展平：widget 项记 (widget, None)、弹簧记 (None, spacer)。"""
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget()
        if w is not None:
            out.append((w, None))
        else:
            out.append((None, item.spacerItem()))
    return out


def test_central_layout_is_ribbon_then_workspace(window):
    """验收①：中央外层 QHBoxLayout = [left_ribbon | 原三栏工作区（含垂直 splitter）]。"""
    central = window.centralWidget()
    layout = central.layout()
    assert isinstance(layout, QHBoxLayout)

    assert layout.indexOf(window.left_ribbon) == 0  # 最左
    assert window.left_ribbon.parent() is central
    assert window.left_ribbon.objectName() == "leftRibbon"
    # 窄条固定宽：不落绝对像素值，只断言等宽固定 >0
    assert window.left_ribbon.minimumWidth() == window.left_ribbon.maximumWidth()
    assert window.left_ribbon.minimumWidth() > 0

    # item1 = 原水平三栏工作区（左导航 | central_stack | 右检查器）
    ws = layout.itemAt(1).widget()
    assert ws is window.ws_splitter
    assert isinstance(ws, QSplitter)
    assert ws.orientation() == Qt.Orientation.Horizontal
    assert ws.count() == 3

    # 中间栏（T-913）为 central_stack：index0 = 常规页（原垂直 splitter：
    # 波形视图（含传输条）在上、分析面板在下）；index1 = 批处理工作区；
    # index2 = 房间模态页；index3 = 房间声学页（T-1054b3）；index4 = 图表设计器页（T-1054a）。
    center = ws.widget(1)
    assert isinstance(center, QStackedWidget)
    assert center is window.central_stack
    assert center.count() == 6
    assert center.currentIndex() == 0  # 默认常规模式（行为零变化）
    regular = center.widget(0)
    assert isinstance(regular, QSplitter)
    assert regular.orientation() == Qt.Orientation.Vertical
    assert regular.count() == 2
    assert regular.widget(0) is window.waveform_view
    assert regular.widget(1) is window.analysis_panel
    assert center.widget(1) is window.batch_workspace


def test_ribbon_vertical_stack_site_help_settings_spacer(window):
    """验收②：ribbon 纵向 = 中部留白 → 底部 网站 → 帮助 → 设置（置底固定）。"""
    ribbon = window.left_ribbon
    lay = ribbon.layout()
    assert isinstance(lay, QVBoxLayout)

    rows = _row_items(lay)
    # 纵向序列：中部弹簧留白、随后底部组 网站/帮助/设置（设置 = 纵向最后一个 widget）
    widgets = [w for w, _ in rows if w is not None]
    spacers = [s for _, s in rows if s is not None]
    assert spacers, "中部弹性留白位缺失"
    assert widgets[0] is window.ribbon_btn_site
    assert widgets[1] is window.ribbon_btn_help
    assert widgets[-1] is window.ribbon_btn_settings
    # 旧占位/底部分组不再出现（账户占位移除；文件页入口由面板头承担）
    assert not hasattr(window, "ribbon_btn_files")
    assert not hasattr(window, "ribbon_account_placeholder")
    assert not hasattr(window, "btn_toggle_ribbon")

    # 设置/帮助：图标按钮在位（get_icon 非空 + i18n 双语 tooltip）
    for btn, key in (
        (window.ribbon_btn_settings, "sidebar.tab.settings"),
        (window.ribbon_btn_help, "action.quickstart"),
    ):
        assert isinstance(btn, QPushButton)
        assert btn.parent() is ribbon
        assert btn.objectName() == "ribbonIconBtn"
        assert btn.icon().isNull() is False
        assert btn.toolTip() == tr(key)
        assert btn.toolTip()


def test_help_icon_opens_quickstart_not_about(qapp, monkeypatch, tmp_path):
    """T-1054 批4b：ribbon 帮助? 走唯一槽 _on_left_page_toggled(c, 1)（左栏快速入门），非关于。"""
    calls = []
    # 类方法 monkeypatch 必须在 MainWindow 构造前生效：connect 绑定的是
    # 构造当时的 bound method，事后替换实例属性无效
    monkeypatch.setattr(
        MainWindow,
        "_on_left_page_toggled",
        lambda self, checked, index: calls.append((checked, index)),
    )
    monkeypatch.setattr(
        MainWindow, "_on_about", lambda self: calls.append(("about",))
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    w = MainWindow(controller)
    try:
        w.ribbon_btn_help.click()
        assert calls == [(True, 1)], \
            f"帮助图标应切到左栏快速入门(index1)，实得 {calls}"
        assert not any(c == ("about",) for c in calls)
    finally:
        w.close()
