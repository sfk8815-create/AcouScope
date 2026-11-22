# SPDX-License-Identifier: GPL-3.0-only
"""元数据与音高标注导出（T-004-2）。EXPORT_V1

无损承诺（用户强指令4）：
- JSON：PitchAnnotation 全字段 + SessionMetadata 全字段（含自定义字段）round-trip 全等。
- CSV：音高表 8 列，浮点用 repr 保证精度可逆；逗号/引号/换行由 csv 模块转义。
- XML：SessionMetadata.to_imdi() 结构 → XML；无损口径 = XML 叶节点 {路径:值}
  与 IMDI dict flatten 结果完全相等（load_session_xml 可回读校验）。
  `Keys/Key` 列表项以 `@Name` 值作叶路径末段（如 `…Keys.Key.SamplingRate`）。
"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from . import PitchAnnotation
from .metadata import (
    DAT63_SLOTS,
    FIELD_TERMS,
    GBT_SLOTS,
    IMDI_NS,
    IMDI_XSI_NS,
    MORPHOLOGY_FIELDS,
    MORPHOLOGY_NOTE,
    MORPHOLOGY_PREFIX,
    SessionMetadata,
    _CUSTOM_KEYS_PATH,
    check_morphology_fields,
    required_for_standard,
)

PITCH_FIELDS = [
    "t_ms", "f0_hz", "cents", "cent_ref",
    "confidence", "label", "session_id", "note",
]
EXPORT_FORMAT = "acouscope-pitch-export"
EXPORT_VERSION = 1
SESSION_EXPORT_FORMAT = "acouscope-session-export"

# ---------------- 导出 profile（M-3）----------------

PROFILE_CUSTOM = "custom"        # 现行为：json/csv=扁平英文字典；xml=M-2 版 IMDI 结构
PROFILE_DAT63 = "DAT63"
PROFILE_GBT = "GBT31219.4"
PROFILE_IMDI = "IMDI"            # M-4b：json/csv=IMDI 路径版 elements；xml 同 custom（IMDI 结构）

# profile → (登记标准名, 适用范围声明)
_PROFILE_META: dict[str, tuple[str, str]] = {
    PROFILE_DAT63: ("DA/T 63-2017", "档案实体元素集（表2，M1-M75；不含 M76-M96）"),
    PROFILE_GBT: ("GB/T 31219.4-2014", "表1/表2 对应元素"),
    PROFILE_IMDI: ("IMDI 3.0.22", "Session 结构（字段级映射）"),
}


def _check_profile(profile: str) -> None:
    """未知 profile 即拒（三个导出函数共用同一校验辅助）。"""
    if profile not in (PROFILE_CUSTOM, *_PROFILE_META):
        raise ValueError(f"未知 profile: {profile!r}（可用: custom / DAT63 / GBT31219.4 / IMDI）")


#: 形态学扩展的导出列键序（``morphology.<字段>[.<子字段>]``；不并入标准槽位）
def _morphology_export_fields() -> tuple[str, ...]:
    keys: list[str] = []
    for item in MORPHOLOGY_FIELDS:
        if item.kind == "annotation":
            keys.extend(f"{MORPHOLOGY_PREFIX}.{item.key}.{child}" for child in item.children)
        else:
            keys.append(f"{MORPHOLOGY_PREFIX}.{item.key}")
    return tuple(keys)


MORPHOLOGY_EXPORT_FIELDS: tuple[str, ...] = _morphology_export_fields()


def morphology_flat(session: SessionMetadata) -> dict[str, str]:
    """形态学块 → 扁平导出字段（``morphology.X``；缺值不出键，禁 0/空串回填）。"""
    block = session.get_morphology() if session is not None else {}
    out: dict[str, str] = {}
    for item in MORPHOLOGY_FIELDS:
        value = (block or {}).get(item.key)
        if value is None or value == "":
            continue
        if item.kind == "annotation":
            if not isinstance(value, dict):
                out[f"{MORPHOLOGY_PREFIX}.{item.key}"] = str(value)
                continue
            for child in item.children:
                sub = value.get(child)
                if sub is None or sub == "":
                    continue
                out[f"{MORPHOLOGY_PREFIX}.{item.key}.{child}"] = str(sub)
            continue
        out[f"{MORPHOLOGY_PREFIX}.{item.key}"] = str(value)
    return out


def _profile_elements(session: SessionMetadata, profile: str) -> list[dict]:
    """逐字段元素登记：渲染范围 = to_dict() 全部条目（标准键一律出现、空值渲染
    为空串不省）；未入表字段与自定义键以字段键作元素名，note=「标准外自定义」。
    每个 element 恒含 field/code/name/table/value/note 六键。

    IMDI profile 走 _imdi_elements（code=槽位路径、name=末段、Key 者 @Name）。
    """
    if profile == PROFILE_IMDI:
        return _imdi_elements(session)
    slots = DAT63_SLOTS if profile == PROFILE_DAT63 else GBT_SLOTS
    field_keys = {t.key for t in FIELD_TERMS}
    elements: list[dict] = []
    for field, value in session.to_dict().items():
        slot = slots.get(field)
        if slot is not None:
            if profile == PROFILE_DAT63:
                code, name, note = slot
                table = ""
            else:
                code, name, table, note = slot
        else:
            code, table = "", ""
            name = field
            note = "标准外自定义" if field in field_keys else "标准外自定义（自定义字段）"
        elements.append({
            "field": field, "code": code, "name": name, "table": table,
            "value": str(value), "note": note,
        })
    return elements


def _imdi_elements(session: SessionMetadata) -> list[dict]:
    """IMDI profile 元素登记（M-4b）：code = 该字段 std_slots["IMDI"] 路径
    （自定义键 → "Session/MDGroup/Keys/Key"）；name = 路径末段（技术四项与
    自定义键均为 "Key"）；末段为 Key 者 note = "@Name=" + 字段键（与
    to_imdi() 的 Keys/Key 列表项口径一致）。
    """
    slot_by_key = {t.key: t.std_slots.get("IMDI", "") for t in FIELD_TERMS}
    elements: list[dict] = []
    for field, value in session.to_dict().items():
        path = slot_by_key.get(field) or _CUSTOM_KEYS_PATH
        name = path.rsplit("/", 1)[-1]
        note = f"@Name={field}" if name == "Key" else ""
        elements.append({
            "field": field, "code": path, "name": name, "table": "",
            "value": str(value), "note": note,
        })
    return elements


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

def export_session_json(path, session: SessionMetadata, profile: str = PROFILE_CUSTOM) -> None:
    """导出 SessionMetadata → JSON（to_dict() 全字段扁平映射，含自定义键）。

    custom 保持现行为（扁平原 dict）；DAT63/GBT31219.4/IMDI 走 M-3 登记形状
    （format/version/profile/standard/scope/elements，element 恒六键；IMDI 侧
    code=槽位路径、name=末段、Key 者 note=@Name=字段键）。
    """
    _check_profile(profile)
    if profile == PROFILE_CUSTOM:
        payload = session.to_dict()
        morph = morphology_flat(session)
        if morph:
            # W-14-07：独立块（不并入标准字段面）
            payload[MORPHOLOGY_PREFIX] = session.get_morphology()
            payload[f"{MORPHOLOGY_PREFIX}_note"] = MORPHOLOGY_NOTE
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    standard, scope = _PROFILE_META[profile]
    data = {
        "format": SESSION_EXPORT_FORMAT,
        "version": 1,
        "profile": profile,
        "standard": standard,
        "scope": scope,
        "elements": _profile_elements(session, profile),
    }
    morph = morphology_flat(session)
    if morph:
        data[MORPHOLOGY_PREFIX] = session.get_morphology()
        data[f"{MORPHOLOGY_PREFIX}_note"] = MORPHOLOGY_NOTE
        data[f"{MORPHOLOGY_PREFIX}_check"] = check_morphology_fields(
            session.get_morphology()
        )
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def export_session_csv(path, session: SessionMetadata, profile: str = PROFILE_CUSTOM) -> None:
    """导出 SessionMetadata → CSV。

    custom 保持现宽表（表头=FIELD_TERMS key+自定义键，逐字、顺序同字典，
    缺失字段写空串，不臆造数值）；DAT63/GBT31219.4/IMDI 为长表六列
    （field,code,name,table,value,note），行序=elements 序（IMDI 侧
    code=槽位路径、name=末段、Key 者 note=@Name=字段键）。
    """
    _check_profile(profile)
    morph = morphology_flat(session)
    if profile == PROFILE_CUSTOM:
        row = session.to_dict()
        header = [t.key for t in FIELD_TERMS]
        header += [k for k in row if k not in header]
        # W-14-07：形态学列独立前缀（不并入标准字段列序）；空块时不加列
        if morph:
            header += [key for key in MORPHOLOGY_EXPORT_FIELDS if key not in header]
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerow([
                morph.get(k, "") if k.startswith(f"{MORPHOLOGY_PREFIX}.") else row.get(k, "")
                for k in header
            ])
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["field", "code", "name", "table", "value", "note"])
        for e in _profile_elements(session, profile):
            w.writerow([
                e["field"], e["code"], e["name"], e["table"], e["value"], e["note"],
            ])
        for key, value in morph.items():
            w.writerow([key, "", key.rsplit(".", 1)[-1], "", value, MORPHOLOGY_NOTE])


# ---------------- XML ----------------

def _safe_tag(key: str) -> str:
    """XML 标签安全化（IMDI 键为字母数字，正常路径不触发替换）。

    命名空间感知：`{uri}Local` 形态先拆 uri，只对 local 段安全化、uri 原样透传
    （M-6a；否则 `_safe_tag` 会把 `{http://…}Local` 整串换成 `__http___…`）。
    """
    if key.startswith("{"):
        uri, _, local = key[1:].partition("}")
        return "{" + uri + "}" + _safe_local(local)
    return _safe_local(key)


def _safe_local(key: str) -> str:
    """单段标签安全化（无命名空间前缀）。"""
    out = "".join(c if (c.isalnum() or c in "_-.") else "_" for c in key)
    if not out or not (out[0].isalpha() or out[0] == "_"):
        out = "_" + out
    return out


def _element_to_xml(parent, tag: str, value) -> None:
    """落一个元素：列表=同名重复元素；dict 中 `@` 前缀=属性、`#text`=元素文本。

    命名空间感知（M-6a）：父节点若带命名空间而 tag 无前缀，则子元素继承父 uri
    （`elementFormDefault="qualified"`〔XSD:86〕要求子元素必带命名空间）。
    """
    if isinstance(value, list):
        for item in value:
            _element_to_xml(parent, tag, item)
        return
    child = ET.SubElement(parent, _ns_tag(parent, tag))
    if isinstance(value, dict):
        text = value.get("#text")
        if text is not None:
            child.text = str(text)
        for k, v in value.items():
            if k.startswith("@"):
                child.set(k[1:], "" if v is None else str(v))
            elif k != "#text":
                _element_to_xml(child, k, v)
    else:
        child.text = "" if value is None else str(value)


def _ns_tag(parent, tag: str) -> str:
    """子元素标签：tag 已带 `{uri}` 则安全化 local 段；否则继承父节点 uri。"""
    if tag.startswith("{"):
        return _safe_tag(tag)
    ptag = parent.tag
    if isinstance(ptag, str) and ptag.startswith("{"):
        uri = ptag[1:].partition("}")[0]
        return "{" + uri + "}" + _safe_local(tag)
    return _safe_local(tag)


def export_session_xml(path, session: SessionMetadata, profile: str = PROFILE_CUSTOM) -> None:
    """导出 SessionMetadata → XML。

    custom：保持现行为（经 to_imdi(legacy=True) 的 M-2 版无命名空间 IMDI 风格
    树，输出逐字不变）；IMDI（M-6a）：产出文档级合法 `{ns}METATRANSCRIPT` 树
    （命名空间 + 五属性 + 完整 Session 骨架）；DAT63/GBT31219.4 走 M-3 profile
    根（standard/scope 登记属性；入表字段子元素=官方名/系统名带 code/table 属性，
    未入表与自定义键子元素=字段键、无属性）。
    """
    _check_profile(profile)
    morph = morphology_flat(session)
    if profile == PROFILE_CUSTOM:
        root = ET.Element("IMDI")
        for k, v in session.to_imdi_session().items():
            _element_to_xml(root, k, v)
        if morph:
            # W-14-07：独立 <morphology> 段（与 Session 平级；不并入标准槽位）
            _element_to_xml(root, MORPHOLOGY_PREFIX, _morphology_tree(session))
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        return
    if profile == PROFILE_IMDI:
        ET.register_namespace("", IMDI_NS)              # 默认命名空间（自动发 xmlns=）
        ET.register_namespace("xsi", IMDI_XSI_NS)       # xsi 前缀（schemaLocation 用）
        body = session.to_imdi()["METATRANSCRIPT"]
        # xmlns/xmlns:xsi 由 register_namespace 自动生成，不可再作字面属性；
        # xsi:schemaLocation 须转 Clark 记法 {xsi}schemaLocation，ElementTree 才会
        # 认出其属 xsi 命名空间并自动声明 xmlns:xsi。
        attrs = {}
        for k, v in body.items():
            if not k.startswith("@") or k in ("@xmlns", "@xmlns:xsi"):
                continue
            name = k[1:]
            if name == "xsi:schemaLocation":
                attrs[f"{{{IMDI_XSI_NS}}}schemaLocation"] = v
            else:
                attrs[name] = v
        children = {k: v for k, v in body.items() if not k.startswith("@")}
        root = ET.Element(f"{{{IMDI_NS}}}METATRANSCRIPT", attrs)
        for k, v in children.items():
            _element_to_xml(root, k, v)
        if morph:
            # W-14-07：项目扩展段追加在 Session 之后。**口径**：带形态学扩展的
            # IMDI XML 是「标准件＋项目扩展段」，不再承诺通过官方 3.0.22 XSD
            # 结构校验（XSD 承诺只对无扩展会话成立，见 README-W14-07.md）。
            _element_to_xml(root, MORPHOLOGY_PREFIX, _morphology_tree(session))
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        return
    standard, scope = _PROFILE_META[profile]
    slots = DAT63_SLOTS if profile == PROFILE_DAT63 else GBT_SLOTS
    root = ET.Element(
        "DA_T63" if profile == PROFILE_DAT63 else "GBT_31219.4",
        {"standard": standard, "scope": scope},
    )
    for e in _profile_elements(session, profile):
        if e["field"] in slots:
            if profile == PROFILE_DAT63:
                # 子元素名=官方名（中文），attr code=M 编号
                _element_to_xml(root, e["name"], {"@code": e["code"], "#text": e["value"]})
            else:
                # 子元素名=系统名（表1）；表2 项无系统名 → 中文名；attr table
                tag = e["code"] if e["code"] else e["name"]
                _element_to_xml(root, tag, {"@table": e["table"], "#text": e["value"]})
        else:
            _element_to_xml(root, e["field"], e["value"])
    if morph:
        # W-14-07：独立 <morphology> 段（不并入 DAT63／GBT 槽位）
        _element_to_xml(root, MORPHOLOGY_PREFIX, _morphology_tree(session))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _morphology_tree(session: SessionMetadata) -> dict:
    """形态学块 → XML 子树（``@note`` 为口径声明属性；缺值不出元素）。"""
    block = session.get_morphology()
    tree: dict = {}
    for item in MORPHOLOGY_FIELDS:
        value = (block or {}).get(item.key)
        if value is None or value == "":
            continue
        if item.kind == "annotation" and isinstance(value, dict):
            sub = {
                child: str(value[child])
                for child in item.children
                if value.get(child) not in (None, "")
            }
            if sub:
                tree[item.key] = sub
            continue
        tree[item.key] = str(value)
    tree["@note"] = MORPHOLOGY_NOTE
    return tree


def morphology_from_flat(flat) -> dict:
    """扁平回读键（``morphology.X[.Y]``）→ 形态学块（用于 XML／CSV 回读）。

    空值**不建键**（回读不臆造）；``confidence`` 回读为 ``float``（失败则留原文）。
    """
    block: dict = {}
    for key, value in dict(flat or {}).items():
        if not str(key).startswith(f"{MORPHOLOGY_PREFIX}."):
            continue
        if value is None or value == "":
            continue
        parts = str(key).split(".")
        if len(parts) == 2:
            block[parts[1]] = value
        elif len(parts) >= 3:
            entry = block.setdefault(parts[1], {})
            if not isinstance(entry, dict):
                continue
            if parts[2] == "confidence":
                try:
                    entry[parts[2]] = float(value)
                except (TypeError, ValueError):
                    entry[parts[2]] = value
            else:
                entry[parts[2]] = value
    return block


def _xml_leaves(elem, prefix: str = "") -> dict[str, str]:
    leaves: dict[str, str] = {}
    for child in elem:
        tag = child.tag
        if isinstance(tag, str) and tag.startswith("{"):   # 剥 {uri} 前缀（M-6a）
            tag = tag.partition("}")[2]
        p = f"{prefix}.{tag}" if prefix else tag
        name = child.get("Name")  # Keys/Key 列表项：@Name 值作叶路径末段
        if name is not None:
            p = f"{p}.{name}"
        if len(child):
            leaves.update(_xml_leaves(child, p))
        else:
            leaves[p] = child.text if child.text is not None else ""
    return leaves


def load_session_xml(path) -> dict[str, str]:
    """回读 XML 所有叶节点 {路径: 值}，用于无损校验。"""
    root = ET.parse(path).getroot()
    return _xml_leaves(root)


# ---------------- M-3 回读加载器 ----------------

def load_session_json(path) -> SessionMetadata:
    """回读 SessionMetadata JSON（profile 登记形状与 custom 扁平形状皆可）。

    profile ∈ (DAT63, GBT31219.4, IMDI) → 按 elements 重建 values；否则按扁平
    dict（现 export_session_json(custom) 产出）回读。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # W-14-07：形态学独立块先摘出（不混进 values）
    morph: dict = {}
    if isinstance(data, dict) and isinstance(data.get(MORPHOLOGY_PREFIX), dict):
        morph = dict(data[MORPHOLOGY_PREFIX])
        data = {
            k: v
            for k, v in data.items()
            if k
            not in (
                MORPHOLOGY_PREFIX,
                f"{MORPHOLOGY_PREFIX}_note",
                f"{MORPHOLOGY_PREFIX}_check",
            )
        }
    if isinstance(data, dict) and data.get("profile") in (
        PROFILE_DAT63, PROFILE_GBT, PROFILE_IMDI
    ):
        values = {e["field"]: str(e["value"]) for e in data["elements"]}
    else:
        values = {k: str(v) for k, v in data.items()}
    return SessionMetadata(values=values, morphology=morph)


