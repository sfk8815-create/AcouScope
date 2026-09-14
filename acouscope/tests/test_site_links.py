# SPDX-License-Identifier: GPL-3.0-only
"""T-1015 网站链接集成回归测试。

覆盖验收（结构 + 行为断言，offscreen 全程，MainWindow 只构造不 show）：
  ① URL 常量集中登记（主站/副站；副站仅登记不链接）；
  ② 关于对话框：LOGO 可点击 → 主站；主站地址文本列出并可点击 → 主站；
  ③ 帮助菜单含「访问网站」项（i18n 三语键 action.visit_site）→ 主站；
  ④ 主工具栏 LOGO 可点击 → 主站；
  ⑤ 左图标栏（ribbon）网站图标位于帮助图标上方、点击 → 主站；
  ⑥ 打开仅由用户点击触发（构造期零 openUrl）；
  ⑦ 静态纪律：禁词 0 / 常量文件零 hex、零 px / 未新增 QDialog / 本文件无 show()。

断言纪律：URL 全部引用常量（禁复制散落硬编码）；openUrl 一律经
QDesktopServices.openUrl monkeypatch 观测（替换后不真实打开浏览器）。
"""

import pathlib
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QPushButton

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.constants import SITE_MAIN_URL, SITE_MIRROR_URL, open_site
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.about_dialog import AboutDialog, ClickableLabel

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "acouscope"
_UI_DIR = _SRC / "ui"


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（构造即建工具栏/菜单/ribbon；不 show）；teardown close。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


def _spy_open_url(monkeypatch):
    """替换 QDesktopServices.openUrl 为记录器（替换后不真实打开浏览器）。"""
    calls = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: calls.append(url))
    )
    return calls


def _as_url_text(url) -> str:
    return url.toString() if hasattr(url, "toString") else str(url)


# ---------------------------------------------------------------------------
# ① URL 常量集中登记
# ---------------------------------------------------------------------------


def test_url_constants_registered():
    assert SITE_MAIN_URL == "https://sfk8815-create.github.io"
    # 副站本轮仅登记不链接（防误用：常量在，但任何入口不指向副站）
    assert SITE_MIRROR_URL == "https://acouscope.vercel.app"


def test_open_site_defaults_to_main(qapp, monkeypatch):
    """打开封装：无参 open_site() → QDesktopServices.openUrl(主站)。"""
    calls = _spy_open_url(monkeypatch)
    open_site()
    assert len(calls) == 1
    assert _as_url_text(calls[0]) == SITE_MAIN_URL


# ---------------------------------------------------------------------------
# ② 关于对话框
# ---------------------------------------------------------------------------


def test_about_logo_clickable_opens_main(qapp, monkeypatch):
    """关于 LOGO 为可点击控件（ClickableLabel），点击 → 主站。"""
    d = AboutDialog()
    try:
        if not hasattr(d, "lbl_logo"):
            pytest.skip("LOGO 资源缺失，无法断言可点击")
        assert isinstance(d.lbl_logo, ClickableLabel)
        assert d.lbl_logo.cursor().shape() == Qt.CursorShape.PointingHandCursor
        assert tr("action.visit_site") in d.lbl_logo.toolTip()

        calls = _spy_open_url(monkeypatch)
        assert calls == []  # 构造期零自动打开
        d.lbl_logo.clicked.emit()  # 模拟用户点击 LOGO
        assert len(calls) == 1
        assert _as_url_text(calls[0]) == SITE_MAIN_URL
    finally:
        d.close()


def test_about_lists_main_site_and_link_opens(qapp, monkeypatch):
    """关于对话框列出主站地址；点击链接 → 主站（仅点击触发）。"""
    d = AboutDialog()
    try:
        assert hasattr(d, "lbl_site_link")
        text = d.lbl_site_link.text()
        assert SITE_MAIN_URL in text

        calls = _spy_open_url(monkeypatch)
        assert calls == []
        d.lbl_site_link.linkActivated.emit(SITE_MAIN_URL)  # 模拟点击富文本链接
        assert len(calls) == 1
        assert _as_url_text(calls[0]) == SITE_MAIN_URL
    finally:
        d.close()


def test_about_construction_opens_nothing(qapp, monkeypatch):
    """关于对话框构造即零 openUrl（禁自动打开断言）。"""
    calls = _spy_open_url(monkeypatch)
    d = AboutDialog()
    try:
        assert calls == []
    finally:
        d.close()


# ---------------------------------------------------------------------------
# ③ 帮助菜单
# ---------------------------------------------------------------------------


def test_help_menu_visit_site_action(window, monkeypatch):
    """帮助菜单含「访问网站」项，位于 关于 之前；触发 → 主站。"""
    menu_text = tr("menu.help")
    help_action = next(
        (a for a in window.menuBar().actions() if a.text() == menu_text), None
    )
    assert help_action is not None and help_action.menu() is not None
    texts = [a.text() for a in help_action.menu().actions()]
    assert tr("action.visit_site") in texts
    assert tr("action.about") in texts
    # 位置：访问网站在 快速入门/用户手册 之后、关于 之前
    assert texts.index(tr("action.visit_site")) < texts.index(tr("action.about"))

    assert window.action_visit_site is not None
    assert window.action_visit_site.text() == tr("action.visit_site")
    calls = _spy_open_url(monkeypatch)
    window.action_visit_site.trigger()
    assert len(calls) == 1
    assert _as_url_text(calls[0]) == SITE_MAIN_URL


