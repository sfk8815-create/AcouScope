# SPDX-License-Identifier: GPL-3.0-only
"""语谱图显示控件。

音乐声学研究专用的时频谱显示，支持：
- STFT 变换（纯 numpy 实现）
- 多种色板（magma / inferno / plasma / viridis / jet / gray）
- 可调动态范围 / 对比度
- 频率范围选择
- 对数频率轴（数据重采样到对数网格实现）
- 时间游标与波形联动
"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QCheckBox,
)

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.param_spin import ParamSpinBox
from acouscope.ui.widgets.spectrum import (
    compact_glyph_button,
    make_view_tool_row,
    pin_tool_row_widths,
    tool_field,
)


def _apply_canvas_theme(plot_widget, bg_role: str = "bg1") -> None:
    """画布并入主题（T-1032）：底色取中性阶，轴/刻度/网格随主题着色。

    pyqtgraph 的 ``setBackground`` 与轴笔不走 QSS，故主题变化时须显式重设。
    网格线沿用轴笔颜色（`showGrid` 的 alpha 不变）→ 随之着色。
    """
    c = theme.colors()
    plot_widget.setBackground(c[bg_role])
    for side in ("left", "bottom", "right", "top"):
        axis = plot_widget.getAxis(side)
        axis.setPen(c["text_sub"])
        axis.setTextPen(c["text_sub"])
        axis.setLabel(
            axis.labelText, units=axis.labelUnits,
            **{**axis.labelStyle, "color": c["text"]},
        )


class NarrowColorBar(pg.PlotWidget):
    """定宽色条（G4a-4 / M2）。

    `width` 为**总宽** = 左轴宽 + 渐变宽（渐变 >= 10 px，不被轴压没）。
    pg.PlotWidget 的 `minimumSizeHint` 按「完整坐标轴 + 视口」算（约 88 px），
    旧写法 `setMaximumWidth(30)` 于是常年落在「have < minimumSizeHint」判定里，
    被误计为截断控件。此处按实际内容（总宽）回报最小宽，语义与视觉一致。
    """

    def __init__(self, width: int = 30, parent=None):
        super().__init__(parent)
        self._narrow_width = width

    def minimumSizeHint(self):  # noqa: N802 (Qt 命名)
        return QSize(self._narrow_width, 60)


class SpectrogramWidget(QWidget):
    """语谱图显示控件。"""

    # T-323 播放联动信号：时间交互事件出口上抛，由 main_window 统一分发
    # （默认导航态；可被上层显式模式覆盖，禁直接调 controller/player）
    timeClicked = pyqtSignal(float)  # 单击：定位播放头
    timeDoubleClicked = pyqtSignal(float)  # 双击：从此处播放
    timeScrubbed = pyqtSignal(float)  # Alt+拖：连续试听位置（拖动过程持续）
    xRangeShifted = pyqtSignal(float, float)  # 用户平移 X 时间窗后上抛 (lo, hi)

    # 预设频率范围
    FREQ_RANGES = [
        ("500 Hz", 500),
        ("1 kHz", 1000),
        ("2 kHz", 2000),
        ("5 kHz", 5000),
        ("10 kHz", 10000),
        ("20 kHz", 20000),
        ("全频段", None),
    ]

    # 色板选项
    COLORMAPS = [
        ("岩浆 Magma", "magma"),
        ("热力 Inferno", "inferno"),
        ("等离子 Plasma", "plasma"),
        ("翠绿 Viridis", "viridis"),
        ("彩虹 Jet", "jet"),
        ("灰度 Gray", "gray"),
        ("反转灰度 GrayR", "gray_r"),
    ]

    # FFT 大小选项
    FFT_SIZES = [512, 1024, 2048, 4096, 8192, 16384]

    # 帧移比例
    HOP_RATIOS = [
        ("1/2 (50%)", 0.5),
        ("1/4 (25%)", 0.25),
        ("1/8 (12.5%)", 0.125),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        # 数据
        self._freqs = np.array([])
        self._times = np.array([])
        self._magnitude_db = np.array([])  # dB 幅度
        self._sample_rate = 44100.0
        self._log_freq_axis = False  # True 时 Y 坐标为 log10(Hz)
        self._freq_unit = "hz"  # Y 轴频率单位（与 FFT 频谱窗口一致）

        # 回调
        self.cursor_changed = None  # func(time_sec)

        self._build_ui()

        # T-326 Pδ：悬停读数 overlay + 选区测量 A/B 标记（plot_widget 内右上角小标签）
        self._on_hover_readout = None  # 外部注入回调 func(text: str | None)
        self._measure_supported = True
        self._hover_overlay = QLabel(self.plot_widget)
        self._hover_overlay.setObjectName("hover_readout_overlay")
        self._hover_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._style_readout_label(self._hover_overlay)
        self._hover_overlay.hide()
        self._last_hover_at = 0.0  # 悬停节流（≤20Hz）
        self._measure_items: list = []  # A/B InfiniteLine
        self._measure_item_labels: list = []  # A/B TextItem
        # T-323 导航态（与 pitch/formants 同构初始化，供 eventFilter/_on_view_range_changed 使用）
        self._xrange_blocked = False
        self._prev_view_x = None
        self._scrubbing = False
        self._nav_press_scene = None
        self._nav_press_view_t = None
        self._last_nav_click_at = -1.0
        self._last_nav_click_t = None

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
        self._build_toolbar(layout)

        # 设置面板（默认隐藏）
        self._build_settings_panel(layout)

        # 信息栏
        self._build_info_bar(layout)

        # 语谱图
        self._build_plot(layout)

    def _build_toolbar(self, parent_layout):
        """构建顶部工具行（G4a-4：QToolBar 容器，窄宽自动溢出到「»」菜单）。"""
        toolbar = make_view_tool_row(self)
        self.tool_row = toolbar

        self.lbl_title = QLabel(tr("view.spectrogram"))
        self.lbl_title.setStyleSheet(
            f"font-weight: bold; font-size: {theme.TOKENS['typography']['body']}px;")
        toolbar.addWidget(self.lbl_title)

        # FFT 大小（G4a-4：删 75 px 硬上限 → 最小内容宽）
        self.cmb_fft = QComboBox()
        for n in self.FFT_SIZES:
            self.cmb_fft.addItem(f"{n}", n)
        self.cmb_fft.setCurrentIndex(2)  # 2048
        self.cmb_fft.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_fft.setMinimumContentsLength(5)
        toolbar.addWidget(tool_field(QLabel("FFT:"), self.cmb_fft))

        # 频率范围
        self.cmb_range = QComboBox()
        for label, _ in self.FREQ_RANGES:
            self.cmb_range.addItem(label)
        self.cmb_range.setCurrentIndex(2)  # 2 kHz
        self.cmb_range.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_range.setMinimumContentsLength(6)
        self.cmb_range.currentIndexChanged.connect(self._on_range_changed)
        toolbar.addWidget(tool_field(QLabel(tr("spectrogram.range")), self.cmb_range))

        # Y 轴单位切换（与 FFT 频谱窗口一致）
        from acouscope.ui.widgets.freq_axis import build_freq_unit_combo

        self.cmb_y_unit = build_freq_unit_combo()
        self.cmb_y_unit.currentIndexChanged.connect(self._on_y_unit_changed)
        toolbar.addWidget(tool_field(QLabel(tr("spectrogram.axis_y")), self.cmb_y_unit))

        # 色板
        self.cmb_cmap = QComboBox()
        for label, key in self.COLORMAPS:
            self.cmb_cmap.addItem(label, key)
        self.cmb_cmap.setCurrentIndex(0)
        self.cmb_cmap.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        # L5：最小宽按最长项文本定死，窄宽溢出整件收进「»」而非裁切末字
        _cmap_fm = self.cmb_cmap.fontMetrics()
        _cmap_longest = max(
            (label for label, _ in self.COLORMAPS),
            key=lambda s: _cmap_fm.horizontalAdvance(s),
        )
        self.cmb_cmap.setMinimumWidth(
            _cmap_fm.horizontalAdvance(_cmap_longest) + 24)
        self.cmb_cmap.currentIndexChanged.connect(self._on_cmap_changed)
        toolbar.addWidget(tool_field(QLabel(tr("spectrogram.colormap")), self.cmb_cmap))

        # 动态范围（T-1115：拖拽改值会触发整幅重算 ⇒ 走释放提交，拖拽中不重绘）
        self.spn_dr = ParamSpinBox()
        self.spn_dr.set_live_preview(False)
        self.spn_dr.setRange(10, 120)
        self.spn_dr.setValue(60)
        self.spn_dr.setSuffix(" dB")
        self.spn_dr.setSingleStep(5)
        self.spn_dr.setMinimumWidth(72)
        self.spn_dr.valueChanged.connect(self._on_dr_changed)
        toolbar.addWidget(tool_field(QLabel("DR:"), self.spn_dr))

        # 测量工具
        self.btn_measure = QPushButton("📏")
        self.btn_measure.setToolTip(tr("spectrogram.tip_measure"))
        self.btn_measure.setCheckable(True)
        compact_glyph_button(self.btn_measure, 32)
        self.btn_measure.toggled.connect(self._toggle_measure_tool)
        toolbar.addWidget(self.btn_measure)

        # 峰值追踪
        self.btn_peak = QPushButton("🔺")
        self.btn_peak.setToolTip(tr("spectrogram.tip_peak_track"))
        self.btn_peak.setCheckable(True)
        compact_glyph_button(self.btn_peak, 32)
        self.btn_peak.toggled.connect(self._toggle_peak_contour)
        toolbar.addWidget(self.btn_peak)

        # 音高曲线叠加开关（PITCH_OVERLAY_V1）
        self.btn_pitch = QPushButton("🎵")
        self.btn_pitch.setToolTip(tr("spectrogram.tip_pitch_overlay"))
        self.btn_pitch.setCheckable(True)
        compact_glyph_button(self.btn_pitch, 32)
        self.btn_pitch.toggled.connect(self._toggle_pitch_contour)
        toolbar.addWidget(self.btn_pitch)

        # 设置按钮
        self.btn_settings = QPushButton("⚙")
        compact_glyph_button(self.btn_settings, 32)
        self.btn_settings.setToolTip(tr("spectrogram.tip_advanced"))
        self.btn_settings.setCheckable(True)
        self.btn_settings.toggled.connect(self._toggle_settings)
        toolbar.addWidget(self.btn_settings)

        pin_tool_row_widths(toolbar)
        parent_layout.addWidget(toolbar)

    def _build_settings_panel(self, parent_layout):
        self.settings_panel = QWidget()
        self.settings_panel.setMaximumHeight(0)
        settings_layout = QHBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(6, 4, 6, 4)
        settings_layout.setSpacing(12)

        # 时频参数
        timefreq_group = QGroupBox("时频参数")
        timefreq_group.setStyleSheet(
            f"QGroupBox {{ font-size: {theme.TOKENS['typography']['caption']}px;"
            f" font-weight: bold; }}")
        tf_form = QFormLayout()
        tf_form.setContentsMargins(6, 8, 6, 6)
        tf_form.setSpacing(4)

        self.cmb_hop = QComboBox()
        for label, ratio in self.HOP_RATIOS:
            self.cmb_hop.addItem(label, ratio)
        self.cmb_hop.setCurrentIndex(1)  # 1/4
        tf_form.addRow("帧移:", self.cmb_hop)

        self.cmb_window = QComboBox()
        for w in ["Hann", "Hamming", "Blackman", "矩形"]:
            self.cmb_window.addItem(w)
        self.cmb_window.setCurrentIndex(0)
        tf_form.addRow("窗函数:", self.cmb_window)

        timefreq_group.setLayout(tf_form)
        settings_layout.addWidget(timefreq_group)

        # 显示设置
        display_group = QGroupBox("显示设置")
        display_group.setStyleSheet(
            f"QGroupBox {{ font-size: {theme.TOKENS['typography']['caption']}px;"
            f" font-weight: bold; }}")
        disp_form = QFormLayout()
        disp_form.setContentsMargins(6, 8, 6, 6)
        disp_form.setSpacing(4)

        self.chk_log_freq = QCheckBox("对数频率轴")
        self.chk_log_freq.stateChanged.connect(lambda _: self._update_image())
        disp_form.addRow("", self.chk_log_freq)

        self.chk_contrast = QCheckBox("自动对比度")
        self.chk_contrast.setChecked(True)
        self.chk_contrast.toggled.connect(lambda _: self._update_image())
        disp_form.addRow("", self.chk_contrast)

        display_group.setLayout(disp_form)
        settings_layout.addWidget(display_group)

        parent_layout.addWidget(self.settings_panel)

    def _build_info_bar(self, parent_layout):
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 2)

        self.lbl_info = QLabel(tr("spectrogram.readout_none"))
        self.lbl_info.setStyleSheet(
            f"color: {theme.colors()['text_sub']};"
            f" font-size: {theme.TOKENS['typography']['caption']}px;")
        bar.addWidget(self.lbl_info)

        bar.addStretch()

        self.lbl_resolution = QLabel("")
        self.lbl_resolution.setStyleSheet(
            f"color: {theme.colors()['text_faint']};"
            f" font-size: {theme.TOKENS['typography']['caption']}px;")
        bar.addWidget(self.lbl_resolution)

        bar_widget = QWidget()
        bar_widget.setLayout(bar)
        bar_widget.setMaximumHeight(22)
        parent_layout.addWidget(bar_widget)

    def _build_plot(self, parent_layout):
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setLabel("bottom", "时间", units="s")
        from acouscope.ui.widgets.time_axis import apply_time_axis

        apply_time_axis(self.plot_widget)
        self.plot_widget.setLabel("left", "频率", units="Hz")
        _apply_canvas_theme(self.plot_widget)
        self.plot_widget.setLogMode(x=False, y=False)
        # 禁用右键菜单
        self.plot_widget.getPlotItem().setMenuEnabled(False)
        parent_layout.addWidget(self.plot_widget)

        # 语谱图图像
        self.img_item = pg.ImageItem()
        self.plot_widget.addItem(self.img_item)

        # 颜色条（M2：总宽 = 左轴 25 + 渐变 14，渐变不再被轴压没）
        self.colorbar_widget = NarrowColorBar(39)
        self.colorbar_widget.setMaximumWidth(39)
        self.colorbar_widget.hideAxis("bottom")
        self.colorbar_widget.getAxis("left").setWidth(25)
        self.colorbar_widget.getAxis("left").setStyle(tickTextOffset=5)
        self.colorbar_widget.setLabel("left", "dB")
        _apply_canvas_theme(self.colorbar_widget, "bg2")

        self.colorbar_img = pg.ImageItem()
        self.colorbar_widget.addItem(self.colorbar_img)
        # 需要用一个 layout 把主图和色条放在一起

        # 重新组织布局：把 plot 和 colorbar 放一起
        # 先从 parent_layout 移除 plot_widget
        parent_layout.removeWidget(self.plot_widget)

        plot_layout = QHBoxLayout()
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)
        plot_layout.addWidget(self.plot_widget, stretch=1)
        plot_layout.addWidget(self.colorbar_widget, stretch=0)

        # 竖排钢琴键盘条（钢琴卷帘模式显示，插在最左侧）
        from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

        self.kb_strip = PianoKeyboardStrip()
        self.kb_strip.follow(self.plot_widget)
        plot_layout.insertWidget(0, self.kb_strip)
        self._sync_kb_strip()

        plot_container = QWidget()
        plot_container.setLayout(plot_layout)
        parent_layout.addWidget(plot_container)
        theme.on_theme_change(self._on_canvas_theme)

        # 时间游标（垂直虚线）
        self.cursor_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pg.mkPen(color=theme.data_ink("cursor"), width=3.3,
                         style=Qt.PenStyle.DashLine),
            movable=True,
        )
        self.plot_widget.addItem(self.cursor_line)
        self.cursor_line.sigPositionChanged.connect(self._on_cursor_moved)

        # ------ 标注系统（与波形控件共享模型） ------
        self._annotations = None  # 外部设置共享模型
        self._region_items: dict[int, object] = {}  # id(region) -> LinearRegionItem
        self._instant_items: dict[int, object] = {}  # id(instant) -> InfiniteLine

        # ------ T-922 音律标尺叠加层（默认关闭；None/[] = 无叠加） ------
        self._tuning_lines: list = []
        self._tuning_items: list = []  # [(pg.InfiniteLine, pg.TextItem)]
        # 频率轴范围变化 → 叠加层按可视范围重绘（超出范围的线跳过）
        self.plot_widget.plotItem.vb.sigYRangeChanged.connect(
            lambda *_args: self._redraw_tuning_overlay()
        )

        # ------ 测量工具 ------
        self._measure_enabled = False
        self._measure_start = None  # (t, f) 起点
        self._measure_rect = None  # pg.LinearRegionItem 等价物
        self._measure_text = None  # 测量结果文本
        self._measure_dragging = False

        # ------ 峰值频率追踪 ------
        self._peak_curve = None  # pg.PlotDataItem
        self._peak_freqs = None  # np.ndarray 峰值频率
        self._pitch_curve = None  # pg.PlotDataItem（PITCH_OVERLAY_V1 音高叠加）
        self._pitch_track = None  # (times, f0_hz)
        self._peak_threshold_db = -30  # 峰值最小强度（dB）

        # 初始色板
        self._apply_colormap()

        # 鼠标移动跟踪
        self._init_mouse_tracking()

    def _apply_ink(self) -> None:
        """数据墨色（T-1038 M1/M6）：游标/峰值曲线/音高叠加/测量与标记随主题取色。"""
        self.cursor_line.setPen(pg.mkPen(
            color=theme.data_ink("cursor"), width=3.3,
            style=Qt.PenStyle.DashLine))
        if self._peak_curve is not None:
            self._peak_curve.setPen(pg.mkPen(color=theme.data_ink("trace"), width=3.3))
        if self._pitch_curve is not None:
            self._pitch_curve.setPen(
                pg.mkPen(color=theme.data_ink("trace_alt"), width=2.2))
        if self._measure_rect is not None:
            self._measure_rect.setPen(pg.mkPen(color=theme.data_ink("marker"), width=4.5))
        if self._measure_text is not None:
            self._measure_text.setColor(theme.data_ink("marker"))
            self._measure_text.fill = pg.mkBrush(theme.data_ink("tint"))
        for i, item in enumerate(getattr(self, "_measure_items", [])):
            role = "cursor" if i == 0 else "marker"
            item.setPen(pg.mkPen(color=theme.data_ink(role), width=1.8))
        for i, tag in enumerate(getattr(self, "_measure_item_labels", [])):
            tag.setColor(theme.data_ink("cursor" if i == 0 else "marker"))
            tag.fill = pg.mkBrush(theme.data_ink("tint"))
        self._redraw_annotations()      # 标注标签底色随主题重取（data.tint）

    def _on_canvas_theme(self):
        """主题切换：重设主图与色条画布底色/轴色 + 数据墨色（pyqtgraph 不走 QSS）。"""
        _apply_canvas_theme(self.plot_widget)
        _apply_canvas_theme(self.colorbar_widget, "bg2")
        self._apply_ink()
        # ★ T-1042c：主题切换亦须保持键面可见性与当前单位一致（与数据无关）
        self._sync_kb_strip()
        self.plot_widget.update()

    def _init_mouse_tracking(self):
        """初始化鼠标位置跟踪。"""
        self.plot_widget.scene().installEventFilter(self)
        self.plot_widget.setMouseTracking(True)
        # T-326 Pδ：鼠标离开图区（viewport Leave）→ 悬停读数清零
        self.plot_widget.viewport().installEventFilter(self)
        vb = self.plot_widget.plotItem.vb
        vb.sigRangeChanged.connect(self._on_view_range_changed)

    def _nav_time_at(self, scene_pos) -> float:
        """场景坐标 → 时间（秒），夹取到数据时间范围。"""
        vb = self.plot_widget.plotItem.vb
        t = float(vb.mapSceneToView(scene_pos).x())
        if self._times.size:
            t = float(np.clip(t, float(self._times[0]), float(self._times[-1])))
        return t

    def _emit_nav_click(self, t: float) -> None:
        """微拖抬起：按 0.35s + 1% 视宽口径区分单击/双击（与波形判定一致）。"""
        lo, hi = self.plot_widget.viewRange()[0]
        span = max(hi - lo, 1e-9)
        now = time.monotonic()
        if (self._last_nav_click_t is not None
                and now - self._last_nav_click_at < 0.35
                and abs(t - self._last_nav_click_t) < span * 0.01):
            self._last_nav_click_at = -1.0
            self._last_nav_click_t = None
            self.timeDoubleClicked.emit(t)
        else:
            self.timeClicked.emit(t)
            self._last_nav_click_at = now
            self._last_nav_click_t = t

    def _on_view_range_changed(self):
        """vb X 范围变化：仅"用户平移"上抛 xRangeShifted。

        程序 setXRange（_xrange_blocked）或缩放（跨度变化）不触发；
        只同步平移不同步缩放级别，防自激/回环由 blocked + 主窗口分发忽略自身上抛。
        """
        vb = self.plot_widget.plotItem.vb
        lo, hi = float(vb.viewRange()[0][0]), float(vb.viewRange()[0][1])
        if self._xrange_blocked:
            self._prev_view_x = (lo, hi)
            return
        prev = self._prev_view_x
        self._prev_view_x = (lo, hi)
        if prev is None:
            return
        if abs(lo - prev[0]) < 1e-12 and abs(hi - prev[1]) < 1e-12:
            return  # 仅 Y 变化
        prev_span = prev[1] - prev[0]
        if prev_span <= 0 or abs((hi - lo) - prev_span) > prev_span * 1e-3:
            return  # 缩放：不同步
        self.xRangeShifted.emit(lo, hi)

    def set_time_range(self, lo: float, hi: float) -> None:
        """程序性同步 X 时间窗（跨视图平移/播放跟随入口，防自激上抛）。"""
        self._xrange_blocked = True
        try:
            self.plot_widget.setXRange(lo, hi, padding=0)
        finally:
            self._xrange_blocked = False

    def eventFilter(self, obj, event):
        """事件过滤器：测量工具 + T-323 导航手势 + 坐标读数。"""
        etype = event.type()
        if self._measure_enabled:
            vb = self.plot_widget.plotItem.vb
            if etype == QEvent.Type.GraphicsSceneMousePress and event.button() == Qt.MouseButton.LeftButton:
                scene_pos = event.scenePos()
                if vb.sceneBoundingRect().contains(scene_pos):
                    mouse_point = vb.mapSceneToView(scene_pos)
                    t = float(mouse_point.x())
                    f = self._view_y_to_hz(float(mouse_point.y()))
                    self._start_measurement(t, f)
                    return True

            elif etype == QEvent.Type.GraphicsSceneMouseMove and self._measure_dragging:
                scene_pos = event.scenePos()
                if vb.sceneBoundingRect().contains(scene_pos):
                    mouse_point = vb.mapSceneToView(scene_pos)
                    t = float(mouse_point.x())
                    f = self._view_y_to_hz(float(mouse_point.y()))
                    self._update_measurement(t, f)
                    return True

            elif etype == QEvent.Type.GraphicsSceneMouseRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._measure_dragging:
                    scene_pos = event.scenePos()
                    if vb.sceneBoundingRect().contains(scene_pos):
                        mouse_point = vb.mapSceneToView(scene_pos)
                        t = float(mouse_point.x())
                        f = self._view_y_to_hz(float(mouse_point.y()))
                        self._update_measurement(t, f)
                    self._measure_dragging = False
                    return True

        # ---- T-323 默认导航手势（单一可拦截出口；测量工具优先，其余放行保留原语义） ----
        if (etype in (QEvent.Type.GraphicsSceneMousePress,
                      QEvent.Type.GraphicsSceneMouseDoubleClick)
                and event.button() == Qt.MouseButton.LeftButton):
            if (etype == QEvent.Type.GraphicsSceneMousePress
                    and event.modifiers() & Qt.KeyboardModifier.AltModifier):
                # Alt+左键按下：进入 scrub（事件吃掉，防 ViewBox 平移）
                self._scrubbing = True
                self.timeScrubbed.emit(self._nav_time_at(event.scenePos()))
                return True
            self._nav_press_scene = event.scenePos()
            self._nav_press_view_t = self._nav_time_at(event.scenePos())

        elif etype == QEvent.Type.GraphicsSceneMouseMove and self._scrubbing:
            self.timeScrubbed.emit(self._nav_time_at(event.scenePos()))
            return True

        elif etype == QEvent.Type.GraphicsSceneMouseRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._scrubbing:
                self._scrubbing = False
                self.timeScrubbed.emit(self._nav_time_at(event.scenePos()))
                return True
            if self._nav_press_scene is not None:
                press_t = self._nav_press_view_t
                t = self._nav_time_at(event.scenePos())
                self._nav_press_scene = None
                # 微拖视同单击/双击；真实拖动（分析游标/平移）不触发，语义保留
                lo, hi = self.plot_widget.viewRange()[0]
                if abs(t - press_t) <= (hi - lo) * 0.004:
                    self._emit_nav_click(t)

        if etype == QEvent.Type.GraphicsSceneMouseMove:
            scene_pos = event.scenePos()
            vb = self.plot_widget.plotItem.vb
            if vb.sceneBoundingRect().contains(scene_pos):
                mouse_point = vb.mapSceneToView(scene_pos)
                t = float(mouse_point.x())
                f = self._view_y_to_hz(float(mouse_point.y()))
                # 查找最近的时间/频率点
                if len(self._times) > 0 and len(self._freqs) > 0:
                    t_idx = int(np.clip(np.searchsorted(self._times, t), 0, len(self._times) - 1))
                    f_idx = int(np.clip(np.searchsorted(self._freqs, f), 0, len(self._freqs) - 1))
                    if f_idx < self._magnitude_db.shape[0] and t_idx < self._magnitude_db.shape[1]:
                        db_val = float(self._magnitude_db[f_idx, t_idx])
                        from acouscope.ui.widgets.freq_axis import format_freq_readout

                        freq_str = format_freq_readout(f, self._freq_unit)
                        self.lbl_info.setText(
                            tr("spectrogram.cursor_readout").format(
                                time=f"{t:.3f}", freq=freq_str, db=f"{db_val:.1f}"
                            )
                        )
                # T-326 Pδ：悬停读数（节流 ≤20Hz；只读坐标映射，保留既有 lbl_info 更新）
                self._hover_update_at(float(mouse_point.x()), float(mouse_point.y()))
            else:
                self._hover_clear()
        elif etype == QEvent.Type.Leave and obj is self.plot_widget.viewport():
            self._hover_clear()
        return super().eventFilter(obj, event)

    def _apply_colormap(self):
        """应用色板到图像和色条。

        jet/gray/gray_r 不在 pyqtgraph 内置色板目录中，
        回退到 matplotlib 色板（matplotlib 已随出图模块安装）。
        """
        cmap_name = self.cmb_cmap.currentData()
        try:
            cmap = pg.colormap.get(cmap_name)
        except Exception:
            cmap = pg.colormap.getFromMatplotlib(cmap_name)

        self.img_item.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
        self.colorbar_img.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))

    def set_data(
        self,
        freqs: np.ndarray,
        times: np.ndarray,
        magnitude_db: np.ndarray,
        sample_rate: float = 44100.0,
    ):
        """设置语谱图数据。

        Args:
            freqs: 频率轴 (n_freq,)
            times: 时间轴 (n_time,)
            magnitude_db: dB 幅度矩阵 (n_freq, n_time)
            sample_rate: 采样率
        """
        self._freqs = freqs
        self._times = times
        self._magnitude_db = magnitude_db
        self._sample_rate = sample_rate

        if len(magnitude_db) < 1:
            return

        # 分辨率信息
        freq_res = freqs[1] - freqs[0] if len(freqs) > 1 else 0
        time_res = times[1] - times[0] if len(times) > 1 else 0
        self.lbl_resolution.setText(f"Δf={freq_res:.2f} Hz  Δt={time_res*1000:.1f} ms")

        self._update_image()
        self._refresh_peak_if_visible()

    def _sync_kb_strip(self) -> None:
        """同步键盘条可见性（T-1042c 缺陷 B）。

        ★ 键面可见性**只取决于当前频率单位**，与「有没有数据」无关：
        原先该赋值写在 `_update_image()` 的数据守卫**之后**，未加载/未成谱图时
        直接 return → 切「钢琴卷帘」后可见性从未被设置（键面永不出现）。
        """
        self.kb_strip.setVisible(self._freq_unit == "piano")

    def _update_image(self):
        """更新语谱图图像。"""
        # ★ T-1042c：可见性同步放在数据守卫**之前**（防其它触发路径漏更新）
        self._sync_kb_strip()

        if len(self._magnitude_db) < 1 or len(self._times) < 1:
            return

        # 确定频率范围
        max_freq = self.FREQ_RANGES[self.cmb_range.currentIndex()][1]
        if max_freq is None:
            max_freq = self._freqs[-1]

        # 截取频率范围
        freq_mask = self._freqs <= max_freq
        spec_data = self._magnitude_db[freq_mask, :]
        freqs_display = self._freqs[freq_mask]

        if len(freqs_display) < 2 or spec_data.shape[0] < 2:
            return

        # 计算颜色映射范围
        dr = self.spn_dr.value()
        if self.chk_contrast.isChecked():
            # 自动对比度：取数据范围内的最大值
            max_db = float(np.max(spec_data))
            min_db = max_db - dr
        else:
            max_db = 0.0
            min_db = -dr

        # 归一化到 [0, 1]
        spec_norm = np.clip((spec_data - min_db) / (max_db - min_db), 0, 1)

        t_min = float(self._times[0])
        t_max = float(self._times[-1])
        axis_left = self.plot_widget.getAxis("left")

        from acouscope.ui.widgets.freq_axis import (
            note_name_ticks,
            resample_rows,
            set_freq_axis_label,
        )

        set_freq_axis_label(self.plot_widget, self._freq_unit)
        unit = self._freq_unit

        if unit in ("midi", "piano", "cents", "mel"):
            # 非线性单位：把图像重采样到目标单位空间的均匀网格
            # （MIDI/音分本身就是对数刻度，等效于对数频率显示）
            pos = freqs_display > 0
            f_pos = freqs_display[pos]
            spec_pos = spec_norm[pos, :]
            if len(f_pos) < 2:
                return

            grid, resampled = resample_rows(f_pos, spec_pos, unit)
            y_lo, y_hi = float(grid[0]), float(grid[-1])
            self.img_item.setImage(resampled.T, levels=(0, 1))
            self.img_item.setRect(t_min, y_lo, t_max - t_min, y_hi - y_lo)
            self.plot_widget.setYRange(y_lo, y_hi, padding=0)

            if unit in ("midi", "piano"):
                axis_left.setTicks([note_name_ticks(y_lo, y_hi)])
            else:
                axis_left.setTicks(None)  # 自动数值刻度
            self._log_freq_axis = False
        elif self.chk_log_freq.isChecked():
            # 对数频率轴：将数据重采样到对数频率网格，Y 坐标用 log10(f)。
            # pyqtgraph 的 ImageItem 不支持原生对数轴（setLogMode 会导致图像错位），
            # 必须在数据层完成对数映射。
            pos = freqs_display > 0
            f_pos = freqs_display[pos]
            spec_pos = spec_norm[pos, :]
            if len(f_pos) < 2:
                return

            f_hi = float(f_pos[-1])
            f_lo = max(float(f_pos[0]), f_hi / 1000.0)
            log_freqs = np.geomspace(f_lo, f_hi, 256)
            log_spec = np.empty((len(log_freqs), spec_pos.shape[1]))
            for j in range(spec_pos.shape[1]):
                log_spec[:, j] = np.interp(log_freqs, f_pos, spec_pos[:, j])

            y_lo = float(np.log10(log_freqs[0]))
            y_hi = float(np.log10(log_freqs[-1]))

            # (n_time, n_freq)，pyqtgraph col-major：轴0=x(时间)，轴1=y(频率)
            self.img_item.setImage(log_spec.T, levels=(0, 1))
            self.img_item.setRect(t_min, y_lo, t_max - t_min, y_hi - y_lo)
            self.plot_widget.setYRange(y_lo, y_hi, padding=0)

            # Y 轴刻度按当前单位标注（坐标值是 log10）
            ticks = []
            for f in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
                if f_lo <= f <= f_hi:
                    if unit == "khz":
                        label = f"{f / 1000:g} kHz"
                    else:
                        label = f"{f / 1000:g} kHz" if f >= 1000 else f"{f:g} Hz"
                    ticks.append((float(np.log10(f)), label))
            axis_left.setTicks([ticks])
            self._log_freq_axis = True
        else:
            # 线性频率轴（Hz/kHz）：khz 只是坐标缩放
            # (n_time, n_freq)，pyqtgraph col-major：轴0=x(时间)，轴1=y(频率)
            self.img_item.setImage(spec_norm.T, levels=(0, 1))
            f_min = float(freqs_display[0])
            f_max = float(freqs_display[-1])
            if unit == "khz":
                f_min, f_max = f_min / 1000.0, f_max / 1000.0
            self.img_item.setRect(t_min, f_min, t_max - t_min, f_max - f_min)
            self.plot_widget.setYRange(f_min, f_max, padding=0)
            axis_left.setTicks(None)  # 恢复自动刻度
            self._log_freq_axis = False

        # 程序性铺满时间轴：置位 blocked 防 xRangeShifted 自激上抛
        self._xrange_blocked = True
        try:
            self.plot_widget.setXRange(t_min, t_max, padding=0)
        finally:
            self._xrange_blocked = False

        # 设置色条
        self._update_colorbar(min_db, max_db)

    def _update_colorbar(self, min_db: float, max_db: float):
        """更新颜色条。"""
        # 生成一个竖直的渐变条
        gradient = np.linspace(0, 1, 256).reshape(256, 1)
        self.colorbar_img.setImage(gradient, levels=(0, 1))
        self.colorbar_img.setRect(0, min_db, 1, max_db - min_db)
        self.colorbar_widget.setYRange(min_db, max_db, padding=0)

    def _hz_to_view_y(self, f_hz: float) -> float:
        """频率(Hz) → 视图 Y 坐标（随当前单位/对数模式）。"""
        from acouscope.ui.widgets.freq_axis import freq_to_display

        if self._log_freq_axis:
            return float(np.log10(max(f_hz, 1e-10)))
        return freq_to_display(f_hz, self._freq_unit)

    def _view_y_to_hz(self, y: float) -> float:
        """视图 Y 坐标 → 频率(Hz)。"""
        from acouscope.ui.widgets.freq_axis import display_to_freq

        if self._log_freq_axis:
            return 10.0 ** y
        return display_to_freq(y, self._freq_unit)

    def _on_y_unit_changed(self, index: int):
        """Y 轴频率单位切换。"""
        self._freq_unit = self.cmb_y_unit.itemData(index)
        # ★ T-1042c：设完单位**立即**同步键面可见性（主路径，不受数据守卫影响）
        self._sync_kb_strip()
        self._update_image()
        self._refresh_peak_if_visible()
        self._clear_measurement()

    def set_cursor(self, time_sec: float):
        """设置时间游标位置。"""
        self.cursor_line.blockSignals(True)
        self.cursor_line.setPos(time_sec)
        self.cursor_line.blockSignals(False)

    def _on_cursor_moved(self):
        """游标被拖动。"""
        t = float(self.cursor_line.value())
        if self.cursor_changed:
            self.cursor_changed(t)

    # ============================================================
    # 标注系统（多视图同步）
    # ============================================================

    def set_annotation_model(self, model):
        """设置共享标注模型，用于与波形控件同步显示。"""
        self._annotations = model
        self._redraw_annotations()

    @property
    def annotations(self):
        return self._annotations

    def _redraw_annotations(self):
        """根据模型重绘所有标注。"""
        # T-922：音律标尺叠加层随既有重绘路径同步（只动叠加层，不重算分析数据）
        self._redraw_tuning_overlay()
        # 清除旧的（含区域顶部的标签 TextItem）
        for item in list(self._region_items.values()):
            label = getattr(item, "_sv_label", None)
            if label is not None:
                self.plot_widget.removeItem(label)
            self.plot_widget.removeItem(item)
        for item in list(self._instant_items.values()):
            self.plot_widget.removeItem(item)
        self._region_items.clear()
        self._instant_items.clear()

        if self._annotations is None:
            return

        for region in self._annotations.regions:
            self._add_region_item(region)
        for inst in self._annotations.instants:
            self._add_instant_item(inst)

    def _add_region_item(self, region):
        """添加区域可视化。语谱图中区域为只读，不可拖动。"""
        color = region.color
        item = pg.LinearRegionItem(
            values=[region.start_time, region.end_time],
            orientation="vertical",
            brush=pg.mkBrush(color=color + "30"),
            pen=pg.mkPen(color=color, width=3.3),
            movable=False,
        )
        # 标签（用 TextItem 显示在区域顶部）
        if region.label and region.show_label:
            label = pg.TextItem(
                text=region.label,
                color=color,
                anchor=(0.5, 0),
            )
            label.setPos((region.start_time + region.end_time) / 2, 0)
            self.plot_widget.addItem(label)
            item._sv_label = label
        self.plot_widget.addItem(item)
        self._region_items[id(region)] = item

    def _add_instant_item(self, inst):
        """添加时间点可视化。"""
        color = inst.color
        item = pg.InfiniteLine(
            pos=inst.time,
            angle=90,
            pen=pg.mkPen(color=color, width=3.3, style=Qt.PenStyle.DashLine),
            movable=False,
            label=inst.label if inst.show_label and inst.label else "",
            labelOpts={
                "position": 0.05,
                "color": color,
                "fill": theme.data_ink("tint"),
                "anchors": [(0.5, 0), (0.5, 1)],
            },
        )
        self.plot_widget.addItem(item)
        self._instant_items[id(inst)] = item

    def refresh_annotations(self):
        """外部通知：标注模型已更新，重新绘制。"""
        self._redraw_annotations()

    # ------------------------------------------------------------------
    # T-922 音律标尺叠加层
    # ------------------------------------------------------------------

    def set_tuning_overlay(self, lines=None) -> None:
        """设置音律标尺叠加线（None/[] → 清除）。

        只重绘叠加层：不重算分析数据、不清空语谱/音高轨迹（``set_data`` /
        ``set_pitch_track`` 不会被调用）。
        """
        self._tuning_lines = list(lines) if lines else []
        self._redraw_tuning_overlay()

    def tuning_overlay_enabled(self) -> bool:
        """当前是否显示音律标尺叠加层。"""
        return bool(getattr(self, "_tuning_lines", []))

    def _redraw_tuning_overlay(self) -> None:
        """按当前叠加线在频率轴方向重绘音律标尺；超出可视频率范围的线跳过。"""
        from acouscope.ui.theme import TOKENS, colors

        palette = colors()
        lines = list(getattr(self, "_tuning_lines", []))
        items = getattr(self, "_tuning_items", None)
        if items is None:
            items = []
            self._tuning_items = items
        while len(items) < len(lines):
            line_item = pg.InfiniteLine(
                pos=0.0,
                angle=0,
                movable=False,
                pen=pg.mkPen(
                    color=palette["accent"],
                    width=int(TOKENS["elevation"]["border"]),
                    style=Qt.PenStyle.DotLine,
                ),
            )
            label_item = pg.TextItem(color=palette["sub"], anchor=(1.0, 0.0))
            self.plot_widget.addItem(line_item)
            self.plot_widget.addItem(label_item)
            items.append((line_item, label_item))

        y_lo, y_hi = (float(value) for value in self.plot_widget.viewRange()[1])
        x_hi = float(self.plot_widget.viewRange()[0][1])
        for index, (line_item, label_item) in enumerate(items):
            if index >= len(lines):
                line_item.hide()
                label_item.hide()
                continue
            overlay = lines[index]
            y = float(self._hz_to_view_y(overlay.freq_hz))
            if y < y_lo or y > y_hi:  # 超出当前频率范围 → 跳过
                line_item.hide()
                label_item.hide()
                continue
            line_item.setPos(y)
            line_item.show()
            label_item.setText(overlay.label)
            label_item.setPos(x_hi, y)
            label_item.show()

    # ============================================================
    # 测量工具
    # ============================================================

    def _toggle_measure_tool(self, checked: bool):
        """切换测量工具。"""
        self._measure_enabled = checked
        self._measure_dragging = False
        if not checked:
            self._clear_measurement()

    def _start_measurement(self, t: float, f: float):
        """开始测量（鼠标按下）。"""
        self._clear_measurement()
        self._measure_start = (t, f)
        self._measure_dragging = True

        # 创建测量矩形（视图坐标：Y 随当前单位/对数模式）
        y_view = self._hz_to_view_y(f)
        rect = pg.RectROI(
            [t, y_view], [0.001, 0.001],
            pen=pg.mkPen(color=theme.data_ink("marker"), width=4.5),
            movable=False,
            resizable=False,
        )
        self.plot_widget.addItem(rect)
        self._measure_rect = rect

        # 测量结果文本
        text = pg.TextItem(
            text="",
            color=theme.data_ink("marker"),
            fill=theme.data_ink("tint"),
            anchor=(0, 1),
        )
        text.setPos(t, y_view)
        self.plot_widget.addItem(text)
        self._measure_text = text

    def _update_measurement(self, t: float, f: float):
        """更新测量（鼠标拖动）。"""
        if self._measure_start is None or self._measure_rect is None:
            return

        t0, f0 = self._measure_start
        dt = abs(t - t0)
        df = abs(f - f0)

        # 更新矩形（视图坐标：Y 随当前单位/对数模式）
        y0_view = self._hz_to_view_y(f0)
        y_view = self._hz_to_view_y(f)
        x = min(t, t0)
        y = min(y_view, y0_view)
        w = abs(t - t0)
        h = abs(y_view - y0_view)
        self._measure_rect.setPos([x, y])
        self._measure_rect.setSize([w if w > 0 else 0.001, h if h > 0 else 0.001])

        # 计算附加信息（Δf/比率/音分差始终按 Hz 物理量）
        info_parts = [f"Δt={dt*1000:.2f} ms", f"Δf={df:.1f} Hz"]
        if df > 0 and f0 > 0:
            ratio = df / f0
            info_parts.append(f"比率={ratio*100:.1f}%")
        # 音分差
        if f0 > 0 and df > 0 and f > 0:
            import math
            cents = 1200 * math.log2(max(f, f0) / min(f, f0))
            info_parts.append(f"Δcents={cents:.0f}")

        # 更新文本
        text = "  ".join(info_parts)
        self._measure_text.setText(text)
        self._measure_text.setPos(max(t, t0), max(y_view, y0_view))

    def _clear_measurement(self):
        """清除测量标记。"""
        if self._measure_rect is not None:
            self.plot_widget.removeItem(self._measure_rect)
            self._measure_rect = None
        if self._measure_text is not None:
            self.plot_widget.removeItem(self._measure_text)
            self._measure_text = None
        self._measure_start = None
        self._measure_dragging = False

    # ============================================================
    # 峰值频率追踪（Peak Contour）
    # ============================================================

    def _toggle_peak_contour(self, checked: bool):
        """切换峰值频率追踪曲线显示。"""
        if checked:
            self._compute_peak_contour()
            self._draw_peak_contour()
        else:
            self._clear_peak_contour()

    def _compute_peak_contour(self):
        """计算每帧的峰值频率。"""
        if self._magnitude_db.size == 0:
            return

        # 找出每帧最大值的频率索引
        peak_indices = np.argmax(self._magnitude_db, axis=0)
        peak_db = np.max(self._magnitude_db, axis=0)

        # 低于阈值的帧设为 NaN（不显示）
        valid = peak_db >= self._peak_threshold_db
        peak_freqs = self._freqs[peak_indices].astype(float)
        peak_freqs[~valid] = np.nan

        self._peak_freqs = peak_freqs

    def _draw_peak_contour(self):
        """绘制峰值频率曲线。"""
        from acouscope.ui.widgets.freq_axis import freq_to_display

        if self._peak_freqs is None or self._times.size == 0:
            return

        if self._peak_curve is None:
            self._peak_curve = self.plot_widget.plot(
                pen=pg.mkPen(color=theme.data_ink("trace"), width=3.3),
                antialias=False,
            )

        if self._log_freq_axis:
            # 对数模式下，Y 用 log 坐标
            y = np.where(self._peak_freqs > 0, np.log10(self._peak_freqs), np.nan)
            self._peak_curve.setData(self._times, y)
        else:
            # 按当前 Y 轴单位换算（khz/midi/piano/cents/mel）
            y = freq_to_display(self._peak_freqs, self._freq_unit)
            self._peak_curve.setData(self._times, y)

    def _clear_peak_contour(self):
        """清除峰值曲线。"""
        if self._peak_curve is not None:
            self.plot_widget.removeItem(self._peak_curve)
            self._peak_curve = None
        self._peak_freqs = None

    # ============================================================
    # 音高曲线叠加（pYIN pitch track overlay）PITCH_OVERLAY_V1
    # ============================================================

    def set_pitch_track(self, times, f0_hz):
        """设置音高轨迹（Hz；NaN/非正数表示未检出，不绘制）。"""
        self._pitch_track = (
            np.asarray(times, dtype=float),
            np.asarray(f0_hz, dtype=float),
        )
        if self.btn_pitch.isChecked():
            self._draw_pitch_contour()

    def _toggle_pitch_contour(self, checked: bool):
        """切换音高曲线显示。"""
        if checked:
            self._draw_pitch_contour()
        else:
            self._clear_pitch_contour()

    def _draw_pitch_contour(self):
        """绘制音高曲线（随 Y 轴单位/对数轴换算，与峰值曲线同规则）。"""
        from acouscope.ui.widgets.freq_axis import freq_to_display

        if self._pitch_track is None:
            return
        t, f = self._pitch_track
        if t.size == 0:
            return
        if self._pitch_curve is None:
            self._pitch_curve = self.plot_widget.plot(
                pen=pg.mkPen(color=theme.data_ink("trace_alt"), width=2.2),
                antialias=True,
            )
        valid = np.isfinite(f) & (f > 0)
        tt = t[valid]
        ff = f[valid]
        if self._log_freq_axis:
            y = np.where(ff > 0, np.log10(ff), np.nan)
        else:
            y = freq_to_display(ff, self._freq_unit)
        self._pitch_curve.setData(tt, y)

    def _clear_pitch_contour(self):
        """清除音高曲线。"""
        if self._pitch_curve is not None:
            self.plot_widget.removeItem(self._pitch_curve)
            self._pitch_curve = None

    def _maybe_refresh_pitch(self):
        """Y 轴单位/对数轴/频率范围变化时重绘音高曲线。"""
        if self._pitch_curve is not None:
            self._draw_pitch_contour()

    def _refresh_peak_if_visible(self):
        """如果峰值追踪已开启，重新计算并绘制。"""
        if self.btn_peak.isChecked():
            self._compute_peak_contour()
            self._draw_peak_contour()
        self._maybe_refresh_pitch()

    def _on_range_changed(self, index: int):
        """频率范围变化。"""
        self._update_image()
        self._refresh_peak_if_visible()

    def _on_cmap_changed(self, index: int):
        """色板变化。"""
        self._apply_colormap()
        self._update_image()

    def _on_dr_changed(self, value: float):
        """动态范围变化。"""
        self._update_image()

    def _toggle_settings(self, checked: bool):
        """切换设置面板。"""
        if checked:
            self.settings_panel.setMaximumHeight(120)
        else:
            self.settings_panel.setMaximumHeight(0)

    # ============================================================
    # 参数获取（供外部重新计算 STFT 用）
    # ============================================================

    @property
    def fft_size(self) -> int:
        return self.cmb_fft.currentData()

    @property
    def hop_length(self) -> int:
        ratio = self.cmb_hop.currentData()
        return max(1, int(self.fft_size * ratio))

    @property
    def window_name(self) -> str:
        mapping = {
            "Hann": "hann",
            "Hamming": "hamming",
            "Blackman": "blackman",
            "矩形": "rectangular",
        }
        return mapping.get(self.cmb_window.currentText(), "hann")

    # ============================================================
    # T-326 Pδ：悬停读数 + 选区测量（overlay + 上抛状态栏临时段）
    # ============================================================

    @staticmethod
    def _style_readout_label(label: QLabel) -> None:
        """Pδ 读数小标签主题化（零硬编码 hex/px：颜色走 theme，字号走 QFont pt）。"""
        from acouscope.ui.theme import style_when_theme

        style_when_theme(
            label, lambda c: f"color: {c['text']}; background: {c['panel']};"
        )
        font = label.font()
        font.setPointSize(9)
        label.setFont(font)

    def hover_readout_at(self, t_disp: float, y_disp: float) -> str:
        """悬停读数文本（纯计算，测试直接调用断言）：t/频率/音分 + dB。

        频率 = 鼠标 y 显示坐标映射回 Hz；dB = 该 (t, f) 最近网格强度；
        音分 = 相对当前 A4 参考（units.hz_to_cents），f≤0 防御 "--"。
        """
        from acouscope.dsp.units import hz_to_cents
        from acouscope.ui.widgets.freq_axis import format_freq_readout

        f = self._view_y_to_hz(float(y_disp))
        cents = hz_to_cents(f) if f > 0 else None
        parts = [
            f"t={float(t_disp):.3f}s",
            format_freq_readout(f, "hz") if f > 0 else "--",
            f"{cents:+.1f} cents" if cents is not None else "--",
        ]
        db_txt = "--"
        if len(self._times) > 0 and len(self._freqs) > 0 and self._magnitude_db.size:
            t_idx = int(np.clip(
                np.searchsorted(self._times, float(t_disp)), 0, len(self._times) - 1
            ))
            f_idx = int(np.clip(
                np.searchsorted(self._freqs, f), 0, len(self._freqs) - 1
            ))
            if f_idx < self._magnitude_db.shape[0] and t_idx < self._magnitude_db.shape[1]:
                db_txt = f"{float(self._magnitude_db[f_idx, t_idx]):.1f} dB"
        parts.append(db_txt)
        return " | ".join(parts)

    def freq_at(self, t: float) -> float | None:
        """t 时刻该列谱峰频率（抛物线插值细化）；列能量≤阈值(无声)或空数据 → None（Pδ 口径）。

        保留旧版 dB 阈值与静音/空数据分支；仅把峰值读数从「argmax 整 bin」
        升级为：dB 列先转线性幅度 ``np.power(10.0, col/20.0)``，再交给共享
        纯函数 ``refine_peak_frequency`` 做三点抛物线插值，消除 bin 量化。
        """
        if not self._times.size or self._freqs.size == 0 or self._magnitude_db.size == 0:
            return None
        t_idx = int(np.clip(
            np.searchsorted(self._times, float(t)), 0, len(self._times) - 1
        ))
        col = self._magnitude_db[:, t_idx]
        peak_db = float(np.max(col))
        if peak_db <= self._peak_threshold_db:
            return None  # 该列无声（能量低于峰值追踪阈值）
        f_idx = int(np.argmax(col))
        from acouscope.analysis.spectral import refine_peak_frequency

        lin = np.power(10.0, col / 20.0)
        return refine_peak_frequency(lin, self._freqs, f_idx)

    def freq_uncertainty_cent(self, t: float) -> float | None:
        """t 时刻谱峰频率读数的 1σ 不确定度（音分）——半 bin 均匀分布折算。

        ``half_bin_cent = 1200*log2((f + sr/(2*n_fft))/f)``：半 bin 宽度
        ``sr/(2*n_fft)`` 即相邻频率轴间距的一半（``freq_res=sr/n_fft``），
        其量化误差按均匀分布折算标准差 ``half_bin_cent/sqrt(3)``。
        抛物线插值把 bin 读数误差压低约 **8 倍**（本批 44.1 kHz / 1 s
        实测：bin 中位 22.34 cent / 最大 37.34 cent，插值后 n_fft=2048
        最大 4.49 cent、8192 最大 1.09 cent），故该列有有效插值读数时再
        除以 8；静音/空数据（``freq_at`` 返回 None）时无法插值，频率以
        440 Hz 兜底并保留未插值口径。恒返回 float（禁臆造 None）。
        """
        import math

        f = self.freq_at(t)
        interp_ok = f is not None and f > 0
        if not interp_ok:
            f = 440.0
        freq_res = (float(self._freqs[1] - self._freqs[0])
                    if self._freqs.size >= 2 else 0.0)
        if freq_res > 0:
            n_fft = float(self._sample_rate) / freq_res
            half_bin_hz = float(self._sample_rate) / (2.0 * n_fft)
        else:
            half_bin_hz = 0.0
        half_bin_cent = 1200.0 * math.log2((f + half_bin_hz) / f)
        denom = math.sqrt(3.0) * (8.0 if interp_ok else 1.0)
        return float(half_bin_cent / denom)

    def set_readout_overlay(self, text: str | None) -> None:
        """右上角只读 overlay 显示/隐藏（Pδ hover 与测量结果共用；None 隐藏）。"""
        if not text:
            self._hover_overlay.hide()
            return
        self._hover_overlay.setText(text)
        self._hover_overlay.adjustSize()
        sp = self._overlay_spacing()
        x = max(sp, self.plot_widget.width() - self._hover_overlay.width() - sp)
        self._hover_overlay.move(x, sp)
        self._hover_overlay.show()

    @staticmethod
    def _overlay_spacing() -> int:
        from acouscope.ui.theme import TOKENS

        return int(TOKENS["spacing"]["xs"])

    def _hover_update_at(self, t_disp: float, y_disp: float) -> None:
        """鼠标移动（节流 ≤20Hz）：更新 overlay + 上抛 main_window（只读坐标映射）。"""
        now = time.monotonic()
        if now - self._last_hover_at < 0.05:
            return
        self._last_hover_at = now
        text = self.hover_readout_at(float(t_disp), float(y_disp))
        self.set_readout_overlay(text)
        if self._on_hover_readout is not None:
            self._on_hover_readout(text)

    def _hover_clear(self) -> None:
        """鼠标离开：立即隐藏 overlay + 上抛 None（不节流）。"""
        self._last_hover_at = 0.0
        self.set_readout_overlay(None)
        if self._on_hover_readout is not None:
            self._on_hover_readout(None)

    # ----- A/B 测量标记（main_window「测量选区」动作调用；色沿用本文件游标红/测量琥珀） -----

    def measure_markers_clear(self) -> None:
        """隐藏 A/B 测量标记（供「清除测量」/选区清除联动调用）。"""
        for item in list(self._measure_items) + list(self._measure_item_labels):
            if item is not None:
                item.hide()

    def measure_markers_show(self, t0: float, t1: float, f0: float, f1: float) -> None:
        """画 A(t0)/B(t1) 垂直标记线（颜色取数据墨色：A=游标 / B=标记；再次调用覆盖）。"""
        if not self._measure_items:
            for role in ("cursor", "marker"):
                color = theme.data_ink(role)
                line = pg.InfiniteLine(
                    pos=0.0, angle=90, movable=False,
                    pen=pg.mkPen(color=color, width=1.8),
                )
                self.plot_widget.addItem(line)
                self._measure_items.append(line)
                tag = pg.TextItem(color=color, anchor=(0.5, 0))
                self.plot_widget.addItem(tag)
                self._measure_item_labels.append(tag)
        y_hi = float(self.plot_widget.viewRange()[1][1])
        for (tt, name), line, tag in zip(
            ((float(t0), "A"), (float(t1), "B")),
            self._measure_items,
            self._measure_item_labels,
        ):
            line.setPos(tt)
            line.show()
            tag.setText(f"{name}({tt:.3f}s)")
            tag.setPos(tt, y_hi)
            tag.show()

    # ------------------------------------------------------------------
    # T-1060 件3：统一收尾（模板 = waveform.py `_cleanup_scene`/`closeEvent`）
    # 本控件析构图：PlotWidget→scene→{img_item, cursor_line, 标注区域/时间点,
    # 调音叠加层线/标签, A/B 测量线/标签, 测量矩形/文本} + 色条 PlotWidget 的
    # colorbar_img；本控件在 scene 与 viewport 上各装一个事件过滤器。无显式收尾
    # 路径时，进程近尾由 Python GC 以「不同于 Qt 场景删除顺序」回收这些包装 →
    # 场景析构遍历可能触碰已半释放的 C++ 项。这里先逐项移出场景 + 断 item 信号
    # + 摘事件过滤器，消除析构序依赖。只加收尾，不改任何事件/交互/绘制路径。
    # ------------------------------------------------------------------

    _DETACH_SINGLE_ITEMS = ("img_item", "cursor_line", "colorbar_img",
                            "_measure_rect", "_measure_text")

    def _detach_scene_items(self) -> None:
        """统一收尾：断场景 item / 信号 / 事件过滤器（幂等、绝不外抛）。

        收尾后仍保留**纯值快照**（`_tuning_lines` / 标注模型 `_annotations`
        ——后者为外部共享模型，所有权不属本控件）与 class 契约「close 后可读」
        的取值路径不回退；仅清理 Qt 包装与连接：逐项 `removeItem` → 断 item
        信号 → 摘事件过滤器 → 清空 item 容器。
        """
        plot_widget = getattr(self, "plot_widget", None)
        if plot_widget is None:
            return

        items = []
        for attr in self._DETACH_SINGLE_ITEMS:
            item = getattr(self, attr, None)
            if item is not None:
                items.append(item)
        for store_key in ("_region_items", "_instant_items"):
            items.extend(list((getattr(self, store_key, None) or {}).values()))
        for entry in getattr(self, "_tuning_items", None) or []:
            if isinstance(entry, tuple):
                items.extend([e for e in entry if e is not None])
            elif entry is not None:
                items.append(entry)
        for key in ("_measure_items", "_measure_item_labels"):
            items.extend([i for i in (getattr(self, key, None) or []) if i is not None])

        # 断 item → 本控件的信号（先断后移除：避免移除后仍有连接指向本控件）
        cursor = getattr(self, "cursor_line", None)
        if cursor is not None:
            try:
                cursor.sigPositionChanged.disconnect()
            except (TypeError, RuntimeError):
                pass
        for store_key in ("_region_items", "_instant_items"):
            for item in list((getattr(self, store_key, None) or {}).values()):
                for sig_name in ("sigRegionChanged", "sigPositionChanged"):
                    sig = getattr(item, sig_name, None)
                    if sig is None:
                        continue
                    try:
                        sig.disconnect()
                    except (TypeError, RuntimeError):
                        pass

        for item in items:
            try:
                plot_widget.removeItem(item)
            except RuntimeError:
                pass  # 底层 C++ 已析构（控件正在销毁途中）
            except Exception:
                pass  # 双移除/缺登记等一律吞掉：收尾路径绝不外抛

        # 色条上的图像 item 属另一个场景，单独摘除
        cb = getattr(self, "colorbar_widget", None)
        cb_img = getattr(self, "colorbar_img", None)
        if cb is not None and cb_img is not None:
            try:
                cb.removeItem(cb_img)
            except RuntimeError:
                pass
            except Exception:
                pass

        # 摘事件过滤器（断「控件 ← 场景/视口」的环）
        for getter in ("scene", "viewport"):
            try:
                obj = getattr(plot_widget, getter)()
            except RuntimeError:
                continue
            if obj is None:
                continue
            try:
                obj.removeEventFilter(self)
            except RuntimeError:
                pass
            except Exception:
                pass

        # 清空 item 容器（纯值快照/外部共享模型不在此列，保持可读）
        self._region_items = {}
        self._instant_items = {}
        self._tuning_items = []
        self._measure_items = []
        self._measure_item_labels = []
        self._measure_rect = None
        self._measure_text = None

    def closeEvent(self, event):  # noqa: N802 (Qt 命名)
        """窗口关闭：先显式收尾场景 item，再走默认关闭。"""
        self._detach_scene_items()
        super().closeEvent(event)
