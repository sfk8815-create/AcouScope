# SPDX-License-Identifier: GPL-3.0-only
"""BWF 嵌入与读回（M-5）。规格逐条依据 02_References/BWF_bext_iXML_notes_20261012.md
（EBU Tech 3285 v2 / EBU R98-1999 / iXML 规范；行文引文见该件 §二–§六）。

只做 RIFF 字节级：bext（3285 v2 布局）+ LIST INFO + iXML（UTF-8，偶数对齐）；
纯标准库（struct/wave/xml.etree），不依赖 soundfile/ffmpeg。
"""
from __future__ import annotations

import os
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

# bext 定长部分（3285 v2 表偏移累计）：Description 256 + Originator 32 +
# OriginatorReference 32 + OriginationDate 10 + OriginationTime 8 +
# TimeReferenceLow/High 8 + Version 2 + UMID 64 + Loudness×5 10 + Reserved 180。
_BEXT_FIXED = 602

_LOUDNESS_UNUSED = 0x7FFF          # 3285 v2 §2.4：未用 loudness 明文 "7FFFh"
_BEXT_VERSION = 0x0002             # v2 布局
_COPY_BUF = 1 << 16                # 流式拷贝缓冲 ≥64KB
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def build_coding_history(sample_rate: int, bit_depth: int, channels: int,
                         *, app: str = "AcouScope") -> str:
    """生成单行 CodingHistory（EBU R98-1999 语法，见取证件 §三）。

    形如 A=PCM,F=8000,W=16,M=mono,T=AcouScope + CR/LF（T= 位放 app 标识）。
    channels==1→mono、==2→stereo、其余→mono（本仓导出恒单声道，仅健壮性）。
    """
    mode = "stereo" if channels == 2 else "mono"
    return (f"A=PCM,F={int(sample_rate)},W={int(bit_depth)},"
            f"M={mode},T={app}\r\n")


def embed_bwf(path, fields: dict) -> None:
    """向 WAV 注入 bext / LIST(INFO) / iXML 三块（写侧；流式重写）。

    - 取样参数（channels / bits / framerate）从 `fmt ` 块现读，不信调用方。
    - 注入位置 = `fmt ` 之后、`data` 之前，序：bext → LIST(INFO) → iXML；
      原文件已存在的 bext / iXML / INFO LIST 先剔除再注入（去重）。
    - 各块偶数对齐；RIFF ckSize 同步增量。
    - 写临时件（同目录 `<name>.bwftmp`）→ os.replace 原子替换；异常清理临时件。
    - 非 RIFF/WAVE（或读不出 fmt）→ ValueError。
    """
    path = Path(path)
    with open(path, "rb") as src:
        header = src.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError(f"非 RIFF/WAVE 文件: {path}")

        # 扫描 chunk 表（按偏移，不整读入内存）
        chunks: list[tuple[bytes, int, int]] = []   # (ckID, data_offset, size)
        src.seek(12)
        while True:
            hdr = src.read(8)
            if len(hdr) < 8:
                break
            ckid = hdr[:4]
            size = struct.unpack("<I", hdr[4:8])[0]
            data_offset = src.tell()
            chunks.append((ckid, data_offset, size))
            src.seek(size, 1)               # 跳过 data
            if size % 2:
                src.seek(1, 1)              # 跳过 pad byte

        # 现读 fmt（channels / framerate / bits）+ 定位首个 data
        fmt_chunk = None
        data_chunk = None
        for ckid, doff, size in chunks:
            if ckid == b"fmt " and fmt_chunk is None:
                fmt_chunk = (doff, size)
            elif ckid == b"data" and data_chunk is None:
                data_chunk = (doff, size)
        if fmt_chunk is None:
            raise ValueError(f"非 RIFF/WAVE 文件（缺 fmt 块）: {path}")
        src.seek(fmt_chunk[0])
        channels, framerate, bits = _parse_fmt(src.read(fmt_chunk[1]))

        bext_bytes = _build_bext(fields, framerate, bits, channels)
        info_bytes = _build_info_list(fields)
        ixml_bytes = _build_ixml(fields, framerate, bits)

        # 分类：keep = 其他保留 chunk（剔除 bext/iXML/INFO-LIST；fmt/data 端点）
        keep: list[tuple[bytes, int, int]] = []
        for ckid, doff, size in chunks:
            if ckid in (b"fmt ", b"data", b"bext", b"iXML"):
                continue
            if ckid == b"LIST" and _is_info_list(src, doff):
                continue
            keep.append((ckid, doff, size))

        # 新 RIFF ckSize（含各块 pad）
        new_size = 4  # "WAVE"
        new_size += _chunk_total(fmt_chunk[1])
        for _c, _d, s in keep:
            new_size += _chunk_total(s)
        new_size += _chunk_total(len(bext_bytes))
        new_size += _chunk_total(len(info_bytes))
        new_size += _chunk_total(len(ixml_bytes))
        if data_chunk is not None:
            new_size += _chunk_total(data_chunk[1])

        tmp = path.parent / (path.name + ".bwftmp")
        try:
            with open(tmp, "wb") as out:
                out.write(b"RIFF")
                out.write(struct.pack("<I", new_size))
                out.write(b"WAVE")
                _copy_chunk(src, out, b"fmt ", fmt_chunk[0], fmt_chunk[1])
                for ckid, doff, size in keep:
                    _copy_chunk(src, out, ckid, doff, size)
                _write_chunk(out, b"bext", bext_bytes)
                _write_chunk(out, b"LIST", info_bytes)
                _write_chunk(out, b"iXML", ixml_bytes)
                if data_chunk is not None:
                    _copy_chunk(src, out, b"data",
                                data_chunk[0], data_chunk[1])
            os.replace(tmp, path)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise


