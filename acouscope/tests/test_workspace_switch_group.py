"""T-1054 批0：主工具栏「工作区开关组」验收（令 §五 1~6）。

覆盖：开关组结构 / 切页与再点收回 / 互斥 / 右键入口状态一致性 /
房间两开关启用（批3）+ 图表设计器禁用占位（待启用）/ 状态源禁引入新机制（无 QDialog·线程·定时器·hex·px）。
开关组位置：file_toolbar 右栏开关之后、前置分隔符。
"""

import inspect
import re

import pytest

pytest.importorskip("PyQt6")

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow

# 开关组 4 钮：属性名 → (objectName, 图标, tooltip 键)（令 §一）
_SWITCHES = {
    "btn_toggle_batch_workspace": ("toggleBatchWorkspaceBtn", "layers", "action.batch"),
    "btn_toggle_room_modal": ("toggleRoomModalBtn", "room_modal", "toolbar.room_modal"),
    "btn_toggle_room_acoustic": ("toggleRoomAcousticBtn", "room_acoustic", "toolbar.room_acoustic"),
    "btn_toggle_chart_designer": ("toggleChartDesignerBtn", "chart_designer", "toolbar.chart_designer"),
}


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（不 show）；teardown close。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


@pytest.fixture
def tb(window):
    """主工具栏（file_toolbar，含左右栏开关与开关组）。"""
    return window.btn_toggle_right_panel.parent()


# ---------------------------------------------------------------------------
# §五 1 结构：4 新钮 + 2 既有；objectName 正确；批处理开关父对象为主工具栏
# ---------------------------------------------------------------------------


def test_switch_group_structure(window, tb):
    buttons = [getattr(window, attr) for attr in _SWITCHES]
    assert len(buttons) == 4
    for b, (objname, _icon, _tip) in zip(buttons, _SWITCHES.values()):
        assert b.objectName() == objname, f"{objname} objectName 缺失"
        assert b.parent() is tb, f"{objname} 不在主工具栏"
        assert b.isCheckable(), f"{objname} 须为 checkable（复用 _panel_toggle_button）"
        assert b.text() == "", f"{objname} 应为 icon-only"
    # 既有左右栏开关仍在工具栏
    for b in (window.btn_toggle_left_panel, window.btn_toggle_right_panel):
        assert b.parent() is tb


# ---------------------------------------------------------------------------
# §五 2 切页与再点收回
# ---------------------------------------------------------------------------


def test_batch_toggle_switch_page_roundtrip(window):
    btn = window.btn_toggle_batch_workspace
    assert window.central_stack.currentIndex() == 0
    btn.click()
    assert window.central_stack.currentIndex() == 1
    assert btn.isChecked()
    btn.click()  # 再点 → 收回 index0
    assert window.central_stack.currentIndex() == 0
    assert not btn.isChecked()


# ---------------------------------------------------------------------------
# §五 3 互斥：任一时刻至多一个 checked
# ---------------------------------------------------------------------------


def test_switch_group_mutually_exclusive(window):
    all_buttons = [getattr(window, attr) for attr in _SWITCHES]
    window.btn_toggle_batch_workspace.click()
    assert window.btn_toggle_batch_workspace.isChecked()
    assert sum(b.isChecked() for b in all_buttons) <= 1, "至多一个 checked（互斥）"
    # 收回后全组无勾选
    window.btn_toggle_batch_workspace.click()
    assert sum(b.isChecked() for b in all_buttons) == 0


# ---------------------------------------------------------------------------
# §五 4 ★ 状态一致性：右键入口进/出后开关自动同步
# ---------------------------------------------------------------------------


def test_external_entries_sync_switch_state(window):
    window._open_batch_workspace()  # 模拟右键「批处理…」入口
    assert window.central_stack.currentIndex() == 1
    assert window.btn_toggle_batch_workspace.isChecked(), "右键进批处理后开关未自动点亮（状态分裂）"
    window._exit_batch_workspace()
    assert window.central_stack.currentIndex() == 0
    assert not window.btn_toggle_batch_workspace.isChecked(), "退出批处理后开关未自动反勾"


# ---------------------------------------------------------------------------
# §五 5 占位：图表设计器仍禁用（tooltip 含「待启用」）；房间两开关已启用
# （tooltip 无待启用标记、接槽可点、互斥、再点收回）——批3 扩面⑦（用例数不变）
# ---------------------------------------------------------------------------


