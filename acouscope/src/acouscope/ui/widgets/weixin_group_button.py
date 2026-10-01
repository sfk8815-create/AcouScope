# SPDX-License-Identifier: GPL-3.0-only
"""主窗常驻「微信群」闪耀入口：非模态，点击仅发 ``weixinRequested``，由宿主开二维码窗。"""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QToolButton

from acouscope.i18n import tr
from acouscope.ui import theme

# 闪耀节奏（模块级给死；长度一律走常量，禁裸尺寸字面量）
_SHIMMER_MIN_OPACITY = 0.45
_SHIMMER_MS = 900
_SHIMMER_LOOPS = 3
_HOVER_LOOPS = 1

# 恒定占位尺寸：与心跳图标同宽同高 ⇒ 两钮成组、行高不抬升
_BTN_W_PX = 96
_BTN_H_PX = 28


class WeixinGroupButton(QToolButton):
    """主窗常驻微信群入口：透明度呼吸闪耀，点击发信号（开窗逻辑归宿主）。"""

    weixinRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText(tr("weixin_group.label"))
        self.setToolTip(tr("weixin_group.tip"))
        # QToolButton 默认 IconOnly 会把文字吞掉不可见，故显式图文并存
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIcon(theme.get_icon("weixin_group"))
        self.setFixedSize(_BTN_W_PX, _BTN_H_PX)

        self._effect = QGraphicsOpacityEffect(self)
        # QGraphicsOpacityEffect 默认 0.7，须显式归满，否则未跳动画前整钮发暗
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)

        self._shimmered = False
        self._shimmer = QVariantAnimation(self)
        # 一放一收靠**中段关键帧**，不靠「方向自动翻转」：Qt 的 loopCount>1 是每圈从
        # startValue 重启（`Direction` 实测成员仅 Forward/Backward，无 Alternate），
        # 只给 start=1.0/end=0.45 会做成长暗后瞬间回满的**锯齿**。
        self._shimmer.setStartValue(1.0)
        self._shimmer.setKeyValueAt(0.5, _SHIMMER_MIN_OPACITY)
        self._shimmer.setEndValue(1.0)
        self._shimmer.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._shimmer.setDuration(_SHIMMER_MS)
        self._shimmer.setLoopCount(_SHIMMER_LOOPS)
        # ★ 跳满 _SHIMMER_LOOPS 圈即停。禁 loopCount 0（=永久循环）
        self._shimmer.valueChanged.connect(self._on_shimmer_value)
        self._shimmer.finished.connect(self._on_shimmer_finished)

        self.clicked.connect(self._emit_requested)

    # ------------------------------------------------------------------
    # 对外信号（本档不 import 任何开窗实现）
    # ------------------------------------------------------------------
    def _emit_requested(self, _checked: bool = False) -> None:
        self.weixinRequested.emit()

    # ------------------------------------------------------------------
    # 闪耀（透明度呼吸；零尺寸变化，与邻居的尺寸缩放观感区分）
    # ------------------------------------------------------------------
    def _start_shimmer(self, loops: int) -> None:
        if self._shimmer.state() == QAbstractAnimation.State.Running:
            return
        self._shimmer.setLoopCount(loops)
        self._shimmer.start()

    def _on_shimmer_value(self, value) -> None:
        self._effect.setOpacity(float(value))

    def _on_shimmer_finished(self) -> None:
        self._effect.setOpacity(1.0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._shimmered:
            return
        self._shimmered = True
        self._start_shimmer(_SHIMMER_LOOPS)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._start_shimmer(_HOVER_LOOPS)