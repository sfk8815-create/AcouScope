# SPDX-License-Identifier: GPL-3.0-only
"""帮助面板测试：快速入门/用户手册 = QWidget 非模态；关于 = 模态 QDialog 例外。

快速入门 / 用户手册：QDialog 模态 exec 流 → QWidget 非模态面板，
T-1054 批4d 起抽屉（open_drawer）已整体退役，面板改为装入右栏内容页
宿主（window.right_content 及其页宿主）。模式照抄
tests/test_settings_drawer.py。

关于（AboutDialog）：CB-010 用户特批「关于」回归模态 QDialog
（内容/样式与原非模态版本一致，见 about_dialog.py），其余帮助面板不受影响。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QWidget, QDialog, QVBoxLayout
from acouscope.ui.widgets.help_dialogs import QuickStartDialog, ManualDialog
from acouscope.ui.widgets.about_dialog import AboutDialog

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def test_help_dialogs_are_widgets(qapp):
    """快速入门/用户手册：QWidget 且非 QDialog（均可直接无参构造）。"""
    qs = QuickStartDialog()
    assert isinstance(qs, QWidget)
    assert not isinstance(qs, QDialog)
    man = ManualDialog()
    assert isinstance(man, QWidget)
    assert not isinstance(man, QDialog)


def test_about_is_modal_qdialog(qapp):
    """关于：QDialog 模态例外（CB-010 用户特批；仅结构断言，禁 show/exec）。"""
    d = AboutDialog()
    assert isinstance(d, QDialog)
    assert d.isModal()
    # 内容存在（LOGO/版本/版权等区段的锚点控件仍可构造）
    assert d.btn_close is not None


def test_help_close_button_emits_cancelled(qapp):
    """帮助面板“关闭”按钮 click() → cancelled 信号（QuickStart/Manual）。"""
    qs = QuickStartDialog()
    seen = []
    qs.cancelled.connect(lambda: seen.append("qs"))
    qs.btn_close.click()
    assert seen == ["qs"]

    man = ManualDialog()
    seen2 = []
    man.cancelled.connect(lambda: seen2.append("man"))
    man.btn_close.click()
    assert seen2 == ["man"]


def test_about_close_button_accepts(qapp):
    """关于关闭按钮 click() → accept()（模态 exec 正常收尾）。"""
    ab = AboutDialog()
    seen = []
    ab.accepted.connect(lambda: seen.append("ok"))
    ab.btn_close.click()
    assert seen == ["ok"]


def test_embedded_in_page_host(qapp):
    """非模态嵌入：帮助面板可装入右栏内容页宿主容器且非模态。

    抽屉退役后等价断言：面板作为普通 QWidget 子件装入宿主容器
    （对应右栏内容页宿主 window.right_content 的承载方式）。
    """
    host = QWidget()
    host.resize(1200, 800)
    host.show()
    panel = QuickStartDialog()
    layout = QVBoxLayout(host)
    layout.addWidget(panel)
    qapp.processEvents()
    assert not isinstance(panel, QDialog)     # 非模态面板（非对话框）
    assert panel.parent() is host             # 装入宿主容器
    assert panel.isModal() is False           # 非模态语义保留
    assert panel.isVisibleTo(host)            # 宿主显示时面板随之可见


def test_sources_modal_split():
    """帮助源去模态 + 关于模态例外：QDialog 只允许在 about_dialog.py 出现。"""
    hd = (UI / "widgets" / "help_dialogs.py").read_text(encoding="utf-8")
    assert "class _HelpDialog(QWidget)" in hd
    assert "QDialog" not in hd
    assert "QDialogButtonBox" not in hd
    assert ".exec(" not in hd

    ab = (UI / "widgets" / "about_dialog.py").read_text(encoding="utf-8")
    assert "class AboutDialog(QDialog)" in ab
    assert "setModal(True)" in ab  # CB-010 模态例外登记

    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    assert "QuickStartDialog(self).exec()" not in mw
    assert "ManualDialog(self).exec()" not in mw
    assert "AboutDialog(self).exec()" in mw  # 关于为唯一 exec 例外
    # T-1054 批4b：帮助族退役 —— _info_drawer 及其槽在 main_window 零出现
    assert "_info_drawer" not in mw
    assert "def _on_quickstart" not in mw
    assert "def _on_manual" not in mw
    assert "_on_info_drawer_cancelled" not in mw
    # T-1054 批4d：抽屉基础设施整体退役 —— drawer.py 已删除
    assert not (UI / "widgets" / "drawer.py").exists()


def test_manual_dialog_widget(qapp):
    """用户手册：无参构造无异常且 btn_close 存在。"""
    d = ManualDialog()
    assert hasattr(d, "btn_close")
    assert d.btn_close is not None

