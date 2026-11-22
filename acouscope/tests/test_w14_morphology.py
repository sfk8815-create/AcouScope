# SPDX-License-Identifier: GPL-3.0-only
"""W-14-07 中国音乐形态学扩展字段判据（``annotation/metadata.py``＋``export.py``）。

要点：① 独立命名空间（``FIELD_TERMS`` 仍 16 项）；② 结构与取值校验（必填子字段、
confidence 0–1、枚举、未知键）；③ 导出为独立 ``morphology`` 块／列／段，
`profile_field_table` 不含这些字段；④ 空块时旧导出件逐字不变。
"""

import json

import pytest

from acouscope.annotation.export import (
    MORPHOLOGY_EXPORT_FIELDS,
    export_session_csv,
    export_session_json,
    export_session_xml,
    load_session_csv,
    load_session_json,
    load_session_xml,
    morphology_from_flat,
    profile_field_table,
)
from acouscope.annotation.metadata import (
    FIELD_TERMS,
    MORPHOLOGY_ANNOTATION_CHILDREN,
    MORPHOLOGY_CAVITY_TYPES,
    MORPHOLOGY_FIELDS,
    MORPHOLOGY_KEYS,
    MORPHOLOGY_NOTE,
    SessionMetadata,
    check_morphology_fields,
    morphology_field_table,
    normalize_morphology,
)

_SAMPLE = {
    "CavityType": "上趋",
    "CavityCoreAnnotation": {
        "annotator": "A1",
        "method": "stable 运行中位偏离",
        "template": "qin_lu",
        "confidence": 0.8,
    },
}


def test_namespace_is_independent():
    """① 4 主字段 + 4 子字段；FIELD_TERMS 仍 16；取值枚举四值。"""
    assert len(FIELD_TERMS) == 16
    assert MORPHOLOGY_KEYS == (
        "CavityPosition", "CavityType", "NotePosition", "CavityCoreAnnotation",
    )
    assert MORPHOLOGY_ANNOTATION_CHILDREN == (
        "annotator", "method", "template", "confidence",
    )
    assert len(morphology_field_table()) == 8
    assert MORPHOLOGY_CAVITY_TYPES == ("上趋", "下趋", "平直", "未分类")
    # 形态学字段不得出现在标准字段字典里
    standard_keys = {term.key for term in FIELD_TERMS}
    assert standard_keys.isdisjoint(MORPHOLOGY_KEYS)
    assert "不属 DAT63" in MORPHOLOGY_NOTE and "不认证范畴" in MORPHOLOGY_NOTE


def test_validation_rules():
    """② 结构与取值校验逐条。"""
    assert check_morphology_fields(None) == []
    assert check_morphology_fields(_SAMPLE) == []
    # 缺 annotator／method／template 即报错
    for missing in ("annotator", "method", "template"):
        payload = json.loads(json.dumps(_SAMPLE))
        payload["CavityCoreAnnotation"].pop(missing)
        assert any(missing in problem for problem in check_morphology_fields(payload))
    # confidence 越界／非数
    over = json.loads(json.dumps(_SAMPLE))
    over["CavityCoreAnnotation"]["confidence"] = 1.2
    assert any("0,1" in problem.replace("[", "").replace("]", "")
               or "[0,1]" in problem for problem in check_morphology_fields(over))
    text_conf = json.loads(json.dumps(_SAMPLE))
    text_conf["CavityCoreAnnotation"]["confidence"] = "高"
    assert any("confidence" in problem for problem in check_morphology_fields(text_conf))
    # 枚举
    assert any("CavityType" in p for p in check_morphology_fields({"CavityType": "吟"}))
    # 未知键（防标准字段混入）
    assert any("未知" in p for p in check_morphology_fields({"Title": "x"}))
    # 未知子字段
    bad_child = json.loads(json.dumps(_SAMPLE))
    bad_child["CavityCoreAnnotation"]["score"] = 1
    assert any("score" in p for p in check_morphology_fields(bad_child))
    # 空值不臆造：空串视为未标注，不报错也不补默认
    assert check_morphology_fields({"CavityPosition": ""}) == []
    assert normalize_morphology({"CavityPosition": "", "CavityType": "平直"}) == {
        "CavityType": "平直"
    }


