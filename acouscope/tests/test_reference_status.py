# SPDX-License-Identifier: GPL-3.0-only
"""A4 基准来源记录测试（任务件-20261026 · T-4）。REFERENCE_STATUS_TEST_V1

覆盖：
① 三态可辨 —— ``default-nominal``／``user-set``／``calibrated``；
② ``calibrated`` 须附参考音标识，无标识即拒（禁伪标）；
③ 记录**不写全局值**：改值仍走 ``dsp.units.set_reference_hz``（单点写入面）；
④ ``reference_hz`` 恒取实时值，与全局单源逐位一致；
⑤ 误差范围随件记录（二元组）；
⑥ 未知状态／非法入参一律 ValueError，不静默吞。
"""

import pytest

pytest.importorskip("numpy")

from acouscope.dsp.reference_status import (  # noqa: E402
    REF_STATUSES,
    REF_STATUS_CALIBRATED,
    REF_STATUS_DEFAULT_NOMINAL,
    REF_STATUS_USER_SET,
    declare_reference,
    get_reference_status,
    reset_reference_status,
)
from acouscope.dsp.units import A4_FREQ, get_reference_hz, set_reference_hz  # noqa: E402


@pytest.fixture(autouse=True)
def _restore():
    """每条用例后把全局值与记录都复位（测试不得污染进程状态）。"""
    old = get_reference_hz()
    reset_reference_status()
    try:
        yield
    finally:
        set_reference_hz(old)
        reset_reference_status()


def test_default_nominal_is_initial_state():
    """① 未声明 ⇒ ``default-nominal``，且 source 标 platform-default。"""
    status = get_reference_status()
    assert status["reference_status"] == REF_STATUS_DEFAULT_NOMINAL
    assert status["source"] == "platform-default"
    assert status["detail"] == {}


def test_three_states_are_distinguishable():
    """① 三态互异，且都落在枚举面内。"""
    assert len(set(REF_STATUSES)) == 3
    assert {
        REF_STATUS_DEFAULT_NOMINAL,
        REF_STATUS_USER_SET,
        REF_STATUS_CALIBRATED,
    } == set(REF_STATUSES)

    # user-set：显式设定后
    assert set_reference_hz(442.0) is True
    after_set = declare_reference(status=REF_STATUS_USER_SET, source="test:apply")
    assert after_set["reference_status"] == REF_STATUS_USER_SET
    assert after_set["reference_hz"] == pytest.approx(442.0)

    # calibrated：附参考音标识与误差范围
    after_cal = declare_reference(
        status=REF_STATUS_CALIBRATED,
        source="test:reference-tone",
        reference_id="D-ARCHIVE-A4",
        error_range_cents=(-1.2, 1.2),
    )
    assert after_cal["reference_status"] == REF_STATUS_CALIBRATED
    assert after_cal["detail"]["reference_id"] == "D-ARCHIVE-A4"
    assert after_cal["detail"]["error_range_cents"] == [-1.2, 1.2]


def test_calibrated_requires_reference_id():
    """② 无参考音标识不得记为 calibrated（禁伪标）。"""
    with pytest.raises(ValueError, match="reference_id"):
        declare_reference(status=REF_STATUS_CALIBRATED, source="test:no-id")


def test_unknown_status_rejected():
    """⑥ 未知状态一律 ValueError，不静默落到默认态。"""
    with pytest.raises(ValueError, match="未知"):
        declare_reference(status="calibrated-by-eye")
    with pytest.raises(ValueError, match="未知"):
        declare_reference(status="")


def test_ledger_does_not_write_global_value():
    """③ 记录只记来源，不写全局值（改值仍走 ``units.set_reference_hz``）。"""
    before = get_reference_hz()
    declare_reference(status=REF_STATUS_USER_SET, source="test:ledger-only")
    assert get_reference_hz() == pytest.approx(before)

    # 全局值由 units 单点写入；记录随后照实跟随
    assert set_reference_hz(432.0) is True
    assert get_reference_status()["reference_hz"] == pytest.approx(432.0)
    assert set_reference_hz(before)


def test_reference_hz_tracks_single_source():
    """④ ``reference_hz`` 恒取 ``units.get_reference_hz()`` 实时值（防记录另存一份）。"""
    old = get_reference_hz()
    try:
        for value in (415.0, 432.0, 442.0):
            assert set_reference_hz(value) is True
            assert get_reference_status()["reference_hz"] == pytest.approx(value)
    finally:
        set_reference_hz(old)
    assert get_reference_status()["reference_hz"] == pytest.approx(old)


def test_reset_returns_to_undeclared():
    """① 复位后回到未声明态（不残留上一次的来源）。"""
    declare_reference(status=REF_STATUS_CALIBRATED, source="x", reference_id="D-1")
    assert get_reference_status()["reference_status"] == REF_STATUS_CALIBRATED
    reset_reference_status()
    assert get_reference_status()["reference_status"] == REF_STATUS_DEFAULT_NOMINAL
    assert get_reference_status()["detail"] == {}
