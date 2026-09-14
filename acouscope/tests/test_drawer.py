# SPDX-License-Identifier: GPL-3.0-only
"""T-504b 右侧抽屉基础设施测试（离屏；几何断言先 resize 固定，禁硬编码布局结果）。"""
import re
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QWidget, QLabel, QFrame
from acouscope.ui.widgets.drawer import DrawerWidget, open_drawer


def test_parent_required(qapp):
    try:
        DrawerWidget(None)
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def test_contract_and_child(qapp):
    host = QWidget()
    host.resize(900, 700)
    d = DrawerWidget(host, width=360, duration=0)
    assert isinstance(d, QFrame)
    assert d.parent() is host
    assert d.window() is host  # 子部件，不是顶层窗口
    assert d.width() == 360
    assert not d.is_open()


def test_open_close_toggle_signal(qapp):
    host = QWidget()
    host.resize(900, 700)
    host.show()
    d = DrawerWidget(host, duration=0)
    seen = []
    d.closed.connect(lambda: seen.append("closed"))
    d.opened.connect(lambda: seen.append("opened"))
    d.set_content(QLabel("设置面板"))
    d.open()
    assert d.is_open()
    assert d.isVisible()
    d.toggle()  # 开 -> 关
    assert not d.is_open()
    assert not d.isVisible()
    d.toggle()  # 关 -> 开
    assert d.is_open()
    d.close_drawer()
    assert not d.is_open()
    assert seen == ["opened", "closed", "opened", "closed"]


def test_position_right_aligned_and_follows_resize(qapp):
    host = QWidget()
    host.resize(900, 700)
    host.show()
    d = DrawerWidget(host, width=300, duration=0)
    d.open()
    assert d.x() == 900 - 300
    assert d.height() == 700
    host.resize(1100, 700)
    assert d.x() == 1100 - 300  # 父窗变宽后仍右缘对齐


def test_open_reuses_existing_drawer(qapp):
    host = QWidget()
    host.resize(900, 700)
    a = open_drawer(host, QLabel("A"), width=360)
    b = open_drawer(host, QLabel("B"), width=360)
    assert a is b
    assert a.is_open()


def test_non_modal_no_exec(qapp):
    host = QWidget()
    d = DrawerWidget(host)
    assert d.parent() is host
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "widgets" / "drawer.py"
    text = src.read_text(encoding="utf-8")
    assert "exec(" not in text.replace("execute(", "")
    assert "setWindowModality" not in text
    assert "QSettings" not in text


def test_styling_uses_theme_no_hardcode(qapp):
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "widgets" / "drawer.py"
    text = src.read_text(encoding="utf-8")
    assert "TOKENS" in text and "style_when_theme" in text
    assert not re.search(r"#[0-9a-fA-F]{6}\b", text), "发现硬编码 hex 色值"
