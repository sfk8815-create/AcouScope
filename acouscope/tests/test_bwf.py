# SPDX-License-Identifier: GPL-3.0-only
"""M-5；规格取证件见 02_References/BWF_bext_iXML_notes_20261012.md（§二–§六）。

bwf.py 写/读核心的字节级测试：bext/INFO/iXML 注入 + 读回 + 数据完整性 +
布局 + 偶数对齐 + 读侧独立性 + 重复嵌入去重。
"""
from __future__ import annotations

import struct
import wave

import pytest

from acouscope.audio.bwf import (
    build_coding_history,
    embed_bwf,
    parse_vendor_tree,
    read_bwf,
)

# fixture 字段（ASCII 与中文混合，验证 bext ASCII 域 / iXML UTF-8 分工）
FIELDS = {
    "Title": "Field Take 01",          # ASCII → bext.Description + iXML.PROJECT
    "Identifier": "AC-2026-001",       # ASCII ≤32 → bext.OriginatorReference
    "Date": "2026-08-15",              # YYYY-MM-DD → bext.OriginationDate
    "Creator": "张三",                  # 中文 → bext 拒、iXML 承载
    "Location": "贵州省黔东南州",       # 中文 → iXML
    "Note": "field-note-7",            # ASCII → INFO.ICMT + iXML
    "SamplingRate": "8000",
    "GenreContext": "飞歌/山地民歌",    # 中文 → iXML
}


def _write_wav(path, sample_rate: int = 8000, seconds: float = 0.25) -> None:
    """写 PCM_16 单声道 wav（wave 模块；确定性非零数据，同既有测试范式）。"""
    n = int(sample_rate * seconds)
    frames = b"".join(struct.pack("<h", ((i * 37) % 2001) - 1000)
                      for i in range(n))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)


def _chunk_table(raw: bytes) -> list[tuple[str, int]]:
    """遍历 RIFF chunk 表 → [(ckID, size), ...]（跳过 pad）。"""
    out: list[tuple[str, int]] = []
    pos = 12
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4].decode("ascii", "replace")
        size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        out.append((cid, size))
        pos += 8 + size + (size % 2)
    return out


def _find_chunk(raw: bytes, cid: bytes):
    """找 chunk 数据（data 载荷，不含 pad）。"""
    pos = 12
    while pos + 8 <= len(raw):
        size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        if raw[pos:pos + 4] == cid:
            return raw[pos + 8:pos + 8 + size]
        pos += 8 + size + (size % 2)
    return None