def load_session_csv(path) -> SessionMetadata:
    """回读 SessionMetadata CSV（长表 profile 与现宽表皆可）。

    表头前四列 == [field, code, name, table] → 取 r[0], r[4] 重建 values；
    否则按现宽表（表头=FIELD_TERMS 键…）回读。
    """
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError("空 CSV")
    header, body = rows[0], rows[1:]
    if header[:4] == ["field", "code", "name", "table"]:
        flat = {r[0]: r[4] for r in body if len(r) >= 5}
    else:
        flat = dict(zip(header, body[0])) if body else {}
    # W-14-07：morphology.* 列先摘出（不混进 values）
    morph = morphology_from_flat(flat)
    values = {
        k: v for k, v in flat.items() if not str(k).startswith(f"{MORPHOLOGY_PREFIX}.")
    }
    return SessionMetadata(values=values, morphology=morph)


# ---------------- 腔格类型学导出（B3-01 / PI-P5 第 2 棒）----------------
# 函数级追加：以上 5 个既有导出/回读函数零改动。

CAVITY_TYPE_FORMAT = "acouscope-cavity-type-export"
#: 版本 2（2026-10-25）：补 ``ref_mode``——音级字段的口径必须随行登记，
#: 否则 ``absolute`` 与 ``main_tone`` 两套行无法区分（任务-20261025-主音两阶段 乙）。
CAVITY_TYPE_VERSION = 2

