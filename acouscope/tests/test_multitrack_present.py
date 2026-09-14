# SPDX-License-Identifier: GPL-3.0-only
"""T-1009 M4 多轨对比呈现层回归（全离屏，不构造主窗口显示调用）。

覆盖：逐轨 F0 序列（含 T-1006 对齐偏移）、密度热图聚合与默认阈值、
一图叠绘（折线数/参考轨加粗虚线/图例）、多图分离（布局数 = 轨数、共享播放头）、
模式切换（进出与 toggle 同步）、热图开关、逐轨分析入口（T-1008 缓存）、
共享播放头/选区/缩放联动、T-1005 预留禁用槽、文案三语齐全。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from acouscope.i18n import get_language, set_language, tr
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import (
    HEATMAP_FREQ_BINS, HEATMAP_TIME_BINS, MODE_GRID, MODE_SINGLE,
    ComparePresentWidget, build_density_heatmap, heatmap_default,
    series_from_cache,
)
from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel
from acouscope.ui.widgets.multitrack.track_header import track_color
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

COMPARE_KEYS = (
    "multitrack.compare.title",
    "multitrack.compare.mode_single",
    "multitrack.compare.mode_single_tip",
    "multitrack.compare.mode_grid",
    "multitrack.compare.mode_grid_tip",
    "multitrack.compare.heatmap",
    "multitrack.compare.heatmap_tip",
    "multitrack.compare.analyze",
    "multitrack.compare.analyze_tip",
    "multitrack.compare.analyzed",
    "multitrack.compare.analyze_failed",
    "multitrack.compare.no_tracks",
    "multitrack.compare.no_result",
    "multitrack.compare.reference",
    "multitrack.compare.reference_tip",
    "multitrack.compare.diff_stats",
    "multitrack.compare.diff_tip",
)


class _PitchStub:
    """逐轨音高结果桩（只含呈现层消费的 times / f0_hz）。"""

    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


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
        session.add_path(f"/tmp/present{i}.wav", label=f"track{i}")
    return session


def _pitch_series(times, f0):
    return _PitchStub(times, f0)


def _seed(cache, track_id, *, times, f0, kind="pitch"):
    result = _pitch_series(times, f0)
    cache.put(TrackResultCache.key(track_id, kind, None), result)
    return result


def _two_track_cache(session, *, kind="pitch"):
    """两轨已知 F0 差（220 Hz / 330 Hz），帧序列相同。"""
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.5, 30)
    _seed(cache, session.tracks()[0].track_id, times=times,
          f0=np.full(30, 220.0), kind=kind)
    _seed(cache, session.tracks()[1].track_id, times=times,
          f0=np.full(30, 330.0), kind=kind)
    return cache


def _widget(session=None, cache=None, **kwargs):
    widget = ComparePresentWidget(session, cache, **kwargs)
    widget.resize(480, 260)
    return widget


@pytest.fixture
def _main_window(qapp, monkeypatch, tmp_path):
    """离屏主窗（**不 show**）：仅用于呈现模式接线断言。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(sr) / sr
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), sr)
    window = MainWindow(controller)
    yield window
    window.close()


# ---------------------------------------------------------------------------
# 纯数据层
# ---------------------------------------------------------------------------


def test_series_from_cache_applies_alignment_offset_and_reference(qapp):
    session = _session(2)
    cache = TrackResultCache()
    times = np.array([0.0, 0.25, 0.5])
    _seed(cache, session.tracks()[0].track_id, times=times, f0=np.full(3, 220.0))
    _seed(cache, session.tracks()[1].track_id, times=times, f0=np.full(3, 330.0))
    session.set_offset_ms(session.tracks()[1].track_id, 250.0)

    series = series_from_cache(
        session, cache, reference_id=session.tracks()[1].track_id
    )
    assert [s.track_id for s in series] == [t.track_id for t in session.tracks()]
    assert np.allclose(series[1].times, times + 0.25)      # 对齐偏移右移
    assert np.allclose(series[0].times, times)             # 参考轨/零偏移原样
    assert [s.is_reference for s in series] == [False, True]
    assert series[0].color == track_color(session.tracks()[0].color_index)
    assert series[1].label == "track1"


def test_series_from_cache_skips_tracks_without_result(qapp):
    session = _session(2)
    cache = TrackResultCache()
    _seed(cache, session.tracks()[0].track_id, times=np.array([0.0, 1.0]),
          f0=np.array([440.0, 441.0]))
    series = series_from_cache(session, cache)
    assert len(series) == 1
    assert series_from_cache(None, cache) == []
    assert series_from_cache(session, None) == []