def read_bwf(path) -> dict:
    """通用 RIFF 遍历读回（读侧独立于自家写侧，外部 BWF 亦能读）。

    返回 {"bext": dict|None, "info": dict|None, "ixml_raw": str|None}；
    无块纯 WAV → 三键全 None（不抛）；iXML 用 utf-8 宽容解码。
    """
    raw = Path(path).read_bytes()
    bext = None
    info = None
    ixml_raw = None
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        pos = 12
        n = len(raw)
        while pos + 8 <= n:
            ckid = raw[pos:pos + 4]
            size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
            body = raw[pos + 8:pos + 8 + size]
            if ckid == b"bext":
                bext = _decode_bext(body)
            elif ckid == b"LIST" and body[:4] == b"INFO":
                info = _decode_info(body[4:])
            elif ckid == b"iXML":
                ixml_raw = body.decode("utf-8", errors="replace")
            pos += 8 + size
            if size % 2:
                pos += 1
    return {"bext": bext, "info": info, "ixml_raw": ixml_raw}


def parse_vendor_tree(ixml_raw, vendor: str = "ACOUSCOPE") -> dict:
    """解析 BWFXML/<vendor> 子元素 → {元素名: 文本}。

    空 / 缺 / 解析失败 → {}（不抛）。
    """
    if not ixml_raw:
        return {}
    try:
        root = ET.fromstring(ixml_raw)
    except ET.ParseError:
        return {}
    node = root.find(vendor)
    if node is None:
        return {}
    out: dict[str, str] = {}
    for child in node:
        out[child.tag] = child.text or ""
    return out


# ---------------------------------------------------------------------------
# fmt / RIFF 辅助
# ---------------------------------------------------------------------------

def _parse_fmt(body: bytes) -> tuple[int, int, int]:
    """标准 PCM fmt：channels(H) / framerate(I) / bits(H)。"""
    if len(body) < 16:
        raise ValueError("fmt 块过短，无法读取取样参数")
    channels = struct.unpack("<H", body[2:4])[0]
    framerate = struct.unpack("<I", body[4:8])[0]
    bits = struct.unpack("<H", body[14:16])[0]
    return channels, framerate, bits


def _chunk_total(size: int) -> int:
    """chunk 占用总字节数（8 头 + data + 奇数 pad）。"""
    return 8 + size + (size % 2)


def _is_info_list(src, doff: int) -> bool:
    """判断 LIST 块 formType 是否为 INFO（读原始 4 字节）。"""
    src.seek(doff)
    return src.read(4) == b"INFO"


