# SPDX-License-Identifier: GPL-3.0-only
"""波形视图的实时特征面板：借鉴 Realtime_PyAudio_FFT 的四窗口 UI。

四个动态窗口（对应原项目 viz-lines / viz-fft / viz-scene / viz-bars）：
- 左上 频段能量滚动线：LIVE 滚动窗跟随播放头 + onset 标记
- 右上 实时频谱：当前帧 128-bin 对数频谱 + dB 平滑 + 峰值保持
- 左下 场景可视化：低频中心发光圆盘 + 中频全屏染色 + 高频噪点
- 右下 频段能量条：L/M/H 竖条 + 峰值保持刻度

性能要点：
- 逐帧数据由 analysis 层一次预计算，播放期间刷新零 FFT 开销
- 分析结果可缓存（get_cache/set_cached），视图切换重建面板不重算
- 场景噪点预生成，绘制时仅做索引切片
"""

from __future__ import annotations

import csv

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui.widgets.plot_menu import install_plot_menu as _install_plot_menu
from acouscope.ui.theme import (
    TOKENS,
    colors as _theme_colors,
    data_ink as theme_data_ink,
    on_theme_change,
    style_when_theme,
    ui_font as theme_ui_font,
)
from acouscope.analysis.realtime_features import (
    BAND_COLORS,
    BAND_RANGES,
    ENV_ATTACK_TAU,
    ENV_RELEASE_TAU,
    NOISE_FLOOR,
    PEAK_ATTACK_TAU,
    PEAK_RELEASE_TAU,
    analyze_all,
    compute_frame_log_spectrogram,
    log_bin_map,
    tau_to_alpha,
)

_LIVE_WINDOW = 20.0     # LIVE 模式滚动窗宽 (s)
_LIVE_AHEAD = 2.0       # 播放头右侧预留 (s)
_SMOOTH_ALPHA = 0.55    # 帧间 dB 平滑（越大越平滑）
_PEAK_DECAY_DB = 1.5    # 频谱峰值保持衰减 (dB/tick)
_BAR_PEAK_DECAY = 0.02  # 能量条峰值保持衰减 (/tick)


def _title_style() -> dict:
    """图表标题样式：颜色随主题令牌（§八 禁散落 hex）。"""
    return {"size": "9pt", "color": _theme_colors()["text"], "bold": False}


def _apply_canvas_theme(plot_widget, bg_role: str = "bg1") -> None:
    """画布并入主题（T-1032）：底色取中性阶，轴/刻度/网格随主题着色。

    pyqtgraph 的 ``setBackground`` 与轴笔不走 QSS，故主题变化时须显式重设。
    网格线沿用轴笔颜色（`showGrid` 的 alpha 不变）→ 随之着色。
    """
    c = _theme_colors()
    plot_widget.setBackground(c[bg_role])
    for side in ("left", "bottom", "right", "top"):
        axis = plot_widget.getAxis(side)
        axis.setPen(c["text_sub"])
        axis.setTextPen(c["text_sub"])
        axis.setLabel(
            axis.labelText, units=axis.labelUnits,
            **{**axis.labelStyle, "color": c["text"]},
        )


_NOISE_POINTS = 500     # 场景噪点预生成数量


def _th(key: str) -> str:
    """当前主题颜色（信息标签富文本用；缺键回落到当前正文色）。"""
    c = _theme_colors()
    return c.get(key) or c["text"]


def _fs(key: str) -> str:
    """富文本字号（T-1038 M3：字号取自令牌插值，禁字面 px）。"""
    return f"{TOKENS['typography'][key]}px"


def _qss_px(*keys: str) -> str:
    """令牌像素值序列（空格分隔的令牌像素对），供旁路 QSS 插值。"""
    return " ".join(f"{TOKENS['spacing'][k]}px" for k in keys)


def _ink_rgba(role: str, alpha: int) -> tuple:
    """数据墨色 → (r, g, b, a) 派生（pyqtgraph 填充用）。"""
    col = QColor(theme_data_ink(role))
    return (col.red(), col.green(), col.blue(), alpha)


# H4：图例半透明底（alpha），避免图例文字/色块压住同色曲线
_LEGEND_BG_ALPHA = 200


def _legend_bg() -> QColor:
    """图例背景：主题 bg1 + 半透明（随主题换色；禁硬编码 hex/alpha 混合值）。"""
    col = QColor(_theme_colors()["bg1"])
    col.setAlpha(_LEGEND_BG_ALPHA)
    return col


def _style_legend(legend) -> None:
    """图例描边/底色/文字色随主题（pyqtgraph 不走 QSS）。"""
    if legend is None:
        return
    c = _theme_colors()
    try:
        legend.setBrush(_legend_bg())
        legend.setPen(pg.mkPen(color=c["border"], width=1))
        legend.setLabelTextColor(c["text_sub"])
    except Exception:  # noqa: BLE001 — 图例样式永不抛
        pass