class TestBwf:
    """bwf.py 写/读核心（M-5）。"""

    def test_bext_roundtrip(self, tmp_path):
        """bext 回读全字段（含 7FFF 未用值 + 中文 Originator 被拒）。"""
        wav = tmp_path / "take.wav"
        _write_wav(wav)
        embed_bwf(wav, dict(FIELDS))
        b = read_bwf(wav)["bext"]
        assert b is not None
        assert b["Description"] == "Field Take 01"
        assert b["OriginatorReference"] == "AC-2026-001"
        assert b["OriginationDate"] == "2026-08-15"
        assert b["OriginationTime"] == ""          # 无时刻源→留空（裁一A），不写零点
        assert b["Version"] == 2
        assert b["TimeReference"] == 0
        for k in ("LoudnessValue", "LoudnessRange", "MaxTruePeakLevel",
                  "MaxMomentaryLoudness", "MaxShortTermLoudness"):
            assert b[k] == 0x7FFF
        assert b["Originator"] == ""          # 中文被拒，不臆造
        assert b["CodingHistory"] == \
            "A=PCM,F=8000,W=16,M=mono,T=AcouScope\r\n"

    def test_info_roundtrip(self, tmp_path):
        """INFO 回读（ISFT 恒写；IART 因中文被拒不出现）。"""
        wav = tmp_path / "take.wav"
        _write_wav(wav)
        embed_bwf(wav, dict(FIELDS))
        info = read_bwf(wav)["info"]
        assert info is not None
        assert info["ISFT"] == "AcouScope"
        assert info["INAM"] == "Field Take 01"
        assert info["ICRD"] == "2026-08-15"
        assert info["ICMT"] == "field-note-7"
        assert "IART" not in info            # 中文被拒

    def test_ixml_full_values(self, tmp_path):
        """iXML 全值（中文完整，vendor 树 + PROJECT/SPEED）。"""
        wav = tmp_path / "take.wav"
        _write_wav(wav)
        embed_bwf(wav, dict(FIELDS))
        r = read_bwf(wav)
        assert r["ixml_raw"] is not None
        vt = parse_vendor_tree(r["ixml_raw"])
        assert vt["Creator"] == "张三"
        assert vt["Location"] == "贵州省黔东南州"
        assert vt["GenreContext"] == "飞歌/山地民歌"
        assert vt["Note"] == "field-note-7"
        assert "<PROJECT>Field Take 01</PROJECT>" in r["ixml_raw"]
        assert "<FILE_SAMPLE_RATE>8000</FILE_SAMPLE_RATE>" in r["ixml_raw"]

    def test_data_integrity(self, tmp_path):
        """embed 前后 wave 读回一致 + data 区前/后各 1KB 逐字相等。"""
        wav = tmp_path / "take.wav"
        _write_wav(wav)
        before = _find_chunk(wav.read_bytes(), b"data")
        embed_bwf(wav, dict(FIELDS))
        after = _find_chunk(wav.read_bytes(), b"data")
        assert before is not None and after is not None
        assert before[:1024] == after[:1024]
        assert before[-1024:] == after[-1024:]
        with wave.open(str(wav), "rb") as wf:
            assert wf.getnframes() == 2000
            assert wf.getframerate() == 8000
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2

    def test_byte_layout(self, tmp_path):
        """字节级布局：块序 fmt/bext/LIST/iXML/data；RIFF/bext ckSize 精确。"""
        wav = tmp_path / "take.wav"
        _write_wav(wav)
        embed_bwf(wav, dict(FIELDS))
        raw = wav.read_bytes()
        assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
        riff_size = struct.unpack("<I", raw[4:8])[0]
        assert riff_size == len(raw) - 8
        table = _chunk_table(raw)
        assert [cid for cid, _ in table] == ["fmt ", "bext", "LIST", "iXML", "data"]
        bext_size = dict(table)["bext"]
        ch = build_coding_history(8000, 16, 1)
        assert bext_size == 602 + len(ch.encode("ascii"))

    def test_even_alignment(self, tmp_path):
        """iXML 块 size 恒偶；触发补位时末字节 == 0x20 且读回以空格结尾。

        注：Title 在 iXML 中双出现（PROJECT + ACOUSCOPE 树），单改其长度只改
        偶数倍字节、总字节奇偶恒定，故用仅单次出现的 Location 调奇偶以触发补位。
        """
        found = False
        for k in range(1, 20):
            wav = tmp_path / f"t{k}.wav"
            _write_wav(wav)
            fields = dict(FIELDS)
            fields["Location"] = "L" * k       # 仅 ACOUSCOPE 树 1 次出现，改奇偶
            embed_bwf(wav, fields)
            raw = wav.read_bytes()
            ixml = _find_chunk(raw, b"iXML")
            assert ixml is not None
            assert len(ixml) % 2 == 0          # size 恒偶（_find_chunk 长度 == ckSize）
            if ixml[-1:] == b"\x20":           # 触发补位
                assert read_bwf(wav)["ixml_raw"].endswith(" ")
                found = True
                break
        assert found, "未找到触发补位的字段长度"

    def test_external_chunk_readable(self, tmp_path):
        """读侧独立性：手工构造 fmt+bext+data（不经写侧）→ 读出字段。"""
        fmt_body = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
        coding = b"A=PCM,F=8000,W=16,M=mono,T=AcouScope\r\n"
        bext_fixed = (
            b"Ext Take\x00".ljust(256, b"\x00")
            + b"\x00" * 32 + b"\x00" * 32 + b"\x00" * 10 + b"\x00" * 8
            + struct.pack("<II", 0, 0)
            + struct.pack("<H", 2)
            + b"\x00" * 64
            + struct.pack("<5h", 0x7FFF, 0x7FFF, 0x7FFF, 0x7FFF, 0x7FFF)
            + b"\x00" * 180
        )
        assert len(bext_fixed) == 602
        bext_body = bext_fixed + coding

        def chunk(cid: bytes, body: bytes) -> bytes:
            out = cid + struct.pack("<I", len(body)) + body
            if len(body) % 2:
                out += b"\x00"
            return out

        body = (b"WAVE" + chunk(b"fmt ", fmt_body)
                + chunk(b"bext", bext_body) + chunk(b"data", b"\x00\x00" * 100))
        raw = b"RIFF" + struct.pack("<I", len(body)) + body
        wav = tmp_path / "ext.wav"
        wav.write_bytes(raw)
        r = read_bwf(wav)
        assert r["bext"] is not None
        assert r["bext"]["Description"] == "Ext Take"
        assert r["bext"]["CodingHistory"] == \
            "A=PCM,F=8000,W=16,M=mono,T=AcouScope\r\n"

    def test_double_embed_dedup(self, tmp_path):
        """重复嵌入去重：二次嵌入后仍单份三块，值 == 新。"""
        wav = tmp_path / "take.wav"
        _write_wav(wav)
        embed_bwf(wav, dict(FIELDS))
        fields2 = dict(FIELDS)
        fields2["Title"] = "Field Take 02"
        embed_bwf(wav, fields2)
        table = _chunk_table(wav.read_bytes())
        assert [cid for cid, _ in table] == ["fmt ", "bext", "LIST", "iXML", "data"]
        assert read_bwf(wav)["bext"]["Description"] == "Field Take 02"

