# SPDX-License-Identifier: GPL-3.0-only
"""田野元数据模型（T-004-1）。FIELD_PITCH_V1

标准依据（文档级事实）：
- IASA-TC 04《音像档案著录指南》第二版核心要素：标识符(Identifier)、
  题名(Title)、创作者/责任者(Creator)、日期(Date)、载体与技术信息(Technical)。
- IMDI (ISLE Meta Data Initiative) Session 结构：
  Session{Name, Date, Location, Genre, Context, Actor{FullName, Role}, Resources}。
- 国内非遗音像档案著录核心要素映射：项目名称/传承人(表演者)/时间/地区/类别。

to_imdi() 无损承诺：标准槽位放标准字段，其余全部进 Session.Additional。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldTerm:
    """元数据字段项。"""

    namespace: str      # IASA | IMDI | TECH
    key: str            # 英文键（导出 CSV 表头用）
    label_zh: str       # 中文名
    required: bool = False
    imdi_slot: str = ""  # IMDI 标准槽位路径；空 = 进 Additional


# IASA-TC 04 / IMDI 核心字段字典（用户强指令4：必须内嵌）
FIELD_TERMS: list[FieldTerm] = [
    FieldTerm("IASA", "Identifier", "标识符", True, "Session.ID"),
    FieldTerm("IASA", "Title", "题名", True, "Session.Name"),
    FieldTerm("IMDI", "Creator", "创作者/表演者(传承人)", True, "Actor.FullName"),
    FieldTerm("IASA", "Date", "日期(采集日期)", True, "Session.Date"),
    FieldTerm("IMDI", "Location", "地理位置", True, "Session.Location"),
    FieldTerm("IMDI", "GenreContext", "文化语境/流派", True, "Session.Genre"),
    FieldTerm("IMDI", "ActorRole", "表演者角色", False, "Actor.Role"),
    # 技术元数据（IASA-TC 04 载体信息）
    FieldTerm("TECH", "SamplingRate", "采样率(Hz)", False, "Resources.SamplingRate"),
    FieldTerm("TECH", "BitDepth", "位深(bit)", False, "Resources.BitDepth"),
    FieldTerm("TECH", "Format", "格式", False, "Resources.Format"),
    FieldTerm("TECH", "Channels", "声道数", False, "Resources.Channels"),
    FieldTerm("TECH", "Duration", "时长(秒)", False, "Resources.Duration"),
]

REQUIRED_KEYS = [t.key for t in FIELD_TERMS if t.required]


@dataclass
class SessionMetadata:
    """田野元数据容器：key → value（全部字符串化存储）。"""

    values: dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value) -> None:
        self.values[key] = str(value)

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def validate(self) -> list[str]:
        """返回缺失必填字段列表（空列表 = 合法）。"""
        missing = [k for k in REQUIRED_KEYS if not self.values.get(k)]
        return missing

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

    def to_imdi(self) -> dict:
        """无损映射到 IMDI Session 结构。

        标准槽位字段放对应位置，其余（含自定义字段）无损放入
        Session.Additional。Actor/Resources 为嵌套结构。
        """
        session: dict = {"Additional": {}}
        actor: dict = {}
        resources: dict = {}
        slot_map = {t.key: t.imdi_slot for t in FIELD_TERMS}
        for k, v in self.values.items():
            slot = slot_map.get(k, "")
            if slot == "Session.Name":
                session["Name"] = v
            elif slot == "Session.ID":
                session["ID"] = v
            elif slot == "Session.Date":
                session["Date"] = v
            elif slot == "Session.Location":
                session["Location"] = v
            elif slot == "Session.Genre":
                session["Genre"] = v
            elif slot == "Actor.FullName":
                actor["FullName"] = v
            elif slot == "Actor.Role":
                actor["Role"] = v
            elif slot == "Resources.SamplingRate":
                resources["SamplingRate"] = v
            elif slot == "Resources.BitDepth":
                resources["BitDepth"] = v
            elif slot == "Resources.Format":
                resources["Format"] = v
            elif slot == "Resources.Channels":
                resources["Channels"] = v
            elif slot == "Resources.Duration":
                resources["Duration"] = v
            else:
                session["Additional"][k] = v
        if actor:
            session["Actor"] = actor
        if resources:
            session["Resources"] = resources
        return {"IMDI": {"Session": session}}

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
        m.set("Duration", round(float(duration_s), 3))
        for k, v in extra.items():
            m.set(k, v)
        return m
