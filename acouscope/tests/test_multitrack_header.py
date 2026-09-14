# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 轨道头回归（全离屏）：S/M 信号、当前轨高亮、音量/电平、
移除入口、i18n 三语 tooltip、令牌派生尺寸与静态纪律（无硬编码色值/像素）。
"""

import pathlib
import re

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

import acouscope.i18n as i18n
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.multitrack.track_header import (
    COLUMN_WIDTH, ROW_HEIGHT, LevelBar, TrackHeader, TrackHeaderColumn, track_color,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "widgets" / "multitrack"
# T-1006 归因：新增 align.py（对齐引擎）一并纳入静态纪律扫描
_FILES = ("track_model.py", "track_header.py", "multitrack_view.py", "align.py", "__init__.py")
_TOOLTIP_KEYS = (
    "multitrack.area_title", "multitrack.waveform_area", "multitrack.action_tip",
    "multitrack.readonly", "multitrack.empty", "multitrack.info",
    "multitrack.status", "multitrack.health", "multitrack.unsupported_drop",
    "multitrack.removed_toast", "multitrack.undo", "multitrack.add_tip",
    "multitrack.no_selection", "multitrack.tt.name", "multitrack.tt.rename",
    "multitrack.tt.solo", "multitrack.tt.mute", "multitrack.tt.volume",
    "multitrack.tt.level", "multitrack.tt.offset", "multitrack.tt.play",
    "multitrack.tt.stop", "multitrack.tt.remove",
)


def _model(label: str = "take-1"):
    from acouscope.ui.widgets.multitrack.track_model import TrackModel

    track = TrackModel(
        f"/tmp/{label}.wav",
        label=label,
        metadata_reader=lambda p: {"sample_rate": 48000, "channels": 2,
                                   "duration": 12.5},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, 12.5, points), np.full(points, 0.7, dtype=np.float32)
        ),
    )
    track.load_metadata()
    track.load_envelope()
    return track


def test_row_geometry_is_token_derived():
    assert ROW_HEIGHT == TOKENS["spacing"]["xl"] + TOKENS["spacing"]["lg"]
    # T-1006 归因：列宽由 7 倍增至 9 倍 xxl 令牌，以容纳对齐微调组（-10 / 数值框 / +10），
    # 仍为纯令牌派生（新增硬编码像素 0）。
    assert COLUMN_WIDTH == TOKENS["spacing"]["xxl"] * 9
    # T-1036 归因（非静默）：原断言 `track_color(n) == TOKENS["semantic"][...]` 编码的正是
    # 本任务要消除的缺陷 B（身份色错用语义反馈色）+ 缺陷 A（仅 4 色轮转）→ 改指内容色板口径；
    # 语义四色冻结与「身份色 ≠ 反馈色」另由 tests/test_track_palette.py 独立守卫。
    palette = theme.track_palette()
    assert track_color(0) == palette[0]
    assert track_color(1) == palette[1]
    assert track_color(5) == palette[5]                         # 12 色内不轮转
    assert track_color(len(palette)) == palette[0]              # 末位回绕
    assert set(palette) & set(TOKENS["semantic"].values()) == set()


def test_header_shows_track_facts_and_defaults(qapp):
    track = _model()
    header = TrackHeader(track, index=0)
    assert header.edit_name.text() == "take-1"
    assert "0:12.500" in header.lbl_info.text() and "48.0 kHz" in header.lbl_info.text()
    # T-1006 归因：偏移读数由 QLabel 升级为可编辑数值框（±1ms 步进），断言改指控件值
    assert header.offset_ms() == 0.0 and header.spin_offset.suffix() == " ms"
    assert header.btn_solo.text() == "S" and header.btn_mute.text() == "M"
    assert header.btn_solo.isCheckable() and header.btn_mute.isCheckable()
    assert header.slider_volume.minimum() == 0 and header.slider_volume.maximum() == 100
    assert header.slider_volume.value() == 100
    assert header.level_bar.level() == pytest.approx(0.7, abs=0.02)


def test_header_signals_emit_track_id(qapp):
    track = _model()
    header = TrackHeader(track)
    seen = {}
    header.soloToggled.connect(lambda tid, on: seen.setdefault("solo", (tid, on)))
    header.muteToggled.connect(lambda tid, on: seen.setdefault("mute", (tid, on)))
    header.volumeChanged.connect(
        lambda tid, value: seen.setdefault("volume", (tid, value))
    )
    header.renamed.connect(lambda tid, text: seen.setdefault("rename", (tid, text)))
    header.playToggled.connect(lambda tid: seen.setdefault("play", tid))
    header.removeRequested.connect(lambda tid: seen.setdefault("remove", tid))
    header.currentRequested.connect(lambda tid: seen.setdefault("current", tid))

    header.btn_solo.setChecked(True)
    header.btn_mute.setChecked(True)
    header.slider_volume.setValue(40)
    header.edit_name.setText("take-2")
    header._on_rename()
    header.btn_play.click()
    header.btn_remove.click()
    point = QPointF(2.0, 2.0)
    header.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress, point, point, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
    )

    assert seen["solo"] == (track.track_id, True)
    assert seen["mute"] == (track.track_id, True)
    assert seen["volume"] == (track.track_id, pytest.approx(0.4))
    assert seen["rename"] == (track.track_id, "take-2")
    assert seen["play"] == track.track_id
    assert seen["remove"] == track.track_id
    assert seen["current"] == track.track_id


def test_header_current_highlight_and_playing_icon(qapp):
    track = _model()
    header = TrackHeader(track, current=False)
    assert header.is_current() is False
    assert header.edit_name.font().bold() is False
    header.set_current(True)
    assert header.is_current() is True
    assert header.edit_name.font().bold() is True
    header.set_playing(True)
    assert header.btn_play.toolTip() == tr("multitrack.tt.stop")
    header.set_playing(False)
    assert header.btn_play.toolTip() == tr("multitrack.tt.play")
    header.refresh_from_track(track)
    # T-1006 归因：偏移读数升级为数值框（同前一处断言口径）
    assert header.offset_ms() == 0.0


def test_header_tooltips_use_i18n_keys_in_three_languages(qapp):
    header = TrackHeader(_model())
    tooltips = [
        header.toolTip(), header.edit_name.toolTip(), header.btn_solo.toolTip(),
        header.btn_mute.toolTip(), header.btn_remove.toolTip(),
        header.slider_volume.toolTip(), header.level_bar.toolTip(),
        header.spin_offset.toolTip(), header.btn_play.toolTip(),
    ]
    assert all(tooltips)
    assert not any(t.startswith("multitrack.") for t in tooltips)   # 键均有译文
    strings = getattr(i18n, "_STRINGS")
    for key in _TOOLTIP_KEYS:
        entry = strings.get(key)
        assert entry, f"缺 i18n 键: {key}"
        assert set(entry) == {"en_US", "zh_CN", "zh_TW"}, f"三语缺失: {key}"


def test_level_bar_static_then_dynamic(qapp):
    bar = LevelBar()
    bar.set_peak(0.6)
    assert bar.level() == pytest.approx(0.6)
    bar.set_level(0.2)
    assert bar.level() == pytest.approx(0.2)
    bar.set_level(0.0)                                # 归零回落静态峰值
    assert bar.level() == pytest.approx(0.6)
    bar.set_peak(5.0)                                 # 夹紧
    assert bar.level() == pytest.approx(1.0)
    bar.grab()                                        # 绘制不崩


def test_header_column_matches_session_order(qapp):
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": 8000, "channels": 1,
                                   "duration": 1.0},
        envelope_reader=lambda p, points: (
            np.zeros(points), np.zeros(points, dtype=np.float32)
        ),
    )
    ids = [session.add_path(f"/tmp/c{i}.wav", label=f"c{i}").track_id
           for i in range(3)]
    column = TrackHeaderColumn()
    column.rebuild(session)
    assert list(column.headers()) == ids
    assert [h.edit_name.text() for h in column.headers().values()] == ["c0", "c1", "c2"]
    column.set_current(ids[2])
    assert column.header_for(ids[2]).is_current() is True
    assert column.header_for(ids[0]).is_current() is False


def test_new_sources_static_discipline():
    """纪律：新增模块零硬编码色值/像素、零 QDialog、零禁词、零模态 exec。"""
    banned = "Mel" + "odyne"
    for name in _FILES:
        src = (_SRC / name).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), f"{name} 含硬编码色值"
        assert not re.search(r"\b\d+(?:\.\d+)?px\b", src), f"{name} 含硬编码像素"
        assert banned.lower() not in src.lower(), f"{name} 含禁词"
        assert "QDialog" not in src, f"{name} 引入 QDialog"
        assert ".exec(" not in src, f"{name} 引入模态 exec"