# ---------------------------------------------------------------------------
# ④ 主工具栏 LOGO
# ---------------------------------------------------------------------------


def test_toolbar_logo_clickable_opens_main(window, monkeypatch):
    """主工具栏 LOGO（ClickableLabel）点击 → 主站；构造期零自动打开。"""
    calls = _spy_open_url(monkeypatch)
    assert calls == []
    if not hasattr(window, "lbl_logo"):
        pytest.skip("LOGO 资源缺失，无法断言可点击")
    assert isinstance(window.lbl_logo, ClickableLabel)
    assert window.lbl_logo.objectName() == "mainLogo"
    window.lbl_logo.clicked.emit()  # 模拟用户点击 LOGO
    assert len(calls) == 1
    assert _as_url_text(calls[0]) == SITE_MAIN_URL


# ---------------------------------------------------------------------------
# ⑤ 左图标栏（ribbon）网站入口
# ---------------------------------------------------------------------------


def _widget_rows(layout):
    """按布局顺序收集非空 widget 项。"""
    out = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is not None:
            out.append(w)
    return out


def test_ribbon_site_button_above_help(window, monkeypatch):
    """ribbon 网站图标在 帮助 上方，帮助在 设置 上方（底部分组 网站→帮助→设置）；图标非空 + i18n tooltip；点击 → 主站。"""
    ribbon = window.left_ribbon
    site_btn = window.ribbon_btn_site
    assert isinstance(site_btn, QPushButton)
    assert site_btn.parent() is ribbon
    assert site_btn.objectName() == "ribbonIconBtn"
    assert site_btn.icon().isNull() is False
    assert site_btn.toolTip() == tr("action.visit_site")

    # 顺序（T-1054 批1a）：底部组 = 网站 → 帮助 → 设置（地址序列）site 紧邻帮助上方、帮助紧邻设置上方
    widgets = _widget_rows(ribbon.layout())
    assert window.ribbon_btn_help in widgets
    assert widgets[-1] is window.ribbon_btn_settings  # 设置现为最底部（置底固定）
    assert widgets.index(site_btn) == widgets.index(window.ribbon_btn_help) - 1
    assert widgets.index(window.ribbon_btn_help) == widgets.index(window.ribbon_btn_settings) - 1

    calls = _spy_open_url(monkeypatch)
    site_btn.click()  # 模拟用户点击
    assert len(calls) == 1
    assert _as_url_text(calls[0]) == SITE_MAIN_URL


def test_ribbon_click_site_is_not_quickstart(window, monkeypatch):
    """网站按钮 ≠ 帮助按钮：点网站走 openUrl 主站，不开快速入门抽屉。"""
    calls = _spy_open_url(monkeypatch)
    window.ribbon_btn_site.click()
    assert len(calls) == 1
    assert _as_url_text(calls[0]) == SITE_MAIN_URL
    assert getattr(window, "_info_drawer", None) is None  # 帮助族已走左栏页，无抽屉


# ---------------------------------------------------------------------------
# ⑦ 静态纪律（禁词 / 零 hex·px / 未新增 QDialog / MainWindow 不 show()）
# ---------------------------------------------------------------------------


def test_static_discipline_new_sources():
    """新增/修改源零禁词、constants 零 hex·px、about_dialog 未新增 QDialog 类。"""
    files = [
        _UI_DIR / "constants.py",
        _UI_DIR / "widgets" / "about_dialog.py",
        _UI_DIR / "main_window.py",
    ]
    banned = "M" + "elodyne"  # 拼接防模式字面量自身被扫中
    for p in files:
        src = p.read_text(encoding="utf-8")
        assert banned.lower() not in src.lower(), f"{p.name} 命中禁词"

    const_src = (_UI_DIR / "constants.py").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", const_src), "constants.py 含硬编码 hex"
    assert "px" not in const_src.replace("pytest", ""), "constants.py 含 px 硬编码"

    about_src = (_UI_DIR / "widgets" / "about_dialog.py").read_text(
        encoding="utf-8"
    )
    # 未新增 QDialog 子类：只允许既有 AboutDialog 白名单例外
    dialog_classes = re.findall(r"class\s+\w+\(QDialog\)", about_src)
    assert dialog_classes == ["class AboutDialog(QDialog)"], dialog_classes
    assert (".ex" + "ec(") not in about_src


def test_this_file_static_discipline():
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert ("MainWindow" + ".show()") not in src
    assert (".ex" + "ec(") not in src
    assert ("standard" + "Icon") not in src
    # 禁词（拼接构造，避免字面量自身被扫中）
    assert ("M" + "elodyne").lower() not in src.lower()
