# SPDX-License-Identifier: GPL-3.0-only
"""音高网格模型与吸附单元测试（T-801）。PITCH_GRID_TEST_V1"""

import numpy as np
import pytest

pytest.importorskip("numpy")

from acouscope.analysis.pitch_grid import (  # noqa: E402
    SNAP_12TET,
    SNAP_OFF,
    PitchGridModel,
    build_pitch_grid,
    snap_cents_12tet,
    snap_cents_grid,
)
from acouscope.dsp.units import hz_to_cents  # noqa: E402


def test_snap_12tet_exact():
    snapped, dev = snap_cents_12tet(np.array([0.0, 1200.0, -2400.0]))
    assert np.allclose(snapped, [0.0, 1200.0, -2400.0])
    assert np.allclose(dev, 0.0)


def test_snap_12tet_within_semitone():
    c = float(hz_to_cents(445.0))
    snapped, dev = snap_cents_12tet(np.array([c]))
    assert abs(snapped[0]) < 1e-9
    assert 0.0 < dev[0] < 50.0


def test_snap_12tet_fold():
    snapped, dev = snap_cents_12tet(np.array([60.0, -60.0]))
    assert np.allclose(snapped, [100.0, -100.0])
    assert np.allclose(dev, [-40.0, 40.0])


def test_snap_grid_nearest():
    grid = np.array([0.0, 150.0, 300.0])
    snapped, dev = snap_cents_grid(np.array([100.0]), grid)
    assert snapped[0] == 150.0
    assert dev[0] == -50.0


def test_snap_grid_on_grid_point():
    grid = np.array([0.0, 150.0, 300.0])
    snapped, dev = snap_cents_grid(np.array([150.0]), grid)
    assert snapped[0] == 150.0
    assert dev[0] == 0.0


def test_snap_grid_empty_identity():
    c = np.array([33.3, -12.0])
    snapped, dev = snap_cents_grid(c, np.array([]))
    assert np.allclose(snapped, c)
    assert np.allclose(dev, 0.0)


def test_from_contour_two_notes():
    dt = 0.01
    t1 = np.arange(0, 1.0, dt)
    t2 = np.arange(1.3, 2.3, dt)
    times = np.concatenate([t1, t2])
    f0 = np.concatenate([np.full(t1.size, 220.0), np.full(t2.size, 330.0)])
    conf = np.ones_like(times)
    m = PitchGridModel.from_contour(times, f0, conf)
    assert len(m.notes) == 2
    assert abs(m.notes[0].f0_hz - 220.0) < 1e-9
    assert abs(m.notes[1].f0_hz - 330.0) < 1e-9
    assert m.notes[1].start_s == pytest.approx(1.3)


def test_gap_merge():
    dt = 0.01
    t = np.arange(0, 1.0, dt)
    f0 = np.full(t.size, 220.0)
    conf = np.ones_like(t)
    conf[50:53] = 0.0
    m = PitchGridModel.from_contour(t, f0, conf)
    assert len(m.notes) == 1


def test_min_dur_drop():
    dt = 0.01
    t = np.arange(0, 0.5, dt)
    f0 = np.full(t.size, 220.0)
    conf = np.ones_like(t)
    conf[:5] = 0.0
    conf[8:12] = 0.0
    m = PitchGridModel.from_contour(t, f0, conf)
    assert len(m.notes) == 1


def test_apply_snap_preserves_f0():
    dt = 0.01
    t = np.arange(0, 0.5, dt)
    f0 = np.full(t.size, 445.0)
    m = PitchGridModel.from_contour(t, f0, None, min_dur=0.01)
    m.snap_mode = SNAP_12TET
    m.apply_snap()
    nt = m.notes[0]
    assert nt.f0_hz == 445.0
    assert nt.snapped_f0_hz == pytest.approx(440.0, abs=1e-6)
    assert 0.0 < nt.deviation_cents < 50.0


def test_apply_snap_off_identity():
    dt = 0.01
    t = np.arange(0, 0.2, dt)
    m = PitchGridModel.from_contour(t, np.full(t.size, 445.0), None, min_dur=0.01)
    m.snap_mode = SNAP_OFF
    m.apply_snap()
    assert m.notes[0].snapped_f0_hz == m.notes[0].f0_hz
    assert m.notes[0].deviation_cents == 0.0


def test_serialization_roundtrip():
    dt = 0.01
    t = np.arange(0, 0.5, dt)
    m = PitchGridModel.from_contour(t, np.full(t.size, 445.0), None, min_dur=0.01)
    m.snap_mode = SNAP_12TET
    m.apply_snap()
    m2 = PitchGridModel.from_dict(m.to_dict())
    assert m2.snap_mode == SNAP_12TET
    assert len(m2.notes) == len(m.notes)
    a, b = m.notes[0], m2.notes[0]
    assert (a.start_s, a.end_s, a.f0_hz, a.conf) == (b.start_s, b.end_s, b.f0_hz, b.conf)
    assert b.snapped_f0_hz == pytest.approx(a.snapped_f0_hz)


def test_empty_contour():
    m = PitchGridModel.from_contour(np.array([]), np.array([]), None)
    assert m.notes == []


def test_build_pitch_grid_off_identity():
    t_ = np.arange(0, 0.5, 0.01)
    f0 = np.full(t_.size, 441.5)
    g = build_pitch_grid(t_, f0, None, SNAP_OFF)
    assert g.snap_mode == SNAP_OFF
    assert g.notes
    assert all(n.snapped_f0_hz == n.f0_hz for n in g.notes)
    assert all(n.deviation_cents == 0.0 for n in g.notes)


def test_build_pitch_grid_12tet():
    t_ = np.arange(0, 0.5, 0.01)
    f0 = np.full(t_.size, 445.0)
    g = build_pitch_grid(t_, f0, None, SNAP_12TET)
    assert g.snap_mode == SNAP_12TET
    nt = g.notes[0]
    assert nt.f0_hz == 445.0  # 原始 f0 不修改
    assert nt.snapped_f0_hz == pytest.approx(440.0, abs=1e-6)
    assert 0.0 < nt.deviation_cents < 50.0


def test_build_pitch_grid_nan_safe():
    t_ = np.arange(0, 1.0, 0.01)
    f0 = np.full(t_.size, 220.0)
    f0[:40] = np.nan
    f0[80:] = np.nan
    g = build_pitch_grid(t_, f0, None, SNAP_OFF)
    assert len(g.notes) == 1
    assert g.notes[0].f0_hz == 220.0


def test_build_pitch_grid_unknown_mode_falls_back():
    t_ = np.arange(0, 0.5, 0.01)
    f0 = np.full(t_.size, 441.5)
    g = build_pitch_grid(t_, f0, None, "custom-grid")
    assert g.snap_mode == SNAP_OFF
    assert g.notes[0].snapped_f0_hz == g.notes[0].f0_hz
