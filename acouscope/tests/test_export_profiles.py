# SPDX-License-Identifier: GPL-3.0-only
"""M-3 导出 profile 测试；与 M-2 契约互补，不改既有三件。

覆盖：custom/DAT63/GBT31219.4 × JSON/CSV/XML 三格式导出与回读、profile JSON
登记形状（standard/scope/六键 element）、XML 叶逐字预期、旧版（M-2）IMDI
XML 可读、未知 profile 拒绝，以及 DAT63_SLOTS/GBT_SLOTS 与
FIELD_TERMS.std_slots 的槽位一致性守卫（防两处漂）。
"""

from __future__ import annotations

import json

import pytest

from acouscope.annotation import export
from acouscope.annotation.metadata import (
    DAT63_SLOTS,
    FIELD_TERMS,
    GBT_SLOTS,
    SessionMetadata,
)

# 统一 fixture：全 12 标准键 + 1 自定义键（逐字，设计约定 ①-4）
FIXTURE = {
    "Identifier": "/field/AC-2026-001.wav",
    "Title": "AcouScope 田野录音",
    "Creator": "张三",
    "Date": "2026-08-15",
    "Location": "贵州省黔东南州",
    "GenreContext": "飞歌/山地民歌",
    "ActorRole": "主唱",
    "SamplingRate": 44100,
    "BitDepth": 16,
    "Format": "WAV",
    "Channels": 1,
    "Duration": 12.5,
    "Note": "田野笔记甲",
}


def _session() -> SessionMetadata:
    m = SessionMetadata()
    for k, v in FIXTURE.items():
        m.set(k, v)
    return m


# ---------------- 1-2 custom 现行为（M-2 契约不破） ----------------

def test_custom_json_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    export.export_session_json(p, _session())
    assert export.load_session_json(p).to_dict() == _session().to_dict()


def test_custom_csv_roundtrip(tmp_path):
    p = tmp_path / "s.csv"
    export.export_session_csv(p, _session())
    assert export.load_session_csv(p).to_dict() == _session().to_dict()


# ---------------- 3-5 DAT63 ----------------

def test_dat63_json_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    export.export_session_json(p, _session(), export.PROFILE_DAT63)
    assert export.load_session_json(p).to_dict() == _session().to_dict()


def test_dat63_csv_roundtrip(tmp_path):
    p = tmp_path / "s.csv"
    export.export_session_csv(p, _session(), export.PROFILE_DAT63)
    assert export.load_session_csv(p).to_dict() == _session().to_dict()


def test_dat63_xml_leaves(tmp_path):
    p = tmp_path / "s.xml"
    export.export_session_xml(p, _session(), export.PROFILE_DAT63)
    leaves = export.load_session_xml(p)
    # 键=官方名（入表）/字段键（未入表与自定义），17 条逐字（M-8a 四项空值照渲染；标签不被 _safe_tag 改写）
    assert leaves == {
        "唯一标识符": "/field/AC-2026-001.wav",
        "题名": "AcouScope 田野录音",
        "责任者": "张三",
        "摄录时间": "2026-08-15",
        "Location": "贵州省黔东南州",
        "主题": "飞歌/山地民歌",
        "ActorRole": "主唱",
        "音频采样率": "44100",
        "音频量化位数": "16",
        "格式名称": "WAV",
        "声道": "1",
        "时间长度": "12.5",
        "计算机文件名": "",
        "计算机文件大小": "",
        "聚合层次": "",
        "保管期限": "",
        "Note": "田野笔记甲",
    }


# ---------------- 6-8 GBT31219.4 ----------------

def test_gbt_json_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    export.export_session_json(p, _session(), export.PROFILE_GBT)
    assert export.load_session_json(p).to_dict() == _session().to_dict()


def test_gbt_csv_roundtrip(tmp_path):
    p = tmp_path / "s.csv"
    export.export_session_csv(p, _session(), export.PROFILE_GBT)
    assert export.load_session_csv(p).to_dict() == _session().to_dict()


