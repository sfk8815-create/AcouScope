# SPDX-License-Identifier: GPL-3.0-only
"""T-1089 N-B：差异可见化去截断（hint 由只露 1 量扩到逐轨量化 · 差异条排序 + 截断告知）。

根因（PI-T81 DIM3 3.2 / DIM2 2.4）：

- ``compare_diff`` 已算 19 量（``TrackDiff`` 的 mean/abs̄/max、``over_ratio``、
  ``consistency()`` 10 键），改前 ``_update_diff_hint`` **只露 ``max_over_ratio`` 一个量**
  ⇒「算了看不见」；
- ``DIFF_BAR_MAX_ROWS = 4`` 在 ``_draw_diff_bar`` 里**静默切片**（5 非参考轨实画 4 行、
  缺 1 行零告知），且行序 = 轨序（最需关注的轨可能整条不画）。

本档判据（数值/构件离屏可判·观感归 N5）：① hint 至少露 3 个量化（平均|Δ| / 超阈占比 /
最大|Δ|），且被钉的三段（汇总首段 · 阈值注记 · 律制名末段）逐字仍在；② 差异条按超阈占比
降序取前 4 并在条尾标「＋N 轨未画」；③ 未截断时几何零变化（反证）；④ 新文案三语齐备。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.analysis.tunings.templates import get_template
from acouscope.i18n import LANGUAGES, _STRINGS, get_language, set_language, tr
from acouscope.ui import theme
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import (
    DIFF_BAR_GAP, DIFF_BAR_MAX_ROWS, DIFF_BAR_NOTICE_H, DIFF_BAR_ROW_H,
    DIFF_HINT_MAX_TRACKS, ComparePresentWidget,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession
from PyQt6.QtGui import QColor

_SR = 8000
_FRAMES = 20
_NEW_KEYS = (
    "multitrack.compare.diff_overview_stats",
    "multitrack.compare.diff_track_stats",
    "multitrack.compare.diff_more_tracks",
    "multitrack.compare.diff_bar_more",
)


class _PitchStub:
    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _session(n, duration=1.5, sr=_SR) -> MultitrackSession:
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": sr, "channels": 1,
                                   "duration": duration},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, duration, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(sr * duration)), sr),
    )
    for index in range(n):
        session.add_path(f"/tmp/t1089b{index}.wav", label=f"b{index}")
    return session


def _shift(cents):
    """逐帧音分偏移 → 频率数组（参考轨恒 440 Hz ⇒ Δcent 即偏移本身）。"""
    return 440.0 * (2.0 ** (np.asarray(cents, dtype=float) / 1200.0))


def _cache(session, profiles):
    """profiles: {轨序下标: 逐帧 cent 偏移}；轨 0 恒为参考轨（零偏移）。"""
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.5, _FRAMES)
    cache.put(
        TrackResultCache.key(session.tracks()[0].track_id, "pitch", None),
        _PitchStub(times, np.full(_FRAMES, 440.0)),
    )
    for index, cents in profiles.items():
        cache.put(
            TrackResultCache.key(session.tracks()[index].track_id, "pitch", None),
            _PitchStub(times, _shift(cents)),
        )
    return cache


def _mixed(over_frames, over_cents=60.0, within_cents=10.0):
    """前 ``over_frames`` 帧超阈（>50c），其余在报警线内 ⇒ over_ratio 可控。"""
    return [over_cents] * over_frames + [within_cents] * (_FRAMES - over_frames)


def _ready_widget(session, cache):
    widget = ComparePresentWidget(session, cache)
    widget.resize(640, 420)
    widget.refresh()
    widget.set_view_range(0.0, 1.5)
    widget.btn_diff_stats.click()                      # 既有「差异统计」路径拿 diff
    assert widget.diff() is not None
    return widget


@pytest.fixture(autouse=True)
def _zh(qapp):
    """语言钉死（本档按 zh 文案断首末段与「＋N」全角加号）。"""
    original = get_language()
    set_language("zh_CN")
    yield
    set_language(original)


def _ink_in_band(widget, rect) -> int:
    """部件矩形带内的落笔像素数（离屏判定「条尾到底画没画东西」）。"""
    image = widget.grab().toImage()
    ratio_x = image.width() / max(1, widget.width())
    ratio_y = image.height() / max(1, widget.height())
    panel = QColor(theme.colors()["panel"]).rgb()
    left = int(rect.left() * ratio_x)
    top = int(rect.top() * ratio_y)
    right = int(rect.right() * ratio_x)
    bottom = int(rect.bottom() * ratio_y)
    ink = 0
    for y in range(max(0, top), min(image.height(), bottom)):
        for x in range(max(0, left), min(image.width(), right)):
            if image.pixel(x, y) != panel:
                ink += 1
    return ink


# ---------------------------------------------------------------------------
# ① hint 由 1 量扩到多量（平均|Δ| / 超阈占比 / 最大|Δ| 同屏可见）
# ---------------------------------------------------------------------------


def test_hint_exposes_at_least_three_quantities(qapp):
    session = _session(2)
    cache = _cache(session, {})
    # 逐帧 60c/240c 交替 ⇒ 平均|Δ|=150c、最大=240c、超阈占比=100%（三量互异）
    profile = [60.0 if index % 2 == 0 else 240.0 for index in range(_FRAMES)]
    cache.put(
        TrackResultCache.key(session.tracks()[1].track_id, "pitch", None),
        _PitchStub(np.linspace(0.0, 1.5, _FRAMES), _shift(profile)),
    )
    widget = _ready_widget(session, cache)
    text = widget.lbl_hint.text()
    assert "150.0c" in text and "240.0c" in text and "100.0%" in text
    assert session.tracks()[1].label in text           # 逐轨行带轨名
    assert "50" in text                                # 阈值仍在（test_multitrack_diff:439）


def test_hint_sections_pinned_by_existing_contracts_stay_first_and_last(qapp):
    session = _session(2)
    widget = _ready_widget(session, _cache(session, {1: _mixed(_FRAMES)}))
    widget.set_tuning(get_template("just_major"))
    widget.btn_diff_stats.click()
    text = widget.lbl_hint.text()
    head = tr("multitrack.compare.diff_summary").split("{")[0].strip()
    assert text.startswith(head)                                 # 汇总行仍为首段
    assert tr("multitrack.compare.diff_threshold_note") in text   # 注记仍为末段
    assert get_template("just_major").name in text               # 律制名保留（link:152）
    assert text.rstrip().endswith(get_template("just_major").name)


def test_detail_text_is_what_carries_the_numbers(qapp):
    """反证：抽掉新增的逐轨量化段 ⇒ 三个量化全部消失（证明①不是既有文案的巧合）。"""
    session = _session(2)
    profile = [60.0 if index % 2 == 0 else 240.0 for index in range(_FRAMES)]
    cache = _cache(session, {})
    cache.put(
        TrackResultCache.key(session.tracks()[1].track_id, "pitch", None),
        _PitchStub(np.linspace(0.0, 1.5, _FRAMES), _shift(profile)),
    )
    widget = _ready_widget(session, cache)
    original = widget._diff_detail_text
    widget._diff_detail_text = lambda summary, stats: ""
    widget._update_diff_hint()
    text = widget.lbl_hint.text()
    assert "150.0c" not in text and "240.0c" not in text
    assert "100.0%" in text                            # 仅剩原先那一个量（max_over_ratio）
    widget._diff_detail_text = original
    widget._update_diff_hint()
    assert "150.0c" in widget.lbl_hint.text()          # 复位后恢复


# ---------------------------------------------------------------------------
# ② 差异条：按超阈占比降序取前 4 + 条尾显式标「＋N 轨未画」
# ---------------------------------------------------------------------------


def test_diff_bar_ranks_by_severity_and_announces_truncation(qapp):
    session = _session(6)                                    # 5 条非参考轨 > 4 行上限
    profiles = {1: _mixed(5), 2: _mixed(_FRAMES), 3: _mixed(15), 4: _mixed(0),
                5: _mixed(10)}
    widget = _ready_widget(session, _cache(session, profiles))
    ids = [t.track_id for t in session.tracks()]
    expected_rank = [ids[2], ids[3], ids[5], ids[1]]          # 100% / 75% / 50% / 25%
    widget.grab()
    stats = widget.paint_stats()
    assert stats["diff_rows"] == DIFF_BAR_MAX_ROWS
    assert stats["diff_row_order"] == expected_rank           # ★ 排序取最需关注者
    assert stats["diff_truncated"] == 1                       # ★ 缺的那一行显式告知

    geometry = widget.diff_bar_geometry()
    assert geometry["rows"] == DIFF_BAR_MAX_ROWS
    assert geometry["hidden_rows"] == 1
    assert geometry["height"] == (
        DIFF_BAR_MAX_ROWS * DIFF_BAR_ROW_H
        + (DIFF_BAR_MAX_ROWS - 1) * DIFF_BAR_GAP
        + DIFF_BAR_GAP + DIFF_BAR_NOTICE_H                   # 提示行占位
    )
    band = widget._diff_rect().adjusted(0.0, -DIFF_BAR_NOTICE_H, 0.0, 0.0)
    assert _ink_in_band(widget, band) > 0                    # ★ 条尾确有落笔


def test_diff_bar_geometry_unchanged_when_nothing_truncated(qapp):
    """反证：轨数 ≤ 上限 ⇒ 零告知、几何与改前逐字相同（既有测档钉此面）。"""
    session = _session(2)
    widget = _ready_widget(session, _cache(session, {1: _mixed(_FRAMES)}))
    widget.grab()
    stats = widget.paint_stats()
    assert stats["diff_rows"] == 1
    assert stats["diff_truncated"] == 0
    geometry = widget.diff_bar_geometry()
    assert geometry["height"] == DIFF_BAR_ROW_H
    assert geometry["hidden_rows"] == 0
    assert geometry["rows"] == 1


def test_hint_caps_listed_tracks_and_says_so(qapp, monkeypatch):
    """逐轨行列数有上限，超出显式标「＋N 轨未列」（不再无限撑高呈现带）。"""
    monkeypatch.setattr(
        "acouscope.ui.widgets.multitrack.compare_present.DIFF_HINT_MAX_TRACKS", 2,
        raising=False,
    )
    session = _session(6)
    widget = _ready_widget(
        session, _cache(session, {i: _mixed(_FRAMES - i) for i in range(1, 6)}),
    )
    text = widget.lbl_hint.text()
    listed = sum(1 for track in session.tracks()[1:] if track.label in text)
    assert listed <= 2 or DIFF_HINT_MAX_TRACKS <= 2         # 只列前 N
    assert "＋3" in text or "+3" in text                    # 其余以计数告知未列


# ---------------------------------------------------------------------------
# ③ 三语齐备（新增用户可见文案）
# ---------------------------------------------------------------------------


def test_new_i18n_keys_in_three_languages(qapp):
    original = get_language()
    try:
        for key in _NEW_KEYS:
            entry = _STRINGS.get(key)
            assert entry, f"缺 i18n 键: {key}"
            assert set(entry) == set(LANGUAGES), f"{key} 三语不齐"
            for lang in LANGUAGES:
                set_language(lang)
                assert tr(key) != key, f"{key} 在 {lang} 缺失"
    finally:
        set_language(original)
