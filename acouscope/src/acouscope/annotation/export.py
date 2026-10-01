# SPDX-License-Identifier: GPL-3.0-only
"""元数据与音高标注导出（T-004-2）。EXPORT_V1

无损承诺（用户强指令4）：
- JSON：PitchAnnotation 全字段 + SessionMetadata 全字段（含自定义字段）round-trip 全等。
- CSV：音高表 8 列，浮点用 repr 保证精度可逆；逗号/引号/换行由 csv 模块转义。
- XML：SessionMetadata.to_imdi() 结构 → XML；无损口径 = XML 叶节点 {路径:值}
  与 IMDI dict flatten 结果完全相等（load_session_xml 可回读校验）。
"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from . import PitchAnnotation
from .metadata import FIELD_TERMS, SessionMetadata

PITCH_FIELDS = [
    "t_ms", "f0_hz", "cents", "cent_ref",
    "confidence", "label", "session_id", "note",
]
EXPORT_FORMAT = "acouscope-pitch-export"
EXPORT_VERSION = 1


# ---------------- JSON ----------------

def export_pitches_json(
    path, pitches: list[PitchAnnotation],
    session: SessionMetadata | None = None,
) -> None:
    """导出 JSON：session 元数据 + 音高标注列表（全字段）。"""
    data = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "session": dict(session.values) if session is not None else {},
        "pitches": [
            {
                "t_ms": int(p.t_ms),
                "f0_hz": float(p.f0_hz),
                "cents": float(p.cents),
                "cent_ref": float(p.cent_ref),
                "confidence": float(p.confidence),
                "label": p.label,
                "session_id": p.session_id,
                "note": p.note,
            }
            for p in pitches
        ],
    }
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_pitches_json(path):
    """回读 JSON → (SessionMetadata, list[PitchAnnotation])，与导出前全等。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != EXPORT_FORMAT:
        raise ValueError(f"非 acouscope 导出格式: {data.get('format')!r}")
    session = SessionMetadata(
        values={k: str(v) for k, v in data.get("session", {}).items()}
    )
    pitches = [
        PitchAnnotation(**{k: item[k] for k in PITCH_FIELDS})
        for item in data["pitches"]
    ]
    return session, pitches


# ---------------- CSV ----------------

def export_pitches_csv(path, pitches: list[PitchAnnotation]) -> None:
    """导出音高表 CSV（8 列，PITCH_FIELDS 顺序）。"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(PITCH_FIELDS)
        for p in pitches:
            w.writerow([
                repr(int(p.t_ms)), repr(float(p.f0_hz)), repr(float(p.cents)),
                repr(float(p.cent_ref)), repr(float(p.confidence)),
                p.label, p.session_id, p.note,
            ])


def load_pitches_csv(path) -> list[PitchAnnotation]:
    """回读音高表 CSV（表头不符即拒绝）。"""
    rows: list[PitchAnnotation] = []
    with open(path, encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        if header != PITCH_FIELDS:
            raise ValueError(f"CSV 表头不符: {header}")
        for row in r:
            rows.append(PitchAnnotation(
                t_ms=int(row[0]), f0_hz=float(row[1]), cents=float(row[2]),
                cent_ref=float(row[3]), confidence=float(row[4]),
                label=row[5], session_id=row[6], note=row[7],
            ))
    return rows


# ---------------- SessionMetadata 单体导出（T-1035b）----------------

def export_session_json(path, session: SessionMetadata) -> None:
    """导出 SessionMetadata → JSON（to_dict() 全字段扁平映射，含自定义键）。"""
    Path(path).write_text(
        json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def export_session_csv(path, session: SessionMetadata) -> None:
    """导出 SessionMetadata → 单行宽表 CSV。

    表头基准 = FIELD_TERMS 的 key（逐字、顺序同字典），其后追加未入字典的
    自定义键（按 values 插入序，稳定）；缺失字段写空串，不臆造数值。
    """
    row = session.to_dict()
    header = [t.key for t in FIELD_TERMS]
    header += [k for k in row if k not in header]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerow([row.get(k, "") for k in header])


# ---------------- XML ----------------

def _safe_tag(key: str) -> str:
    """XML 标签安全化（IMDI 键为字母数字，正常路径不触发替换）。"""
    out = "".join(c if (c.isalnum() or c in "_-.") else "_" for c in key)
    if not out or not (out[0].isalpha() or out[0] == "_"):
        out = "_" + out
    return out


def _dict_to_xml(parent, obj: dict) -> None:
    for k, v in obj.items():
        child = ET.SubElement(parent, _safe_tag(k))
        if isinstance(v, dict):
            _dict_to_xml(child, v)
        else:
            child.text = "" if v is None else str(v)


def export_session_xml(path, session: SessionMetadata) -> None:
    """导出 SessionMetadata → XML（经 to_imdi() 标准槽位结构）。"""
    root = ET.Element("IMDI")
    _dict_to_xml(root, session.to_imdi()["IMDI"])
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _xml_leaves(elem, prefix: str = "") -> dict[str, str]:
    leaves: dict[str, str] = {}
    for child in elem:
        p = f"{prefix}.{child.tag}" if prefix else child.tag
        if len(child):
            leaves.update(_xml_leaves(child, p))
        else:
            leaves[p] = child.text if child.text is not None else ""
    return leaves


def load_session_xml(path) -> dict[str, str]:
    """回读 XML 所有叶节点 {路径: 值}，用于无损校验。"""
    root = ET.parse(path).getroot()
    return _xml_leaves(root)