def test_gbt_xml_leaves(tmp_path):
    p = tmp_path / "s.xml"
    export.export_session_xml(p, _session(), export.PROFILE_GBT)
    leaves = export.load_session_xml(p)
    # 键=系统名（表1）/中文名（表2 项）/字段键（未入表与自定义），17 条逐字（M-8a 四项空值照渲染）
    assert leaves == {
        "infoResourceIdentifier": "/field/AC-2026-001.wav",
        "题名": "AcouScope 田野录音",
        "agentName": "张三",
        "actionDateTime": "2026-08-15",
        "Location": "贵州省黔东南州",
        "GenreContext": "飞歌/山地民歌",
        "ActorRole": "主唱",
        "samplingFrequency": "44100",
        "quantizationPrecision": "16",
        "format": "WAV",
        "numberOfChannels": "1",
        "Duration": "12.5",
        "FileName": "",
        "FileSize": "",
        "AggregationLevel": "",
        "RetentionPeriod": "",
        "Note": "田野笔记甲",
    }


# ---------------- 9 JSON 登记形状 ----------------

def test_dat63_json_shape(tmp_path):
    p = tmp_path / "s.json"
    export.export_session_json(p, _session(), export.PROFILE_DAT63)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["profile"] == "DAT63"
    assert data["standard"] == "DA/T 63-2017"
    assert "M76-M96" in data["scope"]
    for e in data["elements"]:
        assert set(e) == {"field", "code", "name", "table", "value", "note"}
    ident = next(e for e in data["elements"] if e["field"] == "Identifier")
    assert ident["code"] == "M5"
    # 未入表字段与自定义键 note 标注
    loc = next(e for e in data["elements"] if e["field"] == "Location")
    assert loc["note"] == "标准外自定义"
    note = next(e for e in data["elements"] if e["field"] == "Note")
    assert note["note"] == "标准外自定义（自定义字段）"


def test_gbt_json_shape(tmp_path):
    p = tmp_path / "s.json"
    export.export_session_json(p, _session(), export.PROFILE_GBT)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["profile"] == "GBT31219.4"
    assert data["standard"] == "GB/T 31219.4-2014"
    assert data["scope"] == "表1/表2 对应元素"
    for e in data["elements"]:
        assert set(e) == {"field", "code", "name", "table", "value", "note"}
    ident = next(e for e in data["elements"] if e["field"] == "Identifier")
    assert ident["code"] == "infoResourceIdentifier"
    assert ident["table"] == "表1"
    dur = next(e for e in data["elements"] if e["field"] == "Duration")
    assert dur["note"] == "标准外自定义"


# ---------------- 10 槽位一致性守卫（机读表 vs std_slots） ----------------

def test_dat63_slots_guard():
    by_key = {t.key: t for t in FIELD_TERMS}
    for field, (code, name, _note) in DAT63_SLOTS.items():
        assert f"{code} {name}" in by_key[field].std_slots["DAT63"], field


def test_gbt_slots_guard():
    by_key = {t.key: t for t in FIELD_TERMS}
    for field, (code, name, _table, _note) in GBT_SLOTS.items():
        slot = by_key[field].std_slots["GBT31219.4"]
        if code:
            assert f"{code} {name}" in slot, field
        else:
            assert name in slot, field


# ---------------- 11 旧（M-2 版）IMDI XML 可读 ----------------

def test_old_imdi_xml_readable(tmp_path):
    p = tmp_path / "old.xml"
    p.write_text(
        '<IMDI><Session><Name>AC-2026-001</Name><Title>旧档</Title>'
        "<Resources><MediaFile><Keys>"
        '<Key Name="SamplingRate">44100</Key>'
        "</Keys></MediaFile></Resources></Session></IMDI>",
        encoding="utf-8",
    )
    leaves = export.load_session_xml(p)
    assert leaves["Session.Name"] == "AC-2026-001"
    assert leaves["Session.Title"] == "旧档"
    assert leaves["Session.Resources.MediaFile.Keys.Key.SamplingRate"] == "44100"


