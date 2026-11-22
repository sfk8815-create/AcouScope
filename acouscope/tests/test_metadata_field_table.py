# SPDX-License-Identifier: GPL-3.0-only
"""元数据字段表判据（任务-20261025-平台图导出 丙）。

字段表是论文字段表的机检基准：必须覆盖四个标准槽位（DAT63／GB/T 31219.4／
IMDI／custom）、必填列与运行时校验一致、导出结构可核。表由导出层自身生成，
不是另抄一份映射——本文件的变异用例验证「表被改动时机检会红」。
"""

import csv
import json

from acouscope.annotation.export import (
    FIELD_TABLE_FIELDS,
    PROFILE_DAT63,
    PROFILE_GBT,
    PROFILE_IMDI,
    PROFILE_SLOTS,
    check_profile_field_table,
    export_profile_field_table_csv,
    export_profile_field_table_json,
    profile_field_table,
)
from acouscope.annotation.metadata import FIELD_TERMS, required_for_standard


def test_table_covers_four_slots_and_all_fields():
    """四标准槽位 × 全部标准字段键，无漏项。"""
    table = profile_field_table()
    assert set(PROFILE_SLOTS) == {PROFILE_DAT63, PROFILE_GBT, PROFILE_IMDI, "custom"}
    keys = [term.key for term in FIELD_TERMS]
    for profile in PROFILE_SLOTS:
        covered = {row["field"] for row in table if row["profile"] == profile}
        assert covered == set(keys), f"{profile} 覆盖不全：{set(keys) - covered}"
    assert len(table) == len(PROFILE_SLOTS) * len(keys)


def test_required_column_matches_runtime_validation():
    """必填列须等于该标准下 SessionMetadata.validate 的缺失集（机检非自证）。"""
    table = profile_field_table()
    for profile in PROFILE_SLOTS:
        want = set(required_for_standard(profile))
        got = {row["field"] for row in table if row["profile"] == profile and row["required"]}
        assert got == want, f"{profile}: 表={sorted(got)} 运行时={sorted(want)}"
    # DA/T 63 机读拦盘六键（任务口径）：不得增删
    dat63 = {row["field"] for row in table if row["profile"] == PROFILE_DAT63 and row["required"]}
    assert dat63 == {"Identifier", "Title", "Creator", "Date", "Format", "Duration"}


def test_check_passes_and_detects_tampering():
    """机检空 = 通过；人为削行 ⇒ 必须报问题（防判据恒绿）。"""
    assert check_profile_field_table() == []
    table = profile_field_table()
    broken = [row for row in table if not (row["profile"] == PROFILE_DAT63 and row["field"] == "Title")]
    problems = check_profile_field_table(broken)
    assert any("DAT63" in p and "缺字段" in p for p in problems), problems

    forged = [dict(row) for row in table]
    for row in forged:
        if row["profile"] == PROFILE_GBT and row["field"] == "Identifier":
            row["required"] = True
    assert any("必填集不一致" in p for p in check_profile_field_table(forged))


def test_export_json_and_csv(tmp_path):
    """JSON 带机检结论；CSV 列序固定、布尔落 0/1。"""
    json_path = tmp_path / "fields.json"
    csv_path = tmp_path / "fields.csv"
    export_profile_field_table_json(json_path)
    export_profile_field_table_csv(csv_path)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["fields"] == list(FIELD_TABLE_FIELDS)
    assert data["check"] == []
    assert len(data["rows"]) == len(profile_field_table())

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == list(FIELD_TABLE_FIELDS)
    assert {row["required"] for row in rows} <= {"0", "1"}
    assert {row["profile"] for row in rows} == set(PROFILE_SLOTS)


def test_dat63_slots_are_real_codes_not_placeholders():
    """DAT63 行的槽位路径须非空（占位/空码会被当成已实现，属伪实现）。"""
    table = [row for row in profile_field_table([PROFILE_DAT63])]
    implemented = [row for row in table if row["implemented"]]
    assert implemented, "DAT63 无任何已实现字段"
    assert all(row["code"] for row in implemented)
    assert all(row["standard"] == "DA/T 63-2017" for row in implemented)
