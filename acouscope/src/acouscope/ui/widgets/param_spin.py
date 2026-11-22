# SPDX-License-Identifier: GPL-3.0-only
"""Blender 式数值框：左键拖拽擦除（隐藏光标循环 / Shift 精调 / Ctrl 吸附）。

只在拖拽真发生（位移达到 Qt 起拖阈值）时夺取鼠标；单击仍进入文本编辑。
取色与尺寸一律走主题令牌，本文件零字面 hex、零字面 px。
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import QApplication, QDoubleSpinBox

from acouscope.ui import theme
from acouscope.utils.number_expr import parse_number

# Ctrl/Cmd 拖拽的吸附基数 = 步进的整数倍（值落在该倍数上）
_SNAP_STEPS = 10


class ParamSpinBox(QDoubleSpinBox):
    """带拖拽擦除的数值框。

    位移 < QApplication.startDragDistance() ⇒ 视为单击，交给基类（保留文本编辑）；
    达到阈值 ⇒ 进入擦除态：隐藏系统光标、光标锚定并循环回绕、按水平位移改值；
    Shift ⇒ 步进 /10；Ctrl（macOS 为 Cmd）⇒ 吸附到 步进×10 的整倍数。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos: QPoint | None = None
        self._anchor = QPoint()
        self._base_value = 0.0
        self._dx_accum = 0
        self._dragging = False
        self._tracking_before = self.keyboardTracking()
        self._live = True

    # ---- 纯逻辑（无副作用，便于单测） ---------------------------------
    @staticmethod
    def should_warp(cursor_pos: QPoint, anchor: QPoint) -> bool:
        """光标离锚点超过一个 xxl 间距 ⇒ 需要回绕（循环拖拽）。"""
        limit = int(theme.TOKENS["spacing"]["xxl"])
        return (abs(cursor_pos.x() - anchor.x()) >= limit
                or abs(cursor_pos.y() - anchor.y()) >= limit)

    def value_after_drag(self, base: float, dx: int, modifiers) -> float:
        """（基准值, 累计水平位移, 修饰键）→ 目标值；含 Shift 精调 / Ctrl 吸附 / clamp。"""
        factor = 0.1 if (modifiers & Qt.KeyboardModifier.ShiftModifier) else 1.0
        raw = base + dx * self.singleStep() * factor
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            snap = self.singleStep() * _SNAP_STEPS
            raw = round(raw / snap) * snap
        return min(max(raw, self.minimum()), self.maximum())

    # ---- 文本解析（T-1118：字段内算式） --------------------------------
    def valueFromText(self, text: str) -> float:  # noqa: N802 (Qt 命名)
        """先按数值表达式解析（2*pi / min(4,3) / 1.5k）；不可解析则保留原值。

        ★ 不把解析失败交给 `super()`：Qt 对非法文本返回 0.0，经 clamp 会静默跳到下限
        （实测 `valueFromText("abc")` → 400.0），属用户可感知的误改。
        """
        parsed = parse_number(text)
        if parsed is None:
            return self.value()
        return min(max(parsed, self.minimum()), self.maximum())

    def validate(self, text: str, pos: int):  # noqa: N802 (Qt 命名)
        """输入期放行表达式：能算成数 ⇒ Acceptable；否则保持 Intermediate 让用户继续敲。"""
        if parse_number(text) is not None:
            return (QValidator.State.Acceptable, text, pos)
        state, _t, _p = super().validate(text, pos)
        if state == QValidator.State.Invalid:
            return (QValidator.State.Intermediate, text, pos)
        return (state, text, pos)

    def _cursor_dx(self) -> int:
        """当前光标相对锚点的水平偏移（测试可覆写以脱离真光标）。"""
        return QCursor.pos().x() - self._anchor.x()

    def set_live_preview(self, enabled: bool) -> None:
        """拖拽期间是否实时发 valueChanged。False ⇒ 拖拽只改显示，释放时统一发一次。"""
        self._live = bool(enabled)

    def _apply_drag_value(self, target: float) -> None:
        """写值：实时模式直发信号；提交模式在拖拽中屏蔽信号。"""
        if self._live:
            self.setValue(target)
            return
        blocked = self.blockSignals(True)
        try:
            self.setValue(target)
        finally:
            self.blockSignals(blocked)

    # ---- 拖拽态 -------------------------------------------------------
    def _begin_drag(self) -> None:
        self._dragging = True
        self._dx_accum = 0
        self.setKeyboardTracking(False)
        self.lineEdit().setReadOnly(True)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
        self.grabMouse()

    def _commit_if_needed(self) -> None:
        """提交模式：拖拽结束时补发一次 valueChanged（释放 / 焦点丢失共用）。"""
        if not self._live:
            self.valueChanged.emit(self.value())

    def _end_drag(self) -> None:
        if not self._dragging:
            return
        self._dragging = False
        try:
            self.releaseMouse()
        finally:
            QGuiApplication.restoreOverrideCursor()
            self.lineEdit().setReadOnly(False)
            self.setKeyboardTracking(self._tracking_before)

    # ---- 事件 ---------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._anchor = QCursor.pos()
            self._base_value = self.value()
            self._dx_accum = 0
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if not self._dragging:
            moved = (event.position().toPoint() - self._press_pos).manhattanLength()
            if moved < QApplication.startDragDistance():
                super().mouseMoveEvent(event)
                return
            self._begin_drag()
        self._dx_accum += self._cursor_dx()
        if self.should_warp(QCursor.pos(), self._anchor):
            QCursor.setPos(self._anchor)
        self._apply_drag_value(self.value_after_drag(
            self._base_value, self._dx_accum, event.modifiers()))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._end_drag()
            self._press_pos = None
            self._commit_if_needed()
            event.accept()
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def focusOutEvent(self, event):
        if self._dragging:
            self._commit_if_needed()
        self._end_drag()
        super().focusOutEvent(event)
