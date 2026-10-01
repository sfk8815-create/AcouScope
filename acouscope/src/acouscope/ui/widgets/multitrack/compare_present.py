# SPDX-License-Identifier: GPL-3.0-only
"""T-1009 M4 多轨对比呈现层：一图差异（F0 叠图）/ 密度热图 / 多图分离 / 模式切换。

- 呈现范式：Overview + Detail（总览 = 时间-频率密度热图；细节 = F0 折线），轨数少时以
  折线叠图为主；**不做波形相减**（不同 take 的时间/装饰音不同，波形差无物理意义）。
- 数据源：T-1008 逐轨结果缓存（kind="pitch"）；时间轴按 T-1006 对齐偏移映射到共享基线。
- **T-1005 接通**：差异统计（以参考轨为基准的逐轨量化，量化层 = `compare_diff`）、
  差异条（超阈色段）、悬停读数（T-326 Pδ 机制复用）与差异表 CSV 导出；
  阈值取自 `Settings`（默认 50 cents，**报警阈值，非精度承诺**）。
- 颜色一律取主题语义色（轨色轮转复用轨道头口径），无硬编码色值。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from acouscope.dsp import units
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.multitrack import compare_diff
from acouscope.ui.widgets.multitrack.align import shifted_times
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.track_header import track_color
from acouscope.ui.widgets.multitrack.track_model import format_seconds

MODE_SINGLE = "single"          # 一图差异：全部轨 F0 叠绘于共享时间轴
MODE_GRID = "grid"              # 多图分离：每轨一图
MODES = (MODE_SINGLE, MODE_GRID)
PITCH_KIND = "pitch"

# 密度热图（Overview 范式）：轨数过少时折线已足够 → 默认关（用户可显式开启）
HEATMAP_MIN_TRACKS = 4
HEATMAP_TIME_BINS = 240
HEATMAP_FREQ_BINS = 96
# T-1089 N-F：色标量纲（绝对计数参考 = 非零格分位·不再是逐图 peak）
HEATMAP_SCALE_PERCENTILE = 95.0
HEATMAP_COLORBAR_TICKS = 5

# T-1005 差异条（超阈色段）：行高/间距一律令牌派生（禁硬编码 px）
DIFF_BAR_ROW_H = float(TOKENS["spacing"]["sm"])
DIFF_BAR_GAP = float(TOKENS["spacing"]["xs"])
DIFF_BAR_MAX_ROWS = 4
# T-1089 N-B：截断须显式告知（行高取 spacing.md ⇒ 提示行能装下正文字号）
DIFF_BAR_NOTICE_H = float(TOKENS["spacing"]["md"])
DIFF_HINT_MAX_TRACKS = 8               # hint 逐轨行列数上限（超出显式标「＋N 轨未列」）
DIFF_ANALYSIS_MAX_FRAMES = 400    # T-1089 N-E：派生指标的逐帧抽样上限（主线程不吃全帧循环）
HOVER_THROTTLE_S = 0.05          # 悬停读数节流（≤20Hz，同 T-326 Pδ）

DEFAULT_FMIN = 40.0
DEFAULT_FMAX = 2000.0
_MIN_SPAN_S = 1e-3
CURVE_WIDTH = 1.6
REFERENCE_WIDTH = 2.6
WAVEFORM_ALPHA = 70
DIFF_ALPHA = 120
LABEL_PAD = 4.0
_GAP_SECONDS = 0.05

# T-1089 N-C 轴与网格（借 SV ScaleTickIntervals 的"取疏整档"与 HorizontalFrequencyScale
# 的防叠字避让；宽度全部令牌派生，禁硬编码 px）
AXIS_LABEL_GUTTER_W = float(TOKENS["spacing"]["xl"])    # 左轴带：音名/频率标签
AXIS_TIME_BAND_H = float(TOKENS["spacing"]["lg"])       # 下轴带：时间标注
AXIS_LABEL_ALPHA = 90                                   # 网格线淡出（非语义色·仅透明度）
TUNING_LINE_ALPHA = 110                                 # 律级参考线淡出（N-D）
AXIS_MIN_LABEL_SPACING = float(TOKENS["spacing"]["lg"])  # 音名标签最小竖向间距（选档判据）
AXIS_LABEL_STEPS = (1, 3, 6, 12)                        # 半音 / 小三度 / 三全音 / 八度 C
AXIS_TARGET_LABELS = 8                                  # 时间轴目标标注数（疏档依据）
AXIS_TIME_STEPS = (1.0, 2.0, 5.0, 10.0)                 # 每十倍程的"nice"步长档

__all__ = [
    "MODE_SINGLE", "MODE_GRID", "MODES", "PITCH_KIND",
    "HEATMAP_MIN_TRACKS", "DIFF_BAR_ROW_H", "DIFF_BAR_MAX_ROWS",
    "DIFF_BAR_NOTICE_H", "DIFF_HINT_MAX_TRACKS", "DIFF_ANALYSIS_MAX_FRAMES",
    "TrackSeries", "PanelInfo",
    "series_from_cache", "build_density_heatmap", "heatmap_default",
    "ComparePresentWidget",
]


# ----------------------------------------------------------------------
# 纯数据层（可离屏直测，不依赖 Qt 绘制）
# ----------------------------------------------------------------------


def _nearest_semitone_cents(cents: float) -> float:
    """距 ``cents`` 最近的 12TET 半音位置（``SEMITONE_CENTS`` 的唯一呈现层消费点）。"""
    step = compare_diff.SEMITONE_CENTS
    return round(float(cents) / step) * step


@dataclass
class TrackSeries:
    """一轨的 F0 呈现数据（`times` 已应用 T-1006 对齐偏移，单位秒）。"""

    track_id: str
    label: str
    color_index: int = 0
    times: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=float))
    f0_hz: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=float))
    is_reference: bool = False

    @property
    def color(self) -> str:
        """轨色（主题语义色轮转，与轨道头同口径）。"""
        return track_color(self.color_index)

    def voiced(self) -> np.ndarray:
        """有声帧掩码（NaN / 非正频率 = 未检出）。"""
        f0 = np.asarray(self.f0_hz, dtype=float)
        with np.errstate(invalid="ignore"):
            return np.isfinite(f0) & (f0 > 0)


@dataclass
class PanelInfo:
    """多图分离中的一个子图（`series` 为空 = 该轨暂无结果，仅呈空图 + 轨名）。"""

    rect: QRectF
    track_id: str | None
    label: str
    series: TrackSeries | None = None


def series_from_cache(
    session,
    cache,
    *,
    kind: str = PITCH_KIND,
    reference_id=None,
) -> list[TrackSeries]:
    """从 T-1008 逐轨结果缓存取各轨 F0 序列（含对齐偏移）；无结果轨不产生序列。

    仅消费 `times` / `f0_hz`（Hz 域），不做任何量化统计。
    """
    if session is None or cache is None:
        return []
    out: list[TrackSeries] = []
    for track in session.tracks():
        result = cache.get(TrackResultCache.key(track.track_id, kind, None))
        if result is None:
            continue
        times = np.asarray(getattr(result, "times", ()), dtype=float)
        f0 = np.asarray(getattr(result, "f0_hz", ()), dtype=float)
        if times.size == 0 or f0.size == 0:
            continue
        n = min(times.size, f0.size)
        times, f0 = times[:n], f0[:n]
        offset_ms = float(getattr(track, "offset_ms", 0.0) or 0.0)
        if offset_ms:
            times = shifted_times(times, offset_ms)
        out.append(
            TrackSeries(
                track_id=track.track_id,
                label=str(getattr(track, "label", "")) or str(track.track_id),
                color_index=int(getattr(track, "color_index", 0) or 0),
                times=times,
                f0_hz=f0,
                is_reference=(reference_id is not None
                              and track.track_id == reference_id),
            )
        )
    return out


def build_density_heatmap(
    series_list,
    view_range,
    *,
    time_bins: int = HEATMAP_TIME_BINS,
    freq_bins: int = HEATMAP_FREQ_BINS,
    fmin: float | None = None,
    fmax: float | None = None,
) -> np.ndarray:
    """全部轨 F0 的时间-频率密度（numpy 直方图聚合，Overview 范式）。

    返回 `(freq_bins, time_bins)` 计数矩阵（行 = 频率由低到高）；无数据 → 全零矩阵。
    """
    matrix = np.zeros((int(freq_bins), int(time_bins)), dtype=float)
    times_all, f0_all = [], []
    for series in series_list or ():
        mask = series.voiced()
        if not mask.any():
            continue
        times_all.append(np.asarray(series.times, dtype=float)[mask])
        f0_all.append(np.asarray(series.f0_hz, dtype=float)[mask])
    if not times_all:
        return matrix
    times = np.concatenate(times_all)
    f0 = np.concatenate(f0_all)
    t0, t1 = (float(view_range[0]), float(view_range[1]))
    if t1 <= t0:
        t1 = t0 + _MIN_SPAN_S
    lo = float(fmin) if fmin is not None else float(np.min(f0))
    hi = float(fmax) if fmax is not None else float(np.max(f0))
    if hi <= lo:
        hi = lo + _MIN_SPAN_S
    keep = (times >= t0) & (times <= t1)
    if not keep.any():
        return matrix
    hist, _edges_t, _edges_f = np.histogram2d(
        f0[keep], times[keep],
        bins=[int(freq_bins), int(time_bins)],
        range=[[lo, hi], [t0, t1]],
    )
    return hist


def heatmap_default(track_count: int) -> bool:
    """热图默认开关：轨数 < 阈值 → 默认关（用户可显式开启）。"""
    return int(track_count) >= HEATMAP_MIN_TRACKS


# ----------------------------------------------------------------------
# 呈现部件
# ----------------------------------------------------------------------


class ComparePresentWidget(QWidget):
    """多轨对比呈现部件（一图 / 多图 + 可选密度热图；共享播放头与缩放）。

    交互沿用分析视图手势语义：单击定位（共享播放头）/ 拖 = 共享选区 /
    Alt+拖 = scrub / 滚轮 = 以光标为中心缩放。播放头与视图范围均向宿主发信号，
    由宿主与轨道区互相同步（D1/D2）。
    """

    playheadMoved = pyqtSignal(float)
    selectionChanged = pyqtSignal(object)
    viewRangeChanged = pyqtSignal(tuple)
    analyzeRequested = pyqtSignal()
    modeChanged = pyqtSignal(str)
    heatmapToggled = pyqtSignal(bool)

    def __init__(self, session=None, cache=None, parent=None, *, with_mode_bar=True):
        super().__init__(parent)
        self.setObjectName("comparePresent")
        self._session = session
        self._cache = cache
        self._view_range = (0.0, 1.0)
        self._playhead = 0.0
        self._selection: tuple[float, float] | None = None
        self._mode = MODE_SINGLE
        self._heatmap = False
        self._heatmap_user: bool | None = None
        self._reference_id = None
        self._series: list[TrackSeries] = []
        self._freq_range: tuple[float, float] | None = None   # M8：freq_range 缓存
        self._drag_anchor: float | None = None
        self._scrubbing = False
        self._paint_stats = {"panels": 0, "curves": 0, "waveforms": 0,
                             "legend": 0, "heatmap": False,
                             "diff_rows": 0, "diff_over_segments": 0,
                             "diff_truncated": 0, "diff_row_order": [],
                             "y_ticks": 0, "grid_lines": 0, "time_ticks": 0,
                             "tuning_lines": 0, "reference_line": 0, "colorbar": False}
        # T-1005：差异量化状态（阈值取自 Settings；单位默认 cents = 12TET 先行）
        self._diff: compare_diff.DiffSummary | None = None
        self._diff_threshold = compare_diff.DEFAULT_THRESHOLD_CENTS
        self._diff_unit = compare_diff.DEFAULT_UNIT
        # T-1034a 轮 B：当前生效律制（宿主唯一取用点推送；None = 未注入）
        self._tuning = None
        # T-1087 M7：差异计算投递缝（None ⇒ 就地同步算，裸部件行为逐字不变）
        self._diff_deliver = None
        self._diff_inflight = False
        self._diff_gen = 0
        # T-1005：悬停读数（T-326 Pδ 机制复用：overlay + 可选上抛回调）
        self._on_hover_readout = None
        self._last_hover_at = 0.0

        sp = TOKENS["spacing"]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(sp["xs"], sp["xs"], sp["xs"], sp["xs"])
        outer.setSpacing(sp["xs"])
        outer.addLayout(self._build_toolbar(with_mode_bar))
        self.lbl_hint = QLabel(tr("multitrack.compare.no_result"), self)
        self.lbl_hint.setObjectName("compareHint")
        self.lbl_hint.setWordWrap(True)
        outer.addWidget(self.lbl_hint)
        self.setMinimumHeight(sp["xxl"] * 4)
        self.setMouseTracking(True)
        self._hover_overlay = QLabel(self)
        self._hover_overlay.setObjectName("compareHoverReadout")
        self._hover_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._style_readout_label(self._hover_overlay)
        self._hover_overlay.hide()
        self._refresh_style = theme.style_when_theme(self, self._on_theme_refresh)

    # ------------------------------------------------------------------
    # 工具栏（模式切换控件 / 热图开关 / 逐轨分析入口 / T-1005 差异区）
    # ------------------------------------------------------------------

    def _build_toolbar(self, with_mode_bar: bool) -> QHBoxLayout:
        sp = TOKENS["spacing"]
        bar = QHBoxLayout()
        bar.setSpacing(sp["sm"])
        self.lbl_title = QLabel(tr("multitrack.compare.title"), self)
        self.lbl_title.setObjectName("compareTitle")
        bar.addWidget(self.lbl_title)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.btn_mode_single = QToolButton(self)
        self.btn_mode_single.setObjectName("compareModeSingle")
        self.btn_mode_single.setText(tr("multitrack.compare.mode_single"))
        self.btn_mode_single.setToolTip(tr("multitrack.compare.mode_single_tip"))
        self.btn_mode_single.setCheckable(True)
        self.btn_mode_single.setChecked(True)
        self.btn_mode_grid = QToolButton(self)
        self.btn_mode_grid.setObjectName("compareModeGrid")
        self.btn_mode_grid.setText(tr("multitrack.compare.mode_grid"))
        self.btn_mode_grid.setToolTip(tr("multitrack.compare.mode_grid_tip"))
        self.btn_mode_grid.setCheckable(True)
        self.mode_group.addButton(self.btn_mode_single)
        self.mode_group.addButton(self.btn_mode_grid)
        self.btn_mode_single.toggled.connect(
            lambda on: on and self.set_mode(MODE_SINGLE)
        )
        self.btn_mode_grid.toggled.connect(lambda on: on and self.set_mode(MODE_GRID))
        if with_mode_bar:
            bar.addWidget(self.btn_mode_single)
            bar.addWidget(self.btn_mode_grid)
        else:
            self.btn_mode_single.hide()
            self.btn_mode_grid.hide()

        self.chk_heatmap = QCheckBox(tr("multitrack.compare.heatmap"), self)
        self.chk_heatmap.setObjectName("compareHeatmap")
        self.chk_heatmap.setToolTip(tr("multitrack.compare.heatmap_tip"))
        self.chk_heatmap.toggled.connect(self._on_heatmap_toggled)
        bar.addWidget(self.chk_heatmap)
        bar.addStretch(1)

        self.lbl_reference = QLabel(self)
        self.lbl_reference.setObjectName("compareReference")
        bar.addWidget(self.lbl_reference)
        self.cmb_reference = QComboBox(self)
        self.cmb_reference.setObjectName("compareReferencePick")
        self.cmb_reference.setToolTip(tr("multitrack.compare.reference_tip"))
        self.cmb_reference.currentIndexChanged.connect(self._on_reference_picked)
        bar.addWidget(self.cmb_reference)

        self.btn_analyze = QToolButton(self)
        self.btn_analyze.setObjectName("compareAnalyze")
        self.btn_analyze.setText(tr("multitrack.compare.analyze"))
        self.btn_analyze.setToolTip(tr("multitrack.compare.analyze_tip"))
        self.btn_analyze.clicked.connect(
            lambda _checked=False: self.analyzeRequested.emit()
        )
        bar.addWidget(self.btn_analyze)

        # T-1005 差异区：接通 T-1009 预留槽（差异统计）+ 单位切换 + 差异表导出
        self.btn_diff_stats = QPushButton(tr("multitrack.compare.diff_stats"), self)
        self.btn_diff_stats.setObjectName("compareDiffStats")
        self.btn_diff_stats.setToolTip(tr("multitrack.compare.diff_tip"))
        self.btn_diff_stats.setEnabled(False)
        self.btn_diff_stats.clicked.connect(self._on_diff_stats_clicked)
        bar.addWidget(self.btn_diff_stats)

        self.chk_diff_cents = QCheckBox(tr("multitrack.compare.diff_unit_cents"), self)
        self.chk_diff_cents.setObjectName("compareDiffUnitCents")
        self.chk_diff_cents.setToolTip(tr("multitrack.compare.diff_unit_tip"))
        self.chk_diff_cents.setChecked(self._diff_unit == compare_diff.UNIT_CENTS)
        self.chk_diff_cents.toggled.connect(self._on_diff_unit_toggled)
        bar.addWidget(self.chk_diff_cents)

        self.btn_diff_csv = QToolButton(self)
        self.btn_diff_csv.setObjectName("compareDiffExport")
        self.btn_diff_csv.setText(tr("multitrack.compare.diff_export"))
        self.btn_diff_csv.setToolTip(tr("multitrack.compare.diff_export_tip"))
        self.btn_diff_csv.setEnabled(False)
        self.btn_diff_csv.clicked.connect(
            lambda _checked=False: self.export_diff_csv()
        )
        bar.addWidget(self.btn_diff_csv)
        return bar

    # ------------------------------------------------------------------
    # 会话 / 缓存 / 状态
    # ------------------------------------------------------------------

    def session(self):
        return self._session

    def set_session(self, session) -> None:
        self._session = session
        self.refresh()

    def set_result_cache(self, cache) -> None:
        """注入多轨结果缓存域（T-1008；主窗持有，跨模式切换保留）。"""
        self._cache = cache
        self.refresh()

    def result_cache(self):
        return self._cache

    def series(self) -> list[TrackSeries]:
        """当前有结果的轨序列（一图叠绘用）。"""
        return list(self._series)

    def has_results(self) -> bool:
        return bool(self._series)

    def view_range(self) -> tuple[float, float]:
        return self._view_range

    def set_view_range(self, t0: float, t1: float) -> None:
        lo, hi = (float(t0), float(t1)) if t1 >= t0 else (float(t1), float(t0))
        if hi - lo < _MIN_SPAN_S:
            hi = lo + _MIN_SPAN_S
        self._view_range = (lo, hi)
        self.update()

    def playhead(self) -> float:
        return self._playhead

    def set_playhead(self, value: float) -> None:
        self._playhead = max(0.0, float(value))
        self.update()

    def selection(self):
        return self._selection

    def set_selection(self, value) -> None:
        if value is None:
            self._selection = None
        else:
            self._selection = (float(value[0]), float(value[1]))
        self.update()

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        mode = str(mode)
        if mode not in MODES or mode == self._mode:
            return
        self._mode = mode
        self._sync_mode_buttons()
        self.modeChanged.emit(mode)
        self.update()

    def toggle_mode(self) -> str:
        self.set_mode(MODE_GRID if self._mode == MODE_SINGLE else MODE_SINGLE)
        return self._mode

    def heatmap_enabled(self) -> bool:
        return self._heatmap

    def set_heatmap(self, on: bool, *, user: bool = True) -> None:
        self._heatmap = bool(on)
        if user:
            self._heatmap_user = bool(on)
        self.chk_heatmap.blockSignals(True)
        self.chk_heatmap.setChecked(self._heatmap)
        self.chk_heatmap.blockSignals(False)
        self.heatmapToggled.emit(self._heatmap)
        self.update()

    def reference_id(self):
        return self._reference_id

    def set_reference(self, track_id) -> None:
        """指定参考轨（默认首轨，与 T-1005 参考轨口径一致）。"""
        self._reference_id = track_id
        self.refresh()

    def t_at(self, x: float) -> float:
        rect = self._data_rect()
        if rect.width() <= 0:
            return self._view_range[0]
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        return t0 + (float(x) - rect.left()) / rect.width() * span

    def x_at(self, t: float) -> float:
        rect = self._data_rect()
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        return rect.left() + (float(t) - t0) / span * rect.width()

    def zoom(self, factor: float, center: float | None = None) -> None:
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        pivot = t0 + span / 2.0 if center is None else float(center)
        new_span = max(span * float(factor), _MIN_SPAN_S)
        lo = pivot - (pivot - t0) * (new_span / span)
        self.set_view_range(lo, lo + new_span)
        self.viewRangeChanged.emit(self._view_range)

    def freq_range(self) -> tuple[float, float]:
        """频率显示范围（Hz；按当前序列自适应，无数据回落默认量程）。

        ★ T-1087 M8：带缓存。本函数只依赖 ``_series``（与视图范围无关），改前却由
        每条曲线的 ``curve_points`` 各调一次 ⇒ 每帧对全部轨数组做 N² 遍 min/max 重扫。
        序列换代点（``refresh`` / 改参考轨）负责置空缓存。
        """
        cached = self._freq_range
        if cached is not None:
            return cached
        lo = hi = None
        for series in self._series:
            mask = series.voiced()
            if not mask.any():
                continue
            values = np.asarray(series.f0_hz, dtype=float)[mask]
            v_lo, v_hi = float(np.min(values)), float(np.max(values))
            lo = v_lo if lo is None else min(lo, v_lo)
            hi = v_hi if hi is None else max(hi, v_hi)
        if lo is None or hi is None or hi <= lo:
            result = (DEFAULT_FMIN, DEFAULT_FMAX)
        else:
            result = (lo, hi)
        self._freq_range = result
        return result

    # ------------------------------------------------------------------
    # 布局与几何
    # ------------------------------------------------------------------

    def _data_rect(self) -> QRectF:
        """曲线实际绘制区 = 绘图矩形让出左音名轴带与下时间轴带（T-1089 N-C）。

        时间↔像素映射（:meth:`x_at` / :meth:`t_at`）与播放头、选区、差异条**一律以此为
        准** ⇒ 轴上标注与曲线、色段同一条竖直基线，不会出现"针偏离曲线"。
        """
        rect = self._plot_rect()
        width = max(1.0, rect.width() - AXIS_LABEL_GUTTER_W)
        height = max(1.0, rect.height() - AXIS_TIME_BAND_H)
        return QRectF(rect.left() + AXIS_LABEL_GUTTER_W, rect.top(), width, height)

    def _header_band_bottom(self) -> float:
        widgets = [
            getattr(self, "lbl_title", None),
            getattr(self, "chk_heatmap", None),
            getattr(self, "lbl_reference", None),
            getattr(self, "cmb_reference", None),
            getattr(self, "btn_analyze", None),
            getattr(self, "btn_diff_stats", None),
            getattr(self, "lbl_hint", None),
        ]
        bottom = 0.0
        for w in widgets:
            if w is not None and w.isVisible():
                g = w.geometry()
                b = float(g.bottom())
                if b > bottom:
                    bottom = b
        return bottom

    def _plot_rect(self) -> QRectF:
        pad = float(TOKENS["spacing"]["sm"])
        header_bottom = self._header_band_bottom()
        top = max(pad, header_bottom + pad)
        height = max(1.0, self.height() - top - pad)
        bar_height = self._diff_bar_height()
        if bar_height > 0.0:                     # T-1005：差异条存在时让位（否则几何零变化）
            height = max(1.0, height - bar_height - DIFF_BAR_GAP)
        return QRectF(
            pad, top,
            max(1.0, self.width() - 2.0 * pad),
            height,
        )

    def _diff_bar_height(self) -> float:
        """差异条总高（无差异/无可比帧 → 0，此时不占位）。

        ★ T-1089 N-B：轨数超过 :data:`DIFF_BAR_MAX_ROWS` 时追加一条**截断提示行**
        （改前静默只画前 4 行、5 轨会话实画 4 缺 1 无任何告知）。
        """
        summary = self._diff
        if summary is None or not summary.has_data():
            return 0.0
        rows = min(len(summary.tracks), DIFF_BAR_MAX_ROWS)
        if rows <= 0:
            return 0.0
        height = float(rows) * DIFF_BAR_ROW_H + float(rows - 1) * DIFF_BAR_GAP
        if len(summary.tracks) > DIFF_BAR_MAX_ROWS:
            height += DIFF_BAR_GAP + DIFF_BAR_NOTICE_H
        return height

    def _diff_rect(self) -> QRectF:
        """差异条几何（沿时间轴；无差异 → 零高矩形）。

        ★ T-1089 N-C：横向取 :meth:`_data_rect` 的左右界 ⇒ 超阈色段与曲线、播放头
        同一条基线（改前差一条左边界，色段整体相对曲线左偏一个轴带宽）。
        """
        pad = float(TOKENS["spacing"]["sm"])
        height = self._diff_bar_height()
        if height <= 0.0:
            return QRectF(pad, float(self.height()) - pad, 0.0, 0.0)
        data = self._data_rect()
        return QRectF(
            data.left(), float(self.height()) - pad - height,
            data.width(), height,
        )

    def diff_bar_geometry(self) -> dict:
        """差异条几何口径（测试用：无硬编码绝对值，均取自实时控件尺寸）。"""
        rect = self._diff_rect()
        summary = self._diff
        has_data = bool(summary is not None and summary.has_data())
        return {
            "height": rect.height(), "width": rect.width(),
            "rows": min(len(summary.tracks), DIFF_BAR_MAX_ROWS) if has_data else 0,
            "hidden_rows": (max(0, len(summary.tracks) - DIFF_BAR_MAX_ROWS)
                            if has_data else 0),
            "row_height": DIFF_BAR_ROW_H, "gap": DIFF_BAR_GAP,
            "notice_height": DIFF_BAR_NOTICE_H,
        }

    def panels(self) -> list[PanelInfo]:
        """子图布局：一图 = 单面板；多图 = 每轨一图（布局数 = 轨数）。

        ★ T-1089 N-C：面板矩形取 :meth:`_data_rect` 的等分（轴带不参与等分），
        故多图窄高时标签仍落在同一左带内。
        """
        rect = self._data_rect()
        if self._mode != MODE_GRID:
            return [PanelInfo(rect, None, "", None)]
        tracks = self._session.tracks() if self._session is not None else []
        if not tracks:
            return [PanelInfo(rect, None, "", None)]
        by_id = {s.track_id: s for s in self._series}
        height = rect.height() / len(tracks)
        out: list[PanelInfo] = []
        for index, track in enumerate(tracks):
            panel_rect = QRectF(
                rect.left(), rect.top() + index * height, rect.width(), height
            )
            out.append(
                PanelInfo(panel_rect, track.track_id,
                          str(getattr(track, "label", "")) or str(track.track_id),
                          by_id.get(track.track_id))
            )
        return out

    def legend(self) -> list[tuple[str, str, str]]:
        """图例项（轨 id, 轨名, 颜色）。"""
        return [(s.track_id, s.label, s.color) for s in self._series]

    def pen_spec(self, series: TrackSeries) -> tuple[str, float, bool]:
        """折线笔规格（色, 线宽, 是否虚线）：参考轨 = 加粗 + 虚线基准强调。"""
        if series.is_reference:
            return (series.color, REFERENCE_WIDTH, True)
        return (series.color, CURVE_WIDTH, False)

    def curve_points(self, series: TrackSeries, rect: QRectF | None = None):
        """该轨 F0 在当前视图下的部件坐标折线点（未检出帧剔除）。"""
        rect = rect if rect is not None else self._data_rect()
        mask = series.voiced() & np.isfinite(series.times)
        times = np.asarray(series.times, dtype=float)[mask]
        f0 = np.asarray(series.f0_hz, dtype=float)[mask]
        if times.size == 0:
            return np.zeros((0, 2), dtype=float)
        t0, t1 = self._view_range
        keep = (times >= t0) & (times <= t1)
        times, f0 = times[keep], f0[keep]
        if times.size == 0:
            return np.zeros((0, 2), dtype=float)
        lo, hi = self.freq_range()
        ln_lo, ln_hi = np.log(max(lo, 1e-6)), np.log(max(hi, lo * 1.0001))
        span = max(t1 - t0, _MIN_SPAN_S)
        xs = rect.left() + (times - t0) / span * rect.width()
        ys = rect.bottom() - (
            np.log(np.maximum(f0, 1e-6)) - ln_lo
        ) / (ln_hi - ln_lo) * rect.height()
        ys = np.clip(ys, rect.top(), rect.bottom())
        return np.column_stack([xs, ys])

    def curve_segments(self, series: TrackSeries, rect: QRectF | None = None):
        """折线分段（未检出造成的空档断开，避免跨静音连线）。"""
        rect = rect if rect is not None else self._data_rect()
        points = self.curve_points(series, rect)
        if points.shape[0] < 2:
            return [] if points.shape[0] == 0 else [points]
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        threshold = max(2.0, rect.width() / span * _GAP_SECONDS)
        cuts = np.where(np.abs(np.diff(points[:, 0])) > threshold)[0] + 1
        return [seg for seg in np.split(points, cuts) if seg.shape[0] >= 1]

    def paint_stats(self) -> dict:
        """最近一次绘制的统计（面板数 / 折线数 / 波形数 / 图例数 / 热图层）。"""
        return dict(self._paint_stats)

    def refresh(self) -> None:
        """按当前会话 + 缓存重建呈现（轨集 / 对齐偏移 / 结果变化后调用）。"""
        session = self._session
        tracks = session.tracks() if session is not None else []
        if tracks and self._reference_id is None:
            self._reference_id = tracks[0].track_id       # 参考轨默认首轨
        if self._reference_id is not None and all(
            t.track_id != self._reference_id for t in tracks
        ):
            self._reference_id = tracks[0].track_id if tracks else None
        self._series = series_from_cache(
            session, self._cache, reference_id=self._reference_id
        )
        self._freq_range = None            # T-1087 M8：序列换代 → 频率范围缓存作废
        if self._heatmap_user is None:
            self._heatmap = heatmap_default(len(tracks))
        else:
            self._heatmap = bool(self._heatmap_user)
        self.chk_heatmap.blockSignals(True)
        self.chk_heatmap.setChecked(self._heatmap)
        self.chk_heatmap.blockSignals(False)
        self.btn_analyze.setEnabled(bool(tracks))
        self.lbl_hint.setVisible(bool(tracks) and not self._series)
        self.lbl_hint.setText(tr("multitrack.compare.no_result"))
        self._invalidate_diff()          # T-1005：轨集/结果变化 → 差异作废重算
        self._update_diff_controls()
        self._update_reference_label()
        self.update()

    # ------------------------------------------------------------------
    # T-1005 差异量化：预留槽接通 / 计算 / 悬停读数 / CSV 出口
    # ------------------------------------------------------------------

    def diff(self):
        """最近一次差异汇总（未计算 → None）。"""
        return self._diff

    def diff_threshold_cents(self) -> float:
        """当前报警阈值（cents；取自 Settings，默认 50）。"""
        return self._diff_threshold

    def diff_unit(self) -> str:
        return self._diff_unit

    def set_diff_unit(self, unit: str) -> None:
        """差异单位切换（hz / cents；默认 cents = 12TET 先行；不接入任意音律）。"""
        unit = str(unit)
        if unit not in compare_diff.UNITS or unit == self._diff_unit:
            return
        self._diff_unit = unit
        self.chk_diff_cents.blockSignals(True)
        self.chk_diff_cents.setChecked(unit == compare_diff.UNIT_CENTS)
        self.chk_diff_cents.blockSignals(False)
        if self._diff is not None:
            self._diff.unit = unit
        self.update()

    def diff_available(self) -> bool:
        """差异统计可用条件：**≥2 轨且非参考轨存在 F0 结果**（放行令口径）。"""
        tracks = self._session.tracks() if self._session is not None else []
        if len(tracks) < 2:
            return False
        return any(series.track_id != self._reference_id for series in self._series)

    def set_diff_deliver(self, fn) -> None:
        """注入差异计算投递器（T-1087 M7）。

        ``fn(title, work, on_done, on_settle) -> Any``：宿主把 ``work(reporter)``
        （纯量化帧循环·零 UI 触碰）交任务中心 worker，终态在主线程 ``on_done``
        回填。``fn=None`` ⇒ 就地同步算（裸部件 / 离屏单测口径逐字不变）。
        """
        self._diff_deliver = fn

    def diff_deliver(self):
        """当前差异投递器（None = 就地同步算）。"""
        return self._diff_deliver

    def diff_inflight(self) -> bool:
        """差异任务是否在途（连点 / 律制连推不重投）。"""
        return self._diff_inflight

    def _invalidate_diff(self) -> None:
        """作废旧差异并**递增世代**（在途 worker 结果随之失效，不回填脏值）。"""
        self._diff = None
        self._diff_gen += 1

    def _build_diff(self, tuning=None):
        """就地算差异并回填（量化层 ``compare_diff``；阈值取自 Settings）。

        ``tuning``（T-1034a 轮 B）：显式传入优先，否则用 :meth:`set_tuning` 注入值。
        主线程与 worker 回填两条路共用本函数 ⇒ 口径唯一。
        """
        effective_tuning = self._tuning if tuning is None else tuning
        self._diff_threshold = compare_diff.settings_threshold()
        summary = compare_diff.build_diff_summary(
            self._series, reference_id=self._reference_id,
            threshold_cents=self._diff_threshold, unit=self._diff_unit,
            rms_provider=self._rms_source, duration_provider=self._duration_of,
            tuning=effective_tuning,
        )
        self._diff = summary
        self._update_diff_hint()
        self._update_diff_controls()
        self.update()
        return summary

    def compute_diff(self, *, tuning=None):
        """按当前序列 + 参考轨计算差异。

        ★ T-1087 M7：注入投递器 ⇒ **后台化**（投递任务中心、立即返回 ``None``，
        终态由 ``on_done`` 主线程回填 hint / 差异条 / 导出可用性）；未注入 ⇒
        保持原样就地算并返回 summary（裸部件既有契约与返回值逐字不变）。
        """
        if not self.diff_available():
            return None
        if self._diff_deliver is None:
            return self._build_diff(tuning)
        self._submit_diff(tuning)
        return None

    def _submit_diff(self, tuning=None) -> None:
        """差异计算投递（worker 只算纯量化·回填只在主线程）。

        序列 / 参考轨 / 单位 / 阈值 / rms·时长取数结果全部在**主线程快照**后交给
        worker（``_rms_source`` 只读已驻留样本、不触发载入），worker 内零部件状态
        触碰；世代号在回填时比对 ⇒ 期间换轨/改参考轨/切律制的旧结果一律作废。
        """
        if self._diff_inflight:
            return
        series = list(self._series)
        reference_id = self._reference_id
        unit = self._diff_unit
        threshold = compare_diff.settings_threshold()
        effective_tuning = self._tuning if tuning is None else tuning
        rms_snapshot = {s.track_id: self._rms_source(s.track_id) for s in series}
        duration_snapshot = {s.track_id: self._duration_of(s.track_id) for s in series}

        def work(_reporter):
            return compare_diff.build_diff_summary(
                series, reference_id=reference_id, threshold_cents=threshold,
                unit=unit,
                rms_provider=lambda tid: rms_snapshot.get(tid),
                duration_provider=lambda tid: duration_snapshot.get(tid),
                tuning=effective_tuning,
            )

        def on_done(summary) -> None:
            if summary is None or generation != self._diff_gen:
                return                              # 已作废（轨集/律制/单位变了）
            self._diff = summary
            self._diff_threshold = threshold
            self._update_diff_hint()
            self._update_diff_controls()
            self.update()

        def on_settle() -> None:
            self._diff_inflight = False

        self._diff_inflight = True
        self._invalidate_diff()                     # 本次计算期间旧值一律作废
        generation = self._diff_gen                 # ★ 作废之后取世代（否则恒不等）
        entry = self._diff_deliver(
            tr("task_center.title.multitrack_diff").format(n=len(series)),
            work, on_done, on_settle,
        )
        if entry is None:
            on_settle()

    def set_tuning(self, tuning) -> None:
        """注入当前律制（T-1034a 轮 B，宿主唯一取用点推送）。

        换律制必须作废旧差异并按新律制重算（同 T-1005 范式），
        否则悬停读数/音级归属会取旧值。

        ★ T-1087 M7：接了投递器 ⇒ 重算走 worker（本方法随之**不再阻塞主线程**；
        宿主 `_apply_tuning_overlay` 每次推律制都会经这里）。未注入 ⇒ 原同步重算。
        """
        self._tuning = tuning
        self._invalidate_diff()                    # 换律制 → 差异作废重算
        self.compute_diff()

    def tuning(self):
        """当前注入的律制（未注入 → None）。"""
        return self._tuning

    def hover_readout_at(self, t: float) -> str:
        """差异悬停读数（纯计算，测试直调）：各非参考轨最近配对帧的 Δ 值。

        注入律制时追加语言中立音级 ``#<音级>``（取自与 Δ 值同一配对帧索引），并按
        T-1089 N-D 再追加该音级的「音名±cent」（``A4+12c`` 式·无律制时二者皆无）。
        """
        summary = self._diff
        if summary is None or not summary.tracks:
            return ""
        tuning = self._tuning
        parts = [f"t={float(t):.3f}s"]
        for track in summary.tracks:
            value = self._diff_value_at(track, float(t))
            if value is None:
                parts.append(f"{track.label}: {tr('multitrack.compare.diff_no_pair')}")
                continue
            text = (
                f"{track.label}: "
                f"{compare_diff.format_delta(value, self._diff_unit)}"
            )
            degrees = getattr(track, "degrees", None)
            if tuning is not None and degrees is not None:
                index = self._diff_frame_index(track, float(t))
                if index is not None and index < int(np.asarray(degrees).size):
                    degree = int(np.asarray(degrees)[index])
                    text = f"{text} #{degree}"
                    # T-1089 N-D：裸音级读不出"这是哪个音、差多少"⇒ 追加音名±cent
                    label = self._degree_pitch_label(degree)
                    if label:
                        text = f"{text} ({label})"
            parts.append(text)
        return " | ".join(parts)

    def export_diff_csv(self, path=None):
        """导出差异表 CSV（表头 = 轨/时间/ΔHz/Δcent/超阈标记/参考轨名）。

        `path=None` 走系统保存框（既有导出豁免口径）；写盘范式 = `csv.writer` + `repr`。
        """
        if self._diff is None:
            # 导出 = 用户一次性主动动作（保存框本就阻塞主线程）⇒ 一律就地算出
            # 表来，不走后台投递（否则 fire-and-forget 会让"点了导出却没表"）。
            self._build_diff()
        summary = self._diff
        if summary is None or not summary.has_data():
            self._toast(tr("multitrack.compare.diff_export_empty"), level="warning")
            return None
        if path is None:
            from PyQt6.QtWidgets import QFileDialog

            path, _selected = QFileDialog.getSaveFileName(
                self, tr("multitrack.compare.diff_export_title"),
                "multitrack_diff.csv", "CSV (*.csv)",
            )
        if not path:
            return None
        target = str(path)
        if not target.lower().endswith(".csv"):
            target += ".csv"
        try:
            compare_diff.write_diff_csv(target, summary)
        except Exception as exc:  # noqa: BLE001 - 导出失败以 toast 反馈，不抛
            self._toast(
                f"{tr('multitrack.compare.diff_export_failed')}: {exc}", level="error"
            )
            return None
        self._toast(
            f"{tr('multitrack.compare.diff_export_done')} · {target}", level="success"
        )
        return target

    def _on_diff_stats_clicked(self, _checked: bool = False) -> None:
        """差异统计按钮：不可用（<2 轨 / 无非参考结果）才提示。

        原实现按 ``compute_diff() is None`` 判空——M7 后台化后"已投递"同样返回
        ``None``，据此提示会在任务刚起时误弹 warning ⇒ 改按可用性判定。
        """
        if not self.diff_available():
            self._toast(tr("multitrack.compare.diff_export_empty"), level="warning")
            return
        self.compute_diff()

    def _on_diff_unit_toggled(self, checked: bool) -> None:
        self.set_diff_unit(
            compare_diff.UNIT_CENTS if checked else compare_diff.UNIT_HZ
        )

    def _update_diff_controls(self) -> None:
        available = self.diff_available()
        self.btn_diff_stats.setEnabled(available)
        self.btn_diff_csv.setEnabled(
            bool(available and self._diff is not None and self._diff.has_data())
        )

    def _update_diff_hint(self) -> None:
        """差异摘要文案（含阈值与「报警阈值，非精度承诺」注记；帧率不一致加注）。

        ★ T-1089 N-B：``compare_diff`` 已算出逐轨 mean/abs̄/max/超阈占比与全轨一致性
        关键键，改前只露 ``max_over_ratio`` 一个量（PI-T81 DIM3 3.2「算了看不见」）⇒
        现追加全轨概览 + 逐轨量化（按超阈占比降序、超出 :data:`DIFF_HINT_MAX_TRACKS`
        显式告知未列数）。汇总行仍是**首段**、注记仍是**末段**（既有测档钉此两面）。
        """
        summary = self._diff
        if summary is None or not summary.tracks:
            self.lbl_hint.setText(tr("multitrack.compare.no_result"))
            self.lbl_hint.setVisible(bool(self._session is not None and len(self._session))
                                     and not self._series)
            return
        stats = summary.consistency()
        ratio = stats["max_over_ratio"]
        text = tr("multitrack.compare.diff_summary").format(
            threshold=f"{summary.threshold_cents:g}",
            tracks=stats["compared_tracks"],
            ratio="--" if ratio is None else f"{ratio:.1%}",
        )
        details = self._diff_detail_text(summary, stats)
        if details:
            text = f"{text} · {details}"
        note = tr("multitrack.compare.diff_threshold_note")
        if summary.pairing and not summary.pairing.get("frame_rates_equal", True):
            note = f"{note} · {tr('multitrack.compare.diff_pairing_note')}"
        # T-1034a 轮 B：汇总行挂律制名（模型自带数据文本，非翻译键）
        tuning = self._tuning
        if tuning is not None and getattr(tuning, "name", ""):
            note = f"{note} · {tuning.name}"
        self.lbl_hint.setText(f"{text} · {note}")
        self.lbl_hint.setVisible(True)

    @staticmethod
    def _cents_text(value) -> str:
        """cents 量读数（无值 → ``--``，不臆造）。"""
        return "--" if value is None else f"{float(value):.1f}c"

    @staticmethod
    def _diff_tracks_by_severity(tracks):
        """按超阈占比**降序**（零配对/None 轨末位；稳定排序 ⇒ 同值保持原序）。"""
        def key(track):
            ratio = track.over_ratio
            return -(float(ratio) if ratio is not None else -1.0)

        return sorted(tracks, key=key)

    def _diff_detail_text(self, summary, stats) -> str:
        """全轨一致性关键键 + 逐轨量化（与差异条同序： worst-first）。"""
        parts: list[str] = []
        if stats["compared_tracks"]:
            parts.append(tr("multitrack.compare.diff_overview_stats").format(
                mean_abs=self._cents_text(stats["mean_abs_delta_cent"]),
                max_abs=self._cents_text(stats["max_abs_delta_cent"]),
                over_tracks=stats["tracks_with_any_over"],
                worst=stats["worst_track_label"] or "--",
            ))
        ranked = self._diff_tracks_by_severity(summary.tracks)
        listed = ranked[:DIFF_HINT_MAX_TRACKS]
        for track in listed:
            ratio = track.over_ratio
            parts.append(tr("multitrack.compare.diff_track_stats").format(
                label=track.label,
                mean_abs=self._cents_text(track.mean_abs_delta_cent),
                over="--" if ratio is None else f"{ratio:.1%}",
                max_abs=self._cents_text(track.max_abs_delta_cent),
            ))
        hidden = len(ranked) - len(listed)
        if hidden > 0:
            parts.append(tr("multitrack.compare.diff_more_tracks").format(n=hidden))
        derived = self._diff_analysis_text(summary)
        if derived:
            parts.append(derived)
        return " | ".join(parts)

    # ----- T-1089 N-E：呈现层只读派生指标（量化层零改·pcp/compare_diff 仅 import） -----

    def _sampled_frames(self, count: int) -> list[int]:
        """帧下标抽样（上限 :data:`DIFF_ANALYSIS_MAX_FRAMES`·均匀步进）。

        ``tuning.freq_to_degree`` 是纯 Python 换算 ⇒ 逐帧全算会在主线程回填时给出
        百毫秒级停顿（M7 后台化的初衷就是不在主线程跑帧循环）⇒ 分位/占比类指标
        按均匀抽样估计，量级足以支撑读数，且不随轨数放大。
        """
        total = int(count)
        if total <= 0:
            return []
        if total <= DIFF_ANALYSIS_MAX_FRAMES:
            return list(range(total))
        return [int(index) for index in
                np.linspace(0, total - 1, DIFF_ANALYSIS_MAX_FRAMES, dtype=int)]

    def _reference_series(self):
        """参考轨序列（共同音级指标的基准侧；找不到 → None）。"""
        if self._reference_id is None:
            return None
        return next((item for item in self._series
                     if item.track_id == self._reference_id), None)

    def _shared_degree_share(self, track, tuning, reference) -> float | None:
        """共同音级占比（**八度归一**后与参考轨同音级的配对帧比例）。

        量化层 ``degrees`` 只给被比较轨的音级（PI-T81 DIM1 1.6）⇒ 参考轨音级由呈现层
        以 ``tuning.freq_to_degree`` 自算：``TrackDiff.times`` 即参考轨的配对帧时间，
        就近取参考序列的有声帧，超出一帧移则丢弃该帧（不插值）。
        """
        degrees = getattr(track, "degrees", None)
        count = int(getattr(tuning, "degree_count", 0) or 0)
        if degrees is None or count <= 0 or reference is None:
            return None
        ref_times = np.asarray(reference.times, dtype=float)
        ref_f0 = np.asarray(reference.f0_hz, dtype=float)
        times = np.asarray(track.times, dtype=float)
        values = np.asarray(degrees)
        size = min(ref_times.size, ref_f0.size, times.size, int(values.size))
        if size == 0:
            return None
        hop = max(float(track.hop_s), _MIN_SPAN_S)
        same = 0
        considered = 0
        for index in self._sampled_frames(size):
            freq = float(ref_f0[index])
            if not np.isfinite(freq) or freq <= 0.0:
                continue
            if abs(float(ref_times[index]) - float(times[index])) > hop:
                continue
            ref_degree = int(tuning.freq_to_degree(freq))
            if (int(values[index]) - ref_degree) % count == 0:
                same += 1
            considered += 1
        return same / float(considered) if considered else None

    def _micro_remainder_cents(self, summary) -> float | None:
        """微分音余差：逐帧音级相对**最近半音**的偏离中位数（cents·12TET 恒 0）。

        与 :meth:`_degree_pitch_label` 同一口径（``SEMITONE_CENTS`` 就近取整后的余差），
        但取全轨中位数 ⇒ 「这套演唱相对平均律偏多少」有一个可比的单一数。
        """
        tuning = self._tuning
        if tuning is None:
            return None
        remainders: list[float] = []
        for track in summary.tracks:
            degrees = getattr(track, "degrees", None)
            if degrees is None:
                continue
            values = np.asarray(degrees)
            for index in self._sampled_frames(int(values.size)):
                cents = float(tuning.degree_to_cents(int(values[index])))
                remainders.append(abs(cents - _nearest_semitone_cents(cents)))
        return float(np.median(remainders)) if remainders else None

    def _diff_analysis_metrics(self, summary) -> dict:
        """``|Δ|`` 分位 / 系统偏差比 / 共同音级占比 / 微分音余差（全部只读派生）。"""
        entries = [track for track in summary.tracks if track.pairs]
        metrics = {"p50": None, "p95": None, "bias": None,
                   "shared": None, "remainder": self._micro_remainder_cents(summary)}
        if not entries:
            return metrics
        absolute = np.concatenate(
            [np.abs(np.asarray(track.delta_cent, dtype=float)) for track in entries]
        )
        if absolute.size:
            metrics["p50"] = float(np.percentile(absolute, 50))
            metrics["p95"] = float(np.percentile(absolute, 95))
        signed = np.array([track.mean_delta_cent for track in entries
                           if track.mean_delta_cent is not None], dtype=float)
        spread = np.array([track.mean_abs_delta_cent for track in entries
                           if track.mean_abs_delta_cent is not None], dtype=float)
        if signed.size and spread.size:
            denominator = float(np.mean(spread))
            if denominator > _MIN_SPAN_S:
                metrics["bias"] = float(np.mean(signed)) / denominator   # ∈[-1,1]
        tuning = self._tuning
        reference = self._reference_series()
        shares = [self._shared_degree_share(track, tuning, reference)
                  for track in entries] if tuning is not None and reference else []
        shares = [value for value in shares if value is not None]
        if shares:
            metrics["shared"] = float(np.mean(shares))
        return metrics

    def _diff_analysis_text(self, summary) -> str:
        metrics = self._diff_analysis_metrics(summary)
        if all(value is None for value in metrics.values()):
            return ""
        bias = metrics["bias"]
        shared = metrics["shared"]
        return tr("multitrack.compare.diff_analysis_stats").format(
            p50=self._cents_text(metrics["p50"]),
            p95=self._cents_text(metrics["p95"]),
            bias="--" if bias is None else f"{bias:+.2f}",
            shared="--" if shared is None else f"{shared:.1%}",
            remainder=self._cents_text(metrics["remainder"]),
        )

    def _rms_source(self, track_id):
        """电平差数据源：**仅当样本已在内存**时给值（不触发载入、不卡 UI）。"""
        track = self._track_for(track_id)
        data = getattr(track, "data", None)
        rate = float(getattr(track, "sample_rate", 0.0) or 0.0)
        if data is None or rate <= 0.0:
            return None
        return data, rate

    def _duration_of(self, track_id):
        """时长（秒；元数据不可得 → None，不臆造）。"""
        track = self._track_for(track_id)
        value = float(getattr(track, "duration", 0.0) or 0.0)
        return value if value > 0.0 else None

    def _diff_frame_index(self, track, t: float):
        """时间 t 处最近**配对帧**的索引（超出该轨帧移 → None）。"""
        times = np.asarray(track.times, dtype=float)
        if times.size == 0:
            return None
        index = int(np.clip(np.searchsorted(times, float(t)), 0, times.size - 1))
        candidates = [index] + ([index - 1] if index > 0 else [])
        best = min(candidates, key=lambda i: abs(float(times[i]) - float(t)))
        if abs(float(times[best]) - float(t)) > max(float(track.hop_s), _MIN_SPAN_S):
            return None
        return best

    def _diff_value_at(self, track, t: float):
        """时间 t 处最近**配对帧**的差异值（超出该轨帧移 → None）。"""
        best = self._diff_frame_index(track, float(t))
        if best is None:
            return None
        values = (np.asarray(track.delta_hz, dtype=float)
                  if self._diff_unit == compare_diff.UNIT_HZ
                  else np.asarray(track.delta_cent, dtype=float))
        if best >= values.size:
            return None
        return float(values[best])

    # ----- 悬停读数（T-326 Pδ 机制复用：只读 overlay + 可选上抛回调） -----

    @staticmethod
    def _style_readout_label(label: QLabel) -> None:
        """Pδ 读数小标签主题化（零硬编码 hex/px：颜色走 theme，字号走 QFont pt）。"""
        theme.style_when_theme(
            label, lambda c: f"color: {c['text']}; background: {c['panel']};"
        )
        font = label.font()
        font.setPointSize(9)
        label.setFont(font)

    def set_readout_overlay(self, text: str | None) -> None:
        """右上角只读 overlay 显示/隐藏（None 隐藏）。"""
        if not text:
            self._hover_overlay.hide()
            return
        self._hover_overlay.setText(text)
        self._hover_overlay.adjustSize()
        spacing = int(TOKENS["spacing"]["xs"])
        x = max(spacing, self.width() - self._hover_overlay.width() - spacing)
        self._hover_overlay.move(x, spacing)
        self._hover_overlay.show()

    def _hover_update(self, x: float) -> None:
        """鼠标移动：节流 ≤20Hz 更新 overlay 并上抛（差异未计算 → 不动）。"""
        now = time.monotonic()
        if now - self._last_hover_at < HOVER_THROTTLE_S:
            return
        self._last_hover_at = now
        text = self.hover_readout_at(self.t_at(x))
        if not text:
            return
        self.set_readout_overlay(text)
        if self._on_hover_readout is not None:
            self._on_hover_readout(text)

    def _hover_clear(self) -> None:
        """鼠标离开：立即隐藏 overlay 并上抛 None（不节流）。"""
        self._last_hover_at = 0.0
        self.set_readout_overlay(None)
        if self._on_hover_readout is not None:
            self._on_hover_readout(None)

    def _toast(self, message: str, *, level: str = "info") -> None:
        """非模态 toast 反馈（T-504f 口径：禁新建 QDialog/模态）。"""
        from acouscope.ui.widgets.toast import show_toast

        show_toast(self, message, level=level)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _update_reference_label(self) -> None:
        """参考轨文案 + 选择项（默认首轨；与差异量化参考轨口径一致）。"""
        self.lbl_reference.setText(tr("multitrack.compare.reference"))
        tracks = self._session.tracks() if self._session is not None else []
        self.cmb_reference.blockSignals(True)
        self.cmb_reference.clear()
        for track in tracks:
            label = str(getattr(track, "label", "")) or str(track.track_id)
            self.cmb_reference.addItem(label, track.track_id)
        index = self.cmb_reference.findData(self._reference_id)
        self.cmb_reference.setCurrentIndex(index if index >= 0 else 0)
        self.cmb_reference.blockSignals(False)

    def _on_reference_picked(self, index: int) -> None:
        """用户改选参考轨（重建序列，不递归触发下拉框刷新）。"""
        track_id = self.cmb_reference.itemData(int(index))
        if track_id is None or track_id == self._reference_id:
            return
        self._reference_id = track_id
        self._series = series_from_cache(
            self._session, self._cache, reference_id=track_id
        )
        self._freq_range = None            # T-1087 M8：序列换代 → 缓存作废
        self._invalidate_diff()              # T-1005：改参考轨 → 作废重算（含在途）
        self._update_diff_controls()
        self.update()

    def _sync_mode_buttons(self) -> None:
        for button, value in (
            (self.btn_mode_single, MODE_SINGLE),
            (self.btn_mode_grid, MODE_GRID),
        ):
            button.blockSignals(True)
            button.setChecked(self._mode == value)
            button.blockSignals(False)

    def _on_heatmap_toggled(self, checked: bool) -> None:
        self.set_heatmap(checked, user=True)

    def _on_theme_refresh(self, c: dict) -> str:
        return (
            f"QLabel#compareHint {{ color: {c['sub']}; }}"
            f" QLabel#compareTitle, QLabel#compareReference {{ color: {c['text']}; }}"
        )

    def _track_for(self, track_id):
        if self._session is None or track_id is None:
            return None
        return self._session.get(track_id)

    def _heatmap_reference(self, series_list=None) -> float:
        """色标参考计数（全轨合图密度**非零格**的 p95·T-1089 N-F）。

        改前按逐图 ``peak`` 归一 ⇒ 同一个 alpha 在不同轨数/不同窗下含义不同，5 轨×3s
        素材 peak=2 时全图只剩 ``0/128/255`` 三档（探针[13]），色阶读不出量纲。改为
        全轨共享一个稳健参考值：① 同一次绘制内各面板同一映射（多图可横向比色）；
        ② 达到参考值即饱和，色标上直接标出该档的**绝对帧数**。
        """
        source = self._series if series_list is None else series_list
        lo, hi = self.freq_range()
        density = build_density_heatmap(source, self._view_range, fmin=lo, fmax=hi)
        nonzero = density[density > 0]
        if not nonzero.size:
            return 0.0
        return float(np.percentile(nonzero, HEATMAP_SCALE_PERCENTILE))

    def _heatmap_image(self, series_list, rect: QRectF, *, reference=None):
        """密度热图位图（T-1087 M8：向量化·逐像素等值于旧双循环实现）。

        改前为 ``rows×cols``（固定 96×240 ≈ 23k 像素/面板/帧）的纯 Python 双循环
        ``setPixelColor``，在 MODE_GRID 下按轨数翻倍 ⇒ 绘制期直接掉帧。本实现把
        alpha 计算整体交给 numpy（单次翻转 + 一次位打包），QImage 用 ``.copy()``
        让 Qt 自持缓冲（不留外部内存引用）。

        ★ T-1089 N-F：归一分母由 ``peak`` 换成 :meth:`_heatmap_reference`（绝对计数
        参考值），**向量化与逐像素等值的 M8 语义逐字保留**（守卫测同步换标尺）。
        ``reference`` 由绘制期传入以避免重算直方图；缺省时自行取。
        """
        lo, hi = self.freq_range()
        density = build_density_heatmap(
            series_list, self._view_range, fmin=lo, fmax=hi
        )
        if not density.any():
            return None
        scale = self._heatmap_reference() if reference is None else float(reference)
        if scale <= 0.0:
            return None
        # 对数档：稀疏密度下 1 帧/格 也要看得见（线性归一会把全图压成近黑）
        norm = np.clip(np.log1p(density) / np.log1p(scale), 0.0, 1.0)
        base = QColor(theme.colors()["accent"])
        rows, cols = norm.shape
        # 行序翻转 = 低频在下（同改前 norm[rows-1-row]）；round 与 np.rint 同为
        # 半偶舍入 ⇒ 逐像素 alpha 与旧实现一致。
        alphas = np.rint(255.0 * norm[::-1, :]).astype(np.uint32)
        rgb = np.uint32(
            ((base.red() & 0xFF) << 16) | ((base.green() & 0xFF) << 8)
            | (base.blue() & 0xFF)
        )
        pixels = (alphas << np.uint32(24)) | rgb
        image = QImage(
            pixels.tobytes(), int(cols), int(rows), QImage.Format.Format_ARGB32
        )
        return image.copy()

    def _draw_colorbar(self, painter: QPainter, rect: QRectF, c: dict, stats: dict,
                       reference: float, top: float) -> None:
        """热图色标（借 SV ``LinearColourScale::paintVertical``：逐行取色 + 由步长定小数位）。

        色带旁标的是**绝对帧数/格**（不是 peak 相对值），故热图深浅第一次有了可读量纲；
        底衬与图例同一口径（tint + border），避免压在热区上读不出。
        """
        if reference <= 0.0:
            return
        pad = float(TOKENS["spacing"]["sm"])
        metrics = painter.fontMetrics()
        label_w = float(TOKENS["spacing"]["xxl"])
        bar_w = float(TOKENS["spacing"]["md"])
        height = float(TOKENS["spacing"]["xxl"])
        top = max(top + pad, rect.top())
        box = QRectF(rect.right() - pad - label_w - bar_w - pad, top,
                     label_w + bar_w + pad * 2.0, height + metrics.height())
        painter.setPen(QPen(QColor(c["border"])))
        painter.fillRect(box, QColor(theme.data_ink("tint")))
        painter.drawRoundedRect(box, TOKENS["radius"]["sm"], TOKENS["radius"]["sm"])
        base = QColor(c["accent"])
        bar = QRectF(box.left() + pad + label_w, top + metrics.height(),
                     bar_w, height)
        rows = max(1, int(height))
        log_reference = math.log1p(reference)
        for index in range(rows):                      # 逐行取色（同 SV 实现）
            value = reference * (rows - index) / float(rows)
            color = QColor(base)
            # ★ 色带深浅与热图位图同口径（log1p 档），否则色标读不出图上的深浅
            ratio = min(1.0, max(0.0, math.log1p(value) / log_reference))
            color.setAlpha(int(round(255.0 * ratio)))
            painter.setPen(QPen(color, 1))
            y = bar.top() + index
            painter.drawLine(QPointF(bar.left(), y), QPointF(bar.right(), y))
        painter.setPen(QPen(QColor(c["text_faint"])))
        painter.drawText(
            QRectF(box.left(), top, label_w + pad, metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            tr("multitrack.compare.heatmap_colorbar_unit"),
        )
        for tick, (_count, text) in enumerate(self._colorbar_ticks(reference)):
            y = bar.top() + (height * tick / float(HEATMAP_COLORBAR_TICKS))
            painter.setPen(QPen(QColor(c["border"]), 1))
            painter.drawLine(QPointF(bar.right() - bar_w / 3.0, y),
                             QPointF(bar.right(), y))
            painter.setPen(QPen(QColor(c["text_faint"])))
            painter.drawText(
                QRectF(box.left(), y - metrics.height() / 2.0, label_w,
                       metrics.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
        stats["colorbar"] = True

    @staticmethod
    def _colorbar_ticks(reference: float) -> list[tuple[float, str]]:
        """色标刻度 ``[(绝对计数, 文本)]``（自顶向下·小数位由步长定，同 SV 规则）。"""
        step = float(reference) / float(HEATMAP_COLORBAR_TICKS)
        decimals = 0
        if 0.0 < step < 1.0:                            # 步长亚 1 ⇒ 补足小数位
            decimals = max(0, -int(math.floor(math.log10(step))) + 1)
        return [(float(reference) - tick * step, f"{reference - tick * step:.{decimals}f}")
                for tick in range(HEATMAP_COLORBAR_TICKS + 1)]

    def _draw_waveform(self, painter: QPainter, track, rect: QRectF, c: dict) -> bool:
        """子图波形剪影（复用既有包络读取；无包络 → 不画）。"""
        try:
            from acouscope.ui.widgets.multitrack.multitrack_view import (
                LOD_COARSE, envelope_for_range,
            )

            t0, t1 = self._view_range
            times, peaks = envelope_for_range(track, t0, t1, LOD_COARSE)
        except Exception:  # noqa: BLE001 - 呈现层降级：无包络则不画波形
            return False
        times = np.asarray(times, dtype=float)
        peaks = np.asarray(peaks, dtype=float)
        if times.size == 0 or peaks.size == 0:
            return False
        span = max(t1 - t0, _MIN_SPAN_S)
        center = rect.center().y()
        half = rect.height() / 2.0
        color = QColor(c["sub"])
        color.setAlpha(WAVEFORM_ALPHA)
        painter.setPen(QPen(color, 1))
        for x_t, peak in zip(times, peaks):
            if x_t < t0 or x_t > t1:
                continue
            x = rect.left() + (x_t - t0) / span * rect.width()
            amplitude = float(np.clip(abs(peak), 0.0, 1.0)) * half
            painter.drawLine(QPointF(x, center - amplitude), QPointF(x, center + amplitude))
        return True

    def _draw_diff_bar(self, painter: QPainter, bar: QRectF, c: dict,
                       stats: dict) -> None:
        """T-1005 差异条：每非参考轨一行，**超阈帧段**按语义 warning 色沿时间轴标注。

        连续超阈帧先并段再落笔（O(段数)，避免逐帧矩形导致重绘卡顿）。
        ★ T-1089 N-B：行序改为**按超阈占比降序**（最需关注的轨排首位，不再依赖轨序
         luck），且超出 :data:`DIFF_BAR_MAX_ROWS` 时在条尾显式标注「＋N 轨未画」
        （改前静默截断：5 非参考轨实画 4 行、缺 1 行零告知）。
        """
        summary = self._diff
        if summary is None or bar.height() <= 0.0:
            return
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        ranked = self._diff_tracks_by_severity(summary.tracks)
        hop = max((float(track.hop_s) for track in ranked), default=0.0)
        half = max(1.0, bar.width() / span * max(hop, _MIN_SPAN_S)) / 2.0
        over_color = QColor(TOKENS["semantic"]["warning"])
        over_color.setAlpha(DIFF_ALPHA)
        border_pen = QPen(QColor(c["border"]), 1)
        drawn = ranked[:DIFF_BAR_MAX_ROWS]
        for index, track in enumerate(drawn):
            row = QRectF(bar.left(),
                         bar.top() + index * (DIFF_BAR_ROW_H + DIFF_BAR_GAP),
                         bar.width(), DIFF_BAR_ROW_H)
            painter.setPen(border_pen)
            painter.drawRect(row)
            stats["diff_rows"] += 1
            times = np.asarray(track.times, dtype=float)
            flags = np.asarray(track.over_threshold, dtype=bool)
            if times.size == 0 or flags.size == 0 or not flags.any():
                continue
            keep = flags & (times >= t0) & (times <= t1)
            positions = np.nonzero(keep)[0]
            if positions.size == 0:
                continue
            breaks = np.nonzero(np.diff(positions) > 1)[0] + 1
            for run in np.split(positions, breaks):
                left = self.x_at(float(times[run[0]])) - half
                right = self.x_at(float(times[run[-1]])) + half
                painter.fillRect(
                    QRectF(left, row.top(), max(1.0, right - left), row.height()),
                    over_color,
                )
                stats["diff_over_segments"] += 1
        stats["diff_row_order"] = [track.track_id for track in drawn]
        hidden = len(ranked) - len(drawn)
        stats["diff_truncated"] = hidden
        if hidden <= 0:
            return
        notice = QRectF(bar.left(), bar.bottom() - DIFF_BAR_NOTICE_H,
                        bar.width(), DIFF_BAR_NOTICE_H)
        painter.setPen(QPen(QColor(c["text_faint"])))
        painter.drawText(
            notice.adjusted(LABEL_PAD, 0.0, -LABEL_PAD, 0.0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            tr("multitrack.compare.diff_bar_more").format(n=hidden),
        )

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _freq_to_y(self, freq_hz: float, rect: QRectF) -> float:
        """频率 → 部件 y（与 :meth:`curve_points` 逐字同一对数映射·口径唯一）。"""
        lo, hi = self.freq_range()
        ln_lo = math.log(max(lo, 1e-6))
        ln_hi = math.log(max(hi, lo * 1.0001))
        ratio = (math.log(max(float(freq_hz), 1e-6)) - ln_lo) / (ln_hi - ln_lo)
        return rect.bottom() - ratio * rect.height()

    def _y_axis_ticks(self, rect: QRectF) -> list[tuple[float, str, bool]]:
        """Y 轴刻度 ``[(频率, 标签, 是否主刻度)]``（对数频轴·音名口径）。

        疏密自适应按**可用竖向像素**选档（借 SV ``ScaleTickIntervals`` 的取疏整档思路）：
        半音 → 小三度 → 三全音 → 八度 C，取第一档使标签间距 ≥
        :data:`AXIS_MIN_LABEL_SPACING`；主刻度之间的每个半音一律保留为短划刻度。
        音名与换算全部复用 ``dsp.units``（与单轨音高视图 ``freq_axis.note_name_ticks``
        同一命名口径；本模块不引 pyqtgraph）。
        """
        lo, hi = self.freq_range()
        if hi <= lo or rect.height() <= 0.0:
            return []
        midi_lo = float(units.hz_to_midi(lo))
        midi_hi = float(units.hz_to_midi(hi))
        if not (math.isfinite(midi_lo) and math.isfinite(midi_hi)):
            return []
        semitones = max(midi_hi - midi_lo, 1e-6)
        px_per_semitone = rect.height() / semitones
        step = next((candidate for candidate in AXIS_LABEL_STEPS
                     if candidate * px_per_semitone >= AXIS_MIN_LABEL_SPACING), 12)
        out: list[tuple[float, str, bool]] = []
        for midi in range(max(int(math.floor(midi_lo)), 0),
                          min(int(math.ceil(midi_hi)) + 1, 128)):
            freq = float(units.midi_to_hz(midi))
            if freq < lo or freq > hi:
                continue
            major = midi % step == 0
            out.append((freq, units.midi_note_name(midi) if major else "", major))
        return out

    def _time_axis_ticks(self) -> list[float]:
        """时间轴刻度（"nice" 步长 = 每十倍程 1/2/5 档·目标标注数封顶）。"""
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        raw = span / float(AXIS_TARGET_LABELS)
        if not math.isfinite(raw) or raw <= 0.0:
            return []
        magnitude = 10.0 ** math.floor(math.log10(raw))
        step = next((factor * magnitude for factor in AXIS_TIME_STEPS
                     if factor * magnitude >= raw), 10.0 * magnitude)
        ticks: list[float] = []
        value = math.ceil(t0 / step) * step
        while value <= t1 + 1e-9 and len(ticks) <= AXIS_TARGET_LABELS * 2:
            ticks.append(value)
            value += step
        return ticks

    def _draw_axis_caption(self, painter: QPainter, rect: QRectF, c: dict) -> float:
        """左带顶部的频率单位标注；返回其底边（供音名标签避让游标起步）。"""
        metrics = painter.fontMetrics()
        box = QRectF(rect.left() - AXIS_LABEL_GUTTER_W, rect.top(),
                     AXIS_LABEL_GUTTER_W - 2.0, metrics.height())
        painter.setPen(QPen(QColor(c["text_faint"])))
        painter.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                         tr("multitrack.compare.axis_hz"))
        return float(box.bottom())

    def _draw_y_axis(self, painter: QPainter, rect: QRectF, c: dict, stats: dict,
                     avoid_top: float = -1.0e9) -> float:
        """一格线的音名轴 + 横向网格 + A4 参考线（改前整幅零 Y 刻度、零网格·探针[14]）。

        标签自上而下贪心避让（借 SV ``HorizontalFrequencyScale`` 的 margin 规则·竖向版），
        游标由调用方跨面板传递 ⇒ 多图分离窄高子图下也不会叠字。返回新的避让游标。
        """
        metrics = painter.fontMetrics()
        half_text = metrics.height() / 2.0
        grid_color = QColor(c["border"])
        grid_color.setAlpha(AXIS_LABEL_ALPHA)
        rows = sorted(((self._freq_to_y(freq, rect), freq, label, major)
                       for freq, label, major in self._y_axis_ticks(rect)),
                      key=lambda item: item[0])
        next_top = float(avoid_top)
        for y, _freq, label, major in rows:
            if y < rect.top() - 1.0 or y > rect.bottom() + 1.0:
                continue
            if major:
                painter.setPen(QPen(grid_color, 1))
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                stats["grid_lines"] += 1
            else:
                painter.setPen(QPen(QColor(c["text_faint"]), 1))
                painter.drawLine(QPointF(rect.left() - AXIS_LABEL_GUTTER_W / 4.0, y),
                                 QPointF(rect.left(), y))
            if not label:
                continue
            if y - half_text < next_top:
                continue                                   # ★ 避让：与上一标签重叠则不画
            next_top = y + half_text
            painter.setPen(QPen(QColor(c["text_faint"])))
            painter.drawText(
                QRectF(rect.left() - AXIS_LABEL_GUTTER_W, y - half_text,
                       AXIS_LABEL_GUTTER_W - 2.0, metrics.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            stats["y_ticks"] += 1
        self._draw_reference_line(painter, rect, stats)
        return next_top

    def _draw_reference_line(self, painter: QPainter, rect: QRectF,
                             stats: dict) -> None:
        """A4 参考线（复用 ``dsp.units`` 当前参考频率 + ``data_ink('ref_line')`` 墨色）。

        与八度 C 网格同一左带口径；参考频率落在可见频带外 ⇒ 不画（不臆造）。
        """
        lo, hi = self.freq_range()
        reference = float(units.get_reference_hz())
        if not (lo <= reference <= hi):
            return
        y = self._freq_to_y(reference, rect)
        if not (rect.top() <= y <= rect.bottom()):
            return
        pen = QPen(QColor(theme.data_ink("ref_line")), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        stats["reference_line"] += 1

    def _tuning_band_lines(self) -> list:
        """当前律制在可见频带内的密铺律级线（未注入律制 ⇒ 空·不凭空造 12TET）。"""
        tuning = self._tuning
        if tuning is None:
            return []
        from acouscope.analysis.tunings.overlay import build_band_overlay_lines

        lo, hi = self.freq_range()
        try:
            return list(build_band_overlay_lines(
                tuning, min_hz=lo, max_hz=hi,
                ref_hz=float(units.get_reference_hz()),
            ))
        except Exception:  # noqa: BLE001 - 呈现层降级：律级线画不出不影响曲线
            return []

    def _draw_tuning_lines(self, painter: QPainter, rect: QRectF,
                           stats: dict) -> None:
        """T-1089 N-D：按当前律制密铺律级参考线（借 SV ``PianoScale`` 的分级轴范式）。

        间距不足一个像素时按整数倍抽稀 ⇒ 密律制（22 shruti）+ 宽频带也不会糊成一片；
        密铺密度是否抢戏归 N5。
        """
        lines = self._tuning_band_lines()
        if not lines:
            return
        positions = [self._freq_to_y(line.freq_hz, rect) for line in lines]
        positions = [y for y in positions
                     if rect.top() - 1.0 <= y <= rect.bottom() + 1.0]
        if not positions:
            return
        spacing = rect.height() / float(len(positions))
        keep = max(1, int(math.ceil(1.0 / max(spacing, 1e-6))))
        color = QColor(theme.data_ink("ref_line"))
        color.setAlpha(TUNING_LINE_ALPHA)
        painter.setPen(QPen(color, 1))
        drawn = 0
        for index, y in enumerate(positions):
            if index % keep:
                continue
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            drawn += 1
        stats["tuning_lines"] = drawn

    def _degree_pitch_label(self, degree: int) -> str:
        """音级 → 12TET 语境的「音名±cent」（借 SV ``Pitch::getPitchLabel`` 口径）。

        ★ 这里消费的是 ``compare_diff.SEMITONE_CENTS``（其注释宣称的"显示参考半音线/
        吸附"在呈现层的落地·量化层本体零改）：音级频率 → 相对 A4 音分 → 就近半音出
        音名、余差以 ``±Nc`` 标注 ⇒ 纯律第 2 音级直读作 ``C#5-14c``，不再是裸 ``#2``。
        """
        tuning = self._tuning
        if tuning is None:
            return ""
        try:
            reference = float(units.get_reference_hz())
            freq = float(tuning.degree_to_freq(int(degree), ref=reference))
            cents = float(units.hz_to_cents(freq, ref_freq=reference))
        except (TypeError, ValueError):
            return ""
        if not math.isfinite(cents):
            return ""
        semitones = int(round(cents / compare_diff.SEMITONE_CENTS))
        offset = cents - _nearest_semitone_cents(cents)
        name = units.midi_note_name(int(units.A4_MIDI) + semitones)
        if name == "--":
            return ""
        delta = int(round(offset))
        return name if delta == 0 else f"{name}{delta:+d}c"

    def _draw_time_axis(self, painter: QPainter, rect: QRectF, c: dict,
                        stats: dict) -> None:
        """下时间轴：分隔线 + 刻度 + ``M:SS.mmm`` 标注（口径同轨道信息条 ``format_seconds``）。

        标注横向贪心避让（S2 marginx 规则）⇒ 密缩放时抽稀而不是叠字。
        """
        metrics = painter.fontMetrics()
        line_color = QColor(c["border"])
        painter.setPen(QPen(line_color, 1))
        painter.drawLine(QPointF(rect.left(), rect.bottom()),
                         QPointF(rect.right(), rect.bottom()))
        tick_depth = float(TOKENS["spacing"]["xs"]) / 2.0
        margin_x = -1.0e9
        gap = float(TOKENS["spacing"]["xs"]) / 2.0
        for value in self._time_axis_ticks():
            x = self.x_at(value)
            if x < rect.left() - 1.0 or x > rect.right() + 1.0:
                continue
            label = format_seconds(value)
            half_text = metrics.horizontalAdvance(label) / 2.0
            painter.setPen(QPen(QColor(c["text_faint"]), 1))
            painter.drawLine(QPointF(x, rect.bottom()),
                             QPointF(x, rect.bottom() + tick_depth))
            if x - half_text < margin_x:
                continue                                   # ★ 避让
            margin_x = x + half_text + gap
            painter.drawText(
                QRectF(x - half_text, rect.bottom() + tick_depth,
                       half_text * 2.0 + gap, metrics.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                label,
            )
            stats["time_ticks"] += 1
        painter.setPen(QPen(QColor(c["text_faint"])))
        painter.drawText(
            QRectF(rect.left() - AXIS_LABEL_GUTTER_W, rect.bottom(),
                   AXIS_LABEL_GUTTER_W, metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            tr("multitrack.compare.axis_time"),
        )

    def paintEvent(self, event):  # noqa: N802（Qt 命名）
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(c["panel"]))
        rect = self._plot_rect()
        data = self._data_rect()
        panels = self.panels()
        stats = {"panels": len(panels), "curves": 0, "waveforms": 0,
                 "legend": 0, "heatmap": False,
                 "diff_rows": 0, "diff_over_segments": 0,
                 "diff_truncated": 0, "diff_row_order": [],
                 "y_ticks": 0, "grid_lines": 0, "time_ticks": 0,
                 "tuning_lines": 0, "reference_line": 0, "colorbar": False}

        # 共享选区（D1·与曲线同一数据区基线）
        if self._selection is not None:
            x0, x1 = self.x_at(self._selection[0]), self.x_at(self._selection[1])
            band = QRectF(min(x0, x1), data.top(), abs(x1 - x0), data.height())
            painter.fillRect(band, QColor(c["sel_bg"]))

        # T-1089 N-C/N-D：轴带 + 每格线的网格/律级线先落笔（在曲线之下）；
        # 无结果时整段不画（不与空态文案打架）。多图分离逐面板映射 ⇒ 逐面板画轴。
        if self._series:
            avoid_top = self._draw_axis_caption(painter, data, c)
            for info in panels:
                self._draw_tuning_lines(painter, info.rect, stats)
                avoid_top = self._draw_y_axis(painter, info.rect, c, stats, avoid_top)

        # T-1089 N-F：色标参考计数一帧算一次 ⇒ 各面板共用同一 alpha↔帧数映射
        heat_reference = self._heatmap_reference() if (
            self._heatmap and self._series) else 0.0
        for info in panels:
            painter.setPen(QPen(QColor(c["border"]), 1))
            painter.drawRect(info.rect)
            if self._mode == MODE_GRID:
                # 多图分离：每图只画本轨曲线；无结果轨留空图（仅轨名）
                subset = [info.series] if info.series is not None else []
            else:
                subset = list(self._series)
            if self._heatmap and subset:
                image = self._heatmap_image(subset, info.rect,
                                            reference=heat_reference)
                if image is not None:
                    painter.drawImage(info.rect, image)
                    stats["heatmap"] = True
            if self._mode == MODE_GRID:
                track = self._track_for(info.track_id)
                if track is not None and self._draw_waveform(
                    painter, track, info.rect, c
                ):
                    stats["waveforms"] += 1
            for series in subset:
                segments = self.curve_segments(series, info.rect)
                if not segments:
                    continue
                color, width, dashed = self.pen_spec(series)
                pen = QPen(QColor(color), width)
                if dashed:
                    pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                for segment in segments:
                    painter.drawPolyline(
                        [QPointF(float(x), float(y)) for x, y in segment]
                    )
                stats["curves"] += 1
            if self._mode == MODE_GRID and info.label:
                painter.setPen(QPen(QColor(c["sub"])))
                painter.drawText(
                    info.rect.adjusted(LABEL_PAD, LABEL_PAD, -LABEL_PAD, 0.0),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                    info.label,
                )

        if self._series:
            self._draw_time_axis(painter, data, c, stats)
            legend_bottom = self._draw_legend(painter, data, c, stats)
            if self._heatmap:
                self._draw_colorbar(painter, data, c, stats, heat_reference,
                                    legend_bottom)

        if self._diff_bar_height() > 0.0:        # T-1005 差异条（超阈色段）
            self._draw_diff_bar(painter, self._diff_rect(), c, stats)

        # 共享播放头（D2：对齐基线时间；红针沿用语义错误色）
        x = self.x_at(self._playhead)
        painter.setPen(
            QPen(QColor(TOKENS["semantic"]["error"]), TOKENS["elevation"]["low"])
        )
        painter.drawLine(QPointF(x, data.top()), QPointF(x, data.bottom()))

        if not self._series and self._session is not None and len(self._session):
            painter.setPen(QPen(QColor(c["sub"])))
            painter.drawText(
                rect.adjusted(LABEL_PAD, LABEL_PAD, -LABEL_PAD, 0.0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                tr("multitrack.compare.no_result"),
            )
        self._paint_stats = stats

    def _draw_legend(self, painter: QPainter, rect: QRectF, c: dict,
                     stats: dict) -> float:
        """图例（轨色线段 + 轨名，右上竖排）。返回底边 y（色标接在其下）。

        ★ T-1089 N-C：改前直叠曲线之上、叠在一起读不出（探针[13b]/DIM2 2.5）⇒
        先按项目尺寸算出**整块底衬**（tint 墨色 + border 描边）再落笔。
        """
        metrics = painter.fontMetrics()
        pad = float(TOKENS["spacing"]["sm"])
        swatch = float(TOKENS["spacing"]["sm"])
        row_step = swatch + pad / 2.0
        widths = [metrics.horizontalAdvance(s.label) for s in self._series]
        if not widths:
            return float(rect.top())
        left = rect.right() - pad - swatch - max(widths)
        top = rect.top() + pad
        bottom = top + len(widths) * row_step
        box = QRectF(left - pad / 2.0, top - pad / 2.0,
                     rect.right() - pad / 2.0 - left + pad, bottom - top + pad)
        painter.setPen(QPen(QColor(c["border"])))
        painter.fillRect(box, QColor(theme.data_ink("tint")))
        painter.drawRoundedRect(box, TOKENS["radius"]["sm"], TOKENS["radius"]["sm"])
        y = top
        for series, text_width in zip(self._series, widths):
            color, width, dashed = self.pen_spec(series)
            pen = QPen(QColor(color), width)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            item_left = rect.right() - pad - swatch - text_width
            painter.drawLine(
                QPointF(item_left, y + swatch / 2.0),
                QPointF(item_left + swatch, y + swatch / 2.0)
            )
            painter.setPen(QPen(QColor(c["text"])))
            painter.drawText(
                QRectF(item_left + swatch + pad / 2.0, y, text_width, swatch),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                series.label,
            )
            y += row_step
            stats["legend"] += 1
        return float(box.bottom())

    # ------------------------------------------------------------------
    # 交互（沿用分析视图手势语义）
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802（Qt 命名）
        if event.button() != Qt.MouseButton.LeftButton:
            return
        value = max(0.0, self.t_at(event.position().x()))
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._scrubbing = True
            self.set_playhead(value)
            self.playheadMoved.emit(value)
            return
        self._drag_anchor = value
        self.set_playhead(value)
        self.playheadMoved.emit(value)

    def mouseMoveEvent(self, event):  # noqa: N802（Qt 命名）
        self._hover_update(event.position().x())   # T-1005：悬停读数（节流，被动显示）
        if self._scrubbing:
            value = max(0.0, self.t_at(event.position().x()))
            self.set_playhead(value)
            self.playheadMoved.emit(value)
            return
        if self._drag_anchor is None or not (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            return
        end = max(0.0, self.t_at(event.position().x()))
        self.set_selection((self._drag_anchor, end))
        self.selectionChanged.emit(self._selection)

    def mouseReleaseEvent(self, event):  # noqa: N802（Qt 命名）
        self._scrubbing = False
        if self._drag_anchor is None:
            return
        self._drag_anchor = None
        if self._selection is not None and abs(
            self._selection[1] - self._selection[0]
        ) < _MIN_SPAN_S:
            self.set_selection(None)
            self.selectionChanged.emit(None)

    def wheelEvent(self, event):  # noqa: N802（Qt 命名）
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom(0.8 if steps > 0 else 1.25, self.t_at(event.position().x()))

    def leaveEvent(self, event):  # noqa: N802（Qt 命名）
        """鼠标离开：清悬停读数（Pδ 口径：离开即清，不节流）。"""
        self._hover_clear()
        super().leaveEvent(event)
