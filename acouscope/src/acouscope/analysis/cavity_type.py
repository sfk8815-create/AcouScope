# SPDX-License-Identifier: GPL-3.0-only
"""腔格类型学检验件（B3-01 / PI-P5 第 2 棒）。

对象与边界（本模块自述，勿自行放宽）：
- 本模块是**类型学检验件**，分类器只是副产品：对外主产物是四项读数
  （① 一致率与不确定带／② 复合型与「未分类」占比／③ 失效边界清单／
  ④ 跨录音、跨艺人稳定性）。①④ 只交计算函数 + 输入 schema，缺数据时
  ``value=None`` + ``status="machine_ready_data_pending"``——机器就绪、读数待数据，
  **不虚构读数、不以合成数据冒充专家判定**。
- 分类按**成文规则**判定（禁概率、禁聚类、禁隐层阈值学习）。规则出处：
  沈洽《音腔论》（2019）第三章 p.37 的「上趋／下趋／平直」三分表述。
- **基准 = 段内 f0 中位数（操作化代理）**：以段中位作「腔腹」参照属工程代理，
  与沈洽「音腔」本体概念**不等同**；本模块据该代理只陈述「按段中位参照的
  偏离方向」，不作音腔本体判定，也不作「符合／覆盖标准」级宣称。
- Δh = 段内**首个** ``stable`` 运行的 head 偏离（``NoteSegment.head_deviation_cents``），
  Δt = **末个** ``stable`` 运行的 tail 偏离（``NoteSegment.tail_deviation_cents``），
  单位音分（正 = 高于段中位，负 = 低于段中位）。两字段在 note_hmm 构造期算定，
  本模块只消费，**不改** ``state_runs`` 结构。
- 上趋 ⟺ Δh < 0（段首低于段中位 ⇒ 由低向中上行）或 Δt > 0（段尾高于段中位
  ⇒ 由中上行至尾）；下趋 ⟺ Δh > 0 或 Δt < 0；两侧都无变化 ⇒ 平直；两侧倾向
  相反（一上一下）⇒ 复合，标 ``"未分类"`` 并留字段（``records`` 内的 votes）。
- τ（判「无变化」的音分容差）= :data:`TAU_CENTS_PLACEHOLDER`，**待 P2 标定**：
  本模块只出这一个占位常量，值 ``None`` = 未标定；未标定时按符号判（|Δ| > 0 才
  计有向），**不自设数值冒充标定结果**。
- 检验语料 = 古琴吟猱 ＋《二泉映月》两例；专家判定分**琴人／二胡演奏者两栏**
  （``qin_player`` / ``erhu_player``），不合并为「专家」一项。两例音频未到前
  只做机器与契约，不跑真语料。

纯函数、无 UI、不入项目文件。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Mapping, Sequence

import numpy as np

from .tonic_ref import REF_ABSOLUTE

__all__ = [
    "EXPERT_LABEL_SCHEMA",
    "EXPERT_ROLES",
    "LABELS",
    "LABEL_DOWN",
    "LABEL_FLAT",
    "LABEL_UNCLASSIFIED",
    "LABEL_UP",
    "STATE_ORDER",
    "STATUS_COMPUTED",
    "STATUS_PENDING",
    "TAU_CENTS_PLACEHOLDER",
    "cavity_type_report",
    "classify_cavity_type",
    "classify_detail",
    "repeat_degree",
    "repeat_degree_v2",
    "segment_features",
    "tau_sweep",
]

#: 「无变化」容差 τ（音分）——**待 P2 标定**。None = 未标定，按符号判。
#: 禁自设数值：标定须由 P2 依语料出具，本常量只作显式占位（勿在调用方另设默认值）。
TAU_CENTS_PLACEHOLDER: float | None = None

#: 三分标签（+ 复合者单列），与专家判定 label 枚举逐字一致
LABEL_UP = "上趋"
LABEL_DOWN = "下趋"
LABEL_FLAT = "平直"
LABEL_UNCLASSIFIED = "未分类"
LABELS: tuple[str, ...] = (LABEL_UP, LABEL_DOWN, LABEL_FLAT, LABEL_UNCLASSIFIED)

#: 两栏角色（不合并）
ROLE_QIN = "qin_player"
ROLE_ERHU = "erhu_player"
EXPERT_ROLES: tuple[str, ...] = (ROLE_QIN, ROLE_ERHU)

#: 读数状态标记
STATUS_COMPUTED = "computed"
STATUS_PENDING = "machine_ready_data_pending"

#: 专家判定行 schema（字段级；缺数据时随读数①输出供后续填充）
EXPERT_LABEL_SCHEMA: dict[str, str] = {
    "subject_id": "str｜主体匿名 id（琴人／二胡演奏者各一栏，禁合并为「专家」）",
    "role": f"str｜{ROLE_QIN}（琴人）| {ROLE_ERHU}（二胡演奏者）",
    "recording_id": "str｜录音 id（读数③④按此聚合跨录音/跨艺人）",
    "segment_id": "str｜腔格段 id（= segment_features() 的 segment_id，起讫秒三位小数）",
    "label": f"str｜'上趋' | '下趋' | '平直' | '未分类'",
    "note": "str｜自由备注（可为空串）",
}

_EXPERT_FIELDS: tuple[str, ...] = tuple(EXPERT_LABEL_SCHEMA)


# ---------------------------------------------------------------------------
# 段级特征与单段判定
# ---------------------------------------------------------------------------


def _segment_id(start_s: float, end_s: float) -> str:
    """腔格段 id：段起讫秒三位小数（专家判定行按此对齐，确定性可复核）。"""
    return f"{float(start_s):.3f}-{float(end_s):.3f}"


#: 段内状态名与并列时的固定序（W-14-02；**只输出这三态**，不做腔头/腔腹/腔尾映射）
STATE_ORDER: tuple[str, ...] = ("attack", "stable", "inter")


def _state_frame_counts(runs) -> dict[str, int]:
    """``state_runs`` → 各状态帧数（帧数按 run 的 [起帧, 讫帧] 闭区间计）。"""
    counts = {name: 0 for name in STATE_ORDER}
    for run in runs or ():
        if len(run) != 5:
            continue
        name = str(run[4])
        counts[name] = counts.get(name, 0) + int(run[1]) - int(run[0]) + 1
    return counts


def _dominant_state(counts: dict[str, int]) -> str | None:
    """段内帧数最多的状态；并列按 attack→stable→inter 固定序（W-14-02）。"""
    best: str | None = None
    best_count = -1
    for name in STATE_ORDER:
        value = int(counts.get(name, 0))
        if value > best_count:
            best, best_count = name, value
    if best_count <= 0:
        return None
    return best


def segment_features(model) -> list[dict]:
    """把音高网格模型（``PitchGridModel`` 或含 ``notes`` 的同类对象）展成段级特征行。

    行键：``segment_id``（起讫秒三位小数）、``start_s``、``end_s``、``f0_hz``、
    ``degree_index``、``degree_deviation_cents``、``head_deviation_cents``、
    ``tail_deviation_cents``、``ref_mode``。缺字段（旧数据／simple 分段）一律 None，
    禁回退 0.0。空模型 ⇒ 空列表（诚实可判据）。

    **W-14-02 段内状态导出**（只导出，不改 HMM／Viterbi 与三型判定）：

    - ``state``：与 ``NoteSegment.state`` **逐字相同**（无 state_runs ⇒ None）；
    - ``state_runs``：原形制 list 化（``[起帧, 讫帧, 起秒, 讫秒, 态名]``）；
    - ``dominant_state``：段内帧数最多者，取值 ∈ ``{"attack","stable","inter"}``，
      并列按 :data:`STATE_ORDER` 固定序；
    - ``attack_ratio``／``stable_ratio``／``inter_ratio``：分母＝段内**总帧数**
      （三态之和），三者之和 = 1（±1e-6）；无帧 ⇒ 全 None（**禁 0 回填**）；
    - ``segment_type_signal``：＝ ``dominant_state``（检索用信号）；
      **不得**映射为腔头／腔腹／腔尾（那是另一理论问题，本模块不做）。

    ``ref_mode`` 标明该行音级字段的口径：模型由 ``build_pitch_grid`` 的 A4 校准路径
    填出的音级即 ``absolute``（默认）；若模型自带 ``ref_mode`` 属性则以其为准，
    不得在两行之间混用两套口径（口径贯通见 ``analysis.tonic_ref``）。
    """
    ref_mode = str(getattr(model, "ref_mode", REF_ABSOLUTE))
    notes = list(getattr(model, "notes", None) or [])
    rows: list[dict] = []
    for note in notes:
        start_s = float(note.start_s)
        end_s = float(note.end_s)
        runs = tuple(getattr(note, "state_runs", ()) or ())
        counts = _state_frame_counts(runs) if runs else {}
        total = int(sum(counts.values())) if counts else 0
        dominant = _dominant_state(counts) if total > 0 else None
        ratios = {
            name: (None if total <= 0 else round(counts.get(name, 0) / total, 6))
            for name in STATE_ORDER
        }
        rows.append(
            {
                "segment_id": _segment_id(start_s, end_s),
                "start_s": start_s,
                "end_s": end_s,
                "ref_mode": ref_mode,
                "f0_hz": float(getattr(note, "f0_hz", float("nan"))),
                "degree_index": getattr(note, "degree_index", None),
                "degree_deviation_cents": getattr(note, "degree_deviation_cents", None),
                "head_deviation_cents": getattr(note, "head_deviation_cents", None),
                "tail_deviation_cents": getattr(note, "tail_deviation_cents", None),
                # ---- W-14-02 段内状态/占比（只导出，不改判定）----
                "state": (None if not runs else (str(getattr(note, "state", "") or "") or None)),
                "state_runs": [list(run) for run in runs],
                "dominant_state": dominant,
                "attack_ratio": ratios["attack"],
                "stable_ratio": ratios["stable"],
                "inter_ratio": ratios["inter"],
                "segment_type_signal": dominant,
                "state_frames": {
                    "attack": int(counts.get("attack", 0)) if total else None,
                    "stable": int(counts.get("stable", 0)) if total else None,
                    "inter": int(counts.get("inter", 0)) if total else None,
                    "total": (total if total else None),
                },
            }
        )
    return rows


def _turn_count(vals) -> int:
    """连续同向反转次数（平滑 5 帧后去平台）；吟猱一周期约 2 次，单调为 0。"""
    if vals.size < 6:
        return 0
    k = min(5, vals.size)
    smooth = np.convolve(vals, np.ones(k) / k, mode="valid")
    d = np.sign(np.diff(smooth))
    d = d[d != 0]
    return int(np.count_nonzero(np.diff(d))) if d.size >= 2 else 0


def repeat_degree(model, f0) -> list[dict]:
    """往复度第二轴（描述量，**不参与三型判定**）。

    对每段取帧级 f0（与 head/tail 同源），输出 ``turns``（方向反转次数）与
    ``peak2peak_cents``（峰峰幅度）。三型仍只由 :func:`classify_cavity_type`
    按 Δh／Δt 与 τ 判定；本函数不产生标签、不改任何判定结果，也不新增类型。
    无 ``state_runs`` 或段内有效 f0 < 4 帧 ⇒ 两值 ``None``。
    """
    rows: list[dict] = []
    f0_arr = np.asarray(f0, dtype=float)
    for note in getattr(model, "notes", ()):
        row: dict = {
            "segment_id": _segment_id(note.start_s, note.end_s),
            "turns": None,
            "peak2peak_cents": None,
        }
        runs = getattr(note, "state_runs", ()) or ()
        if runs:
            i, j = int(runs[0][0]), int(runs[-1][1])
            vals = f0_arr[i : j + 1]
            vals = vals[np.isfinite(vals) & (vals > 0)]
            if vals.size >= 4:
                row["turns"] = _turn_count(vals)
                row["peak2peak_cents"] = round(
                    float(1200.0 * np.log2(vals.max() / vals.min())), 2
                )
        rows.append(row)
    return rows


def _hysteretic_turns_pos(vals, thr_cents: float):
    """迟滞计数核心：返回 (反转次数, 反转位置索引列表)。

    反转须自上一转折点起累计反向位移 >= thr 才计一次；同音内小幅抖动不计。
    """
    if vals.size < 3:
        return 0, []
    turns = 0
    pos: list[int] = []
    direction = 0
    anchor = float(vals[0])
    for idx, v in enumerate(vals[1:], 1):
        v = float(v)
        if direction >= 0:
            if v > anchor:
                anchor = v
            if anchor - v >= thr_cents:
                if direction == 1:
                    turns += 1
                    pos.append(idx)
                direction = -1
                anchor = v
                continue
        if direction == -1:
            if v < anchor:
                anchor = v
            if v - anchor >= thr_cents:
                turns += 1
                pos.append(idx)
                direction = 1
                anchor = v
    return turns, pos


def _hysteretic_turns(vals, thr_cents: float) -> int:
    """迟滞计数：压制 pYIN 帧间抖动（噪声级 ±16 音分），只计有效往复。"""
    return _hysteretic_turns_pos(vals, thr_cents)[0]


def _detrend_residual_cents(vals):
    n = vals.size
    x = np.arange(n, dtype=float)
    slope, icpt = np.polyfit(x, vals, 1)
    fit = slope * x + icpt
    if np.any(fit <= 0):
        return None
    return 1200.0 * np.log2(vals / fit)


def repeat_degree_v2(
    model, f0, *, mode: str = "fixed", smooth_k: int = 5, min_thr: float = 10.0
) -> list[dict]:
    """往复度第二轴（修正版）：迟滞计数 + 适度平滑 + 有效性闸。

    mode：
    - ``fixed``：迟滞阈值固定 ``min_thr``（默认 10 音分）；
    - ``adaptive``：阈值 = min(max(1.5 × 去趋势残差稳健标准差, ``min_thr``),
      max(0.5 × 稳健峰峰, ``min_thr``))
      ——k = 1.5（不取 3）；稳健标准差 = 1.4826 × MAD；稳健峰峰 = p95 − p5
      （不用极值，极值受单帧跳变支配）；双端 clamp 的**上限取 p95−p5 稳健量，
      不是合成输入的名义峰峰**，故合成 20 音分例的上限（10.38）可高于名义 10。
    ``smooth_k`` 限定 5–10 帧（约 60–120 ms），不得加长到 20 帧以上。
    反转率 > 12 Hz（半周期 < 40 ms）⇒ ``valid=False``（``osc_invalid``），
    该段不计入往复度统计，只单列段数。
    输出字段 ``pp_cents`` 为平滑后去趋势残差极差（图 A／甲-1 共用此口径）；
    ``pp_robust_cents`` 为同残差的 p95−p5，即 adaptive 上限所用的量。
    """
    if not 5 <= smooth_k <= 10:
        raise ValueError("smooth_k 须在 5–10 帧之间（不得加长到 20 帧以上）")
    rows: list[dict] = []
    f0_arr = np.asarray(f0, dtype=float)
    for note in getattr(model, "notes", ()):
        row = {
            "segment_id": _segment_id(note.start_s, note.end_s),
            "mode": mode,
            "smooth_k": smooth_k,
            "thr_cents": None,
            "turns": None,
            "pp_cents": None,
            "pp_robust_cents": None,
            "rate_hz": None,
            "valid": False,
        }
        runs = getattr(note, "state_runs", ()) or ()
        if runs:
            i, j = int(runs[0][0]), int(runs[-1][1])
            vals = f0_arr[i : j + 1]
            vals = vals[np.isfinite(vals) & (vals > 0)]
            if vals.size >= smooth_k + 2:
                sm = np.convolve(vals, np.ones(smooth_k) / smooth_k, mode="valid")
                sm_c = 1200.0 * np.log2(sm / float(np.median(sm)))
                if mode == "fixed":
                    thr = float(min_thr)
                else:
                    # 自适应（2026-10-25 约定）：k=1.5（不取 3）；
                    # 峰峰用稳健量 p95−p5（不用极值，极值受单帧跳变支配）；
                    # 双端 clamp：下限 min_thr 保噪声防护，上限 0.5×稳健峰峰保可计性。
                    res = _detrend_residual_cents(sm)
                    if res is None:
                        thr = float(min_thr)
                    else:
                        std = float(1.4826 * np.median(np.abs(res - np.median(res))))
                        pp_robust = float(np.percentile(res, 95) - np.percentile(res, 5))
                        upper = max(0.5 * pp_robust, float(min_thr))
                        thr = min(max(1.5 * std, float(min_thr)), upper)
                turns = _hysteretic_turns(sm_c, thr)
                dur = float(note.end_s - note.start_s)
                # 振荡频率（每周期 2 次反转）；闸门 12 Hz 即半周期 40 ms
                rate = turns / (2.0 * dur) if dur > 0 else 0.0
                res = _detrend_residual_cents(sm)
                row.update(
                    {
                        "thr_cents": round(thr, 2),
                        "turns": turns,
                        "pp_cents": None
                        if res is None
                        else round(float(res.max() - res.min()), 2),
                        "pp_robust_cents": None
                        if res is None
                        else round(
                            float(np.percentile(res, 95) - np.percentile(res, 5)), 2
                        ),
                        "rate_hz": round(rate, 2),
                        "valid": bool(rate <= 12.0),
                    }
                )
        rows.append(row)
    return rows


def _read(features, key: str) -> float | None:
    """从 Mapping 或对象读一个可能缺省的浮点字段（None/非有限 ⇒ None）。"""
    if isinstance(features, Mapping):
        raw = features.get(key)
    else:
        raw = getattr(features, key, None)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _beyond_tau(delta_cents: float | None, tau_cents: float | None) -> float | None:
    """Δ 是否超出「无变化」容差 τ：超出 ⇒ 原值（带符号），否则 None。

    τ = None（未标定）⇒ 只按符号判（|Δ| > 0 才计有向）；**不自设数值**。
    """
    if delta_cents is None or delta_cents == 0.0:
        return None
    if tau_cents is not None and abs(delta_cents) <= float(tau_cents):
        return None
    return delta_cents


def _head_vote(delta_h: float | None, tau_cents: float | None) -> str | None:
    """head 侧倾向：Δh < 0 ⇒ 上趋（由低向中上行）；Δh > 0 ⇒ 下趋。"""
    delta = _beyond_tau(delta_h, tau_cents)
    if delta is None:
        return None
    return LABEL_UP if delta < 0.0 else LABEL_DOWN


def _tail_vote(delta_t: float | None, tau_cents: float | None) -> str | None:
    """tail 侧倾向：Δt > 0 ⇒ 上趋（由中上行至尾）；Δt < 0 ⇒ 下趋。"""
    delta = _beyond_tau(delta_t, tau_cents)
    if delta is None:
        return None
    return LABEL_UP if delta > 0.0 else LABEL_DOWN


def classify_detail(features, tau_cents: float | None = None) -> dict:
    """单段判定明细（``classify_cavity_type`` 的留字段版）。

    返回 ``{"head_deviation_cents", "tail_deviation_cents", "tau_cents",
    "head_vote", "tail_vote", "composite", "label"}``：``composite=True`` 即两侧
    倾向相反（复合型），此时 ``label == "未分类"`` 而 votes 仍如实保留。
    """
    tau = TAU_CENTS_PLACEHOLDER if tau_cents is None else tau_cents
    delta_h = _read(features, "head_deviation_cents")
    delta_t = _read(features, "tail_deviation_cents")
    head_vote = _head_vote(delta_h, tau)
    tail_vote = _tail_vote(delta_t, tau)
    votes = [v for v in (head_vote, tail_vote) if v is not None]
    composite = len(set(votes)) > 1
    if not votes:
        label = LABEL_FLAT
    elif composite:
        label = LABEL_UNCLASSIFIED
    else:
        label = votes[0]
    return {
        "head_deviation_cents": delta_h,
        "tail_deviation_cents": delta_t,
        "tau_cents": tau,
        "head_vote": head_vote,
        "tail_vote": tail_vote,
        "composite": composite,
        "label": label,
    }


def classify_cavity_type(features, tau_cents: float | None = None) -> str:
    """按成文规则判定腔格走向标签（确定性，禁概率、禁聚类）。

    规则出处：沈洽《音腔论》（2019）第三章 p.37（上趋／下趋／平直三分）。
    输入 ``features`` 为 Mapping 或对象，至少含 ``head_deviation_cents`` /
    ``tail_deviation_cents``（音分，None = 该侧无 stable 运行）。

    判定（基准 = 段内 f0 中位数，**操作化代理**，与音腔本体不等同）：
    - head 侧：Δh < 0 ⇒ 上趋；Δh > 0 ⇒ 下趋（|Δh| ≤ τ 或 None ⇒ 该侧无倾向）；
    - tail 侧：Δt > 0 ⇒ 上趋；Δt < 0 ⇒ 下趋（同 τ 规则）；
    - 两侧倾向一致（或仅一侧有倾向）⇒ 该倾向标签；
    - 两侧倾向相反 ⇒ 判为复合，返回 ``"未分类"``（明细见 ``classify_detail``）；
    - 两侧都无倾向 ⇒ ``"平直"``。
    τ 取 :data:`TAU_CENTS_PLACEHOLDER`（**待 P2 标定**，None = 按符号判）。
    """
    return classify_detail(features, tau_cents=tau_cents)["label"]


# ---------------------------------------------------------------------------
# τ 扫描（读数③ 的可算部分）
# ---------------------------------------------------------------------------


def _tau_key(tau_cents: float | None) -> str:
    """τ 的 JSON 安全键（None = 未标定，按符号判）。"""
    return "None" if tau_cents is None else repr(float(tau_cents))


def tau_sweep(model, tau_values: Iterable[float | None]) -> dict:
    """对给定语料扫 τ 区间，输出判定翻转清单（读数③ 的可算部分）。

    返回 ``{"tau_values", "labels_by_tau", "flips", "flip_count",
    "unstable_segment_ids", "n_segments"}``：
    ``flips`` 逐条记 ``{segment_id, tau_from, tau_to, label_from, label_to}``
    ——即 τ 一变判定就翻的失效边界；``unstable_segment_ids`` 为翻转过的段 id
    去重升序（空清单 = 该 τ 区间内判定稳定，诚实可判据）。
    τ 值由调用方给定（本模块不自设标定值）。
    """
    rows = segment_features(model)
    taus = list(tau_values)
    labels_by_tau: dict[str, list[str]] = {}
    flips: list[dict] = []
    prev_tau: float | None = None
    prev_labels: list[str] | None = None
    for tau in taus:
        labels = [classify_cavity_type(row, tau_cents=tau) for row in rows]
        labels_by_tau[_tau_key(tau)] = labels
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
    return {
        "tau_values": taus,
        "labels_by_tau": labels_by_tau,
        "flips": flips,
        "flip_count": len(flips),
        "unstable_segment_ids": sorted({str(f["segment_id"]) for f in flips}),
        "n_segments": len(rows),
    }


# ---------------------------------------------------------------------------
# 读数①：一致率与不确定带（需专家两栏判定）
# ---------------------------------------------------------------------------


def _normalize_expert(expert) -> list[dict]:
    """专家判定行过滤：只留 schema 齐备且 label 在枚举内的行（其余丢弃，禁臆测补值）。"""
    rows: list[dict] = []
    for item in expert or []:
        if not isinstance(item, Mapping):
            continue
        if any(key not in item for key in _EXPERT_FIELDS):
            continue
        if item.get("label") not in LABELS:
            continue
        if item.get("role") not in EXPERT_ROLES:
            continue
        rows.append({key: item[key] for key in _EXPERT_FIELDS})
    return rows


def _agreement(records: Sequence[dict], expert_rows: Sequence[dict]) -> dict | None:
    """机器人判定 vs 专家判定的一致率（按 role 分栏；跨栏值仅作参照，禁合并解读）。"""
    machine = {row["segment_id"]: row["label"] for row in records}
    matched = [row for row in expert_rows if row["segment_id"] in machine]
    if not matched:
        return None
    by_role: dict[str, dict] = {}
    for role in EXPERT_ROLES:
        rows = [row for row in matched if row["role"] == role]
        if not rows:
            continue
        n_agree = sum(1 for row in rows if machine[row["segment_id"]] == row["label"])
        by_role[role] = {
            "n": len(rows),
            "n_agree": n_agree,
            "agreement": n_agree / len(rows),
        }
    n_agree = sum(1 for row in matched if machine[row["segment_id"]] == row["label"])
    return {
        "n": len(matched),
        "n_agree": n_agree,
        "agreement": n_agree / len(matched),
        "by_role": by_role,
    }


# ---------------------------------------------------------------------------
# 四项读数一次出齐
# ---------------------------------------------------------------------------


def cavity_type_report(
    model,
    expert: Sequence[Mapping] | None = None,
    tau_values: Iterable[float | None] | None = None,
) -> dict:
    """四项读数一次出齐（B3-01 检验件主产物）。

    ① 一致率与不确定带：需 ``expert``（琴人／二胡演奏者两栏，schema 见
       :data:`EXPERT_LABEL_SCHEMA`）；缺 ⇒ ``value=None`` +
       ``status="machine_ready_data_pending"``。不确定带同列 pending（带宽须随
       P2 标定给出，本模块不自设）。
    ② 复合型与「未分类」占比：纯函数可算（段数、逐标签计数、占比）。
    ③ 失效边界清单：τ 敏感翻转案例（可算，见 :func:`tau_sweep`）＋ 跨录音不稳
       （缺多录音 ⇒ sub-reading pending）。
    ④ 跨录音／跨艺人稳定性：需多录音多主体 ⇒ pending（只交算路与 schema）。
    ``tau_values`` 缺省 ⇒ 只按占位 τ（None，未标定）扫一档，翻转清单恒空。
    """
    records: list[dict] = []
    for row in segment_features(model):
        detail = classify_detail(row)
        records.append({**row, **detail})

    # ② 复合型与「未分类」占比
    n_segments = len(records)
    counts = Counter(row["label"] for row in records)
    share = {label: (counts[label] / n_segments if n_segments else 0.0) for label in LABELS}
    n_composite = sum(1 for row in records if row["composite"])
    reading2 = {
        "value": {
            "n_segments": n_segments,
            "counts": {label: counts[label] for label in LABELS},
            "share": share,
            "n_composite": n_composite,
            "share_composite": (n_composite / n_segments if n_segments else 0.0),
            "n_unclassified": counts[LABEL_UNCLASSIFIED],
            "share_unclassified": (
                counts[LABEL_UNCLASSIFIED] / n_segments if n_segments else 0.0
            ),
        },
        "status": STATUS_COMPUTED,
        "note": "纯函数可算：段数、逐标签计数与占比（复合者单列「未分类」）",
    }

    # ③ 失效边界清单：τ 翻转（可算）＋ 跨录音不稳（pending）
    sweep = tau_sweep(model, (TAU_CENTS_PLACEHOLDER,) if tau_values is None else tau_values)
    reading3 = {
        "tau_flips": {
            "value": sweep["flips"],
            "labels_by_tau": sweep["labels_by_tau"],
            "tau_values": sweep["tau_values"],
            "flip_count": sweep["flip_count"],
            "unstable_segment_ids": sweep["unstable_segment_ids"],
            "status": STATUS_COMPUTED,
        },
        "cross_recording_instability": {
            "value": None,
            "status": STATUS_PENDING,
            "note": "缺多录音 ⇒ 待数据（按 expert.recording_id 聚合后同名段判定是否翻）",
        },
        "status": "partial",
        "note": "τ 翻转可算；跨录音不稳待多录音落地",
    }

    # ① 一致率与不确定带
    expert_rows = _normalize_expert(expert)
    agreement = _agreement(records, expert_rows) if expert_rows else None
    reading1 = {
        "value": agreement,
        "status": STATUS_COMPUTED if agreement is not None else STATUS_PENDING,
        "uncertainty_band": {
            "value": None,
            "status": STATUS_PENDING,
            "note": "带宽须随 P2 标定给出；本模块不自设数值",
        },
        "input_schema": dict(EXPERT_LABEL_SCHEMA),
        "n_expert_labels": len(expert_rows),
        "note": "缺专家两栏判定 ⇒ 机器就绪、读数待数据",
    }

    # ④ 跨录音／跨艺人稳定性
    reading4 = {
        "value": None,
        "status": STATUS_PENDING,
        "input_schema": {
            "subject_id": EXPERT_LABEL_SCHEMA["subject_id"],
            "role": EXPERT_LABEL_SCHEMA["role"],
            "recording_id": EXPERT_LABEL_SCHEMA["recording_id"],
            "segment_id": EXPERT_LABEL_SCHEMA["segment_id"],
            "label": EXPERT_LABEL_SCHEMA["label"],
        },
        "note": "需多录音 × 多艺人（两栏）判定矩阵 ⇒ 待语料；只交算路与输入 schema",
    }

    return {
        "format": "acouscope-cavity-type-report",
        "version": 1,
        "tau_cents": TAU_CENTS_PLACEHOLDER,
        "labels": list(LABELS),
        "roles": list(EXPERT_ROLES),
        "reading_1_agreement_band": reading1,
        "reading_2_composite_share": reading2,
        "reading_3_failure_boundary": reading3,
        "reading_4_cross_recording_stability": reading4,
        "records": records,
    }
