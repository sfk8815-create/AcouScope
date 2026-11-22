# SPDX-License-Identifier: GPL-3.0-only
"""三型分布的通用读数与导出层（任务件-20261026 · T-1／T-2／T-5）。

**本模块自述边界（勿自行放宽）：**

- τ（判「无变化」的音分容差）由**平台声明**：值恒取自
  :data:`acouscope.analysis.cavity_type.TAU_CENTS_PLACEHOLDER`（None = 未标定），
  状态随之取 ``unspecified_sign_based``；若该常量日后经 P2 标定给出数值，状态即
  ``calibrated``。``tau_cents=None`` 的语义是「取平台占位值」，**不是**「由使用方
  自设」——使用方注入的 τ 一律另记 ``assumed_for_scan``，不得冒充标定结果
  （与 ``cavity_type.py:22–24,59–64,325–333`` 同一口径）。
- 运行身份 ``run_id`` = 该运行描述符（输入清单 × 参数面 × 分段快照）的 sha256，
  **内容定址、非时间戳**：同参同输入两次跑得同一 id，故图件与表件可凭 run_id
  断言同源（T-3）。
- 只出读数与导出件：不画图、不写论文文字、不入 UI。

三型的判定规则与标签枚举一律复用 :mod:`acouscope.analysis.cavity_type`
（沈洽《音腔论》2019：37 的上趋／下趋／平直三分），本模块不重实现判定。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from ..dsp.reference_status import get_reference_status
from .cavity_type import (
    LABELS,
    LABEL_UNCLASSIFIED,
    TAU_CENTS_PLACEHOLDER,
    classify_cavity_type,
    segment_features,
)
from .denominator import (
    DENOMINATOR_POLICY,
    INDETERMINATE_NOTE_ZH,
    INDETERMINATE_RULE_ZH,
    INDETERMINATE_ZH,
    LOW_FREQ_CLASS,
    LOW_FREQ_NOTE_ZH,
    classify_segment,
    counts_block,
    low_frequency_segments,
)
from .params_snapshot import analysis_params_snapshot
from .tonic_ref import REF_ABSOLUTE, REF_MAIN_TONE

__all__ = [
    "CALIBRATION_NOTE",
    "DEFAULT_TAU_VALUES",
    "DISTRIBUTION_FORMAT",
    "DISTRIBUTION_VERSION",
    "LABEL_GLOSS",
    "REF_MODE_GLOSS",
    "RUN_DESCRIPTOR_FORMAT",
    "RUN_DESCRIPTOR_VERSION",
    "SWEEP_FORMAT",
    "SWEEP_SUMMARY_FORMAT",
    "SWEEP_VERSION",
    "TAU_BAND_CONTROL",
    "TAU_BAND_MAIN",
    "TAU_STATUSES",
    "TAU_STATUS_CALIBRATED",
    "TAU_STATUS_DECLARED_UNCALIBRATED",
    "TAU_STATUS_SCAN_ASSUMED",
    "TAU_STATUS_UNSPECIFIED",
    "count_labels",
    "distribution_payload",
    "export_json",
    "export_rows_csv",
    "pair_segments",
    "panels_payload",
    "run_descriptor",
    "run_id",
    "scan_tau_status",
    "segment_source_snapshot",
    "sweep_summary",
    "tau_declaration",
    "tau_key",
    "tau_sweep_payload",
    "window_segment_rows",
]

#: τ 状态：``tau_status`` 字段的**枚举面**（T-1 只取这两值）
TAU_STATUS_CALIBRATED = "calibrated"
TAU_STATUS_UNSPECIFIED = "unspecified_sign_based"
TAU_STATUSES = (TAU_STATUS_CALIBRATED, TAU_STATUS_UNSPECIFIED)

#: 使用方注入的 τ（仅用于敏感性扫描）的登记态——**不是**标定态，
#: 出现在 sweep 的 ``tau_status_by_tau`` 里，不得写进 T-1 的 ``tau_status``。
TAU_STATUS_SCAN_ASSUMED = "assumed_for_scan"

#: 主档（本次运行口径声明）的 τ 状态（W-1／T-9）：**运行口径声明、未经参考语料标定**。
#: 与 ``calibrated``（平台标定）逐字区分：声明值可复算，但不冒充标定结果。
TAU_STATUS_DECLARED_UNCALIBRATED = "run_config_declared_uncalibrated"

#: 双档并陈的档位标记（W-1）：主档／对照档
TAU_BAND_MAIN = "main_declared"
TAU_BAND_CONTROL = "control_sign_based"

#: 固定文案（T-9 交付字段 ``calibration_note``）：一个字都不得改成「已校准」。
CALIBRATION_NOTE = "未经参考语料标定"

#: τ 敏感性扫描的默认取值：第一档 = 平台占位（按符号判），其余为扫描用假设值
DEFAULT_TAU_VALUES: tuple[float | None, ...] = (None, 10.0, 20.0, 30.0)

DISTRIBUTION_FORMAT = "acouscope-type-distribution"
DISTRIBUTION_VERSION = 1
SWEEP_FORMAT = "acouscope-tau-sweep"
SWEEP_VERSION = 1
SWEEP_SUMMARY_FORMAT = "acouscope-tau-sweep-summary"
RUN_DESCRIPTOR_FORMAT = "acouscope-run-descriptor"
RUN_DESCRIPTOR_VERSION = 1

#: 标签语义（T-5）：随件导出，避免「未分类」被读作「未达分段资格」
LABEL_GLOSS: dict[str, str] = {
    "上趋": "头或尾相对段中位的偏离呈上行倾向（Δh<0 或 Δt>0）",
    "下趋": "头或尾相对段中位的偏离呈下行倾向（Δh>0 或 Δt<0）",
    "平直": "头尾两侧均无超出容差的有向偏离",
    LABEL_UNCLASSIFIED: "复合型（头尾倾向相反）",
}

#: 口径语义（供表注图注直接引用；内部 key 不变）
REF_MODE_GLOSS: dict[str, str] = {
    REF_ABSOLUTE: "绝对口径",
    REF_MAIN_TONE: "主音相对口径",
}


# ---------------------------------------------------------------------------
# τ 声明与分段快照
# ---------------------------------------------------------------------------


def tau_key(tau_cents: float | None) -> str:
    """τ 的 JSON 安全键（None = 未标定，按符号判）。"""
    return "None" if tau_cents is None else repr(float(tau_cents))


def tau_declaration() -> dict:
    """**平台侧**的 τ 声明（值 + 状态），供导出件随件写入。

    返回 ``{"tau_cents", "tau_status"}``：``tau_cents`` 恒取
    :data:`TAU_CENTS_PLACEHOLDER` 的当前值；``None`` ⇒ ``tau_status`` 为
    ``"unspecified_sign_based"``（未标定，按符号判），有数值 ⇒ ``"calibrated"``。
    本函数**不接受外部 τ** —— 平台未标定就是未标定，不得由使用方补值。
    """
    value = TAU_CENTS_PLACEHOLDER
    return {
        "tau_cents": None if value is None else float(value),
        "tau_status": TAU_STATUS_UNSPECIFIED if value is None else TAU_STATUS_CALIBRATED,
    }


def scan_tau_status(tau_cents: float | None) -> str:
    """单个扫描 τ 值的状态（**扫描记账用**，非平台标定态）。

    ``None`` ⇒ ``unspecified_sign_based``（即平台占位档）；数值 ⇒ ``assumed_for_scan``
    ——说明该值系为观察敏感性而设的假设，**不代表平台已标定**。
    """
    return TAU_STATUS_UNSPECIFIED if tau_cents is None else TAU_STATUS_SCAN_ASSUMED


def segment_source_snapshot(
    *,
    segmenter: str = "hmm",
    window_s: float = 30.0,
    min_window_s: float = 5.0,
    fmin: float = 60.0,
    fmax: float = 1500.0,
    block_seconds: float = 30.0,
    tuning_template: str = "12tet",
    window_starts_s: Sequence[float] | None = None,
    params: Mapping | None = None,
) -> dict:
    """分段器与其参数快照（导出件随件字段）。

    分段口径随参数而变（换窗／换分段器／换律制 ⇒ 换段 ⇒ 换数），故**随件登记**，
    使任何一张分布表都能回溯到其分段快照。``params_snapshot`` 走
    :func:`analysis.params_snapshot.analysis_params_snapshot`（A4 基准等全局单源实读）。
    """
    snap = analysis_params_snapshot() if params is None else dict(params)
    starts = [round(float(x), 3) for x in (window_starts_s or ())]
    return {
        "segmenter": str(segmenter),
        "window_s": float(window_s),
        "min_window_s": float(min_window_s),
        "fmin": float(fmin),
        "fmax": float(fmax),
        "block_seconds": float(block_seconds),
        "tuning_template": str(tuning_template),
        "windows": {
            "count": len(starts),
            "starts_s": starts,
        },
        "params_snapshot": snap,
    }


# ---------------------------------------------------------------------------
# 段行与计数
# ---------------------------------------------------------------------------


def window_segment_rows(model, *, window_start_s: float = 0.0,
                        ref_mode: str = REF_ABSOLUTE) -> list[dict]:
    """单窗模型 → **全局时间基准**的段特征行。

    ``segment_id`` 为「全局起讫秒三位小数」（含窗偏移），可跨窗对齐与复核；
    ``segment_id_local`` 保留**窗内** id，供与窗级读数（如 ``repeat_degree_v2``）
    对齐——两者**不可混用**：窗级读数按窗内 id 出，跨窗汇总须先挂到行上再全局化。
    ``ref_mode`` 标明该行所属口径，两口径的行不得混在一个列表里。
    """
    rows: list[dict] = []
    for row in segment_features(model):
        start = float(row["start_s"]) + float(window_start_s)
        end = float(row["end_s"]) + float(window_start_s)
        out = dict(row)
        out["segment_id_local"] = str(row["segment_id"])
        out["start_s"] = start
        out["end_s"] = end
        out["segment_id"] = f"{start:.3f}-{end:.3f}"
        out["ref_mode"] = str(ref_mode)
        rows.append(out)
    return rows


def count_labels(rows: Iterable[Mapping], *, tau_cents: float | None = None) -> dict:
    """段行 → 三型＋未分类计数与合计（判定复用平台分类器）。

    返回键：``上趋``／``下趋``／``平直``／``未分类``／``合计``。第四项
    （``未分类``）即**复合型**（头尾倾向相反），语义见 :data:`LABEL_GLOSS`。
    ``tau_cents=None`` ⇒ 取平台占位值（``tau_declaration()``）。
    """
    tau = TAU_CENTS_PLACEHOLDER if tau_cents is None else float(tau_cents)
    counts = {label: 0 for label in LABELS}
    for row in rows:
        label = classify_cavity_type(row, tau_cents=tau)
        counts[label] = counts.get(label, 0) + 1
    out = {label: int(counts[label]) for label in LABELS}
    out["合计"] = int(sum(out[label] for label in LABELS))
    return out


def distribution_payload(
    rows: Sequence[Mapping],
    *,
    recording_id: str = "",
    ref_mode: str = REF_ABSOLUTE,
    segment_source: Mapping | None = None,
    run_id_: str | None = None,
    tau_band: str = TAU_BAND_CONTROL,
    tau_analysis: float | None = None,
    tau_provenance: str = "",
    criterion_window_frames: int = 0,
    provenance: Mapping | None = None,
) -> dict:
    """三型分布导出件（T-1 字段面；W-1 双档；**W-8 四值改按可判段**）。

    ``counts_per_recording`` 的分母自 W-8 起是 **可判段** ``n_judgable``
    （＝``n_all − n_indeterminate``）：段内有效帧不足一个头尾偏离判据窗的短段
    **不拿类型标签**，单列 ``n_indeterminate``（件内正名「往复窗不可判」）。故

    - 四值之和 ＝ ``n_judgable``（不再等于 ``n_all``）；
    - ``n_indeterminate`` 段**不在**四值里；
    - ``n_high_conf``／``n_low_conf``／``n_conf_missing`` 显式给出（三者和＝``n_all``）；
    - ``n_coexist`` 为重叠指标，不入任何合计；
    - 另给 W-9 的正文分母 ``n_denominator_body`` 与
      ``counts_per_recording_excluding_low_freq``（低频不可靠段不入正文比例分母）。

    ``criterion_window_frames``：判据窗长（0.10 s 折帧数，本运行 17）。缺省 0 ＝
    不做该诊断（**仅向后兼容**；正式出件必须传入）。

    ``tau_band``：

    - ``control_sign_based``（默认，**对照档**）：τ 恒由平台声明
      （:func:`tau_declaration`），即 ``TAU_CENTS_PLACEHOLDER`` 现值 ``None``
      ⇒ ``tau_cents = null``、``tau_status = unspecified_sign_based``；
    - ``main_declared``（**主档**）：τ 取**本次运行的口径声明**
      ``tau_analysis``（如 10 音分），``tau_status`` 记
      ``run_config_declared_uncalibrated``（运行口径声明、**未经参考语料标定**），
      并随件附 ``tau_provenance``（声明途径）与固定文案 ``calibration_note``。

    两档的 ``run_id`` 同值（同一次运行同批段行，只换判型容差），故可逐格比对。
    **本函数不改** :data:`cavity_type.TAU_CENTS_PLACEHOLDER`，也不设全局默认。
    """
    band = str(tau_band)
    ref = get_reference_status()
    if band == TAU_BAND_MAIN:
        if tau_analysis is None:
            raise ValueError("主档（main_declared）必须有数值 τ：运行口径声明缺失")
        tau_cents: float | None = float(tau_analysis)
        tau_status = TAU_STATUS_DECLARED_UNCALIBRATED
    else:
        decl = tau_declaration()
        tau_cents = decl["tau_cents"]
        tau_status = decl["tau_status"]
    block = counts_block(
        rows, tau_cents=tau_cents,
        criterion_window_frames=int(criterion_window_frames or 0),
    )
    payload = {
        "format": DISTRIBUTION_FORMAT,
        "version": DISTRIBUTION_VERSION,
        "run_id": run_id_,
        "recording_id": str(recording_id),
        "ref_mode": str(ref_mode),
        "tau_band": band,
        "tau_cents": tau_cents,
        "tau_status": tau_status,
        "tau_analysis": None if tau_analysis is None else float(tau_analysis),
        "tau_provenance": str(tau_provenance),
        "calibration_note": CALIBRATION_NOTE,
        "segment_source": dict(segment_source or segment_source_snapshot()),
        **block,
        "counts_denominator": DENOMINATOR_POLICY,
        "n_segments": int(block["n_all"]),
        "label_gloss": dict(LABEL_GLOSS),
        "ref_mode_gloss": dict(REF_MODE_GLOSS),
        "reference_hz": ref["reference_hz"],
        "reference_status": ref["reference_status"],
        "reference": ref,
        "tau_bands_present": [TAU_BAND_MAIN, TAU_BAND_CONTROL],
    }
    if provenance is not None:
        payload["provenance"] = dict(provenance)
    return payload


# ---------------------------------------------------------------------------
# τ 敏感性扫描（T-2）
# ---------------------------------------------------------------------------


def tau_sweep_payload(
    rows: Sequence[Mapping],
    *,
    tau_values: Iterable[float | None] = DEFAULT_TAU_VALUES,
    recording_id: str = "",
    ref_mode: str = REF_ABSOLUTE,
    segment_source: Mapping | None = None,
    run_id_: str | None = None,
) -> dict:
    """对一批段行扫 τ 区间，输出判定翻转清单（T-2）。

    返回 ``{"tau_values", "tau_status_by_tau", "labels_by_tau", "flips",
    "flip_count", "flip_rate", "flip_direction_counts", "n_segments", …}``：

    - ``labels_by_tau``：逐 τ 的逐段标签（键为 :func:`tau_key`）；
    - ``flips``：逐条记 ``{segment_id, tau_from, tau_to, label_from, label_to}``；
    - ``flip_rate`` = ``flip_count / (n_segments × (n_τ − 1))``，即**相邻 τ 对 ×
      段**的翻转率（分母不含 τ 档数本身）；
    - ``flip_direction_counts``：翻转方向计数（如 ``平直→上趋``），按计数降序。

    τ 值由调用方给定用于**观察敏感性**，故其状态一律记 ``assumed_for_scan``；
    平台自身的标定态仍以 :func:`tau_declaration` 为准，二者**不得混称**。
    """
    taus = list(tau_values)
    labels_by_tau: dict[str, list[str]] = {}
    status_by_tau: dict[str, str] = {}
    flips: list[dict] = []
    prev_tau: float | None = None
    prev_labels: list[str] | None = None
    for tau in taus:
        labels = [classify_cavity_type(row, tau_cents=tau) for row in rows]
        labels_by_tau[tau_key(tau)] = labels
        status_by_tau[tau_key(tau)] = scan_tau_status(tau)
        if prev_labels is not None:
            for row, before, after in zip(rows, prev_labels, labels):
                if before != after:
                    flips.append(
                        {
                            "segment_id": row["segment_id"],
                            "tau_from": prev_tau,
                            "tau_to": tau,
                            "label_from": before,
                            "label_to": after,
                        }
                    )
        prev_tau, prev_labels = tau, labels

    n_seg = int(len(rows))
    slots = n_seg * max(len(taus) - 1, 0)
    directions: dict[str, int] = {}
    for flip in flips:
        key = f"{flip['label_from']}→{flip['label_to']}"
        directions[key] = directions.get(key, 0) + 1
    ordered = dict(sorted(directions.items(), key=lambda kv: (-kv[1], kv[0])))
    ref = get_reference_status()
    return {
        "format": SWEEP_FORMAT,
        "version": SWEEP_VERSION,
        "run_id": run_id_,
        "recording_id": str(recording_id),
        "ref_mode": str(ref_mode),
        "tau_values": taus,
        "tau_status_by_tau": status_by_tau,
        "tau_declaration": tau_declaration(),
        "labels_by_tau": labels_by_tau,
        "flips": flips,
        "flip_count": int(len(flips)),
        "flip_rate": (len(flips) / slots) if slots else None,
        "flip_direction_counts": ordered,
        "n_segments": n_seg,
        "segment_source": dict(segment_source or segment_source_snapshot()),
        "label_gloss": dict(LABEL_GLOSS),
        "reference_hz": ref["reference_hz"],
        "reference_status": ref["reference_status"],
        "reference": ref,
        "note": (
            "τ 为扫描用假设值（assumed_for_scan）；平台标定态见 tau_declaration，"
            "未标定即按符号判，不得把扫描值当作标定结果引用。"
        ),
    }


def sweep_summary(sweeps: Sequence[Mapping], *, ref_mode: str = REF_ABSOLUTE,
                  run_id_: str | None = None) -> dict:
    """多例 τ 扫描的汇总件（T-2 汇总：``flip_rate`` 与主要翻转方向）。

    ``sweeps`` 为 :func:`tau_sweep_payload` 的返回值序列；输出 ``per_recording``
    逐例账与 ``totals`` 合计账，并给 ``dominant_flip_directions``（按计数降序的
    前三翻转方向，供论文写「翻转以…为主」这类限制句）。
    """
    per: list[dict] = []
    total_seg = 0
    total_flips = 0
    directions: dict[str, int] = {}
    for sweep in sweeps:
        counts = dict(sweep.get("flip_direction_counts") or {})
        for key, value in counts.items():
            directions[key] = directions.get(key, 0) + int(value)
        n_seg = int(sweep.get("n_segments", 0))
        n_flip = int(sweep.get("flip_count", 0))
        total_seg += n_seg
        total_flips += n_flip
        per.append(
            {
                "recording_id": sweep.get("recording_id", ""),
                "n_segments": n_seg,
                "flip_count": n_flip,
                "flip_rate": sweep.get("flip_rate"),
                "flip_direction_counts": counts,
            }
        )
    ordered = dict(sorted(directions.items(), key=lambda kv: (-kv[1], kv[0])))
    return {
        "format": SWEEP_SUMMARY_FORMAT,
        "version": SWEEP_VERSION,
        "run_id": run_id_,
        "ref_mode": str(ref_mode),
        "tau_values": list(next(iter(sweeps)).get("tau_values", ())) if sweeps else [],
        "per_recording": per,
        "totals": {
            "n_segments": int(total_seg),
            "flip_count": int(total_flips),
            "flip_rate": (total_flips / total_seg) if total_seg else None,
        },
        "flip_direction_counts": ordered,
        "dominant_flip_directions": list(ordered)[:3],
        "note": "flip_rate 分母＝段数 ×（τ 档数 − 1）（相邻 τ 对）；跨例合计非加权平均。",
    }


# ---------------------------------------------------------------------------
# 两口径配对（表 4-3 的「未配对段」）
# ---------------------------------------------------------------------------


def pair_segments(rows_a, rows_b, *, overlap_ratio: float = 0.5,
                  tau_cents: float | None = None) -> dict:
    """按时间重叠把两套段行配对（贪心：对每个 a 段取未用的最大重叠 b 段）。

    重叠率分母为 **a 段时长**，低于 ``overlap_ratio`` 即判未配对。返回
    ``{"matched", "unmatched_a", "unmatched_b", "type_flips", "pairs"}``：
    ``type_flips`` 记配对后标签改判的**方向计数**（如 ``平直→上趋``）。
    两口径各自分段 ⇒ 段界可随移调而移，故段数不必相等。

    ``tau_cents``：判型容差（``None`` = 取平台占位值，即按符号判）；主档改判
    明细须显式传入本次运行声明的 τ（W-1／W-2）。
    ``label_bands=True`` 时，明细数组另带 ````label_from``／``label_to`` 的
    逐对条目（见 :func:`pair_flip_detail`），此处保持向后兼容的键面不变。
    """
    used: set[int] = set()
    pairs: list[dict] = []
    flips: dict[str, int] = {}
    unmatched_a = 0
    tau = TAU_CENTS_PLACEHOLDER if tau_cents is None else float(tau_cents)
    for row_a in rows_a:
        a0, a1 = float(row_a["start_s"]), float(row_a["end_s"])
        best: int | None = None
        best_ov = 0.0
        for j, row_b in enumerate(rows_b):
            if j in used:
                continue
            b0, b1 = float(row_b["start_s"]), float(row_b["end_s"])
            ov = max(0.0, min(a1, b1) - max(a0, b0))
            if ov > best_ov:
                best, best_ov = j, ov
        dur_a = max(a1 - a0, 1e-9)
        if best is not None and best_ov / dur_a >= float(overlap_ratio):
            row_b = rows_b[best]
            used.add(best)
            label_a = classify_cavity_type(row_a, tau_cents=tau)
            label_b = classify_cavity_type(row_b, tau_cents=tau)
            if label_a != label_b:
                key = f"{label_a}→{label_b}"
                flips[key] = flips.get(key, 0) + 1
            pairs.append(
                {
                    "segment_id_a": row_a["segment_id"],
                    "segment_id_b": row_b["segment_id"],
                    "overlap_s": round(best_ov, 3),
                    "label_a": label_a,
                    "label_b": label_b,
                }
            )
        else:
            unmatched_a += 1
            pairs.append(
                {
                    "segment_id_a": row_a["segment_id"],
                    "segment_id_b": None,
                    "overlap_s": round(best_ov, 3),
                    "label_a": classify_cavity_type(row_a, tau_cents=tau),
                    "label_b": None,
                }
            )
    return {
        "matched": int(len(used)),
        "unmatched_a": int(unmatched_a),
        "unmatched_b": int(len(rows_b) - len(used)),
        "type_flips": dict(sorted(flips.items(), key=lambda kv: (-kv[1], kv[0]))),
        "pairs": pairs,
    }


# ---------------------------------------------------------------------------
# 图件分面数据（T-3：与表同源同 τ）
# ---------------------------------------------------------------------------


def panels_payload(rows_by_recording, *, tau_cents: float | None = None,
                   run_id_: str | None = None, ref_mode: str = REF_ABSOLUTE,
                   tau_band: str = TAU_BAND_CONTROL,
                   tau_status_: str | None = None,
                   tau_analysis: float | None = None,
                   criterion_window_frames=0,
                   provenance: Mapping | None = None) -> dict:
    """段行 → 图件分面数据（``{"panels": [{"label":…, "rows":[…]}], …}``）。

    ``rows_by_recording`` 为 ``[(label, rows)]``；每行输出
    ``{"segment_id", "cavity_type", "turns", "valid", "pp_cents", "rate_hz"}``，
    供 :func:`visualization.figures.type_oscillation_data` 直接消费。
    标签由**同一批段行**按平台声明的 τ 判出 ⇒ 与分布表逐格同源（T-3）；
    ``run_id`` 随件写入，图件因此可与表件对账。

    **W-8／W-10 同分母**：自本版起分面行只含**可判段**（``in_judgable``），
    与分布件 ``counts_per_recording`` 同一集合，故

    - 图 ``n_plotted`` ＝ 表 ``n_axis``（三型入图）；
    - 图 ``excluded`` ＝ 表 ``n_composite``（未入三型）；
    - 图 ``n_total`` ＝ 表四值之和 ＝ ``n_judgable``；
    - 不可判段与低频不可靠段**不入图**，逐面板另给计数与 ``segment_id`` 清单，
      供图注指到件面（``denominators``／``low_frequency_unreliable_segments``）。

    ``criterion_window_frames``：判据窗长；可传单个整数（全例同长）或
    ``{label: 帧数}`` 映射（各例 hop 不同时用）。缺省 0 ＝ 不做该诊断（向后兼容）。

    ``tau_band``／``tau_status_``：主档（``main_declared``）时显式传入运行口径
    声明值与状态，使图件与**主档**分布表同 τ（而非退回平台占位 τ）。
    """
    decl = tau_declaration()
    tau = decl["tau_cents"] if tau_cents is None else float(tau_cents)
    tau_status = decl["tau_status"] if tau_status_ is None else str(tau_status_)
    if str(tau_band) == TAU_BAND_MAIN and tau is None:
        raise ValueError("主档分面数据必须有数值 τ：运行口径声明缺失")

    def _criterion(label: str) -> int:
        if hasattr(criterion_window_frames, "get"):
            return int(criterion_window_frames.get(label, 0) or 0)
        return int(criterion_window_frames or 0)

    panels = []
    for label, rows in rows_by_recording:
        crit = _criterion(label)
        block = counts_block(
            rows, tau_cents=tau, criterion_window_frames=crit
        )
        panel_rows = []
        for row in rows:
            flags = classify_segment(
                row, criterion_window_frames=crit, tau_cents=tau
            )
            if not flags["in_judgable"]:
                continue
            panel_rows.append(
                {
                    "segment_id": row.get("segment_id", ""),
                    "cavity_type": classify_cavity_type(row, tau_cents=tau),
                    "turns": row.get("turns"),
                    "valid": row.get("turns_valid"),
                    "pp_cents": row.get("pp_cents"),
                    "rate_hz": row.get("rate_hz"),
                    "low_frequency_unreliable": bool(
                        flags["low_frequency_unreliable"]
                    ),
                    # W-14-02：段内状态与占比（只导出，不改判定/计数）
                    "state": row.get("state"),
                    "state_runs": row.get("state_runs"),
                    "dominant_state": row.get("dominant_state"),
                    "attack_ratio": row.get("attack_ratio"),
                    "stable_ratio": row.get("stable_ratio"),
                    "inter_ratio": row.get("inter_ratio"),
                    "segment_type_signal": row.get("segment_type_signal"),
                }
            )
        panels.append(
            {
                "label": label,
                "rows": panel_rows,
                "denominators": {
                    key: block[key]
                    for key in (
                        "n_all", "n_judgable", "n_axis", "n_composite",
                        "n_indeterminate", "n_low_freq_unreliable",
                        "n_denominator_body", "n_coexist",
                    )
                },
                "low_frequency_unreliable_segments": [
                    item["segment_id"] for item in low_frequency_segments(rows)
                ],
                "counts_per_recording": dict(block["counts_per_recording"]),
                "counts_per_recording_excluding_low_freq": dict(
                    block["counts_per_recording_excluding_low_freq"]
                ),
            }
        )
    payload = {
        "format": "acouscope-figure-panels",
        "version": DISTRIBUTION_VERSION,
        "run_id": run_id_,
        "ref_mode": str(ref_mode),
        "tau_band": str(tau_band),
        "tau_cents": tau,
        "tau_status": tau_status,
        "tau_analysis": None if tau_analysis is None else float(tau_analysis),
        "calibration_note": CALIBRATION_NOTE,
        "denominator_policy": DENOMINATOR_POLICY,
        "indeterminate_name_zh": INDETERMINATE_ZH,
        "indeterminate_rule_zh": INDETERMINATE_RULE_ZH,
        "indeterminate_note_zh": INDETERMINATE_NOTE_ZH,
        "low_frequency_class": LOW_FREQ_CLASS,
        "low_frequency_note_zh": LOW_FREQ_NOTE_ZH,
        "label_gloss": dict(LABEL_GLOSS),
        "panels": panels,
    }
    if provenance is not None:
        payload["provenance"] = dict(provenance)
    return payload


# ---------------------------------------------------------------------------
# 运行身份（内容定址）
# ---------------------------------------------------------------------------


def run_descriptor(
    *,
    inputs: Sequence[Mapping],
    segment_source: Mapping,
    tau_values: Iterable[float | None] = DEFAULT_TAU_VALUES,
    ref_modes: Iterable[str] = (REF_ABSOLUTE, REF_MAIN_TONE),
    params: Mapping | None = None,
    config: Mapping | None = None,
) -> dict:
    """一次运行的描述符（输入清单 × 参数面 × 分段快照 × τ／口径面）。

    **只含取数面**：不含任何读数结果，故同参同输入两次跑得同一 ``run_id``。
    ``inputs`` 每项含 ``recording_id``／``audio_name``／``sha256``／``frames``／
    ``samplerate``／``duration_s``／``anchor_offset_cents``／``anchor_source``。

    ``config``（W-7／T-14 口径面补登）：**机读口径面**，进 ``run_id`` 的内容
    定址。至少含 ``tonic_window_s``／``min_window_s``／``overlap_ratio``／
    ``smooth_k``／``min_thr``／``tau_analysis``／``fminfmax_variant``——上一轮
    这些维只写在 ``MANIFEST.md`` 的人读表格里，``run_id`` 未变即证其未入哈希面。
    """
    snap = analysis_params_snapshot() if params is None else dict(params)
    payload = {
        "format": RUN_DESCRIPTOR_FORMAT,
        "version": RUN_DESCRIPTOR_VERSION,
        "params_snapshot": snap,
        "segment_source": dict(segment_source),
        "tau_values": [tau_key(t) for t in tau_values],
        "ref_modes": [str(mode) for mode in ref_modes],
        "inputs": [dict(item) for item in inputs],
    }
    if config is not None:
        payload["config"] = dict(config)
    return payload


def run_id(descriptor: Mapping) -> str:
    """运行描述符 → ``run_id``（sha256 前 16 位十六进制；内容定址）。

    序列化取 ``sort_keys=True`` ＋ ``default=str``（浮点一律 ``repr``），
    故键序与浮点写法不影响结果；**时间戳不进入**描述符。
    """
    canonical = json.dumps(descriptor, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------


def export_json(path, payload: Mapping) -> Path:
    """payload → JSON（UTF-8，缩进 2，非 ASCII 原样）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    return target


def export_rows_csv(path, rows: Sequence[Mapping]) -> Path:
    """表格行 → CSV（UTF-8 with BOM；列序取首行键序）。"""
    import csv

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        target.write_text("", encoding="utf-8-sig")
        return target
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return target
