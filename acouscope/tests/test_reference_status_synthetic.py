# SPDX-License-Identifier: GPL-3.0-only
"""A4 来源记录：合成信号不得记 calibrated（2026-11-22 修正）。REFERENCE_STATUS_SYNTH_TEST_V1

判据 1：显式 synthetic=True 或来源命中合成标记 ⇒ calibrated 被拒；既有真实参考音写法不受影响。
判据 2：链路自检以 chain_check 随 default-nominal／user-set 登记，状态语义不变。
判据 3：chain_check 类型与组合有齿。
"""

import pytest

pytest.importorskip("numpy")

from acouscope.dsp.reference_status import (  # noqa: E402
    REF_STATUSES,
    REF_STATUS_CALIBRATED,
    REF_STATUS_DEFAULT_NOMINAL,
    REF_STATUS_USER_SET,
    SYNTHETIC_SOURCE_MARKERS,
    declare_reference,
    get_reference_status,
    reset_reference_status,
)
from acouscope.dsp.units import get_reference_hz, set_reference_hz  # noqa: E402

#: 运行 1d11038c87927099 实际登记的来源串（逐字）
RUN_SOURCE = (
    "ISO 16:1975; platform pitch generator; file=Sine_wave_440.wav; "
    "sha256=2b6a375b2ea73dd8a066e4cb83c208cc51d7760bc119597a3cdacce03d76621e; "
    "measured_median_hz=440.0001; bias_cents=+0.0004; p95_cents=0.0038; a4_base_hz=440.0001"
)
RUN_REF_ID = "iso16-1975-sine-440:2b6a375b2ea73dd8a066e4cb83c208cc51d7760bc119597a3cdacce03d76621e"


@pytest.fixture(autouse=True)
def _restore():
    old = get_reference_hz()
    reset_reference_status()
    try:
        yield
    finally:
        set_reference_hz(old)
        reset_reference_status()


def test_enum_unchanged():
    assert REF_STATUSES == ("default-nominal", "user-set", "calibrated")


def test_run_declaration_is_now_rejected():
    with pytest.raises(ValueError, match="合成信号"):
        declare_reference(status=REF_STATUS_CALIBRATED, source=RUN_SOURCE, reference_id=RUN_REF_ID)
    assert get_reference_status()["reference_status"] == REF_STATUS_DEFAULT_NOMINAL


def test_explicit_synthetic_flag_rejected():
    with pytest.raises(ValueError, match="合成信号"):
        declare_reference(status=REF_STATUS_CALIBRATED, source="lab", reference_id="D-1", synthetic=True)


@pytest.mark.parametrize("marker", SYNTHETIC_SOURCE_MARKERS)
def test_each_marker_rejected_in_source(marker):
    with pytest.raises(ValueError, match="合成信号"):
        declare_reference(status=REF_STATUS_CALIBRATED, source=f"x {marker.upper()} y", reference_id="D-1")


@pytest.mark.parametrize("marker", SYNTHETIC_SOURCE_MARKERS)
def test_each_marker_rejected_in_reference_id(marker):
    with pytest.raises(ValueError, match="合成信号"):
        declare_reference(status=REF_STATUS_CALIBRATED, source="lab", reference_id=f"id-{marker}-1")


def test_real_reference_tone_still_calibrates():
    out = declare_reference(
        status=REF_STATUS_CALIBRATED,
        source="test:reference-tone",
        reference_id="D-ARCHIVE-A4",
        error_range_cents=(-1.2, 1.2),
    )
    assert out["reference_status"] == REF_STATUS_CALIBRATED
    assert out["detail"] == {"reference_id": "D-ARCHIVE-A4", "error_range_cents": [-1.2, 1.2]}


@pytest.mark.parametrize("status", [REF_STATUS_DEFAULT_NOMINAL, REF_STATUS_USER_SET])
def test_chain_check_recorded_without_changing_status(status):
    check = {"file": "Sine_wave_440.wav", "measured_median_hz": 440.0001, "bias_cents": 0.0004}
    out = declare_reference(status=status, source=RUN_SOURCE, chain_check=check)
    assert out["reference_status"] == status
    assert out["detail"] == {"chain_check": check}
    check["bias_cents"] = 99.0
    assert get_reference_status()["detail"]["chain_check"]["bias_cents"] == 0.0004


def test_default_detail_unchanged_without_chain_check():
    out = declare_reference(status=REF_STATUS_USER_SET, source="settings:reference_hz@apply")
    assert out["detail"] == {}


def test_chain_check_type_and_combination_guarded():
    with pytest.raises(ValueError, match="chain_check"):
        declare_reference(status=REF_STATUS_USER_SET, chain_check=["not", "dict"])
    with pytest.raises(ValueError, match="chain_check"):
        declare_reference(status=REF_STATUS_CALIBRATED, source="lab", reference_id="D-1",
                          chain_check={"a": 1})