#: 腔格类型判定表列序（段级记录 → 导出扁平表；None 一律留空，禁回填 0）
CAVITY_TYPE_FIELDS = (
    "segment_id",
    "ref_mode",
    "start_s",
    "end_s",
    "f0_hz",
    "degree_index",
    "degree_deviation_cents",
    "head_deviation_cents",
    "tail_deviation_cents",
    "label",
)


def _cavity_type_rows(rows) -> list[dict]:
    """按 CAVITY_TYPE_FIELDS 收窄逐段记录（缺键 ⇒ None，未知键丢弃）。

    ``rows`` 可为 Mapping 或对象（逐键取值，缺省 None）。
    """
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            out.append({key: row.get(key) for key in CAVITY_TYPE_FIELDS})
        else:
            out.append({key: getattr(row, key, None) for key in CAVITY_TYPE_FIELDS})
    return out


def export_cavity_types_json(path, rows, tau_cents=None) -> None:
    """导出腔格类型判定表 → JSON（口径仿 export_pitches_json：format/version + 全字段）。

    ``rows`` = ``cavity_type.segment_features`` / ``cavity_type_report()["records"]``
    同形逐段记录；``tau_cents`` 原样登记（None = 待 P2 标定，禁自设数值）。
    """
    data = {
        "format": CAVITY_TYPE_FORMAT,
        "version": CAVITY_TYPE_VERSION,
        "tau_cents": tau_cents,
        "fields": list(CAVITY_TYPE_FIELDS),
        "rows": _cavity_type_rows(rows),
    }
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def export_cavity_types_csv(path, rows) -> None:
    """导出腔格类型判定表 → CSV（表头 = CAVITY_TYPE_FIELDS，列序逐字）。

    浮点用 ``repr`` 保证精度可逆；None 写空串（禁以 0 冒充缺值）。
    """
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(CAVITY_TYPE_FIELDS))
        for row in _cavity_type_rows(rows):
            w.writerow([
                "" if value is None else (repr(value) if isinstance(value, float) else value)
                for value in row.values()
            ])


