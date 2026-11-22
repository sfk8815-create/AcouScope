# SPDX-License-Identifier: GPL-3.0-only
"""共振峰轨迹显示控件。"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip
from acouscope.ui.widgets.spectrum import (
    make_view_tool_row,
    pin_tool_row_widths,
    tool_field,
)


# F1~F4 序列数（配色不在此处定义：T-1038 M2 复用 T-1036 内容色板入口）
FORMANT_COUNT = 4

# H3：画布内图例（左上内缩 / 半透明底），挂在 ViewBox 内不占控件最小宽
_LEGEND_OFFSET = 8
_LEGEND_BG_ALPHA = 200


def formant_colors() -> list[str]:
    """F1~F4 多序列取色：T-1036 内容色板前 4 色（随主题骨架，禁另造第二套分类色）。"""
    return theme.track_palette()[:FORMANT_COUNT]


def _meta_qss(extra: str = "") -> str:
    """次级读数标签 QSS（T-1038 M3：令牌插值，禁字面 hex/px）。"""
    return (f"color: {theme.colors()['text_sub']};"
            f" font-size: {theme.TOKENS['typography']['body_sm']}px;{extra}")


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


class FormantWidget(QWidget):
    """共振峰轨迹显示控件（Y 轴单位可切换，与 FFT 频谱一致）。

    以散点显示各次共振峰频率随时间的变化，
    游标联动显示当前时刻各共振峰频率与带宽。
    """

    # T-323 播放联动信号：时间交互事件出口上抛，由 main_window 统一分发
    timeClicked = pyqtSignal(float)
    timeDoubleClicked = pyqtSignal(float)
    timeScrubbed = pyqtSignal(float)
    xRangeShifted = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._freq_unit = "hz"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 工具行（G4a-4：QToolBar 容器，窄宽下读数/单位收进「»」扩展菜单；
        # 横排布局会把 F1–F4 读数文字直接算进页面最小宽，实测 664 > 620 预算）
        toolbar = make_view_tool_row(self)
        self.tool_row = toolbar

        self.lbl_title = QLabel(tr("formants.title"))
        toolbar.addWidget(self.lbl_title)

        # Y 轴单位切换（与 FFT 频谱窗口一致）
        from acouscope.ui.widgets.freq_axis import build_freq_unit_combo

        self.cmb_y_unit = build_freq_unit_combo()
        self.cmb_y_unit.currentIndexChanged.connect(self._on_y_unit_changed)
        toolbar.addWidget(tool_field(QLabel(tr("formants.axis_y")), self.cmb_y_unit))

        self.lbl_time = QLabel(tr("formants.time_none"))
        self.lbl_time.setStyleSheet(_meta_qss())
        toolbar.addWidget(self.lbl_time)

        self.lbl_values = QLabel("")
        self.lbl_values.setStyleSheet(
            _meta_qss(f" margin-left: {theme.TOKENS['control']['pad_x']}px;"))
        toolbar.addWidget(self.lbl_values)

        pin_tool_row_widths(toolbar)
        layout.addWidget(toolbar)

        # 图 + 竖排钢琴键盘条（钢琴卷帘模式显示）
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("bottom", "时间", units="s")
        from acouscope.ui.widgets.time_axis import apply_time_axis

        apply_time_axis(self.plot_widget)
        # F3：构造期与 _redraw 共用同一数据源（freq_axis.set_freq_axis_label），
        # 消除硬写 Hz 的第二处标签；下拉切换后轴标题/刻度单位与所选一致。
        from acouscope.ui.widgets.freq_axis import set_freq_axis_label

        set_freq_axis_label(self.plot_widget, self._freq_unit)
        self.plot_widget.setMenuEnabled(False)
        _apply_canvas_theme(self.plot_widget)

        self.kb_strip = PianoKeyboardStrip()
        self.kb_strip.hide()
        self.kb_strip.follow(self.plot_widget)
        theme.on_theme_change(self._on_canvas_theme)

        plot_row = QHBoxLayout()
        plot_row.setContentsMargins(0, 0, 0, 0)
        plot_row.setSpacing(0)
        plot_row.addWidget(self.kb_strip)
        plot_row.addWidget(self.plot_widget)
        layout.addLayout(plot_row)

        # 各次共振峰散点
        self._scatters = []
        for color in formant_colors():
            scatter = pg.ScatterPlotItem(
                size=3,
                pen=pg.mkPen(None),
                brush=pg.mkBrush(color),
            )
            self.plot_widget.addItem(scatter)
            self._scatters.append(scatter)

        # H3：画布内图例（颜色 → F1/F2/F3/F4）。挂在 ViewBox 内（GraphicsItem），
        # 不参与控件 sizeHint → 不增加本页 minimumWidth（横排预算 620 已吃紧）。
        # 注意：只 setParentItem（同 PlotItem.addLegend 的口径），不 addItem——
        # ViewBox.addItem 会把父级改成内部 ChildGroup，而 LegendItem 的锚定要求
        # 父级带 geometryChanged（ChildGroup 没有 → 直接 AttributeError）。
        self.legend = self._build_legend()
        self.legend.hide()  # 空态/全缺值不显示（_redraw 按有效序列决定）

        # 游标
        self.v_line = pg.InfiniteLine(
            pos=0, angle=90, movable=True,
            pen=pg.mkPen(color=theme.data_ink("cursor"), width=3.3),
        )
        self.plot_widget.addItem(self.v_line)
        self.v_line.sigPositionChanged.connect(self._on_cursor_moved)

        self._times = np.array([])
        self._freqs = np.zeros((0, 0))
        self._bandwidths = np.zeros((0, 0))

        # T-323 导航手势状态
        self._scrubbing = False
        self._nav_press_view_t = None
        self._last_nav_click_at = -1.0
        self._last_nav_click_t = None
        self._xrange_blocked = False
        self._prev_view_x = None

        self.plot_widget.scene().installEventFilter(self)
        self.plot_widget.setMouseTracking(True)
        # T-326 Pδ：鼠标离开图区（viewport Leave）→ 悬停读数清零
        self.plot_widget.viewport().installEventFilter(self)
        self.plot_widget.plotItem.vb.sigRangeChanged.connect(self._on_view_range_changed)

        # T-326 Pδ：悬停读数 overlay + 选区测量 A/B 标记
        # （右上角只读小标签不挡图；读数经 _on_hover_readout 上抛 main_window → 状态栏临时段）
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

    def _build_legend(self):
        """H3：画布内图例（半透明底，随主题换色；不撑控件最小宽）。"""
        c = theme.colors()
        brush = QColor(c["bg1"])
        brush.setAlpha(_LEGEND_BG_ALPHA)
        legend = pg.LegendItem(
            offset=(_LEGEND_OFFSET, _LEGEND_OFFSET),
            brush=brush,
            pen=pg.mkPen(color=c["border"], width=1),
            labelTextColor=c["text_sub"],
            labelTextSize=f"{theme.TOKENS['typography']['caption_sm']}px",
        )
        legend.setParentItem(self.plot_widget.plotItem.vb)
        legend.setZValue(60)
        return legend

    def _sync_legend(self, valid_ks: list) -> None:
        """按「有数据的序列」重建图例项：缺值序列不显示图例项（H3）。"""
        legend = getattr(self, "legend", None)
        if legend is None:
            return
        try:
            legend.clear()
            for k in valid_ks:
                legend.addItem(self._scatters[k], f"F{k + 1}")
            legend.setVisible(bool(valid_ks))
        except Exception:  # noqa: BLE001 — 图例刷新永不抛
            pass

    def _apply_ink(self) -> None:
        """数据墨色（T-1038 M1/M6）：F1~F4 多序列 + 游标/测量标记随主题取色。"""
        colors = formant_colors()
        for i, scatter in enumerate(getattr(self, "_scatters", [])):
            scatter.setBrush(pg.mkBrush(colors[i % len(colors)]))
        legend = getattr(self, "legend", None)
        if legend is not None:
            c = theme.colors()
            brush = QColor(c["bg1"])
            brush.setAlpha(_LEGEND_BG_ALPHA)
            try:
                legend.setBrush(brush)
                legend.setPen(pg.mkPen(color=c["border"], width=1))
                legend.setLabelTextColor(c["text_sub"])
            except Exception:  # noqa: BLE001
                pass
        self.v_line.setPen(pg.mkPen(color=theme.data_ink("cursor"), width=3.3))
        for i, item in enumerate(getattr(self, "_measure_items", [])):
            role = "cursor" if i == 0 else "trace"
            item.setPen(pg.mkPen(color=theme.data_ink(role), width=1.8))
        for i, tag in enumerate(getattr(self, "_measure_item_labels", [])):
            tag.setColor(theme.data_ink("cursor" if i == 0 else "trace"))

    def _on_canvas_theme(self):
        """主题切换：重设共振峰画布底色/轴色 + 数据墨色（pyqtgraph 不走 QSS）。"""
        _apply_canvas_theme(self.plot_widget)
        self._apply_ink()
        self.lbl_time.setStyleSheet(_meta_qss())
        self.lbl_values.setStyleSheet(
            _meta_qss(f" margin-left: {theme.TOKENS['control']['pad_x']}px;"))
        self.plot_widget.update()

    def _nav_time_at(self, scene_pos) -> float:
        """场景坐标 → 时间（秒），夹取到数据时间范围。"""
        vb = self.plot_widget.plotItem.vb
        t = float(vb.mapSceneToView(scene_pos).x())
        if self._times.size:
            t = float(np.clip(t, float(self._times[0]), float(self._times[-1])))
        return t

    def _emit_nav_click(self, t: float) -> None:
        """微拖抬起：0.35s + 1% 视宽口径区分单击/双击（与波形判定一致）。"""
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
        """vb X 范围变化：仅"用户平移"上抛 xRangeShifted（程序 setXRange/缩放不发）。"""
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
            return
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
        """默认导航态手势出口：单击定位 / 双击播放 / Alt+拖 scrub（其余放行）。"""
        etype = event.type()
        if (etype in (event.Type.GraphicsSceneMousePress,
                      event.Type.GraphicsSceneMouseDoubleClick)
                and event.button() == Qt.MouseButton.LeftButton):
            if (etype == event.Type.GraphicsSceneMousePress
                    and event.modifiers() & Qt.KeyboardModifier.AltModifier):
                self._scrubbing = True
                self.timeScrubbed.emit(self._nav_time_at(event.scenePos()))
                return True
            self._nav_press_view_t = self._nav_time_at(event.scenePos())

        elif etype == event.Type.GraphicsSceneMouseMove and self._scrubbing:
            self.timeScrubbed.emit(self._nav_time_at(event.scenePos()))
            return True

        elif (etype == event.Type.GraphicsSceneMouseRelease
                and event.button() == Qt.MouseButton.LeftButton):
            if self._scrubbing:
                self._scrubbing = False
                self.timeScrubbed.emit(self._nav_time_at(event.scenePos()))
                return True
            if self._nav_press_view_t is not None:
                press_t = self._nav_press_view_t
                t = self._nav_time_at(event.scenePos())
                self._nav_press_view_t = None
                lo, hi = self.plot_widget.viewRange()[0]
                if abs(t - press_t) <= (hi - lo) * 0.004:
                    self._emit_nav_click(t)

        # T-326 Pδ：悬停读数（被动显示，不占手势；节流 ≤20Hz，离开即清不节流）
        if etype == event.Type.GraphicsSceneMouseMove:
            scene_pos = event.scenePos()
            vb = self.plot_widget.plotItem.vb
            if vb.sceneBoundingRect().contains(scene_pos):
                self._hover_update(scene_pos)
            else:
                self._hover_clear()
        elif etype == QEvent.Type.Leave and obj is self.plot_widget.viewport():
            self._hover_clear()
        return super().eventFilter(obj, event)

    def set_data(
        self,
        times: np.ndarray,
        formant_freqs: np.ndarray,
        formant_bw: np.ndarray,
    ):
        """设置共振峰数据。

        Args:
            times: 时间轴 [n_frames]
            formant_freqs: 共振峰频率 [n_frames, n_formants]（0 表示无效）
            formant_bw: 共振峰带宽 [n_frames, n_formants]
        """
        self._times = times
        self._freqs = formant_freqs
        self._bandwidths = formant_bw
        self._redraw()

    def _redraw(self):
        """按当前 Y 轴单位重绘散点。"""
        from acouscope.ui.widgets.freq_axis import (
            freq_to_display,
            note_name_ticks,
            set_freq_axis_label,
        )

        set_freq_axis_label(self.plot_widget, self._freq_unit)
        self.kb_strip.setVisible(self._freq_unit == "piano")

        times = self._times
        n_formants = min(self._freqs.shape[1], len(self._scatters)) if self._freqs.ndim == 2 else 0
        f_min, f_max = np.inf, 0.0

        valid_ks: list[int] = []
        for k in range(n_formants):
            freq_k = self._freqs[:, k]
            valid = freq_k > 0
            if np.any(valid):
                y = freq_to_display(freq_k[valid], self._freq_unit)
                self._scatters[k].setData(times[valid], y)
                valid_ks.append(k)
                f_min = min(f_min, freq_k[valid].min())
                f_max = max(f_max, freq_k[valid].max())
            else:
                self._scatters[k].setData([], [])

        if len(times) > 0 and f_min < np.inf:
            # 范围先在 Hz 域定界，再换算到当前单位
            margin = max((f_max - f_min) * 0.1, 50)
            y_lo = freq_to_display(max(0.0, f_min - margin), self._freq_unit)
            y_hi = freq_to_display(f_max + margin, self._freq_unit)
            self.plot_widget.setYRange(min(y_lo, y_hi), max(y_lo, y_hi), padding=0)
            self._xrange_blocked = True
            try:
                self.plot_widget.setXRange(times[0], times[-1], padding=0)
            finally:
                self._xrange_blocked = False
            self.v_line.setPos(times[len(times) // 2])

        # H3：图例只列有数据的序列（缺值序列不出条目）
        self._sync_legend(valid_ks)

        # Y 轴刻度：MIDI/钢琴卷帘用音名，其余自动
        axis_left = self.plot_widget.getAxis("left")
        if self._freq_unit in ("midi", "piano") and f_min < np.inf:
            y_lo = freq_to_display(max(0.0, f_min - max((f_max - f_min) * 0.1, 50)), self._freq_unit)
            y_hi = freq_to_display(f_max + max((f_max - f_min) * 0.1, 50), self._freq_unit)
            axis_left.setTicks([note_name_ticks(min(y_lo, y_hi), max(y_lo, y_hi))])
        else:
            axis_left.setTicks(None)

    def _on_y_unit_changed(self, index: int):
        """Y 轴单位切换。"""
        self._freq_unit = self.cmb_y_unit.itemData(index)
        self._redraw()

    def _on_cursor_moved(self):
        """游标移动。"""
        if len(self._times) == 0:
            return

        t = self.v_line.value()
        self.lbl_time.setText(tr("formants.time").format(time=f"{t:.3f}"))

        idx = int(np.argmin(np.abs(self._times - t)))
        parts = []
        for k in range(min(self._freqs.shape[1], FORMANT_COUNT)):
            f = self._freqs[idx, k]
            if f > 0:
                bw = self._bandwidths[idx, k]
                parts.append(f"F{k+1}: {f:.0f}Hz/{bw:.0f}Hz")
        self.lbl_values.setText("  ".join(parts))

    # ------------------------------------------------------------------
    # T-326 Pδ：悬停读数 + 选区测量（overlay 就近读数 + 上抛状态栏临时段）
    # ------------------------------------------------------------------

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
        """悬停读数文本（纯计算，测试直接调用断言）。

        频率 = 鼠标 y 显示坐标按当前单位映射回 Hz（format_freq_readout）；
        音分 = 相对当前 A4 参考（units.hz_to_cents），f≤0 防御显示 "--"。
        """
        from acouscope.dsp.units import hz_to_cents
        from acouscope.ui.widgets.freq_axis import display_to_freq, format_freq_readout

        f = display_to_freq(float(y_disp), self._freq_unit)
        if f > 0:
            cents = hz_to_cents(f)
            return (
                f"t={float(t_disp):.3f}s | {format_freq_readout(f, 'hz')} "
                f"| {cents:+.1f} cents"
            )
        return f"t={float(t_disp):.3f}s | -- | --"

    def freq_at(self, t: float) -> float | None:
        """t 时刻 F1（时间轴线性插值，非频谱插值）。

        F1 轨迹本身是逐帧估计值、**无 FFT bin 量化**，故只补「时间轴线性
        插值」：t 落在两个相邻且 F1 均有效的帧之间时，按时间比例线性插值
        F1。端点（恰好落在帧上/首末帧）、缺值（某帧 F1≤0）、越界一律回退
        到旧版「最近帧」读数，行为逐位不变。禁臆造频谱插值。
        """
        if not self._times.size or self._freqs.size == 0:
            return None
        tv = float(t)
        idx = int(np.argmin(np.abs(self._times - tv)))
        f1 = float(self._freqs[idx, 0])
        base = f1 if f1 > 0 else None
        if self._freqs.ndim >= 2:
            series = self._freqs[:, 0]
            n = min(int(self._times.size), int(series.size))
            if n >= 2:
                j = int(np.searchsorted(self._times[:n], tv, side="right")) - 1
                if 0 <= j < n - 1:
                    ta = float(self._times[j])
                    tb = float(self._times[j + 1])
                    fa = float(series[j])
                    fb = float(series[j + 1])
                    if tb > ta and fa > 0 and fb > 0 and ta <= tv <= tb:
                        w = (tv - ta) / (tb - ta)
                        return float(fa + (fb - fa) * w)
        return base

    def freq_uncertainty_cent(self, t: float) -> float | None:
        """共振峰 F1 的不确定度未建模：恒返回 None（禁臆造 u）。

        返回 None 时，main_window 的选区测量沿用旧键 ``measure_result.full``，
        显示文本不加 ``±``。
        """
        return None

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

    def _hover_update(self, scene_pos) -> None:
        """鼠标移动：节流 ≤20Hz 更新 overlay + 上抛 main_window（只读坐标映射）。"""
        now = time.monotonic()
        if now - self._last_hover_at < 0.05:
            return
        self._last_hover_at = now
        vb = self.plot_widget.plotItem.vb
        mp = vb.mapSceneToView(scene_pos)
        text = self.hover_readout_at(float(mp.x()), float(mp.y()))
        self.set_readout_overlay(text)
        if self._on_hover_readout is not None:
            self._on_hover_readout(text)

    def _hover_clear(self) -> None:
        """鼠标离开：立即隐藏 overlay + 上抛 None（不节流）。"""
        self._last_hover_at = 0.0
        self.set_readout_overlay(None)
        if self._on_hover_readout is not None:
            self._on_hover_readout(None)

    # ----- A/B 测量标记（main_window「测量选区」动作调用） -----

    def measure_markers_clear(self) -> None:
        """隐藏 A/B 测量标记（供「清除测量」/选区清除联动调用）。"""
        for item in list(self._measure_items) + list(self._measure_item_labels):
            if item is not None:
                item.hide()

    def measure_markers_show(self, t0: float, t1: float, f0: float, f1: float) -> None:
        """画 A(t0)/B(t1) 垂直标记线（颜色取数据墨色：A=游标 / B=轨迹；再次调用即覆盖）。"""
        if not self._measure_items:
            for role in ("cursor", "trace"):
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
