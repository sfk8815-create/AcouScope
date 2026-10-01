# SPDX-License-Identifier: GPL-3.0-only
"""T-504a Toast 非模态反馈服务测试。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QDialog
from acouscope.ui.widgets.toast import ToastWidget, show_toast, LEVELS


def test_levels_contract():
    assert LEVELS == ("info", "success", "warning", "error")


def test_show_toast_visible_parented(qapp):
    host = QWidget()
    host.resize(800, 600)
    t = show_toast(host, "分析完成", level="success")
    assert isinstance(t, ToastWidget)
    assert t.parent() is host
    assert t.isVisible()
    assert t.property("level") == "success"
    assert t.lblMessage.text() == "分析完成"


def test_all_levels_and_unknown_fallback(qapp):
    host = QWidget()
    for lv in LEVELS:
        t = show_toast(host, f"msg-{lv}", level=lv)
        assert t.property("level") == lv
    t = show_toast(host, "unknown", level="__nope__")
    assert t.property("level") == "info"


def test_non_modal_no_activation(qapp):
    host = QWidget()
    t = show_toast(host, "x")
    assert not isinstance(t, QDialog)
    assert t.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert t.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert not t.isModal() if hasattr(t, "isModal") else True


def test_parent_required(qapp):
    try:
        show_toast(None, "x")
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def test_auto_close_timer_exists(qapp):
    host = QWidget()
    t = show_toast(host, "x", duration=1000)
    from PyQt6.QtCore import QTimer
    timers = t.findChildren(QTimer)
    assert any(tm.isSingleShot() for tm in timers)


def test_styling_uses_theme_no_hardcode():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "widgets" / "toast.py"
    text = src.read_text(encoding="utf-8")
    assert "exec(" not in text.replace("execute(", "")  # 无模态 exec
    assert "setWindowModality" not in text
    assert "TOKENS" in text and "style_when_theme" in text