# ---------------- 13 未知 profile 拒绝 ----------------

@pytest.mark.parametrize(
    "fn",
    [export.export_session_json, export.export_session_csv, export.export_session_xml],
    ids=["json", "csv", "xml"],
)
def test_unknown_profile_rejected(tmp_path, fn):
    with pytest.raises(ValueError, match="未知 profile"):
        fn(tmp_path / "out", _session(), "bogus")


# ---------------- 12 IMDI profile（M-4b：PROFILE_IMDI）----------------

class TestImdiProfile:
    """M-4b：PROFILE_IMDI —— xml 走 IMDI 结构（同 custom）；json/csv 走
    IMDI 路径版 elements（code=槽位路径、name=末段、Key 者 @Name）+ 回读。
    """

    def test_imdi_json_roundtrip(self, tmp_path):
        p = tmp_path / "s.json"
        export.export_session_json(p, _session(), export.PROFILE_IMDI)
        assert export.load_session_json(p).to_dict() == _session().to_dict()

    def test_imdi_csv_roundtrip(self, tmp_path):
        p = tmp_path / "s.csv"
        export.export_session_csv(p, _session(), export.PROFILE_IMDI)
        assert export.load_session_csv(p).to_dict() == _session().to_dict()

    def test_imdi_xml_valid_and_custom_unchanged(self, tmp_path):
        """M-6a 分叉后：IMDI 侧根为 {ns}METATRANSCRIPT，custom 侧根仍 IMDI（无命名空间）。

        取代旧的「IMDI 与 custom XML 叶集相等」用例——分叉后两侧叶集本就不相等
        （IMDI 出完整骨架、custom 只落有值槽），故只断言根形态分野，不断言相等。
        """
        p_imdi = tmp_path / "imdi.xml"
        p_custom = tmp_path / "custom.xml"
        export.export_session_xml(p_imdi, _session(), export.PROFILE_IMDI)
        export.export_session_xml(p_custom, _session(), export.PROFILE_CUSTOM)
        import xml.etree.ElementTree as ET
        imdi_root = ET.parse(p_imdi).getroot()
        custom_root = ET.parse(p_custom).getroot()
        assert imdi_root.tag == "{http://www.mpi.nl/IMDI/Schema/IMDI}METATRANSCRIPT"
        assert custom_root.tag == "IMDI"
        # custom 仍是无命名空间 M-2 形状：Session 为其直接子元素
        assert custom_root.find("Session") is not None

    def test_imdi_json_shape(self, tmp_path):
        p = tmp_path / "s.json"
        export.export_session_json(p, _session(), export.PROFILE_IMDI)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["profile"] == "IMDI"
        assert data["standard"] == "IMDI 3.0.22"
        assert data["scope"] == "Session 结构（字段级映射）"
        for e in data["elements"]:
            assert set(e) == {"field", "code", "name", "table", "value", "note"}
        # 官方槽位路径作 code、末段作 name
        ident = next(e for e in data["elements"] if e["field"] == "Identifier")
        assert ident["code"] == "Session/Name"
        assert ident["name"] == "Name"
        assert ident["note"] == ""
        # 技术四项与自定义键：Keys/Key + @Name=字段键（与 to_imdi() 口径一致）
        sr = next(e for e in data["elements"] if e["field"] == "SamplingRate")
        assert sr["code"] == "Session/Resources/MediaFile/Keys/Key"
        assert sr["name"] == "Key"
        assert sr["note"] == "@Name=SamplingRate"
        note = next(e for e in data["elements"] if e["field"] == "Note")
        assert note["code"] == "Session/MDGroup/Keys/Key"
        assert note["name"] == "Key"
        assert note["note"] == "@Name=Note"
