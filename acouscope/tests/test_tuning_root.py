# SPDX-License-Identifier: GPL-3.0-only
"""律制模板根音参数（analysis/tunings/root.py）判据。TUNING_ROOT_TEST_V1

判据 1：默认 a4 与现行为逐位一致（冻结面不动）。
判据 2：tonic / hz 取法逐值正确；根音处音级为 0、偏离 0.0；八度处为末级、偏离 0.0。
判据 3：非法输入有齿。
"""

import math

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.pitch_grid import _segment_degree  # noqa: E402
from acouscope.analysis.tunings.root import (  # noqa: E402
    ROOT_MODES,
    root_hz,
    root_record,
    with_root,
)
from acouscope.analysis.tunings.templates import (  # noqa: E402
    PAPER_TEMPLATE_KEYS,
    TEMPLATES,
    get_template,
    list_templates,
)
from acouscope.dsp.units import A4_FREQ, NOTE_NAMES  # noqa: E402

PROBE_HZ = (110.0, 196.0, 261.63, 293.66, 369.99, 440.0, 466.16, 587.33, 880.0, 1318.5)


# ---- 判据 1：默认与现行为逐位一致 ---------------------------------------


def test_default_root_is_a4_freq():
    assert ROOT_MODES == ("a4", "tonic", "hz")
    assert root_hz() == float(A4_FREQ)
    assert root_hz("a4") == 440.0


@pytest.mark.parametrize("key", list_templates())
def test_default_with_root_equals_builtin(key):
    base = get_template(key)
    rooted = with_root(base, root_hz("a4"))
    assert rooted == base
    for f in PROBE_HZ:
        assert _segment_degree(f, rooted) == _segment_degree(f, base)


def test_frozen_surface_unchanged():
    assert len(list_templates()) == 8
    assert len(TEMPLATES) == 8
    assert len(PAPER_TEMPLATE_KEYS) == 6


def test_with_root_does_not_mutate_input():
    base = get_template("qin_lu")
    before = (base.name, base.source, base.degrees, base.reference_freq)
    rooted = with_root(base, 369.99)
    assert (base.name, base.source, base.degrees, base.reference_freq) == before
    assert rooted.degrees == base.degrees
    assert rooted.name == base.name
    assert rooted.source == base.source
    assert rooted.reference_freq == 369.99


# ---- 判据 2：tonic / hz 取法 --------------------------------------------


@pytest.mark.parametrize("tonic", NOTE_NAMES)
@pytest.mark.parametrize("anchor", (0.0, 15.5, 66.0, 90.45, 102.6, -30.0))
def test_tonic_formula(tonic, anchor):
    expect = 440.0 * 2.0 ** (((NOTE_NAMES.index(tonic) - 9) * 100.0 + anchor) / 1200.0)
    assert root_hz("tonic", tonic=tonic, anchor_cents=anchor) == expect


def test_tonic_a_zero_is_a4():
    assert root_hz("tonic", tonic="A", anchor_cents=0.0) == 440.0
    assert root_hz("tonic", tonic="A") == 440.0


def test_hz_mode_passthrough():
    assert root_hz("hz", hz=407.228) == 407.228


@pytest.mark.parametrize("key", ["12tet", "qin_lu", "just_major", "chinese_sanfen_sunyi_12"])
def test_root_degree_zero_and_octave(key):
    base = get_template(key)
    r = root_hz("tonic", tonic="F", anchor_cents=90.45)
    rooted = with_root(base, r)
    assert _segment_degree(r, rooted) == (0, 0.0)
    deg, dev = _segment_degree(2.0 * r, rooted)
    assert deg == base.degree_count
    assert dev == 0.0


def test_root_record_keys():
    assert root_record() == {
        "root_mode": "a4",
        "root_tonic": None,
        "root_anchor_cents": None,
        "root_hz": 440.0,
        "root_label": "A4",
    }
    rec = root_record("tonic", tonic="F", anchor_cents=90.45)
    assert rec["root_mode"] == "tonic"
    assert rec["root_tonic"] == "F"
    assert rec["root_anchor_cents"] == 90.45
    assert rec["root_hz"] == root_hz("tonic", tonic="F", anchor_cents=90.45)
    assert rec["root_label"] == "F+90.45c"
    assert root_record("hz", hz=407.228)["root_label"] == "407.228Hz"


# ---- 判据 3：非法输入有齿 ------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "A4"},
        {"mode": "gong"},
        {"mode": "tonic"},
        {"mode": "tonic", "tonic": "H"},
        {"mode": "tonic", "tonic": "f"},
        {"mode": "tonic", "tonic": "F", "anchor_cents": math.nan},
        {"mode": "tonic", "tonic": "F", "anchor_cents": math.inf},
        {"mode": "hz"},
        {"mode": "hz", "hz": 0.0},
        {"mode": "hz", "hz": -1.0},
        {"mode": "hz", "hz": math.nan},
        {"mode": "a4", "a4_hz": 0.0},
    ],
)
def test_invalid_inputs_raise(kwargs):
    with pytest.raises(ValueError):
        root_hz(**kwargs)


def test_with_root_rejects_bad_args():
    with pytest.raises(TypeError):
        with_root("qin_lu", 440.0)
    for bad in (0.0, -5.0, math.nan, math.inf):
        with pytest.raises(ValueError):
            with_root(get_template("qin_lu"), bad)
