# SPDX-License-Identifier: GPL-3.0-only
"""图表字体设置面板（西文/中文分开设置，供各功能模块共用入口）。

UI 宪法条 3（对话框最小化）：本体为 QWidget，由右侧抽屉
（`acouscope.ui.widgets.drawer.open_drawer`）非模态承载——无 exec 调用、无模态
按钮盒、不阻塞主窗工作区。

原「确定 / 取消」语义改为**即时生效**：选择变化即发 `fontChanged(latin, cjk)`，
由调用侧（主窗 / 3D 视图）负责持久化与重绘；`latin()` / `cjk()` 仍可随时读当前值。
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from acouscope.ui import theme

AUTO_LABEL = "自动（按语言推荐）"

# 抽屉宽度：与录音设置(360) / 设置·帮助(560) / AI 释图(640) 互不复用同一实例
DRAWER_WIDTH = 420


class ChartFontDialog(QWidget):
    """图表字体设置：西文/数字字体与中文字体分开选择。

    作用于所有导出图表与 3D 视图。选择变化即发 fontChanged(latin, cjk)，
    调用侧负责持久化与刷新；也可随时用 latin()/cjk() 读当前值。
    类名保留 Dialog 仅为兼容既有调用与测试导入，实际非对话框。
    """

    fontChanged = pyqtSignal(str, str)

    def __init__(self, latin: str = "auto", cjk: str = "auto", parent=None):
        super().__init__(parent)

        sp = theme.TOKENS["spacing"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp["sm"], sp["sm"], sp["sm"], sp["sm"])
        layout.setSpacing(sp["sm"])

        layout.addWidget(QLabel(
            "西文/数字字体与中文字体分开设置，应用于全部导出图表与 3D 视图。\n"
            "「自动」时按界面语言选择推荐字体。"
        ))

        form = QFormLayout()

        try:
            from acouscope.visualization.mpl_style import (
                list_cjk_fonts,
                list_latin_fonts,
            )
            latin_fonts = list_latin_fonts()
            cjk_fonts = list_cjk_fonts()
        except Exception:
            latin_fonts, cjk_fonts = [], []

        self.cmb_latin = QComboBox()
        self.cmb_latin.addItem(AUTO_LABEL, "auto")
        for name in latin_fonts:
            self.cmb_latin.addItem(name, name)
        form.addRow("西文 / 数字字体:", self.cmb_latin)

        self.cmb_cjk = QComboBox()
        self.cmb_cjk.addItem(AUTO_LABEL, "auto")
        for name in cjk_fonts:
            self.cmb_cjk.addItem(name, name)
        form.addRow("中文字体:", self.cmb_cjk)

        layout.addLayout(form)

        self.preview = QLabel("Aa 440 Hz · Harmonics · 谐波列 · 语谱图")
        self.preview.setObjectName("chartFontPreview")
        layout.addWidget(self.preview)

        layout.addWidget(QLabel(
            "提示：学术图表常用 Times New Roman（西文）+ 宋体/苹方（中文）；"
            "设置会持久化，重启后保留。"
        ))
        layout.addStretch(1)

        # 初值装载期间屏蔽信号，避免构造即触发一次 fontChanged
        self.cmb_latin.blockSignals(True)
        self.cmb_cjk.blockSignals(True)
        self._select(self.cmb_latin, latin)
        self._select(self.cmb_cjk, cjk)
        self.cmb_latin.blockSignals(False)
        self.cmb_cjk.blockSignals(False)

        self.cmb_latin.currentIndexChanged.connect(self._on_changed)
        self.cmb_cjk.currentIndexChanged.connect(self._on_changed)
        self._refresh_preview()

        # 样式注册：随主题刷新（严禁硬编码 hex）
        self._refresh_style = theme.style_when_theme(self, self._build_qss)

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------

    @staticmethod
    def _build_qss(c: dict) -> str:
        """预览框：边框取 theme border 色，内外距/字号取 TOKENS。"""
        ty = theme.TOKENS["typography"]
        sp = theme.TOKENS["spacing"]
        elev = theme.TOKENS["elevation"]
        return (
            "QLabel#chartFontPreview {"
            f"  border: {elev['border']}px solid {c['border']};"
            f"  padding: {sp['sm']}px;"
            f"  font-size: {ty['body_lg']}px;"
            "}"
        )

    # ------------------------------------------------------------------
    # 行为
    # ------------------------------------------------------------------

    @staticmethod
    def _select(cmb: QComboBox, value: str):
        idx = cmb.findData(value)
        cmb.setCurrentIndex(idx if idx >= 0 else 0)

    def _on_changed(self):
        """选择变化：刷新预览 + 外抛 fontChanged（调用侧即时持久化）。"""
        self._refresh_preview()
        self.fontChanged.emit(self.latin(), self.cjk())

    def _refresh_preview(self):
        latin = self.cmb_latin.currentData()
        cjk = self.cmb_cjk.currentData()
        font = QFont()
        if latin and latin != "auto":
            font.setFamily(latin)
        elif cjk and cjk != "auto":
            font.setFamily(cjk)
        self.preview.setFont(font)

    def latin(self) -> str:
        return self.cmb_latin.currentData() or "auto"

    def cjk(self) -> str:
        return self.cmb_cjk.currentData() or "auto"
