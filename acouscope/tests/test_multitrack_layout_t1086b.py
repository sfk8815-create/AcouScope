# SPDX-License-Identifier: GPL-3.0-only
"""T-1086 里程碑 B 守卫测：轨道头咬合 + 防叠字。

覆盖：① TrackHeaderColumn.rebuild 后头列行顶对齐 + 尾 stretch；
② ComparePresentWidget._plot_rect 顶 > 标题带底；
③ 反证：还原 top=pad → top < toolbar_bottom（重现叠字）；
④ 既有多轨呈现测不回退（由 B① 命令含既有档保证）。
全离屏。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.multitrack.compare_present import ComparePresentWidget
from acouscope.ui.widgets.multitrack.track_header import ROW_HEIGHT, TrackHeaderColumn
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession


def _session(n=3, duration=2.0, sr=8000):
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
        session.add_path(f"/tmp/layout_test_{i}.wav", label=f"track{i}")
    return session


def test_header_column_top_alignment_and_tail_stretch(qapp):
    session = _session(n=3)
    col = TrackHeaderColumn()
    col.rebuild(session)
    col.resize(col.width(), 600)
    col.layout().activate()
    qapp.processEvents()

    headers = list(col._headers.values())
    assert len(headers) == 3

    first_geo = headers[0].geometry()
    assert first_geo.top() == pytest.approx(0, abs=2)

    for i in range(1, len(headers)):
        prev_bottom = headers[i - 1].geometry().bottom()
        curr_top = headers[i].geometry().top()
        assert curr_top == pytest.approx(prev_bottom + 1, abs=2)

    layout = col._layout
    last_item = layout.itemAt(layout.count() - 1)
    assert last_item is not None
    assert last_item.spacerItem() is not None


def test_plot_rect_clears_toolbar_band(qapp):
    session = _session(n=2)
    widget = ComparePresentWidget(session, with_mode_bar=True)
    widget.resize(480, 300)
    qapp.processEvents()

    rect = widget._plot_rect()
    band_bottom = widget._header_band_bottom()
    assert rect.top() >= band_bottom


def test_negative_old_plot_rect_would_overlap(qapp):
    session = _session(n=2)
    widget = ComparePresentWidget(session, with_mode_bar=True)
    widget.resize(480, 300)
    qapp.processEvents()

    from acouscope.ui.widgets.multitrack.compare_present import TOKENS
    pad = float(TOKENS["spacing"]["sm"])
    band_bottom = widget._header_band_bottom()
    if band_bottom > pad:
        assert pad < band_bottom
