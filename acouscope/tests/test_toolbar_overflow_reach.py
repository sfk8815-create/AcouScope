# SPDX-License-Identifier: GPL-3.0-only
"""G3：窄窗工具栏入口可达——常驻「更多」QToolButton 收纳 8 入口接原槽。

1600 宽时主工具栏 6 个 addWidget toggle + 分析工具栏 2 个 checkable 入口
可达；缩到 1000 宽后这 8 个入口从无障碍树整批消失（Qt 不会为 addWidget
的 widget 生成扩展菜单）。修复：主工具栏靠左常驻「更多」QToolButton +
QMenu，8 入口以 QAction 收纳并接到原有槽；原有 8 个 widget 不删/不隐。

变异：删掉溢出按钮注册到主工具栏（addWidget）⇒ 可达性断言翻红。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QToolBar, QToolButton

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow

_EXPECTED = (
    "overflowLeftPanel",
    "overflowRightPanel",
    "overflowBatch",
    "overflowRoomModal",
    "overflowRoomAcoustic",
    "overflowChartDesigner",
    "overflowPitchRulerOverlay",
    "overflowChartDesignerDialog",
)

_SLOT_NAMES = (
    "_on_toggle_left_panel",
    "_on_toggle_right_panel",
    "_on_workspace_toggle",
    "_on_tuning_ruler_toggled",
    "_on_chart_designer",
)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """不 show 的 MainWindow（沿用 test_cb012_toolbar_toggles.py 夹具口径）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


def test_overflow_button_and_actions(window):
    btn = window.btn_toolbar_overflow
    assert btn.objectName() == "toolbarOverflowBtn"
    menu = btn.menu()
    assert menu is not None
    acts = menu.actions()
    assert len(acts) == 8
    assert [a.objectName() for a in acts] == list(_EXPECTED)
    assert all(a.text().strip() for a in acts)


def test_overflow_actions_reach_original_slots(window, monkeypatch):
    calls = {}

    def _spy(name):
        def _record(*args):
            calls.setdefault(name, []).append(args)
        return _record

    for name in _SLOT_NAMES:
        monkeypatch.setattr(window, name, _spy(name))

    for act in window.btn_toolbar_overflow.menu().actions():
        act.trigger()

    assert set(calls) == set(_SLOT_NAMES)
    assert calls["_on_workspace_toggle"] == [
        ("batch",), ("room_modal",), ("room_acoustic",), ("chart_designer",),
    ]
    assert len(calls["_on_toggle_left_panel"]) == 1
    assert len(calls["_on_toggle_right_panel"]) == 1
    assert len(calls["_on_tuning_ruler_toggled"]) == 1
    assert len(calls["_on_chart_designer"]) == 1


def test_overflow_reachable_in_narrow_window(window, qapp):
    btn = window.btn_toolbar_overflow
    window.show()
    qapp.processEvents()
    window.resize(1000, 728)
    qapp.processEvents()
    try:
        ft = btn.parent()
        assert isinstance(ft, QToolBar)
        acts = ft.actions()
        idx = [
            i for i, a in enumerate(acts) if ft.widgetForAction(a) is btn
        ]
        # C2 真齿：真实可见性 = show() 后 isVisible() 为 True 且 已作为
        # QWidgetAction 反查得到。仅 setParent 而未 addWidget 时离屏实测
        # isVisible() 仍恒 True、geometry.right 恒 99，故旧的几何/宽度/
        # findChildren 三条「现状即绿」无齿；本复合断言把「已注册」并入
        # 可见性，删掉 addWidget 后 widgetForAction 反查变空 ⇒ 必翻红。
        assert btn.isVisible() is True and len(idx) == 1, (
            f"溢出按钮未真实可见地常驻主工具栏（未 addWidget）: "
            f"isVisible={btn.isVisible()}, widgetForAction idx={idx}"
        )
        # 全局右边界（右上角映射到屏幕坐标）须落在 1000 宽窗口内。
        global_right = btn.mapToGlobal(btn.rect().topRight()).x()
        assert global_right <= 1000, (
            f"溢出按钮全局右边界 {global_right} 超出 1000 宽窗口"
        )
        # 溢出按钮靠左常驻：widgetForAction 索引 < 第一个 toggle 的索引。
        toggle_idx = [
            i for i, a in enumerate(acts)
            if ft.widgetForAction(a) is not None
            and ft.widgetForAction(a).objectName().startswith("toggle")
        ]
        assert toggle_idx and idx[0] < min(toggle_idx), (
            f"溢出按钮索引 {idx[0]} 未排在首个 toggle {min(toggle_idx)} 之前"
        )
    finally:
        window.close()
        qapp.processEvents()
