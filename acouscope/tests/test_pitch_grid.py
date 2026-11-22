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


def test_grid_cents_for_tuning_12tet_and_sanfen():
    """B1-02①：grid_cents_for_tuning 按模板生成网格（12tet 等距 / 三分损益非等距）。"""
    from acouscope.analysis.pitch_grid import grid_cents_for_tuning
    from acouscope.analysis.tunings import get_template

    cn = grid_cents_for_tuning(get_template("12tet"))
    assert cn[0] == 0.0
    assert cn[-1] == 1200.0
    assert np.allclose(np.diff(cn), 100.0)  # 12tet：等距 100 cent
    sf = grid_cents_for_tuning(get_template("chinese_sanfen_sunyi_12"))
    assert sf[0] == 0.0
    assert sf[-1] == 1200.0
    # 正对照：非等距 ⇒ 证明按模板生成，不是恒返回 12tet（咬 M3）
    assert not np.allclose(np.diff(sf), 100.0)
    assert not np.allclose(cn, sf)


def test_snap_cents_grid_uneven_nearest_law_position():
    """B1-02②：非等距网格吸附到最近律位；deviation = 到最近律位音分差（非 12tet 偏差）。"""
    from acouscope.analysis.pitch_grid import grid_cents_for_tuning
    from acouscope.analysis.tunings import get_template

    grid = grid_cents_for_tuning(get_template("chinese_sanfen_sunyi_12"))
    mid = (grid[0] + grid[1]) / 2.0  # 恰在前两律位中间
    snapped, dev = snap_cents_grid(np.array([mid]), grid)
    assert snapped[0] == grid[0]  # 等距取较低侧（既有口径 take_left）
    assert dev[0] == pytest.approx(mid - grid[0])  # 到最近律位的音分差
    # 语义断言：非等距网格下 deviation 不表示「相对 12tet 的高低」
    _, d12 = snap_cents_12tet(np.array([mid]))
    assert dev[0] != pytest.approx(d12[0])


def test_pitch_note_state_runs_roundtrip():
    """B1-01a③：PitchNote.state_runs 经 to_dict/from_dict 往返逐位一致。

    to_dict 落 list（JSON 友好）；from_dict 白名单还原后逐位一致
    （帧号/秒值/态名）。旧文件无该键 ⇒ 落 ()（另条判据复锁）。
    """
    from acouscope.analysis.pitch_grid import PitchNote

    runs = (
        (0, 3, 0.0, 0.03, "attack"),
        (4, 48, 0.04, 0.48, "stable"),
        (49, 50, 0.49, 0.50, "inter"),
    )
    nt = PitchNote(
        start_s=0.0,
        end_s=0.50,
        f0_hz=220.0,
        conf=0.9,
        state="attack",
        state_runs=runs,
    )
    model = PitchGridModel(notes=[nt], snap_mode=SNAP_OFF)
    entry = model.to_dict()["notes"][0]
    # tuple → list（JSON 友好），逐位一致
    assert entry["state_runs"] == [list(run) for run in runs]
    # from_dict 白名单还原（list → 归一 tuple 后逐位一致）
    back = PitchGridModel.from_dict(model.to_dict()).notes[0]
    assert tuple(tuple(run) for run in back.state_runs) == runs


