# SPDX-License-Identifier: GPL-3.0-only
"""分组标题共用构件（ARCH_ui_visual_language §五-2 · T-1033 阶段四「信息架构」）。

分组规范：``typography.h3`` 标题 + ``spacing.sm`` 上间距；**禁**用 `QGroupBox`
描边框做分组（现状 ``QGroupBox`` 边框感过重）。几何与取色一律走既有令牌
（禁 hex/px 字面量）。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from acouscope.ui import theme
from acouscope.ui.theme import TOKENS


def _section_qss(c: dict) -> str:
    """分组标题样式：h3 字阶 + 正文色（层级靠留白与底色阶梯，不靠描边）。"""
    ty = TOKENS["typography"]
    return (
        f"QLabel#sectionHeaderTitle {{ background: transparent; color: {c['text']}; "
        f"font-size: {ty['h3']}px; }}"
    )


class SectionHeader(QWidget):
    """分组标题：h3 字号 + 8 上间距（共用构件，ARCH §五-2）。"""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        sp = TOKENS["spacing"]
        col = QVBoxLayout(self)
        # 上间距 = spacing.sm（8）：分组与上一段留白靠明度差 + 留白，不用描边
        col.setContentsMargins(0, sp["sm"], 0, 0)
        col.setSpacing(0)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("sectionHeaderTitle")
        col.addWidget(self.title_label)

        self._refresh_style = theme.style_when_theme(self, _section_qss)

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        self.title_label.setText(text or "")

    def title(self) -> str:
        return self.title_label.text()
