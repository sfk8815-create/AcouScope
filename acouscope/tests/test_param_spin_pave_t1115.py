# SPDX-License-Identifier: GPL-3.0-only
"""T-1115 铺设两个点位：谱图动态范围（释放提交）+ 房间模态 6 个参数（实时档）。

判据：
① `SpectrogramWidget.spn_dr` 为 ParamSpinBox 且提交模式：拖拽中 `_update_image`
   调用 0 次（不重绘），释放后恰 1 次；
② `RoomModesWidget` 六个数值框全部为 ParamSpinBox，拖拽改值不触发 `_on_calculate`
   （该页计算由按钮驱动，拖拽只改值）。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from acouscope.ui.widgets.param_spin import ParamSpinBox


def _mouse(w, etype, x, y, button, buttons, mods=Qt.KeyboardModifier.NoModifier):
    QCoreApplication.sendEvent(
        w,
        QMouseEvent(etype, QPointF(float(x), float(y)), QPointF(float(x), float(y)),
                    button, buttons, mods),
    )


def _press(w, x=40, y=12):
    _mouse(w, QMouseEvent.Type.MouseButtonPress, x, y,
           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)


def _move(w, x=50, y=12):
    _mouse(w, QMouseEvent.Type.MouseMove, x, y,
           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)


def _release(w, x=50, y=12):
    _mouse(w, QMouseEvent.Type.MouseButtonRelease, x, y,
           Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def test_spectrogram_dr_commits_on_release(qapp):
    """谱图动态范围：拖拽只跟手，释放才触发一次整幅重算。"""
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = SpectrogramWidget()
    spin = w.spn_dr
    assert isinstance(spin, ParamSpinBox), type(spin)

    calls = {"n": 0}
    w._update_image = lambda: calls.__setitem__("n", calls["n"] + 1)

    spin._cursor_dx = lambda: 4            # 每次 +4 × 5 dB，两次累计 +40（60 → 100）
    base = spin.value()

    _press(spin)
    _move(spin)
    _move(spin)
    assert calls["n"] == 0, f"拖拽中不应整幅重算，实际 {calls['n']}"
    assert spin.value() == base + 40.0, spin.value()

    _release(spin)
    assert calls["n"] == 1, f"释放后应恰重算一次，实际 {calls['n']}"


def test_room_modes_spins_are_param_spin_and_calc_untouched(qapp):
    """房间模态：六个数值框均换装；拖拽改值不触发模态重算。"""
    from acouscope.ui.widgets.room_modes import RoomModesWidget

    w = RoomModesWidget()
    names = ("spin_lx", "spin_ly", "spin_lz", "spin_max_freq", "spin_speed", "spin_q")
    for name in names:
        assert isinstance(getattr(w, name), ParamSpinBox), name

    calls = {"n": 0}
    w._on_calculate = lambda: calls.__setitem__("n", calls["n"] + 1)

    spin = w.spin_lx
    spin._cursor_dx = lambda: 20           # 20 × 0.1 = +2.0 m（6.0 → 8.0）
    _press(spin)
    _move(spin)
    _release(spin)

    assert spin.value() == pytest.approx(8.0), spin.value()
    assert calls["n"] == 0, f"拖拽不应触发计算，实际 {calls['n']}"

    # 既有交互不受影响：点「计算模态」仍能算（按钮信号未动）
    assert w.btn_calculate.isEnabled()
