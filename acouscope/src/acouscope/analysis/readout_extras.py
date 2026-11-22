# SPDX-License-Identifier: GPL-3.0-only
"""丙案出件补项（W-1—W-7）的**纯函数**装配层：不跑音频、不落盘、不改判定。

本模块只回答一件事：**同一批段行**怎样才能把设计约定要求的读数**分列**出来，
而不把不同的量折进一个互斥字段。逐项对应：

- W-2（T-10）:func:`pair_flip_detail`——两口径改判**明细**与逐方向计数；
- W-3（T-11）:func:`counts_by_tau`／:func:`counts_by_tau_matrix`——各 τ 档四值计数；
- W-4（T-12）:func:`three_column_payload`——三栏并行布尔＋``indeterminate``
  ＋交叉表＋六个可核查分母量；
- W-6（T-14）:func:`grid_boundary_payload`——候选面与输出面**分列**的钳位读数；
- W-5（T-13）:func:`fminfmax_diff`——两档音域件的逐例差值（只读落盘件）；
- W-7（前置）:func:`run_config_block`——机读口径面（进 ``run_id`` 内容定址）。

**口径纪律（照设计约定，勿放宽）：**

- τ 的**主档**是「运行口径声明」，状态恒记
  ``run_config_declared_uncalibrated``（未经参考语料标定），**不冒充** ``calibrated``；
  对照档仍是平台占位（``None`` ⇒ 按符号判）；扫描档仍记 ``assumed_for_scan``。
- 三栏（类型／低置信／净平直—段内往复并见）**可重叠**，交集非零是正常结果；
  只有旧 ``flag`` 是互斥级联，本模块不改它、也不拿它当三栏。
- ``indeterminate``（不可判）**单列**，不折进「谓词不成立」，也不折进任何类别；
  六个分母量之和的自检恒等式随件给出（``n_axis + n_composite + n_indeterminate = n_all``）。
- 钳位读数**只由候选面**成立：``candidate_*`` 与 ``hmm_output_*`` 分列，不得以
  输出最小值反证候选在网格内。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .cavity_type import (
    LABEL_FLAT,
    LABEL_UNCLASSIFIED,
    LABELS,
    classify_cavity_type,
    classify_detail,
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
from .type_distribution import (
    CALIBRATION_NOTE,
    TAU_BAND_CONTROL,
    TAU_BAND_MAIN,
    TAU_STATUS_DECLARED_UNCALIBRATED,
    count_labels,
    pair_segments,
    scan_tau_status,
    tau_declaration,
    tau_key,
)

__all__ = [
    "COEXIST_MIN_TURNS",
    "EDGE_WINDOW_S",
    "GRID_MIN_HZ",
    "LOW_CONF_THRESHOLD",
    "PRIORITY_NOTE",
    "counts_by_tau",
    "counts_by_tau_matrix",
    "fminfmax_diff",
    "fminfmax_variant_tag",
    "grid_boundary_payload",
    "pair_flip_detail",
    "provenance_block",
    "run_config_block",
    "tau_band_declaration",
    "three_column_payload",
]

#: HMM 有效网格下界（``pitch_hmm.MIN_FREQ``；k=0 即 61.735 Hz）。
#: 候选低于此值的帧在装入观测时被钳到最低格（``pitch_hmm.observation``）。
GRID_MIN_HZ = 61.735

#: 低置信判据（T-12 交付口径）：段中位置信度 < 0.5 记低置信。
LOW_CONF_THRESHOLD = 0.5

#: 「体内 ≥2 次往复」判据（T-12）：往复度 v2（fixed 口径）``turns`` ≥ 2。
COEXIST_MIN_TURNS = 2

#: 头尾偏离的判据窗长（秒）：``note_hmm._edge_deviation_cents`` 的
#: ``min(0.10 s, 段长/3)``，至少 2 帧；本模块用 0.10 s 折帧数作「有效帧是否够窗」。
EDGE_WINDOW_S = 0.10

#: 旧互斥字段的优先级次序说明（T-12 要求随件给出；本文不指其为缺陷）。
PRIORITY_NOTE = (
    "旧 status 字段（ok／low_conf／unclassified）系互斥级联分派，优先级次序为 "
    "ok → 不可判 → 低置信 → 并见；本文不指其为缺陷，但它不能充当三个可并列变量。"
    "本件的 cavity_type／low_confidence／coexist_netflat_segturn 为**并行**量，"
    "四者（含 indeterminate）可任意重叠，交集非零属正常结果。"
)

#: 口径面里必须出现的键（W-7；缺一即视为补登未完成）
CONFIG_KEYS = (
    "tonic_window_s",
    "min_window_s",
    "overlap_ratio",
    "smooth_k",
    "min_thr",
    "tau_analysis",
    "fminfmax_variant",
)


def fminfmax_variant_tag(fmin: float, fmax: float) -> str:
    """音域档标记（W-5 交付字段 ``fminfmax_variant``）：``fmin60_fmax1500`` 形式。"""
    return f"fmin{float(fmin):g}_fmax{float(fmax):g}"


def run_config_block(
    *,
    window_s: float,
    min_window_s: float,
    fmin: float,
    fmax: float,
    segmenter: str,
    template: str,
    overlap_ratio: float,
    smooth_k: int,
    min_thr: float,
    tonic_window_s: float,
    tau_values: Sequence[float | None],
    tau_analysis: float | None,
    ref_modes: Sequence[str],
    anchors: Sequence[Mapping] = (),
    templates: Sequence[Mapping] | None = None,
    template_metadata: Sequence[Mapping] | None = None,
    reference: Mapping | None = None,
) -> dict:
    """机读**口径面**（W-7）：进 ``run_descriptor['config']``，即进 ``run_id``。

    与 ``MANIFEST.md`` 的人读表格**同值**，但机读面以本块为准；``fminfmax_variant``
    使两档音域件在描述符层面可判（W-5 的 B 项「两档除音域外还有别的参数漂移」
    因此可直接比对，而不是靠人读表格）。

    ``templates``（2026-10-31 加）：**逐例**音级归属参照系（仅当有例自带
    ``template`` 时传入，否则缺省 ``None`` ⇒ 不出现在配置块里，历史运行的
    run_id 因此不受影响）。逐例换参照系必须登记于此，否则 run_id 不随参照系变。
    """
    return {
        "window_s": float(window_s),
        "min_window_s": float(min_window_s),
        "fmin": float(fmin),
        "fmax": float(fmax),
        "fminfmax_variant": fminfmax_variant_tag(fmin, fmax),
        "segmenter": str(segmenter),
        "template": str(template),
        "overlap_ratio": float(overlap_ratio),
        "smooth_k": int(smooth_k),
        "min_thr": float(min_thr),
        "tonic_window_s": float(tonic_window_s),
        "tau_values": [tau_key(t) for t in tau_values],
        "tau_analysis": None if tau_analysis is None else float(tau_analysis),
        "tau_analysis_status": (
            None if tau_analysis is None else TAU_STATUS_DECLARED_UNCALIBRATED
        ),
        "ref_modes": [str(m) for m in ref_modes],
        "anchors": [dict(item) for item in anchors],
        # 仅在确有逐例参照系时出现（缺省不出现 ⇒ 历史运行 run_id 不变）
        **(
            {"templates": [dict(item) for item in templates]}
            if templates
            else {}
        ),
        # W-14-05／06：模板来源面（全例；5 字段＋自定义音阶的 .scl 哈希）。
        # 与 templates 分键：后者形状由既有守卫锁定，本键承载来源与指纹。
        **(
            {"template_metadata": [dict(item) for item in template_metadata]}
            if template_metadata
            else {}
        ),
        "reference": dict(reference or {}),
        "grid_min_hz": float(GRID_MIN_HZ),
        "low_confidence_threshold": float(LOW_CONF_THRESHOLD),
        "coexist_min_turns": int(COEXIST_MIN_TURNS),
        "edge_window_s": float(EDGE_WINDOW_S),
        "calibration_note": CALIBRATION_NOTE,
        # W-8／W-9：分母口径与两类单列规则（换口径即换 run_id）
        "denominator_policy": DENOMINATOR_POLICY,
        "indeterminate_name": INDETERMINATE_ZH,
        "indeterminate_rule": INDETERMINATE_RULE_ZH,
        "low_frequency_class": LOW_FREQ_CLASS,
        "low_frequency_excluded_from_body_denominator": True,
    }


def tau_band_declaration(tau_analysis: float | None, provenance: str = "") -> dict:
    """双档（主档／对照档）的 τ 声明块（W-1 交付字段）。

    主档：``tau_cents`` 取声明值、``tau_status = run_config_declared_uncalibrated``、
    ``tau_provenance`` 记声明途径（如 ``cli --tau-analysis 10``）、
    ``calibration_note`` 为固定文案；对照档：``tau_cents = null``、
    ``tau_status = unspecified_sign_based``（平台占位，按符号判）。
    """
    decl = tau_declaration()
    main = {
        "tau_band": TAU_BAND_MAIN,
        "tau_analysis": None if tau_analysis is None else float(tau_analysis),
        "tau_cents": None if tau_analysis is None else float(tau_analysis),
        "tau_status": (
            TAU_STATUS_DECLARED_UNCALIBRATED if tau_analysis is not None else None
        ),
        "tau_provenance": str(provenance),
        "calibration_note": CALIBRATION_NOTE,
    }
    control = {
        "tau_band": TAU_BAND_CONTROL,
        "tau_analysis": None if tau_analysis is None else float(tau_analysis),
        "tau_cents": decl["tau_cents"],
        "tau_status": decl["tau_status"],
        "tau_provenance": "platform_placeholder:TAU_CENTS_PLACEHOLDER",
        "calibration_note": CALIBRATION_NOTE,
    }
    return {"main_declared": main, "control_sign_based": control}


def provenance_block(
    *,
    run_id_: str | None,
    run_config: Mapping,
    command: str,
    denominators: Mapping | None = None,
    extra: Mapping | None = None,
) -> dict:
    """溯源面（回执 §三.6）：每个交付件都要能把数标到具体运行。

    ``run_id`` ＋ ``run_config``（音域／τ 档／窗参数／平滑与迟滞阈值／模板／锚点）
    ＋ 六分母量（W-4）＋ 生成命令，缺一不可。
    """
    payload = {
        "run_id": run_id_,
        "run_config": dict(run_config),
        "command": str(command),
    }
    if denominators is not None:
        payload["denominators"] = dict(denominators)
    if extra is not None:
        payload.update(dict(extra))
    return payload


# ---------------------------------------------------------------------------
# W-2：两口径改判明细
# ---------------------------------------------------------------------------


def pair_flip_detail(
    rows_a: Sequence[Mapping],
    rows_b: Sequence[Mapping],
    *,
    tau_cents: float | None,
    overlap_ratio: float = 0.5,
    band: str = TAU_BAND_CONTROL,
) -> dict:
    """配对段逐对导出 ``label_from``／``label_to`` 与逐方向计数（W-2／T-10）。

    与 τ 扫描的 ``flip_rate`` **分母不同**，不得混用：

    - 本件 ``flip_rate_dual`` ＝ 翻转**配对段数** / **配对段数**（``matched``）；
    - sweep 件 ``flip_rate`` ＝ 翻转数 / (段数 × (τ 档数 − 1))。

    ``type_flips`` 为**明细数组**（可逐段回查），``type_flip_counts`` 为逐方向计数，
    恒有 ``Σ type_flip_counts == len(type_flips)``。
    """
    paired = pair_segments(
        rows_a, rows_b, overlap_ratio=float(overlap_ratio), tau_cents=tau_cents
    )
    flips: list[dict] = []
    for index, pair in enumerate(paired["pairs"]):
        label_from = pair["label_a"]
        label_to = pair["label_b"]
        if label_to is None or label_from == label_to:
            continue
        flips.append(
            {
                "pair_index": int(index),
                "segment_id_from": pair["segment_id_a"],
                "segment_id_to": pair["segment_id_b"],
                "overlap_s": pair["overlap_s"],
                "label_from": str(label_from),
                "label_to": str(label_to),
            }
        )
    counts: dict[str, int] = {}
    for flip in flips:
        key = f"{flip['label_from']}→{flip['label_to']}"
        counts[key] = counts.get(key, 0) + 1
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    matched = int(paired["matched"])
    return {
        "tau_band": str(band),
        "tau_cents": None if tau_cents is None else float(tau_cents),
        "type_flips": flips,
        "type_flip_counts": ordered,
        "flip_rate_dual": (len(flips) / matched) if matched else None,
        "flip_numerator": int(len(flips)),
        "flip_denominator": "matched_pairs",
        "matched_pairs": matched,
        "unpaired_segments": int(paired["unmatched_a"]),
        "unmatched_a": int(paired["unmatched_a"]),
        "unmatched_b": int(paired["unmatched_b"]),
        "n_absolute": int(len(rows_a)),
        "n_main_tone": int(len(rows_b)),
        "overlap_ratio": float(overlap_ratio),
        "direction_from": "absolute",
        "direction_to": "main_tone",
        "note": (
            "分母＝配对段数（matched），非 n_segments；与 τ 扫描的 flip_rate 不同分母，"
            "不得混用。Σ type_flip_counts 恒等于 type_flips 明细条数。"
        ),
    }


# ---------------------------------------------------------------------------
# W-3：各 τ 档的类别分布
# ---------------------------------------------------------------------------


def counts_by_tau(
    rows: Sequence[Mapping],
    *,
    tau_values: Iterable[float | None],
    mode: str = "absolute",
    criterion_window_frames: int = 0,
) -> dict:
    """单例单口径的各 τ 档四值计数＋逐档翻转数（W-3／T-11；W-8 同分母）。

    分母恒为该例该口径的**可判段**（``n_judgable``）：往复窗不可判的段不拿类型
    标签，故各档合计必相等且等于 ``n_judgable``（与分布件同分母，可逐格对拍）。
    每档随件记 ``tau_status``（``None`` 档 = 平台占位、数值档 = ``assumed_for_scan``）。
    """
    taus = list(tau_values)
    judgable = [
        row for row in rows
        if classify_segment(
            row, criterion_window_frames=int(criterion_window_frames),
            tau_cents=None,
        )["in_judgable"]
    ]
    labels_by_tau: dict[str, list[str]] = {}
    by_tau: dict[str, dict] = {}
    for tau in taus:
        key = tau_key(tau)
        labels = [classify_cavity_type(row, tau_cents=tau) for row in judgable]
        labels_by_tau[key] = labels
        block = counts_block(
            rows, tau_cents=tau,
            criterion_window_frames=int(criterion_window_frames),
        )
        counts = block["counts_per_recording"]
        by_tau[key] = {
            "tau_cents": None if tau is None else float(tau),
            "tau_status": scan_tau_status(tau),
            **{label: int(counts[label]) for label in LABELS},
            "合计": int(counts["合计"]),
            "分母定义": (
                "该例该口径的**可判段**（n_judgable = n_all − 往复窗不可判）；各档同分母"
            ),
            "n_judgable": int(block["n_judgable"]),
            "n_indeterminate": int(block["n_indeterminate"]),
        }
    n_base = len(judgable)
    flips_by_pair: dict[str, dict] = {}
    for prev, cur in zip(taus, taus[1:]):
        prev_key, cur_key = tau_key(prev), tau_key(cur)
        changed = [
            row["segment_id"]
            for row, before, after in zip(judgable, labels_by_tau[prev_key], labels_by_tau[cur_key])
            if before != after
        ]
        flips_by_pair[f"{prev_key}→{cur_key}"] = {
            "n_flip_segments": int(len(changed)),
            "n_segments": int(n_base),
            "flip_rate": (len(changed) / n_base) if n_base else None,
            "segment_ids": changed,
        }
    return {
        "ref_mode": str(mode),
        "tau_values": [None if t is None else float(t) for t in taus],
        "counts_by_tau": by_tau,
        "flip_counts_by_tau": flips_by_pair,
        "denominator_definition": (
            "分母＝该例该口径的可判段（n_judgable = n_all − 往复窗不可判）；"
            "四值之和恒等于合计，且与分布件 counts_per_recording 逐格相同"
        ),
        "n_segments": int(len(rows)),
        "n_judgable": int(n_base),
        "n_indeterminate": int(len(rows) - n_base),
        "denominator_policy": DENOMINATOR_POLICY,
    }


def counts_by_tau_matrix(per_case: Sequence[Mapping]) -> dict:
    """跨例汇总矩阵（W-3：**例 × 口径 × 档 × 四值** ＋ 逐档翻转数）。

    ``per_case`` 每项形如 ``{"例", "recording_id", "by_ref_mode": {mode: counts_by_tau(...)}}``。
    本件只摆矩阵，不对「哪个阈值更合适」给建议（设计约定明令）。
    """
    matrix: list[dict] = []
    flips: list[dict] = []
    for case in per_case:
        for mode, block in dict(case.get("by_ref_mode") or {}).items():
            for key, counts in dict(block.get("counts_by_tau") or {}).items():
                matrix.append(
                    {
                        "例": case.get("例"),
                        "recording_id": case.get("recording_id"),
                        "ref_mode": mode,
                        "tau": key,
                        **{label: counts.get(label, 0) for label in LABELS},
                        "合计": counts.get("合计", 0),
                        "分母定义": counts.get("分母定义"),
                        "tau_status": counts.get("tau_status"),
                    }
                )
            for pair, flip in dict(block.get("flip_counts_by_tau") or {}).items():
                flips.append(
                    {
                        "例": case.get("例"),
                        "recording_id": case.get("recording_id"),
                        "ref_mode": mode,
                        "tau_pair": pair,
                        "n_flip_segments": flip.get("n_flip_segments"),
                        "n_segments": flip.get("n_segments"),
                        "flip_rate": flip.get("flip_rate"),
                    }
                )
    return {
        "format": "acouscope-counts-by-tau",
        "version": 1,
        "matrix": matrix,
        "flips_matrix": flips,
        "tau_values": sorted({row["tau"] for row in matrix}, key=_tau_sort_key),
        "denominator_definition": (
            "每格分母＝该例该口径全部段行数；同一例同一口径下各档合计恒相等。"
        ),
        "no_recommendation": (
            "本件只出完整矩阵（例 × 口径 × 档 × 四值 ＋ 逐段翻转数），"
            "不就「哪个阈值更合适」给建议。"
        ),
    }


def _tau_sort_key(key: str) -> tuple[int, float]:
    """τ 键排序：``None`` 档最前，其余按数值升序。"""
    if str(key) == "None":
        return (0, 0.0)
    try:
        return (1, float(key))
    except (TypeError, ValueError):
        return (2, 0.0)


# ---------------------------------------------------------------------------
# W-4：三栏并行布尔、不可判单列、交叉表与六分母量
# ---------------------------------------------------------------------------


def _read(row: Mapping, key: str) -> float | None:
    """读一个可能缺省的浮点字段（None／空／非数 ⇒ None）。"""
    raw = row.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def three_column_payload(
    rows: Sequence[Mapping],
    *,
    tau_cents: float | None,
    criterion_window_frames: int,
    mode: str = "absolute",
    tau_band: str = TAU_BAND_CONTROL,
    tau_status: str | None = None,
) -> dict:
    """段级三栏并行布尔＋``indeterminate``＋交叉表＋六分母量（W-4／T-12）。

    三栏（**并行、可重叠**）：

    1. ``cavity_type``：四值（上趋／下趋／平直／未分类＝复合型），按本件 τ 判；
    2. ``low_confidence``：段中位置信度 < 0.5（``confidence_band`` 另给三态）；
    3. ``coexist_netflat_segturn``：``|tail − head| ≤ τ``（净平直）**且**
       ``turns ≥ 2``（体内往复）**且** 往复度有效。

    ``indeterminate``（不可判，**单列不折入任何类别**）：头或尾偏离不可得
    （``None``），**或**段内有效帧数 < 判据窗长（0.10 s 折帧数）。

    六分母量：``n_all``／``n_judgable``／``n_axis``／``n_composite``／
    ``n_indeterminate``／``n_coexist``；恒等式
    ``n_axis + n_composite + n_indeterminate == n_all`` 随件自检（``identity_check``）。
    """
    items: list[dict] = []
    cross: dict[tuple[str, str, bool], int] = {}
    n_indeterminate = 0
    n_axis = 0
    n_composite = 0
    n_coexist = 0
    for row in rows:
        label = classify_cavity_type(row, tau_cents=tau_cents)
        detail = classify_detail(row, tau_cents=tau_cents)
        head = _read(row, "head_deviation_cents")
        tail = _read(row, "tail_deviation_cents")
        conf = _read(row, "conf")
        turns = _read(row, "turns")
        turns_valid = bool(row.get("turns_valid"))
        n_valid = _read(row, "n_valid_frames")
        net_diff = None if (head is None or tail is None) else float(tail - head)
        net_flat = bool(net_diff is not None and _within(net_diff, tau_cents))
        seg_turns = int(turns) if turns is not None else None
        coexist = bool(
            net_flat
            and seg_turns is not None
            and seg_turns >= COEXIST_MIN_TURNS
            and turns_valid
        )
        if conf is None:
            confidence_band = "conf_missing"
        elif conf < LOW_CONF_THRESHOLD:
            confidence_band = "low_conf"
        else:
            confidence_band = "high_conf"
        low_conf: bool | None = None if conf is None else bool(conf < LOW_CONF_THRESHOLD)
        edge_missing = head is None or tail is None
        flags = classify_segment(
            row, criterion_window_frames=int(criterion_window_frames),
            tau_cents=tau_cents,
        )
        short_frames = bool(flags["recurrence_window_insufficient"])
        # 「往复窗不可判」自 W-8 起只由帧数判（头尾偏离不可得另记，不并入该类）
        indeterminate = short_frames
        n_indeterminate += int(indeterminate)
        if not indeterminate:
            if label == LABEL_UNCLASSIFIED:
                n_composite += 1
            else:
                n_axis += 1
        n_coexist += int(coexist)
        # W-8：往复窗不可判的段**不再拿类型标签**（原标签留作 label_if_type_applied，
        # 仅供回查，不参与任何计数），交叉表里单列为一类
        key = (
            INDETERMINATE_ZH if indeterminate else label,
            confidence_band,
            coexist,
        )
        cross[key] = cross.get(key, 0) + 1
        items.append(
            {
                "segment_id": row.get("segment_id"),
                "ref_mode": str(mode),
                "cavity_type": None if indeterminate else label,
                "label_if_type_applied": label,
                "counts_in_type_distribution": not indeterminate,
                "low_confidence": low_conf,
                "confidence": None if conf is None else round(float(conf), 4),
                "confidence_band": confidence_band,
                "coexist_netflat_segturn": coexist,
                "indeterminate": indeterminate,
                "recurrence_window_insufficient": indeterminate,
                "indeterminate_reason": (
                    None
                    if not indeterminate
                    else (
                        "edge_deviation_missing"
                        if edge_missing
                        else "insufficient_valid_frames"
                    )
                ),
                "low_frequency_unreliable": bool(
                    flags["low_frequency_unreliable"]
                ),
                "in_judgable": bool(flags["in_judgable"]),
                "in_denominator_body": bool(flags["in_denominator_body"]),
                "net_diff_cents": None if net_diff is None else round(net_diff, 3),
                "net_flat_within_tau": net_flat,
                "turns": seg_turns,
                "turns_valid": turns_valid,
                "n_valid_frames": None if n_valid is None else int(n_valid),
                "criterion_window_frames": int(criterion_window_frames),
                "head_deviation_cents": head,
                "tail_deviation_cents": tail,
                "head_vote": detail["head_vote"],
                "tail_vote": detail["tail_vote"],
                "composite": bool(detail["composite"]),
            }
        )
    block = counts_block(
        rows, tau_cents=tau_cents,
        criterion_window_frames=int(criterion_window_frames),
    )
    cross_rows = [
        {
            "cavity_type": label,
            "confidence_band": band,
            "coexist_netflat_segturn": bool(coexist),
            "n": int(count),
        }
        for (label, band, coexist), count in sorted(
            cross.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])
        )
    ]
    coexist_low_conf = sum(
        int(item["coexist_netflat_segturn"]) for item in items
        if item["confidence_band"] == "low_conf"
    )
    return {
        "ref_mode": str(mode),
        "tau_band": str(tau_band),
        "tau_cents": None if tau_cents is None else float(tau_cents),
        "tau_status": tau_status,
        "criterion_window_frames": int(criterion_window_frames),
        "denominator_policy": DENOMINATOR_POLICY,
        "counts_per_recording": dict(block["counts_per_recording"]),
        "counts_per_recording_excluding_low_freq": dict(
            block["counts_per_recording_excluding_low_freq"]
        ),
        "denominators": {
            key: block[key]
            for key in (
                "n_all", "n_judgable", "n_axis", "n_composite",
                "n_indeterminate", "n_high_conf", "n_low_conf",
                "n_conf_missing", "n_coexist",
                "n_low_freq_unreliable", "n_denominator_body",
            )
        },
        "identity_checks": list(block["identity_checks"]),
        "identity_check": list(block["identity_checks"])[0],
        "indeterminate_name_zh": INDETERMINATE_ZH,
        "indeterminate_rule_zh": INDETERMINATE_RULE_ZH,
        "indeterminate_note_zh": INDETERMINATE_NOTE_ZH,
        "low_frequency_class": LOW_FREQ_CLASS,
        "low_frequency_note_zh": LOW_FREQ_NOTE_ZH,
        "low_frequency_unreliable_segments": low_frequency_segments(rows),
        "low_confidence_count": int(block["n_low_conf"]),
        "criteria": {
            "cavity_type": (
                "上趋／下趋／平直／未分类（复合型）四值，按 cavity_type.classify_detail "
                "的成文规则；τ 取本件声明档（主档 = 运行口径声明，未经参考语料标定）；"
                "分母为**可判段**（n_judgable），往复窗不可判的段不拿类型标签"
            ),
            "low_confidence": f"段中位置信度 < {LOW_CONF_THRESHOLD}（阈值来源：本运行取数面）",
            "coexist_netflat_segturn": (
                f"|tail_deviation − head_deviation| ≤ τ（净平直）且 turns ≥ "
                f"{COEXIST_MIN_TURNS}（体内往复）且往复度有效（rate ≤ 12 Hz）"
            ),
            "indeterminate": (
                f"「{INDETERMINATE_ZH}」：" + INDETERMINATE_RULE_ZH +
                f"（本运行判据窗长 = {int(criterion_window_frames)} 帧）"
            ),
            "low_frequency_unreliable": LOW_FREQ_NOTE_ZH,
            "threshold_sources": {
                "tau_cents": "运行口径声明（主档）／平台占位（对照档）",
                "hysteresis_min_thr": "取数面 min_thr（往复度迟滞阈值，单位音分）",
                "smooth_k": "取数面 smooth_k（往复度平滑窗，帧）",
                "confidence_low": f"{LOW_CONF_THRESHOLD}（低置信判据）",
                "edge_window_s": f"{EDGE_WINDOW_S}（头尾偏离判据窗）",
                "grid_min_hz": f"{GRID_MIN_HZ}（HMM 网格下界，低频不可靠判据）",
            },
        },
        "priority_note": PRIORITY_NOTE,
        "counts_cross": cross_rows,
        "coexist_and_low_conf": int(coexist_low_conf),
        "segments": items,
        "denominator_note": (
            "n_coexist 与其余各项均可重叠（并见不是互斥类）；各列之和不得当总段数使用。"
            "n_indeterminate 单列，不折入「谓词不成立」，也不折入任何类别；"
            "n_low_freq_unreliable 是低频不可靠段数（与 n_judgable 有重叠，"
            "正文比例分母应用 n_denominator_body）。"
        ),
    }


def _within(value: float, tau_cents: float | None) -> bool:
    """「净差在容差内」判据：τ 未声明（None）⇒ 只按符号判（|差| == 0 才算平）。"""
    if tau_cents is None:
        return abs(float(value)) == 0.0
    return abs(float(value)) <= float(tau_cents)


# ---------------------------------------------------------------------------
# W-6：网格边界钳位与频率范围分列
# ---------------------------------------------------------------------------


def grid_boundary_payload(
    *,
    recording_id: str,
    label: str = "",
    grid: Mapping,
    candidate: Mapping,
    output: Mapping,
    affected: Mapping,
    tau_cents: float | None,
    denominators: Mapping | None = None,
) -> dict:
    """候选面／输出面**分列**的钳位读数（W-6／T-14；W-9 低频不可靠类）。

    ``candidate`` 面的计数由 pYIN 候选自身给出（``stream_candidates`` 的
    ``candidate_*``），**不是**由输出最小值反推；``output`` 面只报解码输出。
    两面的范围各占一个键，禁止拿 ``hmm_output_range_hz`` 反证候选在网格内。

    ``denominators``（W-9）：``{ref_mode: {n_all, n_judgable, n_low_freq_unreliable,
    n_denominator_body}}``，用于把「低频不可靠段不入正文分母」写成可核的数；
    缺省则 ``denominator_impact`` 只给段清单不给比数。
    """
    frames_total = int(output.get("frames") or candidate.get("frames") or 0)
    below_frames = int(candidate.get("candidate_below_grid_min_frames") or 0)
    at_min_frames = int(output.get("output_at_grid_min_frames") or 0)
    voiced = int(output.get("voiced_frames") or 0)
    affected_total = sum(
        int(block.get("n_affected_segments") or 0) for block in (affected or {}).values()
    )
    reads_unreliable = bool(below_frames or at_min_frames)
    return {
        "recording_id": str(recording_id),
        "label": str(label),
        "tau_cents": None if tau_cents is None else float(tau_cents),
        "grid": {
            "min_hz": float(grid.get("min_hz", GRID_MIN_HZ)),
            "max_hz": grid.get("max_hz"),
            "pitch_bins": grid.get("pitch_bins"),
            "bins_per_semitone": grid.get("bins_per_semitone"),
            "bin_cents": grid.get("bin_cents"),
            "formula": "f_k = 61.735 × 2^(k/60)，k = 0…344",
            "clamp_rule": (
                "候选装入观测时 k = round(60·log2(f/61.735)) 后钳位于 [0, 344]"
                "（pitch_hmm.observation），故 f < 61.735 Hz 的候选一律落到最低格"
            ),
        },
        "candidate_face": {
            "frames": int(candidate.get("frames") or frames_total),
            "candidate_frames": int(candidate.get("candidate_frames") or 0),
            "candidate_count": int(candidate.get("candidate_count") or 0),
            "candidate_range_hz": [
                candidate.get("candidate_min_hz"),
                candidate.get("candidate_max_hz"),
            ],
            "grid_clamp_below_frames": below_frames,
            "grid_clamp_below_frame_share": (
                (below_frames / frames_total) if frames_total else None
            ),
            "grid_clamp_below_candidates": int(
                candidate.get("candidate_below_grid_min_count") or 0
            ),
        },
        "output_face": {
            "voiced_frames": voiced,
            "hmm_output_range_hz": [
                output.get("output_min_hz"),
                output.get("output_max_hz"),
            ],
            "output_at_grid_min_frames": at_min_frames,
            "output_at_grid_min_share_of_voiced": (
                (at_min_frames / voiced) if voiced else None
            ),
            "grid_freq_range_hz": [
                output.get("grid_freq_min_hz", GRID_MIN_HZ),
                output.get("grid_freq_max_hz"),
            ],
        },
        "affected_segments": dict(affected or {}),
        "n_affected_segments": int(affected_total),
        "low_frequency_unreliable_segments": {
            str(mode): {
                "n": int(block.get("n_affected_segments") or 0),
                "segment_ids": [
                    item.get("segment_id")
                    for item in (block.get("segments") or [])
                ],
                "segments": list(block.get("segments") or []),
            }
            for mode, block in dict(affected or {}).items()
        },
        "n_low_frequency_unreliable_segments": {
            str(mode): int(block.get("n_affected_segments") or 0)
            for mode, block in dict(affected or {}).items()
        },
        "excluded_from_denominators": True,
        "excluded_from_denominators_note": (
            "低频不可靠段不入**正文比例**的分母（W-9）：正文分母取 "
            "n_denominator_body = n_judgable − n_low_freq_unreliable；"
            "而 W-8 的四值分母 n_judgable 仍按设计约定 A 应见的算法（只减往复窗不可判），"
            "两者逐项命名、并陈于 denominator_impact。"
        ),
        "denominator_impact": {
            str(mode): {
                "n_all": (dict(block) or {}).get("n_all"),
                "n_judgable": (dict(block) or {}).get("n_judgable"),
                "n_low_freq_unreliable": (dict(block) or {}).get("n_low_freq_unreliable"),
                "n_denominator_body": (dict(block) or {}).get("n_denominator_body"),
            }
            for mode, block in dict(denominators or {}).items()
        },
        "reads_must_be_read_as": (
            "列两条路径交由人工决定：①扩网格（把 MIN_FREQ/n_semitones 纳入口径面后重跑）；"
            "②把受影响段数列为不可靠（单列计数，不并入任何类别）。"
            if reads_unreliable
            else "两档均无钳位（候选面无低于网格下界的帧，且无输出落在最低格）"
        ),
        "paths": [
            {
                "id": "expand_grid",
                "applies": reads_unreliable,
                "desc": "扩网格：把 HMM 下界纳入口径面（MIN_FREQ / n_semitones），重跑并换 run_id",
            },
            {
                "id": "mark_unreliable",
                "applies": reads_unreliable,
                "desc": "列为不可靠：受影响段单列计数，不并入腔格三型与往复度统计",
            },
        ],
        "note": (
            "candidate_range_hz 与 hmm_output_range_hz **分列**：后者不得用于反证前者"
            "在网格内；候选低于 61.735 Hz 的帧数由候选面原始计数给出。"
        ),
    }


# ---------------------------------------------------------------------------
# W-5：音域两档的逐例差值
# ---------------------------------------------------------------------------


def fminfmax_diff(base_dir, variant_dir) -> dict:
    """两档音域件的逐例差值（W-5／T-13）——只读落盘件，不重算。

    读三个件：``counts_by_tau_summary.json``（四值分布）、
    ``three_column_summary.json``（低置信／并见）、``dual_calibre_pairing.json``
    （配对段数与未配对段）。差值逐例列明；若两档除音域外还有参数漂移，
    ``params_identical_except_audio_range`` 判 ``false``（对应设计约定 W-5 的 B 项）。
    """
    base = _load_json(Path(base_dir) / "counts_by_tau_summary.json")
    var = _load_json(Path(variant_dir) / "counts_by_tau_summary.json")
    base_three = _load_json(Path(base_dir) / "three_column_summary.json")
    var_three = _load_json(Path(variant_dir) / "three_column_summary.json")
    base_pair = _load_json(Path(base_dir) / "dual_calibre_pairing.json")
    var_pair = _load_json(Path(variant_dir) / "dual_calibre_pairing.json")
    base_desc = _load_json(Path(base_dir) / "run_descriptor.json")
    var_desc = _load_json(Path(variant_dir) / "run_descriptor.json")

    def config_of(desc: Mapping) -> dict:
        return dict(desc.get("config") or {})

    base_cfg, var_cfg = config_of(base_desc), config_of(var_desc)
    drift = {
        key: {"base": base_cfg.get(key), "variant": var_cfg.get(key)}
        for key in sorted(set(base_cfg) | set(var_cfg))
        if key not in ("fmin", "fmax", "fminfmax_variant") and base_cfg.get(key) != var_cfg.get(key)
    }

    base_tau = {
        (row["recording_id"], row["ref_mode"], row["tau"]): row
        for row in base.get("matrix") or []
    }
    base_pair_by_id = {row["recording_id"]: row for row in base_pair}
    var_pair_by_id = {row["recording_id"]: row for row in var_pair}
    base_three_by_id = _denominators_by_case(base_three)
    var_three_by_id = _denominators_by_case(var_three)

    per_case: dict[str, dict] = {}
    for row in var.get("matrix") or []:
        rid = str(row["recording_id"])
        case = per_case.setdefault(
            rid, {"recording_id": rid, "例": row.get("例"), "cells": []}
        )
        base_row = base_tau.get((rid, row.get("ref_mode"), row.get("tau"))) or {}
        case["cells"].append(_cell_delta(base_row, row))
    for rid, case in per_case.items():
        case["matched_pairs"] = {
            "base": int((base_pair_by_id.get(rid) or {}).get("配对段数") or 0),
            "variant": int((var_pair_by_id.get(rid) or {}).get("配对段数") or 0),
        }
        case["unpaired_segments"] = {
            "base": int((base_pair_by_id.get(rid) or {}).get("未配对段") or 0),
            "variant": int((var_pair_by_id.get(rid) or {}).get("未配对段") or 0),
        }
        case["low_confidence"] = {
            "base": int((base_three_by_id.get(rid) or {}).get("absolute_low_conf") or 0),
            "variant": int((var_three_by_id.get(rid) or {}).get("absolute_low_conf") or 0),
        }
        case["coexist"] = {
            "base": int(
                ((base_three_by_id.get(rid) or {}).get("absolute") or {}).get("n_coexist") or 0
            ),
            "variant": int(
                ((var_three_by_id.get(rid) or {}).get("absolute") or {}).get("n_coexist") or 0
            ),
        }
    return {
        "format": "acouscope-fminfmax-variant",
        "version": 1,
        "fminfmax_variant": {
            "base": base_cfg.get("fminfmax_variant"),
            "variant": var_cfg.get("fminfmax_variant"),
            "base_range_hz": [base_cfg.get("fmin"), base_cfg.get("fmax")],
            "variant_range_hz": [var_cfg.get("fmin"), var_cfg.get("fmax")],
        },
        "run_ids": {"base": base_desc.get("run_id"), "variant": var_desc.get("run_id")},
        "params_identical_except_audio_range": not drift,
        "param_drift": drift,
        "per_recording": list(per_case.values()),
        "delta_definition": (
            "Δ ＝ 变体档（fmin/fmax 第二档）− 基线档；四值取 τ=None 对照档与主档各一列，"
            "分母为**可判段**（n_judgable；W-8 后的 counts_by_tau 矩阵，四值之和即该值）；"
            "低置信数／并见数取该例 absolute 口径（W-4 件）。"
        ),
    }


def _denominators_by_case(summary: Mapping) -> dict:
    """``three_column_summary.json`` → ``{recording_id: {...}}``（低置信／并见等）。"""
    out: dict[str, dict] = {}
    for case in summary.get("per_recording") or []:
        rid = str(case.get("recording_id"))
        entry = out.setdefault(rid, {})
        for mode, block in dict(case.get("by_ref_mode") or {}).items():
            entry[mode] = dict(block.get("denominators") or {})
            entry[f"{mode}_low_conf"] = int(block.get("low_confidence_count") or 0)
    return out


def _cell_delta(base_row: Mapping, var_row: Mapping) -> dict:
    """单格（例 × 口径 × τ 档）两档差值：四值计数与**可判段**数（W-5 四值列）。

    分母自 W-8 起为 ``n_judgable``（``合计`` 即四值之和），故键名用 ``n_judgable``
    而不再叫 ``n_segments``，避免与「全部段」混读。
    """
    labels = list(LABELS)
    return {
        "ref_mode": var_row.get("ref_mode"),
        "tau": var_row.get("tau"),
        "n_judgable": {
            "base": int(base_row.get("合计") or 0),
            "variant": int(var_row.get("合计") or 0),
            "delta": int(var_row.get("合计") or 0) - int(base_row.get("合计") or 0),
        },
        "n_segments": {
            "base": int(base_row.get("合计") or 0),
            "variant": int(var_row.get("合计") or 0),
            "delta": int(var_row.get("合计") or 0) - int(base_row.get("合计") or 0),
        },
        "counts": {
            "base": {label_: int(base_row.get(label_) or 0) for label_ in labels},
            "variant": {label_: int(var_row.get(label_) or 0) for label_ in labels},
            "delta": {
                label_: int(var_row.get(label_) or 0) - int(base_row.get(label_) or 0)
                for label_ in labels
            },
        },
    }


def _load_json(path: Path) -> dict:
    """读 JSON 件；缺件即报错（不静默当 0）。"""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"缺件，无法比对：{target}")
    return json.loads(target.read_text(encoding="utf-8"))
