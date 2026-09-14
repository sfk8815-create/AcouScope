# SPDX-License-Identifier: GPL-3.0-only
"""T-504d 房间声学工具去模态化 + 右抽屉接入测试。

模式照抄 tests/test_settings_drawer.py（T-504g-migration 模式）。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QWidget, QDialog, QTabWidget
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


def test_embedded_in_drawer(qapp):
    from acouscope.ui.widgets.drawer import open_drawer
    host = QWidget()
    host.resize(1200, 800)
    host.show()
    drawer = open_drawer(host, RoomAcousticsDialog(), width=560)
    assert drawer.is_open()


def test_sources_de_modalized():
    sd = (UI / "widgets" / "room_acoustics_dialog.py").read_text(encoding="utf-8")
    assert "class RoomAcousticsDialog(QWidget)" in sd
    assert "QDialog" not in sd
    assert ".exec(" not in sd
    assert "self.accept" not in sd
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    assert "open_drawer" in mw  # 抽屉基础设施仍在（批4 才退役）
    # _on_room_acoustics 函数体：走全铺页通路（_set_workspace_page）、无 .exec()
    # 分隔符 "\n    def " 会吞掉 "def " 前缀，块以方法名开头
    chunks = [c for c in mw.split("\n    def ") if c.startswith("_on_room_acoustics")]
    assert len(chunks) == 1
    body = chunks[0].split("\n    def ")[0]
    assert "_set_workspace_page" in body  # T-1054 批3：中央全铺页通路（唯一状态源）
    assert ".exec()" not in body
