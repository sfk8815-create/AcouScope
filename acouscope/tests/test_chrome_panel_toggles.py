# SPDX-License-Identifier: GPL-3.0-only
"""T-1048：Chrome 收口守卫 —— 主工具栏成对面板开关 + 左・右面板头图标栏。

口径：全离屏（不 MainWindow.show()，点击驱动信号），与 test_cb012_toolbar_toggles
同一 fixture 形态。覆盖：
  ① 左栏开关 btn_toggle_left_panel：存在 / checkable / 默认未勾选（左栏默认折叠）
     / 点击往返与 left_panel 折叠态联动 / icon-only + i18n tooltip；
  ② 右栏开关：图标由 inspect（放大镜）改 sidebar_right（缺口 E 修复）；
  ③ 外部折叠（set_collapsed）→ 两开关勾选态反同步；
  ④ btn_toggle_ribbon 仍不存在（R6 命名硬约束）；
  ⑤ 左右面板头右操作区各 ≥1 动作且 tooltip 非空（禁造空按钮）；
  ⑥ 左栏面板头入口与 ribbon 页签入口同组互斥（复用 T-1043 机制，零新同步逻辑）；
  ⑦ 图标：ICONS sidebar_left/sidebar_right + 三套资源齐备 + get_icon 非空；
  ⑧ 静态：新增段无 QDialog/QThread/QTimer、无 hex/px 字面量。
"""

import inspect
import re
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.main_window import (
    MainWindow,
    _header_icon_button,
    _panel_toggle_button,
)
from tests._pin_baselines import (
    ICONS_LOGICAL_NAME_COUNT,
    MAINWINDOW_QDIALOG_COUNT,
    MAINWINDOW_QTHREAD_COUNT,
    MAINWINDOW_QTIMER_COUNT,
)

_SRC = Path(__file__).resolve().parents[1] / "src" / "acouscope"
_MW_PY = _SRC / "ui" / "main_window.py"
_ICON_ROOT = _SRC / "resources" / "icons"


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（不 show）；teardown close。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# ① 左栏开关
# ---------------------------------------------------------------------------


def test_left_panel_toggle_exists_checkable_icon_only(window):
    btn = window.btn_toggle_left_panel
    tb = window.btn_toggle_right_panel.parent()
    assert btn.parent() is tb, "成对开关须同属主工具栏"
    assert btn.isCheckable()
    # 左栏默认折叠（workspace 缺省态）→ 默认未勾选
    assert window.left_panel.is_collapsed()
    assert not btn.isChecked()
    # icon-only + tooltip 承担可发现性
    assert btn.text() == ""
    assert btn.icon().isNull() is False
    assert btn.toolTip() == tr("toolbar.toggle_left_panel")


def test_left_panel_toggle_click_roundtrip(window):
    btn = window.btn_toggle_left_panel
    btn.click()  # 折叠 → 展开
    assert btn.isChecked()
    assert not window.left_panel.is_collapsed()
    btn.click()  # 展开 → 折叠（再点可关）
    assert not btn.isChecked()
    assert window.left_panel.is_collapsed()


# ---------------------------------------------------------------------------
# ② 右栏开关（图标缺口 E）
# ---------------------------------------------------------------------------


def test_right_panel_toggle_uses_sidebar_icon_not_inspect(window):
    btn = window.btn_toggle_right_panel
    assert btn.isCheckable()
    assert btn.isChecked()
    assert not window.right_panel.is_collapsed()
    assert btn.icon().isNull() is False
    assert btn.toolTip() == tr("toolbar.toggle_right_panel")

    src = _MW_PY.read_text(encoding="utf-8")
    assert 'get_icon("inspect")' not in src, "右栏开关不得再用放大镜（缺口 E）"
    assert '"sidebar_right"' in src, "右栏开关图标应为面板图元 sidebar_right"
    assert '"sidebar_left"' in src, "左栏开关图标应为面板图元 sidebar_left"


# ---------------------------------------------------------------------------
# ③ 外部折叠 → 两开关反同步
# ---------------------------------------------------------------------------


def test_external_collapse_resyncs_both_panel_toggles(window):
    window.left_panel.set_collapsed(True)
    assert not window.btn_toggle_left_panel.isChecked()
    window.left_panel.set_collapsed(False)
    assert window.btn_toggle_left_panel.isChecked()

    window.right_panel.set_collapsed(True)
    assert not window.btn_toggle_right_panel.isChecked()
    window.right_panel.set_collapsed(False)
    assert window.btn_toggle_right_panel.isChecked()

    # T-1054 批2-bis：右栏页签勾选态与折叠态不同步守卫（anchor L1462 修复后收敛）
    # 预置：面板头钮展开并切到 chart_font 页 → index2 入口（面板头钮 + 菜单 action）应勾选
    window.btn_header_chart_font.click()
    assert not window.right_panel.is_collapsed()
    assert window.btn_header_chart_font.isChecked()
    assert window.action_chart_font.isChecked()
    assert not window.btn_header_inspect.isChecked()
    assert not window.btn_header_ai.isChecked()

    # (a) 工具栏开关收起 → 所有页签入口回落（缺陷路径一）
    window.btn_toggle_right_panel.click()
    assert window.right_panel.is_collapsed()
    assert all(e is None or not e.isChecked() for e, _ in window._right_page_entries())

    # (b) 外部 set_collapsed(True) 收起 → 所有页签入口回落（缺陷路径二）
    window.btn_header_chart_font.click()
    assert not window.right_panel.is_collapsed()
    window.right_panel.set_collapsed(True)
    assert window.right_panel.is_collapsed()
    assert all(e is None or not e.isChecked() for e, _ in window._right_page_entries())

    # (c) 由任一面板头钮重新展开 → 该钮勾选、其余（含 action_chart_font）互斥回落（异 index）
    window.btn_header_inspect.click()
    assert not window.right_panel.is_collapsed()
    assert window.btn_header_inspect.isChecked()
    assert not window.btn_header_chart_font.isChecked()
    assert not window.action_chart_font.isChecked()
    assert not window.btn_header_ai.isChecked()
    # 同 index 设计：面板头图表字体钮与菜单 action_chart_font 同勾选
    window.btn_header_chart_font.click()
    assert window.btn_header_chart_font.isChecked()
    assert window.action_chart_font.isChecked()
    assert not window.btn_header_inspect.isChecked()


