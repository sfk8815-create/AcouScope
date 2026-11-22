# SPDX-License-Identifier: GPL-3.0-only
"""T-1116 铺设：论文图导出对话框 4 个数值框换装 ParamSpinBox（实时档，导出时取值）。"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from acouscope.ui.widgets.param_spin import ParamSpinBox


def _press(w, x=40, y=12):
    QCoreApplication.sendEvent(
        w, QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(float(x), float(y)),
                       QPointF(float(x), float(y)),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier))


def _move(w, x=50, y=12):
    QCoreApplication.sendEvent(
        w, QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(float(x), float(y)),
                       QPointF(float(x), float(y)),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier))


def _release(w, x=50, y=12):
    QCoreApplication.sendEvent(
        w, QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(float(x), float(y)),
                       QPointF(float(x), float(y)),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier))


def test_paper_figure_spins_are_param_spin(qapp):
    """四个数值框均换装；锚定偏移拖拽 +5 音分，导出取值路径不受影响。"""
    from acouscope.ui.widgets.paper_figure_dialog import PaperFigureDialog

    dlg = PaperFigureDialog()
    for name in ("spin_start", "spin_end", "spin_window_start", "spin_anchor"):
        assert isinstance(getattr(dlg, name), ParamSpinBox), name

    # 默认「锚未提供」会禁用锚定框（禁用控件不吃鼠标事件）；先解除
    dlg.chk_anchor_pending.setChecked(False)
    anchor = dlg.spin_anchor
    assert anchor.isEnabled()
    anchor.setValue(0.0)
    anchor._cursor_dx = lambda: 5          # 5 × 1 音分
    _press(anchor)
    _move(anchor)
    _release(anchor)
    assert anchor.value() == pytest.approx(5.0), anchor.value()
    assert anchor.decimals() == 2 and anchor.objectName() == "paperFigureAnchorCents"
