# SPDX-License-Identifier: GPL-3.0-only
"""频谱显示控件。

音乐声学研究专用的频谱显示，支持：
- 多种频率单位：Hz / kHz / MIDI / 音分 / Mel
- 多种幅度单位：线性 / dB / dBFS / 归一化%
- 乐音优化的峰值检测与和弦识别
- 峰值保持、窗函数选择

交互规范（对齐成熟频谱分析工具）：
- 滚轮：X 轴缩放（锚定鼠标位置，单轴）
- Shift+滚轮：Y 轴缩放（锚定鼠标位置）
- 左键拖动：平移；右键拖动：框选缩放
- 双击：重置视图
- 左键单击峰：切换标记（已有则取消）
- 右键单击：标记管理菜单
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QSize, Qt, QEvent
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QAbstractItemView,
    QFrame,
    QSizePolicy,
    QToolBar,
)

from acouscope.i18n import tr
from acouscope.dsp.units import (
    FREQ_UNITS,
    MAG_UNITS,
    convert_freq_axis,
    convert_mag_axis,
    freq_unit_label,
    mag_unit_label,
    hz_to_note_name,
)

from acouscope.ui import theme
from acouscope.ui.widgets.peak_marks_panel import PeakMarksPanel
from acouscope.ui.widgets.toast import show_toast

CLICK_DRAG_THRESHOLD = 5  # 像素，小于此距离视为单击而非拖动

# F4：谱波标记表第 5 列是「相对最强峰归一化」的 dBr（mag_db 恒以最强峰为 0），
# 非绝对 dBFS 电平。表头文案与 tooltip 说明共用同一处定义（单一数据源）。
_MARKS_MAG_HEADER = "相对幅度 (dBr)"
_MARKS_MAG_TOOLTIP = (
    "相对幅度 (dBr)：20·log10(峰值幅度 / 最强峰幅度)，"
    "以本表最强峰为 0 dBr 参考（最强峰恒 0.0）；非绝对 dBFS 电平。"
)


def _fit_combo_width(combo: QComboBox) -> None:
    """下拉框宽度自适应最长条目（含下拉箭头与边距），避免文字截断。"""
    from acouscope.ui.widgets.freq_axis import fit_combo_width

    fit_combo_width(combo)


def _zero_row_vmargins(bar: QToolBar) -> None:
    """工具行布局上下边距清零、左右保留原值（G4a-4-Δ2 钩子，Δ3 起只作兜底）。

    Δ3 已把 QSS `padding` 归零，正常情况下边距本来就是 (0,0,0,0)，本函数早退、
    零成本。留着它是为个别风格/平台在 polish 时仍写回上下边距的情形兜底：
    只清上下、左右不动，行高由可见子件最小高导出。

    ★ 行高不由本钩子导出：本钩子只改 `layout().contentsMargins()`（sizeHint 的
      依据），动不了 `QToolBarLayout` 的定位偏移 —— 靠它去补 padding 留下的
      偏移，结果就是「行高 36、内容 42」的子件越界裁切。故禁借此复活
      setFixedHeight / setMaximumHeight。
    """
    lay = bar.layout()
    if lay is None:  # QToolBar 构造即建布局；此处只防析构期空布局
        return
    m = lay.contentsMargins()
    if m.top() == 0 and m.bottom() == 0:
        return
    lay.setContentsMargins(m.left(), 0, m.right(), 0)


class _ViewToolRow(QToolBar):
    """工具行容器（G4a-4-Δ2 事件钩子，Δ3 起只作兜底）。

    Δ3 把 QSS `padding` 归零后，布局边距通常已是 (0,0,0,0)，正常路径上钩子空转。
    保留它是防个别风格/平台在 polish / 换父件 / 换主题时仍写回上下边距 —— 那时
    重新收口一次。行高始终由可见子件最小高自然导出，不写死任何像素。
    """

    _REZERO_EVENTS = frozenset((
        QEvent.Type.Polish,
        QEvent.Type.StyleChange,
        QEvent.Type.Show,
        QEvent.Type.ParentChange,
    ))

    def event(self, ev):  # noqa: N802（Qt 命名）
        handled = super().event(ev)   # 先让基类/样式引擎处理，再收口
        if ev.type() in self._REZERO_EVENTS:
            _zero_row_vmargins(self)
        return handled


def make_view_tool_row(owner: QWidget, spacing: int = 8) -> QToolBar:
    """分析视图的统一工具行容器（G4a-4）。

    为什么不是 QHBoxLayout：横排布局把「所有控件的最小宽之和」原样上报给
    `minimumSizeHint`，窄窗下只能把控件压到 0 宽（截断），并顺带把
    `analysis_panel` 顶到 1665。换成 QToolBar 后，放不下的控件由 Qt 收进
    尾部「»」扩展菜单（`qt_toolbar_ext_button`），工具行最小宽只留扩展按钮。

    QSS 冲突处理：全局 `QToolBar` 规则带 bg1 底 + 下描边（多 1 px 且会撑高），
    此处按控件覆写为透明无框；`spacing` 只能用 QSS 给（QToolBar 无 setSpacing）。

    ★ 全树唯一实现：其余视图一律 `from ...spectrum import make_view_tool_row`
      复用，禁各视图各写一套。
    """
    bar = _ViewToolRow(owner)
    bar.setObjectName("viewToolRow")
    bar.setMovable(False)          # 禁拖动（工具行不重排）
    bar.setFloatable(False)        # 禁浮动（不脱窗）
    bar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
    bar.setContentsMargins(0, 0, 0, 0)
    bar.setIconSize(QSize(16, 16))
    # G4a-4-Δ3：padding 一律归零。QSS 的 `padding` 由样式引擎按**四边同值**写回
    # 布局边距 —— 写 `1 px 6 px`（本意垂直 1、水平 6）实测得到 (6,6,6,6)：行高被
    # 撑到 48，而「清边距」只改了 sizeHint 的依据、QToolBarLayout 的 6 px 定位
    # 偏移仍在，于是子件底边越出行底 6 px 被裁。写 `0 px 6 px` 同样不行（水平值 6
    # 照样写回垂直）。故不留任何 padding，水平呼吸位改由行内 spacing 承担。
    bar.setStyleSheet(
        "QToolBar { background: transparent; border: none;"
        " padding: 0; spacing: %dpx; }" % spacing
    )
    bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    # G4a-4-Δ2：行高不钉死。padding 归零后行高 = 「可见子件最小高」自然导出
    # （实测 36/37），既不吃画布净高，也不压子件换行高。禁再写死像素值
    # （setFixedHeight / setMaximumHeight 一律不许复活）。
    return bar


def pin_tool_row_widths(bar: QToolBar) -> None:
    """工具行内「按内容定宽」的控件锁成 Fixed（G4a-4）。

    QToolBar 在最后一件只放得下一半时会按「最小宽」把它压扁 —— 下拉框被压成
    只剩一个箭头，观感等同截断（且 `have < minimumSizeHint` 判不出来）。
    锁成 Fixed 后最小宽 = 内容宽，Qt 只能整件收进「»」溢出菜单。
    必须在控件全部 addWidget 之后调用（四视图均走此处，行高也在末尾一并收口）。
    """
    from PyQt6.QtWidgets import QAbstractSpinBox

    for w in bar.findChildren(
        QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
    ):
        if isinstance(w, (QComboBox, QAbstractSpinBox, QPushButton, QLabel)):
            w.setSizePolicy(
                QSizePolicy.Policy.Fixed, w.sizePolicy().verticalPolicy()
            )
    _zero_row_vmargins(bar)


def tool_field(label: QLabel, control: QWidget) -> QWidget:
    """把「说明标签 + 控件」捆成一件（G4a-4）。

    QToolBar 的溢出粒度是「单个 widget action」：不捆的话，窄宽下会出现
    「Window:」留在行上、它的下拉框却进了「»」菜单的孤儿标签。
    捆成一件后整组一起溢出，读起来始终成对。
    """
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(label)
    lay.addWidget(control)
    box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return box


def compact_glyph_button(btn: QPushButton, width: int) -> None:
    """把符号按钮压到「内容宽 = 给定宽」（G4a-4 第 3 条）。

    全局 QSS 的内边距会把 ``+``/``−``/``⤢`` 这类单字符按钮的最小宽抬到 80，
    旧代码再用 setMaximumWidth(30) 硬压 → 每帧都算「截断」。这里把内边距归零、
    宽度取符号实际所需（固定宽 = 内容宽，不是压缩上限）。
    """
    btn.setStyleSheet("QPushButton { padding: 0; }")
    btn.setFixedWidth(width)


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


class _PlotInteraction(QObject):
    """频谱图交互事件过滤器。

    在 PlotWidget viewport 上安装，职责：
    - 区分单击与拖动（释放时位移 < 阈值才算单击）
    - 拦截滚轮事件做锚定单轴缩放
    - 双击重置视图
    """

    def __init__(self, plot_widget: pg.PlotWidget, click_cb: Callable,
                 wheel_cb: Callable, dblclick_cb: Callable):
        super().__init__(plot_widget)
        self.plot_widget = plot_widget
        self.click_cb = click_cb
        self.wheel_cb = wheel_cb
        self.dblclick_cb = dblclick_cb
        self._press_pos = None
        self._press_button = None

        self.plot_widget.viewport().installEventFilter(self)

    def detach(self) -> None:
        """摘掉 viewport 事件过滤器（幂等、绝不出错）——收尾断环用。"""
        try:
            viewport = self.plot_widget.viewport()
        except RuntimeError:
            return  # 控件已销毁
        if viewport is None:
            return
        try:
            viewport.removeEventFilter(self)
        except RuntimeError:
            pass

    def _to_view(self, event):
        """事件像素坐标转数据坐标。"""
        scene_pos = self.plot_widget.mapToScene(event.position().toPoint())
        return self.plot_widget.plotItem.vb.mapSceneToView(scene_pos)

    def eventFilter(self, obj, event):
        try:
            viewport = self.plot_widget.viewport()
        except RuntimeError:
            # 控件已销毁，消费所有事件防止访问失效对象
            return True
        if obj is not viewport:
            return super().eventFilter(obj, event)

        etype = event.type()

        if etype == QEvent.Type.MouseButtonPress:
            self._press_pos = event.position()
            self._press_button = event.button()
            # 不消费按下事件，让 pyqtgraph 处理拖动平移/框选

        elif etype == QEvent.Type.MouseButtonRelease:
            if self._press_pos is not None:
                moved = (event.position() - self._press_pos).manhattanLength()
                if moved < CLICK_DRAG_THRESHOLD and event.button() == self._press_button:
                    view_pos = self._to_view(event)
                    btn = 1 if event.button() == Qt.MouseButton.LeftButton else (
                        2 if event.button() == Qt.MouseButton.RightButton else 0
                    )
                    if btn > 0:
                        self.click_cb(btn, float(view_pos.x()), float(view_pos.y()))
            self._press_pos = None
            self._press_button = None

        elif etype == QEvent.Type.Wheel:
            # 消费滚轮：自定义锚定单轴缩放（默认行为是双轴缩放，会"到处乱跑"）
            view_pos = self._to_view(event)
            delta = event.angleDelta().y()
            if delta != 0:
                self.wheel_cb(delta, float(view_pos.x()), float(view_pos.y()),
                              bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            return True

        elif etype == QEvent.Type.MouseButtonDblClick:
            self.dblclick_cb()
            return True

        return super().eventFilter(obj, event)


class SpectrumWidget(QWidget):
    """高级频谱显示控件（音乐声学研究专用）。"""

    @staticmethod
    def _default_freq_unit_index() -> int:
        """默认频率单位在 FREQ_UNITS 中的索引（钢琴卷帘）。"""
        for i, (_, key, _) in enumerate(FREQ_UNITS):
            if key == "piano":
                return i
        return 0

    # 预设频率范围（基于 Hz，内部统一用 Hz 存储）
    FREQ_RANGES_HZ = [
        ("500 Hz", 500),
        ("1 kHz", 1000),
        ("2 kHz", 2000),
        ("5 kHz", 5000),
        ("10 kHz", 10000),
        ("20 kHz", 20000),
        ("全频段", None),
    ]

    # 可用窗函数
    WINDOW_TYPES = [
        ("Hann", "hann"),
        ("Hamming", "hamming"),
        ("Blackman", "blackman"),
        ("矩形", "rectangular"),
    ]

    # FFT 大小选项（Audacity 风格）
    FFT_SIZES = [
        ("128", 128),
        ("256", 256),
        ("512", 512),
        ("1024", 1024),
        ("2048", 2048),
        ("4096", 4096),
        ("8192", 8192),
        ("16384", 16384),
        ("32768", 32768),
        ("65536", 65536),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        # 当前单位（默认钢琴卷帘视图）
        self._freq_unit = "piano"
        self._mag_unit = "linear"

        # 原始数据（始终以 Hz + 线性幅度存储）
        self._freqs_hz = np.array([])
        self._magnitude_linear = np.array([])
        self._sample_rate = 44100.0
        self._signal_data = None
        self._peak_hold_data = np.array([])

        # 手动标记的峰值列表 [{freq, magnitude, note, cents, midi}]
        self._manual_peaks = []
        # 最近一次「找峰值」检测结果（供 F-3 内嵌标记面板使用）
        self._last_peaks: list[dict] = []
        # 标记图形项（竖线 + 文本，随标记增删重建，缩放时不重建）
        self._mark_items = []

        # Y 轴锁定（用户手动缩放 Y 后自动锁定，按钮可解锁）
        self._y_locked = False
        self._in_programmatic_range = False

        # 回调
        self.window_changed_callback: Optional[Callable[[str], None]] = None
        self._window_type = "hann"

        # === 布局 ===
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- 工具栏 ----
        self._build_toolbar(layout)

        # ---- 信息栏 ----
        self._build_info_bar(layout)

        # ---- 频谱图 + 钢琴键盘 ----
        self._build_plot(layout)

        # ---- 标记面板（数值表） ----
        self._build_marks_panel(layout)

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_toolbar(self, parent_layout):
        """构建顶部工具行。

        G4a-4：容器由 QHBoxLayout 改 QToolBar —— 窄宽下 Qt 自动把放不下的
        次要动作收进尾部「»」扩展菜单（overflow），工具行不再把整页最小宽
        顶到 1665。加入顺序即优先级：越靠前越常驻（左端标题/和弦 + 右端
        单位 → 显示参数 → 标记动作 → 缩放）。
        """
        toolbar = make_view_tool_row(self)
        self.tool_row = toolbar

        self.lbl_title = QLabel(tr("spectrum.title"))
        self.lbl_title.setStyleSheet(
            f"font-weight: bold; font-size: {theme.TOKENS['typography']['body']}px;")
        toolbar.addWidget(self.lbl_title)

        # 和弦/标记摘要显示（T-1038 M4：底块改走中性阶 bg2，禁主题互斥硬编码浅底）
        self.lbl_chord = QLabel(tr("spectrum.single_tone_none"))
        self.lbl_chord.setStyleSheet(
            f"color: {theme.colors()['accent']}; font-weight: bold;"
            f" font-size: {theme.TOKENS['typography']['body']}px;"
            f" padding: {theme.TOKENS['spacing']['xxs']}px"
            f" {theme.TOKENS['spacing']['sm']}px;"
            f" background: {theme.colors()['bg2']};"
            f" border: {theme.TOKENS['elevation']['border']}px solid"
            f" {theme.colors()['border']};"
            f" border-radius: {theme.TOKENS['radius']['sm']}px;"
        )
        toolbar.addWidget(self.lbl_chord)

        # X 轴单位
        self.cmb_x_unit = QComboBox()
        for label, key, tip in FREQ_UNITS:
            self.cmb_x_unit.addItem(label, key)
            self.cmb_x_unit.setItemData(self.cmb_x_unit.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.cmb_x_unit.setCurrentIndex(self._default_freq_unit_index())
        _fit_combo_width(self.cmb_x_unit)
        self.cmb_x_unit.currentIndexChanged.connect(self._on_x_unit_changed)
        toolbar.addWidget(tool_field(QLabel(tr("spectrum.axis_x")), self.cmb_x_unit))

        # Y 轴单位
        self.cmb_y_unit = QComboBox()
        for label, key, tip in MAG_UNITS:
            self.cmb_y_unit.addItem(label, key)
            self.cmb_y_unit.setItemData(self.cmb_y_unit.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.cmb_y_unit.setCurrentIndex(0)
        _fit_combo_width(self.cmb_y_unit)
        self.cmb_y_unit.currentIndexChanged.connect(self._on_y_unit_changed)
        toolbar.addWidget(tool_field(QLabel(tr("spectrum.axis_y")), self.cmb_y_unit))

        # 窗函数（G4a-4：删 90 px 硬上限 → 最小内容宽，空间富余时不再被钉死）
        self.cmb_window = QComboBox()
        for label, _ in self.WINDOW_TYPES:
            self.cmb_window.addItem(label)
        self.cmb_window.setCurrentIndex(0)
        self.cmb_window.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_window.setMinimumContentsLength(6)
        self.cmb_window.currentIndexChanged.connect(self._on_window_changed)
        toolbar.addWidget(tool_field(QLabel(tr("spectrum.window")), self.cmb_window))

        # FFT 大小
        self.cmb_fft_size = QComboBox()
        for label, _ in self.FFT_SIZES:
            self.cmb_fft_size.addItem(label)
        self.cmb_fft_size.setCurrentIndex(4)  # 默认 2048
        self.cmb_fft_size.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_fft_size.setMinimumContentsLength(5)
        self.cmb_fft_size.currentIndexChanged.connect(self._on_fft_size_changed)
        toolbar.addWidget(tool_field(QLabel("FFT:"), self.cmb_fft_size))

        # 峰值检测按钮
        self.btn_find_peaks = QPushButton("找峰值")
        self.btn_find_peaks.setToolTip(tr("spectrum.tip_peak_detect"))
        self.btn_find_peaks.setStyleSheet(
            f"font-size: {theme.TOKENS['typography']['body_sm']}px;"
            f" padding: {theme.TOKENS['spacing']['xxs']}px"
            f" {theme.TOKENS['spacing']['sm']}px;")
        self.btn_find_peaks.clicked.connect(self._on_find_peaks)
        toolbar.addWidget(self.btn_find_peaks)

        # 峰值标记面板开关（非模态内嵌，CB-002 F-3）
        self.btn_peaks_panel = QPushButton("标记面板")
        self.btn_peaks_panel.setCheckable(True)
        self.btn_peaks_panel.setToolTip(tr("spectrum.tip_toggle_marks"))
        self.btn_peaks_panel.setStyleSheet(
            f"font-size: {theme.TOKENS['typography']['body_sm']}px;"
            f" padding: {theme.TOKENS['spacing']['xxs']}px"
            f" {theme.TOKENS['spacing']['sm']}px;")
        self.btn_peaks_panel.toggled.connect(self._toggle_peaks_panel)
        toolbar.addWidget(self.btn_peaks_panel)

        # 频率范围
        self.cmb_range = QComboBox()
        for label, _ in self.FREQ_RANGES_HZ:
            self.cmb_range.addItem(label)
        self.cmb_range.setCurrentIndex(1)  # 默认 1 kHz
        self.cmb_range.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_range.setMinimumContentsLength(6)
        self.cmb_range.currentIndexChanged.connect(self._update_display)
        toolbar.addWidget(tool_field(QLabel(tr("spectrum.range")), self.cmb_range))

        # 峰值保持
        self.btn_hold = QPushButton("保持")
        self.btn_hold.setCheckable(True)
        self.btn_hold.setChecked(False)
        self.btn_hold.setToolTip(tr("spectrum.tip_peak_hold"))
        self.btn_hold.toggled.connect(self._toggle_peak_hold)
        toolbar.addWidget(self.btn_hold)

        # 分隔线（显示控制 | 标记操作）
        from acouscope.ui.theme import style_when_theme

        sep_marks = QFrame()
        sep_marks.setFrameShape(QFrame.Shape.NoFrame)
        sep_marks.setFixedWidth(1)
        style_when_theme(sep_marks, lambda c: f"background: {c['border']};")
        toolbar.addWidget(sep_marks)

        # 标记操作按钮（置于工具栏，论文截图时随顶部控件排除在图外）
        self.btn_auto_detect = QPushButton("自动检测分音")
        self.btn_auto_detect.setToolTip(tr("spectrum.tip_auto_mark"))
        self.btn_auto_detect.clicked.connect(self._auto_detect_peaks)
        toolbar.addWidget(self.btn_auto_detect)

        self.btn_clear_marks = QPushButton("清除标记")
        self.btn_clear_marks.setToolTip(tr("spectrum.tip_clear_marks"))
        self.btn_clear_marks.clicked.connect(self._clear_all_marks)
        toolbar.addWidget(self.btn_clear_marks)

        self.btn_copy_marks = QPushButton("复制数据")
        self.btn_copy_marks.setToolTip(tr("spectrum.tip_copy_table"))
        self.btn_copy_marks.clicked.connect(self._copy_marks_to_clipboard)
        toolbar.addWidget(self.btn_copy_marks)

        # 缩放按钮组（符号按钮：固定宽 = 符号内容宽，见 compact_glyph_button）
        self.btn_zoom_in = QPushButton("+")
        compact_glyph_button(self.btn_zoom_in, 28)
        self.btn_zoom_in.setToolTip(tr("spectrum.tip_zoom_in"))
        self.btn_zoom_in.clicked.connect(lambda: self._zoom_center(1.3))
        toolbar.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("−")
        compact_glyph_button(self.btn_zoom_out, 28)
        self.btn_zoom_out.setToolTip(tr("spectrum.tip_zoom_out"))
        self.btn_zoom_out.clicked.connect(lambda: self._zoom_center(1 / 1.3))
        toolbar.addWidget(self.btn_zoom_out)

        self.btn_zoom_fit = QPushButton("⤢")
        compact_glyph_button(self.btn_zoom_fit, 30)
        self.btn_zoom_fit.setToolTip(tr("spectrum.tip_fit"))
        self.btn_zoom_fit.clicked.connect(self._zoom_fit)
        toolbar.addWidget(self.btn_zoom_fit)

        # Y 轴锁定按钮
        self.btn_y_lock = QPushButton("Y自动")
        self.btn_y_lock.setCheckable(True)
        self.btn_y_lock.setChecked(False)
        self.btn_y_lock.setToolTip(tr("spectrum.y_follow_tooltip"))
        self.btn_y_lock.toggled.connect(self._on_y_lock_toggled)
        toolbar.addWidget(self.btn_y_lock)

        pin_tool_row_widths(toolbar)
        parent_layout.addWidget(toolbar)

    def _build_info_bar(self, parent_layout):
        """构建信息栏。"""
        info_bar = QHBoxLayout()
        info_bar.setContentsMargins(6, 2, 6, 4)
        info_bar.setSpacing(12)

        self.lbl_freq = QLabel(tr("spectrum.freq_none"))
        self.lbl_freq.setStyleSheet(
            f"color: {theme.colors()['text_sub']};"
            f" font-size: {theme.TOKENS['typography']['body_sm']}px;")
        info_bar.addWidget(self.lbl_freq)

        self.lbl_mag = QLabel(tr("spectrum.amp_none"))
        self.lbl_mag.setStyleSheet(
            f"color: {theme.colors()['text_sub']};"
            f" font-size: {theme.TOKENS['typography']['body_sm']}px;")
        info_bar.addWidget(self.lbl_mag)

        self.lbl_note = QLabel(tr("spectrum.note_none"))
        self.lbl_note.setStyleSheet(
            f"color: {theme.colors()['text_sub']};"
            f" font-size: {theme.TOKENS['typography']['body_sm']}px;")
        info_bar.addWidget(self.lbl_note)

        self.lbl_resolution = QLabel("")
        self.lbl_resolution.setStyleSheet(
            f"color: {theme.colors()['text_faint']};"
            f" font-size: {theme.TOKENS['typography']['caption']}px;")
        info_bar.addStretch()
        info_bar.addWidget(self.lbl_resolution)

        info_widget = QWidget()
        info_widget.setLayout(info_bar)
        info_widget.setMaximumHeight(22)
        parent_layout.addWidget(info_widget)

    def _build_plot(self, parent_layout):
        """构建频谱图 + 钢琴键盘。"""
        self.splitter_plot = QSplitter(Qt.Orientation.Vertical)
        self.splitter_plot.setChildrenCollapsible(False)

        # 主频谱图
        self.plot_widget = pg.PlotWidget()
        _apply_canvas_theme(self.plot_widget)
        # 关闭滚动条：截屏时拉杆会挡住图表边缘，导致无法截满整图
        self.plot_widget.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.plot_widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("bottom", "频率", units="Hz")
        self.plot_widget.setLabel("left", "幅度")
        self.splitter_plot.addWidget(self.plot_widget)

        # 主曲线（antialias=False：软件光栅化下 AA 是数量级开销）
        self.curve = self.plot_widget.plot(
            pen=pg.mkPen(color=theme.data_ink("trace"), width=2.7),
            antialias=False,
        )

        # 峰值保持曲线
        self.curve_hold = self.plot_widget.plot(
            pen=pg.mkPen(color=theme.data_ink("trace_alt"), width=0.8,
                         style=Qt.PenStyle.DashLine),
            antialias=False,
        )
        self.curve_hold.setVisible(False)

        # 标记峰顶小三角
        self._peak_marker = self.plot_widget.plot(
            pen=None,
            symbol="t1",
            symbolSize=9,
            symbolBrush=theme.data_ink("marker"),
            symbolPen=None,
        )

        # 交叉线游标
        self.v_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=True,
            pen=pg.mkPen(color=theme.data_ink("cursor"), width=2.7,
                         style=Qt.PenStyle.DashLine),
        )
        self.h_line = pg.InfiniteLine(
            pos=0,
            angle=0,
            movable=False,
            pen=pg.mkPen(color=theme.data_ink("cursor"), width=2.7,
                         style=Qt.PenStyle.DashLine),
        )
        self.plot_widget.addItem(self.v_line)
        self.plot_widget.addItem(self.h_line)
        self.v_line.sigPositionChanged.connect(self._on_cursor_moved)
        self.h_line.sigPositionChanged.connect(self._on_cursor_moved)

        # 禁用默认右键菜单
        self.plot_widget.getPlotItem().setMenuEnabled(False)

        vb = self.plot_widget.plotItem.vb
        # X 轴范围变化时：Y 自动跟随 + 钢琴键盘同步
        vb.sigXRangeChanged.connect(self._on_x_range_changed)

        # 安装交互事件过滤器（单击标记 / 滚轮缩放 / 双击重置）
        self._interaction = _PlotInteraction(
            self.plot_widget,
            self._on_plot_clicked,
            self._on_wheel,
            self._zoom_fit,
        )

        # 钢琴键盘（初始隐藏，切换到钢琴卷帘时显示）
        self.keyboard_widget = pg.PlotWidget()
        _apply_canvas_theme(self.keyboard_widget, "bg2")
        self.keyboard_widget.setMinimumHeight(55)
        self.keyboard_widget.setMaximumHeight(70)
        self.keyboard_widget.setMouseEnabled(x=False, y=False)
        self.keyboard_widget.hideAxis("left")
        self.keyboard_widget.hideAxis("right")
        self.keyboard_widget.hideAxis("top")
        # ★ T-1042c：音名改画进键床内（§2.1-②，竖横同一套）→ 隐藏音名轴，
        # 键床铺满整个部件可见区（键床覆盖率 ≥0.95 的像素判据 e 依赖此项）。
        self.keyboard_widget.hideAxis("bottom")
        self.keyboard_widget.setXLink(self.plot_widget)  # X 轴与频谱图联动
        # ★ T-1042c 缺陷 C：关闭键盘自身自动量程 —— 否则每次重建键床时，X 范围被
        # 键床包围盒「撑开」（实测 20.5–108.5 → 12.2–108.5），键床左端便与视图错位、
        # 露出键带底（中线背景段 40 像素）。关闭后 X 范围严格等于宿主（联动源）范围。
        self.keyboard_widget.enableAutoRange(x=False, y=False)
        self.keyboard_widget.setContentsMargins(0, 0, 0, 0)
        self.splitter_plot.addWidget(self.keyboard_widget)
        theme.on_theme_change(self._on_canvas_theme)

        # 存储键盘图形项
        self._keyboard_items = []
        # 默认钢琴卷帘视图 → 键盘默认可见
        self._keyboard_visible = True

        # 设置初始 splitter 比例
        self.splitter_plot.setSizes([500, 55])

        parent_layout.addWidget(self.splitter_plot, stretch=1)

    def _build_marks_panel(self, parent_layout):
        """构建标记面板：峰值标记内嵌面板（非模态）+ 操作按钮 + 数值表。"""
        # CB-002 F-3：峰值标记内嵌面板（默认隐藏，由工具栏「标记面板」开关）
        self._peaks_panel = PeakMarksPanel()
        self._peaks_panel.setVisible(False)
        self._peaks_panel.marksRequested.connect(self._on_panel_mark_peaks)
        self._peaks_panel.unmarkRequested.connect(self._on_panel_unmark_peaks)
        parent_layout.addWidget(self._peaks_panel)

        panel = QWidget()
        # 配色改为跟随主题（令牌优先 V099_TOKENS_V1）：
        # 原"强制浅底防深色下白字不可见"的冻结写法，令牌化后由 colors()
        # 统一提供 bg/text 配对即自然可见，无需再冻为浅色。
        panel.setObjectName("marksPanel")

        def _marks_qss(c):
            # T-1038 M3：描边/半径/内边距一律令牌插值，禁字面 px
            sp = theme.TOKENS["spacing"]
            el = theme.TOKENS["elevation"]["border"]
            rad = f"{sp['xxs'] + el}px"
            return (
                f"#marksPanel {{ background: {c['panel']}; }}"
                f"#marksPanel QLabel {{ color: {c['text']}; }}"
                f"#marksPanel QPushButton {{"
                f" background: {c['btn']}; color: {c['text']};"
                f" border: {el}px solid {c['border']}; border-radius: {rad};"
                f" padding: {sp['xxs']}px {theme.TOKENS['control']['pad_x']}px;"
                f"}}"
                f"#marksPanel QPushButton:hover {{ background: {c['btn_hover']}; }}"
                f"#marksPanel QPushButton:pressed {{ background: {c['accent']}; color: {c['accent_text']}; }}"
                f"#marksPanel QTableWidget {{"
                f" background: {c['panel']}; color: {c['text']};"
                f" gridline-color: {c['border']}; border: {el}px solid {c['border']};"
                f"}}"
                f"#marksPanel QHeaderView::section {{"
                f" background: {c['btn']}; color: {c['text']};"
                f" border: none; border-bottom: {el}px solid {c['border']};"
                f" padding: {sp['xxs']}px {sp['xs']}px;"
                f"}}"
            )

        self._refresh_marks_style = theme.style_when_theme(panel, _marks_qss)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        # 头部：仅标题 + 计数（按钮已移至频谱工具栏，保持表格区域纯净便于论文截图）
        header = QHBoxLayout()
        header.setSpacing(6)

        self.lbl_marks_title = QLabel(tr("spectrum.harmonic_marks").format(n=0))
        self.lbl_marks_title.setStyleSheet(
            f"font-weight: bold; font-size: {theme.TOKENS['typography']['body_sm']}px;")
        header.addWidget(self.lbl_marks_title)

        header.addStretch()

        layout.addLayout(header)

        # 数值表
        self.marks_table = QTableWidget(0, 7)
        self.marks_table.setHorizontalHeaderLabels(
            ["#", "频率 (Hz)", "音名", "音分偏差", _MARKS_MAG_HEADER, "Δ音分", "n×基频"]
        )
        # F4：第 5 列表头明确相对口径，并挂口径说明 tooltip
        self.marks_table.horizontalHeaderItem(4).setToolTip(_MARKS_MAG_TOOLTIP)
        header_view = self.marks_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, 7):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.marks_table.verticalHeader().setVisible(False)
        self.marks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.marks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # 高度随标记行数自适应（_fit_marks_table_height），
        # 避免固定上限导致出现滚动条、截屏时拉杆遮挡内容
        self.marks_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.marks_table.itemDoubleClicked.connect(self._on_mark_row_double_clicked)
        # Delete 键删除选中行对应的标记
        self.marks_table.installEventFilter(self)
        layout.addWidget(self.marks_table)

        # 交互说明（G4a-4）：原为表格下方整行 QLabel —— 单行不换行、需 613 px，
        # 直接把 FFT 页最小宽顶到 1665（本页最大单项）。改挂 tooltip +
        # 读屏可访问描述：说明文字一字不减，但不占行宽。
        _peak_hint = tr("spectrum.peak_mark_hint")
        self.marks_table.setToolTip(_peak_hint)
        self.marks_table.setAccessibleDescription(_peak_hint)

        parent_layout.addWidget(panel)

    # ============================================================
    # 表格事件（Delete 删除标记）
    # ============================================================

    def eventFilter(self, obj, event):
        if obj is self.marks_table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                row = self.marks_table.currentRow()
                if 0 <= row < len(self._manual_peaks):
                    self._remove_mark(row)
                return True
        return super().eventFilter(obj, event)

    # ============================================================
    # 数据接口
    # ============================================================

    def set_data(
        self,
        freqs: np.ndarray,
        magnitude: np.ndarray,
        title: str = "频谱",
        db_scale: bool = False,
        sample_rate: float = 44100.0,
        signal_data: np.ndarray | None = None,
    ):
        """设置频谱数据。

        输入数据始终以 Hz 和线性幅度存储（内部标准格式）。
        新数据默认只自动标记基频（最强峰），其他谐波不标记。
        """
        self._freqs_hz = freqs
        self._sample_rate = sample_rate
        self._signal_data = signal_data

        if db_scale:
            self._magnitude_linear = 10 ** (magnitude / 20.0)
        else:
            self._magnitude_linear = np.maximum(magnitude, 1e-12)

        self.lbl_title.setText(title)

        # 标记处理：
        # - 首次（无标记）：默认只标记基频（最强峰）
        # - 已有标记（指针移动/换窗函数）：重新吸附到新频谱的峰值，
        #   保留用户手动增删的结果，无邻近峰值的标记丢弃
        prev_marks = self._manual_peaks
        self._manual_peaks = []
        if prev_marks:
            for m in prev_marks:
                peak = self._find_nearest_peak(m["freq"])
                if peak is not None:
                    self._manual_peaks.append(peak)
            self._manual_peaks.sort(key=lambda x: x["freq"])
        else:
            peaks = self._detect_peaks(max_peaks=1, mag_threshold=0.001)
            if peaks:
                self._manual_peaks = peaks[:1]

        # 分辨率信息
        if len(freqs) > 1:
            res = freqs[1] - freqs[0]
            n_fft = 2 * (len(freqs) - 1)
            self.lbl_resolution.setText(
                tr("spectrum.resolution_info").format(res=f"{res:.2f}", n=int(n_fft))
            )

        # 重置峰值保持
        if self.btn_hold.isChecked():
            self._peak_hold_data = self._magnitude_linear.copy()

        # Y 锁定状态重置（新数据自动跟随）
        self._set_y_locked(False)

        self._update_display()

    # ============================================================
    # 单位切换
    # ============================================================

    def _on_x_unit_changed(self, index: int):
        """X 轴单位变化。"""
        self._freq_unit = self.cmb_x_unit.itemData(index)
        is_piano = self._freq_unit == "piano"
        self._toggle_piano_keyboard(is_piano)
        self._update_display()

    def _on_y_unit_changed(self, index: int):
        """Y 轴单位变化。"""
        self._mag_unit = self.cmb_y_unit.itemData(index)
        self._update_display()

    def _get_display_x(self) -> np.ndarray:
        return convert_freq_axis(self._freqs_hz, self._freq_unit)

    def _get_display_y(self) -> np.ndarray:
        return convert_mag_axis(self._magnitude_linear, self._mag_unit, self._freqs_hz)

    def _get_hold_y(self) -> np.ndarray:
        if len(self._peak_hold_data) == 0:
            return np.array([])
        return convert_mag_axis(self._peak_hold_data, self._mag_unit, self._freqs_hz)

    def _x_unit_label(self) -> str:
        return freq_unit_label(self._freq_unit)

    def _y_unit_label(self) -> str:
        return mag_unit_label(self._mag_unit)

    def _x_axis_label(self) -> str:
        """导出用 X 轴完整标签（与窗口显示一致）。"""
        from acouscope.dsp.units import get_reference_hz
        return {
            "hz": "频率 (Hz)",
            "khz": "频率 (kHz)",
            "midi": "MIDI 音高",
            "piano": "MIDI 音高",
            "cents": f"音分（相对 A4={get_reference_hz():.0f}Hz）",
            "mel": "Mel 标度",
        }.get(self._freq_unit, "频率")

    def _y_axis_label(self) -> str:
        """导出用 Y 轴完整标签（与窗口显示一致）。"""
        return {
            "linear": "幅度（线性）",
            "db": "幅度 (dB)",
            "dbfs": "幅度 (dBFS)",
            "dba": "A 计权声级 (dB(A))",
            "norm": "幅度 (%)",
        }.get(self._mag_unit, "幅度")

    def get_view_export(self) -> dict:
        """导出当前视图所需数据（与窗口显示完全一致）。

        Returns:
            dict: x/y 当前显示单位的数据（仅可见段）、xlim/ylim 当前视图范围、
            xlabel/ylabel 轴标签、markers [(x显示单位, 标签)] 仅可见标记
        """
        x = self._get_display_x()
        y = self._get_display_y()
        finite = np.isfinite(x) & np.isfinite(y)
        x, y = x[finite], y[finite]
        if len(x) < 2:
            raise ValueError("频谱数据为空")

        try:
            x_view, y_view = self.plot_widget.plotItem.vb.viewRange()
            xlim = (float(x_view[0]), float(x_view[1]))
            ylim = (float(y_view[0]), float(y_view[1]))
        except Exception:
            xlim = (float(x[0]), float(x[-1]))
            ylim = None

        # 仅保留可见 X 范围（缩放/平移/预设范围都体现在 viewRange 中）
        mask = (x >= xlim[0]) & (x <= xlim[1])
        if mask.sum() >= 2:
            x, y = x[mask], y[mask]

        markers = []
        for p in self._manual_peaks:
            mx = self._hz_to_display_x(float(p["freq"]))
            if np.isfinite(mx) and xlim[0] <= mx <= xlim[1]:
                markers.append((float(mx), str(p.get("note", ""))))

        return {
            "x": x,
            "y": y,
            "xlim": xlim,
            "ylim": ylim,
            "xlabel": self._x_axis_label(),
            "ylabel": self._y_axis_label(),
            "markers": markers,
        }

    # ============================================================
    # 显示更新
    # ============================================================

    def _update_display(self):
        """根据当前设置更新整个显示。"""
        if len(self._freqs_hz) == 0:
            return

        x = self._get_display_x()
        y = self._get_display_y()

        # 剔除非有限值（DC 分量在 MIDI/音分单位下为 -inf）
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.all(finite):
            x, y = x[finite], y[finite]

        self.curve.setData(x, y)

        # 轴标签
        if self._freq_unit == "hz":
            self.plot_widget.setLabel("bottom", "频率", units="Hz")
        elif self._freq_unit == "khz":
            self.plot_widget.setLabel("bottom", "频率", units="kHz")
        elif self._freq_unit == "midi":
            self.plot_widget.setLabel("bottom", "MIDI 音高")
        elif self._freq_unit == "piano":
            self.plot_widget.setLabel("bottom", "频率", units="Hz")
        elif self._freq_unit == "cents":
            from acouscope.dsp.units import get_reference_hz
            self.plot_widget.setLabel("bottom", f"音分（相对 A4={get_reference_hz():.0f}Hz）")
        elif self._freq_unit == "mel":
            self.plot_widget.setLabel("bottom", "Mel")
        else:
            self.plot_widget.setLabel("bottom", "频率")

        if self._mag_unit == "db":
            self.plot_widget.setLabel("left", "幅度", units="dB")
        elif self._mag_unit == "dbfs":
            self.plot_widget.setLabel("left", "幅度", units="dBFS")
        elif self._mag_unit == "dba":
            self.plot_widget.setLabel("left", "A 计权声级", units="dB(A)")
        elif self._mag_unit == "norm":
            self.plot_widget.setLabel("left", "幅度", units="%")
        else:
            self.plot_widget.setLabel("left", "幅度")

        self.plot_widget.setLogMode(x=False, y=False)

        # 更新频率范围（触发 Y 自动跟随）
        self._update_freq_range()

        # 更新标记与表格
        self._refresh_marks()
        self._update_chord_label()
        self._update_hold_curve()

        # 重置游标位置
        self._reset_cursor()

    def _display_bounds(self) -> tuple[float, float]:
        """当前显示单位下的数据边界（有限值）。"""
        x = self._get_display_x()
        finite = np.isfinite(x)
        if not np.any(finite):
            return 0.0, 1.0
        xf = x[finite]
        return float(xf[0]), float(xf[-1])

    def _update_freq_range(self):
        """更新频率显示范围（内部始终以 Hz 计算，再转为当前单位）。"""
        if len(self._freqs_hz) == 0:
            return

        self._in_programmatic_range = True
        try:
            # 钢琴卷帘模式：固定 88 键范围
            if self._freq_unit == "piano":
                x_min, x_max = 20.5, 108.5
                self.plot_widget.setXRange(x_min, x_max, padding=0)
                self._set_piano_xticks()
                self._update_piano_keyboard(x_min, x_max)
                self._auto_y_range(x_min, x_max)
                return

            range_hz = self.FREQ_RANGES_HZ[self.cmb_range.currentIndex()][1]
            if range_hz is None:
                x_max_hz = min(self._freqs_hz[-1], self._sample_rate / 2)
            else:
                x_max_hz = min(range_hz, self._freqs_hz[-1])

            x_min_hz = 0.0

            if self._freq_unit == "hz":
                x_min, x_max = x_min_hz, x_max_hz
            elif self._freq_unit == "khz":
                x_min, x_max = x_min_hz / 1000, x_max_hz / 1000
            elif self._freq_unit == "midi":
                from acouscope.dsp.units import hz_to_midi
                x_max, x_min = hz_to_midi(x_max_hz), hz_to_midi(20.0)
            elif self._freq_unit == "cents":
                from acouscope.dsp.units import hz_to_cents
                x_max, x_min = hz_to_cents(x_max_hz), hz_to_cents(20.0)
            elif self._freq_unit == "mel":
                from acouscope.dsp.units import hz_to_mel
                x_max, x_min = hz_to_mel(x_max_hz), 0.0
            else:
                x_min, x_max = x_min_hz, x_max_hz

            self.plot_widget.setXRange(float(x_min), float(x_max), padding=0.02)
            self._auto_y_range(float(x_min), float(x_max))
        finally:
            self._in_programmatic_range = False

    def _set_piano_xticks(self):
        """钢琴卷帘模式下，X 轴刻度用 Hz 值标记（坐标仍是 MIDI）。"""
        from acouscope.dsp.units import midi_to_hz

        tick_midis = [24, 36, 48, 60, 72, 84, 96, 108]
        ticks = []
        for midi in tick_midis:
            freq = midi_to_hz(midi)
            label = f"{freq/1000:.1f} kHz" if freq >= 1000 else f"{freq:.0f} Hz"
            ticks.append((float(midi), label))

        self.plot_widget.getAxis("bottom").setTicks([ticks])

    # ============================================================
    # Y 轴自动跟随
    # ============================================================

    def _auto_y_range(self, x_min: float, x_max: float):
        """按可见 X 范围自动调整 Y 轴。"""
        if self._y_locked:
            return

        x = self._get_display_x()
        y = self._get_display_y()
        if len(x) < 2:
            return

        finite = np.isfinite(x) & np.isfinite(y)
        x, y = x[finite], y[finite]
        if len(x) < 2:
            return

        visible = (x >= x_min) & (x <= x_max)
        if np.any(visible):
            vis_y = y[visible]
            y_max = float(np.max(vis_y))
        else:
            y_max = float(np.max(y)) if len(y) else 1.0

        if self._mag_unit in ("db", "dbfs", "dba"):
            y_min = y_max - 80
            y_max = y_max + 3
        elif self._mag_unit == "norm":
            y_min, y_max = 0, 105
        else:
            y_min = 0
            y_max = y_max * 1.18 if y_max > 0 else 1.0

        self.plot_widget.setYRange(y_min, y_max, padding=0)

    def _on_x_range_changed(self, vb, x_range):
        """X 范围变化回调：Y 自动跟随 + 键盘同步。"""
        if len(self._freqs_hz) == 0:
            return
        x_min, x_max = float(x_range[0]), float(x_range[1])
        self._sync_piano_keyboard()
        if not self._in_programmatic_range:
            self._auto_y_range(x_min, x_max)

    def _on_y_lock_toggled(self, checked: bool):
        """Y 锁定按钮切换。"""
        self._y_locked = checked
        self.btn_y_lock.setText(
            tr("spectrum.y_locked") if checked else tr("spectrum.y_auto")
        )
        if not checked:
            # 解锁：立即按当前可见范围自适应
            x_min, x_max = self.plot_widget.plotItem.vb.viewRange()[0]
            self._auto_y_range(float(x_min), float(x_max))

    def _set_y_locked(self, locked: bool):
        """程序化设置 Y 锁定状态。"""
        if self.btn_y_lock.isChecked() != locked:
            self.btn_y_lock.blockSignals(True)
            self.btn_y_lock.setChecked(locked)
            self.btn_y_lock.blockSignals(False)
        self._y_locked = locked
        self.btn_y_lock.setText(
            tr("spectrum.y_locked") if locked else tr("spectrum.y_auto")
        )

    def _reset_cursor(self):
        """重置游标到合理位置。"""
        x = self._get_display_x()
        y = self._get_display_y()
        if len(x) < 2:
            return

        if self._manual_peaks:
            peak_hz = self._manual_peaks[0]["freq"]
            self.v_line.setPos(self._hz_to_display_x(peak_hz))
        else:
            finite = np.isfinite(x)
            if np.any(finite):
                xf = x[finite]
                self.v_line.setPos(float(xf[len(xf) // 10]))
                # 该点曲线值（而非 max*0.5），同步 h_line（D8）
                x_val = self.v_line.value()
                freq_hz = self._display_x_to_hz(x_val)
                mag_lin = float(np.interp(freq_hz, self._freqs_hz, self._magnitude_linear))
                y_val = self._linear_to_display_y(mag_lin, freq_hz)
                self.h_line.blockSignals(True)
                self.h_line.setPos(y_val)
                self.h_line.blockSignals(False)

    # ============================================================
    # 坐标换算（Hz <-> 当前显示单位）
    # ============================================================

    def _hz_to_display_x(self, freq_hz: float) -> float:
        """Hz 转当前 X 显示单位。"""
        if self._freq_unit == "khz":
            return freq_hz / 1000
        if self._freq_unit in ("midi", "piano"):
            from acouscope.dsp.units import hz_to_midi
            return float(hz_to_midi(freq_hz))
        if self._freq_unit == "cents":
            from acouscope.dsp.units import hz_to_cents
            return float(hz_to_cents(freq_hz))
        if self._freq_unit == "mel":
            from acouscope.dsp.units import hz_to_mel
            return float(hz_to_mel(freq_hz))
        return freq_hz

    def _display_x_to_hz(self, x_display: float) -> float:
        """当前 X 显示单位转 Hz。"""
        if self._freq_unit == "khz":
            return x_display * 1000
        if self._freq_unit in ("midi", "piano"):
            from acouscope.dsp.units import midi_to_hz
            return float(midi_to_hz(x_display))
        if self._freq_unit == "cents":
            from acouscope.dsp.units import cents_to_hz
            return float(cents_to_hz(x_display))
        if self._freq_unit == "mel":
            from acouscope.dsp.units import mel_to_hz
            return float(mel_to_hz(x_display))
        return x_display

    def _linear_to_display_y(self, mag_linear: float, freq_hz: float) -> float:
        """线性幅度转当前 Y 显示单位。"""
        if self._mag_unit == "db":
            return 20.0 * np.log10(max(mag_linear, 1e-12))
        if self._mag_unit == "dbfs":
            from acouscope.dsp.units import linear_to_dbfs
            return float(linear_to_dbfs(mag_linear))
        if self._mag_unit == "dba":
            from acouscope.dsp.units import a_weighting
            return 20.0 * np.log10(max(mag_linear, 1e-12)) + float(a_weighting(freq_hz))
        if self._mag_unit == "norm":
            max_mag = float(np.max(self._magnitude_linear)) if len(self._magnitude_linear) else 1.0
            return mag_linear / max_mag * 100.0 if max_mag > 0 else 0.0
        return mag_linear

    # ============================================================
    # 缩放控制
    # ============================================================

    def _on_wheel(self, delta: int, x_view: float, y_view: float, shift: bool):
        """滚轮：X 轴锚定缩放；Shift 时 Y 轴缩放。"""
        if len(self._freqs_hz) == 0:
            return

        factor = 1.25 if delta > 0 else 1 / 1.25
        vb = self.plot_widget.plotItem.vb

        if shift:
            # Y 轴缩放（锚定鼠标）
            self._set_y_locked(True)
            y0, y1 = vb.viewRange()[1]
            new_y0 = y_view - (y_view - y0) / factor
            new_y1 = y_view + (y1 - y_view) / factor
            vb.setYRange(float(new_y0), float(new_y1), padding=0)
        else:
            # X 轴缩放（锚定鼠标）
            x0, x1 = vb.viewRange()[0]
            new_x0 = x_view - (x_view - x0) / factor
            new_x1 = x_view + (x1 - x_view) / factor
            self._set_x_range_clamped(float(new_x0), float(new_x1))

    def _set_x_range_clamped(self, x0: float, x1: float):
        """设置 X 范围并钳制在数据边界内，限制缩放深度。"""
        data_min, data_max = self._display_bounds()
        full_span = data_max - data_min
        if full_span <= 0:
            return

        span = x1 - x0
        # 最小跨度：4 个频率分辨率（防过度放大）
        x = self._get_display_x()
        finite = np.isfinite(x)
        min_span = full_span * 1e-5
        if np.sum(finite) > 1:
            xf = np.sort(x[finite])
            min_span = max(min_span, 4 * float(np.min(np.diff(xf))))

        if span < min_span:
            center = (x0 + x1) / 2
            x0, x1 = center - min_span / 2, center + min_span / 2
        elif span > full_span:
            x0, x1 = data_min, data_max
            self.plot_widget.plotItem.vb.setXRange(x0, x1, padding=0)
            return

        # 平移回数据边界
        if x0 < data_min:
            x1 += data_min - x0
            x0 = data_min
        if x1 > data_max:
            x0 -= x1 - data_max
            if x0 < data_min:
                x0 = data_min
            x1 = data_max

        self.plot_widget.plotItem.vb.setXRange(float(x0), float(x1), padding=0)

    def _zoom_center(self, factor: float):
        """以视图中心为基准缩放 X 轴（按钮/快捷键用）。"""
        if len(self._freqs_hz) == 0:
            return
        vb = self.plot_widget.plotItem.vb
        x0, x1 = vb.viewRange()[0]
        center = (x0 + x1) / 2
        span = (x1 - x0) / factor
        self._set_x_range_clamped(center - span / 2, center + span / 2)

    def _zoom_fit(self):
        """重置视图。"""
        if len(self._magnitude_linear) < 1:
            return
        self._set_y_locked(False)
        self._update_freq_range()

    def keyPressEvent(self, event):
        """键盘快捷键。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                self._zoom_center(1.3)
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Minus:
                self._zoom_center(1 / 1.3)
                event.accept()
                return
            elif event.key() == Qt.Key.Key_0:
                self._zoom_fit()
                event.accept()
                return
        super().keyPressEvent(event)

    # ============================================================
    # 峰值检测
    # ============================================================

    def _detect_peaks(self, max_peaks: int = 8, mag_threshold: float = 0.001) -> list[dict]:
        """检测乐音峰值（始终基于 Hz 和线性幅度）。"""
        if len(self._magnitude_linear) < 3:
            return []

        range_hz = self.FREQ_RANGES_HZ[self.cmb_range.currentIndex()][1]
        max_freq = range_hz if range_hz else self._sample_rate / 2

        try:
            from acouscope.analysis import SpectralAnalyzer
            analyzer = SpectralAnalyzer(self._sample_rate)
            return analyzer.detect_pitch_peaks(
                self._magnitude_linear,
                self._freqs_hz,
                min_freq=20.0,
                max_freq=min(max_freq, self._sample_rate / 2),
                max_peaks=max_peaks,
                mag_threshold=mag_threshold,
                min_peak_spacing=3,
            )
        except Exception:
            return []

    def _find_nearest_peak(self, click_freq_hz: float) -> Optional[dict]:
        """找点击位置 ±半音内最强的局部峰值。"""
        if len(self._magnitude_linear) < 3:
            return None

        freq_res = self._freqs_hz[1] - self._freqs_hz[0]
        if freq_res <= 0:
            return None

        half_semitone_low = click_freq_hz / (2 ** (1 / 24))
        half_semitone_high = click_freq_hz * (2 ** (1 / 24))

        idx_low = max(1, int(half_semitone_low / freq_res))
        idx_high = min(len(self._magnitude_linear) - 2, int(half_semitone_high / freq_res))

        if idx_low >= idx_high:
            return None

        # 范围内找局部最大值
        segment = self._magnitude_linear[idx_low - 1 : idx_high + 2]
        if len(segment) < 3:
            return None
        inner = segment[1:-1]
        local_max_mask = (inner > segment[:-2]) & (inner >= segment[2:])
        if not np.any(local_max_mask):
            return None

        candidates = np.where(local_max_mask)[0] + idx_low
        max_idx = int(candidates[np.argmax(self._magnitude_linear[candidates])])
        max_val = float(self._magnitude_linear[max_idx])

        if max_val <= 0:
            return None

        # 阈值：大于全谱最大幅度的 1%
        spect_max = float(np.max(self._magnitude_linear))
        if max_val < spect_max * 0.01:
            return None

        # 抛物线插值精确定位
        a = self._magnitude_linear[max_idx - 1]
        b = self._magnitude_linear[max_idx]
        c = self._magnitude_linear[max_idx + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-20:
            delta = (a - c) / (2 * denom)
            true_idx = max_idx + delta
            peak_freq = true_idx * freq_res
            peak_mag = b - 0.25 * (a - c) * delta
        else:
            peak_freq = self._freqs_hz[max_idx]
            peak_mag = max_val

        from acouscope.dsp.units import hz_to_midi, midi_note_name
        midi_float = hz_to_midi(peak_freq)
        midi = int(round(midi_float))
        cents = 100 * (midi_float - midi)

        return {
            "freq": float(peak_freq),
            "magnitude": float(peak_mag),
            "note": midi_note_name(midi),
            "cents": float(cents),
            "midi": midi,
        }

    def _find_marked_peak_near(self, freq_hz: float) -> Optional[int]:
        """已标记峰值中最近的一个（半音内）。"""
        if not self._manual_peaks:
            return None

        from acouscope.dsp.units import hz_to_midi
        nearest_idx = None
        nearest_diff = float("inf")
        for i, peak in enumerate(self._manual_peaks):
            cents_diff = abs(hz_to_midi(peak["freq"]) - hz_to_midi(freq_hz)) * 100
            if cents_diff < 50 and cents_diff < nearest_diff:
                nearest_diff = cents_diff
                nearest_idx = i
        return nearest_idx

    # ============================================================
    # 标记交互（单击切换 / 右键菜单）
    # ============================================================

    def _on_plot_clicked(self, button: int, x_view: float, y_view: float):
        """频谱图单击（释放时位移小于阈值，与拖动区分）。"""
        if len(self._magnitude_linear) < 3:
            return

        click_freq = self._display_x_to_hz(x_view)
        if click_freq < self._freqs_hz[0] or click_freq > self._freqs_hz[-1]:
            return

        if button == 1:
            # 左键：切换标记（有则取消，无则添加）
            peak = self._find_nearest_peak(click_freq)
            if peak:
                existing = self._find_marked_peak_near(peak["freq"])
                if existing is not None:
                    self._remove_mark(existing)
                else:
                    self._add_peak_mark(peak)

        elif button == 2:
            # 右键：管理菜单
            self._show_context_menu(click_freq)

    def _show_context_menu(self, click_freq: float):
        """右键标记管理菜单。"""
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QMenu

        marked_idx = self._find_marked_peak_near(click_freq)
        nearby_peak = self._find_nearest_peak(click_freq)

        menu = QMenu(self)

        if marked_idx is not None:
            peak = self._manual_peaks[marked_idx]
            act = menu.addAction(f"取消标记 {peak['note']}")
            act.triggered.connect(lambda: self._remove_mark(marked_idx))
        elif nearby_peak is not None:
            act = menu.addAction(f"标记音高 {nearby_peak['note']}")
            act.triggered.connect(lambda: self._add_peak_mark(nearby_peak))

        if self._manual_peaks:
            menu.addSeparator()
            act = menu.addAction("复制标记数据 (TSV)")
            act.triggered.connect(self._copy_marks_to_clipboard)
            act = menu.addAction("清除全部标记")
            act.triggered.connect(self._clear_all_marks)

        if menu.actions():
            menu.exec(QCursor.pos())

    def _add_peak_mark(self, peak: dict):
        """添加标记（已存在同位置标记则忽略）。"""
        existing = self._find_marked_peak_near(peak["freq"])
        if existing is None:
            self._manual_peaks.append(peak)
            self._manual_peaks.sort(key=lambda x: x["freq"])
            self._after_marks_changed()

    def restore_marks(self, marks: list) -> int:
        """恢复保存的谐波标记。

        对每个保存的频率在当前频谱中重新定位峰值
        （幅度与音名按当前数据重算），保证标记准确吸附。

        Args:
            marks: 标记列表 [{freq, note, cents, midi}, ...]

        Returns:
            成功恢复的标记数
        """
        restored = 0
        for mark in marks:
            try:
                freq = float(mark["freq"])
            except (KeyError, TypeError, ValueError):
                continue
            if freq <= 0:
                continue

            peak = self._find_nearest_peak(freq)
            if peak is None:
                magnitude = (
                    float(np.interp(freq, self._freqs_hz, self._magnitude_linear))
                    if len(self._freqs_hz) > 1
                    else 0.0
                )
                peak = {
                    "freq": freq,
                    "magnitude": magnitude,
                    "note": str(mark.get("note", "")),
                    "cents": float(mark.get("cents", 0.0)),
                    "midi": float(mark.get("midi", 0.0)),
                }
            self._add_peak_mark(peak)
            restored += 1
        return restored

    def _remove_mark(self, idx: int):
        """移除指定索引的标记。"""
        if 0 <= idx < len(self._manual_peaks):
            del self._manual_peaks[idx]
            self._after_marks_changed()

    def _clear_all_marks(self):
        """清除所有标记。"""
        self._manual_peaks = []
        self._after_marks_changed()

    def _auto_detect_peaks(self):
        """自动检测分音并标记（前 6 个，阈值 1%）。"""
        peaks = self._detect_peaks(max_peaks=6, mag_threshold=0.01)
        for peak in peaks:
            if self._find_marked_peak_near(peak["freq"]) is None:
                self._manual_peaks.append(peak)
        self._manual_peaks.sort(key=lambda x: x["freq"])
        self._after_marks_changed()

    def _after_marks_changed(self):
        """标记变更后的统一刷新。"""
        self._refresh_marks()
        self._update_marks_table()
        self._update_chord_label()

    def _copy_marks_to_clipboard(self):
        """复制标记数值表到剪贴板（TSV，可粘贴到 Excel）。"""
        if not self._manual_peaks:
            return
        from PyQt6.QtWidgets import QApplication

        lines = ["#\t频率(Hz)\t音名\t音分偏差\t幅度(dB)\tΔ音分\tn×基频"]
        rows = self._build_table_rows()
        for row in rows:
            lines.append("\t".join(str(v) for v in row))
        QApplication.clipboard().setText("\n".join(lines))

    def _on_mark_row_double_clicked(self, item):
        """双击表格行：视图跳转到该标记（居中放大）。"""
        row = item.row()
        if 0 <= row < len(self._manual_peaks):
            freq = self._manual_peaks[row]["freq"]
            x = self._hz_to_display_x(freq)
            data_min, data_max = self._display_bounds()
            span = max((data_max - data_min) * 0.05, 1e-6)
            self._set_x_range_clamped(x - span / 2, x + span / 2)

    # ============================================================
    # 标记渲染（竖线 + 文本标签）与数值表
    # ============================================================

    def _refresh_marks(self):
        """重建标记图形项（竖线 + 音名标签 + 峰顶三角）。"""
        # 清除旧图形项
        for item in self._mark_items:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self._mark_items = []

        if not self._manual_peaks:
            self._peak_marker.setData([], [])
            self._update_marks_table()
            return

        font = QFont()
        font.setPointSize(9)
        font.setBold(True)

        peak_x = []
        peak_y = []
        for peak in self._manual_peaks:
            px = self._hz_to_display_x(peak["freq"])
            py = self._linear_to_display_y(peak["magnitude"], peak["freq"])
            peak_x.append(px)
            peak_y.append(py)

            # 竖线
            line = pg.InfiniteLine(
                pos=px,
                angle=90,
                movable=False,
                pen=pg.mkPen(color=theme.data_ink("marker"), width=2.2,
                             style=Qt.PenStyle.DashLine),
            )
            self.plot_widget.addItem(line)
            self._mark_items.append(line)

            # 音名标签（含音分）
            label = f'{peak["note"]}'
            if abs(peak.get("cents", 0)) >= 1:
                label += f' {peak["cents"]:+.0f}¢'
            text = pg.TextItem(text=label, color=theme.data_ink("marker"),
                               anchor=(0.5, 1.5))
            text.setFont(font)
            text.setPos(px, py)
            self.plot_widget.addItem(text)
            self._mark_items.append(text)

        self._peak_marker.setData(peak_x, peak_y)
        self._update_marks_table()

    def _build_table_rows(self) -> list[list]:
        """构造标记数值表行数据。"""
        rows = []
        if not self._manual_peaks:
            return rows

        max_mag = max(p["magnitude"] for p in self._manual_peaks) or 1.0
        base_freq = self._manual_peaks[0]["freq"]

        prev_hz = None
        for i, peak in enumerate(self._manual_peaks, start=1):
            freq = peak["freq"]
            mag_db = 20 * np.log10(max(peak["magnitude"], 1e-12) / max_mag)

            if prev_hz is not None and prev_hz > 0 and freq > 0:
                delta_cents = 1200 * np.log2(freq / prev_hz)
                delta_str = f"{delta_cents:+.0f}"
            else:
                delta_str = "—"

            ratio = freq / base_freq if base_freq > 0 else 0
            rows.append([
                i,
                f"{freq:.2f}",
                peak["note"],
                f'{peak["cents"]:+.0f}',
                f"{mag_db:.1f}",
                delta_str,
                f"{ratio:.2f}",
            ])
            prev_hz = freq
        return rows

    def _fit_marks_table_height(self):
        """表格高度自适应内容：标记行全部可见、不出现滚动条；
        超过 8 行才封顶（防止标记过多时挤占绘图区）。"""
        table = self.marks_table
        header_h = table.horizontalHeader().height()
        rows = table.rowCount()
        row_h = table.rowHeight(0) if rows > 0 else table.verticalHeader().defaultSectionSize()
        frame = 2 * table.frameWidth()
        visible_rows = max(1, min(rows, 8))
        table.setFixedHeight(int(header_h + row_h * visible_rows + frame))

    def _update_marks_table(self):
        """更新标记数值表。"""
        rows = self._build_table_rows()
        self.marks_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if c == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    # F4：幅度单元格与表头共用同一口径说明（相对最强峰归一化 dBr）
                    item.setToolTip(_MARKS_MAG_TOOLTIP)
                self.marks_table.setItem(r, c, item)
        self.lbl_marks_title.setText(
            tr("spectrum.harmonic_marks").format(n=len(self._manual_peaks))
        )
        self._fit_marks_table_height()

    def _update_chord_label(self):
        """更新和弦/单音标签（基于标记）。"""
        peaks = self._manual_peaks
        if not peaks:
            self.lbl_chord.setText(tr("spectrum.single_tone_none"))
            return

        try:
            from acouscope.analysis import SpectralAnalyzer
            analyzer = SpectralAnalyzer(self._sample_rate)
            chord = analyzer.detect_chord(peaks)
            if chord["quality"] == "单音":
                self.lbl_chord.setText(
                    tr("spectrum.single_tone").format(name=chord["name"])
                )
            elif chord["name"] != "--" and chord["confidence"] > 0.35:
                conf_pct = int(chord["confidence"] * 100)
                self.lbl_chord.setText(
                    tr("spectrum.chord").format(name=chord["name"], conf=conf_pct)
                )
            else:
                n_notes = len(set(p["note"][:-1] for p in peaks))
                if n_notes == 1:
                    self.lbl_chord.setText(
                        tr("spectrum.single_tone").format(name=peaks[0]["note"])
                    )
                else:
                    self.lbl_chord.setText(tr("spectrum.notes_count").format(n=n_notes))
        except Exception:
            self.lbl_chord.setText(
                tr("spectrum.marks_notes").format(n=len(peaks))
            )

    # ============================================================
    # 峰值保持
    # ============================================================

    def _toggle_peak_hold(self, checked: bool):
        """切换峰值保持。"""
        if checked and len(self._magnitude_linear) > 0:
            self._peak_hold_data = self._magnitude_linear.copy()
        self.curve_hold.setVisible(checked)
        self._update_hold_curve()

    def _update_hold_curve(self):
        """更新峰值保持曲线。"""
        if not self.btn_hold.isChecked() or len(self._peak_hold_data) == 0:
            return

        if len(self._magnitude_linear) > 0 and len(self._peak_hold_data) == len(self._magnitude_linear):
            self._peak_hold_data = np.maximum(self._peak_hold_data, self._magnitude_linear)

        x = self._get_display_x()
        y = self._get_hold_y()
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.all(finite):
            x, y = x[finite], y[finite]
        self.curve_hold.setData(x, y)

    # ============================================================
    # 窗函数与游标
    # ============================================================

    def _on_window_changed(self, index: int):
        """窗函数变化。"""
        self._window_type = self.WINDOW_TYPES[index][1]
        if self.window_changed_callback and self._signal_data is not None:
            self.window_changed_callback(self._window_type)

    def _on_fft_size_changed(self, index: int):
        """FFT 大小变化。重新计算频谱。"""
        if self._signal_data is None:
            return
        n_fft = self.FFT_SIZES[index][1]
        self._recompute_spectrum(n_fft)

    def _recompute_spectrum(self, n_fft: int):
        """用指定 FFT 大小重新计算频谱。"""
        if self._signal_data is None:
            return
        from acouscope.dsp import FFTEngine
        from acouscope.dsp.windows import get_window

        signal = self._signal_data
        sr = self._sample_rate

        # 取中间 n_fft 个采样点（Audacity 风格）
        mid = len(signal) // 2
        half = n_fft // 2
        start = max(0, mid - half)
        end = min(len(signal), start + n_fft)
        segment = signal[start:end].astype(np.float64)

        if len(segment) < n_fft:
            segment = np.pad(segment, (0, n_fft - len(segment)))

        # 加窗
        window = get_window(self._window_type, n_fft)
        segment = segment * window

        # FFT
        engine = FFTEngine(size=n_fft)
        spec = engine.magnitude(segment)
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

        self._freqs_hz = freqs
        self._magnitude_linear = spec
        self._peak_hold_data = spec.copy()

        self._update_display()
        self._update_info_bar()

    def _on_find_peaks(self):
        """自动检测频谱峰值（Audacity Plot Spectrum 风格）。"""
        if len(self._freqs_hz) < 3:
            return

        freqs = self._freqs_hz
        mags = self._magnitude_linear

        # 转为 dB 便于峰值检测
        mag_db = 20 * np.log10(np.maximum(mags, 1e-12))

        # 简单峰值检测：局部极大值
        peaks = []
        min_peak_db = np.max(mag_db) - 40  # 40 dB 以下的峰忽略
        for i in range(1, len(mag_db) - 1):
            if mag_db[i] > mag_db[i - 1] and mag_db[i] > mag_db[i + 1]:
                if mag_db[i] >= min_peak_db:
                    peaks.append((freqs[i], mag_db[i], i))

        # 按幅度排序，取前 20 个
        peaks.sort(key=lambda x: x[1], reverse=True)
        peaks = peaks[:20]

        if not peaks:
            return

        # 非模态反馈：峰值摘要走 toast（UI 宪法条 3：对话框最小化，本处禁建模态）。
        # 标记能力不因去模态而丢失：原「标记选中峰值」的同功能入口仍在谱图右键菜单
        # （「标记音高 X」）与自动标记路径，本处只做检测结果提示。
        from acouscope.dsp.units import hz_to_midi, midi_note_name

        top_n = 5
        items = []
        for freq, _db, _idx in peaks[:top_n]:
            try:
                note = midi_note_name(int(round(hz_to_midi(float(freq)))))
            except Exception:
                note = ""
            items.append(f"{freq:.1f} Hz" + (f"（{note}）" if note else ""))
        summary = "、".join(items) + (" …" if len(peaks) > top_n else "")
        show_toast(
            self,
            f"检测到 {len(peaks)} 个峰值（按幅度降序）：{summary}。"
            "在谱图上右键可标记 / 取消标记音高。",
            level="info",
        )

        # CB-002 F-3：缓存检测结果供内嵌标记面板使用
        last = []
        for freq, _db, idx in peaks:
            try:
                midi_f = hz_to_midi(float(freq))
                midi = int(round(midi_f))
                note = midi_note_name(midi)
                cents = 100 * (midi_f - midi)
            except Exception:
                midi = 0
                note = ""
                cents = 0.0
            last.append({
                "freq": float(freq),
                "magnitude": float(self._magnitude_linear[idx]),
                "note": note,
                "cents": float(cents),
                "midi": midi,
            })
        self._last_peaks = last
        if getattr(self, "_peaks_panel", None) is not None \
                and self._peaks_panel.isVisible():
            self._refresh_peaks_panel()

    # ------------------------------------------------------------
    # CB-002 F-3：峰值标记内嵌面板
    # ------------------------------------------------------------

    def _toggle_peaks_panel(self, checked: bool):
        """工具栏「标记面板」勾选 → 内嵌展开/收起（非模态）。"""
        panel = getattr(self, "_peaks_panel", None)
        if panel is not None:
            panel.setVisible(checked)
            if checked:
                self._refresh_peaks_panel()

    def _refresh_peaks_panel(self):
        """用最近一次检测结果刷新内嵌面板（含已标记态）。"""
        panel = getattr(self, "_peaks_panel", None)
        if panel is None or not self._last_peaks:
            return
        panel.set_peaks(self._last_peaks)
        panel.set_mark_flags([
            self._find_marked_peak_near(p["freq"]) is not None
            for p in self._last_peaks
        ])

    def _on_panel_mark_peaks(self, peaks):
        """面板「标记选中」：复用 _add_peak_mark，零重复实现。"""
        added = 0
        for p in peaks:
            if self._find_marked_peak_near(p["freq"]) is None:
                self._add_peak_mark(p)
                added += 1
        show_toast(
            self,
            f"已标记 {added} 个峰值。" if added else "所选峰值均已标记。",
            level="success" if added else "info",
        )
        self._refresh_peaks_panel()

    def _on_panel_unmark_peaks(self, freqs):
        """面板「取消标记」：复用 _remove_mark，零重复实现。"""
        removed = 0
        for freq in freqs:
            idx = self._find_marked_peak_near(float(freq))
            if idx is not None:
                self._remove_mark(idx)
                removed += 1
        show_toast(
            self,
            f"已取消标记 {removed} 个峰值。" if removed else "所选峰值均未标记。",
            level="info",
        )
        self._refresh_peaks_panel()

    def _on_cursor_moved(self):
        """游标移动，更新信息栏。幅度取曲线在游标频率处的值（D8）。"""
        if len(self._freqs_hz) == 0:
            return

        x_val = self.v_line.value()
        freq_hz = self._display_x_to_hz(x_val)

        # 幅度取曲线在游标频率处的线性值，再换算为当前显示单位
        mag_lin = float(np.interp(freq_hz, self._freqs_hz, self._magnitude_linear))
        y_val = self._linear_to_display_y(mag_lin, freq_hz)

        # 水平准星由程序同步到曲线值（读数指示线），blockSignals 防递归
        self.h_line.blockSignals(True)
        self.h_line.setPos(y_val)
        self.h_line.blockSignals(False)

        # 频率显示（用当前单位）
        if self._freq_unit in ("hz", "khz"):
            self.lbl_freq.setText(
                tr("spectrum.freq_unit").format(
                    value=f"{x_val:.2f}", unit=self._x_unit_label()
                )
            )
        elif self._freq_unit == "midi":
            self.lbl_freq.setText(f"MIDI: {x_val:.2f}")
        elif self._freq_unit == "piano":
            self.lbl_freq.setText(
                tr("spectrum.freq_hz").format(value=f"{freq_hz:.2f}")
            )
        elif self._freq_unit == "cents":
            self.lbl_freq.setText(
                tr("spectrum.cents").format(value=f"{x_val:.0f}")
            )
        elif self._freq_unit == "mel":
            self.lbl_freq.setText(f"Mel: {x_val:.1f} mel")
        else:
            self.lbl_freq.setText(tr("spectrum.freq_value").format(value=f"{x_val:.2f}"))

        # 幅度显示
        y_label = self._y_unit_label()
        if self._mag_unit in ("db", "dbfs", "dba"):
            self.lbl_mag.setText(
                tr("spectrum.amp_unit").format(value=f"{y_val:.1f}", unit=y_label)
            )
        elif self._mag_unit == "norm":
            self.lbl_mag.setText(tr("spectrum.amp_pct").format(value=f"{y_val:.1f}"))
        else:
            self.lbl_mag.setText(tr("spectrum.amp_value").format(value=f"{y_val:.4f}"))

        # 音符显示（基于 Hz）
        note_name = hz_to_note_name(freq_hz)
        if note_name != "--":
            from acouscope.dsp.units import hz_to_midi, midi_to_hz
            # 音名与音分同基准：均走当前 A4（hz_to_midi/midi_to_hz 默认口径）
            midi_round = round(float(hz_to_midi(freq_hz)))
            ref_freq = float(midi_to_hz(midi_round))
            cents = 1200 * np.log2(freq_hz / ref_freq) if freq_hz > 0 else 0
            self.lbl_note.setText(
                tr("spectrum.note_cents").format(
                    name=note_name, cents=f"{cents:+.0f}"
                )
            )
        else:
            self.lbl_note.setText(tr("spectrum.note_none"))

    # ============================================================
    # 钢琴键盘
    # ============================================================

    def _sync_piano_keyboard(self):
        """按当前视图 X 范围刷新钢琴键盘（仅钢琴卷帘模式下有效）。"""
        if not self._keyboard_visible:
            return
        x_min, x_max = self.plot_widget.plotItem.vb.viewRange()[0]
        self._update_piano_keyboard(x_min, x_max)

    def _apply_ink(self):
        """数据墨色（T-1038 M1/M6）：主曲线/峰值保持/峰标记/交叉游标随主题取色。"""
        self.curve.setPen(pg.mkPen(color=theme.data_ink("trace"), width=2.7))
        self.curve_hold.setPen(pg.mkPen(
            color=theme.data_ink("trace_alt"), width=0.8,
            style=Qt.PenStyle.DashLine))
        self._peak_marker.setSymbolBrush(pg.mkBrush(theme.data_ink("marker")))
        for line in (self.v_line, self.h_line):
            line.setPen(pg.mkPen(color=theme.data_ink("cursor"), width=2.7,
                                 style=Qt.PenStyle.DashLine))
        for item in self._mark_items:
            if isinstance(item, pg.InfiniteLine):
                item.setPen(pg.mkPen(color=theme.data_ink("marker"), width=2.2,
                                     style=Qt.PenStyle.DashLine))
            elif isinstance(item, pg.TextItem):
                item.setColor(theme.data_ink("marker"))

    def _on_canvas_theme(self):
        """主题切换：重设主频谱与钢琴键盘画布（pyqtgraph 不走 QSS）。

        键盘键面随主题令牌重绘（键色取自 colors()，不在源码散落 hex）；
        曲线/游标/标记等数据墨色一并随骨架重取（T-1038 M6）。
        """
        _apply_canvas_theme(self.plot_widget)
        _apply_canvas_theme(self.keyboard_widget, "bg2")
        self._apply_ink()
        self.lbl_chord.setStyleSheet(
            f"color: {theme.colors()['accent']}; font-weight: bold;"
            f" font-size: {theme.TOKENS['typography']['body']}px;"
            f" padding: {theme.TOKENS['spacing']['xxs']}px"
            f" {theme.TOKENS['spacing']['sm']}px;"
            f" background: {theme.colors()['bg2']};"
            f" border: {theme.TOKENS['elevation']['border']}px solid"
            f" {theme.colors()['border']};"
            f" border-radius: {theme.TOKENS['radius']['sm']}px;"
        )
        for lbl in (self.lbl_freq, self.lbl_mag, self.lbl_note):
            lbl.setStyleSheet(
                f"color: {theme.colors()['text_sub']};"
                f" font-size: {theme.TOKENS['typography']['body_sm']}px;")
        self.lbl_resolution.setStyleSheet(
            f"color: {theme.colors()['text_faint']};"
            f" font-size: {theme.TOKENS['typography']['caption']}px;")
        self.plot_widget.update()
        if self._keyboard_visible:
            x_min, x_max = self.plot_widget.plotItem.vb.viewRange()[0]
            self._update_piano_keyboard(x_min, x_max)

    def _update_piano_keyboard(self, min_midi: float, max_midi: float):
        """更新钢琴键盘显示。"""
        for item in self._keyboard_items:
            self.keyboard_widget.removeItem(item)
        self._keyboard_items = []

        if not self._keyboard_visible:
            return

        # ★ T-1042c 缺陷 C：键床须铺满键盘**实际可见范围**——横排键盘经 X 联动后自身
        # 范围可比宿主略宽（实测 12.2–108.5 vs 宿主 20.5–108.5），只按宿主范围布键
        # 会在左端露出键带底（中线背景段 40 像素 → 「键床断裂」复发）。
        kx0, kx1 = self.keyboard_widget.plotItem.vb.viewRange()[0]
        midi_start = max(int(np.floor(min(min_midi, kx0))), 0)
        midi_end = min(int(np.ceil(max(max_midi, kx1))), 127)
        if midi_start >= midi_end:
            return

        from acouscope.dsp.units import midi_is_white_key, midi_is_black_key
        from acouscope.ui.widgets.freq_axis import (
            PianoKeyboardStrip, make_seam_pen, rounded_end_rect,
        )

        # T-1042b：横排键面与竖排**同一常量/同一取值来源**（竖横不得割裂）：
        # 白键高 = 竖排 WHITE_W（4.0）；黑键长比 0.46、半音方向 0.55、圆角 r 全部同源。
        WHITE_HEIGHT = PianoKeyboardStrip.WHITE_W            # 白键纵向高
        BLACK_HEIGHT = PianoKeyboardStrip.BLACK_W            # 黑键长（纵向）同源 = 4.0×0.46
        BLACK_WIDTH = PianoKeyboardStrip.BLACK_H             # 黑键半音方向同源 = 0.55
        BLACK_TOP = WHITE_HEIGHT - BLACK_HEIGHT              # 贴上（黑键贴顶缘）
        WHITE_KEY_R = PianoKeyboardStrip.WHITE_KEY_R
        BLACK_KEY_R = PianoKeyboardStrip.BLACK_KEY_R

        # 键面令牌（T-1042b）：白键/黑键/白键缝一律取 TOKENS["keys"]（单套物理色，明暗同款）；
        # 键带底/gutter 随骨架 bg2（仅作底板）。源码不散落 hex、不再用任何语义反馈色（去金色）。
        faces = theme.key_faces()
        strip_brush = pg.mkBrush(theme.colors()["bg2"])
        key_white = pg.mkBrush(faces["white"])
        # 白键间分隔：keys.white_seam（比白键暗），禁 border（壳色会亮于键面 → 「格子纸」）
        # T-1079 ①：cosmetic 设备像素宽，与竖排同源（make_seam_pen），任意缩放缝可见
        seam_pen = make_seam_pen(pg.mkPen(faces["white_seam"], width=0.15))
        key_black = pg.mkBrush(faces["black"])
        no_pen = pg.mkPen(None)

        # 键带底：铺满本段键盘（gutter，随骨架 bg2），先于白键层。
        if midi_end >= midi_start:
            strip = pg.QtWidgets.QGraphicsRectItem(
                midi_start - 0.5, 0, (midi_end - midi_start) + 1.0, WHITE_HEIGHT
            )
            strip.setBrush(strip_brush)
            strip.setPen(no_pen)
            strip.setZValue(-20)
            self.keyboard_widget.addItem(strip)
            self._keyboard_items.append(strip)

            # ★ 键床底：keys.white 连续铺满整条（T-1042c §3-ter-1，横排=满高）——
            # 白键不再画成互不接触的块，黑键行剩余区域也是白键面（观感=键盘，非「豆腐块」）。
            bed = pg.QtWidgets.QGraphicsRectItem(
                midi_start - 0.5, 0, (midi_end - midi_start) + 1.0, WHITE_HEIGHT
            )
            bed.setBrush(key_white)
            bed.setPen(no_pen)
            bed.setZValue(-10)
            self.keyboard_widget.addItem(bed)
            self._keyboard_items.append(bed)

        # 白键（全高、底缘小圆角——远离黑键的自由端，同竖排「右端圆角」语义）
        for midi in range(midi_start, midi_end + 1):
            if midi_is_white_key(midi):
                path = rounded_end_rect(
                    midi - 0.5, 0, 1.0, WHITE_HEIGHT, WHITE_KEY_R, end="top",
                )
                item = pg.QtWidgets.QGraphicsPathItem(path)
                item.setBrush(key_white)
                item.setPen(seam_pen)
                self.keyboard_widget.addItem(item)
                self._keyboard_items.append(item)

        # 黑键（贴上、右缘贴键缝、顶缘圆角（自由端）、顶层、无描边）
        for midi in range(midi_start, midi_end + 1):
            if midi_is_black_key(midi):
                path = rounded_end_rect(
                    midi + 0.5 - BLACK_WIDTH, BLACK_TOP,
                    BLACK_WIDTH, BLACK_HEIGHT, BLACK_KEY_R, end="bottom",
                )
                item = pg.QtWidgets.QGraphicsPathItem(path)
                item.setBrush(key_black)
                item.setPen(no_pen)
                item.setZValue(20)
                self.keyboard_widget.addItem(item)
                self._keyboard_items.append(item)

        self.keyboard_widget.setYRange(0, WHITE_HEIGHT, padding=0)

        # ★ 音名画进键床内（T-1042c §2.1-②，竖横同一套）：文案沿用现有音名形态，
        # 色取 keys.label；自由端（键床下缘）一侧落位，避开贴上的黑键。原「音名轴」已隐藏。
        base_font, bold_font = PianoKeyboardStrip._name_fonts()
        for midi in range(midi_start, midi_end + 1):
            if midi % 12 != 0:
                continue
            is_center = midi == 60
            txt = pg.TextItem(
                PianoKeyboardStrip.note_label(midi), color=faces["label"],
                anchor=(0.5, 0.0), border=None, fill=None,
            )
            txt.textItem.setFont(bold_font if is_center else base_font)
            txt.setPos(float(midi), WHITE_HEIGHT * PianoKeyboardStrip.LABEL_INSET)
            txt.setZValue(30)
            self.keyboard_widget.addItem(txt)
            self._keyboard_items.append(txt)

    def _toggle_piano_keyboard(self, visible: bool):
        """切换钢琴键盘显示。"""
        self._keyboard_visible = visible
        if visible:
            self.keyboard_widget.show()
            self.splitter_plot.setSizes([self.splitter_plot.sizes()[0], 60])
            self.plot_widget.showAxis("bottom")
        else:
            self.keyboard_widget.hide()
            self.plot_widget.showAxis("bottom")
            for item in self._keyboard_items:
                self.keyboard_widget.removeItem(item)
            self._keyboard_items = []

    # ------------------------------------------------------------------
    # T-1060 件3：统一收尾（模板 = waveform.py `_cleanup_scene`/`closeEvent`）
    # 本控件析构图：PlotWidget→scene→{curve, curve_hold, _peak_marker, v_line,
    # h_line, 标记线/标签}，另有键床 PlotWidget 的键面 item 与两个事件过滤器
    # （viewport 交互过滤器 + 标记表键盘过滤器）。无显式收尾路径时，进程近尾
    # 由 Python GC 以「不同于 Qt 场景删除顺序」回收这些包装 → 场景析构遍历
    # 可能触碰已半释放的 C++ 项。这里先逐项移出场景 + 断 item 信号 + 摘事件
    # 过滤器，消除析构序依赖。只加收尾，不改任何事件/交互/绘制路径。
    # ------------------------------------------------------------------

    _DETACH_SINGLE_ITEMS = ("curve", "curve_hold", "_peak_marker", "v_line", "h_line")

    def _detach_scene_items(self) -> None:
        """统一收尾：断场景 item / 信号 / 事件过滤器（幂等、绝不外抛）。

        收尾后仍保留**纯值快照**（标记数据 `_manual_peaks` / 峰值行等），
        class 契约「close 后可读」不回退；仅清理 Qt 包装与连接：
        逐项 `removeItem` → 断 item 信号 → 摘事件过滤器 → 清空 item 容器。
        """
        plot_widget = getattr(self, "plot_widget", None)
        if plot_widget is None:
            return

        items = []
        for attr in self._DETACH_SINGLE_ITEMS:
            item = getattr(self, attr, None)
            if item is not None:
                items.append(item)
        items.extend([i for i in (getattr(self, "_mark_items", None) or []) if i is not None])

        # 断 item → 本控件的信号（先断后移除）
        for attr in ("v_line", "h_line"):
            line = getattr(self, attr, None)
            if line is None:
                continue
            try:
                line.sigPositionChanged.disconnect()
            except (TypeError, RuntimeError):
                pass

        for item in items:
            try:
                plot_widget.removeItem(item)
            except RuntimeError:
                pass  # 底层 C++ 已析构（控件正在销毁途中）
            except Exception:
                pass  # 双移除/缺登记等一律吞掉：收尾路径绝不外抛

        # 键床 item（本控件持有的键面包装；第二段 T-1060b 覆盖键面控件本体）
        kb = getattr(self, "keyboard_widget", None)
        if kb is not None:
            for item in list(getattr(self, "_keyboard_items", None) or []):
                try:
                    kb.removeItem(item)
                except RuntimeError:
                    pass
                except Exception:
                    pass
            self._keyboard_items = []

        # 摘事件过滤器（断「控件 ← 视口/标记表」的环）
        interaction = getattr(self, "_interaction", None)
        detach = getattr(interaction, "detach", None)
        if callable(detach):
            try:
                detach()
            except Exception:
                pass
        table = getattr(self, "marks_table", None)
        if table is not None:
            try:
                table.removeEventFilter(self)
            except RuntimeError:
                pass

        # 清空 item 容器（纯值快照不在此列，保持可读）
        self._mark_items = []

    def closeEvent(self, event):  # noqa: N802 (Qt 命名)
        """窗口关闭：先显式收尾场景 item，再走默认关闭。"""
        self._detach_scene_items()
        super().closeEvent(event)
