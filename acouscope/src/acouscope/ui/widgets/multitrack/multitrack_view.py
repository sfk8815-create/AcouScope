# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 多轨波形区：LOD 三级包络渲染器 + 同步时间轴 + 轨道区容器。

渲染口径（本模块自绘，**不复制** waveform.py / player.py 逻辑）：

- LOD 三级：粗（整轨 ~1k 点峰值包络，载入即算）/ 中 / 细（按可见区按需计算，
  结果进有界缓存）；无全量样本时一律回落粗包络 → 大文件多轨不卡、内存有界。
- 每轨一行波形 + 单条共享时间轴（同步缩放/平移，绝对时间口径沿用 T-917）。
- 交互（ARCH D1/D2/D9）：单击=定位共享播放头、双击=播放/停止当前轨、
  拖=设共享选区、Alt+拖=scrub；拖入支持格式文件=追加新轨（白名单拒否）。
- 区域命名（D9）：多轨态该区文案「轨道区」（主态仍「波形区」，代码标识不动）。
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.multitrack.align import (
    DEFAULT_GATE_DB, DEFAULT_MIN_SPEECH_MS, align_session, shifted_times,
)
from acouscope.ui.widgets.multitrack.compare_present import (
    MODE_GRID, MODE_SINGLE, PITCH_KIND, ComparePresentWidget,
)
from acouscope.ui.widgets.multitrack.track_header import (
    ROW_HEIGHT, TrackHeaderColumn, track_color,
)
from acouscope.ui.widgets.multitrack.track_model import format_seconds

LOD_COARSE = "coarse"
LOD_MEDIUM = "medium"
LOD_FINE = "fine"
LOD_POINTS = {LOD_COARSE: 1024, LOD_MEDIUM: 4096, LOD_FINE: 32768}

# 缓存条目上限（可见区包络按需计算后的有界缓存）
_CACHE_LIMIT = 64
# 最小可见时长（秒）：缩放下限，防退化到零跨度
_MIN_SPAN_S = 0.005
# 撤销窗口（毫秒）
UNDO_WINDOW_MS = 5000


def choose_lod(visible_samples: int, target_width: int, has_data: bool) -> str:
    """按可见样本数与像素宽度选 LOD；无全量样本一律粗包络（内存有界）。"""
    if not has_data:
        return LOD_COARSE
    width = max(1, int(target_width))
    if visible_samples <= width * 2:
        return LOD_FINE
    if visible_samples <= width * 16:
        return LOD_MEDIUM
    return LOD_COARSE


