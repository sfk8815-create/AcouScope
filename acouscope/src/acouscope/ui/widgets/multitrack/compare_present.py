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

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.multitrack import compare_diff
from acouscope.ui.widgets.multitrack.align import shifted_times
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.track_header import track_color

MODE_SINGLE = "single"          # 一图差异：全部轨 F0 叠绘于共享时间轴
MODE_GRID = "grid"              # 多图分离：每轨一图
MODES = (MODE_SINGLE, MODE_GRID)
PITCH_KIND = "pitch"

# 密度热图（Overview 范式）：轨数过少时折线已足够 → 默认关（用户可显式开启）
HEATMAP_MIN_TRACKS = 4
HEATMAP_TIME_BINS = 240
HEATMAP_FREQ_BINS = 96

# T-1005 差异条（超阈色段）：行高/间距一律令牌派生（禁硬编码 px）
DIFF_BAR_ROW_H = float(TOKENS["spacing"]["sm"])
DIFF_BAR_GAP = float(TOKENS["spacing"]["xs"])
DIFF_BAR_MAX_ROWS = 4
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

__all__ = [
    "MODE_SINGLE", "MODE_GRID", "MODES", "PITCH_KIND",
    "HEATMAP_MIN_TRACKS", "DIFF_BAR_ROW_H", "DIFF_BAR_MAX_ROWS",
    "TrackSeries", "PanelInfo",
    "series_from_cache", "build_density_heatmap", "heatmap_default",
    "ComparePresentWidget",
]


