# SPDX-License-Identifier: GPL-3.0-only
"""主窗常驻「支持一下」心跳按钮：非模态，点击仅发 ``encourageRequested``，由宿主开框。

自绘无关：图标走 theme 语义渲染；心跳由 ``QVariantAnimation`` 驱动 ``setIconSize``
（本档零 ``QTimer``，动画一律走 ``QVariantAnimation``）。
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtWidgets import QToolButton

from acouscope.i18n import tr
from acouscope.ui import theme

# 心跳图标尺寸与节奏（模块级给死；长度一律走常量，禁裸尺寸字面量）
_ICON_BASE_PX = 16
_ICON_PEAK_PX = 20
_PULSE_MS = 260
_PULSE_LOOPS = 3
_HOVER_LOOPS = 1

# 恒定占位尺寸：setIconSize 逐帧变化不得改变控件外接矩形（防整行随心跳横向抖动）
_BTN_W_PX = 96
_BTN_H_PX = 28


class EncourageButton(QToolButton):
    """主窗常驻支持入口：心跳式缩放图标，点击发信号（开框逻辑归宿主）。"""

    encourageRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText(tr("encourage.label"))
        self.setToolTip(tr("encourage.tip"))
        # QToolButton 默认 IconOnly 会把文字吞掉不可见，故显式图文并存
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIcon(theme.get_icon("encourage"))
        self.setIconSize(QSize(_ICON_BASE_PX, _ICON_BASE_PX))
        self.setFixedSize(_BTN_W_PX, _BTN_H_PX)

        self._pulsed = False
        self._anim = QVariantAnimation(self)
        # 一放一收靠**中段关键帧**，不靠「方向自动翻转」：Qt 的 loopCount>1 是每圈从
        # startValue 重启（`Direction` 实测成员仅 Forward/Backward，无 Alternate），
        # 只给 start=16/end=20 会做成长大后瞬间弹回的**锯齿**。
        self._anim.setStartValue(_ICON_BASE_PX)
        self._anim.setKeyValueAt(0.5, _ICON_PEAK_PX)
        self._anim.setEndValue(_ICON_BASE_PX)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setDuration(_PULSE_MS)
        self._anim.setLoopCount(_PULSE_LOOPS)
        # ★ 每圈 = 基线→峰值→基线；跳满 _PULSE_LOOPS 圈即停。禁 loopCount 0（=永久循环）
        self._anim.valueChanged.connect(self._on_pulse_value)
        self._anim.finished.connect(self._on_pulse_finished)

        self.clicked.connect(self._emit_requested)

    # ------------------------------------------------------------------
    # 对外信号（本档不 import 任何开框实现）
    # ------------------------------------------------------------------
    def _emit_requested(self, _checked: bool = False) -> None:
        self.encourageRequested.emit()

    # ------------------------------------------------------------------
    # 心跳
    # ------------------------------------------------------------------
    def _start_pulse(self, loops: int) -> None:
        if self._anim.state() == QAbstractAnimation.State.Running:
            return
        self._anim.setLoopCount(loops)
        self._anim.start()

    def _on_pulse_value(self, value) -> None:
        size = round(float(value))  # round 非 int：截断会让临近峰值的若干帧到不了 20
        self.setIconSize(QSize(size, size))

    def _on_pulse_finished(self) -> None:
        self.setIconSize(QSize(_ICON_BASE_PX, _ICON_BASE_PX))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pulsed:
            return
        self._pulsed = True
        self._start_pulse(_PULSE_LOOPS)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._start_pulse(_HOVER_LOOPS)
