# SPDX-License-Identifier: GPL-3.0-only
"""房间模态分析控件。

计算并可视化矩形房间的固有声学模态，包括：
- 轴向/切向/斜向模态分类
- 理论频率响应合成
- 模态密度分析
"""

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QDoubleSpinBox, QSpinBox, QPushButton, QComboBox,
    QGroupBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
)

from acouscope.analysis.room_acoustics import (
    calculate_room_modes,
    synthesize_mode_response,
)
from acouscope.ui import theme

# 模态类型 → 内容色板索引（T-1038 M2：分类色复用 T-1036 内容色板，禁另造第二套分类色）
_MODE_ROLE_INDEX = {"axial": 0, "tangential": 1, "oblique": 2}
# 表格行底透明度（同色低 alpha 派生 → 主题互斥的硬编码浅底块消除）
_MODE_ROW_ALPHA = 48


def mode_ink(mode_type: str) -> str:
    """模态类型取色：内容色板（随主题骨架）。"""
    palette = theme.track_palette()
    return palette[_MODE_ROLE_INDEX[mode_type] % len(palette)]


def _mode_row_color(mode_type: str):
    """表格行底色：同色低 alpha 派生（QColor，随主题骨架）。"""
    from PyQt6.QtGui import QColor

    col = QColor(mode_ink(mode_type))
    col.setAlpha(_MODE_ROW_ALPHA)
    return col


def _btn_qss() -> str:
    """计算按钮 QSS（T-1038 M3：交互色 = accent，令牌插值，禁字面 hex/px）。"""
    c = theme.colors()
    sp = theme.TOKENS["spacing"]
    return (
        f"QPushButton{{background:{c['accent']};color:{c['accent_text']};"
        f"padding:{sp['sm']}px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{c['bg3']};}}"
    )


