# SPDX-License-Identifier: GPL-3.0-only
"""T-1118 ParamSpinBox 字段内算式：valueFromText 走 parse_number，validate 放行表达式。

判据：
① 输入「2*pi」「min(4,3)」「1.5k」经 interpretText 后落到正确值（并按 range clamp）；
② validate：可算 ⇒ Acceptable；写了一半（"2*"）或乱码 ⇒ Intermediate（不 Invalid）；
③ 原生语义不破：纯数字、带后缀（"450 Hz"）、超范围 clamp 逐字与改前一致。
"""

import math

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QValidator

from acouscope.ui.widgets.param_spin import ParamSpinBox


def _type_and_commit(spin, text: str):
    spin.lineEdit().setText(text)
    spin.interpretText()
    return spin.value()


def test_expression_values(qapp):
    spin = ParamSpinBox()
    spin.setDecimals(6)
    spin.setRange(0.0, 10000.0)
    spin.setSingleStep(1.0)

    assert _type_and_commit(spin, "2*pi") == pytest.approx(2 * math.pi, rel=1e-6)
    assert _type_and_commit(spin, "min(4,3)") == pytest.approx(3.0)
    assert _type_and_commit(spin, "1.5k") == pytest.approx(1500.0)
    assert _type_and_commit(spin, "440*2**(1/12)") == pytest.approx(440 * 2 ** (1 / 12), rel=1e-6)


def test_expression_clamped_to_range(qapp):
    spin = ParamSpinBox()
    spin.setDecimals(1)
    spin.setRange(400.0, 480.0)
    spin.setValue(440.0)
    assert _type_and_commit(spin, "1k") == pytest.approx(480.0), "超上限须 clamp"


def test_validate_states(qapp):
    spin = ParamSpinBox()
    spin.setRange(0.0, 10000.0)
    spin.setDecimals(2)

    assert spin.validate("2*pi", 0)[0] == QValidator.State.Acceptable
    assert spin.validate("12.5", 0)[0] == QValidator.State.Acceptable
    for partial in ("2*", "min(", "abc"):
        assert spin.validate(partial, 0)[0] == QValidator.State.Intermediate, partial


def test_garbage_keeps_previous_value(qapp):
    """不可解析文本不得把值静默改到下限（Qt 原生 valueFromText 返回 0 的坑）。"""
    spin = ParamSpinBox()
    spin.setRange(400.0, 480.0)
    spin.setDecimals(1)
    spin.setValue(440.0)
    assert spin.valueFromText("abc") == pytest.approx(440.0)
    assert spin.valueFromText("2*") == pytest.approx(440.0)
    # 真实输入路径：清空/乱码后失焦仍保留 440
    spin.lineEdit().setText("abc")
    spin.interpretText()
    assert spin.value() == pytest.approx(440.0)


def test_native_semantics_kept(qapp):
    spin = ParamSpinBox()
    spin.setRange(400.0, 480.0)
    spin.setDecimals(1)
    spin.setSuffix(" Hz")
    spin.setValue(440.0)

    assert _type_and_commit(spin, "450.0 Hz") == pytest.approx(450.0)
    assert _type_and_commit(spin, "440") == pytest.approx(440.0)
    assert _type_and_commit(spin, "1e9") == pytest.approx(480.0)   # 原生解析 + clamp
