# SPDX-License-Identifier: GPL-3.0-only
"""导出格式无损测试（T-004-2）。EXPORT_TEST_V1"""

import pytest

from acouscope.annotation import AnnotationModel
from acouscope.annotation.export import (
    PITCH_FIELDS,
    export_pitches_csv,
    export_pitches_json,
    export_session_xml,
    load_pitches_csv,
    load_pitches_json,
    load_session_xml,
)
from acouscope.annotation.metadata import SessionMetadata


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
        custom_note="自定义字段应无损保留",  # 非 FIELD_TERMS 键 → Additional
    )
    kw.update(overrides)
    return SessionMetadata.from_audio(**kw)


def _pitches() -> list:
    m = AnnotationModel()
    m.add_pitch(t_ms=0, f0_hz=220.0, cent_ref=440.0, confidence=0.97,
                label="起点", session_id="AC-2026-001", note="低音区, 带逗号")
    m.add_pitch(t_ms=500, f0_hz=442.5, cent_ref=440.0, confidence=0.88,
                label="a\"b", session_id="AC-2026-001", note="带引号与\n换行")
    return m.pitches


class TestJsonExport:
    def test_json_round_trip(self, tmp_path):
        """AT-06-4: JSON round-trip 全字段无损（含自定义元数据字段）。"""
        p = tmp_path / "out.json"
        meta, pitches = _meta(), _pitches()
        export_pitches_json(p, pitches, meta)
        meta2, pitches2 = load_pitches_json(p)
        assert meta2.values == meta.values  # 含 custom_note
        assert len(pitches2) == len(pitches)
        for a, b in zip(pitches, pitches2):
            assert a.t_ms == b.t_ms and a.f0_hz == b.f0_hz
            assert a.cents == b.cents and a.cent_ref == b.cent_ref
            assert a.confidence == b.confidence
            assert a.label == b.label and a.note == b.note
            assert a.session_id == b.session_id

    def test_json_rejects_foreign_format(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text('{"format": "other"}', encoding="utf-8")
        with pytest.raises(ValueError):
            load_pitches_json(p)

    def test_json_empty_pitches(self, tmp_path):
        p = tmp_path / "empty.json"
        export_pitches_json(p, [], _meta())
        meta2, pitches2 = load_pitches_json(p)
        assert pitches2 == [] and meta2.values == _meta().values


class TestCsvExport:
    def test_csv_round_trip(self, tmp_path):
        """AT-06-5: CSV round-trip 浮点精度可逆，特殊字符安全。"""
        p = tmp_path / "out.csv"
        pitches = _pitches()
        export_pitches_csv(p, pitches)
        pitches2 = load_pitches_csv(p)
        assert len(pitches2) == len(pitches)
        for a, b in zip(pitches, pitches2):
            assert a.t_ms == b.t_ms and a.f0_hz == b.f0_hz
            assert a.cents == b.cents and a.confidence == b.confidence
            assert a.label == b.label and a.note == b.note

    def test_csv_header_exact(self, tmp_path):
        p = tmp_path / "hdr.csv"
        export_pitches_csv(p, [])
        import csv as _csv
        with open(p, encoding="utf-8", newline="") as f:
            assert next(_csv.reader(f)) == PITCH_FIELDS

    def test_csv_rejects_bad_header(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("x,y\n1,2", encoding="utf-8")
        with pytest.raises(ValueError):
            load_pitches_csv(p)


class TestXmlExport:
    @staticmethod
    def _flatten(d, prefix=""):
        out = {}
        for k, v in d.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(TestXmlExport._flatten(v, p))
            else:
                out[p] = str(v)
        return out

    def test_xml_lossless_flatten_equal(self, tmp_path):
        """AT-06-6: XML 叶节点 {路径:值} 与 IMDI dict flatten 完全相等。"""
        p = tmp_path / "session.xml"
        meta = _meta()
        export_session_xml(p, meta)
        assert load_session_xml(p) == self._flatten(meta.to_imdi()["IMDI"])

    def test_xml_extra_field_in_additional(self, tmp_path):
        """无损：非标准槽位字段（custom_note）进 Session.Additional 且可回读。"""
        p = tmp_path / "extra.xml"
        export_session_xml(p, _meta())
        leaves = load_session_xml(p)
        assert leaves["Session.Additional.custom_note"] == "自定义字段应无损保留"
        assert leaves["Session.Name"] == "苗族飞歌采集"
        assert leaves["Session.Actor.FullName"] == "张三"
        assert leaves["Session.Resources.SamplingRate"] == "44100"
