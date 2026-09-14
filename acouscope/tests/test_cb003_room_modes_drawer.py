# SPDX-License-Identifier: GPL-3.0-only
"""CB-003 G-1：房间模态抽屉化（库存 D5 收口）测试。

D5 匿名对话框壳包 RoomModesWidget → 右抽屉承载（open_drawer width=560，
与房间声学/设置/录音/帮助抽屉同宽复用）。RoomModesWidget 本体零改动。
模式照抄 tests/test_room_acoustics_drawer.py（结构特征断言，禁字面 count）。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QDialog, QWidget

from acouscope.ui.widgets.room_modes import RoomModesWidget

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def test_room_modes_widget_not_dialog(qapp):
    """RoomModesWidget 本身是 QWidget 且非 QDialog（可无参构造）。"""
    w = RoomModesWidget()
    assert isinstance(w, QWidget)
    assert not isinstance(w, QDialog)


def test_room_modes_embedded_in_drawer(qapp):
    """抽屉承载断言：open_drawer 装载 RoomModesWidget，实例出现在抽屉内容区。"""
    from acouscope.ui.widgets.drawer import open_drawer

    host = QWidget()
    host.resize(1200, 800)
    host.show()
    w = RoomModesWidget()
    drawer = open_drawer(host, w, width=560)
    assert drawer.is_open()
    # 结构特征断言（父链包含，非字面 count）
    assert w in drawer.content_frame.findChildren(RoomModesWidget)


def test_room_modes_source_de_modalized():
    """_on_room_modes 函数体：走全铺页通路（_set_workspace_page）、页内嵌入
    RoomModesWidget、无 QDialog 壳、无 exec 调用。"""
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    chunks = [c for c in mw.split("\n    def ") if c.startswith("_on_room_modes")]
    assert len(chunks) == 1
    body = chunks[0].split("\n    def ")[0]
    assert "_set_workspace_page" in body  # T-1054 批3：中央全铺页通路（唯一状态源）
    assert "RoomModesWidget" in body       # 页内嵌入（R3 零改造）
    assert "QDialog(" not in body
    assert ".exec()" not in body


def test_room_modes_no_leftover_qdialog_wrapper():
    """全文件锚点：main_window.py 已无 QDialog 匿名壳实例化遗留。"""
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    assert "QDialog(self)" not in mw
