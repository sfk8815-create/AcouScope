# SPDX-License-Identifier: GPL-3.0-only
"""M-4b 必填集随标准切换守卫（STANDARD_REQUIRED / required_for_standard）。

钉死（设计约定 M-4b §〇-1/〇-2 + §〇-6-4，10-13 侦察定案）：
- DA/T 63 机读必填集 == {Identifier, Title, Creator, Date, Format, Duration}
  （6 键逐字；constraint 内任一 DA/T 码性质为 M 者）；
- GB/T 31219.4 / IMDI / custom 三家必填集 = 空集（GB/T 表1 无 M/O/C 记法、
  IMDI schema 不要求字段有值〔实测空元素 valid=True〕、custom 无外部约束）；
- STANDARD_REQUIRED 键集 == 导出 profile 四码（防两侧漂移）；
- 未知码回落 REQUIRED_KEYS（不抛、不空——未知≠无约束）。
"""

from acouscope.annotation.export import (
    PROFILE_CUSTOM,
    PROFILE_DAT63,
    PROFILE_GBT,
    PROFILE_IMDI,
)
from acouscope.annotation.metadata import (
    REQUIRED_KEYS,
    STANDARD_REQUIRED,
    required_for_standard,
)

DAT63_SIX = frozenset(
    {"Identifier", "Title", "Creator", "Date", "Format", "Duration"}
)


def test_dat63_required_six_keys_verbatim():
    """DA/T 63 必填集 = 6 键逐字（M6/M7/M8/M14/M17/M48 性质为 M 的字段）。"""
    assert STANDARD_REQUIRED["DAT63"] == DAT63_SIX
    assert required_for_standard("DAT63") == DAT63_SIX


def test_other_three_standards_empty():
    """GB/T 31219.4 / IMDI / custom 三家必填集为空集（原文无「必须有值」记法）。"""
    for code in ("GBT31219.4", "IMDI", "custom"):
        assert STANDARD_REQUIRED[code] == frozenset()
        assert required_for_standard(code) == frozenset()


def test_standard_required_keys_match_export_profiles():
    """STANDARD_REQUIRED 键集 == 导出 profile 四码（DAT63/GBT31219.4/IMDI/custom）。"""
    assert set(STANDARD_REQUIRED) == {
        PROFILE_DAT63, PROFILE_GBT, PROFILE_IMDI, PROFILE_CUSTOM,
    }


def test_unknown_code_falls_back_to_required_keys():
    """未知码 → 回落 REQUIRED_KEYS（不抛、不空——未知≠无约束）。"""
    assert required_for_standard("NOPE-99") == frozenset(REQUIRED_KEYS)