def _copy_chunk(src, out, ckid: bytes, doff: int, size: int) -> None:
    """流式拷贝既有 chunk（ckID + size + data + pad）。"""
    out.write(ckid)
    out.write(struct.pack("<I", size))
    src.seek(doff)
    remaining = size
    while remaining > 0:
        buf = src.read(min(_COPY_BUF, remaining))
        if not buf:
            break
        out.write(buf)
        remaining -= len(buf)
    if size % 2:
        out.write(b"\x00")


def _write_chunk(out, ckid: bytes, data: bytes) -> None:
    """写新构造 chunk（ckID + size + data + pad）。"""
    out.write(ckid)
    out.write(struct.pack("<I", len(data)))
    out.write(data)
    if len(data) % 2:
        out.write(b"\x00")


# ---------------------------------------------------------------------------
# bext 构造
# ---------------------------------------------------------------------------

def _pack_text(value, length: int, *, reject_if_too_long: bool = False) -> bytes:
    """ASCII-only 定长文本字段（null 终止 + 补齐至 length）。

    - 空值 / 含非 ASCII → 全 null（bext 为 ASCII 域，中文留空不臆造，§六-1）。
    - 正好填满 → 无 null 终止位（如 OriginationDate 的 "YYYY-MM-DD" 恰 10 字节）。
    - 超长：reject_if_too_long=True 整字段留空；否则截断至 length-1。
    """
    text = "" if value is None else str(value)
    if not text or not text.isascii():
        return b"\x00" * length
    raw = text.encode("ascii")
    if len(raw) == length:
        return raw
    if len(raw) > length:
        if reject_if_too_long:
            return b"\x00" * length
        raw = raw[: length - 1]
    return (raw + b"\x00").ljust(length, b"\x00")


def _build_bext(fields: dict, sample_rate: int, bits: int,
                channels: int) -> bytes:
    """按 3285 v2 表装配 bext（定长 602 + 变长 CodingHistory）。"""
    date_val = str(fields.get("Date") or "")
    if not _DATE_RE.match(date_val):
        date_val = ""
    parts = [
        _pack_text(fields.get("Title"), 256),                       # Description
        _pack_text(fields.get("Creator"), 32),                      # Originator
        _pack_text(fields.get("Identifier"), 32,
                   reject_if_too_long=True),                        # OriginatorReference
        _pack_text(date_val, 10),                                   # OriginationDate
        _pack_text("", 8),                                          # OriginationTime（无时刻源→留空，裁一A）
        struct.pack("<I", 0),                                       # TimeReferenceLow
        struct.pack("<I", 0),                                       # TimeReferenceHigh
        struct.pack("<H", _BEXT_VERSION),                           # Version
        b"\x00" * 64,                                               # UMID（无源，全 0）
        struct.pack("<5h", *([_LOUDNESS_UNUSED] * 5)),              # Loudness×5 = 7FFF
        b"\x00" * 180,                                              # Reserved
    ]
    fixed = b"".join(parts)
    assert len(fixed) == _BEXT_FIXED, len(fixed)
    coding = build_coding_history(sample_rate, bits, channels)
    return fixed + coding.encode("ascii")


# ---------------------------------------------------------------------------
# INFO LIST 构造
# ---------------------------------------------------------------------------

def _info_subchunk(tag: str, value: str) -> bytes:
    """INFO 子块：4 字节 ID + size + 值（null 终止 + 偶数补位）。"""
    data = value.encode("ascii") + b"\x00"
    size = len(data)                    # ckSize 不含 pad
    if size % 2:
        data += b"\x00"
    return tag.encode("ascii") + struct.pack("<I", size) + data


def _build_info_list(fields: dict) -> bytes:
    """LIST INFO：INAM/IART/ICRD/ICMT（有值且 ASCII 才写）+ ISFT 恒 AcouScope。"""
    subs = b""
    for tag, key in (("INAM", "Title"), ("IART", "Creator"),
                     ("ICRD", "Date"), ("ICMT", "Note")):
        val = fields.get(key)
        if val is not None and str(val).strip() and str(val).isascii():
            subs += _info_subchunk(tag, str(val))
    subs += _info_subchunk("ISFT", "AcouScope")       # 软件标识恒写
    return b"INFO" + subs


# ---------------------------------------------------------------------------
# iXML 构造
# ---------------------------------------------------------------------------

