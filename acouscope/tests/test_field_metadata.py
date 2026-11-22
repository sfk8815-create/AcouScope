# SPDX-License-Identifier: GPL-3.0-only
"""田野元数据模型测试（T-004-1）。FIELD_META_TEST_V1"""

import pytest

from acouscope.annotation import AnnotationModel
from acouscope.annotation.metadata import (
    FIELD_TERMS,
    REQUIRED_KEYS,
    SessionMetadata,
    check_format,
)


def _meta(**overrides) -> SessionMetadata:
    kw = dict(
        identifier="AC-2026-001",
        title="苗族飞歌采集",
        creator="张三",
        date="2026-08-15",
        location="贵州省黔东南州",
        genre_context="飞歌/山地民歌",
        sampling_rate=44100,
        bit_depth=24,
        fmt="WAV",
        channels=1,
        duration_s=123.456,
    )
    kw.update(overrides)
    return SessionMetadata.from_audio(**kw)


class TestSessionMetadata:
    def test_required_fields_complete(self):
        """AT-06-1: 核心要素齐备（Identifier/Title/Creator/Date/Location/Genre）。"""
        assert set(REQUIRED_KEYS) >= {
            "Identifier", "Title", "Creator", "Date", "Location", "GenreContext"
        }
        assert _meta().validate() == []

    def test_validate_missing(self):
        m = _meta(location="")
        missing = m.validate()
        assert "Location" in missing

    def test_tech_metadata(self):
        m = _meta()
        assert m.get("SamplingRate") == "44100"
        assert m.get("BitDepth") == "24"
        assert m.get("Format") == "WAV"

    @staticmethod
    def _recover(session: dict, key: str):
        """按字段键从 IMDI 结构复原值（Keys/Key 列表按 @Name 查；自定义键查 MDGroup）。"""
        term = next((t for t in FIELD_TERMS if t.key == key), None)
        if term is None:
            bucket = session.get("MDGroup", {}).get("Keys", {}).get("Key", [])
        else:
            node = session
            parts = [p for p in term.std_slots["IMDI"].split("/") if p and p != "Session"]
            for part in parts:
                if part == "Key":
                    bucket = node.get("Key", [])
                    break
                node = node.get(part, {})
            else:
                return node
        for item in bucket:
            if item["@Name"] == key:
                return item["#text"]
        return None

    def test_to_imdi_lossless(self):
        """AT-06-3: IMDI 3.0.22 映射无损——标准槽位按 XSD 实位 + MDGroup/Keys/Key 双桶。

        M-6a：根改 `METATRANSCRIPT`；必填件落为空元素（合法化≠臆造）。
        """
        m = _meta(custom_note="田野笔记甲")
        imdi = m.to_imdi()
        meta = imdi["METATRANSCRIPT"]
        assert set(meta) >= {"Session"}                   # 根键 IMDI→METATRANSCRIPT
        s = meta["Session"]
        assert s["Name"] == "AC-2026-001"  # Identifier → 短名/唯一标识〔XSD:771〕
        assert s["Title"] == "苗族飞歌采集"
        assert s["Date"] == "2026-08-15"
        assert s["MDGroup"]["Actors"]["Actor"]["FullName"] == "张三"
        assert s["MDGroup"]["Content"]["Genre"] == "飞歌/山地民歌"
        assert s["MDGroup"]["Location"]["Address"] == "贵州省黔东南州"
        mf = s["Resources"]["MediaFile"]
        assert mf["Format"] == "WAV"
        key_map = {k["@Name"]: k["#text"] for k in mf["Keys"]["Key"]}
        assert key_map == {
            "SamplingRate": "44100", "BitDepth": "24",
            "Channels": "1", "Duration": "00:02:03",
            # M-4b2：from_audio 落值统一 hh:mm:ss（123.456s → 舍入 123s → 00:02:03）
        }
        assert s["MDGroup"]["Keys"]["Key"] == [
            {"@Name": "custom_note", "#text": "田野笔记甲"}
        ]
        # M-6a：无源必填件落为空元素（不臆造洲名/国名/项目名）
        assert s["MDGroup"]["Location"]["Continent"] == ""
        assert s["MDGroup"]["Location"]["Country"] == ""
        assert s["MDGroup"]["Project"]["Name"] == ""
        assert mf["Quality"] == "Unknown"                  # §七-2 官方字面
        assert mf["TimePosition"]["Start"] == "Unspecified"  # §七-2 官方字面
        # 无损：全部 values（含自定义键）经新槽位路径都能在 IMDI 结构中找回
        for k, v in m.values.items():
            assert self._recover(s, k) == str(v), f"丢失字段 {k}"

    def test_to_imdi_child_order_matches_xsd(self):
        """重排后子元素序 == XSD 序列（METATRANSCRIPT/Session/MDGroup/Content/MediaFile/Access）。"""
        s = _meta(custom_note="x").to_imdi()["METATRANSCRIPT"]["Session"]
        assert list(s.keys()) == ["Name", "Title", "Date", "MDGroup", "Resources"]
        assert list(s["MDGroup"].keys()) == [
            "Location", "Project", "Keys", "Content", "Actors"
        ]
        # Content 必填四件序：Genre, CommunicationContext, Languages, Keys
        assert list(s["MDGroup"]["Content"].keys())[:4] == [
            "Genre", "CommunicationContext", "Languages", "Keys"
        ]
        # MediaFile 全树序（§七-2 实测序）
        assert list(s["Resources"]["MediaFile"].keys()) == [
            "ResourceLink", "Type", "Format", "Size", "Quality",
            "RecordingConditions", "TimePosition", "Access", "Keys",
        ]
        # Access 必填五件序（Contact 在末；无源 Description 不补）
        assert list(s["Resources"]["MediaFile"]["Access"].keys()) == [
            "Availability", "Date", "Owner", "Publisher", "Contact"
        ]
        # TimePosition 仅 Start（无源 End 不补）
        assert list(s["Resources"]["MediaFile"]["TimePosition"].keys()) == ["Start"]

    def test_to_heritage_mapping(self):
        h = _meta().to_heritage()
        assert h["项目名称"] == "苗族飞歌采集"
        assert h["传承人/表演者"] == "张三"
        assert h["地区"] == "贵州省黔东南州"
        assert h["技术信息"]["采样率"] == "44100"

    def test_validate_backward_compatible(self):
        """M-4b：validate() 无参 == 现 REQUIRED_KEYS 缺失行为（向后兼容）。"""
        assert _meta().validate() == []
        assert _meta(location="").validate() == ["Location"]

    def test_validate_by_standard(self):
        """M-4b：validate(standard=) 按机读必填集（DAT63 6 键；三家空集恒 []）。"""
        m = _meta(fmt="")  # DAT63 必填的 Format 缺
        missing = m.validate("DAT63")
        assert "Format" in missing
        assert "Location" not in missing  # DA/T 侧非必选（2 进 2 出之出）
        assert "GenreContext" not in missing
        for code in ("GBT31219.4", "IMDI", "custom"):
            assert m.validate(code) == []  # 空集：任何值态都不报缺

    def test_check_format_date(self):
        """M-4b/M-4b2：check_format = Date + Duration 两条（枚举四项不设校验）。"""
        assert check_format("Date", "2026-8-5")  # 不合 → 报
        assert not check_format("Date", "2026-08-05")
        assert not check_format("Date", "2026-10-13 22:04")  # 日期+时间形（自家预填形）不报
        # M-4b2：Duration 解禁——秒形报，hh:mm:ss 放行（小时位两位以上，容纳进位形 24:00:00）
        assert check_format("Duration", "12.5") == "Duration"  # 秒形 → 报
        assert not check_format("Duration", "00:00:12")  # M17 hh:mm:ss 形 → 放行
        assert not check_format("Duration", "24:00:00")  # 进位形合法（银行家舍入产出）
        assert check_format("Duration", "0:0:12") == "Duration"  # 小时位一位 → 报
        assert check_format("Duration", "00:60:00") == "Duration"  # 分位越界 → 报


class TestPitchAnnotation:
    def test_add_pitch_computes_cents(self):
        model = AnnotationModel()
        ann = model.add_pitch(t_ms=123456789, f0_hz=440.0, cent_ref=440.0, session_id="AC-2026-001")
        assert ann.cents == pytest.approx(0.0, abs=1e-9)
        ann2 = model.add_pitch(t_ms=123500000, f0_hz=880.0, cent_ref=440.0)
        assert ann2.cents == pytest.approx(1200.0, abs=1e-6)

    def test_pitch_sorted_and_removable(self):
        model = AnnotationModel()
        model.add_pitch(t_ms=2000, f0_hz=300.0)
        model.add_pitch(t_ms=1000, f0_hz=200.0)
        assert [p.t_ms for p in model.pitches] == [1000, 2000]
        model.remove_pitch(model.pitches[0])
        assert len(model.pitches) == 1
        model.clear_pitches()
        assert model.pitches == []