def test_placeholder_switches_disabled_with_pending_tooltip(window):
    """图表设计器保持禁用占位；房间模态/房间声学已启用并可切全铺页。"""
    from acouscope.ui.theme import ICONS

    # 图表设计器：仍为禁用占位 + tooltip 含待启用 + 图标非空
    btn = window.btn_toggle_chart_designer
    assert btn.isEnabled() is False, "chart_designer 应为禁用占位"
    tip = tr("toolbar.chart_designer")
    assert "待启用" in tip or "待啟用" in tip or "pending" in tip, "chart_designer tooltip 缺待启用标记"
    assert btn.toolTip() == tip and btn.toolTip().strip(), "chart_designer tooltip 缺失/不一致"
    assert "chart_designer" in ICONS, "图标 chart_designer 未登记于 ICONS"
    assert btn.icon().isNull() is False, "chart_designer 图标为空（R7 无障碍）"

    # 房间模态 / 房间声学：启用 + tooltip 无待启用标记 + 图标非空 + 接槽可点
    for key, objname, icon_name in (
        ("room_modal", "toggleRoomModalBtn", "room_modal"),
        ("room_acoustic", "toggleRoomAcousticBtn", "room_acoustic"),
    ):
        b = getattr(window, "btn_toggle_" + key)
        assert b.isEnabled() is True, f"{objname} 应为启用"
        tip = tr(f"toolbar.{key}")
        assert "待启用" not in tip and "待啟用" not in tip and "pending" not in tip, \
            f"{key} tooltip 不应含待启用标记"
        assert b.toolTip() == tip and b.toolTip().strip(), f"{objname} tooltip 缺失/不一致"
        assert icon_name in ICONS, f"图标 {icon_name} 未登记于 ICONS"
        assert b.icon().isNull() is False, f"{objname} 图标为空（R7 无障碍）"

    # 接槽可点：点1 → 切页 + checked；互斥（批处理/房间模态/房间声学至多一个 checked）
    window.btn_toggle_room_modal.click()
    assert window.central_stack.currentIndex() == 2
    assert window.btn_toggle_room_modal.isChecked()
    assert not window.btn_toggle_room_acoustic.isChecked()
    assert not window.btn_toggle_batch_workspace.isChecked()
    window.btn_toggle_room_acoustic.click()
    assert window.central_stack.currentIndex() == 3
    assert window.btn_toggle_room_acoustic.isChecked()
    assert not window.btn_toggle_room_modal.isChecked()
    assert not window.btn_toggle_batch_workspace.isChecked()
    # 再点 → 收回 index0 + 反勾选
    window.btn_toggle_room_acoustic.click()
    assert window.central_stack.currentIndex() == 0
    assert not window.btn_toggle_room_acoustic.isChecked()
    assert not window.btn_toggle_room_modal.isChecked()

    # T-1054b3 补正（幕僚闸门第1轮，教训 Y：新入口 ⇒ 新守卫）：
    # 房间声学页内「关闭」→ cancelled → 回 index0 且开关反勾选（批3 删抽屉通路后曾为死键）
    from acouscope.ui.widgets.room_acoustics_dialog import RoomAcousticsDialog

    window.btn_toggle_room_acoustic.click()
    assert window.central_stack.currentIndex() == 3
    dlg = window.central_stack.currentWidget().findChild(RoomAcousticsDialog)
    assert dlg is not None, "房间声学页内应嵌入 RoomAcousticsDialog"
    dlg.btn_close.click()
    assert window.central_stack.currentIndex() == 0
    assert window.btn_toggle_room_acoustic.isChecked() is False


# ---------------------------------------------------------------------------
# §五 6 状态源禁新机制：_set_workspace_page/_on_workspace_toggle 无 QDialog/线程/定时器/hex/px
# ---------------------------------------------------------------------------


def test_switch_state_source_no_forbidden_mechanisms(window):
    for fn in (window._set_workspace_page, window._on_workspace_toggle):
        src = inspect.getsource(fn)
        for banned in ("QDialog(", "QThread(", "QTimer("):
            assert banned not in src, f"{fn} 引入 {banned}"
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
        )
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), f"{fn} 含硬编码 hex"
        assert not re.search(r"\b[0-9]+px\b", code), f"{fn} 含 px 字面量"