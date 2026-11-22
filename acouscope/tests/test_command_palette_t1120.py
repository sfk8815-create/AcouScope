# SPDX-License-Identifier: GPL-3.0-only
"""T-1120 命令面板：非模态浮层 + 模糊检索 + Enter 触发 + Esc 关闭。

判据：
① 面板可见且**不产生模态**（`QApplication.activeModalWidget() is None`），
   输入即过滤，Enter 触发对应 QAction，Esc 关闭；
② 空查询列出全部；无匹配显示空态项；禁用项不可触发；
③ 主窗集成：`MainWindow.open_command_palette()` 可开且快捷键已注册。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from acouscope.ui.command_palette import CommandPalette


def _esc_event():
    from PyQt6.QtGui import QKeyEvent

    return QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                     Qt.KeyboardModifier.NoModifier)


def _host_with_actions(counter):
    host = QWidget()
    host.resize(800, 600)
    menu = QMenu("视图", host)
    for text in ("图表设计器", "房间模态分析", "导出音频文件"):
        act = QAction(text, host)
        act.triggered.connect(lambda _c=False, t=text: counter.append(t))
        menu.addAction(act)
    host.addAction(menu.menuAction())
    disabled = QAction("禁用命令", host)
    disabled.setEnabled(False)
    disabled.triggered.connect(lambda: counter.append("禁用命令"))
    host.addAction(disabled)
    return host


def test_palette_filters_activates_and_closes(qapp):
    counter: list[str] = []
    host = _host_with_actions(counter)
    host.show()
    qapp.processEvents()

    pal = CommandPalette(host)
    pal.show_over()
    qapp.processEvents()

    assert pal.isVisible()
    assert not pal.isModal()
    assert QApplication.activeModalWidget() is None, "命令面板不得是模态"
    assert pal.list.count() == 4, pal.list.count()

    pal.edit.setText("房间")
    qapp.processEvents()
    assert pal.list.count() == 1
    assert "房间模态分析" in pal.list.item(0).text()

    pal.activate_current()
    qapp.processEvents()
    assert counter == ["房间模态分析"]
    assert not pal.isVisible(), "触发后应关闭"

    pal.show_over()
    qapp.processEvents()
    pal.edit.setText("导出")
    qapp.processEvents()
    QCoreApplication.sendEvent(pal.edit, _esc_event())   # 走 eventFilter 真路径
    qapp.processEvents()
    assert not pal.isVisible()


def test_palette_empty_state_and_disabled(qapp):
    counter: list[str] = []
    host = _host_with_actions(counter)
    host.show()
    qapp.processEvents()

    pal = CommandPalette(host)
    pal.show_over()
    pal.edit.setText("zzz-不存在")
    qapp.processEvents()
    assert pal.list.count() == 1
    assert pal.list.item(0).flags() == Qt.ItemFlag.NoItemFlags
    pal.activate_current()
    assert counter == [], "无匹配项不得触发任何动作"

    pal.edit.setText("禁用")
    qapp.processEvents()
    assert pal.list.count() == 1
    pal.activate_current()
    assert counter == [], "禁用项不得触发"


def test_palette_shape_inside_host(qapp):
    counter: list[str] = []
    host = _host_with_actions(counter)
    host.show()
    qapp.processEvents()
    pal = CommandPalette(host)
    pal.show_over()
    qapp.processEvents()
    assert pal.width() > 0 and pal.height() > 0
    assert pal.width() <= host.width()
    assert pal.height() <= host.height()


def test_main_window_wires_palette_and_shortcut(qapp):
    """主窗集成：方法可开非模态面板；Ctrl+Shift+K 已注册进快捷键表。"""
    import numpy as np

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow
    from acouscope.ui.shortcuts import ShortcutManager
    from acouscope.i18n import tr

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.2 * np.sin(2 * np.pi * 440.0 * t), sr)
    win = MainWindow(controller)
    try:
        pal = win.open_command_palette()
        qapp.processEvents()
        assert pal is not None
        assert pal.isVisible()
        assert QApplication.activeModalWidget() is None
        assert pal.list.count() > 10, f"命令表过少：{pal.list.count()}"
        QCoreApplication.sendEvent(pal.edit, _esc_event())   # 走 eventFilter 真路径
        qapp.processEvents()
        assert not pal.isVisible()

        entry = ShortcutManager.instance()._entries.get("command_palette")
        assert entry is not None, "command_palette 未注册"
        assert entry.label == tr("command_palette.title")
        assert entry.current_key == "Ctrl+Shift+K", entry.current_key
    finally:
        win.close()
