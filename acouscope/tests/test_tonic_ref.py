# SPDX-License-Identifier: GPL-3.0-only
"""双口径音级归属测试（B3-01 后续约定：absolute／main_tone 并报）。"""

import numpy as np
import pytest

from acouscope.analysis.pitch_grid import _segment_degree
from acouscope.analysis.tonic_ref import (
    REF_ABSOLUTE,
    REF_MAIN_TONE,
    TONIC_NAMES,
    degree_rows,
    fit_tonic,
)
from acouscope.analysis.tunings.templates import get_template


class _Note:
    def __init__(self, start_s, end_s, f0_hz):
        self.start_s = start_s
        self.end_s = end_s
        self.f0_hz = f0_hz


class _Model:
    def __init__(self, notes):
        self.notes = notes


def _penta(tonic: str, n_per: int = 100) -> np.ndarray:
    base = 440.0 * 2.0 ** ((TONIC_NAMES.index(tonic) - 9) / 12.0)
    return np.concatenate(
        [np.full(n_per, base * 2.0 ** (off / 12.0)) for off in (0, 2, 4, 7, 9)]
    )


def test_absolute_mode_matches_segment_degree():
    """absolute 口径须与既有段级归属逐位一致（不改写音高）。"""
    tpl = get_template("12tet")
    model = _Model([_Note(0.0, 0.5, 440.0), _Note(0.6, 1.1, 261.63)])
    rows = degree_rows(model, tpl, ref_mode=REF_ABSOLUTE)
    for note, row in zip(model.notes, rows):
        degree, dev = _segment_degree(note.f0_hz, tpl)
        assert row["degree_index"] == degree
        assert row["deviation_cents"] == dev
        assert row["offset_applied_cents"] == 0.0


def test_main_tone_mode_applies_offset():
    """main_tone 口径须按拟合偏移整体移调后再归属，且 offset 留痕。"""
    tpl = get_template("12tet")
    model = _Model([_Note(0.0, 0.5, 466.16)])  # A#4 ≈ A4 + 100 音分
    fit = {"best": {"tonic": "A", "offset_cents": 100.0, "score": 0.9}}
    rows = degree_rows(model, tpl, ref_mode=REF_MAIN_TONE, fit=fit)
    expect_degree, expect_dev = _segment_degree(466.16 * 2.0 ** (-100.0 / 1200.0), tpl)
    assert rows[0]["ref_mode"] == REF_MAIN_TONE
    assert rows[0]["degree_index"] == expect_degree
    assert rows[0]["offset_applied_cents"] == 100.0
    assert rows[0]["deviation_cents"] == pytest.approx(expect_dev, abs=1e-12)


def test_two_modes_coexist_without_overwrite():
    """两口径并存：同一段两行、ref_mode 不同、互不覆盖。"""
    tpl = get_template("12tet")
    model = _Model([_Note(0.0, 0.5, 466.16)])
    fit = {"best": {"tonic": "A", "offset_cents": 100.0, "score": 0.9}}
    abs_rows = degree_rows(model, tpl, ref_mode=REF_ABSOLUTE)
    rel_rows = degree_rows(model, tpl, ref_mode=REF_MAIN_TONE, fit=fit)
    assert abs_rows[0]["segment_id"] == rel_rows[0]["segment_id"]
    assert abs_rows[0]["ref_mode"] != rel_rows[0]["ref_mode"]
    assert abs_rows[0]["offset_applied_cents"] == 0.0
    assert rel_rows[0]["offset_applied_cents"] == 100.0


def test_fit_tonic_identifies_scale_position_not_unique_tonic():
    """正对照：F 五声信号须还原到 F 音阶位置；但半音等价 ⇒ margin 小、主音不唯一。

    这���是「主音拟合必须可审计」的原因：五声模板平移一个半音即另一主音，
    单靠音级类分布只能定到等价类，不能唯一确定主音。
    """
    pos = fit_tonic(_penta("F"))
    pc = (TONIC_NAMES.index(pos["best"]["tonic"]) * 100 + pos["best"]["offset_cents"]) % 1200
    assert pc == pytest.approx(TONIC_NAMES.index("F") * 100, abs=4.0)
    assert pos["margin"] < 0.05, f"F 五声的 margin 应很小（半音等价）：{pos['margin']}"

    even = np.concatenate([np.full(100, 440.0 * 2.0 ** (k / 12.0)) for k in range(12)])
    neg = fit_tonic(even)
    assert neg["margin"] is not None
    assert neg["margin"] <= pos["margin"] + 1e-9, (
        f"均匀音级的 margin 不应更大：pos={pos['margin']} neg={neg['margin']}"
    )


def test_chromatic_template_margin_zero():
    """模板敏感性：十二声模板移调不变 ⇒ margin 必为 0（结构性盲区的直接证据）。"""
    for tonic in ("F", "G", "A"):
        fit = fit_tonic(_penta(tonic), scale="chromatic")
        assert fit["margin"] == pytest.approx(0.0, abs=1e-9), (
            f"{tonic}／chromatic margin={fit['margin']}"
        )