# ---------------------------------------------------------------------------
# ④ R6：btn_toggle_ribbon 仍不存在
# ---------------------------------------------------------------------------


def test_btn_toggle_ribbon_still_absent_and_ribbon_resident(window):
    assert not hasattr(window, "btn_toggle_ribbon")
    # 左栏开关只折叠 PanelContainer，不动 ribbon 本体（ribbon 常驻为中央区 item0）
    assert window.left_ribbon is not None
    central = window.centralWidget()
    assert central.layout().indexOf(window.left_ribbon) == 0


# ---------------------------------------------------------------------------
# ⑤/⑥ 面板头右操作区
# ---------------------------------------------------------------------------


def test_panel_headers_have_own_actions_with_tooltips(window):
    assert window.left_panel_header.action_count() >= 1
    assert window.right_panel_header.action_count() >= 1
    injected = (
        (window.btn_header_files, tr("sidebar.tab.files")),
        (window.btn_header_quickstart, tr("sidebar.tab.quickstart")),
        (window.btn_header_manual, tr("sidebar.tab.manual")),
        (window.btn_header_record, tr("sidebar.tab.record")),
        (window.btn_header_ai, tr("action.ai_interpret")),
    )
    for btn, tip in injected:
        assert btn.toolTip() == tip and btn.toolTip() != ""
        assert btn.icon().isNull() is False, "禁造空按钮（图标/入口必须真实存在）"


def test_left_header_entries_share_ribbon_toggle_group(window):
    """面板头「文件」入口 → 与 ribbon 页签入口同组互斥同步（T-1043 机制复用）。"""
    window.btn_header_files.click()
    assert not window.left_panel.is_collapsed()
    assert window.btn_header_files.isChecked()
    assert not window.ribbon_btn_settings.isChecked()
    assert not window.btn_header_manual.isChecked()

    entries = window._left_page_entries()
    assert (window.btn_header_files, 0) in entries
    assert (window.btn_header_manual, 2) in entries

    # 折叠 → 同组入口一律回落（不复用第二套同步逻辑）
    window.left_panel.set_collapsed(True)
    assert not window.btn_header_files.isChecked()


# ---------------------------------------------------------------------------
# ⑦ 图标扩容（D0）
# ---------------------------------------------------------------------------


def test_sidebar_icons_registered_and_assets_complete(qapp):
    assert theme.ICONS["sidebar_left"] == "generic/sidebar-left.svg"
    assert theme.ICONS["sidebar_right"] == "generic/sidebar-right.svg"
    assert len(theme.ICONS) == ICONS_LOGICAL_NAME_COUNT
    for style in ("generic", "macos", "win", "mint"):
        for filename in ("sidebar-left.svg", "sidebar-right.svg"):
            assert (_ICON_ROOT / style / filename).exists(), f"{style}/{filename} 缺失"
    for key in ("sidebar_left", "sidebar_right"):
        icon = theme.get_icon(key)
        assert icon is not None and not icon.isNull()


# ---------------------------------------------------------------------------
# ⑧ 静态纪律
# ---------------------------------------------------------------------------


def test_new_chrome_segments_have_no_dialog_thread_timer_or_hex_px(window):
    for fn in (
        _panel_toggle_button,
        _header_icon_button,
        window._sync_left_panel_toggle,
        window._on_toggle_left_panel,
    ):
        src = inspect.getsource(fn)
        for banned in ("QDialog(", "QThread(", "QTimer("):
            assert banned not in src, f"{fn} 引入 {banned}"

    # 激活态 = §五-6 内凹（取色一律 theme 键 bg0，禁 accent 实心 pill）
    for fn in (_panel_toggle_button, _header_icon_button):
        assert "bg0" in inspect.getsource(fn), f"{fn} 未走内凹（bg0）令牌"

    src = _MW_PY.read_text(encoding="utf-8")
    # 基线（T-1048 开工实读·T-1088 同步）：QDialog( = 0 / QThread( = 0 / QTimer( = 8（T-1086 _mt_play_timer +1）
    assert src.count("QDialog(") == MAINWINDOW_QDIALOG_COUNT
    assert src.count("QThread(") == MAINWINDOW_QTHREAD_COUNT
    assert src.count("QTimer(") == MAINWINDOW_QTIMER_COUNT

    for method in (MainWindow._create_toolbar, MainWindow._build_side_tabs):
        text = inspect.getsource(method)
        code = "\n".join(
            ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
        )
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), f"{method} 含硬编码 hex"
        assert not re.search(r"\b[0-9]+px\b", code), f"{method} 含 px 字面量"
