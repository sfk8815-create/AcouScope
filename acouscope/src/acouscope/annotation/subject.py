# SPDX-License-Identifier: GPL-3.0-only
"""主体模型与主客观对照中间件（B3-02 / PI-P5 第 2 棒）。

边界与纪律（本模块自述，勿自行放宽）：
- 主体维度只走 ``metadata["subjects"]`` 的 JSON 串：``ProjectFile.metadata`` 保持
  ``Dict[str, str]`` 不变式（键值仍全是 str，主体列表整体序列化进单值），
  不改 project.py 的 metadata 结构。旧工程文件无该键 ⇒ 空列表（零崩溃）。
- **盲判包禁含 ``display_name``**：真名只留本地主体表（本项目文件可见），
  盲包内评者一律只带 ``rater_id``（= ``Subject.subject_id``，匿名 id）＋ ``role``。
- 两栏不合并：``role ∈ {qin_player（琴人）, erhu_player（二胡演奏者）}``；
  :func:`agreement_stats` 逐栏给一致率，跨栏值只作参照并显式标注，禁压成
  「专家」一项。
- 零候选或零响应 ⇒ :func:`agreement_stats` 返回 ``None``（诚实缺值，禁 0.0 冒充）。
- 盲包候选端默认消费 ``analysis.cavity_core.CoreCandidate``（B2-01 候选端）；
  不可用（导入失败 / 非 PitchGridModel / 零候选）时降级用 ``list[PitchNote]``，
  并在包内 ``candidate_source`` 字段披露。

纯函数、无 UI、不入项目文件。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

__all__ = [
    "BLIND_LABELS",
    "PACKET_FORMAT",
    "PACKET_VERSION",
    "ROLES",
    "ROLE_ERHU",
    "ROLE_QIN",
    "SUBJECTS_KEY",
    "Subject",
    "agreement_stats",
    "export_blind_packet",
    "import_blind_responses",
    "subjects_from_metadata",
    "subjects_to_metadata",
]

#: 主体列表在 ProjectFile.metadata 里的唯一键（值为 JSON 串，保持 Dict[str,str] 不变式）
SUBJECTS_KEY = "subjects"

ROLE_QIN = "qin_player"
ROLE_ERHU = "erhu_player"
ROLES: tuple[str, ...] = (ROLE_QIN, ROLE_ERHU)

PACKET_FORMAT = "acouscope-cavity-blind-packet"
PACKET_VERSION = 1

#: 盲判标签枚举（与 cavity_type.LABELS 逐字一致；此处重列以保持本模块自洽）
BLIND_LABELS: tuple[str, ...] = ("上趋", "下趋", "平直", "未分类")

_DEFAULT_INSTRUCTIONS = (
    "盲判说明：逐段仅据听感判定腔格走向（上趋／下趋／平直／未分类），"
    "不提供机器判定以免锚定；评者身份只见 rater_id。"
)


@dataclass(frozen=True)
class Subject:
    """主体（演奏者）：匿名 id ＋ 两栏角色 ＋ 本地真名 ＋ 备注。

    ``display_name`` 为真名，**只留本地主体表**（进 metadata["subjects"]），
    盲判包内一律剔除（见 :func:`export_blind_packet`）。
    ``role`` 限 :data:`ROLES`（琴人／二胡演奏者两栏，禁合并）。
    """

    subject_id: str
    role: str
    display_name: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"未登记角色 {self.role!r}（可用：{ROLES}）")


# ---------------------------------------------------------------------------
# 主体维度 ↔ metadata["subjects"]
# ---------------------------------------------------------------------------


def subjects_to_metadata(subjects: Sequence[Subject]) -> dict[str, str]:
    """主体列表 → ``{"subjects": JSON 串}``（值全是 str，保持 metadata 不变式）。

    序列化逐字段（subject_id / role / display_name / note），``ensure_ascii=False``
    保真中文；空列表亦写出 ``"[]"``（与「旧文件缺键」区分，可判据）。
    """
    return {
        SUBJECTS_KEY: json.dumps(
            [asdict(subject) for subject in subjects], ensure_ascii=False
        )
    }


def subjects_from_metadata(metadata: Mapping[str, str] | None) -> list[Subject]:
    """``metadata["subjects"]`` → 主体列表；缺键／None／坏 JSON ⇒ 空列表（零崩溃）。

    逐条校验：非 dict、缺 subject_id/role、role 未登记者一律跳过（禁臆测补值）。
    """
    if not isinstance(metadata, Mapping):
        return []
    raw = metadata.get(SUBJECTS_KEY)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    subjects: list[Subject] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        if "subject_id" not in item or "role" not in item:
            continue
        if item.get("role") not in ROLES:
            continue
        subjects.append(
            Subject(
                subject_id=str(item["subject_id"]),
                role=str(item["role"]),
                display_name=str(item.get("display_name", "")),
                note=str(item.get("note", "")),
            )
        )
    return subjects


# ---------------------------------------------------------------------------
# 盲判包
# ---------------------------------------------------------------------------


def _candidate_rows(model) -> tuple[list[dict], str]:
    """候选端：默认 CoreCandidate；不可用 ⇒ 降级 list[PitchNote]（回执披露口径名）。"""
    notes = list(getattr(model, "notes", model) or [])
    try:
        from ..analysis.cavity_core import core_candidates
    except Exception:  # 候选端不可导入（缺模块/循环依赖等）⇒ 降级
        core_candidates = None
    if core_candidates is not None and hasattr(model, "notes"):
        try:
            candidates = core_candidates(model)
        except Exception:  # 候选端报错（旧数据形制等）⇒ 降级
            candidates = []
        if candidates:
            return (
                [
                    {
                        "start_s": float(cand.start_s),
                        "end_s": float(cand.end_s),
                        "degree_index": cand.degree_index,
                        "deviation_cents": cand.deviation_cents,
                        "conf": float(cand.conf),
                    }
                    for cand in candidates
                ],
                "core_candidate",
            )
    return (
        [
            {
                "start_s": float(note.start_s),
                "end_s": float(note.end_s),
                "degree_index": getattr(note, "degree_index", None),
                "deviation_cents": getattr(note, "degree_deviation_cents", None),
                "conf": float(getattr(note, "conf", 0.0)),
            }
            for note in notes
        ],
        "pitch_note",
    )


def export_blind_packet(
    model,
    subjects: Sequence[Subject],
    packet_id: str = "",
    instructions: str = "",
) -> dict:
    """导出盲判包（**禁含 display_name**，评者只见 rater_id ＋ role）。

    包结构：``format`` / ``version`` / ``packet_id`` / ``instructions`` /
    ``labels`` / ``roles`` / ``candidate_source`` / ``segments`` / ``raters``。
    ``segments`` 逐条 ``{blind_segment_id: "S0001", start_s, end_s}``（不给机器
    判定，免锚定）；``raters`` 逐条 ``{rater_id: subject_id, role}``。
    候选端默认 ``CoreCandidate``，不可用时降级 ``PitchNote`` 并在
    ``candidate_source`` 披露（"core_candidate" / "pitch_note"）。
    """
    rows, source = _candidate_rows(model)
    segments = [
        {
            "blind_segment_id": f"S{index:04d}",
            "start_s": float(row["start_s"]),
            "end_s": float(row["end_s"]),
        }
        for index, row in enumerate(rows, start=1)
    ]
    body = {
        "format": PACKET_FORMAT,
        "version": PACKET_VERSION,
        "packet_id": str(packet_id),
        "instructions": str(instructions) or _DEFAULT_INSTRUCTIONS,
        "labels": list(BLIND_LABELS),
        "roles": list(ROLES),
        "candidate_source": source,
        "segments": segments,
        "raters": [
            {"rater_id": subject.subject_id, "role": subject.role}
            for subject in subjects
        ],
    }
    # 自检：包内评者只允许 rater_id（匿名 id）＋ role——真名 display_name 只在本地主体表；
    # 越界字段直接拒（禁「先塞进去再过滤」的写法，防真名漏进包内）。
    for rater in body["raters"]:
        if set(rater) != {"rater_id", "role"}:
            raise ValueError(f"盲包 rater 字段越界：{sorted(set(rater))}")
    return body


def _segment_id(start_s: float, end_s: float) -> str:
    """腔格段 id（口径同 cavity_type.segment_features：起讫秒三位小数）。"""
    return f"{float(start_s):.3f}-{float(end_s):.3f}"


def import_blind_responses(packet: Mapping, responses: Sequence[Mapping]) -> list[dict]:
    """回读盲判响应 → 专家判定行（schema 同 ``cavity_type.EXPERT_LABEL_SCHEMA``）。

    逐条校验：rater_id 须在包内、blind_segment_id 须在包内、label 须在包内
    ``labels`` 枚举内；任一不符即 ``ValueError``（确定性，禁静默丢行后再按
    缺值装作「无分歧」）。输出行键：``subject_id`` / ``role`` / ``recording_id``
    （= ``packet_id``）/ ``segment_id``（起讫秒三位小数）/ ``blind_segment_id`` /
    ``label`` / ``note``。
    """
    raters = {
        str(rater.get("rater_id")): str(rater.get("role"))
        for rater in packet.get("raters", [])
        if isinstance(rater, Mapping)
    }
    segments = {
        str(seg.get("blind_segment_id")): _segment_id(seg.get("start_s"), seg.get("end_s"))
        for seg in packet.get("segments", [])
        if isinstance(seg, Mapping)
    }
    allowed = tuple(packet.get("labels", BLIND_LABELS))
    packet_id = str(packet.get("packet_id", ""))
    rows: list[dict] = []
    for item in responses:
        if not isinstance(item, Mapping):
            raise ValueError(f"响应条目须为 Mapping，得到 {type(item).__name__}")
        rater_id = str(item.get("rater_id"))
        blind_id = str(item.get("blind_segment_id"))
        label = item.get("label")
        if rater_id not in raters:
            raise ValueError(f"包外 rater_id：{rater_id!r}")
        if blind_id not in segments:
            raise ValueError(f"包外 blind_segment_id：{blind_id!r}")
        if label not in allowed:
            raise ValueError(f"标签越界：{label!r}（可用：{allowed}）")
        rows.append(
            {
                "subject_id": rater_id,
                "role": raters[rater_id],
                "recording_id": packet_id,
                "segment_id": segments[blind_id],
                "blind_segment_id": blind_id,
                "label": str(label),
                "note": str(item.get("note", "")),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# 一致率
# ---------------------------------------------------------------------------


def agreement_stats(
    candidates: Sequence[Mapping], responses: Sequence[Mapping]
) -> dict | None:
    """机器候选 vs 盲判响应的一致率（按两栏分算；零候选／零响应 ⇒ None）。

    ``candidates``：逐段 ``{"segment_id", "label"}``（机器判定，如
    ``cavity_type_report()["records"]`` 收窄后）；``responses``：判定行（含
    ``role`` / ``segment_id`` / ``label``，如 :func:`import_blind_responses` 输出）。

    返回 ``{"n_candidates", "n_responses", "n_matched", "n_agree", "agreement",
    "by_role"}``；``agreement`` 为匹配行上的总一致率（跨栏参照值，**不作两栏
    合并解读**），无匹配行 ⇒ None。
    """
    cands = [row for row in candidates or [] if isinstance(row, Mapping)]
    resp = [row for row in responses or [] if isinstance(row, Mapping)]
    if not cands or not resp:
        return None
    machine = {
        str(row.get("segment_id")): row.get("label")
        for row in cands
        if row.get("segment_id") is not None
    }
    matched = [row for row in resp if str(row.get("segment_id")) in machine]
    if not matched:
        return None
    by_role: dict[str, dict] = {}
    for role in ROLES:
        rows = [row for row in matched if row.get("role") == role]
        if not rows:
            continue
        n_agree = sum(1 for row in rows if machine[str(row["segment_id"])] == row.get("label"))
        by_role[role] = {
            "n": len(rows),
            "n_agree": n_agree,
            "agreement": n_agree / len(rows),
        }
    n_agree = sum(1 for row in matched if machine[str(row["segment_id"])] == row.get("label"))
    return {
        "n_candidates": len(cands),
        "n_responses": len(resp),
        "n_matched": len(matched),
        "n_agree": n_agree,
        "agreement": n_agree / len(matched),
        "by_role": by_role,
        "note": "两栏分算（by_role）；总值为跨栏参照，禁作「专家」合并项解读",
    }
