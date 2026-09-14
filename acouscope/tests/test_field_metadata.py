# SPDX-License-Identifier: GPL-3.0-only
"""田野元数据模型测试（T-004-1）。FIELD_META_TEST_V1"""

import pytest

from acouscope.annotation import AnnotationModel
from acouscope.annotation.metadata import (
    FIELD_TERMS,
    REQUIRED_KEYS,
    SessionMetadata,
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

    def test_to_imdi_lossless(self):
        """AT-06-3: IMDI 映射无损——标准槽位 + Additional 覆盖全部字段。"""
        m = _meta(custom_note="田野笔记甲")
        imdi = m.to_imdi()
        s = imdi["IMDI"]["Session"]
        assert s["Name"] == "苗族飞歌采集"
        assert s["Actor"]["FullName"] == "张三"
        assert s["Resources"]["SamplingRate"] == "44100"
        # 无损：每个原始字段经槽位路径都能在 IMDI 结构中找回
        recovered = dict(s.get("Additional", {}))
        for t in FIELD_TERMS:
            if not t.imdi_slot:
                continue
            node = s
            ok = True
            for part in t.imdi_slot.split("."):
                if part == "Session":
                    continue  # Session 即 s 本身
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            if ok:
                recovered[t.key] = node
        for k, v in m.values.items():
            assert str(recovered.get(k, "")) == str(v), f"丢失字段 {k}"

    def test_to_heritage_mapping(self):
        h = _meta().to_heritage()
        assert h["项目名称"] == "苗族飞歌采集"
        assert h["传承人/表演者"] == "张三"
        assert h["地区"] == "贵州省黔东南州"
        assert h["技术信息"]["采样率"] == "44100"


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
