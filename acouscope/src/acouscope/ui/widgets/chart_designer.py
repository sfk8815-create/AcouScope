# SPDX-License-Identifier: GPL-3.0-only
"""图表设计器面板（T-1044 P1：导出前设计交互）。

形态：**中央 index4 全铺页**内容（T-1054 批4a：抽屉通路已退役），
上 = 实时预览区 / 下 = 参数区四组（② 版式 · ③ 配色 · ④ 字体 · ⑥ 导出）。

规范遵循：
- `ARCH_ui_visual_language §五-7` 参数三段式（名称上 / 控件中 / 单位下）；
- `§五-8` 参数范围可见性（端点数值标签，**禁裸数字框**）；
- `§五b` 开关语义（入口可再点关闭；可见关闭出口 = 工作区开关组 / 菜单 action）；
- `§八` 禁拟物；取色/尺寸一律走 `theme.TOKENS`（禁 hex / 数值 px 字面量）。

预览性能（Step 0 实测，见 `.pi/reports/T-1044_report.json`）：
- 波形 72dpi ≈ 82ms（≤150ms → **拖动实时，不防抖**）；
- 语谱图 1025×3000 72dpi ≈ 535ms（>400ms → **重图降采样预览 + 防抖 200ms**）。
- 预览与导出**同源**：同一 `FigureExporter` / `_export_current_view` 路径，仅 DPI 与
  是否为预览（重图降采样）不同。本面板不自行渲染，渲染由宿主注入 `preview_renderer`。
- 高 DPI 屏（T-1080 M-1）：预览出图 DPI 与显示缩放一律按 `devicePixelRatio` 折算到
  **物理像素**，`PREVIEW_DPI`（72）只是 dpr=1 基线；导出 DPI 路径不经此处，零影响。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.panels.section_header import SectionHeader

# 预览 DPI 基线（dpr=1；低分辨率快速出图。高 DPI 屏按 devicePixelRatio 倍乘，
# 见 `_preview_dpi`；导出走模板/用户 DPI，与本常量无关）
PREVIEW_DPI = 72
# 重图防抖（ms）：Step 0 实测 >400ms 档 → 防抖 + 降采样
PREVIEW_DEBOUNCE_MS = 200
# 重图模式（与 main_window.analysis_tab_bar 逻辑索引一致）：语谱图 / MFCC
HEAVY_MODES = (2, 5)

# UI 暴露的配色档（`ARCH §三③` 四档；inferno 登记不暴露）
PALETTE_CHOICES = ("default", "grayscale", "colorblind", "viridis")

_PREVIEW_NAME = "acouscope_chart_designer_preview.png"

# T-1046 P3：可共享样式 JSON 的格式标识与版本（沿用 annotation/export.py 范式）
STYLE_FORMAT = "acouscope-chart-style"
STYLE_VERSION = 1
# 两击确认的武装超时（ms）：第二次点击生效，超时自动解除
CONFIRM_ARM_MS = 5000


def _parse_ref_values(text: str) -> list[float]:
    """解析参考线数值输入：逗号/空格/斜杠分隔的 Hz 数；非法项忽略。"""
    out: list[float] = []
    for tok in text.replace("，", ",").replace("/", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            v = float(tok)
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return out


def _param_qss(c: dict) -> str:
    """三段式参数列样式：名称走正文色，单位/范围走最弱字色（禁描边）。

    T-1080 M-2：hint 由 `text_sub` 降为 `text_faint`（层级 = 分区标题 > 字段标签 > hint）。
    """
    ty = TOKENS["typography"]
    return (
        f"QLabel#chartDesignerParamName {{ color: {c['text']}; "
        f"font-size: {ty['body_sm']}px; }}"
        f"QLabel#chartDesignerParamUnit {{ color: {c['text_faint']}; "
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
    T-1080 M-2：标签/ hint 显式左对齐（与同列控件左侧沿齐），行距取 `spacing` 刻度。
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
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        self.name_label.setAlignment(left)
        self.unit_label.setAlignment(left)

        col.addWidget(self.name_label)
        col.addWidget(control)
        col.addWidget(self.unit_label)
        control.setToolTip(name)

        self._refresh_style = theme.style_when_theme(self, _param_qss)


def _editor_column(group_key: str) -> QVBoxLayout:
    """编辑器分区列（T-1080 M-2）：标题 + 字段，列内节拍统一取 `spacing` 刻度。

    只统一间距，不改结构：仍是 6 列分区、仍是 `SectionHeader` + `_ParamField`。
    """
    col = QVBoxLayout()
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(TOKENS["spacing"]["sm"])
    col.addWidget(SectionHeader(tr(group_key)))
    return col


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
        root.addWidget(self._build_preset_bar())

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)

        # T-1046 P3：预设状态（会话层兜底 + 两击确认 + 导入告警）
        self._session_presets: dict[str, dict] = {}
        self._import_warnings: list[str] = []
        self._armed: str | None = None
        self._arm_timer = QTimer(self)
        self._arm_timer.setSingleShot(True)
        self._arm_timer.timeout.connect(self._disarm)

        self._load_defaults()
        self._connect()
        self._refresh_preset_list()
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
        sp = TOKENS["spacing"]
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(sp["md"])

        # ① 内容外壳（T-1045 P2：标题/副标题/来源/脚注）
        col_content = _editor_column("chart_designer.group.content")
        self.edt_title = QLineEdit()
        col_content.addWidget(_ParamField(tr("chart_designer.title_text"), self.edt_title))
        self.edt_subtitle = QLineEdit()
        col_content.addWidget(_ParamField(tr("chart_designer.subtitle"), self.edt_subtitle))
        self.edt_source = QLineEdit()
        col_content.addWidget(_ParamField(tr("chart_designer.source"), self.edt_source))
        self.edt_footer = QLineEdit()
        col_content.addWidget(_ParamField(tr("chart_designer.footer"), self.edt_footer))
        col_content.addStretch(1)
        row.addLayout(col_content)

        # ② 版式
        col_layout = _editor_column("chart_designer.group.layout")
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
        col_palette = _editor_column("chart_designer.group.palette")
        self.cmb_palette = QComboBox()
        for name in PALETTE_CHOICES:
            self.cmb_palette.addItem(tr(f"chart_designer.palette.{name}"), name)
        col_palette.addWidget(_ParamField(tr("chart_designer.palette"), self.cmb_palette))
        col_palette.addStretch(1)
        row.addLayout(col_palette)

        # ④ 字体（保留跳转既有字体设置入口 —— 报告给理由）
        col_font = _editor_column("chart_designer.group.font")
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
        col_export = _editor_column("chart_designer.group.export")
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

        # ⑤ 参考线（T-1045 P2：阈值线 + AT-01 精度闸门）
        col_ref = _editor_column("chart_designer.group.reference")
        self.edt_ref_values = QLineEdit()
        self.edt_ref_values.setPlaceholderText("0 Hz")
        col_ref.addWidget(
            _ParamField(tr("chart_designer.ref_values"), self.edt_ref_values, "Hz")
        )
        self.cmb_ref_linestyle = QComboBox()
        self.cmb_ref_linestyle.addItem(tr("chart_designer.ref_linestyle.dashed"), "--")
        self.cmb_ref_linestyle.addItem(tr("chart_designer.ref_linestyle.dotted"), ":")
        col_ref.addWidget(
            _ParamField(tr("chart_designer.ref_linestyle"), self.cmb_ref_linestyle)
        )
        self.edt_ref_ink = QLineEdit()
        self.edt_ref_ink.setPlaceholderText(tr("chart_designer.ref_ink"))
        col_ref.addWidget(
            _ParamField(tr("chart_designer.ref_ink"), self.edt_ref_ink, "#RRGGBB")
        )
        self.chk_at01 = QCheckBox(tr("chart_designer.at01_gate"))
        self.chk_at01.setToolTip(tr("chart_designer.at01_hint"))
        col_ref.addWidget(self.chk_at01)
        col_ref.addStretch(1)
        row.addLayout(col_ref)

        return box

    def _build_preset_bar(self) -> QWidget:
        """⑦ 预设与共享栏（T-1046 P3）：保存/加载/删除 + 样式 JSON 导入/导出。

        位于参数区下方（不占参数列），复用既有构件；删除/覆盖重名一律两击确认
        （禁静默覆盖 / 禁新建模态弹窗类）。
        """
        sp = TOKENS["spacing"]
        bar = QWidget(self)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(sp["sm"])

        row.addWidget(QLabel(tr("chart_designer.preset.name"), bar))
        self.cmb_preset = QComboBox(bar)
        self.cmb_preset.setMinimumWidth(TOKENS["control"]["h_lg"] * 6)
        row.addWidget(self.cmb_preset)
        self.edt_preset_name = QLineEdit(bar)
        self.edt_preset_name.setPlaceholderText(tr("chart_designer.preset.name_hint"))
        row.addWidget(self.edt_preset_name, 1)
        self.btn_preset_save = QPushButton(tr("chart_designer.preset.save"), bar)
        self.btn_preset_load = QPushButton(tr("chart_designer.preset.load"), bar)
        self.btn_preset_delete = QPushButton(tr("chart_designer.preset.delete"), bar)
        self.btn_style_import = QPushButton(tr("chart_designer.preset.import"), bar)
        self.btn_style_export = QPushButton(tr("chart_designer.preset.export"), bar)
        row.addWidget(self.btn_preset_save)
        row.addWidget(self.btn_preset_load)
        row.addWidget(self.btn_preset_delete)
        row.addWidget(self.btn_style_import)
        row.addWidget(self.btn_style_export)
        return bar

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
            self.edt_title, self.edt_subtitle, self.edt_source, self.edt_footer,
            self.edt_ref_values, self.cmb_ref_linestyle, self.edt_ref_ink, self.chk_at01,
        )
        for w in widgets:
            w.blockSignals(True)

        self._select(self.cmb_template, template)
        self._select(self.cmb_palette, palette)
        self._select(self.cmb_format, fmt)
        self.spn_dpi.setValue(int(dpi))
        self.chk_grid.setChecked(grid)
        self.edt_ref_ink.setText(getattr(s, "chart_designer_ref_ink", "") or "")
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
        for edt in (self.edt_title, self.edt_subtitle, self.edt_source,
                    self.edt_footer, self.edt_ref_values, self.edt_ref_ink):
            edt.editingFinished.connect(self._on_param_changed)
        self.cmb_ref_linestyle.currentIndexChanged.connect(self._on_param_changed)
        self.chk_at01.toggled.connect(self._on_param_changed)
        self.btn_export.clicked.connect(self.exportRequested.emit)
        self.btn_font_jump.clicked.connect(self.fontSettingsRequested.emit)
        # T-1046 P3：预设与共享
        self.cmb_preset.currentIndexChanged.connect(self._on_preset_selected)
        self.btn_preset_save.clicked.connect(self._on_preset_save)
        self.btn_preset_load.clicked.connect(self._on_preset_load)
        self.btn_preset_delete.clicked.connect(self._on_preset_delete)
        self.btn_style_import.clicked.connect(self._on_style_import)
        self.btn_style_export.clicked.connect(self._on_style_export)

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
            "title": self.edt_title.text().strip() or None,
            "subtitle": self.edt_subtitle.text().strip() or None,
            "source": self.edt_source.text().strip() or None,
            "footer": self.edt_footer.text().strip() or None,
            "ref_ink": self.edt_ref_ink.text().strip() or None,
            "ref_values": _parse_ref_values(self.edt_ref_values.text()),
            "ref_linestyle": self.cmb_ref_linestyle.currentData() or "--",
            "at01_gate": bool(self.chk_at01.isChecked()),
        }

    # ------------------------------------------------------------------
    # 预设 / 共享（T-1046 P3：会话/项目/全局三层 + 样式 JSON 导入/导出）
    # ------------------------------------------------------------------

    def _project(self):
        """经 `parent() → controller.project` 取当前项目（隐式通道）。

        面板被页宿主重挂（parent 非主窗），故沿父链上溯
        到首个带 `controller` 的宿主；无 parent / 无 controller / 无 project → None
        （降级为仅会话/全局，不报错）。
        """
        node = self.parent()
        while node is not None:
            controller = getattr(node, "controller", None)
            if controller is not None:
                manager = getattr(controller, "project", None)
                return getattr(manager, "current", None) if manager is not None else None
            node = node.parent()
        return None

    def _preset_stores(self) -> tuple[dict | None, dict | None, dict]:
        """三层写址：(项目 presets | None, 全局 presets | None, 会话兜底 presets)。

        项目层优先；无项目 → 全局（Settings.chart_style_presets，缺键兜底空 dict）；
        settings=None → 会话内存兜底（不报错）。
        """
        project = self._project()
        proj_store = project.presets if project is not None else None
        global_store: dict | None = None
        settings = self._settings
        if settings is not None:
            store = getattr(settings, "chart_style_presets", None)
            if not isinstance(store, dict):
                store = {}
                settings.chart_style_presets = store
            global_store = store
        return proj_store, global_store, self._session_presets

    def _preset_names(self) -> list[str]:
        """合并视图预设名（项目层优先，其次全局，最后会话兜底；去重保序）。"""
        proj, globl, sess = self._preset_stores()
        names: list[str] = []
        for store in (proj, globl, sess):
            for name in (store or {}):
                if name not in names:
                    names.append(name)
        return names

    def _preset_snapshot(self, name: str) -> dict | None:
        """按层优先级取预设快照（项目 → 全局 → 会话）；不存在 → None。"""
        proj, globl, sess = self._preset_stores()
        for store in (proj, globl, sess):
            if store is not None and name in store:
                return dict(store[name])
        return None

    def _refresh_preset_list(self) -> None:
        """重建预设下拉（保持既有选中项）。"""
        current = self.cmb_preset.currentData()
        names = self._preset_names()
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.clear()
        for name in names:
            self.cmb_preset.addItem(name, name)
        if current in names:
            self.cmb_preset.setCurrentIndex(names.index(current))
        self.cmb_preset.blockSignals(False)

    def apply_params(self, snapshot: dict) -> None:
        """将样式快照写入控件（信号屏蔽，单次渲染）；未知键忽略并计入告警。

        缺失键回落控件当前值（面板初始化已装默认 → 即默认值），不崩。
        """
        known = set(self.params().keys())
        unknown = sorted(set(snapshot) - known)
        self._import_warnings = list(unknown)  # 未知键名列表（策略：忽略 + 告警）
        snap = {k: snapshot[k] for k in known if k in snapshot}

        widgets = (
            self.cmb_template, self.spn_width, self.spn_height, self.chk_grid,
            self.cmb_palette, self.cmb_format, self.spn_dpi,
            self.edt_title, self.edt_subtitle, self.edt_source, self.edt_footer,
            self.edt_ref_values, self.cmb_ref_linestyle, self.edt_ref_ink, self.chk_at01,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            if "template" in snap:
                self._select(self.cmb_template, str(snap["template"]))
            if "palette" in snap:
                self._select(self.cmb_palette, str(snap["palette"]))
            if "width" in snap:
                try:
                    self.spn_width.setValue(float(snap["width"]))
                except (TypeError, ValueError):
                    pass
            if "height" in snap:
                try:
                    self.spn_height.setValue(float(snap["height"]))
                except (TypeError, ValueError):
                    pass
            if "grid" in snap:
                self.chk_grid.setChecked(bool(snap["grid"]))
            if "format" in snap:
                self._select(self.cmb_format, str(snap["format"]))
            if "dpi" in snap:
                try:
                    self.spn_dpi.setValue(int(snap["dpi"]))
                except (TypeError, ValueError):
                    pass
            for key, edt in (
                ("title", self.edt_title), ("subtitle", self.edt_subtitle),
                ("source", self.edt_source), ("footer", self.edt_footer),
                ("ref_ink", self.edt_ref_ink),
            ):
                if key in snap:
                    edt.setText(str(snap[key]) if snap[key] not in (None, "") else "")
            if "ref_values" in snap:
                vals = snap["ref_values"]
                text = ", ".join(str(v) for v in vals) if vals else ""
                self.edt_ref_values.setText(text)
            if "ref_linestyle" in snap:
                self._select(self.cmb_ref_linestyle, str(snap["ref_linestyle"]))
            if "at01_gate" in snap:
                self.chk_at01.setChecked(bool(snap["at01_gate"]))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._on_param_changed()

    def _save_preset(self, name: str, snapshot: dict) -> None:
        """保存快照到目标层（项目优先 → 全局 → 会话兜底）；全局落盘静默失败。"""
        proj, globl, _sess = self._preset_stores()
        target = proj if proj is not None else (globl if globl is not None else self._session_presets)
        target[name] = dict(snapshot)
        if target is globl and self._settings is not None:
            try:
                self._settings.save()
            except Exception:
                pass
        self._refresh_preset_list()

    def _delete_preset(self, name: str) -> bool:
        """从存在层删除预设；删除全局层后落盘。返回是否真的删除。"""
        proj, globl, _sess = self._preset_stores()
        removed = False
        for store in (proj, globl, self._session_presets):
            if store is not None and name in store:
                del store[name]
                removed = True
        if removed and globl is not None and self._settings is not None:
            try:
                self._settings.save()
            except Exception:
                pass
        return removed

    def export_style_json(self, path: Path) -> dict:
        """导出当前会话参数为可共享样式 JSON（format + version + params 体）。"""
        snapshot = self.params()
        payload = {
            "format": STYLE_FORMAT,
            "version": STYLE_VERSION,
            "params": snapshot,
        }
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return snapshot

    def import_style_json(self, path: Path) -> dict:
        """导入样式 JSON → 应用控件 → 返回应用后 params()。

        坏 JSON / 缺 format / 错 version / 缺参数体 → ValueError（显式拒绝）；
        未知键 → 忽略并计入 `import_warnings`（策略写入报告）。
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise ValueError(tr("chart_designer.preset.import_bad_json")) from e
        if data.get("format") != STYLE_FORMAT:
            raise ValueError(
                tr("chart_designer.preset.import_reject").format(fmt=repr(data.get("format")))
            )
        if data.get("version") != STYLE_VERSION:
            raise ValueError(
                tr("chart_designer.preset.import_version").format(v=repr(data.get("version")))
            )
        body = data.get("params")
        if not isinstance(body, dict):
            raise ValueError(tr("chart_designer.preset.import_missing_params"))
        self.apply_params(body)
        return self.params()

    def _toast(self, message: str, level: str = "info") -> None:
        """非模态 toast（复用既有 show_toast；失败静默）。"""
        try:
            from acouscope.ui.widgets.toast import show_toast

            show_toast(self, message, level=level)
        except Exception:
            pass

    def _arm(self, token: str, armed_text: str) -> None:
        """两击确认：按钮文本切换为确认文案，5s 内第二次点击生效。"""
        self._armed = token
        if token.startswith("save:"):
            self.btn_preset_save.setText(armed_text)
        elif token.startswith("del:"):
            self.btn_preset_delete.setText(armed_text)
        self._arm_timer.start(CONFIRM_ARM_MS)

    def _disarm(self) -> None:
        """解除两击确认（超时/执行后）。"""
        self._armed = None
        self.btn_preset_save.setText(tr("chart_designer.preset.save"))
        self.btn_preset_delete.setText(tr("chart_designer.preset.delete"))

    def _on_preset_selected(self, _index: int) -> None:
        """选中预设 → 名称输入框同步（便于另存/覆盖）。"""
        name = self.cmb_preset.currentData()
        if name:
            self.edt_preset_name.setText(name)

    def _on_preset_save(self) -> None:
        """保存当前参数为具名预设；重名 → 两击确认覆盖（禁静默覆盖）。"""
        name = self.edt_preset_name.text().strip()
        if not name:
            self._toast(tr("chart_designer.preset.name_required"), level="warning")
            return
        token = f"save:{name}"
        if self._preset_snapshot(name) is not None and self._armed != token:
            self._arm(token, tr("chart_designer.preset.overwrite"))
            return
        self._armed = None
        self._save_preset(name, self.params())
        self._disarm()
        self._toast(tr("chart_designer.preset.saved"))

    def _on_preset_load(self) -> None:
        """加载选中预设 → 控件（单次渲染 + 刷新会话态）。"""
        name = self.cmb_preset.currentData()
        if not name:
            return
        snapshot = self._preset_snapshot(name)
        if snapshot is None:
            return
        self.apply_params(snapshot)

    def _on_preset_delete(self) -> None:
        """删除选中预设；两击确认（禁静默删除）。"""
        name = self.cmb_preset.currentData()
        if not name:
            return
        token = f"del:{name}"
        if self._armed != token:
            self._arm(token, tr("chart_designer.preset.delete_confirm"))
            return
        self._armed = None
        self._delete_preset(name)
        self._disarm()
        self._refresh_preset_list()
        self._toast(tr("chart_designer.preset.deleted"))

    def _on_style_import(self) -> None:
        """导入样式 JSON（文件对话框 + 显式拒绝外来格式）。"""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("chart_designer.preset.import"), "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            self.import_style_json(Path(path))
        except ValueError as e:
            self._toast(f"{e}", level="error")
            return
        if self._import_warnings:
            self._toast(
                tr("chart_designer.preset.import_warning").format(n=len(self._import_warnings)),
                level="warning",
            )
        else:
            self._toast(tr("chart_designer.preset.import_ok"))

    def _on_style_export(self) -> None:
        """导出当前参数为样式 JSON（文件对话框）。"""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("chart_designer.preset.export"), "chart_style.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            self.export_style_json(Path(path))
        except OSError as e:
            self._toast(f"{e}", level="error")
            return
        self._toast(tr("chart_designer.preset.export_ok"))

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
            ok = bool(self._renderer(path, self._preview_dpi(), True))
        except Exception:
            ok = False
        if ok and self._show_pixmap(path):
            self.previewUpdated.emit(True)
            return True
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(tr("chart_designer.preview_placeholder"))
        self.previewUpdated.emit(False)
        return False

    def _preview_dpr(self) -> float:
        """预览所在的设备像素比（离屏 / 普通屏 = 1.0）。

        单独成法便于测档注入假 dpr（retina 面无法在离屏复现）。
        """
        return float(self.preview_label.devicePixelRatioF())

    def _preview_dpi(self) -> int:
        """M-1(a)：源图按 dpr 抬分辨率，令高 DPI 屏有足够物理像素可采样。

        只作用于**预览出图**；导出 DPI 走 `params()["dpi"]`（用户/模板），与此无关。
        """
        return max(PREVIEW_DPI, round(PREVIEW_DPI * self._preview_dpr()))

    def _show_pixmap(self, path: Path) -> bool:
        pix = QPixmap(str(path))
        if pix.isNull():
            return False
        # M-1(b)：缩放目标按**物理像素**（逻辑尺寸 × dpr），再标注 dpr → Qt 1:1 映射；
        # dpr=1 时 `physical == label.size()`，与旧实现逐像素等价。
        dpr = self._preview_dpr()
        logical = self.preview_label.size()
        physical = QSize(
            max(1, round(logical.width() * dpr)),
            max(1, round(logical.height() * dpr)),
        )
        out = pix.scaled(
            physical,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        out.setDevicePixelRatio(dpr)
        self.preview_label.setPixmap(out)
        return True
