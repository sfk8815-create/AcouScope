# SPDX-License-Identifier: GPL-3.0-only
"""空态共用构件（ARCH_ui_visual_language §五-3 · T-1033 阶段四「信息架构」）。

规范：无内容时**必须**给出「一句话说明 + 主操作按钮 + 拖放提示」三要素，
居中、取 ``colors()['sub']``（``text_sub``）；禁空白面板。

三要素 objectName 固定（``emptyStateMessage`` / ``emptyStateAction`` /
``emptyStateDropHint``），供落地处与回归断言按结构取用；几何/取色一律走既有令牌
（禁 hex/px 字面量，禁局部 setStyleSheet 绕过主题）。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from acouscope.ui import theme
from acouscope.ui.theme import TOKENS


def _empty_qss(c: dict) -> str:
    """空态样式：说明与拖放提示同为 text_sub（层级靠留白，不靠字号）。"""
    ty = TOKENS["typography"]
    body = ty["body"]
    return (
        f"QLabel#emptyStateMessage {{ background: transparent; color: {c['sub']}; "
        f"font-size: {body}px; }}"
        f"QLabel#emptyStateDropHint {{ background: transparent; color: {c['sub']}; "
        f"font-size: {body}px; }}"
    )


class EmptyState(QWidget):
    """空态：说明 + 主操作按钮 + 拖放提示（共用构件，ARCH §五-3）。"""

    actionTriggered = pyqtSignal()  # 主操作按钮点击 → 落地处接线到真实入口

    def __init__(
        self,
        message: str = "",
        action_text: str = "",
        drop_hint: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        sp = TOKENS["spacing"]
        col = QVBoxLayout(self)
        col.setContentsMargins(sp["xl"], sp["lg"], sp["xl"], sp["lg"])
        col.setSpacing(sp["sm"])
        col.addStretch(1)

        self.lbl_message = QLabel(message, self)
        self.lbl_message.setObjectName("emptyStateMessage")
        self.lbl_message.setWordWrap(True)
        self.lbl_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.lbl_message)

        self.btn_action: QPushButton | None = None
        if action_text:
            self.btn_action = QPushButton(action_text, self)
            self.btn_action.setObjectName("emptyStateAction")
            self.btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_action.clicked.connect(self.actionTriggered.emit)
            col.addWidget(self.btn_action, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_drop_hint: QLabel | None = None
        if drop_hint:
            self.lbl_drop_hint = QLabel(drop_hint, self)
            self.lbl_drop_hint.setObjectName("emptyStateDropHint")
            self.lbl_drop_hint.setWordWrap(True)
            self.lbl_drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(self.lbl_drop_hint)

        col.addStretch(1)
        self._refresh_style = theme.style_when_theme(self, _empty_qss)

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def set_message(self, text: str) -> None:
        self.lbl_message.setText(text or "")

    def message(self) -> str:
        return self.lbl_message.text()

    def set_drop_hint(self, text: str) -> None:
        """更新拖放提示文案（构件无提示标签时静默忽略）。"""
        if self.lbl_drop_hint is not None:
            self.lbl_drop_hint.setText(text or "")

    def set_action_text(self, text: str) -> None:
        """更新主操作按钮文案（构件无按钮时静默忽略）。"""
        if self.btn_action is not None:
            self.btn_action.setText(text or "")