def test_segment_degree_matches_pcp_frame_level():
    """B1-02a②：段级音级归属与 PCP 帧级 _degree_index_for 同输入逐位一致。

    合成稳态信号（三分损益十二律某音级频率，ref=440 现读换算），
    build_pitch_grid(segmenter="hmm", tuning=<模板>) 后段级 degree_index
    逐位等于 pcp._degree_index_for 对同段 f0 的读数（直接 import 对拍，
    禁重实现）；degree_deviation_cents 同式复算相等。
    正对照：12tet 等距律位归属与手算一致（防恒返同一值）。
    """
    from acouscope.analysis.pcp import _degree_index_for
    from acouscope.analysis.tunings.templates import get_template
    from acouscope.dsp.units import cents_to_hz

    tuning = get_template("chinese_sanfen_sunyi_12")
    ref = float(tuning.reference_freq)
    # 稳态信号：全程单一频率（第 5 音级律位频率 ref=440 现读换算；另取微偏
    # +7 音分的同律位邻域频率——相邻律位间距 ≥ 90 音分，归属不变而偏差非零）
    for target_cents, expect_dev in ((float(tuning.degrees[5]), None), (float(tuning.degrees[5]) + 7.0, 7.0)):
        f0_hz = float(cents_to_hz(target_cents, ref_freq=ref))
        t_ = np.arange(0.0, 0.5, 0.01)
        g = build_pitch_grid(
            t_, np.full(t_.size, f0_hz), None, SNAP_OFF, segmenter="hmm", tuning=tuning
        )
        assert g.notes, "稳态信号应至少解出一段"
        for nt in g.notes:
            cents = float(hz_to_cents(nt.f0_hz, ref_freq=ref))
            expected_degree = int(_degree_index_for(tuning, np.array([cents]))[0])
            assert nt.degree_index == expected_degree  # 逐位对拍（帧级同式）
            # 同式复算：到最近律位的音分差
            assert nt.degree_deviation_cents == pytest.approx(
                cents - tuning.degree_to_cents(expected_degree)
            )
            # 正对照：稳态段归属到该律位本体（非恒返同一值）
            assert nt.degree_index == 5
            if expect_dev is not None:
                # 偏差锚定（防 deviation 恒零骗过）
                assert nt.degree_deviation_cents == pytest.approx(expect_dev, abs=1e-6)

    # 12tet 正对照：等距律位归属与手算一致（A4=440Hz → degree 0；A3=220Hz → degree -12）
    tet = get_template("12tet")
    for f0, expect_deg in ((440.0, 0), (220.0, -12)):
        t2 = np.arange(0.0, 0.3, 0.01)
        g2 = build_pitch_grid(
            t2, np.full(t2.size, f0), None, SNAP_OFF, segmenter="hmm", tuning=tet
        )
        assert g2.notes[0].degree_index == expect_deg
        assert g2.notes[0].degree_deviation_cents == pytest.approx(0.0, abs=1e-6)
    # 12tet 微偏正对照：445Hz 归 A4（degree 0）且偏差 ≈ +19.56 音分（非零）
    t3 = np.arange(0.0, 0.3, 0.01)
    g3 = build_pitch_grid(
        t3, np.full(t3.size, 445.0), None, SNAP_OFF, segmenter="hmm", tuning=tet
    )
    assert g3.notes[0].degree_index == 0
    assert g3.notes[0].degree_deviation_cents == pytest.approx(19.5556, abs=0.01)


def test_build_pitch_grid_no_tuning_zero_change():
    """B1-02a③：不传 tuning ⇒ 零行为变更（两字段全 None）；旧项目文件无键不抛。"""
    t_ = np.arange(0, 0.5, 0.01)
    f0 = np.full(t_.size, 220.0)
    for seg in ("hmm", "simple"):
        g = build_pitch_grid(t_, f0, None, SNAP_OFF, segmenter=seg)
        assert g.notes, f"{seg} 路径应至少出一段"
        for nt in g.notes:
            assert nt.degree_index is None  # 未传律制 ⇒ 不归属
            assert nt.degree_deviation_cents is None
    # 旧项目文件（notes 无两键）→ from_dict 不抛、落 None
    legacy = {
        "snap_mode": "off",
        "grid_cents": None,
        "notes": [{"start_s": 0.0, "end_s": 0.5, "f0_hz": 220.0, "conf": 0.9}],
    }
    restored = PitchGridModel.from_dict(legacy)
    assert restored.notes[0].degree_index is None
    assert restored.notes[0].degree_deviation_cents is None
