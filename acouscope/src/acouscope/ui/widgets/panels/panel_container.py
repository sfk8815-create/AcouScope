# SPDX-License-Identifier: GPL-3.0-only
"""PanelContainer：无标题栏可折叠面板容器（V099_PANEL_V1 · T-1012 形态）。

T-1012 真机反馈修订（ARCH §六）：
- 标题栏横条（panelHeader/图标/标题/▼ 文本折叠钮）全部取消，内容区占满整面板；
- 折叠仅隐藏内容；面板宽度压到 0 由 workspace（QSplitter handle 位三角）完成；
- 保留 set_collapsed / toggle / is_collapsed / collapsedChanged(bool) 契约与
  serialize / restore。
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from acouscope.ui import theme


class _ContentArea(QWidget):
    """面板内容区：isVisible() 报告内容区自身的可见状态（意图态）。

    折叠/展开仅通过 setVisible 改变内容区自身状态；PanelContainer 通常
    内嵌于 QSplitter（离屏测试中顶层窗口亦未 show），按 QWidget 默认语义
    （要求全部祖先可见）将无法直接观测折叠/展开。故这里以自身可见状态
    为准：折叠 → False，展开 → True。Qt 内部布局/绘制/事件走 C++ 可见性，
    不受本 Python 层定义影响。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._self_visible = True  # 内容区自身可见状态（默认展开）

    def setVisible(self, visible: bool) -> None:
        self._self_visible = bool(visible)
        super().setVisible(visible)

    def isVisible(self) -> bool:  # type: ignore[override]
        return self._self_visible


class PanelContainer(QWidget):
    """可折叠面板容器（QSplitter 友好：仅 setVisible 折叠，不改变布局拓扑）。

    - 无标题栏横条；title/icon_name 仅作兼容入参保留，不再渲染
    - 折叠三角钮由 workspace 的 QSplitter handle（分界框线）承载，
      见 widgets/panels/workspace.py 的实现选型说明。
    """

    collapsedChanged = pyqtSignal(bool)  # 折叠 True / 展开 False

    def __init__(self, title: str = "", icon_name: str = "", parent=None):
        super().__init__(parent)
        self._collapsed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 内容区（objectName="panelContent"，边距 = spacing xs）----
        self.panelContent = _ContentArea(self)
        self.panelContent.setObjectName("panelContent")
        sp = theme.TOKENS["spacing"]
        self._content_layout = QVBoxLayout(self.panelContent)
        self._content_layout.setContentsMargins(sp["xs"], sp["xs"], sp["xs"], sp["xs"])
        self._content_layout.setSpacing(sp["xs"])
        outer.addWidget(self.panelContent)

    # ------------------------------------------------------------------
    # 内容 API
    # ------------------------------------------------------------------

    def set_content(self, widget) -> None:
        """替换内容区：清空既有 widget（setParent(None)）后放入新 widget。"""
        for i in reversed(range(self._content_layout.count())):
            item = self._content_layout.takeAt(i)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._content_layout.addWidget(widget)

    def add_widget(self, widget) -> None:
        """向内容区追加 widget。"""
        self._content_layout.addWidget(widget)

    # ------------------------------------------------------------------
    # 折叠 API
    # ------------------------------------------------------------------

    def set_collapsed(self, collapsed: bool) -> None:
        """折叠/展开；状态变化才发 collapsedChanged 信号。"""
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.panelContent.setVisible(not collapsed)
        self.collapsedChanged.emit(collapsed)

    def toggle(self) -> None:
        """切换折叠状态。"""
        self.set_collapsed(not self._collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def serialize(self) -> dict:
        return {"collapsed": self._collapsed}

    def restore(self, state: dict) -> None:
        """从 state.get("collapsed", False) 恢复；状态一致则无副作用。"""
        self.set_collapsed(bool((state or {}).get("collapsed", False)))