# ----------------------------------------------------------------------
# 纯数据层（可离屏直测，不依赖 Qt 绘制）
# ----------------------------------------------------------------------


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
        self._drag_anchor: float | None = None
        self._scrubbing = False
        self._paint_stats = {"panels": 0, "curves": 0, "waveforms": 0,
                             "legend": 0, "heatmap": False,
                             "diff_rows": 0, "diff_over_segments": 0}
        # T-1005：差异量化状态（阈值取自 Settings；单位默认 cents = 12TET 先行）
        self._diff: compare_diff.DiffSummary | None = None
        self._diff_threshold = compare_diff.DEFAULT_THRESHOLD_CENTS
        self._diff_unit = compare_diff.DEFAULT_UNIT
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
        rect = self._plot_rect()
        if rect.width() <= 0:
            return self._view_range[0]
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        return t0 + (float(x) - rect.left()) / rect.width() * span

    def x_at(self, t: float) -> float:
        rect = self._plot_rect()
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
        """频率显示范围（Hz；按当前序列自适应，无数据回落默认量程）。"""
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
            return (DEFAULT_FMIN, DEFAULT_FMAX)
        return (lo, hi)

    # ------------------------------------------------------------------
    # 布局与几何
    # ------------------------------------------------------------------

    def _plot_rect(self) -> QRectF:
        pad = float(TOKENS["spacing"]["sm"])
        height = max(1.0, self.height() - 2.0 * pad)
        bar_height = self._diff_bar_height()
        if bar_height > 0.0:                     # T-1005：差异条存在时让位（否则几何零变化）
            height = max(1.0, height - bar_height - DIFF_BAR_GAP)
        return QRectF(
            pad, pad,
            max(1.0, self.width() - 2.0 * pad),
            height,
        )

    def _diff_bar_height(self) -> float:
        """差异条总高（无差异/无可比帧 → 0，此时不占位）。"""
        summary = self._diff
        if summary is None or not summary.has_data():
            return 0.0
        rows = min(len(summary.tracks), DIFF_BAR_MAX_ROWS)
        if rows <= 0:
            return 0.0
        return float(rows) * DIFF_BAR_ROW_H + float(rows - 1) * DIFF_BAR_GAP

    def _diff_rect(self) -> QRectF:
        """差异条几何（沿时间轴；无差异 → 零高矩形）。"""
        pad = float(TOKENS["spacing"]["sm"])
        height = self._diff_bar_height()
        if height <= 0.0:
            return QRectF(pad, float(self.height()) - pad, 0.0, 0.0)
        return QRectF(
            pad, float(self.height()) - pad - height,
            max(1.0, float(self.width()) - 2.0 * pad), height,
        )

    def diff_bar_geometry(self) -> dict:
        """差异条几何口径（测试用：无硬编码绝对值，均取自实时控件尺寸）。"""
        rect = self._diff_rect()
        return {
            "height": rect.height(), "width": rect.width(),
            "rows": min(len(self._diff.tracks), DIFF_BAR_MAX_ROWS) if (
                self._diff is not None and self._diff.has_data()) else 0,
            "row_height": DIFF_BAR_ROW_H, "gap": DIFF_BAR_GAP,
        }

    def panels(self) -> list[PanelInfo]:
        """子图布局：一图 = 单面板；多图 = 每轨一图（布局数 = 轨数）。"""
        rect = self._plot_rect()
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
        rect = rect if rect is not None else self._plot_rect()
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
        rect = rect if rect is not None else self._plot_rect()
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
        self._diff = None                    # T-1005：轨集/结果变化 → 差异作废重算
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

    def compute_diff(self):
        """按当前序列 + 参考轨计算差异（量化层 `compare_diff`；阈值取自 Settings）。"""
        if not self.diff_available():
            return None
        self._diff_threshold = compare_diff.settings_threshold()
        self._diff = compare_diff.build_diff_summary(
            self._series, reference_id=self._reference_id,
            threshold_cents=self._diff_threshold, unit=self._diff_unit,
            rms_provider=self._rms_source, duration_provider=self._duration_of,
        )
        self._update_diff_hint()
        self._update_diff_controls()
        self.update()
        return self._diff

    def hover_readout_at(self, t: float) -> str:
        """差异悬停读数（纯计算，测试直调）：各非参考轨最近配对帧的 Δ 值。"""
        summary = self._diff
        if summary is None or not summary.tracks:
            return ""
        parts = [f"t={float(t):.3f}s"]
        for track in summary.tracks:
            value = self._diff_value_at(track, float(t))
            if value is None:
                parts.append(f"{track.label}: {tr('multitrack.compare.diff_no_pair')}")
            else:
                parts.append(
                    f"{track.label}: "
                    f"{compare_diff.format_delta(value, self._diff_unit)}"
                )
        return " | ".join(parts)

    def export_diff_csv(self, path=None):
        """导出差异表 CSV（表头 = 轨/时间/ΔHz/Δcent/超阈标记/参考轨名）。

        `path=None` 走系统保存框（既有导出豁免口径）；写盘范式 = `csv.writer` + `repr`。
        """
        if self._diff is None:
            self.compute_diff()
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
        if self.compute_diff() is None:
            self._toast(tr("multitrack.compare.diff_export_empty"), level="warning")

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
        """差异摘要文案（含阈值与「报警阈值，非精度承诺」注记；帧率不一致加注）。"""
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
        note = tr("multitrack.compare.diff_threshold_note")
        if summary.pairing and not summary.pairing.get("frame_rates_equal", True):
            note = f"{note} · {tr('multitrack.compare.diff_pairing_note')}"
        self.lbl_hint.setText(f"{text} · {note}")
        self.lbl_hint.setVisible(True)

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

    def _diff_value_at(self, track, t: float):
        """时间 t 处最近**配对帧**的差异值（超出该轨帧移 → None）。"""
        times = np.asarray(track.times, dtype=float)
        if times.size == 0:
            return None
        index = int(np.clip(np.searchsorted(times, float(t)), 0, times.size - 1))
        candidates = [index] + ([index - 1] if index > 0 else [])
        best = min(candidates, key=lambda i: abs(float(times[i]) - float(t)))
        if abs(float(times[best]) - float(t)) > max(float(track.hop_s), _MIN_SPAN_S):
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
        self._diff = None                    # T-1005：改参考轨 → 差异作废重算
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

    def _heatmap_image(self, series_list, rect: QRectF):
        lo, hi = self.freq_range()
        density = build_density_heatmap(
            series_list, self._view_range, fmin=lo, fmax=hi
        )
        peak = float(density.max()) if density.size else 0.0
        if peak <= 0.0:
            return None
        norm = density / peak
        base = QColor(theme.colors()["accent"])
        rows, cols = norm.shape
        image = QImage(int(cols), int(rows), QImage.Format.Format_ARGB32)
        for row in range(int(rows)):
            source = norm[int(rows) - 1 - row]           # 低频在下
            for col in range(int(cols)):
                alpha = int(round(255.0 * float(source[col])))
                image.setPixelColor(
                    col, row, QColor(base.red(), base.green(), base.blue(), alpha)
                )
        return image

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
        """
        summary = self._diff
        if summary is None or bar.height() <= 0.0:
            return
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        hop = max((float(track.hop_s) for track in summary.tracks), default=0.0)
        half = max(1.0, bar.width() / span * max(hop, _MIN_SPAN_S)) / 2.0
        over_color = QColor(TOKENS["semantic"]["warning"])
        over_color.setAlpha(DIFF_ALPHA)
        border_pen = QPen(QColor(c["border"]), 1)
        for index, track in enumerate(summary.tracks[:DIFF_BAR_MAX_ROWS]):
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

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802（Qt 命名）
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(c["panel"]))
        rect = self._plot_rect()
        panels = self.panels()
        stats = {"panels": len(panels), "curves": 0, "waveforms": 0,
                 "legend": 0, "heatmap": False,
                 "diff_rows": 0, "diff_over_segments": 0}

        # 共享选区（D1）
        if self._selection is not None:
            x0, x1 = self.x_at(self._selection[0]), self.x_at(self._selection[1])
            band = QRectF(min(x0, x1), rect.top(), abs(x1 - x0), rect.height())
            painter.fillRect(band, QColor(c["sel_bg"]))

        for info in panels:
            painter.setPen(QPen(QColor(c["border"]), 1))
            painter.drawRect(info.rect)
            if self._mode == MODE_GRID:
                # 多图分离：每图只画本轨曲线；无结果轨留空图（仅轨名）
                subset = [info.series] if info.series is not None else []
            else:
                subset = list(self._series)
            if self._heatmap and subset:
                image = self._heatmap_image(subset, info.rect)
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
            self._draw_legend(painter, rect, c, stats)

        if self._diff_bar_height() > 0.0:        # T-1005 差异条（超阈色段）
            self._draw_diff_bar(painter, self._diff_rect(), c, stats)

        # 共享播放头（D2：对齐基线时间；红针沿用语义错误色）
        x = self.x_at(self._playhead)
        painter.setPen(
            QPen(QColor(TOKENS["semantic"]["error"]), TOKENS["elevation"]["low"])
        )
        painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        if not self._series and self._session is not None and len(self._session):
            painter.setPen(QPen(QColor(c["sub"])))
            painter.drawText(
                rect.adjusted(LABEL_PAD, LABEL_PAD, -LABEL_PAD, 0.0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                tr("multitrack.compare.no_result"),
            )
        self._paint_stats = stats

    def _draw_legend(self, painter: QPainter, rect: QRectF, c: dict, stats: dict) -> None:
        metrics = painter.fontMetrics()
        pad = float(TOKENS["spacing"]["sm"])
        swatch = float(TOKENS["spacing"]["sm"])
        widths = [metrics.horizontalAdvance(s.label) for s in self._series]
        widest = max(widths) if widths else 0
        y = rect.top() + pad
        for series, text_width in zip(self._series, widths):
            color, width, dashed = self.pen_spec(series)
            pen = QPen(QColor(color), width)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            left = rect.right() - pad - swatch - text_width
            painter.drawLine(
                QPointF(left, y + swatch / 2.0), QPointF(left + swatch, y + swatch / 2.0)
            )
            painter.setPen(QPen(QColor(c["text"])))
            painter.drawText(
                QRectF(left + swatch + pad / 2.0, y, text_width, swatch),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                series.label,
            )
            y += swatch + pad / 2.0
            stats["legend"] += 1

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
