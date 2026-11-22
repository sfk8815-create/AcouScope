# SPDX-License-Identifier: GPL-3.0-only
"""分母口径层（W-8／W-9）：**可判段**分母、不可判单列、低频不可靠单列。

本模块是「四值计数用哪个分母」的**唯一实现**，供分布件、图件分面、三栏件与
对账件共用，避免各处各算一套。

## 口径（照设计约定，勿自行放宽）

- **往复窗不可判**（`:data:`INDETERMINATE_ZH`）：段内有效帧 < 判据窗长
  （0.10 s 折帧数，本运行 17 帧）。这些段**不再拿类型标签**，单列
  ``n_indeterminate``；旧件里它们仍拿到了标签，故 W-8 起四值与旧件不同属正常。
- **不等于「类型不可判」**：本项只否定「往复窗够长」，不否定「类型判不出来」；
  文件内必须带此说明，避免被读成「类型判据失效」。
- **可判段**（``n_judgable``）：``n_all − n_indeterminate``，是 W-8 四值计数的
  分母（设计约定 A 应见：溥雪斋主档绝对口径 177，不是 183）。
- **低频不可靠**（:data:`LOW_FREQ_CLASS`）：横跨候选低钳帧或输出落最低格的段。
  设计约定 W-9 要求「不入正文比例的分母」，故另给 **正文分母**
  ``n_denominator_body = n_judgable − n_low_freq_unreliable`` 与对应的
  ``counts_per_recording_excluding_low_freq``；而 W-8 的 ``n_judgable`` 仍按
  设计约定 A 应见的算法（只减不可判），两者**同时给出、逐项命名**，不互相冒充。
- 三式恒等随件自检，另加一条补充式把正文分母的算式也摆出来：

  1. ``n_all = n_judgable + n_indeterminate``
  2. ``n_judgable = n_axis + n_composite``
  3. ``n_high_conf + n_low_conf + n_conf_missing = n_all``
  4. ``n_denominator_body = n_judgable − n_low_freq_unreliable``（W-9 正文分母）

- ``n_coexist`` 是**重叠指标**，与上述各项均可重叠，不入任何合计。
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from .cavity_type import LABEL_UNCLASSIFIED, LABELS, classify_cavity_type

__all__ = [
    "DENOMINATOR_POLICY",
    "INDETERMINATE_NOTE_ZH",
    "INDETERMINATE_RULE_ZH",
    "INDETERMINATE_ZH",
    "LOW_FREQ_CLASS",
    "LOW_FREQ_NOTE_ZH",
    "classify_segment",
    "counts_block",
]

#: 分母口径名（进机读口径面，换口径即换 ``run_id``）
DENOMINATOR_POLICY = "judgable_segments_v1"

#: 「不可判」在件内的正名（W-8 命名要求：往复窗不可判，不是「类型不可判」）
INDETERMINATE_ZH = "往复窗不可判"
INDETERMINATE_RULE_ZH = (
    "段内有效帧 < 判据窗长（0.10 s 折帧数；本运行见 criterion_window_frames）"
)
INDETERMINATE_NOTE_ZH = (
    "「往复窗不可判」不等于「类型不可判」：它只表示段内有效帧不足一个头尾偏离判据窗，"
    "故这些段自 W-8 起不再拿类型标签、单列为 n_indeterminate；旧件把这些短段仍算进了四值。"
)

#: 低频不可靠类的类名（W-9）
LOW_FREQ_CLASS = "low_frequency_unreliable"
LOW_FREQ_NOTE_ZH = (
    "low_frequency_unreliable：候选低于网格下界 61.735 Hz 或输出落在最低格的段。"
    "设计约定 W-9 要求其不入正文比例的分母，故另给 n_denominator_body 与该分母下的四值；"
    "不得用 hmm_output_range_hz 的下限反证网格已覆盖低频。"
)

#: 低置信判据（与 readout_extras.LOW_CONF_THRESHOLD 同值；此处单列以免循环导入）
_LOW_CONF_THRESHOLD = 0.5

#: 「体内 ≥2 次往复」判据（与 readout_extras.COEXIST_MIN_TURNS 同值）
_COEXIST_MIN_TURNS = 2


def _number(row: Mapping, key: str) -> float | None:
    raw = row.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def classify_segment(row: Mapping, *, criterion_window_frames: int,
                     tau_cents: float | None = None) -> dict:
    """单段的三个分母维：不可判／低频不可靠／置信档（**互不代替**）。

    返回 ``{"recurrence_window_insufficient", "low_frequency_unreliable",
    "confidence_band", "in_judgable", "in_denominator_body"}``。
    """
    n_valid = _number(row, "n_valid_frames")
    if "n_valid_frames" not in row:
        # 旧调用方（未带诊断字段）不作该诊断：缺字段 ≠ 帧数不足，不得据此判不可判
        insufficient = False
    else:
        insufficient = bool(
            n_valid is None or int(n_valid) < int(criterion_window_frames)
        )
    below = int(row.get("clamped_candidate_frames") or 0)
    at_min = int(row.get("output_at_grid_min_frames") or 0)
    low_freq = bool(below or at_min)
    conf = _number(row, "conf")
    if conf is None:
        band = "conf_missing"
    elif conf < _LOW_CONF_THRESHOLD:
        band = "low_conf"
    else:
        band = "high_conf"
    return {
        "recurrence_window_insufficient": insufficient,
        "low_frequency_unreliable": low_freq,
        "confidence_band": band,
        "in_judgable": not insufficient,
        "in_denominator_body": (not insufficient) and (not low_freq),
    }


def counts_block(rows: Sequence[Mapping], *, tau_cents: float | None,
                 criterion_window_frames: int) -> dict:
    """W-8 字段面 ＋ W-9 正文分母（同一批段行、同一次判型，两套分母并陈）。

    返回键（**逐字**，设计约定 W-8 要求）：

    ``counts_per_recording``（四值＋``合计``，分母＝``n_judgable``）、
    ``n_all``／``n_judgable``／``n_axis``／``n_composite``／``n_indeterminate``／
    ``n_high_conf``／``n_low_conf``／``n_conf_missing``／``n_coexist``；
    W-9 追加 ``counts_per_recording_excluding_low_freq``／``n_low_freq_unreliable``／
    ``n_denominator_body``。
    """
    axis = {label: 0 for label in LABELS}
    axis_body = {label: 0 for label in LABELS}
    n_all = 0
    n_indeterminate = 0
    n_low_freq = 0
    n_coexist = 0
    bands = {"high_conf": 0, "low_conf": 0, "conf_missing": 0}
    for row in rows:
        n_all += 1
        cls = classify_segment(
            row, criterion_window_frames=int(criterion_window_frames),
            tau_cents=tau_cents,
        )
        bands[cls["confidence_band"]] += 1
        turns = _number(row, "turns")
        head = _number(row, "head_deviation_cents")
        tail = _number(row, "tail_deviation_cents")
        if (
            head is not None
            and tail is not None
            and turns is not None
            and int(turns) >= _COEXIST_MIN_TURNS
            and bool(row.get("turns_valid"))
            and _within_tau(float(tail) - float(head), tau_cents)
        ):
            n_coexist += 1
        if cls["recurrence_window_insufficient"]:
            n_indeterminate += 1
            continue
        label = classify_cavity_type(row, tau_cents=tau_cents)
        axis[label] = axis.get(label, 0) + 1
        if cls["low_frequency_unreliable"]:
            n_low_freq += 1
        else:
            axis_body[label] = axis_body.get(label, 0) + 1

    n_judgable = n_all - n_indeterminate
    n_axis = sum(axis[label] for label in LABELS if label != LABEL_UNCLASSIFIED)
    n_composite = int(axis[LABEL_UNCLASSIFIED])
    n_body = n_judgable - n_low_freq

    counts = {label: int(axis[label]) for label in LABELS}
    counts["合计"] = int(sum(counts[label] for label in LABELS))
    counts_body = {label: int(axis_body[label]) for label in LABELS}
    counts_body["合计"] = int(sum(counts_body[label] for label in LABELS))

    checks = [
        {
            "expr": "n_all == n_judgable + n_indeterminate",
            "lhs": int(n_all),
            "rhs": int(n_judgable + n_indeterminate),
            "ok": bool(n_all == n_judgable + n_indeterminate),
        },
        {
            "expr": "n_judgable == n_axis + n_composite",
            "lhs": int(n_judgable),
            "rhs": int(n_axis + n_composite),
            "ok": bool(n_judgable == n_axis + n_composite),
        },
        {
            "expr": "n_high_conf + n_low_conf + n_conf_missing == n_all",
            "lhs": int(bands["high_conf"] + bands["low_conf"] + bands["conf_missing"]),
            "rhs": int(n_all),
            "ok": bool(
                bands["high_conf"] + bands["low_conf"] + bands["conf_missing"] == n_all
            ),
        },
        {
            "expr": "n_denominator_body == n_judgable - n_low_freq_unreliable",
            "lhs": int(n_body),
            "rhs": int(n_judgable - n_low_freq),
            "ok": bool(n_body == n_judgable - n_low_freq),
        },
    ]
    return {
        "denominator_policy": DENOMINATOR_POLICY,
        "counts_per_recording": counts,
        "counts_per_recording_excluding_low_freq": counts_body,
        "n_all": int(n_all),
        "n_judgable": int(n_judgable),
        "n_axis": int(n_axis),
        "n_composite": int(n_composite),
        "n_indeterminate": int(n_indeterminate),
        "n_low_freq_unreliable": int(n_low_freq),
        "n_denominator_body": int(n_body),
        "n_high_conf": int(bands["high_conf"]),
        "n_low_conf": int(bands["low_conf"]),
        "n_conf_missing": int(bands["conf_missing"]),
        "n_coexist": int(n_coexist),
        "criterion_window_frames": int(criterion_window_frames),
        "indeterminate_name_zh": INDETERMINATE_ZH,
        "indeterminate_rule_zh": INDETERMINATE_RULE_ZH,
        "indeterminate_note_zh": INDETERMINATE_NOTE_ZH,
        "low_frequency_class": LOW_FREQ_CLASS,
        "low_frequency_note_zh": LOW_FREQ_NOTE_ZH,
        "denominator_names_zh": {
            "n_all": "全部段（含不可判、含低频不可靠）",
            "n_judgable": "可判段＝全部 − 往复窗不可判（W-8 四值分母）",
            "n_denominator_body": "正文比例分母＝可判段 − 低频不可靠（W-9）",
            "n_coexist": "重叠指标，不入任何合计",
        },
        "identity_checks": checks,
        "identity_ok": bool(all(item["ok"] for item in checks)),
    }


def _within_tau(value: float, tau_cents: float | None) -> bool:
    """「净差在容差内」：τ 未声明 ⇒ 只按符号判（|差| == 0 才算平）。"""
    if tau_cents is None:
        return abs(float(value)) == 0.0
    return abs(float(value)) <= float(tau_cents)


def low_frequency_segments(rows: Iterable[Mapping]) -> list[dict]:
    """低频不可靠段的逐段清单（W-9；供表注／正文逐段回查）。"""
    out: list[dict] = []
    for row in rows:
        below = int(row.get("clamped_candidate_frames") or 0)
        at_min = int(row.get("output_at_grid_min_frames") or 0)
        if not (below or at_min):
            continue
        out.append(
            {
                "segment_id": row.get("segment_id"),
                "clamped_candidate_frames": int(below),
                "output_at_grid_min_frames": int(at_min),
                "n_valid_frames": row.get("n_valid_frames"),
                "head_deviation_cents": row.get("head_deviation_cents"),
                "tail_deviation_cents": row.get("tail_deviation_cents"),
                "turns": row.get("turns"),
                "turns_valid": bool(row.get("turns_valid")),
                "in_turn_stats": bool(row.get("turns_valid")),
            }
        )
    return out