# ---------------- 元数据字段表（任务-20261025-平台图导出 丙）----------------
# 函数级追加：以上既有导出/回读零改动。

METADATA_TABLE_FORMAT = "acouscope-metadata-field-table"
METADATA_TABLE_VERSION = 1

#: 四标准槽位（三个外部标准 + 现行为 custom；与 inspector_panel 的 `_standard` 四码一致）
PROFILE_SLOTS = (PROFILE_DAT63, PROFILE_GBT, PROFILE_IMDI, PROFILE_CUSTOM)

FIELD_TABLE_FIELDS = (
    "profile",
    "standard",
    "scope",
    "field",
    "code",
    "name",
    "table",
    "required",
    "implemented",
    "note",
)


def _profile_standard(profile: str) -> tuple[str, str]:
    """profile → (标准名, 适用范围)；custom 走现行为说明。"""
    if profile in _PROFILE_META:
        return _PROFILE_META[profile]
    return ("自定义（现行为）", "扁平英文字典／IMDI 结构，无外部槽位")


def _probe_session() -> SessionMetadata:
    """探针会话：全部标准键填占位值（机检用；值不参与论文，不臆造真实著录）。"""
    session = SessionMetadata()
    for term in FIELD_TERMS:
        session.set(term.key, f"<{term.key}>")
    return session


