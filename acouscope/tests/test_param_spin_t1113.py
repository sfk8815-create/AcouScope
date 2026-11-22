# SPDX-License-Identifier: GPL-3.0-only
"""T-1113 数值框拖拽擦除 · Blender 式。

用例对应 §判据：
① test_drag_dx_maps_to_value      — 位移→改值 + Shift 精调
② test_ctrl_snaps_and_text_lock   — Ctrl 吸附 + 拖拽态文本锁定/释放后复原
③ test_subthreshold_move_keeps_value — 起拖阈值以下的微移不进入擦除态
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from acouscope.ui.widgets.param_spin import ParamSpinBox


def _mouse(spin, etype, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    """发鼠标事件（参考 test_workspace_drag_grip_t1108.py）。"""
    QCoreApplication.sendEvent(
        spin,
        QMouseEvent(etype, QPointF(float(x), float(y)), QPointF(float(x), float(y)),
                    button, buttons, mods),
    )


def _press(spin, x, y):
    _mouse(spin, QMouseEvent.Type.MouseButtonPress, x, y)


def _move(spin, x, y, mods=Qt.KeyboardModifier.NoModifier):
    _mouse(spin, QMouseEvent.Type.MouseMove, x, y, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton, mods=mods)


def _release(spin, x, y):
    _mouse(spin, QMouseEvent.Type.MouseButtonRelease, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton)


def test_drag_dx_maps_to_value(qapp):
    """位移 60px × 步长 0.5 = 30.0；Shift 精调为位移 × 步长 × 0.1 = 3.0。"""
    spin = ParamSpinBox()
    spin.setRange(400, 480)
    spin.setDecimals(1)
    spin.setSingleStep(0.5)
    spin.setValue(440.0)

    # 覆写 _cursor_dx 以脱离真光标
    spin._cursor_dx = lambda: 60

    _press(spin, 40, 12)
    _move(spin, 50, 12)
    assert spin.value() == 470.0, f"expected 470.0, got {spin.value()}"
    _release(spin, 50, 12)

    # Shift 精调
    spin.setValue(440.0)
    _press(spin, 40, 12)
    _move(spin, 50, 12, mods=Qt.KeyboardModifier.ShiftModifier)
    assert spin.value() == 443.0, f"expected 443.0 (shift), got {spin.value()}"
    _release(spin, 50, 12)


def test_ctrl_snaps_and_text_lock(qapp):
    """Ctrl 吸附到步长×10（5.0）的整倍数；拖拽中锁定文本，释放后复原。"""
    spin = ParamSpinBox()
    spin.setRange(400, 480)
    spin.setDecimals(1)
    spin.setSingleStep(0.5)
    spin.setValue(440.0)

    spin._cursor_dx = lambda: 13
    tracking_before = spin.keyboardTracking()

    _press(spin, 40, 12)
    _move(spin, 53, 12, mods=Qt.KeyboardModifier.ControlModifier)
    # step*10 = 5.0; 440 + 13*0.5 = 446.5 → snap to 445.0
    assert spin.value() == 445.0, f"expected 445.0 (snapped), got {spin.value()}"
    # 拖拽中锁定文本编辑（QLineEdit 无 textInteractionFlags，用只读态）
    assert spin.lineEdit().isReadOnly(), "line edit should be read-only during drag"
    _release(spin, 53, 12)

    # 释放后复原
    assert not spin.lineEdit().isReadOnly(), "line edit should be editable after drag"
    assert spin.keyboardTracking() == tracking_before


def test_subthreshold_move_keeps_value(qapp):
    """位移 < startDragDistance 不进入擦除态；also test should_warp boundary.

    Qt 的起拖阈值在 offscreen 上通常 >2，所以 2px 微移应停留在普通编辑态。
    """
    spin = ParamSpinBox()
    spin.setRange(400, 480)
    spin.setDecimals(1)
    spin.setSingleStep(0.5)
    spin.setValue(440.0)

    changed_count = 0

    def on_changed(_v):
        nonlocal changed_count
        changed_count += 1

    spin.valueChanged.connect(on_changed)

    _press(spin, 40, 12)
    # 仅移动 2px（< startDragDistance）
    _move(spin, 42, 12)
    assert not spin._dragging, "subthreshold move should not start drag"
    assert not spin.lineEdit().isReadOnly(), "line edit editable before threshold reached"
    _release(spin, 42, 12)

    assert spin.value() == 440.0
    assert changed_count == 0

    # should_warp 边界：条件为 >= limit（xxl=48）⇒ +48 真、+47 假
    from PyQt6.QtCore import QPoint
    anchor = QPoint(100, 50)
    assert ParamSpinBox.should_warp(QPoint(anchor.x() + 49, 50), anchor) is True
    assert ParamSpinBox.should_warp(QPoint(anchor.x() + 47, 50), anchor) is False
