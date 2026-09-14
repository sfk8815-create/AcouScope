# SPDX-License-Identifier: GPL-3.0-only
"""音高轨迹显示控件。"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip
from acouscope.ui.widgets.plot_menu import install_plot_menu


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


class PitchContourWidget(QWidget):
    """音高轨迹显示控件（Y 轴单位可切换，与 FFT 频谱一致）。"""

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

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)

        self.lbl_title = QLabel("音高轨迹")
        toolbar.addWidget(self.lbl_title)

        toolbar.addStretch()

        # Y 轴单位切换（与 FFT 频谱窗口一致）
        from acouscope.ui.widgets.freq_axis import build_freq_unit_combo

        toolbar.addWidget(QLabel("Y轴:"))
        self.cmb_y_unit = build_freq_unit_combo()
        self.cmb_y_unit.currentIndexChanged.connect(self._on_y_unit_changed)
        toolbar.addWidget(self.cmb_y_unit)

        self.lbl_time = QLabel("时间: -- s")
        self.lbl_time.setStyleSheet(_meta_qss())
        toolbar.addWidget(self.lbl_time)

        self.lbl_freq = QLabel("频率: -- Hz")
        self.lbl_freq.setStyleSheet(
            _meta_qss(f" margin-left: {theme.TOKENS['control']['pad_x']}px;"))
        toolbar.addWidget(self.lbl_freq)

        self.lbl_cents = QLabel("音分: -- cents")
        self.lbl_cents.setStyleSheet(
            _meta_qss(f" margin-left: {theme.TOKENS['control']['pad_x']}px;"))
        toolbar.addWidget(self.lbl_cents)

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setMaximumHeight(32)
        layout.addWidget(toolbar_widget)

        # 图 + 竖排钢琴键盘条（钢琴卷帘模式显示）
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("bottom", "时间", units="s")
        from acouscope.ui.widgets.time_axis import apply_time_axis

        apply_time_axis(self.plot_widget)
        self.plot_widget.setLabel("left", "频率", units="Hz")
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

        # 散点图（音高轨迹）
        self.scatter = pg.ScatterPlotItem(size=3, pen=pg.mkPen(None))
        self.plot_widget.addItem(self.scatter)

        # 参考音高线（A4 = 440Hz）
        self.ref_line = pg.InfiniteLine(
            pos=440, angle=0,
            pen=pg.mkPen(color=theme.data_ink("ref_line"), width=2.2,
                         style=pg.QtCore.Qt.PenStyle.DashLine),
        )
        self.plot_widget.addItem(self.ref_line)
        self.ref_label = pg.TextItem("A4 (440 Hz)", color=theme.data_ink("ref_line"))
        self.ref_label.setPos(0, 440)
        self.plot_widget.addItem(self.ref_label)

        # 游标
        self.v_line = pg.InfiniteLine(
            pos=0, angle=90, movable=True,
            pen=pg.mkPen(color=theme.data_ink("cursor"), width=3.3),
        )
        self.plot_widget.addItem(self.v_line)
        self.v_line.sigPositionChanged.connect(self._on_cursor_moved)

        # 三语右键菜单（替代 pyqtgraph 内置英文菜单，只留真实可用动作）
        install_plot_menu(self.plot_widget, [
            (tr("menu.view_all"), self.plot_widget.autoRange),
            (tr("menu.reset_x"), self._reset_x),
            (tr("pitch.menu_refline"), self._toggle_ref_line),
        ])

        self._times = np.array([])
        self._f0 = np.array([])

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

        # T-922：音律标尺叠加层（默认关闭；None/[] = 无叠加，仅叠加层重绘不动轨迹）
        self._tuning_lines: list = []
        self._tuning_items: list = []  # [(pg.InfiniteLine, pg.TextItem)]

    def _apply_ink(self) -> None:
        """数据墨色（T-1038 M1/M6）：轨迹/参考线/游标/标记随主题骨架取色。"""
        self.scatter.setBrush(pg.mkBrush(theme.data_ink("trace")))
        self.ref_line.setPen(pg.mkPen(
            color=theme.data_ink("ref_line"), width=2.2,
            style=pg.QtCore.Qt.PenStyle.DashLine))
        self.ref_label.setColor(theme.data_ink("ref_line"))
        self.v_line.setPen(pg.mkPen(color=theme.data_ink("cursor"), width=3.3))
        for i, item in enumerate(getattr(self, "_measure_items", [])):
            role = "cursor" if i == 0 else "trace"
            item.setPen(pg.mkPen(color=theme.data_ink(role), width=1.8))
        for i, tag in enumerate(getattr(self, "_measure_item_labels", [])):
            tag.setColor(theme.data_ink("cursor" if i == 0 else "trace"))

    def _on_canvas_theme(self):
        """主题切换：重设音高画布底色/轴色 + 数据墨色（pyqtgraph 不走 QSS）。"""
        _apply_canvas_theme(self.plot_widget)
        self._apply_ink()
        self.lbl_time.setStyleSheet(_meta_qss())
        pad = theme.TOKENS["control"]["pad_x"]
        for lbl in (self.lbl_freq, self.lbl_cents):
            lbl.setStyleSheet(_meta_qss(f" margin-left: {pad}px;"))
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

    def set_data(self, times: np.ndarray, f0: np.ndarray):
        """设置音高数据。

        Args:
            times: 时间轴
            f0: 基频数组（零值表示无声）
        """
        self._times = times
        self._f0 = f0
        self._redraw()

    def _redraw(self):
        """按当前 Y 轴单位重绘轨迹与参考线。"""
        from acouscope.ui.widgets.freq_axis import (
            freq_to_display,
            note_name_ticks,
            set_freq_axis_label,
        )

        set_freq_axis_label(self.plot_widget, self._freq_unit)
        self.kb_strip.setVisible(self._freq_unit == "piano")

        valid = self._f0 > 0
        if not np.any(valid) or len(self._times) == 0:
            self.scatter.setData([], [])
            self._redraw_tuning_overlay()
            return

        y = freq_to_display(self._f0[valid], self._freq_unit)
        self.scatter.setData(self._times[valid], y)

        # 范围（先在 Hz 域定界，再换算到当前单位）
        f0_valid = self._f0[valid]
        y_lo = freq_to_display(max(50.0, f0_valid.min() * 0.8), self._freq_unit)
        y_hi = freq_to_display(min(4000.0, f0_valid.max() * 1.2), self._freq_unit)
        self.plot_widget.setYRange(min(y_lo, y_hi), max(y_lo, y_hi), padding=0)
        self.plot_widget.setXRange(self._times[0], self._times[-1], padding=0)

        # Y 轴刻度：MIDI/钢琴卷帘用音名，其余自动
        axis_left = self.plot_widget.getAxis("left")
        if self._freq_unit in ("midi", "piano"):
            axis_left.setTicks([note_name_ticks(min(y_lo, y_hi), max(y_lo, y_hi))])
        else:
            axis_left.setTicks(None)

        # 参考线位置（A4 = 440 Hz）
        ref_y = freq_to_display(440.0, self._freq_unit)
        self.ref_line.setPos(ref_y)
        self.ref_label.setPos(self._times[0], ref_y)

        self.v_line.setPos(self._times[len(self._times) // 2])

        # T-922：音律标尺叠加层随 Y 轴单位/范围同步（只动叠加层）
        self._redraw_tuning_overlay()

    def _on_y_unit_changed(self, index: int):
        """Y 轴单位切换。"""
        self._freq_unit = self.cmb_y_unit.itemData(index)
        self._redraw()

    # ------------------------------------------------------------------
    # 右键菜单动作
    # ------------------------------------------------------------------

    def _reset_x(self) -> None:
        """复位 X 轴到数据全程。"""
        if len(self._times) > 1:
            self._xrange_blocked = True
            try:
                self.plot_widget.setXRange(self._times[0], self._times[-1], padding=0.02)
            finally:
                self._xrange_blocked = False

    def _toggle_ref_line(self) -> None:
        """A4 参考线（440 Hz）显示开关。"""
        visible = not self.ref_line.isVisible()
        self.ref_line.setVisible(visible)
        self.ref_label.setVisible(visible)

    # ------------------------------------------------------------------
    # T-922 音律标尺叠加层
    # ------------------------------------------------------------------

    def set_tuning_overlay(self, lines=None) -> None:
        """设置音律标尺叠加线（None/[] → 清除）。

        只重绘叠加层：不重算音高数据、不清空轨迹（``set_data`` 不会被调用）。
        """
        self._tuning_lines = list(lines) if lines else []
        self._redraw_tuning_overlay()

    def tuning_overlay_enabled(self) -> bool:
        """当前是否显示音律标尺叠加层。"""
        return bool(getattr(self, "_tuning_lines", []))

    def _redraw_tuning_overlay(self) -> None:
        """按当前叠加线重绘音律标尺（水平线 + 音级标签），不触碰音高数据。"""
        from acouscope.ui.theme import TOKENS, colors
        from acouscope.ui.widgets.freq_axis import freq_to_display

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
                    style=pg.QtCore.Qt.PenStyle.DotLine,
                ),
            )
            label_item = pg.TextItem(color=palette["sub"], anchor=(0.0, 1.0))
            self.plot_widget.addItem(line_item)
            self.plot_widget.addItem(label_item)
            items.append((line_item, label_item))

        x0 = float(self._times[0]) if len(self._times) else 0.0
        for index, (line_item, label_item) in enumerate(items):
            if index >= len(lines):
                line_item.hide()
                label_item.hide()
                continue
            overlay = lines[index]
            y = float(freq_to_display(overlay.freq_hz, self._freq_unit))
            line_item.setPos(y)
            line_item.show()
            label_item.setText(overlay.label)
            label_item.setPos(x0, y)
            label_item.show()

    def _on_cursor_moved(self):
        """游标移动。"""
        if len(self._times) == 0:
            return

        t = self.v_line.value()
        self.lbl_time.setText(f"时间: {t:.3f} s")

        # 找最近的有效音高点
        valid = self._f0 > 0
        if np.any(valid):
            times_valid = self._times[valid]
            f0_valid = self._f0[valid]
            idx = np.argmin(np.abs(times_valid - t))
            f = f0_valid[idx]
            self.lbl_freq.setText(f"频率: {f:.1f} Hz")

            # 计算音分偏差（相对于 A4 = 440Hz）
            cents = 1200 * np.log2(f / 440.0)
            self.lbl_cents.setText(f"音分: {cents:+.0f} cents")

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
        音分 = 1200·log2(f/440)，f≤0 防御显示 "--"。
        """
        from acouscope.ui.widgets.freq_axis import display_to_freq, format_freq_readout

        f = display_to_freq(float(y_disp), self._freq_unit)
        if f > 0:
            cents = 1200.0 * np.log2(f / 440.0)
            return (
                f"t={float(t_disp):.3f}s | {format_freq_readout(f, 'hz')} "
                f"| {cents:+.1f} cents"
            )
        return f"t={float(t_disp):.3f}s | -- | --"

    def freq_at(self, t: float) -> float | None:
        """t 时刻最近 voiced f0（f0>0 最近帧）；无声/无数据 → None（Pδ 测量口径）。"""
        if not self._times.size:
            return None
        valid = self._f0 > 0
        if not np.any(valid):
            return None
        tv = self._times[valid]
        fv = self._f0[valid]
        idx = int(np.argmin(np.abs(tv - float(t))))
        return float(fv[idx])

    def result_arrays(self) -> tuple:
        """返回当前音高结果 (times, f0) 只读引用（T-327 区间统计读取，禁调用方改动）。"""
        return (self._times, self._f0)

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
