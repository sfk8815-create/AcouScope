# SPDX-License-Identifier: GPL-3.0-only
"""可折叠面板组件（V099_PANEL_V1，三面板骨架基础件 + T-1033 信息架构共用构件）。"""
from acouscope.ui.widgets.panels.empty_state import EmptyState
from acouscope.ui.widgets.panels.inspector_panel import InspectorPanel
from acouscope.ui.widgets.panels.panel_container import PanelContainer
from acouscope.ui.widgets.panels.panel_header import PanelHeader, attach_panel_header
from acouscope.ui.widgets.panels.section_header import SectionHeader

__all__ = [
    "EmptyState",
    "InspectorPanel",
    "PanelContainer",
    "PanelHeader",
    "SectionHeader",
    "attach_panel_header",
]
