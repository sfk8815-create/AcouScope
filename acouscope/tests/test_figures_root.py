# SPDX-License-Identifier: GPL-3.0-only
"""参照系对比的模板根音参数（figures.reference_comparison_data / _from_audio）判据。FIGURES_ROOT_TEST_V1

判据 1：root_hz 缺省 ⇒ 输出逐键与旧行为相同（不新增键）；=440.0 ⇒ 读数逐值同旧、另登记根音。
判据 2：给定根音时，degrees / deviations 与「换根模板逐段现算」逐值相等；根音登记随件。
判据 3：非法根音有齿；from_audio 透传并登记。
"""

import math

import numpy as np
import pytest
import soundfile as sf

from acouscope.analysis.pitch_grid import _segment_degree, build_pitch_grid
from acouscope.analysis.pitch_stream import stream_pitch
from acouscope.analysis.tunings.root import root_hz, with_root
from acouscope.analysis.tunings.templates import get_template
from acouscope.visualization.figures import (
    reference_comparison_data,
    reference_comparison_from_audio,
)

SR = 44100
TEMPLATES4 = ["12tet", "qin_lu", "just_major", "chinese_sanfen_sunyi_12"]
#: 五个稳定音（相对十二平均律整体高 30 音分），供 HMM 分出多段
TONES_HZ = tuple(f * 2.0 ** (30.0 / 1200.0) for f in (261.63, 293.66, 349.23, 392.0, 440.0))


def _tones_wav(path, *, dur_each=0.6, gap=0.12):
    parts = []
    for f in TONES_HZ:
        t = np.arange(int(SR * dur_each)) / SR
        env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)
        parts.append(0.2 * env * np.sin(2 * np.pi * f * t))
        parts.append(np.zeros(int(SR * gap)))
    sf.write(str(path), np.concatenate(parts), SR)
    return path


def _model(path):
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    sig = data.mean(axis=1)
    tr = stream_pitch(signal=sig, sr=int(sr), fmin=60.0, fmax=1500.0, block_seconds=30.0)
    f0 = np.asarray(tr.f0_hz, dtype=float)
    return build_pitch_grid(tr.times, f0, tr.confidence, segmenter="hmm", tuning=get_template("12tet"))


@pytest.fixture()
def model(tmp_path):
    m = _model(_tones_wav(tmp_path / "tones.wav"))
    assert len(m.notes) >= 3
    return m


# ---- 判据 1：缺省与 440.0 逐位同旧行为 -----------------------------------


def test_default_root_matches_legacy(model):
    legacy = reference_comparison_data(model, templates=TEMPLATES4, limit=50, note_name=True)
    explicit_none = reference_comparison_data(
        model, templates=TEMPLATES4, limit=50, note_name=True, root_hz=None
    )
    a4 = reference_comparison_data(
        model, templates=TEMPLATES4, limit=50, note_name=True, root_hz=440.0
    )
    assert explicit_none == legacy
    assert "template_root_hz" not in legacy
    assert "template_root_state" not in legacy
    for key in (
        "degrees", "deviations_cents", "median_deviation_cents", "changed_share",
        "note_names", "changed_count_note", "changed_indices_note",
    ):
        assert a4[key] == legacy[key], key
    assert a4["template_root_hz"] == 440.0
    assert a4["template_root_state"] == "given"
    assert set(a4) - set(legacy) == {"template_root_hz", "template_root_state"}


# ---- 判据 2：给定根音逐值等于独立现算 -------------------------------------


@pytest.mark.parametrize(
    "root",
    [
        root_hz("tonic", tonic="F", anchor_cents=90.45),
        root_hz("tonic", tonic="G", anchor_cents=66.0),
        root_hz("hz", hz=300.0),
    ],
)
def test_rooted_degrees_match_independent_recompute(model, root):
    data = reference_comparison_data(
        model, templates=TEMPLATES4, limit=50, note_name=True, root_hz=root
    )
    assert data["template_root_hz"] == root
    assert data["template_root_state"] == "given"
    notes = list(model.notes)[:50]
    for row, (name, degs, devs) in enumerate(
        zip(data["templates"], data["degrees"], data["deviations_cents"])
    ):
        tuning = with_root(get_template(name), root)
        for k, note in enumerate(notes):
            deg, dev = _segment_degree(note.f0_hz, tuning)
            assert degs[k] == deg, (name, k)
            assert devs[k] == (None if dev is None else round(float(dev), 2)), (name, k)
    assert data["changed_count_note"]["12tet"] == 0


def test_root_at_segment_pitch_gives_zero_deviation(model):
    note = list(model.notes)[0]
    data = reference_comparison_data(
        model, templates=["12tet", "qin_lu"], limit=1, root_hz=float(note.f0_hz)
    )
    assert data["degrees"] == [[0], [0]]
    assert data["deviations_cents"] == [[0.0], [0.0]]


def test_root_change_alters_assignment(model):
    a4 = reference_comparison_data(model, templates=TEMPLATES4, limit=50, note_name=True)
    f_root = reference_comparison_data(
        model, templates=TEMPLATES4, limit=50, note_name=True,
        root_hz=root_hz("tonic", tonic="F", anchor_cents=90.45),
    )
    assert f_root["deviations_cents"] != a4["deviations_cents"]


# ---- 判据 3：非法根音有齿；from_audio 透传 --------------------------------


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_invalid_root_raises(model, bad):
    with pytest.raises(ValueError):
        reference_comparison_data(model, templates=["12tet"], limit=3, root_hz=bad)


def test_from_audio_passes_root_through(tmp_path):
    wav = _tones_wav(tmp_path / "tones.wav")
    root = root_hz("tonic", tonic="F", anchor_cents=90.45)
    res = reference_comparison_from_audio(
        str(wav), tmp_path, window_s=30.0, templates=["12tet", "qin_lu"],
        limit=20, note_name=True, root_hz=root, dpi=72, formats=("png",), stem="rc_root",
    )
    assert res["template_root_hz"] == root
    plain = reference_comparison_from_audio(
        str(wav), tmp_path, window_s=30.0, templates=["12tet", "qin_lu"],
        limit=20, note_name=True, dpi=72, formats=("png",), stem="rc_plain",
    )
    assert "template_root_hz" not in plain
    assert set(res) - set(plain) == {"template_root_hz"}
