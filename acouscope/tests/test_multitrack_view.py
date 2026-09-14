# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 多轨波形区回归：LOD 三级包络 / 共享时间轴 / 轨道区容器（全离屏）。

覆盖：LOD 选级与两级回落（无全量样本 → 粗包络）、包络抽稀与区间裁剪、
可见区缓存有界、缩放/平移同步、行映射与共享播放头/选区信号、
轨道头列与轨道数一一对应、白名单拖放（拒否不改轨道集）、移除撤销条。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QDropEvent, QMouseEvent

from acouscope.i18n import tr
from acouscope.ui.widgets.multitrack.multitrack_view import (
    LOD_COARSE, LOD_FINE, LOD_MEDIUM, MultitrackPanel, MultitrackView,
    choose_lod, build_envelope, envelope_for_range, slice_envelope,
)
from acouscope.ui.widgets.multitrack.track_header import ROW_HEIGHT
from acouscope.ui.widgets.multitrack.track_model import (
    COARSE_POINTS, MultitrackSession,
)


def _session(n: int = 2, duration: float = 2.0, sr: int = 8000) -> MultitrackSession:
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": sr, "channels": 1,
                                   "duration": duration},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, duration, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(sr * duration)), sr),
    )
    for i in range(n):
        session.add_path(f"/tmp/view{i}.wav", label=f"track{i}")
    return session


# ---------------------------------------------------------------------------
# LOD 与包络
# ---------------------------------------------------------------------------


def test_choose_lod_three_levels_and_fallback():
    assert choose_lod(10_000_000, 500, has_data=False) == LOD_COARSE
    assert choose_lod(100, 500, has_data=True) == LOD_FINE
    assert choose_lod(5_000, 500, has_data=True) == LOD_MEDIUM
    assert choose_lod(10_000_000, 500, has_data=True) == LOD_COARSE


def test_build_envelope_peak_buckets_and_range():
    sr = 100
    data = np.zeros(1000, dtype=np.float64)
    data[500] = 0.9                                   # 区间中点尖峰
    times, peaks = build_envelope(data, sr, 0.0, 10.0, 10)
    assert len(times) == len(peaks) == 10
    assert peaks.max() == pytest.approx(0.9, abs=1e-6)
    assert int(np.argmax(peaks)) == 5
    assert times[0] > 0.0 and times[-1] < 10.0
    assert np.all(np.diff(times) > 0)

    # 区间裁剪：只看含尖峰的那一段 → 峰值仍被保留（视图内最早桶）
    times2, peaks2 = build_envelope(data, sr, 4.0, 6.0, 4)
    assert len(times2) == 4 and peaks2.max() == pytest.approx(0.9, abs=1e-6)
    assert 4.0 <= times2[0] and times2[-1] <= 6.0
    # 空区间 → 空包络（不抛）
    assert len(build_envelope(data, sr, 5.0, 5.0, 4)[0]) == 0


def test_slice_envelope_is_range_view():
    times = np.arange(10, dtype=np.float64)
    peaks = np.arange(10, dtype=np.float32)
    t, p = slice_envelope(times, peaks, 2.5, 6.5)
    assert list(t) == [3.0, 4.0, 5.0, 6.0]
    assert list(p) == [3.0, 4.0, 5.0, 6.0]
    assert len(slice_envelope(np.zeros(0), np.zeros(0), 0.0, 1.0)[0]) == 0


def test_envelope_for_range_uses_data_only_for_finer_lod():
    session = _session(n=1)
    track = session.tracks()[0]
    # 无全量样本：即使请求细 LOD 也回落粗包络（内存有界）
    folded = envelope_for_range(track, 0.0, 2.0, LOD_FINE)
    coarse = track.envelope()
    assert len(folded[0]) == len(coarse[0])            # 粗包络全段（无裁剪）
    # 载入全量样本后：细 LOD 从样本按可见区重算（粗包络不受影响）
    track.set_data(np.linspace(-0.4, 0.4, 16000), sample_rate=8000)
    fine = envelope_for_range(track, 0.0, 1.0, LOD_FINE)
    assert len(fine[0]) > 0
    assert fine[0][-1] <= 1.0 + 1e-6                  # 只看可见区
    assert fine[1].max() == pytest.approx(0.4, abs=1e-6)
    assert len(track.envelope()[0]) == len(coarse[0])