def _live_bg() -> str:
    """LIVE 状态信息条背景：语义 error 色低 alpha 派生（按骨架明暗取透明度）。"""
    col = QColor(TOKENS["semantic"]["error"])
    alpha = 0.16 if QColor(_th("text")).lightness() > 128 else 0.22
    return f"rgba({col.red()},{col.green()},{col.blue()},{alpha})"

# 图例文案 i18n 键（语言切换重启后生效）
_LEGEND_KEYS = {"low": "rt.leg_low", "mid": "rt.leg_mid", "high": "rt.leg_high"}


# 对数频率轴的十进位主刻度（1-2-5 序列，k 后缀）
_DECADE_TICKS = (10, 20, 30, 50, 100, 200, 300, 500, 1000, 2000, 3000, 5000,
                 10000, 20000)


class _DecadeFreqAxis(pg.AxisItem):
    """对数频率轴：十进位主刻度 + 范围自适应，任何缩放下数字不重叠。"""

    def tickValues(self, minVal, maxVal, size):
        lo, hi = sorted((minVal, maxVal))
        ticks = [v for v in _DECADE_TICKS if lo <= v <= hi]
        if len(ticks) < 2:
            # 极窄范围：退化为 pyqtgraph 默认（保证总有刻度）
            return super().tickValues(lo, hi, size)
        return [(1.0, ticks)]