def profile_field_table(profiles=None) -> list[dict]:
    """平台元数据字段表（论文字段表的机检基准）。

    每个 profile × 每个渲染字段一行：槽位路径（``code``）、标准名、必填
    （``required``，取自 :func:`required_for_standard`）、是否落到导出结构
    （``implemented``）。字段表由**导出层自身**生成（复用 ``_profile_elements``），
    不是另抄一份映射 ⇒ 表与导出不会分叉；一致性用
    :func:`check_profile_field_table` 机检。
    """
    slots = tuple(profiles) if profiles else PROFILE_SLOTS
    table: list[dict] = []
    probe = _probe_session()
    for profile in slots:
        _check_profile(profile)
        standard, scope = _profile_standard(profile)
        required = required_for_standard(profile)
        if profile == PROFILE_CUSTOM:
            elements = [
                {"field": key, "code": "", "name": key, "table": "", "note": "扁平导出（无标准槽位）"}
                for key in probe.to_dict()
            ]
        else:
            elements = _profile_elements(probe, profile)
        for element in elements:
            table.append(
                {
                    "profile": profile,
                    "standard": standard,
                    "scope": scope,
                    "field": element["field"],
                    "code": element["code"],
                    "name": element["name"],
                    "table": element["table"],
                    "required": bool(element["field"] in required),
                    "implemented": bool(element["code"]) or profile == PROFILE_CUSTOM,
                    "note": element["note"],
                }
            )
    return table


