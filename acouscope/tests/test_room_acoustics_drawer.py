# SPDX-License-Identifier: GPL-3.0-only
"""T-504d 房间声学工具去模态化 + 右栏内容页宿主接入测试。

T-1054 批4d：抽屉（open_drawer）已整体退役，房间声学面板改由中央
全铺页 / 页宿主承载。模式照抄 tests/test_settings_drawer.py。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QWidget, QDialog, QTabWidget, QVBoxLayout
from acouscope.ui.widgets.room_acoustics_dialog import RoomAcousticsDialog

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def _find_tabwidget(w: QWidget) -> QTabWidget:
    """深度优先找第一个 QTabWidget。"""
    for child in w.findChildren(QWidget):
        if isinstance(child, QTabWidget):
            return child
    raise AssertionError("未找到 QTabWidget")


def test_room_acoustics_is_widget_not_modal(qapp):
    d = RoomAcousticsDialog()
    assert isinstance(d, QWidget)
    assert not isinstance(d, QDialog)


def test_three_tabs_preserved(qapp):
    d = RoomAcousticsDialog()
    tabs = _find_tabwidget(d)
    assert tabs.count() == 3
    texts = [tabs.tabText(i) for i in range(tabs.count())]
    assert any("Sabine" in t for t in texts)
    assert any("冲激响应" in t for t in texts)
    assert any("RT60" in t for t in texts)


def test_close_button_emits_cancelled(qapp):
    d = RoomAcousticsDialog()
    seen = []
    d.cancelled.connect(lambda: seen.append("c"))
    d.btn_close.click()
    assert seen == ["c"]


def test_embedded_in_page_host(qapp):
    """非模态嵌入：房间声学面板可装入页宿主容器且非模态。

    抽屉退役后等价断言：面板作为普通 QWidget 子件装入宿主容器。
    """
    host = QWidget()
    host.resize(1200, 800)
    host.show()
    panel = RoomAcousticsDialog()
    layout = QVBoxLayout(host)
    layout.addWidget(panel)
    qapp.processEvents()
    assert not isinstance(panel, QDialog)     # 非模态面板（非对话框）
    assert panel.parent() is host             # 装入宿主容器
    assert panel.isModal() is False           # 非模态语义保留
    assert panel.isVisibleTo(host)            # 宿主显示时面板随之可见


def test_sources_de_modalized():
    sd = (UI / "widgets" / "room_acoustics_dialog.py").read_text(encoding="utf-8")
    assert "class RoomAcousticsDialog(QWidget)" in sd
    assert "QDialog" not in sd
    assert ".exec(" not in sd
    assert "self.accept" not in sd
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    # 批4c：录音设置抽屉亦退役 → main_window 无 open_drawer；
    # 批4d：抽屉基础设施本体（drawer.py）整体删除 → 反向断言文件不存在
    assert "open_drawer" not in mw
    assert not (UI / "widgets" / "drawer.py").exists()
    # _on_room_acoustics 函数体：走全铺页通路（_set_workspace_page）、无 .exec()
    # 分隔符 "\n    def " 会吞掉 "def " 前缀，块以方法名开头
    chunks = [c for c in mw.split("\n    def ") if c.startswith("_on_room_acoustics")]
    assert len(chunks) == 1
    body = chunks[0].split("\n    def ")[0]
    assert "_set_workspace_page" in body  # T-1054 批3：中央全铺页通路（唯一状态源）
    assert ".exec()" not in body
