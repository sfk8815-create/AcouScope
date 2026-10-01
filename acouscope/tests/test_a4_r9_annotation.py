# SPDX-License-Identifier: GPL-3.0-only
"""A4-R9：annotation 层 cent_ref 去写死（未传 ⇒ 取当前 A4；创建时快照）。"""

import pytest

from acouscope.annotation import AnnotationModel, PitchAnnotation
from acouscope.dsp import units


def test_a4r9_default_follows_global_a4(monkeypatch):
    """★ 主判据：未传 cent_ref ⇒ 取当前 A4 参考，且【创建时快照】。"""
    monkeypatch.setattr(units, "_reference_hz", 442.0)
    m = AnnotationModel()
    ann = m.add_pitch(t_ms=0, f0_hz=442.0)
    assert ann.cent_ref == pytest.approx(442.0, abs=1e-12)
    assert ann.cents == pytest.approx(0.0, abs=1e-9)
    # ★ 快照：改全局后，已创建的标注【不变】（本件与 R5 的形态差异）
    monkeypatch.setattr(units, "_reference_hz", 430.0)
    assert ann.cent_ref == pytest.approx(442.0, abs=1e-12)
    assert ann.cents == pytest.approx(0.0, abs=1e-9)


def test_a4r9_explicit_wins(monkeypatch):
    """★ 反向：显式 cent_ref 优先（老行为不变）。"""
    monkeypatch.setattr(units, "_reference_hz", 442.0)
    m = AnnotationModel()
    ann = m.add_pitch(t_ms=0, f0_hz=220.0, cent_ref=220.0)
    assert ann.cent_ref == pytest.approx(220.0, abs=1e-12)
    assert ann.cents == pytest.approx(0.0, abs=1e-9)


def test_a4r9_stored_field_is_required():
    """★ 防回潮守卫：存储字段已【无默认值】⇒ 直构不传必抛 TypeError。"""
    with pytest.raises(TypeError):
        PitchAnnotation(t_ms=0, f0_hz=440.0)