def check_profile_field_table(table=None) -> list[str]:
    """机检字段表与运行时行为是否一致；返回问题清单（空 = 通过）。

    三项检查：
    1. 每个 profile 覆盖全部标准字段键（漏字段即问题）；
    2. ``required`` 列与该标准下 ``SessionMetadata.validate(standard)`` 的缺失集一致
       （探针全空 ⇒ 缺失集即必填集）；
    3. 非 custom 档中 ``implemented`` 为真的行必须有非空槽位路径。
    """
    rows = list(table) if table is not None else profile_field_table()
    problems: list[str] = []
    field_keys = [term.key for term in FIELD_TERMS]
    for profile in PROFILE_SLOTS:
        sub = [r for r in rows if r["profile"] == profile]
        if not sub:
            problems.append(f"{profile}: 字段表为空")
            continue
        covered = {r["field"] for r in sub}
        missing = [key for key in field_keys if key not in covered]
        if missing:
            problems.append(f"{profile}: 缺字段 {missing}")
        empty = SessionMetadata(values={key: "" for key in field_keys})
        runtime_required = set(empty.validate(standard=profile))
        table_required = {r["field"] for r in sub if r["required"]}
        if table_required != runtime_required:
            problems.append(
                f"{profile}: 必填集不一致 表={sorted(table_required)} 运行时={sorted(runtime_required)}"
            )
        if profile != PROFILE_CUSTOM:
            hollow = [r["field"] for r in sub if r["implemented"] and not r["code"]]
            if hollow:
                problems.append(f"{profile}: implemented 但无槽位路径 {hollow}")
    return problems


def export_profile_field_table_json(path, profiles=None) -> None:
    rows = profile_field_table(profiles)
    data = {
        "format": METADATA_TABLE_FORMAT,
        "version": METADATA_TABLE_VERSION,
        "profiles": list(profiles) if profiles else list(PROFILE_SLOTS),
        "fields": list(FIELD_TABLE_FIELDS),
        "rows": rows,
        "check": check_profile_field_table(rows),
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def export_profile_field_table_csv(path, profiles=None) -> None:
    rows = profile_field_table(profiles)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(FIELD_TABLE_FIELDS))
        w.writeheader()
        for row in rows:
            w.writerow({key: (int(row[key]) if isinstance(row[key], bool) else row[key]) for key in FIELD_TABLE_FIELDS})
