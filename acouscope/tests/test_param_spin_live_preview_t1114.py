# SPDX-License-Identifier: GPL-3.0-only
"""T-1114 ParamSpinBox 双模：拖拽中是否实时发 valueChanged。

判据：
① 提交模式（set_live_preview(False)）⇒ 拖拽中计数 0（显示仍跟手），释放后计数恰 1；
② 默认实时模式未被改坏 ⇒ 同样拖拽计数 ≥ 1。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from acouscope.ui.widgets.param_spin import ParamSpinBox


def _mouse(spin, etype, x, y, button, buttons, mods=Qt.KeyboardModifier.NoModifier):
    QCoreApplication.sendEvent(
        spin,
        QMouseEvent(etype, QPointF(float(x), float(y)), QPointF(float(x), float(y)),
                    button, buttons, mods),
    )


def _press(spin, x, y):
    _mouse(spin, QMouseEvent.Type.MouseButtonPress, x, y,
           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)


def _move(spin, x, y):
    _mouse(spin, QMouseEvent.Type.MouseMove, x, y,
           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)


def _release(spin, x, y):
    _mouse(spin, QMouseEvent.Type.MouseButtonRelease, x, y,
           Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def _new_spin():
    spin = ParamSpinBox()
    spin.setRange(400, 480)
    spin.setDecimals(1)
    spin.setSingleStep(0.5)
    spin.setValue(440.0)
    return spin


def test_non_live_mode_emits_once_on_release(qapp):
    """提交模式：拖拽中不发信号但显示跟手；释放后恰发一次。"""
    spin = _new_spin()
    spin.set_live_preview(False)
    spin._cursor_dx = lambda: 60          # 每次 move 累计 60 × 0.5 = 30

    seen: list[float] = []
    spin.valueChanged.connect(lambda v: seen.append(float(v)))

    _press(spin, 40, 12)
    _move(spin, 50, 12)
    _move(spin, 60, 12)                   # 累计 120 × 0.5 = 60 → clamp 480.0

    assert len(seen) == 0, f"拖拽中不应发信号，实际 {seen}"
    assert spin.value() == 480.0, f"显示应跟手到 480.0，实际 {spin.value()}"

    _release(spin, 60, 12)
    assert len(seen) == 1, f"释放后应恰发一次，实际 {seen}"
    assert spin.value() == 480.0

    # 对照：默认实时模式未被改坏
    live = _new_spin()
    live._cursor_dx = lambda: 20
    live_seen: list[float] = []
    live.valueChanged.connect(lambda v: live_seen.append(float(v)))

    _press(live, 40, 12)
    _move(live, 50, 12)
    assert len(live_seen) >= 1, "默认实时模式应在拖拽中发信号"
    _release(live, 50, 12)


def test_focusout_during_non_live_drag_commits(qapp):
    """提交模式下拖拽中焦点丢失 ⇒ 也必须补发一次（reviewer 发现的边界缺陷）。"""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QFocusEvent

    spin = _new_spin()
    spin.set_live_preview(False)
    spin._cursor_dx = lambda: 20          # 20 × 0.5 = +10 → 450.0

    seen: list[float] = []
    spin.valueChanged.connect(lambda v: seen.append(float(v)))

    _press(spin, 40, 12)
    _move(spin, 50, 12)
    assert len(seen) == 0, f"拖拽中不应发信号，实际 {seen}"
    assert spin.value() == 450.0

    QCoreApplication.sendEvent(spin, QFocusEvent(QEvent.Type.FocusOut))
    assert not spin._dragging, "焦点丢失后应退出拖拽态"
    assert len(seen) == 1, f"焦点丢失后应补发一次，实际 {seen}"
    assert spin.value() == 450.0