# ---------------------------------------------------------------------------
# 视图：渲染 / 时间轴 / 缓存
# ---------------------------------------------------------------------------


def test_view_renders_empty_and_with_tracks(qapp):
    view = MultitrackView(None)
    view.resize(320, 160)
    assert view.grab().width() == 320                 # 空态不崩（画空态提示）

    session = _session(n=3)
    view.set_session(session)
    view.resize(320, 200)
    pix = view.grab()
    assert pix.width() == 320 and pix.height() > 0
    assert view.minimumHeight() == 3 * ROW_HEIGHT      # 行高与轨道数一致


def test_view_time_mapping_rows_and_clamps(qapp):
    session = _session(n=2, duration=4.0)
    view = MultitrackView(session)
    view.resize(400, 160)
    view.set_view_range(0.0, 4.0)
    assert view.t_at(0.0) == pytest.approx(0.0)
    assert view.t_at(400.0) == pytest.approx(4.0)
    assert view.x_at(2.0) == pytest.approx(200.0)
    assert view.row_at(5.0) == 0
    assert view.row_at(ROW_HEIGHT + 3.0) == 1
    assert view.track_at(ROW_HEIGHT + 3.0).label == "track1"
    assert view.track_at(10_000.0) is session.tracks()[-1]   # 越界夹到末行

    view.set_view_range(3.0, 1.0)                     # 反向输入自动归一
    assert view.view_range() == (1.0, 3.0)
    view.set_view_range(2.0, 2.0)                     # 退化跨度夹到下限
    assert view.view_range()[1] > view.view_range()[0]


def test_view_zoom_keeps_anchor_and_pan_shifts(qapp):
    session = _session(n=1, duration=10.0)
    view = MultitrackView(session)
    view.resize(400, 120)
    view.set_view_range(0.0, 10.0)
    view.zoom(0.5, center=5.0)
    t0, t1 = view.view_range()
    assert (t1 - t0) == pytest.approx(5.0)
    assert (t0 + t1) / 2.0 == pytest.approx(5.0)      # 锚点不动
    before = view.view_range()
    view.pan(1.0)
    assert view.view_range()[0] == pytest.approx(before[0] + 1.0)
    seen = []
    view.viewRangeChanged.connect(lambda rng: seen.append(rng))
    view.set_view_range(0.0, 1.0)
    assert seen and seen[-1] == (0.0, 1.0)            # 同步时间轴信号


def test_view_playhead_selection_signals(qapp):
    session = _session(n=2, duration=2.0)
    view = MultitrackView(session)
    view.resize(200, 160)
    view.set_session(session)
    view.set_view_range(0.0, 2.0)
    playheads, selections = [], []
    view.playheadMoved.connect(playheads.append)
    view.selectionChanged.connect(selections.append)
    view.set_playhead(1.25)
    assert view.playhead() == pytest.approx(1.25)
    view.set_selection((1.0, 0.5))
    assert view.selection() == (0.5, 1.0)             # 归一
    view.set_selection(None)
    assert view.selection() is None
    assert selections == [(0.5, 1.0), None]


def test_view_mouse_gestures(qapp):
    session = _session(n=2, duration=2.0)
    view = MultitrackView(session)
    view.resize(200, 160)
    view.set_view_range(0.0, 2.0)
    activated, played = [], []
    view.trackActivated.connect(activated.append)
    view.playToggled.connect(played.append)

    def _event(kind, x, y, button=Qt.MouseButton.LeftButton, mods=None):
        point = QPointF(float(x), float(y))
        return QMouseEvent(
            kind, point, point, button, button,
            mods or Qt.KeyboardModifier.NoModifier,
        )

    view.mousePressEvent(_event(QEvent.Type.MouseButtonPress, 100.0, 5.0))
    assert activated == [session.tracks()[0].track_id]
    assert view.playhead() == pytest.approx(1.0)      # 单击 = 定位共享播放头
    view.mouseMoveEvent(_event(QEvent.Type.MouseMove, 180.0, 5.0))
    assert view.selection() == pytest.approx((1.0, 1.8))
    view.mouseReleaseEvent(_event(QEvent.Type.MouseButtonRelease, 180.0, 5.0))
    view.mouseDoubleClickEvent(
        _event(QEvent.Type.MouseButtonDblClick, 100.0, ROW_HEIGHT + 5.0)
    )
    assert played == [session.tracks()[1].track_id]