def _session():
    session = SessionMetadata()
    session.set("Identifier", "ID-1")
    session.set("Title", "良宵引")
    session.set_morphology(_SAMPLE)
    return session


def test_json_block_is_independent(tmp_path):
    """③ JSON 独立块；标准 elements 不含形态学；回读无损。"""
    session = _session()
    for profile in ("custom", "DAT63", "GBT31219.4", "IMDI"):
        path = tmp_path / f"s_{profile}.json"
        export_session_json(path, session, profile)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["morphology"]["CavityType"] == "上趋"
        assert data["morphology_note"] == MORPHOLOGY_NOTE
        elements = data.get("elements") or []
        assert all(
            not str(element["field"]).startswith("morphology") for element in elements
        )
        back = load_session_json(path)
        assert back.get_morphology()["CavityType"] == "上趋"
        assert back.get_morphology()["CavityCoreAnnotation"]["annotator"] == "A1"


def test_csv_columns_prefixed(tmp_path):
    """③ CSV：custom 宽表带 ``morphology.`` 前缀列；长表追加独立行；回读无损。"""
    session = _session()
    custom = tmp_path / "custom.csv"
    export_session_csv(custom, session, "custom")
    header = custom.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "morphology.CavityType" in header
    assert all(key in header for key in MORPHOLOGY_EXPORT_FIELDS[:3])
    back = load_session_csv(custom)
    assert back.get_morphology()["CavityType"] == "上趋"
    assert back.get_morphology()["CavityCoreAnnotation"]["confidence"] == 0.8

    dat = tmp_path / "dat.csv"
    export_session_csv(dat, session, "DAT63")
    body = dat.read_text(encoding="utf-8")
    assert "morphology.CavityCoreAnnotation.annotator" in body
    assert morphology_from_flat({"morphology.CavityType": "平直"}) == {"CavityType": "平直"}


def test_xml_morphology_section(tmp_path):
    """③ XML：独立 ``<morphology>`` 段（与 Session 平级/追加），叶节点可回读。"""
    session = _session()
    for profile in ("custom", "DAT63", "IMDI"):
        path = tmp_path / f"s_{profile}.xml"
        export_session_xml(path, session, profile)
        leaves = load_session_xml(path)
        assert leaves.get("morphology.CavityType") == "上趋"
        assert leaves.get("morphology.CavityCoreAnnotation.template") == "qin_lu"
        written = path.read_text(encoding="utf-8")
        assert "<morphology" in written
        assert written.count("<morphology") == 1


def test_profile_field_table_unchanged(tmp_path):
    """③ 标准 profile 字段表不含形态学字段（逐条不变）。"""
    table = profile_field_table()
    assert table  # 非空
    assert all(not str(row["field"]).startswith("morphology") for row in table)
    assert all(row["field"] in {term.key for term in FIELD_TERMS} for row in table)


def test_empty_morphology_keeps_legacy_output(tmp_path):
    """④ 空块 ⇒ 旧导出件逐字不变（不新增键/列/段）。"""
    session = SessionMetadata()
    session.set("Title", "无扩展")
    path = tmp_path / "plain.json"
    export_session_json(path, session, "custom")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "morphology" not in data
    xml = tmp_path / "plain.xml"
    export_session_xml(xml, session, "custom")
    assert "<morphology" not in xml.read_text(encoding="utf-8")
    csv_path = tmp_path / "plain.csv"
    export_session_csv(csv_path, session, "custom")
    header = csv_path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert not any(col.startswith("morphology.") for col in header)


def test_validate_morphology_helper():
    """② 会话级入口：validate_morphology 与 check_morphology_fields 同值。"""
    session = _session()
    assert session.validate_morphology() == []
    session.set_morphology({"CavityCoreAnnotation": {"method": "m"}})
    problems = session.validate_morphology()
    assert problems and any("annotator" in p for p in problems)
    assert SessionMetadata().validate_morphology() == []
