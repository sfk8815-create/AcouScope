# SPDX-License-Identifier: GPL-3.0-only
"""DrawerWidget 顶部图标切换行（CB-012 C-1 组件能力；T-1010 后保留给抽屉临时工具）。

说明（T-1010 归因）：右抽屉对 AI/检查器/设置/帮助 的承载已取消，AI 改由
右栏 tab 承载（integration 断言见 test_sidebar_tabs.py 与 test_ai_drawer.py）；
本文件仅保留 DrawerWidget.set_icon_row 组件层契约（图表字体/录音/房间声学
等抽屉机制保留，drawer.py 不动）。

覆盖验收（离屏，不 MainWindow.show()）：
  ① DrawerWidget/open_drawer 顶层：icons 列表渲染出顶图标行、互斥 checkable、
     index0 默认选中、tooltip 双语 key 实存、点击发 iconSelected。
断言纪律：几何禁硬编码像素；图标非空走 isNull()；tooltip 比对 tr(key) 双语。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QLabel, QWidget

from acouscope.i18n import get_language, set_language, tr
from acouscope.ui.widgets.drawer import open_drawer

# 组件层 icons 参数（drawer.tab.* 键仍实存三语；AI/检查器/设置/帮助四项示意）
_ICON_ITEMS = [
    ("ai", "drawer.tab.ai"),
    ("inspect", "drawer.tab.inspector"),
    ("settings", "drawer.tab.settings"),
    ("help-circle", "drawer.tab.help"),
]


def _icons():
    """构造 icons 参数（name + 双语 tooltip）。"""
    return [(name, tr(key)) for name, key in _ICON_ITEMS]


def test_icon_row_rendered_and_default_checked(qapp):
    """验收①-1：图标行存在、条目数与 icons 一致、index0 默认选中。"""
    host = QWidget()
    host.resize(900, 700)
    items = _icons()
    drawer = open_drawer(host, QLabel("面板"), width=640, icons=items, default_index=0)

    assert drawer.icon_row.isVisibleTo(drawer)
    btns = drawer._icon_buttons
    assert len(btns) == len(items) == len(_ICON_ITEMS)
    # 互斥 checkable、默认选中 index0
    assert btns[0].isChecked()
    assert not any(b.isChecked() for b in btns[1:])
    # 图标走 get_icon 非空、tooltip 为当前语言 tr(key)
    for btn, (_, key) in zip(btns, _ICON_ITEMS):
        assert btn.icon().isNull() is False
        assert btn.toolTip() == tr(key)
        assert btn.toolTip()
    host.close()


def test_icon_row_tooltips_bilingual(qapp):
    """验收①-2：图标行 tooltip 对应 i18n 双语 key（en_US/zh_CN 均实存且不同）。"""
    orig = get_language()
    try:
        set_language("en_US")
        en = [tr(key) for _, key in _ICON_ITEMS]
        set_language("zh_CN")
        zh = [tr(key) for _, key in _ICON_ITEMS]
    finally:
        set_language(orig)
    assert all(e and z for e, z in zip(en, zh))
    assert all(e != z for e, z in zip(en, zh))


def test_icon_row_click_emits_index(qapp):
    """验收①-3：点击图标行条目发出 iconSelected(index)。"""
    host = QWidget()
    host.resize(900, 700)
    drawer = open_drawer(host, QLabel("面板"), width=640, icons=_icons(), default_index=0)
    got = []
    drawer.iconSelected.connect(got.append)
    btns = drawer._icon_buttons
    btns[2].click()  # 设置
    assert got == [2]
    assert btns[2].isChecked()  # 互斥切换
    assert not btns[0].isChecked()
    host.close()