class SceneViz(QWidget):
    """场景可视化（viz-scene）：低→中心发光圆盘，中→全屏染色，高→噪点。

    H4：补图表标题 + X/Y 轴标（与同页三块 pyqtgraph 画布同一套标题/轴标语义）。
    标题与轴标画在控件内部自留带里：不增加页面最小宽（横排预算已吃紧），
    也不压住中心圆盘与噪点（数据绘制区 = 扣掉三条文字带后的矩形）。
    """

    # 标题/轴标带与数据区之间的内缩（令牌间距，禁裸像素字面量）
    _TEXT_INSET = TOKENS["spacing"]["xxs"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self._low = self._mid = self._high = 0.0
        self._frame = 0
        # 预生成边缘偏置噪点（半径平方根均匀分布），绘制时仅索引切片
        rng = np.random.default_rng(7)
        self._pt_r = np.sqrt(rng.random(_NOISE_POINTS))
        self._pt_t = rng.random(_NOISE_POINTS) * 2 * np.pi
        style_when_theme(
            self,
            lambda c: (
                f"SceneViz {{background: {c['bg2']};"
                f" border: {TOKENS['elevation']['border']}px solid {c['border']};"
                f" border-radius: {TOKENS['radius']['sm']}px;}}"
            ),
        )

    def set_values(self, low: float, mid: float, high: float) -> None:
        self._low = float(np.clip(low, 0.0, 1.0))
        self._mid = float(np.clip(mid, 0.0, 1.0))
        self._high = float(np.clip(high, 0.0, 1.0))
        self.update()

    def _text_font(self) -> QFont:
        """标题/轴标字体（族走主题字链、字号走令牌；禁族名/字号字面量）。"""
        font = theme_ui_font()
        font.setPixelSize(TOKENS["typography"]["caption_sm"])
        return font

    def _content_rect(self) -> QRectF:
        """数据绘制区：扣掉标题带、X 轴标带、Y 轴标带（三条文字带）。"""
        line = float(QFontMetrics(self._text_font()).height())
        inset = float(self._TEXT_INSET)
        left = line + inset
        top = line + inset
        bottom = line + inset
        return QRectF(
            left, top,
            max(1.0, self.width() - left - inset),
            max(1.0, self.height() - top - bottom),
        )

    def _paint_text_bands(self, p: QPainter, rect: QRectF) -> None:
        """画标题（上中）+ X 轴标（下中）+ Y 轴标（左中，旋转 90°）。"""
        c = _theme_colors()
        line = float(QFontMetrics(self._text_font()).height())
        p.setPen(QColor(c["text"]))
        p.drawText(
            QRectF(0.0, 0.0, float(self.width()), line),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            tr("rt.plot_scene"),
        )
        p.setPen(QColor(c["sub"]))
        p.drawText(
            QRectF(0.0, float(self.height()) - line, float(self.width()), line),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            tr("rt.axis_scene_x"),
        )
        p.save()
        p.translate(line / 2.0, float(self.height()) / 2.0)
        p.rotate(-90.0)
        p.drawText(
            QRectF(-float(self.height()) / 2.0, -line / 2.0,
                   float(self.height()), line),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            tr("rt.axis_scene_y"),
        )
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._content_rect()
        w, h = rect.width(), rect.height()

        # 中频：全屏色相染色
        if self._mid > 0.02:
            p.fillRect(self.rect(), QColor(121, 209, 122, int(46 * self._mid)))

        # 低频：中心径向发光圆盘（半径与亮度随 low 增长）
        r = (0.16 + 0.34 * self._low) * min(w, h) / 2
        cx, cy = rect.center().x(), rect.center().y()
        grad = QRadialGradient(cx, cy, max(r, 1.0))
        g = int(90 + 120 * self._low)
        grad.setColorAt(0.0, QColor(90, g, 238, int(235 * max(self._low, 0.12))))
        grad.setColorAt(0.6, QColor(90, g, 238, int(90 * self._low)))
        grad.setColorAt(1.0, QColor(90, g, 238, 0))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        # 高频：明亮噪点（数量随 high，循环索引产生闪烁感）
        n = int(10 + 380 * self._high)
        if n > 0:
            idx = (np.arange(n) + self._frame) % _NOISE_POINTS
            self._frame = (self._frame + 97) % _NOISE_POINTS
            xs = cx + self._pt_r[idx] * np.cos(self._pt_t[idx]) * (w / 2 - 4)
            ys = cy + self._pt_r[idx] * np.sin(self._pt_t[idx]) * (h / 2 - 4)
            p.setPen(QPen(QColor(232, 168, 87, 200), 1.4))
            for x, y in zip(xs, ys):
                p.drawPoint(int(x), int(y))

        # H4：标题 + X/Y 轴标（画在自留带内，不压数据区）
        p.setFont(self._text_font())
        self._paint_text_bands(p, rect)
        p.end()


class RealtimePanel(QWidget):
    """波形下方窗口的实时特征面板（四动态窗格）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: dict | None = None
        self._spec_times: np.ndarray | None = None
        self._spec_centers: np.ndarray | None = None
        self._spec_db: np.ndarray | None = None
        self._pos = 0.0
        self._live = False
        self._smooth_db: np.ndarray | None = None
        self._peaks_db: np.ndarray | None = None
        self._bar_peaks = {name: 0.0 for name in BAND_RANGES}

        # 录制实时模式状态（无预计算 _result，推块即算）
        self._live_mode = False
        self._live_sr = 44100.0
        self._live_total = 0
        self._live_t: list[float] = []
        self._live_b = {n: [] for n in BAND_RANGES}
        self._live_env = {n: (0.0, NOISE_FLOOR) for n in BAND_RANGES}
        self._live_last_append = -1.0
        self._live_db: np.ndarray | None = None
        self._live_centers: np.ndarray | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(50)  # 20 FPS，与主窗口播放轮询同步
        self._timer.timeout.connect(self._tick)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(3)

        # ----- 紧凑信息条：全部文字合并为单一富文本标签（根治遮挡） -----
        info_bar = QHBoxLayout()
        info_bar.setContentsMargins(0, 0, 0, 0)
        info_bar.setSpacing(6)

        # 标题 + 模式 + 起音计数 + BPM 全在一个标签里：
        # 窄面板下只在标签自身尾部截断，元素间永不互相遮挡
        self.lbl_info = QLabel(
            f"<b style='font-size:{_fs('body_sm')};color:{_th('text')}'>"
            f"{tr('rt.title')}</b>"
            f"<span style='font-size:{_fs('caption')};color:{_th('sub')}'>"
            f" · {tr('rt.static')} · "
            f"{tr('rt.onset_lmh').format(low=0, mid=0, high=0)}</span>"
        )
        self.lbl_info.setTextFormat(Qt.TextFormat.RichText)
        # 信息条背景随主题（LIVE 时切换暗红/浅红）；富文本颜色在
        # 主题变化时按最近一次状态整体重建
        self._live_style = False
        self._last_mode_html = ""
        self._refresh_info_style = style_when_theme(
            self.lbl_info,
            lambda c: (
                f"background: {_live_bg()}; padding: {_qss_px('xxs', 'gap')};"
                f" border-radius: {TOKENS['radius']['sm']}px;"
                f" border: {TOKENS['elevation']['border']}px solid {c['border']};"
                if self._live_style else
                f"background: {c['window']}; padding: {_qss_px('xxs', 'gap')};"
                f" border-radius: {TOKENS['radius']['sm']}px;"
                f" border: {TOKENS['elevation']['border']}px solid {c['border']};"
            ),
        )
        on_theme_change(self._rebuild_info_text)
        # sizeHint 按默认字体计算，不含内联 BPM 大字号（见 _fs('body')）——
        # 显式按大一号字体高度撑起标签，根治下缘被裁
        _font_big = QFont()
        _font_big.setPointSize(_font_big.pointSize() + 2)
        self.lbl_info.setMinimumHeight(QFontMetrics(_font_big).height() + 4)
        info_bar.addWidget(self.lbl_info, stretch=1)

        self.btn_export = QPushButton("CSV")
        self.btn_export.setToolTip(tr("rt.tip_csv"))
        self.btn_export.setStyleSheet(
            f"font-size: {TOKENS['typography']['caption']}px;"
            f" padding: {TOKENS['elevation']['border']}px"
            f" {TOKENS['spacing']['sm']}px;")
        self.btn_export.clicked.connect(self._on_export_csv)
        info_bar.addWidget(self.btn_export)

        info_widget = QWidget()
        info_widget.setLayout(info_bar)
        # 高度自适应：富文本含大号 BPM 数字，固定高度会裁掉下缘
        layout.addWidget(info_widget)

        # ----- 2×2 四窗格 -----
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)

        # (1) 左上：频段能量滚动线 + onset + 播放头
        self.plot_bands = pg.PlotWidget()
        self.plot_bands.showGrid(x=True, y=True, alpha=0.3)
        self.plot_bands.setTitle(tr("rt.plot_bands"), **_title_style())
        self.plot_bands.setLabel(
            "bottom", tr("rt.axis_time"), units="s", **{"font-size": "8pt"}
        )
        from acouscope.ui.widgets.time_axis import apply_time_axis as _apply_taxis

        _apply_taxis(self.plot_bands)
        _apply_canvas_theme(self.plot_bands)
        # H4：图例加半透明底（原默认透明底，图例文字/色块与曲线互压）
        self.bands_legend = self.plot_bands.addLegend(offset=(36, 6), labelTextSize="8pt")
        _style_legend(self.bands_legend)
        self.plot_bands.setYRange(0, 1.05, padding=0)
        self.plot_bands.setMouseEnabled(x=True, y=False)

        self.band_curves: dict[str, pg.PlotDataItem] = {}
        self.onset_lines: dict[str, pg.PlotDataItem] = {}
        self._onset_spans: dict[str, tuple[float, float]] = {}
        # 低频 onset 线最长（贯穿 0→1，驱动 BPM），中高频依次缩短
        onset_y_spans = {"low": (0.0, 1.0), "mid": (0.33, 1.0), "high": (0.66, 1.0)}
        for name in BAND_RANGES:
            color = BAND_COLORS[name]
            self.band_curves[name] = self.plot_bands.plot(
                pen=pg.mkPen(color, width=4.5), name=tr(_LEGEND_KEYS[name]),
            )
            y0, y1 = onset_y_spans[name]
            self.onset_lines[name] = self.plot_bands.plot(
                pen=pg.mkPen(color, width=2.2, style=Qt.PenStyle.DashLine),
            )
            self._onset_spans[name] = (y0, y1)

        self.playhead = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(theme_data_ink("cursor"), width=4.5),
        )
        self.playhead.hide()
        self.plot_bands.addItem(self.playhead)
        _install_plot_menu(self.plot_bands, [
            (tr("menu.view_all"), lambda: self.plot_bands.autoRange()),
            (tr("menu.reset_x"), self._reset_bands_x),
        ])
        grid.addWidget(self.plot_bands, 0, 0)

        # (2) 右上：实时对数频谱（当前帧 + 峰值保持）
        self.plot_spectrum = pg.PlotWidget(
            axisItems={"bottom": _DecadeFreqAxis(orientation="bottom")}
        )
        self.plot_spectrum.showGrid(x=True, y=True, alpha=0.3)
        self.plot_spectrum.setTitle(tr("rt.plot_spectrum"), **_title_style())
        self.plot_spectrum.setLabel(
            "bottom", tr("rt.axis_freq"), units="Hz", **{"font-size": "8pt"}
        )
        self.plot_spectrum.setLabel("left", "dB", **{"font-size": "8pt"})
        self.plot_spectrum.setLogMode(x=True, y=False)
        self.plot_spectrum.setMouseEnabled(x=True, y=True)
        _apply_canvas_theme(self.plot_spectrum)
        # k 后缀标签
        spec_axis = self.plot_spectrum.getAxis("bottom")
        spec_axis.tickStrings = lambda vals, scale, spacing: [
            f"{v/1000:g}k" if v >= 1000 else f"{v:g}" for v in vals
        ]
        f_axis = QFont()
        f_axis.setPointSize(8)
        spec_axis.setTickFont(f_axis)

        self.curve_spectrum = self.plot_spectrum.plot(
            pen=pg.mkPen(theme_data_ink("trace"), width=4.5),
            fillLevel=-90, brush=_ink_rgba("trace", 40),
        )
        self.curve_peaks = self.plot_spectrum.plot(
            pen=pg.mkPen(theme_data_ink("trace_alt"), width=2.2),
        )
        self.curve_peaks.hide()
        _install_plot_menu(self.plot_spectrum, [
            (tr("menu.view_all"), lambda: self.plot_spectrum.autoRange()),
            (tr("rt.menu_peaks"), self._toggle_spec_peaks),
        ])
        grid.addWidget(self.plot_spectrum, 0, 1)

        # (3) 左下：场景可视化
        self.scene = SceneViz()
        grid.addWidget(self.scene, 1, 0)

        # (4) 右下：频段能量条 + 峰值保持刻度
        self.plot_bars = pg.PlotWidget()
        self.plot_bars.showGrid(y=True, alpha=0.3)
        self.plot_bars.setTitle(tr("rt.plot_bars"), **_title_style())
        self.plot_bars.setMouseEnabled(x=False, y=False)
        self.plot_bars.setYRange(0, 1.05, padding=0)
        self.plot_bars.setLimits(xMin=-0.7, xMax=2.7, yMin=0, yMax=1.1)
        _apply_canvas_theme(self.plot_bars)
        axis = self.plot_bars.getAxis("bottom")
        axis.setTicks([[(0, tr("rt.band_low")), (1, tr("rt.band_mid")),
                        (2, tr("rt.band_high"))]])
        f_small = QFont()
        f_small.setPointSize(8)
        axis.setTickFont(f_small)

        self.bars = pg.BarGraphItem(
            x=[0, 1, 2], height=[0, 0, 0], width=0.55,
            brushes=[BAND_COLORS[n] for n in BAND_RANGES],
        )
        self.plot_bars.addItem(self.bars)
        self.bar_peaks_curve = self.plot_bars.plot(
            pen=pg.mkPen(theme_data_ink("ref_line"), width=2.2),
        )
        _install_plot_menu(self.plot_bars, [
            (tr("menu.view_all"), lambda: self.plot_bars.autoRange()),
            (tr("rt.menu_peaks"), self._toggle_bar_peaks),
        ])
        grid.addWidget(self.plot_bars, 1, 1)

        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        layout.addLayout(grid, stretch=1)
        on_theme_change(self._on_canvas_theme)

    def _apply_ink(self) -> None:
        """数据墨色（T-1038 M1/M6）：播放头/频谱轨迹/峰值线与柱峰线随主题取色。"""
        self.playhead.setPen(pg.mkPen(theme_data_ink("cursor"), width=4.5))
        self.curve_spectrum.setPen(pg.mkPen(theme_data_ink("trace"), width=4.5))
        self.curve_spectrum.setBrush(pg.mkBrush(*_ink_rgba("trace", 40)))
        self.curve_peaks.setPen(pg.mkPen(theme_data_ink("trace_alt"), width=2.2))
        self.bar_peaks_curve.setPen(pg.mkPen(theme_data_ink("ref_line"), width=2.2))

    def _on_canvas_theme(self) -> None:
        """主题切换：重设三个实时画布底色/轴色/标题色 + 数据墨色（pyqtgraph 不走 QSS）。"""
        titles = (
            (self.plot_bands, tr("rt.plot_bands")),
            (self.plot_spectrum, tr("rt.plot_spectrum")),
            (self.plot_bars, tr("rt.plot_bars")),
        )
        for plot, title in titles:
            _apply_canvas_theme(plot)
            plot.setTitle(title, **_title_style())
            plot.update()
        _style_legend(getattr(self, "bands_legend", None))
        self._apply_ink()

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def set_audio(self, data: np.ndarray, sample_rate: float) -> None:
        """预计算全部特征并绘制静态全览。"""
        self._live_mode = False
        self._live_t = []
        self._live_b = {n: [] for n in BAND_RANGES}
        self._result = analyze_all(data, sample_rate)
        self._spec_times, self._spec_centers, self._spec_db = (
            compute_frame_log_spectrogram(data, sample_rate)
        )
        self._smooth_db = None
        self._peaks_db = None
        self._render_static()

    def get_cache(self) -> tuple:
        """导出分析结果缓存（供视图切换后快速重建）。"""
        return (self._result, self._spec_times, self._spec_centers, self._spec_db)

    def set_cached(self, cache: tuple) -> None:
        """从缓存恢复（不重算）。"""
        self._live_mode = False
        self._live_t = []
        self._live_b = {n: [] for n in BAND_RANGES}
        self._result, self._spec_times, self._spec_centers, self._spec_db = cache
        self._smooth_db = None
        self._peaks_db = None
        self._render_static()

    # ------------------------------------------------------------------
    # 录制实时模式（无预计算数据，逐块计算）
    # ------------------------------------------------------------------

    _LIVE_FFT = 1024
    _LIVE_HIST_HZ = 20.0     # 包络历史采样率
    _LIVE_HIST_MAX = 12000   # 历史上限（10 分钟 @20Hz）

    def begin_live_capture(self, sample_rate: float) -> None:
        """进入录制实时模式：清空历史，预置频谱映射。"""
        sr = float(sample_rate)
        self._live_mode = True
        self._live_sr = sr
        self._live_total = 0
        self._live_t = []
        self._live_b = {n: [] for n in BAND_RANGES}
        self._live_env = {n: (0.0, NOISE_FLOOR) for n in BAND_RANGES}
        self._live_last_append = -1.0
        self._live_db = None
        self._smooth_db = None
        self._peaks_db = None
        self._bar_peaks = {n: 0.0 for n in BAND_RANGES}

        n_rfft = self._LIVE_FFT // 2 + 1
        assign, counts, centers = log_bin_map(n_rfft, sr, 128, 30.0)
        m_avg = np.zeros((n_rfft, 128), dtype=np.float32)
        valid = assign >= 0
        np.add.at(m_avg, (np.where(valid)[0], assign[valid]), 1.0)
        nz = counts > 0
        m_avg[:, nz] /= counts[nz]
        self._live_centers = centers
        self._live_m_avg = m_avg
        self._live_window = np.hanning(self._LIVE_FFT)
        self._live_freqs = np.fft.rfftfreq(self._LIVE_FFT, 1.0 / sr)
        self._live_masks = {
            n: (self._live_freqs >= lo) & (self._live_freqs <= min(hi, sr / 2))
            for n, (lo, hi) in BAND_RANGES.items()
        }

        # UI 进入 LIVE（无静态数据可回退）
        self._live = True
        for n in BAND_RANGES:
            self.band_curves[n].setData([], [])
        self._live_style = True
        self._refresh_info_style()
        self._update_info_label(
            f"<b style='font-size:{_fs('caption')};"
            f"color:{TOKENS['semantic']['error']}'> · {tr('rt.live_rec')}</b>"
        )
        self.playhead.show()
        self.curve_peaks.show()
        if not self._timer.isActive():
            self._timer.start()

    def push_live_chunk(self, chunk: np.ndarray) -> None:
        """处理一块采集数据：频段包络 + 当前帧频谱（一次 1024 FFT）。"""
        if not self._live_mode:
            return
        x = np.asarray(chunk, dtype=np.float64).ravel()
        n = len(x)
        if n == 0:
            return
        sr = self._live_sr
        dt = n / sr

        frame = np.zeros(self._LIVE_FFT)
        frame[: min(n, self._LIVE_FFT)] = x[: self._LIVE_FFT]
        power = np.abs(np.fft.rfft(frame * self._live_window)) ** 2

        # 频段包络（与分析层同一套攻击/释放/峰值跟踪参数）
        a_atk = tau_to_alpha(dt, ENV_ATTACK_TAU)
        a_rel = tau_to_alpha(dt, ENV_RELEASE_TAU)
        a_pk_atk = tau_to_alpha(dt, PEAK_ATTACK_TAU)
        a_pk_rel = tau_to_alpha(dt, PEAK_RELEASE_TAU)
        nf2 = NOISE_FLOOR * NOISE_FLOOR
        vals = {}
        for name, mask in self._live_masks.items():
            pw = float(power[mask].mean()) if mask.any() else 0.0
            c = pw - nf2
            v = float(np.sqrt(c)) if c > 0 else 0.0
            s, peak = self._live_env[name]
            d = v - s
            s += (a_atk if d > 0 else a_rel) * d
            dp = s - peak
            peak += (a_pk_atk if dp > 0 else a_pk_rel) * dp
            self._live_env[name] = (s, peak)
            vals[name] = float(np.tanh(s / max(peak, NOISE_FLOOR)))

        # 当前帧对数频谱
        db = 10.0 * np.log10(np.maximum(power @ self._live_m_avg, 1e-20))
        self._live_db = np.maximum(db, -90.0).astype(np.float32)

        # 追加历史（限频）
        t_end = (self._live_total + n) / sr
        if t_end - self._live_last_append >= 1.0 / self._LIVE_HIST_HZ:
            self._live_t.append(t_end)
            for name in BAND_RANGES:
                self._live_b[name].append(vals[name])
            if len(self._live_t) > self._LIVE_HIST_MAX:
                self._live_t.pop(0)
                for name in BAND_RANGES:
                    self._live_b[name].pop(0)
            self._live_last_append = t_end

        self._live_total += n

    def end_live_capture(self) -> None:
        """结束录制实时模式（数据将由 set_audio 正式载入）。"""
        if not self._live_mode:
            return
        self._live_mode = False
        self.set_playing(False)

    def _tick_live(self) -> None:
        """录制实时模式刷新（滚动历史 + 当前频谱 + 能量条 + 场景）。"""
        if not self._live_t:
            return
        t_arr = np.asarray(self._live_t)
        t = self._pos

        x1 = max(_LIVE_WINDOW, t + _LIVE_AHEAD)
        x0 = max(0.0, x1 - _LIVE_WINDOW)
        self.plot_bands.setXRange(x0, x1, padding=0)
        self.playhead.setPos(t)
        m = (t_arr >= x0) & (t_arr <= x1)
        for name in BAND_RANGES:
            self.band_curves[name].setData(
                t_arr[m], np.asarray(self._live_b[name])[m]
            )

        # 当前帧频谱（dB 平滑 + 峰值保持）
        if self._live_db is not None:
            cur = self._live_db.astype(np.float64)
            self._smooth_db = cur.copy() if self._smooth_db is None else (
                _SMOOTH_ALPHA * self._smooth_db + (1 - _SMOOTH_ALPHA) * cur
            )
            self._peaks_db = self._smooth_db.copy() if self._peaks_db is None else np.maximum(
                self._smooth_db, self._peaks_db - _PEAK_DECAY_DB
            )
            self.curve_spectrum.setData(self._live_centers, self._smooth_db)
            self.curve_peaks.setData(self._live_centers, self._peaks_db)

        # 能量条 + 场景：最新历史值
        vals = {n: self._live_b[n][-1] for n in BAND_RANGES}
        self._set_bars(*(vals[n] for n in BAND_RANGES))
        for n in BAND_RANGES:
            self._bar_peaks[n] = max(vals[n], self._bar_peaks[n] - _BAR_PEAK_DECAY)
        self._draw_bar_peaks()
        self.scene.set_values(vals["low"], vals["mid"], vals["high"])

    def _rebuild_info_text(self) -> None:
        """主题变化回调：按最近一次状态重建信息条富文本。"""
        self._update_info_label(self._last_mode_html)

    def _update_info_label(self, mode_html: str) -> None:
        """组装单一信息标签（标题 + 模式 + 起音 + BPM），颜色随主题。"""
        self._last_mode_html = mode_html
        title = (f"<b style='font-size:{_fs('body_sm')};color:{_th('text')}'>"
                 f"{tr('rt.title')}</b>")
        if self._result is None:
            self.lbl_info.setText(f"{title}{mode_html}")
            return
        counts = {n: len(self._result["onsets"][n].times) for n in BAND_RANGES}
        bpm = self._result["bpm"]
        bpm_html = (
            f"<b style='font-family:monospace;font-size:{_fs('body')};"
            f"color:{_th('accent')}'>"
            f"BPM {bpm:.0f}</b>" if bpm > 0
            else f"<span style='font-family:monospace;font-size:{_fs('body')};"
                 f"color:{_th('sub')}'>BPM —</span>"
        )
        onset_html = tr("rt.onset_lmh").format(
            low=counts["low"], mid=counts["mid"], high=counts["high"])
        self.lbl_info.setText(
            f"{title}{mode_html}"
            f"<span style='font-size:{_fs('caption')};color:{_th('sub')}'> · {onset_html}</span>"
            f" · {bpm_html}"
        )

    def _render_static(self) -> None:
        """静态全览渲染（打开文件 / 停止播放 / 缓存恢复共用）。"""
        if self._result is None:
            # 录音刚结束、数据未载入的空窗期：清空曲线待命
            for name in BAND_RANGES:
                self.band_curves[name].setData([], [])
                self.onset_lines[name].setData([], [])
            return
        times = self._result["times"]
        for name in BAND_RANGES:
            self.band_curves[name].setData(times, self._result["bands"][name])
            self._draw_onsets(name)

        self.curve_spectrum.setData(
            self._result["spectrum_freqs"], self._result["spectrum_db"]
        )
        self._restore_static_view()

        self._update_info_label(
            f"<span style='font-size:{_fs('caption')};color:{_th('sub')}'> · {tr('rt.static')}</span>"
        )

        # 能量条与场景显示全文件平均（静态基调）
        means = [float(self._result["bands"][n].mean()) for n in BAND_RANGES]
        self._set_bars(*means)
        self._bar_peaks = {n: m for n, m in zip(BAND_RANGES, means)}
        self.scene.set_values(*means)

    # ------------------------------------------------------------------
    # 播放联动（主窗口 20 FPS 注入位置与播放状态）
    # ------------------------------------------------------------------

    def set_position(self, pos: float) -> None:
        """接收当前播放位置 (s)。"""
        self._pos = float(pos)

    def set_playing(self, playing: bool) -> None:
        """播放状态切换：进入/退出 LIVE 模式（状态未变时零开销）。"""
        if playing:
            # 需要预计算数据（播放）或实时采集模式（录音）
            if self._result is None and not self._live_mode:
                return
            if not self._live:
                self._live = True
                self._live_style = True
                self._refresh_info_style()
                self.playhead.show()
                self.curve_peaks.show()
                self._peaks_db = None
                self._smooth_db = None
                self._bar_peaks = {n: 0.0 for n in BAND_RANGES}
                self._update_info_label(
                    f"<b style='font-size:{_fs('caption')};"
                    f"color:{TOKENS['semantic']['error']}'> · {tr('rt.live_play')}</b>"
                )
            if not self._timer.isActive():
                self._timer.start()
        else:
            if not self._live and not self._timer.isActive():
                return
            self._timer.stop()
            if self._live:
                self._live = False
                self._live_style = False
                self._refresh_info_style()
                self.playhead.hide()
                self.curve_peaks.hide()
                self._render_static()

    def _band_values_at(self, t: float) -> dict[str, float]:
        """取播放时刻的三频段包络值。"""
        times = self._result["times"]
        idx = int(np.clip(np.searchsorted(times, t), 0, len(times) - 1))
        return {n: float(self._result["bands"][n][idx]) for n in BAND_RANGES}

    def _tick(self) -> None:
        """LIVE 刷新：录音实时模式或播放跟随。"""
        if self._live_mode:
            self._tick_live()
            return
        if self._result is None or len(self._result["times"]) == 0:
            return
        t = self._pos

        # (1) 滚动窗口跟随播放头
        x1 = max(_LIVE_WINDOW, t + _LIVE_AHEAD)
        x0 = max(0.0, x1 - _LIVE_WINDOW)
        duration = self._result["times"][-1]
        x1 = min(x1, duration + _LIVE_AHEAD)
        x0 = max(0.0, x1 - _LIVE_WINDOW)
        self.plot_bands.setXRange(x0, x1, padding=0)
        self.playhead.setPos(t)

        # (2) 当前帧对数频谱（dB 平滑 + 峰值保持）
        if self._spec_db is not None and len(self._spec_times) > 0:
            idx = int(np.clip(np.searchsorted(self._spec_times, t), 0,
                              len(self._spec_times) - 1))
            cur = self._spec_db[idx].astype(np.float64)
            if self._smooth_db is None:
                self._smooth_db = cur.copy()
            else:
                self._smooth_db = _SMOOTH_ALPHA * self._smooth_db + (1 - _SMOOTH_ALPHA) * cur
            if self._peaks_db is None:
                self._peaks_db = self._smooth_db.copy()
            else:
                self._peaks_db = np.maximum(self._smooth_db, self._peaks_db - _PEAK_DECAY_DB)

            self.curve_spectrum.setData(self._spec_centers, self._smooth_db)
            self.curve_peaks.setData(self._spec_centers, self._peaks_db)

        # (3)(4) 能量条 + 场景：当前时刻三频段值 + 峰值保持
        vals = self._band_values_at(t)
        self._set_bars(*(vals[n] for n in BAND_RANGES))
        for n in BAND_RANGES:
            self._bar_peaks[n] = max(vals[n], self._bar_peaks[n] - _BAR_PEAK_DECAY)
        self._draw_bar_peaks()
        self.scene.set_values(vals["low"], vals["mid"], vals["high"])

    def _set_bars(self, low: float, mid: float, high: float) -> None:
        self.bars.setOpts(height=[low, mid, high])

    def _draw_bar_peaks(self) -> None:
        xs, ys = [], []
        for i, n in enumerate(BAND_RANGES):
            pk = self._bar_peaks[n]
            xs += [i - 0.28, i + 0.28, np.nan]
            ys += [pk, pk, np.nan]
        self.bar_peaks_curve.setData(xs, ys)

    # ------------------------------------------------------------------
    # 静态模式辅助
    # ------------------------------------------------------------------

    def _restore_static_view(self) -> None:
        """左图恢复全文件 X 范围。"""
        times = self._result["times"] if self._result else np.zeros(0)
        if len(times):
            self.plot_bands.setXRange(0.0, times[-1], padding=0.02)

    # ------------------------------------------------------------------
    # 右键菜单动作
    # ------------------------------------------------------------------

    def _reset_bands_x(self) -> None:
        """复位左图 X 轴：静态→全文件，LIVE→当前滚动窗。"""
        if self._live_mode or self._live:
            x1 = max(_LIVE_WINDOW, self._pos + _LIVE_AHEAD)
            self.plot_bands.setXRange(max(0.0, x1 - _LIVE_WINDOW), x1, padding=0)
        elif self._result is not None and len(self._result["times"]):
            self.plot_bands.setXRange(0.0, self._result["times"][-1], padding=0.02)

    def _toggle_spec_peaks(self) -> None:
        self.curve_peaks.setVisible(not self.curve_peaks.isVisible())

    def _toggle_bar_peaks(self) -> None:
        self.bar_peaks_curve.setVisible(not self.bar_peaks_curve.isVisible())

    def _draw_onsets(self, name: str) -> None:
        """把一个频段的 onset 画成竖虚线段（NaN 断段合并为一条曲线）。"""
        fires = self._result["onsets"][name].times
        y0, y1 = self._onset_spans[name]
        if len(fires) == 0:
            self.onset_lines[name].setData([], [])
            return
        xs = np.empty(len(fires) * 3)
        ys = np.empty(len(fires) * 3)
        xs[0::3] = fires
        xs[1::3] = fires
        xs[2::3] = np.nan
        ys[0::3] = y0
        ys[1::3] = y1
        ys[2::3] = np.nan
        self.onset_lines[name].setData(xs, ys)

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    def _on_export_csv(self):
        """导出特征数据 CSV（逐帧包络 + onset 时刻 + 频谱 + BPM）。"""
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("rt.dlg_export"), "realtime_features.csv",
            tr("rt.file_filter"),
        )
        if not path:
            return
        self._export_csv(path)

    def _export_csv(self, path: str) -> None:
        r = self._result
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)

            w.writerow(["# 实时特征分析 (Realtime_PyAudio_FFT 算法)"])
            w.writerow(["# BPM", f"{r['bpm']:.2f}"])
            w.writerow([])

            w.writerow(["帧时间(s)", "低频包络", "中频包络", "高频包络"])
            for i, t in enumerate(r["times"]):
                w.writerow([
                    f"{t:.4f}",
                    f"{r['bands']['low'][i]:.5f}",
                    f"{r['bands']['mid'][i]:.5f}",
                    f"{r['bands']['high'][i]:.5f}",
                ])
            w.writerow([])

            w.writerow(["频段", "Onset 时刻(s)"])
            for name in BAND_RANGES:
                for t in r["onsets"][name].times:
                    w.writerow([name, f"{t:.4f}"])
            w.writerow([])

            w.writerow(["频率(Hz)", "功率(dB)"])
            for fq, db in zip(r["spectrum_freqs"], r["spectrum_db"]):
                w.writerow([f"{fq:.2f}", f"{db:.2f}"])