def _stat_qss() -> str:
    """统计信息标签 QSS（T-1038 M4：主题互斥的浅底块 → 中性阶令牌）。"""
    c = theme.colors()
    sp = theme.TOKENS["spacing"]
    rad = theme.TOKENS["radius"]
    tp = theme.TOKENS["typography"]
    bd = theme.TOKENS["elevation"]["border"]
    return (
        f"padding:{sp['sm']}px;background:{c['bg2']};"
        f"border:{bd}px solid {c['border']};"
        f"border-radius:{rad['sm']}px;color:{c['text']};font-size:{tp['caption']}px;"
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


class RoomModesWidget(QWidget):
    """房间模态分析控件。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._modes = []
        self._build_ui()
        self._on_calculate()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # ===== 左侧：参数面板 =====
        param_panel = QWidget()
        param_layout = QVBoxLayout(param_panel)
        param_layout.setContentsMargins(0, 0, 0, 0)
        param_layout.setSpacing(8)

        # 房间尺寸
        size_box = QGroupBox("房间尺寸")
        size_form = QGridLayout(size_box)
        size_form.setSpacing(6)

        size_form.addWidget(QLabel("长度 Lx："), 0, 0)
        self.spin_lx = QDoubleSpinBox()
        self.spin_lx.setRange(1.0, 100.0)
        self.spin_lx.setValue(6.0)
        self.spin_lx.setSuffix(" m")
        self.spin_lx.setSingleStep(0.1)
        size_form.addWidget(self.spin_lx, 0, 1)

        size_form.addWidget(QLabel("宽度 Ly："), 1, 0)
        self.spin_ly = QDoubleSpinBox()
        self.spin_ly.setRange(1.0, 100.0)
        self.spin_ly.setValue(4.5)
        self.spin_ly.setSuffix(" m")
        self.spin_ly.setSingleStep(0.1)
        size_form.addWidget(self.spin_ly, 1, 1)

        size_form.addWidget(QLabel("高度 Lz："), 2, 0)
        self.spin_lz = QDoubleSpinBox()
        self.spin_lz.setRange(1.0, 50.0)
        self.spin_lz.setValue(2.8)
        self.spin_lz.setSuffix(" m")
        self.spin_lz.setSingleStep(0.1)
        size_form.addWidget(self.spin_lz, 2, 1)

        param_layout.addWidget(size_box)

        # 计算参数
        calc_box = QGroupBox("计算参数")
        calc_form = QGridLayout(calc_box)
        calc_form.setSpacing(6)

        calc_form.addWidget(QLabel("最大阶数："), 0, 0)
        self.spin_max_order = QSpinBox()
        self.spin_max_order.setRange(1, 30)
        self.spin_max_order.setValue(15)
        calc_form.addWidget(self.spin_max_order, 0, 1)

        calc_form.addWidget(QLabel("最高频率："), 1, 0)
        self.spin_max_freq = QDoubleSpinBox()
        self.spin_max_freq.setRange(20, 2000)
        self.spin_max_freq.setValue(300)
        self.spin_max_freq.setSuffix(" Hz")
        self.spin_max_freq.setSingleStep(10)
        calc_form.addWidget(self.spin_max_freq, 1, 1)

        calc_form.addWidget(QLabel("声速："), 2, 0)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(300, 400)
        self.spin_speed.setValue(343)
        self.spin_speed.setSuffix(" m/s")
        self.spin_speed.setSingleStep(1)
        calc_form.addWidget(self.spin_speed, 2, 1)

        calc_form.addWidget(QLabel("模态 Q 值："), 3, 0)
        self.spin_q = QDoubleSpinBox()
        self.spin_q.setRange(1, 100)
        self.spin_q.setValue(20)
        self.spin_q.setSingleStep(1)
        calc_form.addWidget(self.spin_q, 3, 1)

        param_layout.addWidget(calc_box)

        # 计算按钮
        self.btn_calculate = QPushButton("计算模态")
        theme.style_when_theme(self.btn_calculate, lambda _c: _btn_qss())
        self.btn_calculate.clicked.connect(self._on_calculate)
        param_layout.addWidget(self.btn_calculate)

        # 统计信息
        self.lbl_stats = QLabel("")
        theme.style_when_theme(self.lbl_stats, lambda _c: _stat_qss())
        self.lbl_stats.setWordWrap(True)
        param_layout.addWidget(self.lbl_stats)

        param_layout.addStretch()

        # 预设房间
        preset_box = QGroupBox("预设房间")
        preset_layout = QVBoxLayout(preset_box)
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItem("自定义", None)
        self.cmb_preset.addItem("小型听音室 (4×3×2.5m)", (4.0, 3.0, 2.5))
        self.cmb_preset.addItem("中型录音室 (6×4.5×3m)", (6.0, 4.5, 3.0))
        self.cmb_preset.addItem("大型演播室 (10×8×4m)", (10.0, 8.0, 4.0))
        self.cmb_preset.addItem("起居室 (5×4×2.7m)", (5.0, 4.0, 2.7))
        self.cmb_preset.addItem("卧室 (3.5×3×2.6m)", (3.5, 3.0, 2.6))
        self.cmb_preset.addItem("音乐厅 (30×20×12m)", (30.0, 20.0, 12.0))
        self.cmb_preset.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.cmb_preset)
        param_layout.addWidget(preset_box)

        layout.addWidget(param_panel, stretch=0)

        # ===== 右侧：图表 + 表格（选项卡） =====
        tabs = QTabWidget()

        # 频率响应图
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("bottom", "频率", units="Hz")
        self.plot_widget.setLabel("left", "相对幅度", units="dB")
        self.plot_widget.setLogMode(x=True, y=False)
        self.plot_widget.setYRange(-60, 5)
        self.plot_widget.addLegend()
        _apply_canvas_theme(self.plot_widget)

        self.curve_response = self.plot_widget.plot(
            pen=pg.mkPen(color=theme.data_ink("trace"), width=3.3),
            name="合成响应",
        )

        # 模态标记
        self.scatter_axial = pg.ScatterPlotItem(
            pen=pg.mkPen(None),
            brush=pg.mkBrush(mode_ink("axial")),
            size=8,
            name="轴向模态",
        )
        self.plot_widget.addItem(self.scatter_axial)

        self.scatter_tangential = pg.ScatterPlotItem(
            pen=pg.mkPen(None),
            brush=pg.mkBrush(mode_ink("tangential")),
            size=6,
            name="切向模态",
        )
        self.plot_widget.addItem(self.scatter_tangential)

        self.scatter_oblique = pg.ScatterPlotItem(
            pen=pg.mkPen(None),
            brush=pg.mkBrush(mode_ink("oblique")),
            size=4,
            name="斜向模态",
        )
        self.plot_widget.addItem(self.scatter_oblique)

        tabs.addTab(self.plot_widget, "频率响应")

        # 模态表格
        self.table_modes = QTableWidget()
        self.table_modes.setColumnCount(6)
        self.table_modes.setHorizontalHeaderLabels(
            ["序号", "频率 (Hz)", "nx", "ny", "nz", "类型"]
        )
        self.table_modes.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table_modes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_modes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tabs.addTab(self.table_modes, "模态列表")

        layout.addWidget(tabs, stretch=1)
        theme.on_theme_change(self._on_canvas_theme)

    def _apply_ink(self) -> None:
        """数据墨色（T-1038 M1/M6）：响应曲线 + 三类模态散点/表格行底随主题取色。"""
        self.curve_response.setPen(pg.mkPen(color=theme.data_ink("trace"), width=3.3))
        for scatter, kind in (
            (self.scatter_axial, "axial"),
            (self.scatter_tangential, "tangential"),
            (self.scatter_oblique, "oblique"),
        ):
            scatter.setBrush(pg.mkBrush(mode_ink(kind)))
        for row in range(self.table_modes.rowCount()):
            for col in range(self.table_modes.columnCount()):
                item = self.table_modes.item(row, col)
                if item is None:
                    continue
                kind = item.data(Qt.ItemDataRole.UserRole)
                if kind in _MODE_ROLE_INDEX:
                    item.setBackground(_mode_row_color(kind))
        self.plot_widget.update()

    def _on_canvas_theme(self):
        """主题切换：重设房间模态画布底色/轴色 + 数据墨色（pyqtgraph 不走 QSS）。"""
        _apply_canvas_theme(self.plot_widget)
        self._apply_ink()
        self.lbl_stats.setStyleSheet(_stat_qss())

    def _on_calculate(self):
        """计算房间模态。"""
        lx = self.spin_lx.value()
        ly = self.spin_ly.value()
        lz = self.spin_lz.value()
        max_order = self.spin_max_order.value()
        max_freq = self.spin_max_freq.value()
        speed = self.spin_speed.value()
        q = self.spin_q.value()

        # 计算模态
        self._modes = calculate_room_modes(
            lx, ly, lz,
            max_order=max_order,
            max_freq=max_freq,
            speed_of_sound=speed,
        )

        # 合成频率响应
        freqs, response = synthesize_mode_response(
            self._modes,
            freq_range=(max(20, max_freq / 10), max_freq),
            q_factor=q,
        )
        self.curve_response.setData(freqs, response)

        # 模态散点
        axial_freqs = [m.frequency for m in self._modes if m.mode_type == "axial"]
        tangential_freqs = [m.frequency for m in self._modes if m.mode_type == "tangential"]
        oblique_freqs = [m.frequency for m in self._modes if m.mode_type == "oblique"]

        self.scatter_axial.setData(axial_freqs, [0] * len(axial_freqs))
        self.scatter_tangential.setData(tangential_freqs, [-3] * len(tangential_freqs))
        self.scatter_oblique.setData(oblique_freqs, [-6] * len(oblique_freqs))

        # 更新表格
        self.table_modes.setRowCount(len(self._modes))
        for i, mode in enumerate(self._modes):
            type_names = {
                "axial": "轴向",
                "tangential": "切向",
                "oblique": "斜向",
            }
            type_colors = {
                key: _mode_row_color(key) for key in _MODE_ROLE_INDEX
            }

            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(f"{mode.frequency:.2f}"),
                QTableWidgetItem(str(mode.nx)),
                QTableWidgetItem(str(mode.ny)),
                QTableWidgetItem(str(mode.nz)),
                QTableWidgetItem(type_names.get(mode.mode_type, mode.mode_type)),
            ]
            for j, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if mode.mode_type in type_colors:
                    item.setData(Qt.ItemDataRole.UserRole, mode.mode_type)
                    item.setBackground(type_colors[mode.mode_type])
                self.table_modes.setItem(i, j, item)

        # 统计信息
        volume = lx * ly * lz
        axial_count = sum(1 for m in self._modes if m.mode_type == "axial")
        tangential_count = sum(1 for m in self._modes if m.mode_type == "tangential")
        oblique_count = sum(1 for m in self._modes if m.mode_type == "oblique")

        # 模态密度（低频近似）
        stats_text = (
            f"体积：{volume:.1f} m³\n"
            f"总模态数：{len(self._modes)}\n"
            f"  轴向：{axial_count}  切向：{tangential_count}  斜向：{oblique_count}\n"
            f"最低模态：{self._modes[0].frequency:.1f} Hz" if self._modes else
            f"体积：{volume:.1f} m³\n未找到模态"
        )
        self.lbl_stats.setText(stats_text)

    def _on_preset_changed(self, index: int):
        """预设房间变化。"""
        data = self.cmb_preset.currentData()
        if data is not None:
            lx, ly, lz = data
            self.spin_lx.setValue(lx)
            self.spin_ly.setValue(ly)
            self.spin_lz.setValue(lz)
            self._on_calculate()
