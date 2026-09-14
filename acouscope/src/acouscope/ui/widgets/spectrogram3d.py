# SPDX-License-Identifier: GPL-3.0-only
"""3D 频谱图与瀑布图控件。

音乐声学研究专用的三维时频可视化，支持：
- 3D 曲面谱（plot_surface，时间 × 频率 × 幅度）
- 瀑布图（逐帧频谱线堆叠，时间纵深）
- 消隐瀑布图（白色填充面遮挡后方线条，隐藏线消除）
- 线性 / dB 幅度标度（dB 可调动态范围）
- 频率上限、色板选择
- 乐段时间段选择（对应"乐曲片段的三维频谱图"分析场景）
- 鼠标拖拽旋转 3D 视角（matplotlib mplot3d 内置交互）
- 右侧参数面板：视角（仰角/方位角/复位）与图形边距实时调整、保存图片

基于 matplotlib mplot3d 嵌入 Qt（项目既有依赖，无新增）。
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.toast import show_toast
from acouscope.utils.log import get_logger
from acouscope.visualization.mpl_style import apply_style

_log = get_logger(__name__)

# 学术出图白底（导出专用，不是屏幕呈现）：取浅色主题的中性阶与文字色，
# 避免在源码散落 hex；导出临时切白、结束后恢复当前主题（裁定 D‴/E‴）。
EXPORT_FACE = theme.THEMES["light"]["bg1"]
EXPORT_TEXT = theme.THEMES["light"]["text"]
EXPORT_TEXT_SUB = theme.THEMES["light"]["text_sub"]
EXPORT_BORDER = theme.THEMES["light"]["border"]

# 显示上限（性能保护：mplot3d 面元数与线数过多会显著卡顿）
MAX_FREQ_BINS = 220      # 频率轴显示点数上限
MAX_SURFACE_FRAMES = 110  # 曲面模式时间帧数上限
MAX_WATERFALL_LINES = 60  # 瀑布模式谱线数上限
MAX_SEGMENT_SECONDS = 60.0  # 分析乐段时长上限

# 嵌入式显示字号（画布 dpi=100 时 1pt ≈ 1.39px，与界面 10~12px 字号匹配；
# rcParams 模板的 300dpi 为打印导出设置，嵌入显示会导致字号约为界面 4 倍）
FIG_DPI = 100
TICK_LABEL_PT = 7
AXIS_LABEL_PT = 8.5
TITLE_PT = 9.5
CBAR_TICK_PT = 6.5
CBAR_LABEL_PT = 8

# matplotlib 保存文件类型的中文描述
FORMAT_ZH = {
    "png": "PNG 图片",
    "pdf": "PDF 文档",
    "svg": "SVG 矢量图",
    "eps": "EPS 矢量图",
    "ps": "PostScript 文档",
    "tiff": "TIFF 图片",
    "jpg": "JPEG 图片",
}

# 默认视角与图形边距（复位按钮的目标值）
DEFAULT_ELEV = 28.0
DEFAULT_AZIM = -75.0
DEFAULT_RECT = [0.02, 0.10, 0.72, 0.80]


def _style_mpl_figure(figure, face: str, text: str, text_sub: str,
                      edge: str, pane_face: str) -> None:
    """把 figure 本体 + 全部 axes 并入给定配色（屏幕主题 / 导出白底共用）。

    只改颜色（facecolor/刻度文字/轴标签/网格/3D 面板），不动 cmap、色标范围
    与字号；字号由 ``_style_axes`` 负责，故此处 ``tick_params`` 不传 labelsize。
    不改全局 rcParams（学术白底红线：报告 PDF 与图导出须保持白底）。
    """
    figure.set_facecolor(face)
    for ax in figure.axes:
        ax.set_facecolor(face)
        ax.tick_params(colors=text_sub)
        for axis in (ax.xaxis, ax.yaxis, getattr(ax, "zaxis", None)):
            if axis is None:
                continue
            axis.label.set_color(text)
            pane = getattr(axis, "pane", None)
            if pane is not None:
                pane.set_facecolor(pane_face)
                pane.set_edgecolor(edge)
            axinfo = getattr(axis, "_axinfo", None)
            if isinstance(axinfo, dict) and "grid" in axinfo:
                axinfo["grid"]["color"] = edge
        ax.title.set_color(text)


class Spectrogram3DWidget(QWidget):
    """3D 频谱图 / 瀑布图控件。"""

    # T-1054 批2：3D 内「字体设置…」不再自行开抽屉 → 上抛信号，由主窗切右栏「图表字体」页
    #（单宿主；main_window 在 3D 控件唯一创建/装配点连接，只连一次）。
    chartFontRequested = pyqtSignal()

    MODES = [
        ("3D曲面", "surface"),
        ("瀑布图", "waterfall"),
        ("瀑布图·消隐", "waterfall_hidden"),
    ]

    SCALES = [
        ("线性", "linear"),
        ("dB", "db"),
    ]

    FREQ_LIMITS = [
        ("500 Hz", 500),
        ("1 kHz", 1000),
        ("2 kHz", 2000),
        ("5 kHz", 5000),
        ("10 kHz", 10000),
        ("20 kHz", 20000),
        ("全频段", None),
    ]

    COLORMAPS = [
        ("翠绿 Viridis", "viridis"),
        ("岩浆 Magma", "magma"),
        ("地狱火 Inferno", "inferno"),
        ("等离子 Plasma", "plasma"),
        ("彩虹 Jet", "jet"),
        ("灰度 Gray", "gray"),
        ("青金 Cividis", "cividis"),
        ("涡轮 Turbo", "turbo"),
        ("冷暖 Coolwarm", "coolwarm"),
        ("骨白 Bone", "bone"),
        ("古铜 Copper", "copper"),
        ("春日 Spring", "spring"),
        ("秋橙 Autumn", "autumn"),
        ("深海 Ocean", "ocean"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        # 音频数据
        self._data: Optional[np.ndarray] = None
        self._sample_rate: float = 44100.0
        self._duration: float = 0.0

        # 当前乐段的 STFT 缓存（避免纯显示参数变化时重算）
        self._cache_key: Optional[tuple] = None
        self._stft_freqs: np.ndarray = np.array([])
        self._stft_times: np.ndarray = np.array([])
        self._stft_mag: np.ndarray = np.array([])  # 线性幅度 (n_time, n_freq)

        # 波形指针读取回调（供"指针±2s"按钮定位乐段中心）
        self.pointer_getter: Optional[Callable[[], float]] = None

        # 当前色条（切换到瀑布模式时需移除，避免残留）
        self._colorbar = None

        # 视角参数（右侧面板可调；渲染保持当前视角不强制复位）
        self._elev = DEFAULT_ELEV
        self._azim = DEFAULT_AZIM

        # 图表字体（西文/中文分开；"auto" = 自动；读取用户持久化设置）
        self._chart_font_latin = "auto"
        self._chart_font_cjk = "auto"
        try:
            from acouscope.utils.config import Settings

            s = Settings.load()
            self._chart_font_latin = getattr(s, "chart_font_latin", "auto") or "auto"
            self._chart_font_cjk = getattr(s, "chart_font_cjk", "auto") or "auto"
        except Exception as e:
            _log.warning("操作失败: %s", e)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._build_toolbar(layout)

        # matplotlib 画布（dpi 显式 100：rcParams 模板的 300dpi 会导致嵌入显示字号过大）
        apply_style("default", "zh_CN")
        self.figure = Figure(figsize=(7.0, 4.6), dpi=FIG_DPI, facecolor=EXPORT_FACE)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax_3d = self.figure.add_subplot(111, projection="3d")
        # 固定布局：主轴位置 + 独立色条轴 cax。色条画进固定 cax，
        # 不用 colorbar(ax=) 偷主轴空间——那样每换一次色板都会再压缩一次主轴，
        # 导致图像逐次左移并缩小（colorbar.remove() 不会还原主轴位置）。
        # 色条宽度按学术出图规范取图宽 ~2.5%（≈3mm 细条）；mplot3d 会在
        # 分配区内按数据纵横比居中缩放立方体（默认视角下右缘 ≈ 分配区右缘
        # 内缩 0.097），cax 起点取立方体典型右缘附近，保证视觉上紧贴。
        # 鼠标拖拽旋转由 mplot3d 自带的画布事件处理，无需导航工具栏。
        self._ax_rect = list(DEFAULT_RECT)
        self.ax_3d.set_position(self._ax_rect)
        self.cax = self.figure.add_axes([0.655, 0.22, 0.018, 0.50])
        # 画布并入主题（matplotlib 不走 QSS）：订阅主题变化并立即套用当前主题
        theme.on_theme_change(self._restore_canvas_theme)
        self._restore_canvas_theme()

        # 画布 + 右侧参数面板（视角 / 边距 / 保存），无左下角工具列
        plot_row = QHBoxLayout()
        plot_row.setContentsMargins(0, 0, 0, 0)
        plot_row.setSpacing(0)
        plot_row.addWidget(self.canvas, stretch=1)
        self.side_panel = self._build_side_panel()
        plot_row.addWidget(self.side_panel)
        layout.addLayout(plot_row, stretch=1)

    def _build_toolbar(self, parent_layout):
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 6, 6, 6)
        toolbar.setSpacing(8)

        self.lbl_title = QLabel("3D 频谱图")
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        toolbar.addWidget(self.lbl_title)

        toolbar.addStretch()

        # 时间段选择
        toolbar.addWidget(QLabel("乐段:"))
        self.spn_t0 = QDoubleSpinBox()
        self.spn_t0.setRange(0.0, 3600.0)
        self.spn_t0.setDecimals(2)
        self.spn_t0.setSingleStep(0.5)
        self.spn_t0.setSuffix(" s")
        self.spn_t0.setMaximumWidth(90)
        self.spn_t0.editingFinished.connect(self._on_time_changed)
        toolbar.addWidget(self.spn_t0)

        toolbar.addWidget(QLabel("→"))
        self.spn_t1 = QDoubleSpinBox()
        self.spn_t1.setRange(0.0, 3600.0)
        self.spn_t1.setDecimals(2)
        self.spn_t1.setSingleStep(0.5)
        self.spn_t1.setSuffix(" s")
        self.spn_t1.setMaximumWidth(90)
        self.spn_t1.editingFinished.connect(self._on_time_changed)
        toolbar.addWidget(self.spn_t1)

        # 以波形指针为中心快速选段
        self.btn_pointer = QPushButton("指针±2s")
        self.btn_pointer.setToolTip("以波形分析指针为中心，取前后各 2 秒的乐段")
        self.btn_pointer.setMaximumWidth(80)
        self.btn_pointer.clicked.connect(self._on_pointer_centered)
        toolbar.addWidget(self.btn_pointer)

        toolbar.addSpacing(8)

        # 显示模式
        toolbar.addWidget(QLabel("模式:"))
        self.cmb_mode = QComboBox()
        for label, key in self.MODES:
            self.cmb_mode.addItem(label, key)
        self.cmb_mode.setMaximumWidth(105)
        self.cmb_mode.currentIndexChanged.connect(lambda _: self.render())
        toolbar.addWidget(self.cmb_mode)

        # 幅度标度
        toolbar.addWidget(QLabel("标度:"))
        self.cmb_scale = QComboBox()
        for label, key in self.SCALES:
            self.cmb_scale.addItem(label, key)
        self.cmb_scale.setMaximumWidth(70)
        self.cmb_scale.currentIndexChanged.connect(lambda _: self.render())
        toolbar.addWidget(self.cmb_scale)

        # 频率上限
        toolbar.addWidget(QLabel("频率:"))
        self.cmb_fmax = QComboBox()
        for label, _ in self.FREQ_LIMITS:
            self.cmb_fmax.addItem(label)
        self.cmb_fmax.setCurrentIndex(2)  # 2 kHz
        self.cmb_fmax.setMaximumWidth(80)
        self.cmb_fmax.currentIndexChanged.connect(lambda _: self.render())
        toolbar.addWidget(self.cmb_fmax)

        # 色板（曲面模式）
        toolbar.addWidget(QLabel("色板:"))
        self.cmb_cmap = QComboBox()
        for label, key in self.COLORMAPS:
            self.cmb_cmap.addItem(label, key)
        self.cmb_cmap.setMaximumWidth(110)
        self.cmb_cmap.currentIndexChanged.connect(lambda _: self.render())
        toolbar.addWidget(self.cmb_cmap)

        # 动态范围（dB 标度）
        toolbar.addWidget(QLabel("DR:"))
        self.spn_dr = QDoubleSpinBox()
        self.spn_dr.setRange(20, 120)
        self.spn_dr.setValue(60)
        self.spn_dr.setSuffix(" dB")
        self.spn_dr.setSingleStep(10)
        self.spn_dr.setMaximumWidth(80)
        self.spn_dr.valueChanged.connect(lambda _: self.render())
        toolbar.addWidget(self.spn_dr)

        # 图表字体（字号固定规范不变，西文/中文字体分开设置）
        self.btn_font = QPushButton("字体…")
        self.btn_font.setToolTip(
            "设置 3D 图表的西文/中文字体（与导出图表共用，导出图片同样生效）"
        )
        self.btn_font.setMaximumWidth(70)
        self.btn_font.clicked.connect(self._on_font_button)
        toolbar.addWidget(self.btn_font)

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setMaximumHeight(40)
        parent_layout.addWidget(toolbar_widget)

    def _build_side_panel(self) -> QWidget:
        """右侧参数面板：视角 / 图形边距 / 保存（替代原左下角导航工具列）。

        配色随主题即时变化（style_when_theme 注册动态样式）。
        """
        from acouscope.ui.theme import style_when_theme

        panel = QWidget()
        panel.setFixedWidth(150)
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(5)

        def _heading(key: str) -> QLabel:
            lbl = QLabel(tr(key))
            lbl.setProperty("cls", "heading")
            return lbl

        def _sep() -> QFrame:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.NoFrame)
            line.setFixedHeight(1)
            line.setProperty("cls", "sep")
            return line

        def _spin(lo: float, hi: float, value: float, step: float,
                  decimals: int, suffix: str = "") -> QDoubleSpinBox:
            box = QDoubleSpinBox()
            box.setRange(lo, hi)
            box.setDecimals(decimals)
            box.setSingleStep(step)
            box.setValue(value)
            if suffix:
                box.setSuffix(suffix)
            return box

        # ---- 视角参数 ----
        v.addWidget(_heading("s3d.panel_view"))
        self.spn_elev = _spin(-90.0, 90.0, self._elev, 1.0, 0, " °")
        self.spn_azim = _spin(-180.0, 180.0, self._azim, 1.0, 0, " °")
        self.spn_elev.valueChanged.connect(self._on_view_changed)
        self.spn_azim.valueChanged.connect(self._on_view_changed)
        v.addWidget(QLabel(tr("s3d.elev")))
        v.addWidget(self.spn_elev)
        v.addWidget(QLabel(tr("s3d.azim")))
        v.addWidget(self.spn_azim)
        self.btn_reset_view = QPushButton(tr("s3d.reset_view"))
        self.btn_reset_view.clicked.connect(self._reset_view)
        v.addWidget(self.btn_reset_view)

        v.addWidget(_sep())

        # ---- 边距参数 ----
        v.addWidget(_heading("s3d.panel_margin"))
        left, bottom, width, height = DEFAULT_RECT
        self._margin_spins: dict[str, QDoubleSpinBox] = {}
        for key, value in (
            ("top", bottom + height), ("bottom", bottom),
            ("left", left), ("right", left + width),
        ):
            box = _spin(0.0, 1.0, value, 0.005, 3)
            box.valueChanged.connect(self._on_margin_changed)
            self._margin_spins[key] = box
            v.addWidget(QLabel(tr(f"s3d.m_{key}")))
            v.addWidget(box)
        self.btn_reset_margin = QPushButton(tr("s3d.reset_margin"))
        self.btn_reset_margin.clicked.connect(self._reset_margins)
        v.addWidget(self.btn_reset_margin)

        v.addWidget(_sep())

        # ---- 保存图片 ----
        self.btn_save = QPushButton(tr("s3d.save"))
        self.btn_save.clicked.connect(self._save_figure)
        v.addWidget(self.btn_save)
        v.addStretch()

        # 主题化样式：背景/文字/边框/按钮随主题即时刷新
        style_when_theme(panel, lambda c: f"""
            QWidget {{ background: {c["panel"]}; }}
            QLabel {{ color: {c["text"]}; font-size: 12px; background: transparent; }}
            QLabel[cls="heading"] {{ font-weight: bold; color: {c["accent"]}; }}
            QFrame[cls="sep"] {{ background: {c["border"]}; border: none; }}
            QDoubleSpinBox {{
                background: {c["input"]}; color: {c["text"]};
                border: 1px solid {c["border"]}; border-radius: 3px; padding: 2px 4px;
                selection-background-color: {c["sel_bg"]}; }}
            QDoubleSpinBox:focus {{ border: 1px solid {c["accent"]}; }}
            QDoubleSpinBox::up-button {{
                subcontrol-position: top right; width: 15px;
                background: {c["btn"]}; border: none;
                border-left: 1px solid {c["border"]};
                border-bottom: 1px solid {c["border"]}; }}
            QDoubleSpinBox::down-button {{
                subcontrol-position: bottom right; width: 15px;
                background: {c["btn"]}; border: none;
                border-left: 1px solid {c["border"]}; }}
            QPushButton {{
                background: {c["btn"]}; color: {c["text"]};
                border: 1px solid {c["border"]}; border-radius: 4px; padding: 3px 6px; }}
            QPushButton:hover {{ background: {c["btn_hover"]}; }}
            QPushButton:pressed {{
                background: {c["accent"]}; color: {c["accent_text"]}; }}
        """)
        return panel

    # ------------------------------------------------------------------
    # 参数面板动作
    # ------------------------------------------------------------------

    def _on_view_changed(self) -> None:
        """视角参数变化：即时旋转，不重算数据。"""
        self._elev = self.spn_elev.value()
        self._azim = self.spn_azim.value()
        self.ax_3d.view_init(elev=self._elev, azim=self._azim)
        self.canvas.draw_idle()

    def _reset_view(self) -> None:
        """复位到默认视角。"""
        self._elev, self._azim = DEFAULT_ELEV, DEFAULT_AZIM
        for spn, val in ((self.spn_elev, self._elev), (self.spn_azim, self._azim)):
            spn.blockSignals(True)
            spn.setValue(val)
            spn.blockSignals(False)
        self._on_view_changed()

    def _on_margin_changed(self) -> None:
        """边距参数变化：即时调整主轴与色条位置。"""
        left = self._margin_spins["left"].value()
        bottom = self._margin_spins["bottom"].value()
        right = self._margin_spins["right"].value()
        top = self._margin_spins["top"].value()
        if right - left < 0.1 or top - bottom < 0.1:
            return  # 宽/高过小，忽略本次输入
        self._apply_rect(left, bottom, right - left, top - bottom)

    def _apply_rect(self, x: float, y: float, w: float, h: float) -> None:
        """应用主轴区域并同步色条（紧贴立方体右缘、垂直居中）。"""
        self._ax_rect = [x, y, w, h]
        self.ax_3d.set_position(self._ax_rect)
        cax_h = min(0.50, h * 0.65)
        self.cax.set_position([x + w - 0.085, y + (h - cax_h) / 2, 0.018, cax_h])
        self.canvas.draw_idle()

    def _reset_margins(self) -> None:
        """边距复位到默认布局。"""
        left, bottom, width, height = DEFAULT_RECT
        values = {"top": bottom + height, "bottom": bottom,
                  "left": left, "right": left + width}
        for key, box in self._margin_spins.items():
            box.blockSignals(True)
            box.setValue(values[key])
            box.blockSignals(False)
        self._apply_rect(left, bottom, width, height)

    def _restore_canvas_theme(self) -> None:
        """按当前主题重设画布呈现（主题切换 / 每次重绘后共用）。

        matplotlib 的 facecolor 与轴色不走 QSS；且 ``Axes.clear()`` 会把颜色
        复位到 rcParams 默认（白底），故每次 render 之后也须重套一次。
        """
        c = theme.colors()
        _style_mpl_figure(self.figure, c["bg1"], c["text"], c["text_sub"],
                          c["border"], c["bg2"])
        self.canvas.draw_idle()

    def _apply_export_white(self) -> None:
        """导出前临时切白底（figure + 全部 axes + 面板）；导出后恢复主题呈现。

        学术红线：导出产物（含 axes 面板区）必须白底，故不能只靠
        ``print_figure(facecolor=...)``——它只覆盖 figure 底、管不到 axes。
        """
        _style_mpl_figure(self.figure, EXPORT_FACE, EXPORT_TEXT,
                          EXPORT_TEXT_SUB, EXPORT_BORDER, EXPORT_FACE)

    def export_current_view(self, path, *, fmt: str = "png", dpi: int = 300) -> None:
        """按当前视角/模式/乐段直接导出当前画布（导出等效白底）。

        设计器（main_window mode==6）与「AI 释图」抓画布共用本入口，保证与
        3D 视图自带导出同源：临时切白底 → ``print_figure(facecolor=EXPORT_FACE)`` →
        ``finally`` 恢复屏幕主题（R5：不留"导出后屏幕变白"副作用）。
        ``path`` 既可是文件路径（str/Path），也可是二进制 file-like（如 BytesIO），
        ``print_figure`` 原生支持。
        """
        self._apply_export_white()
        try:
            self.canvas.print_figure(
                path, format=fmt, dpi=dpi, bbox_inches="tight",
                facecolor=EXPORT_FACE,
            )
        finally:
            self._restore_canvas_theme()

    def _save_figure(self, *args) -> None:
        """中文标题的保存图片对话框（目标目录不可写时自动改存）。"""
        from pathlib import Path

        filetypes = self.canvas.get_supported_filetypes()
        ordered = sorted(filetypes.items())
        filters = ";;".join(
            f"{FORMAT_ZH.get(ext, desc)} (*.{ext})" for ext, desc in ordered
        )
        default = "3D频谱图.png"
        path, _ = QFileDialog.getSaveFileName(self, tr("s3d.save"), default, filters)
        if not path:
            return
        ext = str(path).rsplit(".", 1)[-1].lower()
        if ext not in filetypes:
            ext = "png"
            path += ".png"

        relocated = False
        try:
            # 导出期临时白底 + try/finally 保证恢复屏幕主题呈现
            self._apply_export_white()
            try:
                self.canvas.print_figure(
                    path, format=ext, dpi=300, bbox_inches="tight",
                    facecolor=EXPORT_FACE,
                )
            except PermissionError:
                fallback = Path.home() / "Documents" / "AcouScope导出"
                fallback.mkdir(parents=True, exist_ok=True)
                path = str(fallback / Path(path).name)
                self.canvas.print_figure(
                    path, format=ext, dpi=300, bbox_inches="tight",
                    facecolor=EXPORT_FACE,
                )
                relocated = True
        finally:
            self._restore_canvas_theme()

        if relocated:
            show_toast(
                self, f"原目录无写入权限，保存位置调整，已改存到：{path}",
                level="info",
            )

    # ------------------------------------------------------------------
    # 数据设置
    # ------------------------------------------------------------------

    def set_audio(self, data: np.ndarray, sample_rate: float) -> None:
        """设置音频数据并初始化默认乐段。

        Args:
            data: 音频数据（单声道）
            sample_rate: 采样率
        """
        self._data = np.asarray(data, dtype=np.float64)
        self._sample_rate = float(sample_rate)
        self._duration = len(self._data) / self._sample_rate if sample_rate > 0 else 0.0

        # 默认乐段：开头 10 秒（不足取全长）
        default_end = min(10.0, self._duration)
        for spn, value in ((self.spn_t0, 0.0), (self.spn_t1, default_end)):
            spn.blockSignals(True)
            spn.setMaximum(max(self._duration, 0.01))
            spn.setValue(value)
            spn.blockSignals(False)

        self._cache_key = None
        self.render()

    def set_time_range(self, start: float, end: float) -> None:
        """设置分析乐段并重绘。"""
        if self._duration <= 0:
            return
        start = max(0.0, min(start, self._duration - 0.1))
        end = max(start + 0.1, min(end, self._duration))
        for spn, value in ((self.spn_t0, start), (self.spn_t1, end)):
            spn.blockSignals(True)
            spn.setValue(value)
            spn.blockSignals(False)
        self.render()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _on_time_changed(self):
        """时间段编辑完成。"""
        t0 = self.spn_t0.value()
        t1 = self.spn_t1.value()
        if t1 - t0 < 0.1:
            return
        self.render()

    def _on_pointer_centered(self):
        """以波形指针为中心选择 ±2s 乐段。"""
        if self.pointer_getter is None or self._duration <= 0:
            return
        center = float(self.pointer_getter())
        half = 2.0
        start = max(0.0, center - half)
        end = min(self._duration, start + 2 * half)
        start = max(0.0, end - 2 * half)
        self.set_time_range(start, end)

    # ------------------------------------------------------------------
    # STFT 计算（带缓存）
    # ------------------------------------------------------------------

    def _ensure_stft(self) -> bool:
        """计算当前乐段的 STFT（参数未变时直接用缓存）。"""
        if self._data is None or self._duration <= 0:
            return False

        t0 = self.spn_t0.value()
        t1 = min(self.spn_t1.value(), self._duration)
        t0 = max(0.0, min(t0, t1 - 0.1))
        if t1 - t0 < 0.1:
            return False

        n_fft = 2048
        key = (round(t0, 4), round(t1, 4), n_fft)
        if key == self._cache_key:
            return len(self._stft_times) > 0

        # 截取乐段（超长乐段截断保护）
        if t1 - t0 > MAX_SEGMENT_SECONDS:
            t1 = t0 + MAX_SEGMENT_SECONDS

        i0 = int(t0 * self._sample_rate)
        i1 = min(int(t1 * self._sample_rate), len(self._data))
        segment = self._data[i0:i1]
        if len(segment) < n_fft:
            return False

        # 帧移自适应：限制帧数 ≤ ~180，避免大乐段计算量爆炸
        target_frames = 180
        hop = max(n_fft // 8, int(len(segment) / target_frames))

        from acouscope.dsp.stft import STFTEngine

        engine = STFTEngine(n_fft=n_fft, hop_length=hop, window="hann")
        freqs, times, mag_db = engine.magnitude(segment, self._sample_rate, db_scale=False)

        # magnitude 返回 (n_freq, n_time) → 转置为 (n_time, n_freq)
        # T-917：乐段起点偏移回加（i0/sr 与 segment 首样本精确对齐），
        # 使 3D 时间轴/标题为绝对时间，与语谱图/音高/共振峰/音色口径一致
        self._stft_freqs = freqs
        self._stft_times = times + i0 / self._sample_rate
        self._stft_mag = np.abs(mag_db).T if mag_db.ndim == 2 else np.array([])
        self._cache_key = key
        return len(self._stft_times) > 0

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _display_arrays(self):
        """按当前显示参数（频率上限 / 降采样）准备绘图数组。

        Returns:
            (freqs, times, mags) —— mags 形状 (n_time, n_freq)
        """
        fmax = self.FREQ_LIMITS[self.cmb_fmax.currentIndex()][1]
        freqs = self._stft_freqs
        mags = self._stft_mag

        if fmax is not None:
            mask = freqs <= fmax
            freqs = freqs[mask]
            mags = mags[:, mask]

        # 频率轴降采样
        if len(freqs) > MAX_FREQ_BINS:
            stride = int(np.ceil(len(freqs) / MAX_FREQ_BINS))
            freqs = freqs[::stride]
            mags = mags[:, ::stride]

        # 时间轴降采样（曲面模式）
        mode = self.cmb_mode.currentData()
        if mode == "surface" and mags.shape[0] > MAX_SURFACE_FRAMES:
            stride = int(np.ceil(mags.shape[0] / MAX_SURFACE_FRAMES))
            times = self._stft_times[::stride]
            mags = mags[::stride, :]
        else:
            times = self._stft_times

        return freqs, times, mags

    def _scaled_mags(self, mags: np.ndarray) -> tuple[np.ndarray, float, float, str]:
        """按幅度标度转换并返回 (转换后矩阵, zmin, zmax, z标签)。"""
        scale = self.cmb_scale.currentData()
        if scale == "db":
            with np.errstate(divide="ignore"):
                db = 20 * np.log10(np.maximum(mags, 1e-10))
            zmax = float(np.max(db))
            zmin = zmax - self.spn_dr.value()
            z = np.clip(db, zmin, None)
            return z, zmin, zmax, "幅度 (dB)"

        zmax = float(np.max(mags)) if mags.size else 0.0
        zmin = 0.0
        return mags, zmin, zmax, "幅度 (线性)"

    def render(self):
        """按当前参数重绘（STFT 未变时仅重绘，不重算）。"""
        if not self._ensure_stft():
            self.ax_3d.clear()
            self.ax_3d.set_title("乐段过短或无数据")
            self.canvas.draw_idle()
            return

        freqs, times, mags = self._display_arrays()
        if len(freqs) < 2 or len(times) < 2:
            return

        z, zmin, zmax, zlabel = self._scaled_mags(mags)
        mode = self.cmb_mode.currentData()

        ax = self.ax_3d
        ax.clear()
        self._remove_colorbar()
        # 复位主轴到固定位置（双保险，防止任何布局漂移）
        ax.set_position(self._ax_rect)
        self._style_axes(ax)

        t0 = float(times[0])
        t1 = float(times[-1])
        f_hi = float(freqs[-1])

        if mode == "surface":
            self._draw_surface(ax, freqs, times, z, f_hi, t0, t1, zmin, zmax)
        else:
            self._draw_waterfall(ax, freqs, times, z, f_hi, t0, t1, zmin, zmax,
                                 hidden=(mode == "waterfall_hidden"))

        ax.set_xlabel("频率 (Hz)", labelpad=8)
        ax.set_ylabel("时间", labelpad=8)
        # 时间轴统一刻度（Audacity 风格 nice_ticks 位置 + <1s 毫秒 / ≥60s 60 进制标签）
        from acouscope.ui.widgets.time_axis import (
            MatplotlibTimeFormatter,
            NiceTicksLocator,
        )

        ax.yaxis.set_major_locator(NiceTicksLocator(min_label_px=90))
        ax.yaxis.set_minor_locator(NiceTicksLocator(min_label_px=90, minor=True))
        ax.yaxis.set_major_formatter(MatplotlibTimeFormatter())
        ax.set_zlabel(zlabel, labelpad=8)

        scale_name = self.cmb_scale.currentText()
        ax.set_title(
            f"{self.cmb_mode.currentText()} · {scale_name} · "
            f"{t0:.2f}–{t1:.2f} s · 0–{f_hi:.0f} Hz",
            fontsize=TITLE_PT,
        )
        ax.view_init(elev=self._elev, azim=self._azim)
        self._apply_chart_font(ax)
        # clear() 会复位底色/轴色到 rcParams 默认 → 重绘后按当前主题重套
        self._restore_canvas_theme()

    def _style_axes(self, ax):
        """统一 3D 轴字号（嵌入显示，与界面字体大小匹配）。"""
        ax.tick_params(labelsize=TICK_LABEL_PT)
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.label.set_fontsize(AXIS_LABEL_PT)

    def _apply_chart_font(self, ax):
        """应用用户选定的图表字体（字号规范不变，仅字体族可变）。

        使用与导出一致的字体链（西文 + 中文 + 回退），避免中文标签缺字形。
        """
        latin = getattr(self, "_chart_font_latin", "auto")
        cjk = getattr(self, "_chart_font_cjk", "auto")
        try:
            from acouscope.visualization.mpl_style import font_chain

            # auto 会解析为默认字体（西文 Times New Roman + 中文宋体）
            chain = font_chain(latin, cjk)
            ax.title.set_fontfamily(chain)
            for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
                axis.label.set_fontfamily(chain)
                for tick in axis.get_majorticklabels():
                    tick.set_fontfamily(chain)
            if self._colorbar is not None:
                self._colorbar.ax.yaxis.label.set_fontfamily(chain)
                for tick in self._colorbar.ax.yaxis.get_majorticklabels():
                    tick.set_fontfamily(chain)
        except Exception as e:
            _log.warning("操作失败: %s", e)

    def set_chart_font(self, latin: str, cjk: str) -> None:
        """外部同步字体设置（如全局字体对话框），并持久化与重绘。"""
        self._chart_font_latin = latin or "auto"
        self._chart_font_cjk = cjk or "auto"
        self._persist_chart_font()
        self.render()

    def _on_font_button(self):
        """图表字体入口：上抛 #chartFontRequested → 主窗起源切右栏「图表字体」页（单宿主，非模态）。"""
        self.chartFontRequested.emit()

    def _persist_chart_font(self):
        try:
            from acouscope.utils.config import Settings

            settings = Settings.load()
            settings.chart_font_latin = self._chart_font_latin
            settings.chart_font_cjk = self._chart_font_cjk
            settings.save()
        except Exception as e:
            _log.warning("操作失败: %s", e)

    def _draw_surface(self, ax, freqs, times, z, f_hi, t0, t1, zmin, zmax):
        """3D 曲面谱。"""
        # (n_time, n_freq) → 网格
        F, T = np.meshgrid(freqs, times)
        cmap_name = self.cmb_cmap.currentData()
        surf = ax.plot_surface(
            F, T, z,
            cmap=cmap_name,
            rstride=1, cstride=1,
            linewidth=0, antialiased=True,
        )
        ax.set_xlim(0, f_hi)
        ax.set_ylim(t0, t1)
        ax.set_zlim(zmin, zmax)
        # 色条画进固定 cax（不压缩主轴），重绘前清空旧内容
        self.cax.clear()
        self.cax.set_visible(True)
        self._colorbar = self.figure.colorbar(surf, cax=self.cax)
        self._colorbar.ax.tick_params(labelsize=CBAR_TICK_PT)
        self._colorbar.set_label("幅度", fontsize=CBAR_LABEL_PT)

    def _remove_colorbar(self):
        """清空并隐藏色条（cax 固定保留；切瀑布模式时不残留）。"""
        try:
            self.cax.clear()
            self.cax.set_visible(False)
        except Exception as e:
            _log.warning("操作失败: %s", e)
        self._colorbar = None

    def _draw_waterfall(self, ax, freqs, times, z, f_hi, t0, t1, zmin, zmax,
                        hidden: bool):
        """瀑布图（可选白色填充消隐）。谱线按时间轴用当前色板渐变着色。"""
        import matplotlib

        n_time = z.shape[0]
        if n_time > MAX_WATERFALL_LINES:
            stride = int(np.ceil(n_time / MAX_WATERFALL_LINES))
            idx = np.arange(0, n_time, stride)
        else:
            idx = np.arange(n_time)

        cmap = matplotlib.colormaps[self.cmb_cmap.currentData()]
        denom = max(n_time - 1, 1)

        # 从远（时间大）到近（时间小）绘制；mplot3d 深度排序 +
        # 稳定插入序保证本片填充不遮挡本片谱线
        for i in idx:
            y = float(times[i])
            line_z = z[i]
            if hidden:
                verts = [[freqs[0], y, zmin]]
                verts += [[float(f), y, float(m)] for f, m in zip(freqs, line_z)]
                verts.append([freqs[-1], y, zmin])
                poly = Poly3DCollection(
                    [verts], facecolors="white", edgecolors="none"
                )
                ax.add_collection3d(poly)
            ax.plot(
                freqs, np.full(len(freqs), y), line_z,
                color=cmap(i / denom), linewidth=1.6,
            )

        ax.set_xlim(0, f_hi)
        ax.set_ylim(t1, t0)  # 近端（时间小）在前
        ax.set_zlim(zmin, zmax)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    @property
    def segment(self) -> tuple[float, float]:
        """当前分析乐段 (起, 止) 秒。"""
        return self.spn_t0.value(), self.spn_t1.value()
