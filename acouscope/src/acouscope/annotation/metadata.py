# SPDX-License-Identifier: GPL-3.0-only
"""田野元数据模型（T-004-1；M-2 四标准槽位重构）。FIELD_PITCH_V1

标准依据（文档级事实；全量对照见 字段对照表 `METADATA_standards_mapping.md`
§三 M-1 版矩阵；IMDI 行位 = 仓内 `02_References/IMDI_3.0.22_schema.xsd` 行号）：

- IASA-TC 04《数字音频对象生产与保存指南》第二版 §7.4 Basic Metadata：
  五基本元素 = 唯一标识符 / 说明 / 技术参数 / 编码历史 / 进程错误；本项目参照其收录思路。
- IMDI 3.0.22（官方已由 CLARIN CMDI / ISO 24648:2012 承接）：Session 结构为
  `Session{Name〔771〕, Title〔772〕, Date〔773〕, …, MDGroup{Location, Project,
  Keys〔365〕, Content, Actors}, Resources{MediaFile{Format〔863〕, Keys{Key〔886〕}}}}`。
  `Identifier` 挂 `Session/Name`（官方语义 = 短名/唯一标识）；无原生元素的技术参数
  挂 `…/MediaFile/Keys/Key`（`@Name` 区分）；非字典自定义键挂
  `Session/MDGroup/Keys/Key`（XSD:365 注释即「收纳本层其他元素未覆盖信息」）。
  文档级脚手架（METATRANSCRIPT 根、必填属性、Location 必填子元素等）随 M-6 校验器落地。
- DA/T 63-2017：M1-M96；本字典引用档案实体层 M 编号（M5/M6/M7/M8/M14/M17/M19/
  M20/M48/M49/M64/M65/M66）；M76-M96 三业务实体本轮不做（2026-10-12 约定 2A）。
- GB/T 31219.4-2014：表1 17 项（§7.1.2「应包括，但不限于」）/ 表2 4 项（§7.3.2）。
- 国内非遗音像档案著录核心要素映射：项目名称/传承人(表演者)/时间/地区/类别（to_heritage）。

to_imdi() 承诺口径（10-14 M-7 收口；schema 闸 10-13 已绿，降调措辞「IMDI 风格自定义映射」废止）：
标准槽位放标准字段（逐条对 XSD 实位），自定义键进 Session/MDGroup/Keys/Key。
表述纪律：对外可写「输出为 METATRANSCRIPT 文档级结构，过官方 3.0.22 XSD 结构校验」；
仍禁「符合/覆盖标准」裸断言——Schematron 闭集词表与标准全文一致性未校；改文案须过五面闸 scripts/check_claims.py。

必填集随标准切换（M-4b；STANDARD_REQUIRED 四码表 + required_for_standard() 查表，
未知码回落 REQUIRED_KEYS；check_format() 仅 Date + Duration 两条：Date 两形（日期 或
日期+时间，按 M14 原文「件级应含日期与时间」放宽），Duration = M17 hh:mm:ss（小时位
两位以上，容纳 24:00:00 进位形；10-13 M-4b2 解禁，四出口统一由 fmt_hms 产出））：
- DA/T 63：机读拦盘 6 键 = Identifier/Title/Creator/Date/Format/Duration（需用户输入
  的六项；Location 无对应码、GenreContext 的 M19=O/M20=C）；DA/T 另有 M4/M27/M46/M47
  四项名义必选，由本软件自动/预设供给（M-8a；M46/M47 从 AudioInfo 现读、M4/M27 取
  原文缺省档），不参与拦盘（四项由软件供给永不缺，扩拦盘只会把 M-4b 拦盘面搞乱）；
- GB/T 31219.4 / IMDI / custom：空集（GB/T 表1 无 M/O/C 记法〔§7.1.2「应包括，但不
  限于」〕/ IMDI schema 不要求字段有值〔实测空元素 valid=True〕/ 无外部约束）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class FieldTerm:
    """元数据字段项（四标准槽位对照，M-2）。"""

    namespace: str          # 本软件初挂命名空间：IASA | IMDI | TECH | DAT63（判定见对照表 §3.1；DAT63=档案属性类，非 IASA/IMDI/TECH）
    key: str                # 英文键（导出 CSV 表头用）
    label_zh: str           # 中文名
    required: bool = False
    std_slots: dict = field(default_factory=dict)  # 标准→官方元素/条款（键：DAT63|GBT31219.4|IMDI|IASA）
    constraint: str = ""    # DA/T 63 约束（M 编号 + M/O/C + R/NR）
    capture: str = ""       # 捕获方式（自动提取 | 半自动 | 手工）
    value_domain: str = ""  # 值域（DA/T 原文或 IMDI schema 约束）


# 字段字典（M-2：12 字段 × 四标准；判定：Location / GenreContext / ActorRole 为「标准外自定义」）
FIELD_TERMS: list[FieldTerm] = [
    FieldTerm(
        "IASA", "Identifier", "标识符", True,
        std_slots={
            "DAT63": "M5 唯一标识符（O,NR；综合档案馆使用时必选）〔§5.5〕；M6 档号（M,NR）〔§5.6〕",
            "GBT31219.4": "infoResourceIdentifier 信息资源标识符〔表1 §7.1.2〕",
            "IMDI": "Session/Name",  # 〔XSD:771〕短名/唯一标识
            "IASA": "§7.4.1.1.1 唯一标识符",
        },
        constraint="M5 O,NR；M6 M,NR",
        capture="自动（按构成规则生成，可校正）",
    ),
    FieldTerm(
        "IASA", "Title", "题名", True,
        std_slots={
            "DAT63": "M7 题名（M,NR；手工）〔§5.7〕",
            "GBT31219.4": "表2 题名（音频数据文件对应名称）〔§7.3.2〕",
            "IMDI": "Session/Title",  # 〔XSD:772〕
            "IASA": "§7.4.1.1.2 说明",
        },
        constraint="M7 M,NR",
        capture="手工",
    ),
    FieldTerm(
        "IMDI", "Creator", "创作者/表演者(传承人)", True,
        std_slots={
            "DAT63": "M8 责任者（M,NR；手工或从导入数据自动捕获）〔§5.8〕",
            "GBT31219.4": "agentName 代理名称〔表1 §7.1.2〕（近似）",
            "IMDI": "Session/MDGroup/Actors/Actor/FullName",  # 〔XSD:515〕
            "IASA": "—（§7.4.1.1.2 说明可涵盖）",
        },
        constraint="M8 M,NR",
        capture="手工",
    ),
    FieldTerm(
        "IASA", "Date", "日期(采集日期)", True,
        std_slots={
            "DAT63": "M14 摄录时间（M,NR；自动提取自比特流；GB/T 7408-2005）〔§5.13.1〕",
            "GBT31219.4": "actionDateTime 操作日期时间〔表1 §7.1.2〕；表2 日期（数字化日期 YYYY-MM-DD）〔§7.3.2〕",
            "IMDI": "Session/Date",  # 〔XSD:773〕简单串，区间用 /
            "IASA": "§7.4.1.2（日期记 BWF 标题）",
        },
        constraint="M14 M,NR",
        capture="自动（文件时间戳，可校正）",
        value_domain="YYYY-MM-DD；IMDI 简单串（区间 /；可 Unknown / Unspecified）",
    ),
    FieldTerm(
        "IMDI", "Location", "地理位置", True,
        std_slots={
            "DAT63": "无对应",
            "GBT31219.4": "无对应",
            "IMDI": "Session/MDGroup/Location/Address",  # 〔XSD:355→199〕
            "IASA": "—（§7.4.1.1.2 说明可涵盖）",
        },
        capture="手工",
        value_domain="IMDI Location 子元素 Continent〔184〕/Country〔189〕必填受控；现填 Address，拆栏与未知值脚手架随 M-6",
    ),
    FieldTerm(
        "IMDI", "GenreContext", "文化语境/流派", True,
        std_slots={
            "DAT63": "M19 主题（O,R）/ M20 内容描述（C）（近似，非等同）〔表2〕",
            "GBT31219.4": "无对应",
            "IMDI": "Session/MDGroup/Content/Genre",  # 〔XSD:388〕
            "IASA": "—（§7.4.1.1.2 说明可涵盖）",
        },
        constraint="M19 O,R；M20 C",
        capture="手工",
        value_domain="IMDI Genre=Vocabulary_Type〔XSD:1667〕受控（词表未取）",
    ),
    FieldTerm(
        "IMDI", "ActorRole", "表演者角色", False,
        std_slots={
            "DAT63": "无对应（M9 摄录者≠表演者角色）",
            "GBT31219.4": "无对应",
            "IMDI": "Session/MDGroup/Actors/Actor/Role",  # 〔XSD:505〕
            "IASA": "—",
        },
        capture="手工",
        value_domain="IMDI Vocabulary_Type 受控（词表未取）",
    ),
    FieldTerm(
        "TECH", "SamplingRate", "采样率(Hz)", False,
        std_slots={
            "DAT63": "M64 音频采样率（O,NR）〔§5.28.3〕",
            "GBT31219.4": "samplingFrequency 采样频率〔表1 §7.1.2〕",
            "IMDI": "Session/Resources/MediaFile/Keys/Key",  # 无原生元素〔XSD:886〕
            "IASA": "§7.4.1.1.3 技术参数（逐字列采样率）",
        },
        constraint="M64 O,NR",
        capture="自动提取",
        value_domain="22.05/32/44.1/48/96/192kHz/[其他]",
    ),
    FieldTerm(
        "TECH", "BitDepth", "位深(bit)", False,
        std_slots={
            "DAT63": "M65 音频量化位数（O,NR）〔§5.28.4〕",
            "GBT31219.4": "quantizationPrecision 量化精度〔表1 §7.1.2〕",
            "IMDI": "Session/Resources/MediaFile/Keys/Key",
            "IASA": "§7.4.1.1.3（类目涵盖）",
        },
        constraint="M65 O,NR",
        capture="自动提取",
        value_domain="8/16/24bit/[其他]",
    ),
    FieldTerm(
        "TECH", "Format", "格式", False,
        std_slots={
            "DAT63": "M48 格式信息（M,R）〔§5.26〕→ M49 格式名称（C,NR）〔§5.26.1〕",
            "GBT31219.4": "format 格式〔表1 §7.1.2〕",
            "IMDI": "Session/Resources/MediaFile/Format",  # 〔XSD:863〕Minor part of mime-type
            "IASA": "§7.4.1.1.3（逐字列格式）",
        },
        constraint="M48 M,R；M49 C,NR",
        capture="自动提取",
        value_domain="MP3/WAV/WMA/MID/AAC/OGA/APE/FLAC/MPC/[其他]；IMDI Format 写子类（如 wav）",
    ),
    FieldTerm(
        "TECH", "Channels", "声道数", False,
        std_slots={
            "DAT63": "M66 声道（O,NR）〔§5.28.5〕",
            "GBT31219.4": "numberOfChannels 通道数〔表1 §7.1.2〕",
            "IMDI": "Session/Resources/MediaFile/Keys/Key",
            "IASA": "§7.4.1.1.3（类目涵盖）",
        },
        constraint="M66 O,NR",
        capture="自动提取",
        value_domain="1/2/4/6/8/[其他]",
    ),
    FieldTerm(
        "TECH", "Duration", "时长", False,
        std_slots={
            "DAT63": "M17 时间长度（M,NR；hh:mm:ss）〔§5.13.4〕",
            "GBT31219.4": "无直接对应（表1 有 bitRate、无时长）",
            "IMDI": "Session/Resources/MediaFile/Keys/Key",  # TimePosition 语义=资源内位置，非时长
            "IASA": "§7.4.1.1.3（类目涵盖）",
        },
        constraint="M17 M,NR",
        capture="自动提取",
        value_domain="hh:mm:ss（DA/T）",
    ),
    FieldTerm(
        "TECH", "FileName", "文件名", False,
        std_slots={
            "DAT63": "M46 计算机文件名（M,NR；自动；「由文件名与扩展名两部分组成」）〔p45-46、p88〕",
            "IMDI": "Session/MDGroup/Keys/Key",  # Name 无 MediaFile_Type 位（10-14 XSD 实查，见侦察件 §八-1）
        },
        constraint="M46 M,NR",
        capture="自动（Path(filepath).name，恰为名.扩展名；不落绝对路径，正合原文「取相对地址」注释）",
        value_domain="名.扩展名",
    ),
    FieldTerm(
        "TECH", "FileSize", "文件大小", False,
        std_slots={
            "DAT63": "M47 计算机文件大小（M,R；数值型；自动）〔p46、p47、p88〕",
            "IMDI": "Session/Resources/MediaFile/Size",  # 〔XSD:868〕
        },
        constraint="M47 M,R",
        capture="自动提取（AudioInfo.file_size，字节数）",
        value_domain="字节数（数值型，原文可重复〔p47 历次格式转换与 M48/音频参数一一对应〕；本软件出当前单值）",
    ),
    FieldTerm(
        "DAT63", "AggregationLevel", "聚合层次", False,
        std_slots={
            "DAT63": "M4 聚合层次（M,NR；自动；值域=卷、件）〔p13、p87〕",
            "IMDI": "Session/MDGroup/Keys/Key",  # 无原生位 ⇒ 落 Keys
        },
        constraint="M4 M,NR",
        capture="预设（原文「根据预设值自动捕获」，著录说明示例即「件」；导出单位=单个音频文件）",
        value_domain="卷、件（本软件预设 = 件）",
    ),
    FieldTerm(
        "DAT63", "RetentionPeriod", "保管期限", False,
        std_slots={
            "DAT63": "M27 保管期限（M,NR；半自动；值域=永久、〔30〕年、〔10〕年、[其他]）〔p31-32、p88〕",
            "IMDI": "Session/MDGroup/Keys/Key",  # 无原生位 ⇒ 落 Keys
        },
        constraint="M27 M,NR",
        capture="预设（件级示例 p92/p93/p99/p101/p103 全填「永久」；半自动字典择值，GUI 改档随 M-8b）",
        value_domain="永久、〔30〕年、〔10〕年、[其他]（[其他]=按需求自定义；同 M-4b 逻辑不设值域校验）",
    ),
]

# ---------------------------------------------------------------------------
# 中国音乐形态学扩展字段（W-14-07 / 缺口 G-07）
# ---------------------------------------------------------------------------
# **独立命名空间**：不加入 FIELD_TERMS（仍 16 项），不落 DAT63/GBT31219.4/IMDI
# 任何标准槽位；导出为独立 `morphology` 块/列/段。表述纪律同全文件：这些是
# **项目扩展词汇**，不属四标准核心元素，字段语义须学者审定；平台只校验结构与
# 取值，不认证范畴。


@dataclass(frozen=True)
class MorphologyField:
    """形态学扩展字段项（``kind="text"`` 或 ``kind="annotation"``）。"""

    key: str
    label_zh: str
    kind: str = "text"
    children: tuple[str, ...] = ()
    value_domain: str = ""


#: ``CavityCoreAnnotation`` 的四个子字段（缺 annotator/method/template 即报错）
MORPHOLOGY_ANNOTATION_CHILDREN: tuple[str, ...] = (
    "annotator",
    "method",
    "template",
    "confidence",
)

#: 子字段中文名（UI／导出列名用）
MORPHOLOGY_CHILD_LABELS: dict[str, str] = {
    "annotator": "标注者",
    "method": "方法",
    "template": "参照模板",
    "confidence": "置信度",
}

#: 腔格取值（本单先按平台三型＋未分类四值收口；扩表须另裁并在本常量登记）
MORPHOLOGY_CAVITY_TYPES: tuple[str, ...] = ("上趋", "下趋", "平直", "未分类")

#: 形态学扩展字段（4 主字段；``CavityCoreAnnotation`` 带 4 子字段）
MORPHOLOGY_FIELDS: tuple[MorphologyField, ...] = (
    MorphologyField("CavityPosition", "腔位", "text",
                    value_domain="非空字符串；缺省＝未标注（不臆造）"),
    MorphologyField("CavityType", "腔格", "text",
                    value_domain="上趋／下趋／平直／未分类（本单四值）"),
    MorphologyField("NotePosition", "乐位", "text",
                    value_domain="非空字符串；缺省＝未标注"),
    MorphologyField(
        "CavityCoreAnnotation",
        "腔核标注",
        "annotation",
        children=MORPHOLOGY_ANNOTATION_CHILDREN,
        value_domain=(
            "dict：annotator／method／template 必填非空；confidence 若给须在 [0,1]"
        ),
    ),
)

#: 主字段键集合（校验与 UI 遍历用）
MORPHOLOGY_KEYS: tuple[str, ...] = tuple(f.key for f in MORPHOLOGY_FIELDS)

#: 扩展块的口径声明（随件与 README 同文）
MORPHOLOGY_NOTE = (
    "项目扩展词汇（中国音乐形态学：腔位／腔格／乐位／腔核标注），不属 DAT63／"
    "GBT 31219.4／IMDI 核心元素；字段语义须学者审定；平台只校验结构与取值，"
    "不认证范畴，不作「符合／覆盖某标准」的表述。"
)

#: 导出列前缀（CSV／XML 用；不并入标准槽位）
MORPHOLOGY_PREFIX = "morphology"

#: 会话 metadata 里存形态学块的键（值为 JSON 文本；``SessionMetadata.set`` 特例路由）
MORPHOLOGY_STORAGE_KEY = "_morphology"


def _load_morphology_text(value) -> dict:
    """``_morphology`` 值（JSON 文本／dict／None）→ dict（坏文本 ⇒ 空块，不崩）。"""
    import json

    if value is None or value == "":
        return {}
    if isinstance(value, Mapping):
        return normalize_morphology(value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return normalize_morphology(parsed) if isinstance(parsed, Mapping) else {}


def morphology_to_text(values: Mapping[str, Any] | None) -> str:
    """形态学块 → metadata 存储文本（JSON；空块 ⇒ 空串）。"""
    import json

    block = normalize_morphology(values)
    return json.dumps(block, ensure_ascii=False, sort_keys=True) if block else ""


def morphology_field_table() -> list[dict]:
    """形态学字段字典表（字段名／中文名／类型／子字段／值域），供导出与 README 对拍。"""
    rows: list[dict] = []
    for item in MORPHOLOGY_FIELDS:
        rows.append(
            {
                "key": item.key,
                "label_zh": item.label_zh,
                "kind": item.kind,
                "children": list(item.children),
                "value_domain": item.value_domain,
            }
        )
        for child in item.children:
            rows.append(
                {
                    "key": f"{item.key}.{child}",
                    "label_zh": MORPHOLOGY_CHILD_LABELS.get(child, child),
                    "kind": "subfield",
                    "children": [],
                    "value_domain": (
                        "number ∈ [0,1]"
                        if child == "confidence"
                        else "非空字符串（必填）"
                    ),
                }
            )
    return rows


def check_morphology_fields(values: Mapping[str, Any] | None) -> list[str]:
    """逐字段校验形态学扩展块；返回问题清单（空列表＝通过）。

    校验面（设计约定 W-14-07 最小实现面 2）：

    1. 未知键报错（防把标准字段混进扩展块）；
    2. ``kind="text"`` 字段：值须为字符串；空串／``None`` ＝ **未标注**（不报错，
       与 ``FIELD_TERMS`` 的空值规则一致：缺省不臆造）；
    3. ``CavityType`` 的取值须在 :data:`MORPHOLOGY_CAVITY_TYPES` 内（枚举）；
    4. ``CavityCoreAnnotation``：须为 Mapping；``annotator``／``method``／
       ``template`` **必填非空**；``confidence`` 若给须为数且 0 ≤ c ≤ 1；
    5. 空值不臆造：未给的字段不报问题，也不补默认值。
    """
    problems: list[str] = []
    if values is None:
        return problems
    if not isinstance(values, Mapping):
        return [f"morphology 须为映射，得到 {type(values).__name__}"]
    for key in values:
        if key not in MORPHOLOGY_KEYS:
            problems.append(f"未知形态学字段：{key!r}（不得混入标准字段）")
    for item in MORPHOLOGY_FIELDS:
        if item.key not in values:
            continue
        raw = values.get(item.key)
        if item.kind == "annotation":
            if raw is None or raw == "":
                continue
            if not isinstance(raw, Mapping):
                problems.append(f"{item.key}: 须为映射，得到 {type(raw).__name__}")
                continue
            for child in ("annotator", "method", "template"):
                value = raw.get(child)
                if value is None or not str(value).strip():
                    problems.append(f"{item.key}.{child}: 必填且不得为空")
            for unknown in raw:
                if unknown not in item.children:
                    problems.append(f"{item.key}.{unknown}: 未知子字段")
            confidence = raw.get("confidence")
            if confidence is not None and confidence != "":
                try:
                    number = float(confidence)
                except (TypeError, ValueError):
                    problems.append(
                        f"{item.key}.confidence: 须为数值，得到 {confidence!r}"
                    )
                else:
                    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                        problems.append(
                            f"{item.key}.confidence: 须在 [0,1]，得到 {number!r}"
                        )
            continue
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str):
            problems.append(f"{item.key}: 须为字符串，得到 {type(raw).__name__}")
            continue
        if item.key == "CavityType" and raw not in MORPHOLOGY_CAVITY_TYPES:
            problems.append(
                f"{item.key}: 取值须在 {list(MORPHOLOGY_CAVITY_TYPES)} 内，得到 {raw!r}"
            )
    return problems


def normalize_morphology(values: Mapping[str, Any] | None) -> dict:
    """形态学块规范化（校验前用）：去空值、去空白、confidence 转 float。

    **不补默认值**（缺省即未标注）；空串视为未填并从块中移除。
    """
    out: dict = {}
    if not isinstance(values, Mapping):
        return out
    for item in MORPHOLOGY_FIELDS:
        raw = values.get(item.key)
        if raw is None or raw == "":
            continue
        if item.kind == "annotation":
            if not isinstance(raw, Mapping):
                out[item.key] = raw
                continue
            child_out: dict = {}
            for child in item.children:
                value = raw.get(child)
                if value is None or value == "":
                    continue
                if child == "confidence":
                    try:
                        child_out[child] = float(value)
                    except (TypeError, ValueError):
                        child_out[child] = value
                else:
                    child_out[child] = str(value)
            if child_out:
                out[item.key] = child_out
            continue
        out[item.key] = str(raw)
    return out


REQUIRED_KEYS = [t.key for t in FIELD_TERMS if t.required]

# 必填集随标准切换（M-4b；键 = _META/导出 profile 四码）。DA/T 机读拦盘 6 键 = 需用户
# 输入的六项（M6/M7/M8/M14/M17/M48）；Location 在 DA/T 无对应码、GenreContext 的
# M19=O、M20=C 故均不入围。DA/T 另有 M4/M27/M46/M47 四项名义必选，由本软件自动/预设
# 供给（M-8a；M46/M47 现读、M4/M27 原文缺省），不参与拦盘。其余三家空集各带原文依据——
STANDARD_REQUIRED: dict[str, frozenset[str]] = {
    "DAT63": frozenset({
        "Identifier", "Title", "Creator", "Date", "Format", "Duration",
    }),
    "GBT31219.4": frozenset(),  # GB/T 表1 无 M/O/C 记法（§7.1.2「应包括，但不限于」）
    "IMDI": frozenset(),        # IMDI schema 不要求字段有值（实测空元素 valid=True）
    "custom": frozenset(),      # 自定义：无外部约束
}


def required_for_standard(code: str) -> frozenset[str]:
    """按标准码取必填集（STANDARD_REQUIRED 查表）。

    未知码 → 回落 REQUIRED_KEYS（不抛、不空——未知≠无约束，护住既有语义）。
    """
    return STANDARD_REQUIRED.get(code, frozenset(REQUIRED_KEYS))


# check_format 的 Date 规则来源（M-4b 补令 §〇-6-3：DA/T M14 原文「件级应含日期
# 与时间」（mapping :68 逐字，引 GB/T 7408），自家预填 inspector_panel.py:115 =
# %Y-%m-%d %H:%M）⇒ 接受两形之一：结构正则定两形 + 历法实证（真日期；`2026-13-45`
# 之类月/日越界须报），两者皆不合才出 format_warn。
# ★ Duration 一条由 M-4b2（10-13）解禁：DA/T M17 原文记法 = hh:mm:ss（小时位两位
# 以上，容纳 〇-2 的 24:00:00 进位形）；值统一由 fmt_hms 产出，导出侧不再落秒值。
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
DURATION_RE = re.compile(r"^\d{2,}:[0-5]\d:[0-5]\d$")
_DATE_TIME_FORMATS = (
    "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
)


def _date_two_forms_ok(value: str) -> bool:
    """Date 两形判定（等价两形判定，母件 :66）：结构正则 + 历法实证。

    形一 `YYYY-MM-DD` / 形二 `YYYY-MM-DD[ T]HH:MM(:SS)`；`2026-8-5`（未补零）、
    `2026-13-45`（月/日越界）等皆不合。
    """
    if DATE_RE.match(value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False
    if DATE_TIME_RE.match(value):
        for fmt in _DATE_TIME_FORMATS:
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                continue
    return False


def fmt_hms(seconds) -> str:
    """时长（秒）→ hh:mm:ss（DA/T M17 口径；负数截 0）。

    ★ 单一实现，供四出口共用：检查器预填（inspector_panel）、批量预填
    （batch_metadata_module）、导出收集（main_window._collect_export_metadata）、
    from_audio 构造。取整沿用既有银行家舍入（Python round()：1.5→2、2.5→2、
    61.9→62、86399.6→86400→24:00:00 进位形合法）——禁改 floor/ceil（行为变更另裁）。
    """
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def check_format(field: str, value: str) -> str | None:
    """值域格式校验（M-4b/M-4b2）：Date + Duration 两条。

    Date：两形之一（YYYY-MM-DD 或 日期+时间）；Duration：M17 hh:mm:ss（小时位
    两位以上，容纳 24:00:00 进位形）。枚举四项（SamplingRate/BitDepth/Channels/
    Format）因 DA/T 原文值域末尾均带 [其他] 兜底 ⇒ 不设校验（设了即假闸）。

    不合 → 返回字段名（消费方据此组提示文案）；空值/其余字段一律返回 None
    （必填性归 required_for_standard，格式只查已填值）。
    """
    if field == "Date" and value and not _date_two_forms_ok(value):
        return field
    if field == "Duration" and value and not DURATION_RE.match(value):
        return field
    return None

# M-3 导出 profile 机读槽位（与 std_slots 同源；测试守卫对撞防漂）
# field key → (M 编号, 官方名, 特注)
DAT63_SLOTS: dict[str, tuple[str, str, str]] = {
    "Identifier":    ("M5",  "唯一标识符", ""),
    "Title":         ("M7",  "题名", ""),
    "Creator":       ("M8",  "责任者", ""),
    "Date":          ("M14", "摄录时间", ""),
    "GenreContext":  ("M19", "主题", "近似（M19/M20；非等同）"),
    "SamplingRate":  ("M64", "音频采样率", ""),
    "BitDepth":      ("M65", "音频量化位数", ""),
    "Format":        ("M49", "格式名称", "父元素 M48 格式信息"),
    "Channels":      ("M66", "声道", ""),
    "Duration":      ("M17", "时间长度", ""),
    # M-8a：DA/T 必选集四项「有据的自动/预设」入典（M46/M47 现读、M4/M27 原文缺省；
    # GBT_SLOTS 不追加——GB/T 表1 17 项/表2 4 项均无此四概念，导出注「标准外自定义」属实）
    "FileName":         ("M46", "计算机文件名", ""),
    "FileSize":         ("M47", "计算机文件大小", "原文可重复；本软件出当前单值"),
    "AggregationLevel": ("M4",  "聚合层次", ""),
    "RetentionPeriod":  ("M27", "保管期限", ""),
}
# field key → (系统名（表2 项无）, 官方名, 表号, 特注)
GBT_SLOTS: dict[str, tuple[str, str, str, str]] = {
    "Identifier":   ("infoResourceIdentifier", "信息资源标识符", "表1", ""),
    "Title":        ("", "题名", "表2", ""),
    "Creator":      ("agentName", "代理名称", "表1", "近似"),
    "Date":         ("actionDateTime", "操作日期时间", "表1", "表2 另有「日期」（数字化日期）"),
    "SamplingRate": ("samplingFrequency", "采样频率", "表1", ""),
    "BitDepth":     ("quantizationPrecision", "量化精度", "表1", ""),
    "Format":       ("format", "格式", "表1", ""),
    "Channels":     ("numberOfChannels", "通道数", "表1", ""),
}

# 非字段字典自定义键的落点：MDGroup 为 Session 必填子元素〔XSD:776〕，其 Keys〔XSD:365〕即「收纳未覆盖信息」位
_CUSTOM_KEYS_PATH = "Session/MDGroup/Keys/Key"

# IMDI 3.0.22 子元素序列（逐字取自仓内 XSD；导出前按 schema 序重排，表外键稳定追加于后）
_IMDI_CHILD_ORDER: dict[str, list[str]] = {
    "METATRANSCRIPT": ["History", "Session", "Corpus", "Catalogue"],
    "Session": ["Name", "Title", "Date", "ExternalResourceReference",
                "Description", "MDGroup", "Resources", "References"],
    "MDGroup": ["Location", "Project", "Keys", "Content", "Actors"],
    "Location": ["Continent", "Country", "Region", "Address"],
    "Project": ["Name", "Title", "Id", "Contact", "Description"],
    "Content": ["Genre", "SubGenre", "Task", "Modalities", "Subject",
                "CommunicationContext", "Interactivity", "PlanningType",
                "Involvement", "SocialContext", "EventStructure", "Channel",
                "Languages", "Keys", "Description"],
    "Actors": ["Description", "Actor"],
    "Actor": ["Role", "Name", "FullName", "Code", "FamilySocialRole",
              "Languages", "EthnicGroup", "Age", "BirthDate", "Sex",
              "Education", "Anonymized", "Contact", "Keys", "Description"],
    "Resources": ["MediaFile", "WrittenResource", "LexiconResource",
                  "LexiconComponent", "Source", "Anonyms"],
    "MediaFile": ["ResourceLink", "Type", "Format", "Size", "Quality",
                  "RecordingConditions", "TimePosition", "Access",
                  "Description", "Keys"],
    "TimePosition": ["Start", "End"],
    "Access": ["Availability", "Date", "Owner", "Publisher", "Contact",
               "Description"],
    "Keys": ["Key"],
}


def _place(session: dict, path: str, name: str, value: str) -> None:
    """按 IMDI 路径落值；末段为 Key 者生成列表项 {@Name, #text}（Key_Type〔XSD:210〕）。"""
    parts = [p for p in path.split("/") if p and p != "Session"]
    node = session
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    if parts[-1] == "Key":
        node.setdefault("Key", []).append({"@Name": name, "#text": value})
    else:
        node[parts[-1]] = value


def _ordered(tag: str, node: dict) -> dict:
    """按 XSD 子元素序重排单层 dict（表外键稳定追加于后）。"""
    out: dict = {}
    for k in _IMDI_CHILD_ORDER.get(tag, []):
        if k in node:
            out[k] = _ordered(k, node[k]) if isinstance(node[k], dict) else node[k]
    for k, v in node.items():
        if k not in out:
            out[k] = _ordered(k, v) if isinstance(v, dict) else v
    return out


# --- M-6a：文档级合法骨架常量（取证件 02_References/IMDI_document_level_notes_20261013.md §三/§四/§五/§七）---
IMDI_NS = "http://www.mpi.nl/IMDI/Schema/IMDI"           # targetNamespace〔XSD:86〕
IMDI_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
IMDI_FORMAT_ID = "IMDI 3.0.22"                            # §七-1：schema 自声明 Version 3.0.22〔XSD:4〕
IMDI_SCHEMA_LOCATION = (                                  # §七-1：与两机构实例件同形（非必填，仅提示）
    "http://www.mpi.nl/IMDI/Schema/IMDI http://www.mpi.nl/IMDI/Schema/IMDI_3.0.xsd"
)


def _scaffold_actor(actor: dict) -> None:
    """补齐单个 Actor 的必填子件（Actor_Type〔XSD:491-583〕13 必填件）。

    FullName 已有真值（Creator）则保留；Age/Anonymized 无源须用官方字面
    （AgeRange_Type/Boolean_Type 不接受空串，§七-2 同类口径）；其余 String/
    Vocabulary_Type 空元素合法。Contact/Description 为可选项不补。
    """
    actor.setdefault("Role", "")                          # Vocabulary_Type 空合法
    actor.setdefault("Name", "")                          # String_Type 空合法
    actor.setdefault("FullName", "")
    actor.setdefault("Code", "")
    actor.setdefault("FamilySocialRole", "")
    actor.setdefault("Languages", {})                     # Languages_Type 空合法
    actor.setdefault("EthnicGroup", "")
    actor.setdefault("Age", "Unknown")                    # AgeRange_Type 不接受空串→官方字面
    actor.setdefault("BirthDate", "")                     # Date_Type 接受空串
    actor.setdefault("Sex", "")
    actor.setdefault("Education", "")
    actor.setdefault("Anonymized", "Unknown")             # Boolean_Type 不接受空串→官方字面
    actor.setdefault("Keys", {})                          # Keys_Type 空合法


def _scaffold_required(session: dict) -> None:
    """补齐 Session 必填骨架为**空元素**（无源→留空，不得臆造；取证件 §四）。

    只补**必填**元素（XSD 无 minOccurs=0 者）；可选项不补。三处官方字面
    （§五/§七-2）：`Session/Date` 空→`Unknown`；`MediaFile/Quality`→`Unknown`；
    `TimePosition/Start`→`Unspecified`——均为规范自带字面，非本软件自定。
    Actor 有 13 个必填子件〔XSD:505-574〕，故不产出残缺 Actor；Creator 真值
    仍挂 `Actors/Actor/FullName` 时由调用方先落值，本函数只补同层缺失必填件。
    """
    # Session 三必填子 + 空值语义（Date 空→Unknown）
    for k in ("Name", "Title"):
        session.setdefault(k, "")
    if not session.get("Date"):
        session["Date"] = "Unknown"                       # §五：唯一不许空槽
    # MDGroup 五件全必填〔XSD:350〕
    mg = session.setdefault("MDGroup", {})
    loc = mg.setdefault("Location", {})                   # Continent/Country 必填〔XSD:184/189〕
    loc.setdefault("Continent", "")
    loc.setdefault("Country", "")
    proj = mg.setdefault("Project", {})                   # Name/Title/Id/Contact 四件必填〔XSD:314〕
    for k in ("Name", "Title", "Id"):
        proj.setdefault(k, "")
    proj.setdefault("Contact", {})                        # Contact 子件全可选〔XSD:1344〕→空合法
    mg.setdefault("Keys", {})                             # Key minOccurs=0〔XSD:225〕→空合法
    content = mg.setdefault("Content", {})                # Genre/CommunicationContext/Languages/Keys 必填〔XSD:386-461〕
    content.setdefault("Genre", "")
    content.setdefault("CommunicationContext", {})
    content.setdefault("Languages", {})
    content.setdefault("Keys", {})
    actors = mg.setdefault("Actors", {})                  # Actor minOccurs=0〔XSD:480〕
    # Creator 真值挂 Actorso/Actor/FullName〔XSD:515〕时，须产完整 Actor（13 必填子件）
    if isinstance(actors.get("Actor"), dict):
        _scaffold_actor(actors["Actor"])
    # Resources/MediaFile 全树（§七-2 实测序）
    res = session.setdefault("Resources", {})
    mf = res.setdefault("MediaFile", {})
    mf.setdefault("ResourceLink", "")
    mf.setdefault("Type", "")
    mf.setdefault("Format", "")
    mf.setdefault("Size", "")                             # 无源→空
    mf.setdefault("Quality", "Unknown")                   # §七-2：不接受空串，须官方字面
    mf.setdefault("RecordingConditions", "")
    mf.setdefault("TimePosition", {"Start": "Unspecified"})  # §七-2：pattern hh:mm:ss:ff|Unknown|Unspecified
    access = mf.setdefault("Access", {})                  # 六件全必填〔XSD:249〕
    access.setdefault("Availability", "")                 # Vocabulary_Type 可空元素
    access.setdefault("Date", "")                         # Date_Type=simpleContent，值写文本（无源留空合法）
    access.setdefault("Owner", "")
    access.setdefault("Publisher", "")
    access.setdefault("Contact", {})                      # 子件全可选→空合法
    mf.setdefault("Keys", {})                             # 技术四项 Keys/Key 落此（M-2 映射原样）


@dataclass
class SessionMetadata:
    """田野元数据容器：key → value（全部字符串化存储）。

    ``morphology``（W-14-07）为**独立**的中国音乐形态学扩展块：不进 ``values``、
    不进 ``FIELD_TERMS``、不进任何标准槽位；导出侧单列 ``morphology`` 块/列/段。
    缺省空 dict ⇒ 旧行为与旧导出件逐字不变。
    """

    values: dict[str, str] = field(default_factory=dict)
    morphology: dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value) -> None:
        """写一个标准/自定义字段。

        特例（W-14-07）：键 ``"_morphology"`` 视为**形态学扩展块的 JSON 文本**，
        直接落入 :attr:`morphology` 而**不进** ``values``——这样「检视器把块存在
        文件 metadata、导出层由 metadata 重建 SessionMetadata」的既有通路无需改动
        即可让导出件带独立 ``morphology`` 块，且标准字段面不受污染。
        """
        if key == MORPHOLOGY_STORAGE_KEY:
            self.set_morphology(_load_morphology_text(value))
            return
        self.values[key] = str(value)

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    # ---- W-14-07：形态学扩展块（独立命名空间，不混入标准字段）----
    def set_morphology(self, values: Mapping[str, Any] | None) -> None:
        """写入形态学块（先去空、再去空白；**不补默认值**）。"""
        self.morphology = normalize_morphology(values)

    def get_morphology(self) -> dict:
        """读形态学块（浅拷贝；空块返回空 dict）。"""
        return dict(self.morphology or {})

    def validate_morphology(self) -> list[str]:
        """形态学块校验（问题清单；空列表＝通过）。"""
        return check_morphology_fields(self.morphology)

    def validate(self, standard: str | None = None) -> list[str]:
        """返回缺失必填字段列表（空列表 = 合法）。

        standard=None → 现 REQUIRED_KEYS 行为逐字不变（向后兼容）；
        传标准码 → 按 required_for_standard(code) 的必填集（未知码回落 REQUIRED_KEYS）。
        """
        if standard is None:
            keys = REQUIRED_KEYS
        else:
            required = required_for_standard(standard)
            keys = [t.key for t in FIELD_TERMS if t.key in required]
        return [k for k in keys if not self.values.get(k)]

    def to_dict(self) -> dict:
        """全字段扁平映射（FIELD_TERMS 标准键序 + 自定义键）。

        与 to_imdi() 的嵌套结构相对：本方法只做一层扁平映射（不做标准槽位
        分流）。FIELD_TERMS 的标准键一律出现、缺省为空串占位；非 FIELD_TERMS
        的自定义键按 values 插入序无损追加（稳定）。供 JSON 导出与 CSV 表头
        共用，不臆造任何数值。
        """
        flat = {t.key: self.get(t.key) for t in FIELD_TERMS}
        for k, v in self.values.items():
            if k not in flat:
                flat[k] = v
        return flat

    def _place_session(self) -> dict:
        """槽位落值后的**原始** Session dict（未重排、未脚手架）。

        custom（M-2 旧形状）与 to_imdi()（M-6a 文档级树）共用的落值步骤：
        FIELD_TERMS 走 std_slots["IMDI"] 官方路径、末段 Key 生成列表项
        （@Name=字段键）；非字典自定义键落 Session/MDGroup/Keys/Key；空值不落。
        """
        session: dict = {}
        for t in FIELD_TERMS:
            value = self.get(t.key)
            if value:
                _place(session, t.std_slots["IMDI"], t.key, value)
        field_keys = {t.key for t in FIELD_TERMS}
        for k, v in self.values.items():
            if v and k not in field_keys:
                _place(session, _CUSTOM_KEYS_PATH, k, v)
        return session

    def to_imdi_session(self) -> dict:
        """M-2 版 IMDI 风格子树（`{"Session": …}`；空值不落 + 按 XSD 序重排）。

        供 PROFILE_CUSTOM 的 XML 导出沿用——export 侧以 `IMDI` 为根、本方法
        返回值即其下内容，输出与 BASE 逐字相同（含 `Session` 这一层）。
        与 to_imdi() 的文档级合法树相对——本方法不补脚手架、不出空元素。
        """
        return {"Session": _ordered("Session", self._place_session())}

    def to_imdi(self) -> dict:
        """映射到 IMDI 文档级合法树（M-6a；槽位逐条对仓内 XSD）。

        产出 `{"METATRANSCRIPT": {...}}`——根带五必填属性（Date=件生成日、
        Version="1.0"、FormatId=IMDI_FORMAT_ID〔§七-1 取证〕、Type="SESSION"、
        Originator="AcouScope"）+ xmlns/xsi/schemaLocation；Session 必填件齐、
        无源出**空元素**（合法化≠臆造，不编洲名/国名/项目名），仅三处官方字面
        （Session/Date→Unknown、MediaFile/Quality→Unknown、
        TimePosition/Start→Unspecified）。规格见取证件 §三/§四/§五/§七。
        """
        session = self._place_session()
        _scaffold_required(session)
        body = _ordered("Session", session)
        meta = {
            "@xmlns": IMDI_NS,                          # targetNamespace〔XSD:86〕
            "@xmlns:xsi": IMDI_XSI_NS,
            "@Date": date.today().isoformat(),          # 件生成日（勿与 Session/Date 录制日混，§七-3）
            "@Version": "1.0",                           # 件修订号（非 IMDI 版本，§七-1）
            "@FormatId": IMDI_FORMAT_ID,                # §七-1 取证（schema 自声明 Version 3.0.22〔XSD:4〕）
            "@Type": "SESSION",                          # Metatranscript_Value_Type 枚举〔XSD:1907-1914〕
            "@Originator": "AcouScope",                  # 产出工具名（两实例件同形，§七-1）
            "@xsi:schemaLocation": IMDI_SCHEMA_LOCATION,  # 非必填，仅提示（§七-1 末）
            "Session": body,
        }
        return {"METATRANSCRIPT": meta}


    def to_heritage(self) -> dict:
        """映射国内非遗音像档案著录核心要素。"""
        return {
            "档案编号": self.get("Identifier"),
            "项目名称": self.get("Title"),
            "传承人/表演者": self.get("Creator"),
            "采集时间": self.get("Date"),
            "地区": self.get("Location"),
            "类别/流派": self.get("GenreContext"),
            "技术信息": {
                "采样率": self.get("SamplingRate"),
                "位深": self.get("BitDepth"),
                "格式": self.get("Format"),
            },
        }

    @classmethod
    def from_audio(
        cls,
        identifier: str,
        title: str,
        creator: str,
        date: str,
        location: str,
        genre_context: str,
        sampling_rate,
        bit_depth,
        fmt: str,
        channels: int = 1,
        duration_s: float = 0.0,
        actor_role: str = "",
        **extra,
    ) -> "SessionMetadata":
        """便捷构造（技术元数据由录音参数自动填充）。"""
        m = cls()
        m.set("Identifier", identifier)
        m.set("Title", title)
        m.set("Creator", creator)
        m.set("Date", date)
        m.set("Location", location)
        m.set("GenreContext", genre_context)
        if actor_role:
            m.set("ActorRole", actor_role)
        m.set("SamplingRate", int(sampling_rate))
        m.set("BitDepth", int(bit_depth))
        m.set("Format", fmt)
        m.set("Channels", int(channels))
        m.set("Duration", fmt_hms(duration_s))
        for k, v in extra.items():
            m.set(k, v)
        return m
