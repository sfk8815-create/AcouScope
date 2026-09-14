# SPDX-License-Identifier: GPL-3.0-only
"""图表设计器面板（T-1044 P1：导出前设计交互）。

形态：**非模态抽屉**内容（`ui/widgets/drawer.open_drawer` 宿主，宽度 `DRAWER_WIDTH`），
上 = 实时预览区 / 下 = 参数区四组（② 版式 · ③ 配色 · ④ 字体 · ⑥ 导出）。

规范遵循：
- `ARCH_ui_visual_language §五-7` 参数三段式（名称上 / 控件中 / 单位下）；
- `§五-8` 参数范围可见性（端点数值标签，**禁裸数字框**）；
- `§五b` 开关语义（入口可再点关闭、抽屉有可见 ✕ —— 由 drawer 构件与入口接线承担）；
- `§八` 禁拟物；取色/尺寸一律走 `theme.TOKENS`（禁 hex / 数值 px 字面量）。

预览性能（Step 0 实测，见 `.pi/reports/T-1044_report.json`）：
- 波形 72dpi ≈ 82ms（≤150ms → **拖动实时，不防抖**）；
- 语谱图 1025×3000 72dpi ≈ 535ms（>400ms → **重图降采样预览 + 防抖 200ms**）。
- 预览与导出**同源**：同一 `FigureExporter` / `_export_current_view` 路径，仅 DPI 与
  是否为预览（重图降采样）不同。本面板不自行渲染，渲染由宿主注入 `preview_renderer`。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.panels.section_header import SectionHeader

# 抽屉宽度：预览 + 参数并置（ARCH_chart_designer §二 裁定 ~860）
DRAWER_WIDTH = 860

# 预览 DPI（低分辨率预览；导出走模板/用户 DPI）
PREVIEW_DPI = 72
# 重图防抖（ms）：Step 0 实测 >400ms 档 → 防抖 + 降采样
PREVIEW_DEBOUNCE_MS = 200
# 重图模式（与 main_window.analysis_tab_bar 逻辑索引一致）：语谱图 / MFCC
HEAVY_MODES = (2, 5)

# UI 暴露的配色档（`ARCH §三③` 四档；inferno 登记不暴露）
PALETTE_CHOICES = ("default", "grayscale", "colorblind", "viridis")

_PREVIEW_NAME = "acouscope_chart_designer_preview.png"


def _param_qss(c: dict) -> str:
    """三段式参数列样式：名称走正文色，单位/范围走弱化色（禁描边）。"""
    ty = TOKENS["typography"]
    return (
        f"QLabel#chartDesignerParamName {{ color: {c['text']}; "
        f"font-size: {ty['body_sm']}px; }}"
        f"QLabel#chartDesignerParamUnit {{ color: {c['text_sub']}; "
        f"font-size: {ty['caption_sm']}px; }}"
    )


def _preview_qss(c: dict) -> str:
    """预览框：边框取主题 border 色，内距走 spacing（白底由导出侧保证）。"""
    elev = TOKENS["elevation"]
    sp = TOKENS["spacing"]
    return (
        "QLabel#chartDesignerPreview {"
        f"  background: {c['bg1']};"
        f"  border: {elev['border']}px solid {c['border']};"
        f"  padding: {sp['xs']}px;"
        "}"
    )


class _ParamField(QWidget):
    """三段式参数列：名称（上）+ 控件（中）+ 单位·范围（下）。

    `ARCH §五-7`（禁把标签挤在左侧 / 禁用 tooltip 代替可见标签）+
    `§五-8`（端点数值标签 = 可用范围线索）。
    """

    def __init__(self, name: str, control: QWidget, hint: str = "", parent=None):
        super().__init__(parent)
        sp = TOKENS["spacing"]
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(sp["xs"])

        self.name_label = QLabel(name, self)
        self.name_label.setObjectName("chartDesignerParamName")
        self.unit_label = QLabel(hint, self)
        self.unit_label.setObjectName("chartDesignerParamUnit")

        col.addWidget(self.name_label)
        col.addWidget(control)
        col.addWidget(self.unit_label)
        control.setToolTip(name)

        self._refresh_style = theme.style_when_theme(self, _param_qss)


class ChartDesignerPanel(QWidget):
    """图表设计器：上预览 / 下参数区四组（P1）。

    信号：
        paramsChanged        — 任一参数变化（宿主据此更新会话态 + 全局默认）
        previewUpdated(bool) — 预览刷新结束（True = 已刷新，False = 无数据/失败）
        exportRequested      — 点「导出」（宿主走既有导出单路径）
        fontSettingsRequested— 点「字体设置…」（保留跳转既有入口）
    """

    paramsChanged = pyqtSignal()
    previewUpdated = pyqtSignal(bool)
    exportRequested = pyqtSignal()
    fontSettingsRequested = pyqtSignal()

    def __init__(self, settings=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings
        self._renderer = None
        self._mode_provider = None

        root = QVBoxLayout(self)
        sp = TOKENS["spacing"]
        root.setContentsMargins(sp["sm"], sp["sm"], sp["sm"], sp["sm"])
        root.setSpacing(sp["sm"])

        root.addWidget(self._build_preview(), 1)
        root.addWidget(self._build_params())

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)

        self._load_defaults()
        self._connect()
        self._refresh_font_labels()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build_preview(self) -> QWidget:
        self.preview_label = QLabel(tr("chart_designer.preview_placeholder"))
        self.preview_label.setObjectName("chartDesignerPreview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(TOKENS["control"]["h_lg"] * 6)
        self.preview_label.setWordWrap(True)
        self._refresh_preview_style = theme.style_when_theme(self.preview_label, _preview_qss)
        return self.preview_label

    def _build_params(self) -> QWidget:
        from acouscope.visualization.exporters import FigureExporter
        from acouscope.visualization.mpl_style import JOURNAL_TEMPLATES

        box = QWidget(self)
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(TOKENS["spacing"]["md"])

        # ② 版式
        col_layout = QVBoxLayout()
        col_layout.addWidget(SectionHeader(tr("chart_designer.group.layout")))
        self.cmb_template = QComboBox()
        for name in JOURNAL_TEMPLATES:
            label = tr("chart_designer.template_default") if name == "default" else name
            self.cmb_template.addItem(label, name)
        col_layout.addWidget(_ParamField(tr("chart_designer.template"), self.cmb_template))
        self.spn_width = QDoubleSpinBox()
        self.spn_width.setRange(2.0, 12.0)
        self.spn_width.setSingleStep(0.1)
        col_layout.addWidget(
            _ParamField(tr("chart_designer.width"), self.spn_width, "2.0 – 12.0 in")
        )
        self.spn_height = QDoubleSpinBox()
        self.spn_height.setRange(1.5, 10.0)
        self.spn_height.setSingleStep(0.1)
        col_layout.addWidget(
            _ParamField(tr("chart_designer.height"), self.spn_height, "1.5 – 10.0 in")
        )
        self.chk_grid = QCheckBox(tr("chart_designer.grid"))
        col_layout.addWidget(self.chk_grid)
        col_layout.addStretch(1)
        row.addLayout(col_layout)

        # ③ 配色
        col_palette = QVBoxLayout()
        col_palette.addWidget(SectionHeader(tr("chart_designer.group.palette")))
        self.cmb_palette = QComboBox()
        for name in PALETTE_CHOICES:
            self.cmb_palette.addItem(tr(f"chart_designer.palette.{name}"), name)
        col_palette.addWidget(_ParamField(tr("chart_designer.palette"), self.cmb_palette))
        col_palette.addStretch(1)
        row.addLayout(col_palette)

        # ④ 字体（保留跳转既有字体设置入口 —— 报告给理由）
        col_font = QVBoxLayout()
        col_font.addWidget(SectionHeader(tr("chart_designer.group.font")))
        self.lbl_font_latin = QLabel("")
        self.lbl_font_cjk = QLabel("")
        col_font.addWidget(
            _ParamField(tr("chart_designer.font_latin"), self.lbl_font_latin, "—")
        )
        col_font.addWidget(
            _ParamField(tr("chart_designer.font_cjk"), self.lbl_font_cjk, "—")
        )
        self.btn_font_jump = QPushButton(tr("chart_designer.font_jump"))
        col_font.addWidget(self.btn_font_jump)
        col_font.addStretch(1)
        row.addLayout(col_font)

        # ⑥ 导出
        col_export = QVBoxLayout()
        col_export.addWidget(SectionHeader(tr("chart_designer.group.export")))
        self.cmb_format = QComboBox()
        for name in FigureExporter.SUPPORTED_FORMATS:
            self.cmb_format.addItem(name.upper(), name)
        col_export.addWidget(_ParamField(tr("chart_designer.format"), self.cmb_format))
        self.spn_dpi = QSpinBox()
        self.spn_dpi.setRange(72, 1200)
        self.spn_dpi.setSingleStep(1)
        col_export.addWidget(_ParamField(tr("chart_designer.dpi"), self.spn_dpi, "72 – 1200"))
        self.btn_export = QPushButton(tr("chart_designer.export"))
        col_export.addWidget(self.btn_export)
        col_export.addStretch(1)
        row.addLayout(col_export)

        return box

    # ------------------------------------------------------------------
    # 默认值 / 连接
    # ------------------------------------------------------------------

    def _load_defaults(self) -> None:
        """装载默认值：① 全局默认（Settings）→ ② 控件；装载期屏蔽信号。"""
        s = self._settings
        template = getattr(s, "default_journal_template", "default") or "default"
        palette = getattr(s, "chart_designer_palette", "default") or "default"
        fmt = getattr(s, "default_format", "svg") or "svg"
        dpi = getattr(s, "default_dpi", 300) or 300
        width = float(getattr(s, "chart_designer_figsize_w", 0.0) or 0.0)
        height = float(getattr(s, "chart_designer_figsize_h", 0.0) or 0.0)
        grid = bool(getattr(s, "chart_designer_grid", True))

        widgets = (
            self.cmb_template, self.spn_width, self.spn_height, self.chk_grid,
            self.cmb_palette, self.cmb_format, self.spn_dpi,
        )
        for w in widgets:
            w.blockSignals(True)

        self._select(self.cmb_template, template)
        self._select(self.cmb_palette, palette)
        self._select(self.cmb_format, fmt)
        self.spn_dpi.setValue(int(dpi))
        self.chk_grid.setChecked(grid)
        self._sync_figsize(width, height)

        for w in widgets:
            w.blockSignals(False)

    def _connect(self) -> None:
        self.cmb_template.currentIndexChanged.connect(self._on_template_changed)
        for w in (self.spn_width, self.spn_height, self.spn_dpi):
            w.valueChanged.connect(self._on_param_changed)
        self.chk_grid.toggled.connect(self._on_param_changed)
        self.cmb_palette.currentIndexChanged.connect(self._on_param_changed)
        self.cmb_format.currentIndexChanged.connect(self._on_param_changed)
        self.btn_export.clicked.connect(self.exportRequested.emit)
        self.btn_font_jump.clicked.connect(self.fontSettingsRequested.emit)

    @staticmethod
    def _select(cmb: QComboBox, value: str) -> None:
        idx = cmb.findData(value)
        cmb.setCurrentIndex(idx if idx >= 0 else 0)

    def _sync_figsize(self, width: float, height: float) -> None:
        """画幅：0（未设置）→ 取当前模板的 figure_width / figure_height。"""
        from acouscope.visualization.mpl_style import JOURNAL_TEMPLATES

        tpl = JOURNAL_TEMPLATES.get(self.cmb_template.currentData() or "default", {})
        self.spn_width.setValue(width if width > 0 else float(tpl.get("figure_width", 3.5)))
        self.spn_height.setValue(height if height > 0 else float(tpl.get("figure_height", 2.5)))

    # ------------------------------------------------------------------
    # 宿主注入
    # ------------------------------------------------------------------

    def set_preview_renderer(self, renderer) -> None:
        """注入预览渲染函数 `renderer(path: Path, dpi: int, preview: bool) -> bool`。

        渲染由宿主承担（与导出**同一条** `_export_current_view` 路径），本面板不自行建图
        → 保证「所见即所得」；返回 False 表示无音频/无数据/失败（显示占位文案）。
        """
        self._renderer = renderer

    def set_mode_provider(self, provider) -> None:
        """注入当前分析视图索引函数（决定是否重图 → 防抖档）。"""
        self._mode_provider = provider

    def set_font_labels(self, latin: str, cjk: str) -> None:
        """刷新 ④ 字体组显示（字体值唯一源仍在 chart_font_dialog / Settings）。"""
        def _show(value: str) -> str:
            return tr("chart_designer.font_auto") if not value or value == "auto" else value

        self.lbl_font_latin.setText(_show(latin))
        self.lbl_font_cjk.setText(_show(cjk))

    def _refresh_font_labels(self) -> None:
        try:
            from acouscope.visualization.mpl_style import default_cjk_font, font_chain
        except Exception:
            return
        s = self._settings
        latin = getattr(s, "chart_font_latin", "auto") or "auto"
        cjk = getattr(s, "chart_font_cjk", "auto") or "auto"
        try:
            chain = font_chain(latin, cjk)
            self.set_font_labels(chain[0] if chain else latin, default_cjk_font())
        except Exception:
            self.set_font_labels(latin, cjk)

    # ------------------------------------------------------------------
    # 参数 / 预览
    # ------------------------------------------------------------------

    def params(self) -> dict:
        """当前会话参数（持久化第 ① 层：本次会话，供预览与导出使用）。"""
        return {
            "template": self.cmb_template.currentData() or "default",
            "palette": self.cmb_palette.currentData() or "default",
            "width": float(self.spn_width.value()),
            "height": float(self.spn_height.value()),
            "grid": bool(self.chk_grid.isChecked()),
            "format": self.cmb_format.currentData() or "svg",
            "dpi": int(self.spn_dpi.value()),
        }

    def _on_template_changed(self, _index: int) -> None:
        """换模板 → 画幅回该模板默认（保持版式自洽），再走统一变化路径。"""
        self.spn_width.blockSignals(True)
        self.spn_height.blockSignals(True)
        self._sync_figsize(0.0, 0.0)
        self.spn_width.blockSignals(False)
        self.spn_height.blockSignals(False)
        self._on_param_changed()

    def _on_param_changed(self, *_args) -> None:
        self.paramsChanged.emit()
        self.schedule_preview()

    def schedule_preview(self) -> None:
        """按视图类型排程预览：重图防抖 `PREVIEW_DEBOUNCE_MS`，轻图即时（Step 0）。"""
        mode = self._mode_provider() if self._mode_provider is not None else 0
        if mode in HEAVY_MODES:
            self._timer.start(PREVIEW_DEBOUNCE_MS)
        else:
            self._timer.stop()  # 轻图：撤销可能在排的重图预览，避免重复渲染
            self._render_preview()

    def render_now(self) -> bool:
        """立即渲染预览（打开抽屉 / 测试用；跳过防抖）。"""
        self._timer.stop()
        return self._render_preview()

    def _render_preview(self) -> bool:
        if self._renderer is None:
            return False
        path = Path(tempfile.gettempdir()) / _PREVIEW_NAME
        try:
            ok = bool(self._renderer(path, PREVIEW_DPI, True))
        except Exception:
            ok = False
        if ok and self._show_pixmap(path):
            self.previewUpdated.emit(True)
            return True
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(tr("chart_designer.preview_placeholder"))
        self.previewUpdated.emit(False)
        return False

    def _show_pixmap(self, path: Path) -> bool:
        pix = QPixmap(str(path))
        if pix.isNull():
            return False
        target = self.preview_label.size()
        self.preview_label.setPixmap(
            pix.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return True
