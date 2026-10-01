# SPDX-License-Identifier: GPL-3.0-only
"""CB-003 G-1：房间模态页宿主化（库存 D5 收口）测试。

D5 匿名对话框壳包 RoomModesWidget → 页宿主承载（T-1054 批4d 起抽屉
open_drawer 整体退役，改由中央全铺页 / 页宿主承载；RoomModesWidget 本体
零改动）。模式照抄 tests/test_room_acoustics_drawer.py（结构特征断言，
禁字面 count）。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QDialog, QWidget, QVBoxLayout

from acouscope.ui.widgets.room_modes import RoomModesWidget

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def test_room_modes_widget_not_dialog(qapp):
    """RoomModesWidget 本身是 QWidget 且非 QDialog（可无参构造）。"""
    w = RoomModesWidget()
    assert isinstance(w, QWidget)
    assert not isinstance(w, QDialog)


def test_room_modes_embedded_in_page_host(qapp):
    """页宿主承载断言：RoomModesWidget 装入宿主容器且非模态，父链包含自身。"""
    host = QWidget()
    host.resize(1200, 800)
    host.show()
    w = RoomModesWidget()
    layout = QVBoxLayout(host)
    layout.addWidget(w)
    qapp.processEvents()
    assert not isinstance(w, QDialog)     # 非模态（无 QDialog 壳）
    assert w.parent() is host             # 装入宿主容器
    assert w.isModal() is False           # 非模态语义保留
    assert w.isVisibleTo(host)            # 宿主显示时随宿主可见
    # 结构特征断言（父链包含，非字面 count）
    assert w in host.findChildren(RoomModesWidget)


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