def test_view_zoom_via_wheel_and_cache_bounded(qapp):
    from PyQt6.QtGui import QWheelEvent

    session = _session(n=2, duration=4.0)
    view = MultitrackView(session)
    view.resize(400, 160)
    view.set_view_range(0.0, 4.0)
    point = QPointF(200.0, 40.0)
    wheel = QWheelEvent(
        point, point, QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(wheel)
    assert view.view_range()[1] - view.view_range()[0] < 4.0   # 滚轮缩放生效

    for i in range(120):                              # 可见区包络缓存有界
        view.set_view_range(0.0, 0.5 + i * 0.01)
        view.envelope_for_paint(session.tracks()[0])
    assert len(view._cache) <= 64


# ---------------------------------------------------------------------------
# 容器：轨道头列 / 白名单拖放 / 移除撤销
# ---------------------------------------------------------------------------


def test_panel_headers_match_track_count_and_area_title(qapp):
    session = _session(n=3)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    assert len(panel.header_column.headers()) == 3
    assert panel.lbl_area.text() == tr("multitrack.area_title")
    assert panel.current_track_id() == session.tracks()[0].track_id
    assert panel.view.session() is session

    # 点击第二轨头 = 设为当前轨（联动信号）
    seen = []
    panel.currentTrackChanged.connect(seen.append)
    second = session.tracks()[1].track_id
    panel.header_column.header_for(second).currentRequested.emit(second)
    assert seen == [second]
    assert panel.current_track_id() == second
    assert panel.header_column.header_for(second).is_current() is True


def test_panel_add_files_whitelist_and_reject(qapp):
    session = _session(n=0)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    added, rejected = panel.add_files(["/tmp/ok.wav", "/tmp/ok.mp3", "/tmp/bad.txt"])
    assert [p.rsplit("/", 1)[-1] for p in added] == ["ok.wav", "ok.mp3"]
    assert rejected == ["/tmp/bad.txt"]
    assert len(session) == 2
    assert len(panel.header_column.headers()) == 2


def test_panel_unsupported_drop_does_not_add(qapp):
    from PyQt6.QtCore import QMimeData, QUrl

    session = _session(n=0)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/notes.txt")])
    event = QDropEvent(QPointF(5.0, 5.0), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    panel.dragEnterEvent(event)
    panel.dropEvent(event)
    assert len(session) == 0                          # 白名单拒否：不改轨道集


def test_panel_remove_then_undo_restores_track(qapp):
    session = _session(n=2)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    first = session.tracks()[0]
    panel.remove_track(first.track_id)
    assert len(session) == 1
    assert panel.undo_bar.is_active() is True          # D9 撤销窗口已开
    panel.undo_bar.undoRequested.emit()
    assert [t.track_id for t in session.tracks()][0] == first.track_id
    assert panel.undo_bar.is_active() is False
    assert len(panel.header_column.headers()) == 2


def test_panel_play_toggle_semantics(qapp):
    session = _session(n=2)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    played, stopped = [], []
    panel.playRequested.connect(played.append)
    panel.stopRequested.connect(lambda: stopped.append(True))
    tid = session.tracks()[0].track_id
    panel.view.playToggled.emit(tid)
    assert played == [tid] and panel.playing_id() == tid
    panel.view.playToggled.emit(tid)                   # 再点同一轨 = 停止
    assert stopped == [True] and panel.playing_id() is None