_TAG_INVALID = re.compile(r"[^0-9A-Za-z_\-.']")


def _xml_tag(name) -> str:
    """自定义键 → 合法 XML 元素名（本地小函数；同 M-3 _safe_tag 规则）。

    非 alnum/_/-/./' 换 `_`；首字符非法则前置 `_`。
    """
    tag = _TAG_INVALID.sub("_", str(name))
    if not tag or not re.match(r"[A-Za-z_]", tag[0]):
        tag = "_" + tag
    return tag


def _build_ixml(fields: dict, sample_rate: int, bits: int) -> bytes:
    """装配 BWFXML：UTF-8，全值不经 ASCII 限制（中文由它承载）。

    IXML_VERSION / PROJECT(Title) / NOTE(Note) / SPEED{采样率,位深} /
    ACOUSCOPE vendor 树（非空标准 12 键 + 自定义键）。偶数对齐：UTF-8 字节
    数为奇 ⇒ 末尾追加一个空格 0x20（iXML 规范逐字，取证件 §四）。
    """
    root = ET.Element("BWFXML")
    ET.SubElement(root, "IXML_VERSION").text = "1.52"
    title = str(fields.get("Title") or "").strip()
    if title:
        ET.SubElement(root, "PROJECT").text = title
    note = str(fields.get("Note") or "").strip()
    if note:
        ET.SubElement(root, "NOTE").text = note
    speed = ET.SubElement(root, "SPEED")
    ET.SubElement(speed, "FILE_SAMPLE_RATE").text = str(int(sample_rate))
    ET.SubElement(speed, "AUDIO_BIT_DEPTH").text = str(int(bits))
    vendor = ET.SubElement(root, "ACOUSCOPE")         # 空树也保留空元素
    for k, v in fields.items():
        val = str(v).strip()
        if val:
            ET.SubElement(vendor, _xml_tag(k)).text = str(v)
    body = ET.tostring(root, encoding="unicode")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + body
    raw = text.encode("utf-8")
    if len(raw) % 2:
        raw += b"\x20"
    return raw


# ---------------------------------------------------------------------------
# 读回解码
# ---------------------------------------------------------------------------

def _decode_bext(body: bytes) -> dict:
    """bext ckData → dict（文本 null 剥离；int 解值；UMID 保真 hex）。"""
    def txt(off: int, length: int) -> str:
        chunk = body[off:off + length]
        nul = chunk.find(b"\x00")
        if nul >= 0:
            chunk = chunk[:nul]
        return chunk.decode("latin-1")
    out: dict = {}
    out["Description"] = txt(0, 256)
    out["Originator"] = txt(256, 32)
    out["OriginatorReference"] = txt(288, 32)
    out["OriginationDate"] = txt(320, 10)
    out["OriginationTime"] = txt(330, 8)
    tl = struct.unpack("<I", body[338:342])[0]
    th = struct.unpack("<I", body[342:346])[0]
    out["TimeReference"] = (th << 32) | tl
    out["Version"] = struct.unpack("<H", body[346:348])[0]
    out["UMID"] = body[348:412].hex()
    loud = struct.unpack("<5h", body[412:422])
    out["LoudnessValue"] = loud[0]
    out["LoudnessRange"] = loud[1]
    out["MaxTruePeakLevel"] = loud[2]
    out["MaxMomentaryLoudness"] = loud[3]
    out["MaxShortTermLoudness"] = loud[4]
    out["CodingHistory"] = body[602:].decode("latin-1")   # 保留 CR/LF
    return out


def _decode_info(body: bytes) -> dict:
    """LIST INFO 载荷（'INFO' 之后的子块串）→ {tag: 值}。"""
    out: dict[str, str] = {}
    pos = 0
    n = len(body)
    while pos + 8 <= n:
        tag = body[pos:pos + 4].decode("ascii", errors="replace")
        size = struct.unpack("<I", body[pos + 4:pos + 8])[0]
        val = body[pos + 8:pos + 8 + size]
        nul = val.find(b"\x00")
        if nul >= 0:
            val = val[:nul]
        out[tag] = val.decode("latin-1")
        pos += 8 + size
        if size % 2:
            pos += 1
    return out
