# SPDX-License-Identifier: GPL-3.0-only
"""面板头共用构件（ARCH_ui_visual_language §五-1 · T-1033 阶段四「信息架构」）。

统一「左标题 + 右操作区插槽」一套面板头，禁止各面板再写一套样式：
- 高 = ``TOKENS.control.h_lg``（与控件高度阶梯同口径）；
- 底边 = ``TOKENS.elevation.border`` 像素 ``colors()['border']`` 分隔线（与抽屉面板头同一视觉基准）；
- 标题 = ``typography.body_lg`` + ``colors()['text']``。

几何与取色一律走既有令牌（禁 hex/px 字面量；禁局部 setStyleSheet 绕过主题）。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from acouscope.ui import theme
from acouscope.ui.theme import TOKENS


def _header_qss(c: dict) -> str:
    """面板头样式：底边分隔 + 标题字阶；取色/几何全部令牌插值。"""
    elev = TOKENS["elevation"]["border"]
    ty = TOKENS["typography"]
    return (
        f"QFrame#panelHeader {{ background: transparent; border: none; "
        f"border-bottom: {elev}px solid {c['border']}; }}"
        f"QLabel#panelHeaderTitle {{ background: transparent; color: {c['text']}; "
        f"font-size: {ty['body_lg']}px; }}"
    )


class PanelHeader(QFrame):
    """面板头：左标题 + 右操作区插槽（共用构件，ARCH §五-1）。"""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panelHeader")
        self.setFixedHeight(TOKENS["control"]["h_lg"])

        sp = TOKENS["spacing"]
        row = QHBoxLayout(self)
        row.setContentsMargins(sp["md"], 0, sp["xs"], 0)
        row.setSpacing(sp["xs"])

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("panelHeaderTitle")
        row.addWidget(self.title_label)
        row.addStretch(1)

        # 右操作区插槽：落地处注入动作控件（本任务三处落地未注入，见报告）
        self._action_layout = QHBoxLayout()
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action_layout.setSpacing(sp["xs"])
        row.addLayout(self._action_layout)

        self._refresh_style = theme.style_when_theme(self, _header_qss)

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        """设置标题文案（随页面/语言变化时由落地处调用）。"""
        self.title_label.setText(text or "")

    def title(self) -> str:
        return self.title_label.text()

    def add_action(self, widget) -> None:
        """向右侧操作区插槽追加控件（关闭钮/开关/细标签等）。"""
        self._action_layout.addWidget(widget)

    def action_count(self) -> int:
        """右操作区控件数（结构断言用）。"""
        return self._action_layout.count()


def attach_panel_header(panel, title: str = "") -> PanelHeader:
    """把面板头挂到面板内容**上方**（面板布局首项，整栏全宽）。

    Args:
        panel: 具自身布局的面板容器（如 ``PanelContainer`` / 分析区 ``QWidget``）。
        title: 面板标题文案（应已过 i18n）。

    Returns:
        挂上的 ``PanelHeader`` 实例（供落地处 set_title / add_action）。
    """
    header = PanelHeader(title, panel)
    layout = panel.layout()
    if layout is not None:
        layout.insertWidget(0, header)
    return header