def build_envelope(data, sample_rate: int, t0: float, t1: float, points: int):
    """从全量样本按可见区抽稀峰值包络（切片为视图，不复制数据）。

    Returns:
        (times, peaks)：times 为区间内分桶中心时刻（秒），peaks 为桶内峰值。
    """
    points = max(1, int(points))
    arr = np.asarray(data)
    sr = max(1, int(sample_rate or 1))
    length = int(arr.shape[0])
    i0 = max(0, int(round(float(t0) * sr)))
    i1 = min(length, int(round(float(t1) * sr)))
    if i1 - i0 <= 0:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float32)
    seg = arr[i0:i1]
    if seg.ndim > 1:
        seg = np.abs(seg).max(axis=1)
    else:
        seg = np.abs(seg)
    n = seg.shape[0]
    bucket = max(1, n // points)
    count = max(1, (n + bucket - 1) // bucket)
    pad = count * bucket - n
    if pad:
        seg = np.concatenate([seg, np.zeros(pad, dtype=seg.dtype)])
    reshaped = seg.reshape(count, bucket)
    peaks = reshaped.max(axis=1).astype(np.float32)
    times = (i0 + (np.arange(count, dtype=np.float64) + 0.5) * bucket) / sr
    return times, peaks


def slice_envelope(times, peaks, t0: float, t1: float):
    """按可见时间区间裁剪包络（索引切片，无复制地取子集视图）。"""
    if times is None or len(times) == 0:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float32)
    i0 = int(np.searchsorted(times, float(t0), side="left"))
    i1 = int(np.searchsorted(times, float(t1), side="right"))
    return times[i0:i1], peaks[i0:i1]


def envelope_for_range(track, t0: float, t1: float, lod: str = LOD_COARSE):
    """按可见区取 LOD 包络；无全量样本时回落粗包络（懒加载第三级）。"""
    if lod == LOD_COARSE or not track.has_data:
        times, peaks = track.envelope()
        return slice_envelope(times, peaks, t0, t1)
    return build_envelope(track.data, track.sample_rate, t0, t1, LOD_POINTS[lod])


class MultitrackView(QWidget):
    """多轨波形区（自绘 LOD 包络 + 共享时间轴 + 共享播放头/选区）。"""

    playheadMoved = pyqtSignal(float)
    selectionChanged = pyqtSignal(object)      # (t0, t1) 或 None
    playToggled = pyqtSignal(str)              # 双击轨行 = 播放/停止该轨
    trackActivated = pyqtSignal(str)           # 单击轨行 = 设为当前轨
    scrubRequested = pyqtSignal(str, float)
    viewRangeChanged = pyqtSignal(tuple)

    def __init__(self, session=None, parent=None):
        super().__init__(parent)
        self.setObjectName("multitrackView")
        self.setMinimumHeight(ROW_HEIGHT)
        self._session = session
        self._view_range = (0.0, 1.0)
        self._playhead = 0.0
        self._selection: tuple[float, float] | None = None
        self._drag_anchor: float | None = None
        self._scrubbing = False
        self._cache: dict[tuple, tuple] = {}
        self._refresh_style = theme.style_when_theme(self, self._on_theme_refresh)

    # ------------------------------------------------------------------
    # 会话与状态
    # ------------------------------------------------------------------

    def set_session(self, session) -> None:
        self._session = session
        self.reset_view_range()
        self.update()

    def session(self):
        return self._session

    def reset_view_range(self) -> None:
        total = self._session.total_duration() if self._session else 0.0
        self._view_range = (0.0, max(total, _MIN_SPAN_S))
        self.setMinimumHeight(
            max(1, len(self._session.tracks()) if self._session else 1) * ROW_HEIGHT
        )
        self.viewRangeChanged.emit(self._view_range)

    def view_range(self) -> tuple[float, float]:
        return self._view_range

    def set_view_range(self, t0: float, t1: float) -> None:
        lo, hi = (float(t0), float(t1)) if t1 >= t0 else (float(t1), float(t0))
        if hi - lo < _MIN_SPAN_S:
            hi = lo + _MIN_SPAN_S
        self._view_range = (lo, hi)
        self.update()
        self.viewRangeChanged.emit(self._view_range)

    def zoom(self, factor: float, center: float | None = None) -> None:
        """以 center（秒）为锚点缩放可见区（滚轮 / 调用方驱动）。"""
        t0, t1 = self._view_range
        span = max(t1 - t0, _MIN_SPAN_S)
        anchor = (t0 + t1) / 2.0 if center is None else float(center)
        ratio = (anchor - t0) / span
        new_span = max(_MIN_SPAN_S, span * float(factor))
        self.set_view_range(anchor - ratio * new_span, anchor + (1.0 - ratio) * new_span)

    def pan(self, delta_seconds: float) -> None:
        t0, t1 = self._view_range
        self.set_view_range(t0 + float(delta_seconds), t1 + float(delta_seconds))

    def playhead(self) -> float:
        return self._playhead

    def set_playhead(self, value: float) -> None:
        self._playhead = max(0.0, float(value))
        self.update()

    def selection(self):
        return self._selection

    def set_selection(self, value) -> None:
        """设共享时间选区（None = 清除）；不改单轨态选区域（两域隔离）。"""
        if value is None:
            self._selection = None
        else:
            lo, hi = float(value[0]), float(value[1])
            self._selection = (min(lo, hi), max(lo, hi))
        self.update()
        self.selectionChanged.emit(self._selection)

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------

    def _plot_width(self) -> int:
        return max(1, self.width())

    def t_at(self, x: float) -> float:
        t0, t1 = self._view_range
        return t0 + (float(x) / float(self._plot_width())) * (t1 - t0)

    def x_at(self, t: float) -> float:
        t0, t1 = self._view_range
        span = max(t1 - t0, 1e-9)
        return (float(t) - t0) / span * self._plot_width()

    def row_at(self, y: float) -> int:
        tracks = self._session.tracks() if self._session else []
        if not tracks:
            return -1
        return max(0, min(int(float(y) // ROW_HEIGHT), len(tracks) - 1))

    def track_at(self, y: float):
        session = self._session
        if session is None:
            return None
        row = self.row_at(y)
        tracks = session.tracks()
        return tracks[row] if 0 <= row < len(tracks) else None

    # ------------------------------------------------------------------
    # 绘制（LOD 包络；不复制 waveform.py 逻辑）
    # ------------------------------------------------------------------

    def _cache_get(self, key):
        return self._cache.get(key)

    def _cache_put(self, key, value):
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = value

    def track_offset_s(self, track) -> float:
        """该轨对齐偏移（秒；正=内容右移）。只读元数据，不碰音频数据。"""
        return float(getattr(track, "offset_ms", 0.0) or 0.0) / 1000.0

    def envelope_for_paint(self, track, lod: str | None = None):
        """按可见区取包络（带缓存；可见区已折算该轨对齐偏移）；返回 (times, peaks, lod)。"""
        offset = self.track_offset_s(track)
        t0, t1 = self._view_range[0] - offset, self._view_range[1] - offset
        if lod is None:
            visible = int(max(0.0, (t1 - t0)) * max(1, track.sample_rate))
            lod = choose_lod(visible, self._plot_width(), track.has_data)
        key = (track.track_id, lod, round(t0, 6), round(t1, 6))
        cached = self._cache_get(key)
        if cached is not None:
            return cached[0], cached[1], lod
        times, peaks = envelope_for_range(track, t0, t1, lod)
        self._cache_put(key, (times, peaks))
        return times, peaks, lod

    def visible_times(self, track, lod: str | None = None):
        """该轨在共享时间轴上的呈现包络（已按对齐偏移平移）；返回 (times, peaks, lod)。

        切片在原始时间域进行、平移只作用于返回值：缓存键不随微调变化，
        因而 ±ms 微调无需清缓存即可即时重排。
        """
        times, peaks, lod = self.envelope_for_paint(track, lod)
        return shifted_times(times, getattr(track, "offset_ms", 0.0)), peaks, lod

    def paintEvent(self, event):  # noqa: N802（Qt 命名）
        c = theme.colors()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(c["panel"]))
        session = self._session
        tracks = session.tracks() if session else []
        if not tracks:
            p.setPen(QColor(c["sub"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("multitrack.empty"))
            return

        # 共享选区（先铺底，避免遮住包络）
        if self._selection is not None:
            x0, x1 = self.x_at(self._selection[0]), self.x_at(self._selection[1])
            p.fillRect(
                QRectF(min(x0, x1), 0.0, abs(x1 - x0), float(self.height())),
                QColor(c["sel_bg"]),
            )

        current_id = session.current_id if session else None
        for row, track in enumerate(tracks):
            top = float(row * ROW_HEIGHT)
            if track.track_id == current_id:
                p.fillRect(
                    QRectF(0.0, top, float(self.width()), float(ROW_HEIGHT)),
                    QColor(c["btn_hover"]),
                )
            mid = top + ROW_HEIGHT / 2.0
            half = ROW_HEIGHT / 2.0 - TOKENS["spacing"]["sm"]
            times, peaks, _lod = self.visible_times(track)
            if len(times) == 0:
                p.setPen(QPen(QColor(c["border"]), TOKENS["elevation"]["border"]))
                p.drawLine(QPointF(0.0, mid), QPointF(float(self.width()), mid))
            else:
                xs = (times - self._view_range[0]) / max(
                    1e-9, self._view_range[1] - self._view_range[0]
                ) * self._plot_width()
                poly = QPolygonF()
                for x, peak in zip(xs, peaks):
                    poly.append(QPointF(float(x), mid - float(peak) * half))
                for x, peak in zip(xs[::-1], peaks[::-1]):
                    poly.append(QPointF(float(x), mid + float(peak) * half))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(track_color(track.color_index)))
                p.drawPolygon(poly)
            if track.mute:
                p.setPen(QColor(c["sub"]))
                p.drawText(
                    QRectF(0.0, top, float(self.width()), float(ROW_HEIGHT)),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    tr("multitrack.tt.mute"),
                )
            if track.offset_ms:
                p.setPen(QColor(c["sub"]))
                p.drawText(
                    QRectF(
                        max(0.0, self.x_at(track.offset_ms / 1000.0)),
                        top, float(self.width()), float(ROW_HEIGHT),
                    ),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                    format_seconds(track.offset_ms / 1000.0),
                )

        # 共享播放头（红针：主题语义 error 色，绝对时间）
        x = self.x_at(self._playhead)
        p.setPen(QPen(QColor(TOKENS["semantic"]["error"]), TOKENS["elevation"]["low"]))
        p.drawLine(QPointF(x, 0.0), QPointF(x, float(self.height())))

    def _on_theme_refresh(self, c: dict) -> str:
        self.update()
        return ""

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802（Qt 命名）
        track = self.track_at(event.position().y())
        if track is None:
            return
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.AltModifier:
            self._scrubbing = True
            self.scrubRequested.emit(track.track_id, self.t_at(event.position().x()))
            return
        self.trackActivated.emit(track.track_id)
        value = max(0.0, self.t_at(event.position().x()))
        self._drag_anchor = value
        self.set_playhead(value)
        self.playheadMoved.emit(value)

    def mouseMoveEvent(self, event):  # noqa: N802（Qt 命名）
        if self._scrubbing:
            track = self.track_at(event.position().y())
            if track is not None:
                self.scrubRequested.emit(
                    track.track_id, self.t_at(event.position().x())
                )
            return
        if self._drag_anchor is None or not (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            return
        end = max(0.0, self.t_at(event.position().x()))
        self.set_selection((self._drag_anchor, end))

    def mouseReleaseEvent(self, event):  # noqa: N802（Qt 命名）
        self._scrubbing = False
        if self._drag_anchor is not None:
            self._drag_anchor = None
            if self._selection is not None and abs(
                self._selection[1] - self._selection[0]
            ) < _MIN_SPAN_S:
                self.set_selection(None)

    def mouseDoubleClickEvent(self, event):  # noqa: N802（Qt 命名）
        track = self.track_at(event.position().y())
        if track is not None:
            self.playToggled.emit(track.track_id)

    def wheelEvent(self, event):  # noqa: N802（Qt 命名）
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom(0.8 if steps > 0 else 1.25, self.t_at(event.position().x()))

    def resizeEvent(self, event):  # noqa: N802（Qt 命名）
        self._cache.clear()
        super().resizeEvent(event)


class RemoveUndoBar(QWidget):
    """移除轨的撤销窗口条（D9：N 秒内可撤回，单条 pending，无复杂撤销栈）。"""

    undoRequested = pyqtSignal()
    expired = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("trackUndoBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(TOKENS["spacing"]["xs"])
        self.lbl = QLabel(self)
        self.btn = QPushButton(tr("multitrack.undo"), self)
        self.btn.setObjectName("trackUndoButton")
        self.btn.clicked.connect(lambda _checked=False: self.undoRequested.emit())
        row.addWidget(self.lbl)
        row.addWidget(self.btn)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(UNDO_WINDOW_MS)
        self._timer.timeout.connect(self._on_timeout)
        self.hide()

    def start(self, track_label: str) -> None:
        self.lbl.setText(tr("multitrack.removed_toast").format(name=track_label))
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def is_active(self) -> bool:
        return self._timer.isActive()

    def _on_timeout(self) -> None:
        self.hide()
        self.expired.emit()


class _InlineReporter:
    """无宿主投递器时的假 reporter（就地驱动到终态·``cancelled`` 恒 False）。

    与 ``task_center.TaskReporter`` 同鸭子类型（``cancelled`` / ``stage`` /
    ``progress``），使"未接任务中心"与"真异步"两条路共用同一 work/on_done 形状。
    """

    cancelled = False

    def stage(self, text: str) -> None:
        pass

    def progress(self, value: float) -> None:
        pass


class MultitrackPanel(QWidget):
    """多轨态容器：区域标题 + 轨道头列 + 波形区 + 移除撤销条 + 拖放加轨。"""

    playRequested = pyqtSignal(str)
    stopRequested = pyqtSignal()
    tracksChanged = pyqtSignal()
    currentTrackChanged = pyqtSignal(str)
    playheadMoved = pyqtSignal(float)
    selectionChanged = pyqtSignal(object)
    addFromBrowserRequested = pyqtSignal()
    # T-1087 M1（真机目测 #7）：轨道区「退出」请求（宿主接回单轨主态）
    exitRequested = pyqtSignal()

    def __init__(self, session=None, parent=None):
        super().__init__(parent)
        self.setObjectName("multitrackPanel")
        self.setAcceptDrops(True)
        self._session = session
        self._playing_id: str | None = None
        # T-1009：多轨结果缓存域（T-1008；由主窗注入，跨模式切换保留）
        self._cache = None
        # T-1041a 轮 A：投递缝（None ⇒ 原同步路径，行为逐字不变）
        self._deliver = None
        # T-1087 M6：对齐投递缝 + 在途门闩 + 终态结果（fire-and-forget 后唯一取用面）
        self._align_deliver = None
        self._align_inflight = False
        self._align_entry = None
        self._align_result = None
        # T-1087 M5：加轨包络 IO 投递缝（None ⇒ 就地同步读）
        self._prepare_deliver = None
        self._prepare_inflight = False
        self._syncing_selection = False
        self._syncing_range = False

        sp = TOKENS["spacing"]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(sp["xs"], sp["xs"], sp["xs"], sp["xs"])
        outer.setSpacing(sp["xs"])

        top = QHBoxLayout()
        top.setSpacing(sp["sm"])
        self.lbl_area = QLabel(tr("multitrack.area_title"), self)
        self.lbl_area.setObjectName("trackAreaTitle")
        top.addWidget(self.lbl_area)
        self.lbl_hint = QLabel(tr("multitrack.readonly"), self)
        self.lbl_hint.setObjectName("trackReadonlyHint")
        top.addWidget(self.lbl_hint)
        top.addStretch(1)
        self.btn_add = QToolButton(self)
        self.btn_add.setObjectName("trackAddFromBrowser")
        self.btn_add.setIcon(theme.get_icon("files"))
        self.btn_add.setToolTip(tr("multitrack.add_tip"))
        self.btn_add.clicked.connect(
            lambda _checked=False: self.addFromBrowserRequested.emit()
        )
        top.addWidget(self.btn_add)
        self.btn_align = QToolButton(self)
        self.btn_align.setObjectName("trackAutoAlign")
        self.btn_align.setIcon(theme.get_icon("inspect"))
        self.btn_align.setToolTip(tr("multitrack.align.tip"))
        self.btn_align.clicked.connect(lambda _checked=False: self.auto_align())
        top.addWidget(self.btn_align)
        # T-1009：「一图 / 多图」呈现模式切换（文字标签）；T-1098 IM-10 补两枚模式图标。
        # QToolButton 默认 IconOnly——挂上图标后文字会被吞，故显式 TextBesideIcon 保图标与文字并存。
        self.btn_mode_single = QToolButton(self)
        self.btn_mode_single.setObjectName("trackPresentSingle")
        self.btn_mode_single.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_mode_single.setIcon(theme.get_icon("mode_single"))
        self.btn_mode_single.setText(tr("multitrack.compare.mode_single"))
        self.btn_mode_single.setToolTip(tr("multitrack.compare.mode_single_tip"))
        self.btn_mode_single.setCheckable(True)
        self.btn_mode_single.setChecked(True)
        self.btn_mode_grid = QToolButton(self)
        self.btn_mode_grid.setObjectName("trackPresentGrid")
        self.btn_mode_grid.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_mode_grid.setIcon(theme.get_icon("mode_grid"))
        self.btn_mode_grid.setText(tr("multitrack.compare.mode_grid"))
        self.btn_mode_grid.setToolTip(tr("multitrack.compare.mode_grid_tip"))
        self.btn_mode_grid.setCheckable(True)
        self.present_mode_group = QButtonGroup(self)
        self.present_mode_group.setExclusive(True)
        self.present_mode_group.addButton(self.btn_mode_single)
        self.present_mode_group.addButton(self.btn_mode_grid)
        self.btn_mode_single.toggled.connect(
            lambda on: on and self.set_present_mode(MODE_SINGLE)
        )
        self.btn_mode_grid.toggled.connect(
            lambda on: on and self.set_present_mode(MODE_GRID)
        )
        top.addWidget(self.btn_mode_single)
        top.addWidget(self.btn_mode_grid)
        self.undo_bar = RemoveUndoBar(self)
        self.undo_bar.undoRequested.connect(self._on_undo)
        self.undo_bar.expired.connect(self._on_undo_expired)
        top.addWidget(self.undo_bar)
        # T-1087 M1：退出钮（复用现成 theme.close 图标·零新增 ICONS）；模式级动作
        # 置于工具栏最右，与「加入多轨 / 自动对齐」的轨级动作分列。
        self.btn_exit = QToolButton(self)
        self.btn_exit.setObjectName("trackExitMode")
        self.btn_exit.setIcon(theme.get_icon("close"))
        self.btn_exit.setToolTip(tr("multitrack.exit.tip"))
        self.btn_exit.clicked.connect(
            lambda _checked=False: self.exitRequested.emit()
        )
        top.addWidget(self.btn_exit)
        outer.addLayout(top)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner_lay = QHBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(sp["sm"])
        self.header_column = TrackHeaderColumn(inner)
        inner_lay.addWidget(self.header_column)
        self.view = MultitrackView(session, inner)
        inner_lay.addWidget(self.view, 1)
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll, 1)

        # T-1009：对比呈现带（一图 F0 叠图 / 多图分离 / 密度热图），宿主为面板下方；
        # 模式控件统一在面板工具栏（此处不再重复一套，避免双控互斥歧义）
        self.compare_view = ComparePresentWidget(
            session, self._cache, self, with_mode_bar=False
        )
        self.compare_view.analyzeRequested.connect(lambda: self.analyze_all())
        self.compare_view.playheadMoved.connect(self._on_compare_playhead)
        self.compare_view.selectionChanged.connect(self._on_compare_selection)
        self.compare_view.viewRangeChanged.connect(self._on_compare_view_range)
        self.compare_view.modeChanged.connect(lambda *_: self._sync_present_buttons())
        outer.addWidget(self.compare_view, 1)

        self.view.playheadMoved.connect(self._on_playhead)
        self.view.selectionChanged.connect(lambda *_: self._on_selection())
        self.view.playToggled.connect(self._on_play_toggled)
        self.view.trackActivated.connect(self._on_track_activated)
        self.view.scrubRequested.connect(self._on_scrub)
        self.view.viewRangeChanged.connect(self._on_view_range)

    # ------------------------------------------------------------------
    # 会话
    # ------------------------------------------------------------------

    def session(self):
        return self._session

    def set_session(self, session) -> None:
        self._session = session
        self.view.set_session(session)
        self.header_column.rebuild(session)
        self._connect_headers()
        self.refresh()

    def refresh(self) -> None:
        """轨道集合变化后重建轨道头并同步波形区。"""
        if self._session is None:
            return
        self.header_column.rebuild(self._session)
        self._connect_headers()
        self.view.reset_view_range()
        for track in self._session.tracks():
            header = self.header_column.header_for(track.track_id)
            if header is not None:
                header.set_playing(track.track_id == self._playing_id)
        self.view.update()
        self.refresh_presentation()
        self.tracksChanged.emit()

    # ------------------------------------------------------------------
    # 对比呈现（T-1009 M4）：一图 / 多图 + 密度热图 + 逐轨分析入口
    # ------------------------------------------------------------------

    def presentation(self) -> ComparePresentWidget:
        """对比呈现部件（宿主为面板下方呈现带）。"""
        return self.compare_view

    def set_result_cache(self, cache) -> None:
        """注入多轨结果缓存域（T-1008；主窗持有，跨模式切换保留）。"""
        self._cache = cache
        self.compare_view.set_result_cache(cache)
        self.compare_view.refresh()

    def result_cache(self):
        return self._cache

    def set_analysis_deliver(self, fn) -> None:
        """注入逐轨分析投递回调（T-1041a 轮 A）。

        ``fn(plan, kind, cache) -> Any``：``plan`` 为 ``SourcePlan``（**零 IO** 的
        取数计划·T-1087 M4），宿主据此在 **worker 线程** ``plan.resolve()`` 取数后
        调用 ``run_analysis_on_tracks``（可接 ``cancel``/``runner``），并把结果落入
        传入的 ``cache``；收尾的 done 统计 / toast / 刷新 / 返回值一律由宿主承担
        （宿主持有本面板，可调公开的 ``refresh_presentation()``）。
        ``fn=None`` ⇒ 恢复原同步路径（未注入时行为逐字不变）。
        """
        self._deliver = fn

    def analysis_deliver(self):
        """当前投递回调（None 表示走原同步路径；T-1041a 轮 A）。"""
        return self._deliver

    def present_mode(self) -> str:
        return self.compare_view.mode()

    def set_present_mode(self, mode: str) -> None:
        """切换呈现模式（一图 / 多图）；按钮与部件状态保持同步。"""
        self.compare_view.set_mode(mode)
        self._sync_present_buttons()

    def refresh_presentation(self) -> None:
        """按当前会话 + 缓存重建呈现（轨集 / 对齐偏移 / 结果变化后调用）。"""
        self.compare_view.set_session(self._session)
        self.compare_view.refresh()

    def analyze_all(self, *, kind: str = PITCH_KIND, runner=None):
        """逐轨分析（T-1008 调度）：结果入多轨缓存域后刷新呈现；返回句柄列表。

        ★ T-1087 M4：向宿主投递的是 **取数计划**（``SourcePlan``·零 IO），
        ``resolve_source``/``load_full`` 随任务进 worker 线程；主线程只排期。
        未注入投递回调（裸面板/单测）⇒ 仍按原同步路径就地取数并跑完。
        """
        from acouscope.ui.widgets.multitrack.analysis_source import (
            SourcePlan, TrackResultCache, run_analysis_on_tracks,
        )

        session = self._session
        if session is None or len(session) == 0:
            self._toast(tr("multitrack.compare.no_tracks"), level="warning")
            return []
        cache = self._cache if self._cache is not None else TrackResultCache()
        self._cache = cache
        self.compare_view.set_result_cache(cache)
        plan = SourcePlan(session, session.tracks())
        deliver = self._deliver
        if deliver is not None:
            # T-1041a 轮 A：已注入 ⇒ 走投递缝，不再执行同步调用（禁双跑）。
            # done 统计 / toast / refresh / 返回句柄均移交宿主（宿主在 on_done
            # 调 panel.refresh_presentation()）；返回值即投递回调的返回值。
            return deliver(plan, kind, cache)
        handles = run_analysis_on_tracks(
            plan.resolve(), kind, cache=cache, runner=runner
        )
        done = sum(1 for handle in handles if handle.ok)
        if done:
            self._toast(tr("multitrack.compare.analyzed").format(n=done))
        else:
            self._toast(tr("multitrack.compare.analyze_failed"), level="warning")
        self.compare_view.refresh()
        return handles

    def _sync_present_buttons(self) -> None:
        mode = self.compare_view.mode()
        for button, value in (
            (self.btn_mode_single, MODE_SINGLE),
            (self.btn_mode_grid, MODE_GRID),
        ):
            button.blockSignals(True)
            button.setChecked(mode == value)
            button.blockSignals(False)

    def _on_compare_playhead(self, value: float) -> None:
        """呈现带定位 → 轨道区共享播放头（同步、不回声）。"""
        self.view.set_playhead(float(value))
        self.playheadMoved.emit(float(value))

    def _on_compare_selection(self, selection) -> None:
        """呈现带拖选 → 轨道区共享选区（D1：同一全局选区，单次广播）。"""
        self._syncing_selection = True
        try:
            self.view.set_selection(selection)
        finally:
            self._syncing_selection = False
        self.selectionChanged.emit(self.view.selection())

    def _on_compare_view_range(self, rng) -> None:
        """呈现带缩放/平移 → 轨道区同范围（共享时间轴口径）。"""
        if self._syncing_range:
            return
        self._syncing_range = True
        try:
            self.view.set_view_range(rng[0], rng[1])
        finally:
            self._syncing_range = False

    def _on_view_range(self, rng) -> None:
        """轨道区缩放/平移 → 呈现带同范围（双向联动，单次传播）。"""
        if self._syncing_range:
            return
        self._syncing_range = True
        try:
            self.compare_view.set_view_range(rng[0], rng[1])
        finally:
            self._syncing_range = False

    def _connect_headers(self) -> None:
        for header in self.header_column.headers().values():
            header.currentRequested.connect(self._on_current_requested)
            header.renamed.connect(self._on_renamed)
            header.soloToggled.connect(self._on_solo)
            header.muteToggled.connect(self._on_mute)
            header.volumeChanged.connect(self._on_volume)
            header.offsetChanged.connect(self._on_offset)
            header.playToggled.connect(self._on_play_toggled)
            header.removeRequested.connect(self.remove_track)

    # ------------------------------------------------------------------
    # 开头对齐（T-1006 M2）：自动对齐 + 手动微调（只改偏移元数据）
    # ------------------------------------------------------------------

    def set_align_deliver(self, fn) -> None:
        """注入对齐投递器（T-1087 M6）。

        ``fn(title, work, on_done, on_settle) -> Any``：宿主把 ``work(reporter)``
        （纯计算·内含逐轨 ``load_full`` 与帧能量循环）交任务中心 **worker 线程**
        执行，终态在主线程回调 ``on_done(result)`` 并随后 ``on_settle()``。
        ``fn=None`` ⇒ 用假 reporter **就地**驱动到终态（未接宿主的裸面板/离屏单测）；
        两条路共用同一 ``work``/``on_done`` 形状，仅线程不同。
        """
        self._align_deliver = fn

    def align_deliver(self):
        """当前对齐投递器（None = 就地驱动）。"""
        return self._align_deliver

    def align_result(self):
        """最近一次对齐的终态结果（未跑过 → None）。★ fire-and-forget 后的取用面。"""
        return self._align_result

    def align_inflight(self) -> bool:
        """对齐任务是否在途（防抖连点依据）。"""
        return self._align_inflight

    def auto_align(
        self,
        *,
        gate_db: float = DEFAULT_GATE_DB,
        min_speech_ms: float = DEFAULT_MIN_SPEECH_MS,
        reference_id=None,
    ):
        """一键自动对齐全部轨（幂等覆盖）；无有效起点时不改任何偏移。

        ★ T-1087 M6（项目负责人裁）：**fire-and-forget 真异步**——逐轨 ``load_full`` +
        ``align.frame_db_curve`` 帧循环（8 轨 × 3min ≈ 10⁵ 帧）交任务中心 worker，
        主线程只排期；偏移与轨道头由 ``on_done`` → :meth:`apply_align_result` 回填。
        返回值随之从 ``AlignResult`` 改为**投递句柄**（就地驱动时为 None）；
        需要结果请读 :meth:`align_result`。在途期间的连点不重复投递（IM-26）。
        """
        if self._session is None or len(self._session) == 0:
            self._toast(tr("multitrack.align.no_tracks"), level="info")
            return None
        if self._align_inflight:
            return self._align_entry               # ★ 反证守卫：连点不重投
        session = self._session

        def work(reporter):
            return align_session(
                session,
                gate_db=gate_db,
                min_speech_ms=min_speech_ms,
                reference_id=reference_id,
            )

        def on_done(result) -> None:
            self._align_result = result
            if result is not None:
                self.apply_align_result(result)

        def on_settle() -> None:
            self._align_inflight = False
            self._align_entry = None

        deliver = self._align_deliver
        if deliver is None:
            on_done(work(_InlineReporter()))
            on_settle()
            return None

        self._align_inflight = True
        entry = deliver(
            tr("task_center.title.multitrack_align").format(n=len(session)),
            work, on_done, on_settle,
        )
        if entry is None:                            # 队列超限/关停：taskRejected 已提示
            on_settle()
            return None
        self._align_entry = entry
        return entry

    def apply_align_result(self, result) -> None:
        """把对齐结果驱动到轨道头显示与共享时间轴（偏移只改元数据，零音频改动）。"""
        session = self._session
        for track_id, header in self.header_column.headers().items():
            track = session.get(track_id) if session is not None else None
            if track is not None:
                header.set_offset_ms(track.offset_ms)
            if track_id in result.skipped:
                header.set_align_state(None)          # 未检测到起点（偏移不动）
            elif result.onsets.get(track_id) is not None:
                header.set_align_state(result.onsets[track_id])
            else:
                header.clear_align_state()
        self.view.reset_view_range()                  # 对齐基线变化 → 重置共享时间轴
        self.view.update()
        self._toast(self._align_summary(result), level="info")

    def _align_summary(self, result) -> str:
        """对齐结果提示文案（三语）。"""
        if result.reference_id is None:
            return tr("multitrack.align.all_none")
        track = self._session.get(result.reference_id) if self._session else None
        name = track.label if track is not None else str(result.reference_id)
        text = tr("multitrack.align.done").format(n=result.applied, ref=name)
        if result.skipped:
            text = f"{text} · {tr('multitrack.align.skipped').format(n=len(result.skipped))}"
        return text

    def _on_offset(self, track_id: str, value: float) -> None:
        """手动微调：写偏移元数据并即时重排该轨在共享时间轴上的呈现（不改音频数据）。"""
        if self._session is None or self._session.get(track_id) is None:
            return
        self._session.set_offset_ms(track_id, value)
        _t0, t1 = self.view.view_range()
        if self._session.total_duration() > t1:
            self.view.reset_view_range()
        else:
            self.view.update()
        self.refresh_presentation()      # 对齐偏移变化 → 呈现带时间轴同步重排

    def _toast(self, message: str, *, level: str = "info") -> None:
        from acouscope.ui.widgets.toast import show_toast

        show_toast(self, message, level=level)

    def set_track_prepare_deliver(self, fn) -> None:
        """注入加轨 IO 投递器（T-1087 M5）。

        ``fn(title, work, on_done, on_settle) -> Any``：``work(reporter)`` 里跑
        ``session.prepare_track``（粗包络 = 整文件块式读），终态主线程 ``on_done``
        回填轨道头/呈现。``fn=None`` ⇒ 就地同步算（裸面板 / 离屏单测口径不变）。
        """
        self._prepare_deliver = fn

    def track_prepare_deliver(self):
        """当前加轨投递器（None = 就地同步算）。"""
        return self._prepare_deliver

    def track_prepare_inflight(self) -> bool:
        """加轨包络任务是否在途。"""
        return self._prepare_inflight

    def add_files(self, paths) -> tuple[list[str], list[str]]:
        """白名单过滤后追加轨道；返回 (已加入, 被拒) 路径列表。

        ★ T-1087 M5：轨道登记 + 文件头元数据留在主线程（列表立即可见、时长可得），
        粗包络那次**每轨整文件块式读**改交 worker（多轨大文件加轨不再秒级冻结）；
        包络就绪后由 ``on_done`` 在主线程 ``refresh()`` 回填轨头峰值/呈现。
        """
        from acouscope.audio.io import AudioIO

        supported, rejected = [], []
        for path in paths:
            ext = str(path).lower().rsplit(".", 1)[-1]
            (supported if f".{ext}" in AudioIO.SUPPORTED_FORMATS else rejected).append(path)
        if self._session is None or not supported:
            return supported, rejected
        tracks = [self._session.new_track(path) for path in supported]
        deliver = self._prepare_deliver
        if deliver is None:
            for track in tracks:
                self._session.prepare_track(track)
            self.refresh()
            return supported, rejected

        def work(_reporter):
            return [
                track.track_id for track in tracks
                if self._session.prepare_track(track)
            ]

        def on_done(_ready) -> None:
            self.refresh()

        def on_settle() -> None:
            self._prepare_inflight = False

        self._prepare_inflight = True
        entry = deliver(
            tr("task_center.title.multitrack_add").format(n=len(tracks)),
            work, on_done, on_settle,
        )
        if entry is None:
            on_settle()
        self.refresh()             # 先呈列（尚无包络），包络到位后再刷一次
        return supported, rejected

    def remove_track(self, track_id: str) -> None:
        """移除轨 = 撤销窗口（D9）：pending 槽 + N 秒撤销条 + toast 提示。"""
        track = self._session.remove(track_id) if self._session else None
        if track is None:
            return
        if self._playing_id == track_id:
            self._playing_id = None
            self.stopRequested.emit()
        self.refresh()
        self.undo_bar.start(track.label)
        from acouscope.ui.widgets.toast import show_toast

        show_toast(self, tr("multitrack.removed_toast").format(name=track.label))

    def _on_undo(self) -> None:
        if self._session is None:
            return
        track = self._session.restore_pending()
        self.undo_bar.stop()
        if track is not None:
            self.refresh()

    def _on_undo_expired(self) -> None:
        if self._session is not None:
            self._session.clear_pending()

    # ------------------------------------------------------------------
    # 播放（单轨一次播放：由主窗提供播放器，本层只发请求）
    # ------------------------------------------------------------------

    def set_playing(self, track_id: str | None) -> None:
        self._playing_id = track_id
        for tid, header in self.header_column.headers().items():
            header.set_playing(tid == track_id)

    def playing_id(self) -> str | None:
        return self._playing_id

    def set_level(self, track_id: str, value: float) -> None:
        header = self.header_column.header_for(track_id)
        if header is not None:
            header.set_level(value)

    def current_track_id(self):
        return self._session.current_id if self._session else None

    # ------------------------------------------------------------------
    # 轨道头 / 波形区信号
    # ------------------------------------------------------------------

    def _on_current_requested(self, track_id: str) -> None:
        if self._session.set_current(track_id):
            self.header_column.set_current(track_id)
            self.view.update()
            self.currentTrackChanged.emit(track_id)

    def _on_track_activated(self, track_id: str) -> None:
        self._on_current_requested(track_id)

    def _on_renamed(self, track_id: str, text: str) -> None:
        self._session.set_label(track_id, text)
        self.refresh()

    def _on_solo(self, track_id: str, on: bool) -> None:
        self._session.set_solo(track_id, on)
        self.view.update()
        self.tracksChanged.emit()

    def _on_mute(self, track_id: str, on: bool) -> None:
        self._session.set_mute(track_id, on)
        self.view.update()
        self.tracksChanged.emit()

    def _on_volume(self, track_id: str, value: float) -> None:
        self._session.set_volume(track_id, value)
        self.tracksChanged.emit()

    def _on_play_toggled(self, track_id: str) -> None:
        if self._playing_id == track_id:
            self._playing_id = None
            self.set_playing(None)
            self.stopRequested.emit()
            return
        self.set_playing(track_id)
        self.playRequested.emit(track_id)

    def _on_playhead(self, value: float) -> None:
        """共享播放头（对齐基线时间）→ 主窗消费（检查器读数/状态栏）。"""
        self.compare_view.set_playhead(float(value))
        self.playheadMoved.emit(float(value))

    def _on_selection(self) -> None:
        """共享时间选区（D1）→ 主窗消费；两态选区源互不迁移。"""
        selection = self.view.selection()
        self.compare_view.set_selection(selection)
        if self._syncing_selection:
            return
        self.view.update()
        self.selectionChanged.emit(selection)

    def _on_scrub(self, track_id: str, value: float) -> None:
        self.view.set_playhead(value)
        self.playheadMoved.emit(float(value))

    # ------------------------------------------------------------------
    # 拖放加轨（D9：白名单拒否）
    # ------------------------------------------------------------------

    def _dropped_urls(self, event) -> list[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, event):  # noqa: N802（Qt 命名）
        if self._dropped_urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802（Qt 命名）
        if self._dropped_urls(event):
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802（Qt 命名）
        paths = self._dropped_urls(event)
        if not paths:
            return
        added, rejected = self.add_files(paths)
        if rejected:
            from acouscope.ui.widgets.toast import show_toast

            names = ", ".join(str(p).rsplit("/", 1)[-1] for p in rejected)
            show_toast(
                self, tr("multitrack.unsupported_drop").format(name=names), level="warning"
            )
        if added:
            event.acceptProposedAction()
