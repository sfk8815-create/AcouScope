# SPDX-License-Identifier: GPL-3.0-only
"""pyqtgraph 图表右键菜单助手：三语自建菜单替代内置英文菜单。

内置菜单含 Mouse Mode / Downsample / Antialias 等对业务图表无效的
选项；本助手关闭内置菜单，改为只挂真实可用动作的 QMenu。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu

import pyqtgraph as pg


def install_plot_menu(plot: pg.PlotWidget, actions: list) -> None:
    """为 PlotWidget 安装三语右键菜单。

    actions: [(menu_text, callback), ...] —— 只保留真实可用的动作。
    """
    plot.getPlotItem().setMenuEnabled(False)  # 关闭内置菜单
    plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _show_menu(pos):
        menu = QMenu(plot)
        for text, cb in actions:
            menu.addAction(text, cb)
        menu.exec(plot.viewport().mapToGlobal(pos))

    plot.customContextMenuRequested.connect(_show_menu)
