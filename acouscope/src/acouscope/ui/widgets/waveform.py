# SPDX-License-Identifier: GPL-3.0-only
"""波形显示控件。

基于 pyqtgraph 的高性能波形显示，支持：
- 可拖动的分析位置指针（Shift 拖动；CB-016-2 强化）
- 分析范围读数（检查器数值显示，CB-016-3）
- 播放头显示
- 区域标注（时间区间，支持循环播放）
- 时间点标注（瞬态、节拍等）
- 右键菜单增删标注
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
from acouscope.i18n import tr
from acouscope.ui import theme
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import (
    QAction, QPainter, QColor, QLinearGradient, QBrush, QFont, QFontMetrics,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QMenu, QFrame, QLineEdit,
    QScrollBar, QPushButton, QSizePolicy,
)


def _tool_btn_qss(c: dict) -> str:
    """波形工具按钮 QSS（跟随主题令牌；T-1038：字号/间距/半径令牌化，禁字面 px）。"""
    ty = theme.TOKENS["typography"]
    sp = theme.TOKENS["spacing"]
    rad = theme.TOKENS["radius"]
    bd = theme.TOKENS["elevation"]["border"]
    return (
        f"QPushButton{{font-size:{ty['caption']}px;padding:{sp['xxs']}px {sp['sm']}px;"
        f"color:{c['sub']};border:{bd}px solid {c['border']};border-radius:{rad['sm']}px;"
        f"background:{c['btn']};}}"
        f"QPushButton:hover{{background:{c['btn_hover']};color:{c['text']};border-color:{c['border']};}}"
        f"QPushButton:checked{{background:{c['accent']};color:{c['accent_text']};border-color:{c['accent']};}}"
    )


def _tb_btn_qss(c: dict) -> str:
    """缩放按钮组 QSS（固定宽度，跟随主题令牌；T-1038：全令牌化）。"""
    ty = theme.TOKENS["typography"]
    sp = theme.TOKENS["spacing"]
    ctl = theme.TOKENS["control"]
    bd = theme.TOKENS["elevation"]["border"]
    min_w = sp["sm"] * 2 + ctl["gap"]        # 22 = 8*2+6
    return (
        f"QPushButton{{font-size:{ty['caption']}px;padding:{sp['xxs']}px {ctl['gap']}px;"
        f"min-width:{min_w}px;"
        f"color:{c['sub']};border:{bd}px solid {c['border']};border-radius:{sp['xxs'] + bd}px;"
        f"background:{c['btn']};}}"
        f"QPushButton:hover{{background:{c['btn_hover']};color:{c['text']};border-color:{c['border']};}}"
        f"QPushButton:checked{{background:{c['accent']};color:{c['accent_text']};border-color:{c['accent']};}}"
        f"QPushButton:disabled{{color:{c['border']};background:{c['btn_hover']};}}"
    )


def _role_qcolor(role_hex: str, alpha: int) -> QColor:
    """主题角色色 → QColor 派生（hex + 透明度；CB-009 三样式禁硬编码 hex）。

    入参为 theme.TOKENS/colors() 既有角色的 hex 值，alpha 合成半透明视觉，
    供选区/标注等 pyqtgraph item 的 brush/pen 取色使用。
    """
    c = QColor(role_hex)
    c.setAlpha(alpha)
    return c


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


class VUMeter(QWidget):
    """垂直 VU 电平表（Audacity 风格，dB 刻度 + 平滑动画）。

    回调只提交目标峰值（攻击即时）；33ms 动画定时器做释放匀速回落与
    峰值保持，数值未变时跳过重绘（空闲零开销）。
    """

    _DB_FLOOR = -60.0
    _RELEASE_DB_S = 40.0    # 电平条回落速度 (dB/s)
    _PEAK_HOLD_S = 0.7      # 峰值线保持时间
    _PEAK_FALL_DB_S = 18.0  # 峰值线回落速度 (dB/s)
    _TICK_S = 0.033
    _UNIT_LABEL = "dB"
    _TICK_LABELS = ("0", "-3", "-6", "-10", "-20", "-40", "-60")
    _COMPACT_TICK_LABELS = ("0", "-20", "-40", "-60")
    _COMPACT_MAX_H = 120    # 低于此高只标四档，防刻度文字互叠
    _BAR_W = 8
    _BAR_X = 1
    # H2：刻度短线收短（2）、刻度文字与短线之间留空（4）——原 3/1 时短线与
    # 负号相接，0 档被读成「-0」、-3 被读成「––3」。取值仍走本类常量，
    # 不引入裸像素字面量进 QSS（刻度几何本就是绘制常量，非样式表长度）。
    _TICK_LEN = 2
    _LABEL_GAP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_db = self._DB_FLOOR   # 自上次 tick 以来到达的最大电平
        self._level_db = self._DB_FLOOR    # 平滑显示电平
        self._peak_db = self._DB_FLOOR     # 峰值保持
        self._peak_hold = 0.0
        # 屏幕上已绘制的值（变化 >0.05dB 才重绘）
        self._paint_level_db = self._DB_FLOOR
        self._paint_peak_db = self._DB_FLOOR
        self.setMinimumWidth(28)
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)
        self._anim.start(33)  # ~30 fps 动画

    @staticmethod
    def _to_db(v: float) -> float:
        return 20.0 * float(np.log10(max(float(v), 1e-6)))

    def set_level(self, level: float):
        """提交瞬时峰值 (0.0 ~ 1.0)。可高频调用，只记录最大值。"""
        db = self._to_db(max(0.0, min(1.0, level)))
        if db > self._target_db:
            self._target_db = db

    def reset(self):
        """复位到 -∞（停止播放/录音时调用）。"""
        self._target_db = self._DB_FLOOR
        self._level_db = self._DB_FLOOR
        self._peak_db = self._DB_FLOOR
        self._peak_hold = 0.0
        self._paint_level_db = self._DB_FLOOR
        self._paint_peak_db = self._DB_FLOOR
        self.update()

    def stop_animation(self) -> None:
        """停止 33ms 动画定时器并断开其 timeout 连接（幂等、绝不出错）。

        T-1060 件1（H2）：本定时器以 VUMeter 为 C++ 父对象。若宿主的 Python
        包装先于 C++ 对象被回收，计时器仍留在 Qt 定时器表里按 33ms 周期派发
        到失效 slot 代理 → SIGSEGV。故收尾必须**先停表断连**，而不是等 GC
        时机；停表后电平数值不再刷新（控件已在收尾，无可见行为变化）。
        """
        timer = getattr(self, "_anim", None)
        if timer is None:
            return
        try:
            timer.stop()
        except RuntimeError:
            return  # 底层 C++ 已析构
        try:
            timer.timeout.disconnect()
        except (TypeError, RuntimeError):
            pass  # 无连接/已断开/已析构：一律吞掉

    def closeEvent(self, event):  # noqa: N802 (Qt 命名)
        """关闭：先停动画定时器（断悬垂投递源），再走默认关闭。"""
        self.stop_animation()
        super().closeEvent(event)

    def _tick(self):
        dt = self._TICK_S
        # 攻击即时上升，释放按 dB/s 匀速回落
        if self._target_db > self._level_db:
            self._level_db = self._target_db
        else:
            self._level_db = max(
                self._DB_FLOOR, self._level_db - self._RELEASE_DB_S * dt
            )
        # 峰值保持：到达更高峰重置计时，保持期后匀速回落
        if self._target_db >= self._peak_db:
            self._peak_db = self._target_db
            self._peak_hold = 0.0
        else:
            self._peak_hold += dt
            if self._peak_hold > self._PEAK_HOLD_S:
                self._peak_db = max(
                    self._DB_FLOOR, self._peak_db - self._PEAK_FALL_DB_S * dt
                )
        self._target_db = self._DB_FLOOR

        if (
            abs(self._paint_level_db - self._level_db) > 0.05
            or abs(self._paint_peak_db - self._peak_db) > 0.05
        ):
            self._paint_level_db = self._level_db
            self._paint_peak_db = self._peak_db
            self.update()

    def sizeHint(self):
        return QSize(32, 200)

    def minimumSizeHint(self):
        return QSize(24, 80)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        bar_w = self._BAR_W
        bar_x = self._BAR_X

        c = theme.colors()
        sem = theme.TOKENS["semantic"]
        # 背景
        painter.fillRect(bar_x, 0, bar_w, h, QColor(c["border"]))

        floor = self._DB_FLOOR
        # dB → 像素高度（线性 dB 刻度：0dB=满高且在顶，-60dB=0）
        level_h = int((1.0 - self._paint_level_db / floor) * h)
        # 峰值线 y 与刻度线同式：0dB→顶(0)、-60dB→底(h-1)
        peak_y = int((self._paint_peak_db / floor) * h)
        peak_y = min(max(peak_y, 0), h - 1)

        # 渐变色（成功 → 警告 → 错误），跟随主题语义色
        gradient = QLinearGradient(0, h, 0, 0)
        gradient.setColorAt(0.0, QColor(sem["success"]))
        gradient.setColorAt(0.7, QColor(sem["warning"]))
        gradient.setColorAt(0.85, QColor(sem["error"]))
        gradient.setColorAt(1.0, QColor(sem["error"]))

        if level_h > 0:
            painter.fillRect(bar_x, 0, bar_w, level_h, QBrush(gradient))

        if self._paint_peak_db > floor:
            painter.setPen(QColor(c["text"]))
            painter.drawLine(bar_x - 2, peak_y, bar_x + bar_w + 1, peak_y)

        # dB 刻度线 + 数字/单位标注（文字色走主题 sub；矮态只标四档）
        labels = (
            self._COMPACT_TICK_LABELS if h < self._COMPACT_MAX_H
            else self._TICK_LABELS
        )
        text_x = bar_x + bar_w + self._TICK_LEN + self._LABEL_GAP
        # 0dB 在顶(y=0)、-60dB 贴底；clamp 进界（-60 档贴 h-1 不再丢）
        ys = {
            label: min(max(int((float(label) / floor) * h), 0), h - 1)
            for label in labels
        }
        need_ys = sorted(ys.values())
        min_gap = min(
            (b - a for a, b in zip(need_ys, need_ys[1:])), default=float(h)
        )

        def _layout(line_h: int) -> dict[str, int]:
            """自上而下贴刻度排字：密集处下移，单位带（顶部）之下不重叠。

            几何翻转后密集簇（0/-3/-6/-10）在顶部，避让方向随之下行；
            与旧码「密集处在底部、向上避让」镜像，仍贴各自刻度。
            """
            next_top = line_h
            tops: dict[str, int] = {}
            for label in sorted(labels, key=float, reverse=True):
                top = max(int(ys[label]) - line_h // 2, next_top)
                top = min(top, h - line_h)
                tops[label] = top
                next_top = top + line_h
            return tops

        font = QFont(painter.font())
        font.setFamilies(theme.ui_font_families())
        font.setPixelSize(theme.TOKENS["typography"]["caption_sm"])
        avail = max(1, w - text_x)
        while True:
            metrics = QFontMetrics(font)
            line_h = metrics.height()
            widest = max(
                metrics.horizontalAdvance(s)
                for s in (*labels, self._UNIT_LABEL)
            )
            tops = {k: max(v, line_h) for k, v in _layout(line_h).items()}
            ordered = sorted(tops.values())
            fits = (
                max(ordered) + line_h <= h
                and all(
                    a + line_h <= b for a, b in zip(ordered, ordered[1:])
                )
            )
            if (
                (widest <= avail and line_h <= min_gap and fits)
                or font.pixelSize() <= 7
            ):
                break
            font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        painter.setPen(QColor(c["sub"]))
        for label in labels:
            y = int(ys[label])
            if 0 <= y < h:
                painter.drawLine(
                    bar_x + bar_w, y, bar_x + bar_w + self._TICK_LEN, y
                )
            painter.drawText(
                text_x, tops[label], w - text_x, line_h, align, label
            )
        # 顶部留单位带，刻度数字从其下方起排（防压顶档）
        painter.drawText(text_x, 0, w - text_x, line_h, align, self._UNIT_LABEL)

        painter.end()


class ShiftDragInfiniteLine(pg.InfiniteLine):
    """只有按住 Shift 才能拖动的竖线（分析位置线）。

    pyqtgraph 的 InfiniteLine 在 movable=False 时不接受鼠标按压，
    后续拖动事件也不会送达——因此必须在按压时按 Shift 状态动态
    设定 movable，让基类接受按压。
    """

    hover_tip_callback: Optional[Callable[[], None]] = None

    def __init__(self, **kwargs):
        kwargs.setdefault("movable", False)
        super().__init__(**kwargs)

    def mousePressEvent(self, ev):
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.movable = shift
        super().mousePressEvent(ev)

    def mouseDragEvent(self, ev):
        # 拖动中途松开 Shift 立即停止移动
        self.movable = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        super().mouseDragEvent(ev)

    def hoverEvent(self, ev):
        super().hoverEvent(ev)
        if ev.enter and callable(self.hover_tip_callback):
            self.hover_tip_callback()


class _LabelPopover(QFrame):
    """标注标签输入 popover（CB-004 方案 A，非模态）。

    右键菜单选「添加区域/时间点标注」后，在标注点原位弹出的标签输入框：
    - QWidget（QFrame）+ QLineEdit，Qt.Popup 锚定（零对话框/零阻塞调用）
    - 回车或 ✓ 提交；Esc 或 ✕ 取消；失焦（点击外部自动关闭）提交
    - 空文本 = 可留空（与既有原生模态输入语义一致）
    仅负责「收集标签文本」，标注的创建仍由调用方（右键手动触发）完成。
    """

    committed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self._started = False   # present() 之后才允许失焦自动提交
        self._finished = False  # 已提交/已取消，hide 不再触发提交

        from acouscope.i18n import tr

        sp = theme.TOKENS["spacing"]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(sp["sm"], sp["sm"], sp["sm"], sp["sm"])
        lay.setSpacing(sp["xs"])

        self.edit = QLineEdit(self)
        self.edit.setMinimumWidth(160)
        self.edit.installEventFilter(self)  # 拦截 Esc（编辑框聚焦时）
        self.edit.returnPressed.connect(self._commit)
        lay.addWidget(self.edit, 1)

        self.btn_ok = QPushButton("\u2713", self)     # ✓
        self.btn_cancel = QPushButton("\u2715", self)  # ✕
        self.btn_ok.setToolTip(tr("btn.ok"))
        self.btn_cancel.setToolTip(tr("btn.cancel"))
        self.btn_ok.clicked.connect(self._commit)
        self.btn_cancel.clicked.connect(self._cancel)
        lay.addWidget(self.btn_ok)
        lay.addWidget(self.btn_cancel)

        # 主题令牌化（禁硬编码 hex/px）：面板底/边框走 colors()，spacing 走 TOKENS
        self._refresh_style = theme.style_when_theme(self, self._build_qss)

    @staticmethod
    def _build_qss(c: dict) -> str:
        # 令牌派生（V099_TOKENS_V1）：禁硬编码 hex；半径/字阶/间距走 TOKENS
        sp = theme.TOKENS["spacing"]
        rad = theme.TOKENS["radius"]
        ty = theme.TOKENS["typography"]
        bd = theme.TOKENS["elevation"]["border"]
        return "".join([
            f"QFrame {{ background: {c['panel']};"
            f" border: {bd}px solid {c['border']};"
            f" border-radius: {rad['sm']}px; }}",
            f"QLineEdit {{ background: {c['input']}; color: {c['text']};"
            f" border: {bd}px solid {c['border']};"
            f" border-radius: {rad['sm']}px;"
            f" padding: {sp['xs']}px {sp['sm']}px;"
            f" selection-background-color: {c['sel_bg']}; }}",
            f"QLineEdit:focus {{ border: {bd}px solid {c['accent']}; }}",
            f"QPushButton {{ border: none; background: transparent;"
            f" color: {c['sub']}; font-size: {ty['body']}px;"
            f" padding: {sp['xs']}px {sp['xs']}px; }}",
            f"QPushButton:hover {{ background: {c['btn_hover']};"
            f" color: {c['text']}; border-radius: {rad['sm']}px; }}",
        ])

    # ------------------------------------------------------------------
    # 交互语义
    # ------------------------------------------------------------------

    def present(self, global_pos: QPoint) -> None:
        """在指定全局坐标锚定并显示（标注点原位）。"""
        self.adjustSize()
        off = theme.TOKENS["spacing"]["sm"]
        self.move(global_pos.x() + off, global_pos.y() + off)
        self.show()
        self.edit.setFocus()
        self.edit.setCursorPosition(len(self.edit.text()))
        self._started = True

    def _commit(self):
        if self._finished:
            return
        self._finished = True
        self.hide()
        self.committed.emit(self.edit.text())

    def _cancel(self):
        if self._finished:
            return
        self._finished = True
        self.hide()
        self.cancelled.emit()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self._cancel()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def eventFilter(self, obj, ev):
        # 编辑框聚焦时 Esc 被编辑框消费，需在此拦截实现「Esc 取消」
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True
        return super().eventFilter(obj, ev)

    def hideEvent(self, ev):
        # 失焦自动关闭（点击外部）＝提交；Esc/✓/✕ 关闭时 _finished 已置位，不再提交
        if self._started and not self._finished:
            self._commit()
        super().hideEvent(ev)


class WaveformWidget(QWidget):
    """波形显示控件。"""

    # 交互/选区信号（Transport 信号已迁至 widgets/transport_bar.py::TransportBar）
    positionChanged = pyqtSignal(float)  # 位置变化（秒）
    selectionChanged = pyqtSignal(object)  # 选区变化：(t0, t1) 或 None
    analyzeRegionRequested = pyqtSignal(float, float)  # T-915：用户请求对选区 [t0, t1] 重新分析
    playheadSeek = pyqtSignal(float)       # 左键点击波形定位播放头（秒）
    # CB-016-3：红针分析位置变化（钳位后 emit）。禁复用 positionChanged——
    # 该信号在 main_window 已连播放位置语义（controller.set_position），
    # 复用会误跳播放头；position_changed_callback 为单槽且被视图切换覆写。
    analysisPositionChanged = pyqtSignal(float)
    tipRequested = pyqtSignal(str)         # 上下文提示（i18n key）
    trimSilenceRequested = pyqtSignal()    # 请求去除开头静默（主窗口处理）

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # ===== 顶部工具栏：波形工具（Transport 控件已迁至独立传输条） =====
        self.toolbar = QHBoxLayout()
        self.toolbar.setContentsMargins(6, 4, 6, 0)
        self.toolbar.setSpacing(2)

        # --- 波形工具（QSS 跟随主题令牌，见 _tool_btn_qss / _tb_btn_qss） ---
        tool_btn = _tool_btn_qss(theme.colors())
        tb_btn = _tb_btn_qss(theme.colors())

        self.btn_zoom_in = QPushButton("🔍+")
        self.btn_zoom_in.setToolTip(tr("waveform.tip_zoom_in"))
        self.btn_zoom_in.setStyleSheet(tb_btn)
        self.btn_zoom_in.setFixedWidth(36)
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.toolbar.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("🔍−")
        self.btn_zoom_out.setToolTip(tr("waveform.tip_zoom_out"))
        self.btn_zoom_out.setStyleSheet(tb_btn)
        self.btn_zoom_out.setFixedWidth(36)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.toolbar.addWidget(self.btn_zoom_out)

        self.btn_zoom_fit = QPushButton("⤢")
        self.btn_zoom_fit.setToolTip(tr("waveform.tip_fit"))
        self.btn_zoom_fit.setStyleSheet(tb_btn)
        self.btn_zoom_fit.setFixedWidth(36)
        self.btn_zoom_fit.clicked.connect(self.zoom_fit)
        self.toolbar.addWidget(self.btn_zoom_fit)

        # Scrub 模式
        self.btn_scrub = QPushButton("⟿ Scrub")
        self.btn_scrub.setToolTip(tr("waveform.tip_scrub"))
        self.btn_scrub.setCheckable(True)
        self.btn_scrub.setStyleSheet(tool_btn)
        self.btn_scrub.clicked.connect(self._on_scrub_toggled)
        self.toolbar.addWidget(self.btn_scrub)

        # 归一化
        self.btn_normalize = QPushButton("归一化")
        self.btn_normalize.setToolTip(tr("waveform.tip_normalize"))
        # G9：「归一化」本身即切换语义（tooltip 已写「切换波形归一化显示」），
        # 故设为 checkable，由 _tool_btn_qss 的 :checked 规则给出可见「已开启」态
        # （accent 底 + accent_text 字 + accent 描边），与常态/悬停态三态互异。
        self.btn_normalize.setCheckable(True)
        self.btn_normalize.setAccessibleName(tr("waveform.tip_normalize"))
        self.btn_normalize.setStyleSheet(tool_btn)
        self.btn_normalize.clicked.connect(self.toggle_normalize)
        self.toolbar.addWidget(self.btn_normalize)

        # 去除开头静默
        self.btn_trim_silence = QPushButton(tr("wave.trim_silence_btn"))
        self.btn_trim_silence.setToolTip(tr("wave.trim_silence_tip"))
        self.btn_trim_silence.setStyleSheet(tool_btn)
        self.btn_trim_silence.clicked.connect(self.trimSilenceRequested.emit)
        theme.on_theme_change(self._refresh_toolbutton_qss)
        self._refresh_toolbutton_qss()
        self.toolbar.addWidget(self.btn_trim_silence)

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(self.toolbar)
        toolbar_widget.setMaximumHeight(30)
        layout.addWidget(toolbar_widget)

        # ===== 波形图 + 右侧 VU 电平表（同一行） =====
        wave_container = QWidget()
        wave_container.setContentsMargins(0, 0, 0, 0)
        wave_row = QHBoxLayout(wave_container)
        wave_row.setContentsMargins(0, 0, 6, 4)
        wave_row.setSpacing(4)

        # 波形 PlotWidget
        self.plot_widget = pg.PlotWidget()

        # 关键性能配置：长录音（百万采样点）自动峰值降采样 + 只渲染
        # 可视区，否则全量绘制导致界面卡死
        self.plot_widget.setDownsampling(auto=True, mode="peak")
        self.plot_widget.setClipToView(True)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("bottom", "时间", units="s")
        from acouscope.ui.widgets.time_axis import apply_time_axis

        apply_time_axis(self.plot_widget)
        self.plot_widget.setLabel("left", "幅度")
        _apply_canvas_theme(self.plot_widget)
        theme.on_theme_change(self._on_canvas_theme)
        self.plot_widget.setYRange(-1, 1, padding=0)
        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.plot_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        wave_row.addWidget(self.plot_widget, stretch=1)

        # 右侧 VU 表（Audacity 风格垂直电平表）
        self.vu_meter = VUMeter()
        self.vu_meter.setToolTip(tr("waveform.tip_level"))
        self.vu_meter.setFixedWidth(32)
        self.vu_meter.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        wave_row.addWidget(self.vu_meter)

        # 水平滚动条（Audacity 风格：定位 + 导航）
        self.scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.scrollbar.setSingleStep(10)
        self.scrollbar.setPageStep(100)
        self.scrollbar.setRange(0, 1000)
        self.scrollbar.setValue(0)
        self.scrollbar.valueChanged.connect(self._on_scrollbar_changed)

        layout.addWidget(wave_container, stretch=1)
        layout.addWidget(self.scrollbar)

        # 视图范围变化时更新滚动条
        self.plot_widget.plotItem.vb.sigRangeChanged.connect(
            lambda vb, ranges: self._update_scrollbar())

        # 波形曲线（禁用抗锯齿：AA 软件光栅化在本平台是 100 倍级开销，
        # 是录音卡顿与载入后迟钝的直接原因；min/max 包络下视觉差异可忽略）
        self.curve = self.plot_widget.plot(
            pen=pg.mkPen(color=theme.data_ink("trace"), width=1.8),
            antialias=False,
        )

        # 零线
        self.zero_line = pg.InfiniteLine(
            pos=0,
            angle=0,
            pen=pg.mkPen(color=theme.data_ink("ref_line"), width=0.5,
                         style=Qt.PenStyle.DashLine),
        )
        self.plot_widget.addItem(self.zero_line)

        # 分析位置指针（按住 Shift 才能拖动；CB-016-1 蓝条移除后不再与区域咬合）
        # CB-016-2：强化红针——宽度 6、TOKENS 语义 error 色（禁内联 hex）、
        # Label 醒目（i18n 文案 + 加粗/放大的防御式样式，见
        # _style_analysis_cursor_label）。Shift 拖动语义零改动。
        err_hex = theme.TOKENS["semantic"]["error"]
        self.analysis_cursor = ShiftDragInfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=pg.mkPen(color=err_hex, width=6.0),
            label=tr("wave.analysis_cursor"),
            labelOpts={
                "position": 0.95,
                "color": err_hex,
                "fill": _role_qcolor(err_hex, 40),  # error 派生淡底（禁内联 hex）
                "anchors": [(0.5, 0), (0.5, 1)],
            },
        )
        self.plot_widget.addItem(self.analysis_cursor)
        self.analysis_cursor.sigPositionChanged.connect(self._on_cursor_moved)
        self.analysis_cursor.hover_tip_callback = (
            lambda: self.tipRequested.emit("tip.shift_drag")
        )
        self._style_analysis_cursor_label()

        # 波形编辑选区（左键拖动创建； Audacity 风格）
        # CB-016-1：蓝条已移除，选区沿用 colors()["accent"] 强调角色派生，
        # 实线实心，与标注语义色肉眼可辨；禁硬编码 hex。
        sel_brush = _role_qcolor(theme.colors()["accent"], 120)
        sel_pen = _role_qcolor(theme.colors()["accent"], 255)
        self.selection_item = pg.LinearRegionItem(
            values=[0, 0],
            orientation="vertical",
            movable=False,
            brush=pg.mkBrush(sel_brush),
            pen=pg.mkPen(sel_pen, width=1.6, style=Qt.PenStyle.SolidLine),
        )
        self.selection_item.setZValue(-5)
        self.selection_item.hide()
        self.plot_widget.addItem(self.selection_item)
        self._sel_drag = False
        self._sel_anchor = 0.0
        # CB-016-1：蓝条移除后 selection 为唯一拖拽模式（_drag_mode 生命周期见 _vb_mouse_drag）
        self._drag_mode = None       # selection / None

        # 播放头（Audacity 风格：绿色三角 + 竖线）
        self.playhead = pg.InfiniteLine(
            pos=0,  # 初始隐藏（见下），定位/播放时显示；避免 pos=-1 被 autoRange 撑出负刻度
            angle=90,
            pen=pg.mkPen(color=theme.TOKENS["semantic"]["success"], width=4.5),
            label="▶",
            labelOpts={
                "position": 0.02,
                "color": theme.TOKENS["semantic"]["success"],
                "fill": None,
                "anchors": [(0, 0.5), (1, 0.5)],
            },
        )
        self.plot_widget.addItem(self.playhead)
        self.playhead.hide()  # 空态隐藏：不参与 autoRange，时间轴不出现负刻度

        # H7：底轴原始刻度长度（空态置 0 由 _apply_empty_state 恢复真值）
        try:
            self._axis_tick_len = int(
                self.plot_widget.getPlotItem().getAxis("bottom").style["tickLength"]
            )
        except Exception:  # noqa: BLE001 — 度量失败退默认（pyqtgraph 默认 -5）
            self._axis_tick_len = 5
        self._empty_state = True

        self._times = np.array([])
        self._data = np.array([])
        self._sample_rate = 44100.0
        self._frame_size = 1.0  # FFT 帧大小（秒）
        self._live_x0 = None    # 非 None 表示录音滚动模式

        # 回调：指针位置变化时触发
        self.position_changed_callback: Optional[Callable[[float], None]] = None

        # ------ 标注系统 ------
        from acouscope.annotation import AnnotationModel
        self._annotations = AnnotationModel()
        self._region_items: dict[int, object] = {}  # id(region) -> LinearRegionItem
        self._instant_items: dict[int, object] = {}  # id(instant) -> InfiniteLine
        self._selected_region = None
        self._selected_instant = None

        # 右键菜单
        self.plot_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plot_widget.customContextMenuRequested.connect(self._on_context_menu)

        # 场景事件过滤器：仅 scrub 播放使用
        self.plot_widget.scene().installEventFilter(self)

        # ViewBox 交互补丁（pyqtgraph 自 Python 侧分发事件，
        # 实例属性补丁是其标准的自定义交互方式）：
        # 左键拖动建选区 / 单击定位播放头 / 双击全选
        vb = self.plot_widget.plotItem.vb
        self._vb_orig_drag = vb.mouseDragEvent
        self._vb_orig_click = vb.mouseClickEvent
        vb.mouseDragEvent = self._vb_mouse_drag
        vb.mouseClickEvent = self._vb_mouse_click
        self._last_click_at = 0.0
        self._last_click_pos = -1e9

        # 区域选中回调（供外部用于循环播放等）
        self.region_selected_callback: Optional[Callable[[Optional[object]], None]] = None
        self.loop_request_callback: Optional[Callable[[bool, Optional[object]], None]] = None

        # 波形显示归一化
        self._normalized = False
        self._original_data: Optional[np.ndarray] = None
        self._original_times: Optional[np.ndarray] = None

        # Scrub 播放状态
        self._scrubbing = False
        self._scrub_position = 0.0

        # H7：构造即空态——不画时间轴刻度、不显示任何游标（见 _apply_empty_state）
        self._apply_empty_state(True)

    # ------------------------------------------------------------------
    # 空态呈现（H7）：无音频时不出现「假时间轴 + 游标」
    # ------------------------------------------------------------------

    def _apply_empty_state(self, empty: bool) -> None:
        """空态/载入态切换：时间轴刻度与分析游标随之隐藏/恢复。

        空态（未载入音频）此前仍画 0–0.5 s 时间轴刻度与一条红针竖线，观感等于
        「已有数据」。现按数据有无统一切换：空态 `showValues=False` +
        `tickLength=0`（轴标题与网格保留），游标（播放头 + 分析针）一并隐藏；
        载入后逐项恢复原样式。幂等、绝不外抛。
        """
        self._empty_state = bool(empty)
        try:
            axis = self.plot_widget.getPlotItem().getAxis("bottom")
            if axis is not None:
                if empty:
                    axis.setStyle(showValues=False, tickLength=0)
                else:
                    axis.setStyle(
                        showValues=True, tickLength=getattr(self, "_axis_tick_len", 5)
                    )
                axis.update()
        except Exception:  # noqa: BLE001 — 呈现切换永不抛
            pass
        for item in (
            getattr(self, "playhead", None),
            getattr(self, "analysis_cursor", None),
        ):
            if item is None:
                continue
            try:
                item.setVisible(not empty)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 标注 API
    # ------------------------------------------------------------------

    @property
    def annotations(self):
        """标注模型（可直接操作添加/删除）。"""
        return self._annotations

    def set_annotation_model(self, model):
        """设置共享标注模型（用于多视图同步）。"""
        self._annotations = model
        self._redraw_annotations()

    def add_region(self, start: float, end: float, label: str = "",
                   color: Optional[str] = None):
        """添加一个区域标注。"""
        region = self._annotations.add_region(start, end, label, color)
        self._add_region_item(region)
        return region

    def add_instant(self, time: float, label: str = "",
                    color: Optional[str] = None):
        """添加一个时间点标注。"""
        inst = self._annotations.add_instant(time, label, color)
        self._add_instant_item(inst)
        return inst

    # T-325 播放中打点（Pγ）：为已落点补文本 + 撤销上一打点（光标不停顿语义在 main_window）
    def prompt_instant_label(self, inst, anchor: Optional[QPoint] = None):
        """为已落时间点弹标签输入 popover（非模态，不打断播放）。

        回车/失焦提交 → 更新该点文本；Esc/取消 → 保留原样（纯点不丢）。
        """
        if anchor is None:
            anchor = self._playhead_anchor(float(inst.time))
        self._show_label_editor(
            lambda label: self._relabel_instant(inst, label), anchor)

    def delete_instant(self, inst):
        """删除指定时间点（撤销最近打点入口，仅删该对象）。"""
        self._delete_instant(inst)

    def _relabel_instant(self, inst, label: str):
        """更新已打点文本并重建其渲染 item。

        经模型 remove+add 重建以触发 T-322 脏标记监听（禁直接改 label 而漏保存）；
        时间与颜色保留，item 重建后视觉一致。
        """
        if inst.label == label:
            return
        t, color = inst.time, inst.color
        self._annotations.remove_instant(inst)
        new_inst = self._annotations.add_instant(t, label, color)
        item = self._instant_items.pop(id(inst), None)
        if item is not None:
            self.plot_widget.removeItem(item)
        self._add_instant_item(new_inst)

    def _playhead_anchor(self, t: float) -> QPoint:
        """把数据坐标时间 t 映射为波形视图内水平锚点（popover 就近弹出、钳位可视）。"""
        try:
            from PyQt6.QtCore import QPointF
            sp = self.plot_widget.plotItem.vb.mapViewToScene(QPointF(t, 0))
            x = int(self.plot_widget.mapFromScene(sp).x())
            edge = theme.TOKENS["spacing"]["xs"]
            w = self.plot_widget.width()
            if w > 2 * edge:
                x = max(edge, min(w - edge, x))
            else:
                x = w // 2
            return QPoint(x, 0)
        except Exception:
            return QPoint(self.plot_widget.width() // 2, 0)

    def clear_regions(self):
        for item in list(self._region_items.values()):
            self.plot_widget.removeItem(item)
        self._region_items.clear()
        self._annotations.clear_regions()
        self._selected_region = None

    def clear_instants(self):
        for item in list(self._instant_items.values()):
            self.plot_widget.removeItem(item)
        self._instant_items.clear()
        self._annotations.clear_instants()
        self._selected_instant = None

    def selected_region(self):
        """当前选中的「标注区域对象」（AnnotationRegion），无选中时 None。

        T-1019 类型契约：本 getter 返回**对象**（含 .start_time/.end_time），
        语义为「标注区域」，仅供试听/循环/打点等标注链路使用；
        **不得**传给分析槽当 region（分析槽只收元组/None）。
        分析区间请用 get_selection() —— 两者刻意解耦，勿混用。
        """
        return self._selected_region

    def _redraw_annotations(self):
        """全部重绘标注。"""
        # 清除旧的
        for item in self._region_items.values():
            self.plot_widget.removeItem(item)
        for item in self._instant_items.values():
            self.plot_widget.removeItem(item)
        self._region_items.clear()
        self._instant_items.clear()
        # 重建
        for region in self._annotations.regions:
            self._add_region_item(region)
        for inst in self._annotations.instants:
            self._add_instant_item(inst)

    def _add_region_item(self, region):
        """创建区域的可视化 item。"""
        color = region.color
        item = pg.LinearRegionItem(
            values=[region.start_time, region.end_time],
            orientation="vertical",
            brush=pg.mkBrush(color=color + "40"),  # 25% 透明
            pen=pg.mkPen(color=color, width=3.3),
            movable=True,
        )
        # 关联数据
        item._sv_region = region
        item.sigRegionChanged.connect(lambda i, r=region: self._on_region_dragged(r, i))
        self.plot_widget.addItem(item)
        self._region_items[id(region)] = item

    def _add_instant_item(self, inst):
        """创建时间点的可视化 item。"""
        color = inst.color
        item = pg.InfiniteLine(
            pos=inst.time,
            angle=90,
            movable=True,
            pen=pg.mkPen(color=color, width=3.3, style=Qt.PenStyle.DashLine),
            label=inst.label if inst.show_label and inst.label else "",
            labelOpts={
                "position": 0.05,
                "color": color,
                "fill": theme.colors()["input"],
                "anchors": [(0.5, 0), (0.5, 1)],
            },
        )
        item._sv_instant = inst
        item.sigPositionChanged.connect(lambda i, ins=inst: self._on_instant_dragged(ins, i))
        self.plot_widget.addItem(item)
        self._instant_items[id(inst)] = item

    def _on_region_dragged(self, region, item):
        """区域被拖动时更新数据。"""
        values = item.getRegion()
        region.start_time = float(values[0])
        region.end_time = float(values[1])
        self._selected_region = region
        if self.region_selected_callback:
            self.region_selected_callback(region)

    def _on_instant_dragged(self, inst, item):
        """时间点被拖动时更新数据。"""
        inst.time = float(item.value())

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos: QPoint):
        """右键菜单：添加标注。"""
        # 转为数据坐标
        scene_pos = self.plot_widget.mapToScene(pos)
        view_pos = self.plot_widget.plotItem.vb.mapSceneToView(scene_pos)
        click_time = float(view_pos.x())

        menu = QMenu(self)

        # T-915：「分析此区域」= 菜单第一项，仅当存在选区时出现
        if self.get_selection() is not None:
            act_analyze = QAction(tr("ctx.analyze_region"), self)
            act_analyze.triggered.connect(self._on_analyze_region)
            menu.addAction(act_analyze)
            menu.addSeparator()

        act_add_region = QAction("添加区域标注", self)
        # QTimer.singleShot(0, ...)：待 QMenu.exec 收栈后再弹 popover，
        # 避免在菜单 popup grab 期间再开第二个 popup 被 Qt 立即关闭
        act_add_region.triggered.connect(
            lambda: QTimer.singleShot(
                0, lambda: self._add_region_at(click_time, pos))
        )
        menu.addAction(act_add_region)

        act_add_instant = QAction("添加时间点标注", self)
        act_add_instant.triggered.connect(
            lambda: QTimer.singleShot(
                0, lambda: self._add_instant_at(click_time, pos))
        )
        menu.addAction(act_add_instant)

        menu.addSeparator()

        # 如果点击位置有区域/时间点，添加删除选项
        region_near = self._annotations.find_region_at(click_time)
        if region_near is None:
            region_near = self._annotations.find_region_near(click_time, 0.02)
        if region_near:
            act_del_region = QAction(f"删除区域「{region_near.label}」", self)
            act_del_region.triggered.connect(lambda: self._delete_region(region_near))
            menu.addAction(act_del_region)

            act_play_region = QAction(f"循环播放「{region_near.label}」", self)
            act_play_region.triggered.connect(
                lambda: self._loop_play_region(region_near))
            menu.addAction(act_play_region)

        inst_near = self._annotations.find_instant_near(click_time, 0.02)
        if inst_near:
            act_del_inst = QAction(f"删除时间点「{inst_near.label}」", self)
            act_del_inst.triggered.connect(lambda: self._delete_instant(inst_near))
            menu.addAction(act_del_inst)

        menu.addSeparator()

        act_clear_all = QAction("清除全部标注", self)
        act_clear_all.triggered.connect(self._clear_all_annotations)
        menu.addAction(act_clear_all)

        menu.addSeparator()

        act_norm = QAction("归一化显示（0dB 峰值）", self)
        act_norm.setCheckable(True)
        act_norm.setChecked(self._normalized)
        act_norm.triggered.connect(lambda c: self.set_normalized(c))
        menu.addAction(act_norm)

        menu.exec(self.plot_widget.mapToGlobal(pos))

    def _on_analyze_region(self) -> None:
        """T-915：右键「分析此区域」→ 发 analyzeRegionRequested(t0, t1)。

        本方法只发信号，不做任何分析重算/绘图（消费方在 T-916 主窗侧）。
        """
        sel = self.get_selection()
        if sel is None:
            return
        self.analyzeRegionRequested.emit(float(sel[0]), float(sel[1]))

    def _add_region_at(self, t: float, anchor: Optional[QPoint] = None):
        """右键「添加区域标注」：原位非模态输入标签，提交后才创建区域。

        标签输入只改模态形态（原生模态输入 → Qt.Popup popover）；
        区域创建仍由用户右键菜单手动触发；数据结构与其他行为零改动。
        """
        def commit(label: str):
            dur = 0.5
            if len(self._times) > 0:
                total = self._times[-1] - self._times[0]
                dur = max(0.1, total * 0.05)
            start = max(0, t - dur / 2)
            end = t + dur / 2
            if len(self._times) > 0:
                end = min(end, float(self._times[-1]))
            region = self.add_region(start, end, label.strip())
            self._selected_region = region
            if self.region_selected_callback:
                self.region_selected_callback(region)
        self._show_label_editor(commit, anchor)

    def _add_instant_at(self, t: float, anchor: Optional[QPoint] = None):
        """右键「添加时间点标注」：同 _add_region_at 口径（非模态标签输入）。"""
        self._show_label_editor(
            lambda label: self.add_instant(t, label.strip()), anchor)

    def _show_label_editor(self, commit: Callable[[str], None],
                           anchor: Optional[QPoint] = None):
        """弹出标注标签输入 popover（非模态；同一时刻仅保留一个）。"""
        pop = getattr(self, "_label_popover", None)
        if pop is not None:
            pop._cancel()
        pop = _LabelPopover(self)
        pop.committed.connect(commit)
        pop.committed.connect(lambda _label: self._on_label_editor_closed(pop))
        pop.cancelled.connect(lambda: self._on_label_editor_closed(pop))
        self._label_popover = pop
        if anchor is None:
            anchor = QPoint(self.plot_widget.width() // 2, 0)
        pop.present(self.plot_widget.mapToGlobal(anchor))

    def _on_label_editor_closed(self, pop):
        """popover 提交/取消后清引用（pop 是当前 editor 才清）。"""
        if getattr(self, "_label_popover", None) is pop:
            self._label_popover = None

    def _delete_region(self, region):
        item = self._region_items.pop(id(region), None)
        if item:
            self.plot_widget.removeItem(item)
        self._annotations.remove_region(region)
        if self._selected_region is region:
            self._selected_region = None
            if self.region_selected_callback:
                self.region_selected_callback(None)

    def _delete_instant(self, inst):
        item = self._instant_items.pop(id(inst), None)
        if item:
            self.plot_widget.removeItem(item)
        self._annotations.remove_instant(inst)

    def _clear_all_annotations(self):
        self.clear_regions()
        self.clear_instants()
        if self.region_selected_callback:
            self.region_selected_callback(None)

    def _loop_play_region(self, region):
        """请求循环播放指定区域（通过回调通知主窗口）。"""
        self._selected_region = region
        if self.region_selected_callback:
            self.region_selected_callback(region)
        if self.loop_request_callback:
            self.loop_request_callback(True, region)

    # ------------------------------------------------------------------
    # 波形归一化显示
    # ------------------------------------------------------------------

    def _apply_ink(self) -> None:
        """数据墨色（T-1038 M1/M6）：波形主轨迹与零线随主题骨架取色。"""
        self.curve.setPen(pg.mkPen(color=theme.data_ink("trace"), width=1.8))
        self.zero_line.setPen(pg.mkPen(
            color=theme.data_ink("ref_line"), width=0.5,
            style=Qt.PenStyle.DashLine))

    def _on_canvas_theme(self):
        """主题切换：重设波形画布底色与轴/网格色 + 数据墨色。"""
        _apply_canvas_theme(self.plot_widget)
        self._apply_ink()
        self.plot_widget.update()

    def _refresh_toolbutton_qss(self):
        """按当前主题重设工具/缩放按钮 QSS（注册到 theme.on_theme_change）。"""
        c = theme.colors()
        tb = _tb_btn_qss(c)
        tool = _tool_btn_qss(c)
        for b in (self.btn_zoom_in, self.btn_zoom_out, self.btn_zoom_fit):
            b.setStyleSheet(tb)
        for b in (self.btn_scrub, self.btn_normalize, self.btn_trim_silence):
            b.setStyleSheet(tool)
        # G9：已开启态由 _tool_btn_qss 的 QPushButton:checked 规则表达（accent 底
        # + accent_text 字），不再另设一套 success 绿色局部样式（那会与主题令牌
        # 的双态语义打架，且按钮无勾选态可读）。

    def _sync_normalize_button(self, normalized: bool) -> None:
        """G9：按钮勾选态 ← 归一化实际状态（blockSignals 防 clicked 回环）。"""
        btn = getattr(self, "btn_normalize", None)
        if btn is None or btn.isChecked() == bool(normalized):
            return
        btn.blockSignals(True)
        btn.setChecked(bool(normalized))
        btn.blockSignals(False)

    def toggle_normalize(self):
        """切换归一化显示（按钮勾选态即状态源，G9）。"""
        self.set_normalized(self.btn_normalize.isChecked())

    def set_normalized(self, normalized: bool):
        """设置波形是否归一化显示（峰值 = 1.0 / 0 dB）；按钮勾选态双向同步。"""
        normalized = bool(normalized)
        # 先同步按钮（含「数据为空时仅回填勾选态」的路径），再做数据换算
        self._sync_normalize_button(normalized)
        if normalized == self._normalized:
            return
        self._normalized = normalized
        if self._original_data is None:
            return
        if normalized:
            peak = np.max(np.abs(self._original_data))
            if peak > 0:
                self._data = self._original_data / peak
            else:
                self._data = self._original_data
        else:
            self._data = self._original_data
        self._update_display_curve()

    # ------------------------------------------------------------------
    # 显示降采样（长文件防卡死）
    # ------------------------------------------------------------------

    _DISPLAY_BUDGET = 200_000  # 曲线显示点预算（min/max 对）

    @classmethod
    def _decimate_envelope(cls, times, data):
        """峰值包络降采样：保留波形外观，渲染点数封顶。"""
        n = len(data)
        if n <= cls._DISPLAY_BUDGET:
            return times, data
        step = max(2, int(np.ceil(n / (cls._DISPLAY_BUDGET // 2))))
        m = (n // step) * step
        d = data[:m].reshape(-1, step)
        y = np.empty(2 * (m // step), dtype=np.float32)
        y[0::2] = d.min(axis=1)
        y[1::2] = d.max(axis=1)
        t = times[:m].reshape(-1, step).mean(axis=1)
        x = np.empty_like(y)
        x[0::2] = t
        x[1::2] = t
        return x, y

    def _update_display_curve(self):
        """用降采样后的数据更新曲线（_data 保持全分辨率供 Scrub 用）。"""
        x, y = self._decimate_envelope(self._times, self._data)
        self.curve.setData(x, y)

    def is_normalized(self) -> bool:
        return self._normalized

    # ------------------------------------------------------------------
    # Scrub 播放（Audacity 风格）
    # ------------------------------------------------------------------

    def _on_scrub_toggled(self, checked: bool):
        """切换 Scrub 模式（事件过滤器常驻，无需装卸）。"""
        if checked:
            self.btn_scrub.setText("⟿ Scrub ON")
        else:
            self.btn_scrub.setText("⟿ Scrub")
            self._stop_scrub()

    def eventFilter(self, obj, event):
        """捕获场景鼠标事件实现 scrub 播放（选区/定位走 ViewBox 补丁）。"""
        if not self.btn_scrub.isChecked():
            return super().eventFilter(obj, event)

        etype = event.type()
        if etype == event.Type.GraphicsSceneMousePress:
            self._start_scrub(event.scenePos())
        elif etype == event.Type.GraphicsSceneMouseMove and self._scrubbing:
            self._update_scrub(event.scenePos())
        elif etype == event.Type.GraphicsSceneMouseRelease:
            self._stop_scrub()

        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # ViewBox 交互补丁：拖动建选区 / 单击定位播放头 / 双击全选
    # （pyqtgraph 只在无前景图元接受按压时才把事件交给 ViewBox，
    #  因此无需再做图元命中判断）
    # ------------------------------------------------------------------

    def _scene_t(self, scene_pos) -> float:
        """场景坐标 → 时间（秒），并夹取到数据范围。"""
        vb = self.plot_widget.plotItem.vb
        t = float(vb.mapSceneToView(scene_pos).x())
        return self._clamp_t(t)

    def _duration(self) -> float:
        """音频时长（秒），降采样/非降采样两形态均安全。

        禁用"点数÷原始采样率"：峰值降采样后点数≪原始样本数，会把时长
        误算成 10000/44100≈0.227s（CB-016 P3 回归，交互全被钳在开头
        0.227s）。按 step=round(dt*sr)（dt=前两时间戳间隔）判别形态：
        - 非降采样（step≤1）：n/sr，float64 精确（times 存 float32，
          times[-1]+dt 有精度误差 5.0000000725≠5.0）；
        - 降采样（step>1）：times 跨全时长，= times[-1]+dt。
        """
        if self._times.size >= 2:
            dt = float(self._times[1] - self._times[0])
            step = int(round(dt * float(self._sample_rate))) if dt > 0 else 1
            if step <= 1:
                return float(self._times.size) / float(self._sample_rate)
            return float(self._times[-1]) + dt
        if self._times.size == 1:
            return float(self._times[0]) + 1.0 / float(self._sample_rate)
        return 0.0

    def _clamp_t(self, t: float) -> float:
        """夹取到 [起始, 数据时长]（时长判定见 _duration）。"""
        if self._times.size:
            duration = self._duration()
            t = max(float(self._times[0]), min(t, duration))
        return t

    def _wave_interaction_enabled(self) -> bool:
        """有数据且不在录音滚动模式时才允许选区/定位交互。"""
        return self._times.size > 0 and self._live_x0 is None

    def _view_span(self) -> float:
        return float(self.plot_widget.viewRange()[0][1] -
                     self.plot_widget.viewRange()[0][0])

    def _vb_mouse_drag(self, ev, axis=None):
        """左键拖动：建选区（Audacity 行为；蓝条移除后 selection 为唯一模式）。

        axis 参数由 pyqtgraph AxisItem.mouseDragEvent 传入（拖时间轴/刻度区）：
        非 None 时直接委托原 ViewBox 单轴缩放/平移，不进波形选区/定位逻辑。
        CB-016b（事件语义修复）：pyqtgraph 仅对 press 后产生真实拖动的序列把
        release 派发到本方法（DragEvent，isFinish() 为合法 API）；拖选 finish
        置 _drag_mode=None，再按幅度分支——微拖当单击定位播放头 / 真拖建选区
        发 selectionChanged。拖选 release 后 pyqtgraph 不再派发尾随 click，旧
        吞噬 flag 机制（残留会吞掉下一次真单击）已删除，见 _vb_mouse_click。
        """
        if axis is not None:
            return self._vb_orig_drag(ev, axis=axis)
        if (ev.button() == Qt.MouseButton.LeftButton
                and self._wave_interaction_enabled()):
            ev.accept()
            t = self._scene_t(ev.scenePos())

            if ev.isStart():
                self._drag_mode = "selection"
                self._sel_anchor = self._scene_t(ev.buttonDownScenePos())
                self.selection_item.setRegion([self._sel_anchor, self._sel_anchor])
                self.selection_item.show()

            lo, hi = sorted((self._sel_anchor, t))
            self.selection_item.setRegion([lo, hi])
            if ev.isFinish():
                self._drag_mode = None
                if hi - lo < self._view_span() * 0.004:
                    # tiny drag = 当作单击：定位播放头
                    self.clear_selection()
                    self.playhead.setPos(t)
                    self.playhead.show()
                    self.playheadSeek.emit(t)
                else:
                    self.selectionChanged.emit((lo, hi))
                    self.tipRequested.emit("tip.selection")
            return
        self._vb_orig_drag(ev)

    def _vb_mouse_click(self, ev):
        """左键单击：定位播放头；快速双击：全选。

        CB-016b（事件语义修复，架构师探针实证）：pyqtgraph 仅在一次左键
        press 无拖动的 release 派发单个 mouseClickEvent——press/release 并不
        各合成一次，且 MouseClickEvent 无 DragEvent 的 finish 判定 API（旧
        守卫每个单击都抛 AttributeError，被 pyqtgraph sendClickEvent 的
        try/except 吞掉，致单击/双击全废）。拖选序列的 finish 走
        mouseDragEvent，release 不再派发尾随 click，故无需吞噬 flag（旧 flag
        残留会吞掉下一次真单击）。单击=定位播放头+清选区；双击沿用
        0.35s+视宽 1% 判定（两次单击事件对同位置、时间窗内）→ 全选。
        """
        if (ev.button() == Qt.MouseButton.LeftButton
                and self._wave_interaction_enabled()):
            ev.accept()
            t = self._scene_t(ev.scenePos())
            now = time.monotonic()
            is_double = (now - self._last_click_at < 0.35
                         and abs(t - self._last_click_pos)
                         < self._view_span() * 0.01)
            self._last_click_at = now
            self._last_click_pos = t

            if is_double:
                # 上界=全时长（降采样安全，见 _duration；点数÷采样率会误算）
                self.set_selection(float(self._times[0]), self._duration())
                self.tipRequested.emit("tip.dbl_select_all")
                return

            self.clear_selection(emit=True)
            self.playhead.setPos(t)
            self.playhead.show()
            self.playheadSeek.emit(t)
            return
        self._vb_orig_click(ev)

    # 选区 API -------------------------------------------------------

    def set_selection(self, t0: float, t1: float) -> None:
        """设置选区（自动排序与夹取）。"""
        if not self._times.size:
            return
        t0 = self._clamp_t(t0)
        t1 = self._clamp_t(t1)
        lo, hi = sorted((t0, t1))
        self.selection_item.setRegion([lo, hi])
        self.selection_item.show()
        self.selectionChanged.emit((lo, hi))

    def clear_selection(self, emit: bool = True) -> None:
        if not self.selection_item.isVisible() and not emit:
            return
        self._sel_drag = False
        self.selection_item.hide()
        if emit:
            self.selectionChanged.emit(None)

    def get_selection(self):
        """当前分析选区 (t0, t1)，无选区时 None。

        T-1019 类型契约：返回 ``tuple[float, float] | None``，即分析槽 region
        的**唯一**合法来源（_on_fft/spectrogram/pitch/formant/timbre/3D 的
        region 实参口径）；与 selected_region()（标注区域对象）刻意解耦。
        """
        if not self.selection_item.isVisible():
            return None
        lo, hi = self.selection_item.getRegion()
        if hi - lo <= 0:
            return None
        return (float(lo), float(hi))

    def get_playhead_time(self) -> float:
        return max(0.0, float(self.playhead.value()))

    # 缩放 -----------------------------------------------------------

    def _zoom_by(self, factor: float) -> None:
        if not self._times.size:
            return
        (x0, x1) = self.plot_widget.viewRange()[0]
        # 以播放头为中心缩放（若可见），否则以视图中心
        center = (x0 + x1) / 2.0
        if self.playhead.isVisible():
            ph = float(self.playhead.value())
            if x0 <= ph <= x1:
                center = ph
        half = max((x1 - x0) / 2.0 * factor, 1e-3)
        self.plot_widget.setXRange(center - half, center + half, padding=0)

    def zoom_in(self):
        self._zoom_by(0.6)

    def zoom_out(self):
        self._zoom_by(1 / 0.6)

    def zoom_fit(self):
        if self._times.size:
            self.plot_widget.setXRange(
                float(self._times[0]), float(self._times[-1]), padding=0
            )

    def zoom_to_selection(self):
        sel = self.get_selection()
        if sel:
            self.plot_widget.setXRange(sel[0], sel[1], padding=0.02)

    def _on_scrollbar_changed(self, value):
        """滚动条 → 视图位置同步。"""
        times = getattr(self, "_times", None)
        if times is None or not times.size:
            return
        x0, x1 = self.plot_widget.viewRange()[0]
        span = x1 - x0
        t_max = float(times[-1])
        t_min = float(times[0])
        if t_max - t_min > span:
            new_x0 = t_min + (value / 1000.0) * (t_max - t_min - span)
            self.plot_widget.setXRange(new_x0, new_x0 + span, padding=0)

    def _update_scrollbar(self):
        """视图范围 → 滚动条位置同步（防反馈环）。"""
        times = getattr(self, "_times", None)
        if times is None or not times.size:
            return
        x0, x1 = self.plot_widget.viewRange()[0]
        span = x1 - x0
        t_max = float(times[-1])
        t_min = float(times[0])
        if t_max - t_min > span:
            ratio = (x0 - t_min) / max(t_max - t_min - span, 1e-6)
            ratio = max(0.0, min(1.0, ratio))
        else:
            ratio = 0.0
        self.scrollbar.blockSignals(True)
        self.scrollbar.setValue(int(ratio * 1000))
        self.scrollbar.blockSignals(False)

    def _start_scrub(self, scene_pos):
        """开始 scrub 播放。"""
        if self._data is None or len(self._data) == 0:
            return
        self._scrubbing = True
        self._scrub_position = 0.0
        # 使用定时器触发小块播放
        if not hasattr(self, "_scrub_timer"):
            self._scrub_timer = QTimer(self)
            self._scrub_timer.timeout.connect(self._scrub_tick)
        self._scrub_timer.start(50)  # 20 FPS

    def _update_scrub(self, scene_pos):
        """更新 scrub 位置。"""
        # 将场景坐标转换为视图坐标再映射到时间
        viewbox = self.plot_widget.plotItem.vb
        try:
            t = viewbox.mapSceneToView(scene_pos).x()
            self._scrub_position = max(0.0, min(t, float(self._times[-1])))
        except Exception:
            pass

    def _scrub_tick(self):
        """scrub 定时器回调：播放一小段音频。"""
        if not self._scrubbing or self._data is None:
            return
        # 播放一小段（约 50ms）
        from acouscope.audio.player import AudioPlayer
        if not hasattr(self, "_scrub_player"):
            self._scrub_player = AudioPlayer()
        pos_samples = int(self._scrub_position * self._sample_rate)
        chunk_samples = int(self._sample_rate * 0.05)  # 50ms
        start = max(0, pos_samples)
        end = min(len(self._data), start + chunk_samples)
        if end > start:
            chunk = self._data[start:end].copy()
            self._scrub_player.load(chunk, int(self._sample_rate))
            self._scrub_player.play()

    def _stop_scrub(self):
        """停止 scrub 播放。"""
        self._scrubbing = False
        if hasattr(self, "_scrub_timer") and self._scrub_timer.isActive():
            self._scrub_timer.stop()
        if hasattr(self, "_scrub_player"):
            self._scrub_player.stop()

    # ------------------------------------------------------------------
    # 原有 API（保持兼容）
    # ------------------------------------------------------------------

    def set_data(
        self,
        times: np.ndarray,
        data: np.ndarray,
        sample_rate: float = 44100.0,
    ):
        """设置波形数据。

        注意：不复制大数组（长录音可达数亿字节）——本类从不原地修改
        data/times，只整体重绑定；如需修改请先复制。
        """
        self._original_times = times
        self._original_data = data
        self._sample_rate = sample_rate

        # 显示层统一 float32（半内存，精度对显示/分析足够）；
        # 已是 float32 时零复制
        data32 = np.asarray(data, dtype=np.float32)
        if self._normalized:
            peak = float(np.max(np.abs(data32))) if data32.size else 0.0
            self._data = data32 / peak if peak > 0 else data32
        else:
            self._data = data32

        self._times = np.asarray(times, dtype=np.float32)
        self._live_x0 = None
        self._live_x1 = None
        self.clear_selection(emit=True)

        if len(times) > 0:
            self._update_display_curve()
            # 限制视图不可平移到数据范围外（防 0 刻度左侧空白）
            vb = self.plot_widget.plotItem.vb
            vb.setLimits(
                xMin=float(times[0]),
                xMax=float(times[-1]),
            )
            self.plot_widget.setXRange(times[0], times[-1], padding=0)
            # H7：载入数据 → 恢复时间轴刻度与游标
            self._apply_empty_state(False)
            self.playhead.setPos(0.0)
            self.playhead.show()
            self._update_scrollbar()

            # 初始化分析指针到中间位置
            mid_time = times[len(times) // 2]
            self.set_analysis_position(mid_time, emit=False)

        # G9：打开/切换文件后按当前归一化状态回填按钮勾选态（显示态不随文件丢失）
        self._sync_normalize_button(self._normalized)

    def set_frame_size(self, frame_size_seconds: float):
        """设置分析帧宽（秒）。蓝条移除后仅存续状态，供检查器读数/3D 驱动。"""
        self._frame_size = max(0.01, frame_size_seconds)

    def get_frame_size(self) -> float:
        """当前分析帧宽（秒）；CB-016-3 检查器 / CB-016-4 3D 段取帧来源。"""
        return float(self._frame_size)

    def set_analysis_position(self, position: float, emit: bool = True):
        if len(self._times) == 0:
            return
        position = max(self._times[0], min(position, self._times[-1]))
        if not emit:
            self.analysis_cursor.sigPositionChanged.disconnect(self._on_cursor_moved)
        self.analysis_cursor.setPos(position)
        if not emit:
            self.analysis_cursor.sigPositionChanged.connect(self._on_cursor_moved)

    def get_analysis_position(self) -> float:
        return float(self.analysis_cursor.value())

    def _style_analysis_cursor_label(self):
        """红针 Label 醒目化（CB-016-2）：文本项字体加粗/放大。

        防御式：pyqtgraph LabelItem 内部结构跨版本容错，结构不符时静默跳过，
        不影响任何既有行为（本方法被构造期与每次 _on_cursor_moved 调用）。
        """
        label = getattr(self.analysis_cursor, "label", None)
        if label is None:
            return
        text_item = getattr(label, "item", None)
        if text_item is None or not hasattr(text_item, "font"):
            return
        try:
            font = text_item.font()
            font.setBold(True)
            ps = font.pointSizeF()
            if ps > 0:
                font.setPointSizeF(max(ps, 11.0) + 1.0)
            else:
                font.setPixelSize(15)
            text_item.setFont(font)
        except Exception:
            pass

    def _on_cursor_moved(self, line):
        pos = float(line.value())
        if len(self._times) > 0:
            pos = max(self._times[0], min(pos, self._times[-1]))
            line.setPos(pos)
        line.label.setText(f"{pos:.3f} s")
        self._style_analysis_cursor_label()
        # CB-016-3：红针移动 → 分析位置信号（与既有 position_changed_callback 并存）
        self.analysisPositionChanged.emit(pos)
        if self.position_changed_callback:
            self.position_changed_callback(pos)

    def set_playhead(self, position: float):
        self.playhead.setPos(position)
        self.playhead.show()

    # ------------------------------------------------------------------
    # 录音实时显示（Audacity 架构：定长环形缓冲 + 分段降采样，
    # 渲染成本与录音时长无关）
    # ------------------------------------------------------------------

    _LIVE_WINDOW_S = 30.0     # 实时滚动窗宽度
    _LIVE_ENV_POINTS = 4000   # 包络降采样 min/max 对预算
    _RING_SECONDS = 32.0      # 环形缓冲容量（略大于显示窗）

    def begin_live_capture(self, sample_rate: float):
        """开始实时采集显示（清空曲线，进入滚动模式）。"""
        self._live_sr = float(sample_rate)
        cap = int(self._live_sr * self._RING_SECONDS) + 4096
        self._ring = np.zeros(cap, dtype=np.float32)
        self._ring_n = 0       # 已写入总采样数（绝对计数）
        self._ring_pos = 0     # 写游标（环内位置）
        self.curve.setData([], [])
        # H7：录音进实时模式 = 有数据流 → 恢复时间轴刻度与游标
        self._apply_empty_state(False)
        self.playhead.setPos(0.0)
        self.playhead.show()
        self._live_x0 = 0.0
        self._live_x1 = self._LIVE_WINDOW_S
        self.plot_widget.setXRange(0.0, self._LIVE_WINDOW_S, padding=0)

    def append_live_chunk(self, chunk: np.ndarray):
        """把采集块写入环形缓冲（O(块长)，与已录时长无关）。"""
        ring = getattr(self, "_ring", None)
        if ring is None:
            return
        c = np.asarray(chunk, dtype=np.float32).ravel()
        n = len(c)
        cap = len(ring)
        i = 0
        while i < n:
            space = min(n - i, cap - self._ring_pos)
            ring[self._ring_pos:self._ring_pos + space] = c[i:i + space]
            self._ring_pos += space
            if self._ring_pos >= cap:
                self._ring_pos = 0
            i += space
        self._ring_n += n

    def refresh_live(self):
        """绘制滚动窗尾部波形：环内切片 → 分段降采样 → 拼接小数组。"""
        ring = getattr(self, "_ring", None)
        if ring is None or self._ring_n == 0:
            return

        sr = self._live_sr
        total = self._ring_n
        dur = total / sr
        win = min(self._LIVE_WINDOW_S, max(dur, 1.0))
        start_s = max(0.0, dur - win)
        a = max(int(start_s * sr), total - len(ring))  # 钳到环内实际内容
        total_n = total - a

        step = max(1, total_n // self._LIVE_ENV_POINTS + 1)
        xs: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        for piece_start, piece in self._ring_slices(a, total):
            tx, ty = self._decimate_piece(piece, piece_start, step)
            if len(tx):
                xs.append(tx)
                ys.append(ty)
        if xs:
            self.curve.setData(np.concatenate(xs), np.concatenate(ys))

        # 范围/文本未变时跳过重排与重绘请求（30fps 下省一半以上无效工作）
        x0, x1 = start_s, start_s + win
        if getattr(self, "_live_x0", None) != x0 or getattr(self, "_live_x1", None) != x1:
            self._live_x0, self._live_x1 = x0, x1
            self.plot_widget.setXRange(x0, x1, padding=0)
        self.playhead.setPos(dur)

    def _ring_slices(self, a: int, b: int):
        """读绝对采样区间 [a, b)：返回 [(绝对起点, 环内切片), ...]。"""
        cap = len(self._ring)
        off = (self._ring_pos - self._ring_n) % cap
        i0 = (a + off) % cap
        i1 = (b + off) % cap
        if i0 < i1:
            return [(a, self._ring[i0:i1])]
        return [
            (a, self._ring[i0:]),
            (a + (cap - i0), self._ring[:i1]),
        ]

    def _decimate_piece(self, x: np.ndarray, abs_start: int, step: int):
        """单段峰值包络降采样。返回 (时间, min/max 交错值)。"""
        n = len(x)
        sr = self._live_sr
        if n == 0:
            return np.zeros(0), np.zeros(0)
        if step <= 1:
            return abs_start / sr + np.arange(n) / sr, x

        nblocks = n // step
        ts: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        if nblocks:
            d = x[: nblocks * step].reshape(nblocks, step)
            t = abs_start / sr + (np.arange(nblocks) + 0.5) * step / sr
            y = np.empty(2 * nblocks, dtype=np.float32)
            y[0::2] = d.min(axis=1)
            y[1::2] = d.max(axis=1)
            tt = np.empty(2 * nblocks)
            tt[0::2] = t
            tt[1::2] = t
            ts.append(tt)
            ys.append(y)
        rem = n - nblocks * step
        if rem:
            seg = x[nblocks * step:]
            t = abs_start / sr + (nblocks * step + rem / 2.0) / sr
            ts.append(np.full(2, t))
            ys.append(
                np.array([seg.min(), seg.max()], dtype=np.float32)
            )
        return np.concatenate(ts), np.concatenate(ys)

    def end_live_capture(self):
        """结束实时采集（数据将由 set_data 正式载入）。"""
        self._ring = None
        self._ring_n = 0
        self._ring_pos = 0
        self._live_sr = 44100.0

    # ------------------------------------------------------------------
    # 电平显示
    # ------------------------------------------------------------------

    def set_level(self, level: float):
        """设置 VU 表电平 (0.0 ~ 1.0)。"""
        self.vu_meter.set_level(level)

    def clear(self):
        self.curve.setData([], [])
        self._times = np.array([])
        self._data = np.array([])
        self.clear_selection(emit=False)
        self.clear_regions()
        self.clear_instants()
        # H7：清空 → 回空态（时间轴刻度与游标一并收起）
        self._apply_empty_state(True)

    # ------------------------------------------------------------------
    # 析构收尾（CB-006 C2：GUI_backlog #15 偶发原生崩溃）
    #
    # 根因假设 H-A（CB-005 报告）：套件级堆/GC 析构序依赖的 pyqtgraph
    # GraphicsScene/RegionItem 析构 use-after-free。本控件析构图深
    # （QGraphicsView→scene→selection_item + analysis_cursor + zero_line +
    # playhead + curve + 标注区域/时间点），
    # 无显式收尾路径，进程近尾由 Python GC 以『不同于 Qt 场景删除顺序』
    # 回收这些 item 包装时，场景析构遍历可能触碰已半释放的 C++ 项。
    # 这里在 closeEvent 收尾路径先把本控件 addItem 的全部 scene item 移出
    # 场景，view/scene 析构时不再遍历这些项。只加收尾、不改任何事件/交互
    # 路径（右键手动触发/提交才创建/Esc 取消等语义零改动）。
    # ------------------------------------------------------------------

    def _cleanup_scene(self):
        """显式移除本控件添加进场景的全部 item（幂等、绝不外抛）。

        移除后仍保留 Python 引用（不置 None），控件外部若在 close 后读取
        这些属性（如 get_analysis_position()）不受影响；
        item 的 C++ 删除时点交由 Python 侧统一回收，消除场景析构序依赖。
        """
        plot_widget = getattr(self, "plot_widget", None)
        if plot_widget is None:
            return

        items = []
        for attr in (
            "curve",
            "zero_line",
            "analysis_cursor",
            "selection_item",
            "playhead",
        ):
            item = getattr(self, attr, None)
            if item is not None:
                items.append(item)
        # 标注区域/时间点 item（以 _region_items/_instant_items 登记为准；
        # 已被 clear_regions/clear_instants 清掉的项不在 dict 中、无需处理）
        for key in ("_region_items", "_instant_items"):
            store = getattr(self, key, None) or {}
            items.extend(list(store.values()))

        for item in items:
            try:
                plot_widget.removeItem(item)
            except RuntimeError:
                pass  # 底层 C++ 对象已析构（控件正在销毁途中）
            except Exception:
                pass  # 双移除/缺登记等一律吞掉：收尾路径绝不外抛

        # 断开本控件连到这些 item 的信号 + 移除场景事件过滤器
        try:
            ac = getattr(self, "analysis_cursor", None)
            if ac is not None:
                try:
                    ac.sigPositionChanged.disconnect()
                except (TypeError, RuntimeError):
                    pass
            for store_key in ("_region_items", "_instant_items"):
                for item in (getattr(self, store_key, None) or {}).values():
                    for sig_name in ("sigRegionChanged", "sigPositionChanged"):
                        sig = getattr(item, sig_name, None)
                        if sig is None:
                            continue
                        try:
                            sig.disconnect()
                        except (TypeError, RuntimeError):
                            pass
            scene = plot_widget.scene()
            if scene is not None:
                try:
                    scene.removeEventFilter(self)
                except RuntimeError:
                    pass
        except Exception:
            # 收尾路径兜底：任何一项失败都不影响其余清理
            pass

    def _detach_scene_items(self):
        """统一收尾协议入口（T-1060 件3）：先停子控件投递源，再收场景 item。

        与 `_cleanup_scene` 的分工：本方法在既有场景收尾之前，先停掉 VU 表的
        33ms 动画定时器（投递源），保证本控件销毁前其「有父对象的 QTimer」
        已停表断连。幂等、绝不外抛。
        """
        vm = getattr(self, "vu_meter", None)
        stop = getattr(vm, "stop_animation", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass  # 收尾路径绝不外抛
        self._cleanup_scene()

    def closeEvent(self, event):
        """窗口关闭：先显式收尾场景 item，再走默认关闭。"""
        self._detach_scene_items()
        super().closeEvent(event)