def test_series_voiced_mask_marks_nan_and_nonpositive(qapp):
    session = _session(1)
    cache = TrackResultCache()
    _seed(cache, session.tracks()[0].track_id,
          times=np.array([0.0, 0.1, 0.2]), f0=np.array([440.0, np.nan, 0.0]))
    series = series_from_cache(session, cache)[0]
    assert series.voiced().tolist() == [True, False, False]


def test_build_density_heatmap_shape_and_counts(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    series = series_from_cache(session, cache)
    matrix = build_density_heatmap(series, (0.0, 1.5))
    assert matrix.shape == (HEATMAP_FREQ_BINS, HEATMAP_TIME_BINS)
    assert matrix.sum() == pytest.approx(2 * 30)          # 全部有声帧各落一格
    assert build_density_heatmap([], (0.0, 1.0)).sum() == 0.0
    # 视图窗外的帧不参与聚合
    assert build_density_heatmap(series, (5.0, 6.0)).sum() == 0.0


def test_heatmap_default_threshold_is_four_tracks(qapp):
    assert heatmap_default(0) is False
    assert heatmap_default(3) is False
    assert heatmap_default(4) is True


# ---------------------------------------------------------------------------
# 一图差异（F0 叠图 + 参考轨 + 图例）
# ---------------------------------------------------------------------------


def test_single_mode_paints_two_curves_and_legend(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    widget = _widget(session, cache)
    widget.refresh()
    assert widget.mode() == MODE_SINGLE
    assert widget.has_results() is True
    assert len(widget.legend()) == 2
    assert len({item[2] for item in widget.legend()}) == 2      # 每轨一色
    assert len(widget.panels()) == 1

    widget.grab()                                              # 触发离屏绘制
    stats = widget.paint_stats()
    assert stats["curves"] == 2
    assert stats["legend"] == 2
    assert stats["panels"] == 1


def test_reference_track_pen_is_thicker_and_dashed(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    widget = _widget(session, cache)
    widget.refresh()
    first, second = widget.series()
    assert widget.reference_id() == session.tracks()[0].track_id   # 默认首轨
    assert first.is_reference is True
    color, width, dashed = widget.pen_spec(first)
    assert dashed is True
    plain_color, plain_width, plain_dashed = widget.pen_spec(second)
    assert plain_dashed is False
    assert width > plain_width
    assert color == first.color and plain_color == second.color


def test_set_reference_moves_highlight(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    widget = _widget(session, cache)
    widget.refresh()
    assert widget.cmb_reference.count() == 2              # 可指定参考轨
    assert widget.cmb_reference.currentText() == "track0"
    widget.set_reference(session.tracks()[1].track_id)
    assert [s.is_reference for s in widget.series()] == [False, True]
    assert widget.cmb_reference.currentText() == "track1"


def test_reference_picker_changes_highlight(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    widget.cmb_reference.setCurrentIndex(1)               # 用户改选第二轨
    assert widget.reference_id() == session.tracks()[1].track_id
    assert [s.is_reference for s in widget.series()] == [False, True]
    _, _width, dashed = widget.pen_spec(widget.series()[1])
    assert dashed is True


def test_curve_points_follow_view_range_and_frequency(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    widget = _widget(session, cache)
    widget.refresh()
    first, second = widget.series()
    low = widget.curve_points(first)
    high = widget.curve_points(second)
    assert low.shape[0] == high.shape[0] > 0
    assert low[:, 1].mean() > high[:, 1].mean()          # 220 Hz 画得更低
    widget.set_view_range(0.0, 0.5)
    assert widget.curve_points(first).shape[0] < low.shape[0]


# ---------------------------------------------------------------------------
# 多图分离与模式切换
# ---------------------------------------------------------------------------


def test_grid_mode_panels_equal_track_count(qapp):
    session = _session(3)
    cache = _two_track_cache(session)                     # 第三轨无结果
    widget = _widget(session, cache)
    widget.refresh()
    widget.set_mode(MODE_GRID)
    panels = widget.panels()
    assert len(panels) == 3
    assert [p.label for p in panels] == ["track0", "track1", "track2"]
    assert panels[2].series is None                       # 无结果轨仍占一图
    widget.grab()
    stats = widget.paint_stats()
    assert stats["panels"] == 3
    assert stats["curves"] == 2                           # 仅两轨有结果
    assert stats["waveforms"] == 3                        # 每图波形剪影


def test_mode_toggle_roundtrip_and_signal(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.refresh()
    seen = []
    widget.modeChanged.connect(seen.append)
    assert widget.toggle_mode() == MODE_GRID
    assert widget.mode() == MODE_GRID
    assert widget.btn_mode_grid.isChecked() is True
    assert widget.toggle_mode() == MODE_SINGLE
    assert len(widget.panels()) == 1                      # 切回一图零残留
    assert seen == [MODE_GRID, MODE_SINGLE]
    widget.set_mode("nonsense")
    assert widget.mode() == MODE_SINGLE


def test_mode_bar_hidden_when_hosted_without_own_bar(qapp):
    session = _session(1)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    assert panel.compare_view.btn_mode_single.isHidden() is True
    assert panel.present_mode() == MODE_SINGLE
    assert panel.btn_mode_single.isChecked() is True


def test_panel_mode_toggle_mirrors_buttons_and_view(qapp):
    session = _session(2)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    panel.btn_mode_grid.setChecked(True)
    assert panel.present_mode() == MODE_GRID
    assert panel.compare_view.mode() == MODE_GRID
    panel.set_present_mode(MODE_SINGLE)
    assert panel.compare_view.mode() == MODE_SINGLE
    assert panel.btn_mode_single.isChecked() is True
    assert panel.btn_mode_grid.isChecked() is False


# ---------------------------------------------------------------------------
# 密度热图开关
# ---------------------------------------------------------------------------


def test_heatmap_defaults_off_for_few_tracks_and_user_can_enable(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    widget = _widget(session, cache)
    widget.refresh()
    assert widget.heatmap_enabled() is False              # 轨数 < 4 默认关
    assert widget.chk_heatmap.isChecked() is False
    seen = []
    widget.heatmapToggled.connect(seen.append)
    widget.chk_heatmap.setChecked(True)                   # 用户显式开启
    assert widget.heatmap_enabled() is True
    assert seen == [True]
    widget.refresh()                                      # 用户开关优先于默认值
    assert widget.heatmap_enabled() is True


def test_heatmap_layer_painted_only_when_enabled(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    widget = _widget(session, cache)
    widget.set_heatmap(True)
    widget.refresh()
    widget.grab()
    assert widget.paint_stats()["heatmap"] is True
    widget.set_heatmap(False)
    widget.grab()
    assert widget.paint_stats()["heatmap"] is False


def test_heatmap_defaults_on_for_four_tracks(qapp):
    session = _session(4)
    widget = _widget(session, None)
    widget.refresh()
    assert widget.heatmap_enabled() is True


# ---------------------------------------------------------------------------
# 共享播放头 / 选区 / 缩放联动
# ---------------------------------------------------------------------------


def test_widget_click_sets_playhead_and_drag_sets_selection(qapp):
    session = _session(2)
    widget = _widget(session, _two_track_cache(session))
    widget.set_view_range(0.0, 2.0)
    widget.refresh()
    heads, selections = [], []
    widget.playheadMoved.connect(heads.append)
    widget.selectionChanged.connect(selections.append)

    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(120.0, 60.0),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    widget.mousePressEvent(press)
    assert heads and heads[-1] > 0.0
    assert widget.playhead() == pytest.approx(heads[-1])

    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(240.0, 60.0),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    widget.mouseMoveEvent(move)
    assert selections and selections[-1] is not None
    assert selections[-1][1] > selections[-1][0]
    assert widget.selection() == selections[-1]

    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(240.0, 60.0),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
    widget.mouseReleaseEvent(release)


def test_widget_zoom_emits_view_range_and_keeps_anchor(qapp):
    session = _session(2)
    widget = _widget(session, None)
    widget.set_view_range(0.0, 4.0)
    seen = []
    widget.viewRangeChanged.connect(seen.append)
    widget.zoom(0.5, 2.0)
    assert seen and seen[-1] == widget.view_range()
    assert widget.view_range()[1] - widget.view_range()[0] == pytest.approx(2.0)
    assert widget.view_range()[0] <= 2.0 <= widget.view_range()[1]


def test_panel_syncs_playhead_both_ways_single_broadcast(qapp):
    session = _session(2)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    seen = []
    panel.playheadMoved.connect(seen.append)

    panel.view.playheadMoved.emit(1.25)
    assert seen == [1.25]
    assert panel.compare_view.playhead() == pytest.approx(1.25)

    panel.compare_view.playheadMoved.emit(2.5)
    assert seen == [1.25, 2.5]
    assert panel.view.playhead() == pytest.approx(2.5)


def test_panel_syncs_selection_and_view_range(qapp):
    session = _session(2)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    selections = []
    panel.selectionChanged.connect(selections.append)

    panel.view.set_selection((0.4, 1.2))
    assert selections == [(0.4, 1.2)]
    assert panel.compare_view.selection() == (0.4, 1.2)

    panel.compare_view.selectionChanged.emit((0.1, 0.9))
    assert selections == [(0.4, 1.2), (0.1, 0.9)]
    assert panel.view.selection() == (0.1, 0.9)

    panel.view.set_view_range(1.0, 3.0)
    assert panel.compare_view.view_range() == (1.0, 3.0)
    panel.compare_view.set_view_range(2.0, 2.5)
    panel.compare_view.zoom(0.5, 2.2)
    assert panel.view.view_range() == pytest.approx(panel.compare_view.view_range())


def test_panel_offset_nudge_reorders_presentation(qapp):
    session = _session(2)
    cache = _two_track_cache(session)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    panel.set_result_cache(cache)
    before = np.array(panel.compare_view.series()[1].times)
    panel.header_column.header_for(session.tracks()[1].track_id).offsetChanged.emit(
        session.tracks()[1].track_id, 500.0
    )
    after = np.array(panel.compare_view.series()[1].times)
    assert np.allclose(after - before, 0.5)


# ---------------------------------------------------------------------------
# 逐轨分析入口（T-1008 缓存）与 T-1005 预留槽
# ---------------------------------------------------------------------------


def test_analyze_all_fills_cache_and_series(qapp):
    session = _session(2)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    calls = []

    def runner(source, params):
        calls.append(source.track_id)
        return _pitch_series(np.linspace(0.0, 1.0, 10), np.full(10, 440.0))

    handles = panel.analyze_all(runner=runner)
    assert [h.status for h in handles] == ["done", "done"]
    assert len(calls) == 2
    assert panel.compare_view.has_results() is True
    assert len(panel.compare_view.series()) == 2
    assert len(panel.result_cache()) == 2

    again = panel.analyze_all(runner=runner)               # 命中缓存：不再重算
    assert [h.status for h in again] == ["cached", "cached"]
    assert len(calls) == 2


def test_analyze_all_without_tracks_is_guarded(qapp):
    session = _session(0)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    toasts = []
    panel._toast = lambda message, **kwargs: toasts.append(message)
    assert panel.analyze_all() == []
    assert toasts == [tr("multitrack.compare.no_tracks")]


def test_analyze_button_requests_analysis(qapp):
    session = _session(2)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    triggered = []
    panel.analyze_all = lambda **kwargs: triggered.append(True)
    panel.compare_view.btn_analyze.click()
    assert triggered == [True]


def test_no_result_guidance_is_visible_and_not_silent(qapp):
    session = _session(2)
    widget = _widget(session, None)
    widget.refresh()
    assert widget.has_results() is False
    assert widget.lbl_hint.isHidden() is False            # 引导文案可见（非静默）
    assert widget.btn_analyze.isEnabled() is True
    widget.set_result_cache(_two_track_cache(session))
    assert widget.has_results() is True
    assert widget.lbl_hint.isHidden() is True


def test_main_window_wires_presentation_band_and_result_cache(_main_window):
    window = _main_window
    panel = window.multitrack_panel
    assert panel.result_cache() is window.multitrack_result_cache
    assert panel.presentation() is panel.compare_view

    window._enter_multitrack_mode()
    assert panel.present_mode() == MODE_SINGLE
    assert panel.compare_view.isHidden() is False
    panel.btn_mode_grid.setChecked(True)                   # 多轨态内切换呈现模式
    assert panel.compare_view.mode() == MODE_GRID
    window._exit_multitrack_mode()                         # 退出回单轨主态零残留
    assert window._multitrack_mode is False
    assert panel.isHidden() is True
    panel.set_present_mode(MODE_SINGLE)
    assert panel.present_mode() == MODE_SINGLE


def test_diff_stats_slot_is_reserved_disabled(qapp):
    widget = _widget(_session(1), None)
    assert widget.btn_diff_stats.isEnabled() is False
    assert widget.btn_diff_stats.text() == tr("multitrack.compare.diff_stats")
    assert widget.btn_diff_stats.toolTip() == tr("multitrack.compare.diff_tip")


def test_compare_i18n_keys_three_languages(qapp):
    original = get_language()
    try:
        for lang in ("en_US", "zh_CN", "zh_TW"):
            set_language(lang)
            for key in COMPARE_KEYS:
                assert tr(key) != key, f"{key} missing for {lang}"
    finally:
        set_language(original)
