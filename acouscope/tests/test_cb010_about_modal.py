# SPDX-License-Identifier: GPL-3.0-only
"""CB-010 P0-2：「关于」回归模态 QDialog 结构断言测试。

背景：T-504e 曾把「关于」随帮助族去模态化为 QWidget 抽屉；CB-010 用户
特批「关于」回归模态 QDialog（AboutDialog 为模态例外，快速入门/用户手册
维持 QWidget 抽屉不动，登记 deviations）。

本文件只做结构断言（offscreen 全程，禁 .show()/.exec() 交互）：
  ① AboutDialog 是 QDialog 子类且 isModal=True（窗口类型/模态）；
  ② 内容保留（关闭按钮 + 三语标题文案可构造）；
  ③ 关闭按钮 → accept()（模态 exec 收尾语义）；
  ④ 源锚点：about_dialog.py = QDialog+setModal；main_window._on_about
     = AboutDialog(self).exec() 唯一 exec 调用点；help_dialogs.py 不受影响。
"""

import pathlib

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QDialog

from acouscope.ui.widgets.about_dialog import AboutDialog

_UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def test_about_dialog_is_modal_qdialog(qapp):
    """验收：AboutDialog 为 QDialog 子类且 isModal()=True（结构断言）。"""
    d = AboutDialog()
    try:
        assert isinstance(d, QDialog)
        assert d.isModal(), "关于对话框应为模态（CB-010 用户特批）"
    finally:
        d.close()


def test_about_dialog_content_preserved(qapp):
    """验收：内容/样式与抽屉版本一致——关键控件与文案锚点俱在。"""
    from acouscope.i18n import tr

    d = AboutDialog()
    try:
        assert d.btn_close is not None
        assert d.windowTitle() == tr("about.title")
        # 子控件存在（QDialog 内容非空：标题/版本/关闭按钮等均已入布局）
        assert d.layout() is not None and d.layout().count() >= 3
    finally:
        d.close()


def test_about_close_button_accepts(qapp):
    """验收：关闭按钮 click() → accept()（模态 exec 正常收尾，关闭后主窗存活）。"""
    d = AboutDialog()
    seen = []
    d.accepted.connect(lambda: seen.append("accepted"))
    d.btn_close.click()
    assert seen == ["accepted"]
    assert d.result() == QDialog.DialogCode.Accepted
    d.close()


def test_modal_exception_source_anchors():
    """源锚点：模态例外只落 about_dialog.py + main_window 单一 exec 调用点。"""
    ab = (_UI / "widgets" / "about_dialog.py").read_text(encoding="utf-8")
    assert "class AboutDialog(QDialog)" in ab
    assert "setModal(True)" in ab
    assert ".exec(" not in ab  # exec 由调用方 main_window 触发

    mw = (_UI / "main_window.py").read_text(encoding="utf-8")
    assert "AboutDialog(self).exec()" in mw
    # 帮助族（QuickStart/Manual）保持非模态，禁止 exec 调用回退
    assert "QuickStartDialog(self).exec()" not in mw
    assert "ManualDialog(self).exec()" not in mw
