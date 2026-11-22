# SPDX-License-Identifier: GPL-3.0-only
"""腔核候选完整流程 v2（W-14-01 / 缺口 G-03）。

与 :mod:`acouscope.analysis.cavity_core` 的关系（**兼容边界**）：

- 旧模块 :func:`cavity_core.core_candidates` 语义**零改动**：仍按「每 note 每个
  ``stable`` run 一个候选」出 :class:`cavity_core.CoreCandidate`，供既有测试与
  调用点复用；
- 本模块是**新增**的完整流程（同音级成组 → 停留区间 → 帧占比/时长/中位数稳定性
  收缩 → 区间、归属、不确定度），产出可 JSON 序列化的候选表；不改旧类语义。

流程口径（设计约定 §三 W-14-01 逐条落地，禁自行放宽）：

1. **成组**：按 ``model.notes`` 序，取 ``degree_index`` 相同且相邻 note 间隔
   ≤ ``max_gap_s`` 的**连续**组；组内只取 ``stable`` 运行；候选区间 = 组内首段
   stable 起点 → 末段 stable 终点；**不得跨不同 degree_index**；无 stable 运行的
   组**不产候选**。
2. **只给候选，不给判定**：本模块不做任何「腔核／非腔核」裁决，也不把候选写成
   判定结果。
3. **阈值一律显式**：过滤参数缺省 ``None`` ⇒ ``filter_status="not_applied"``，
   **不得静默套值**；给了任一参数即 ``"applied"``，被拒候选进 ``rejected``
   （逐条 ``candidate_id`` ＋ ``reason``），**不进** ``candidates``。
4. **禁回退 12TET**：``template`` 为空或组内 note 无 ``degree_index`` ⇒ 该组不产
   候选（无归属即无候选）；模板 spec 非法时由
   :func:`acouscope.analysis.tunings.templates.get_tuning` 显式报错。

不确定度口径（随件写明，供 C 复核）：``median_mad_cents`` 与
``median_ci95_cents`` 的样本单位由 ``frame_cents`` 决定——

- 给了 ``frame_cents``（逐帧到最近律位的有符号音分差，与 ``PitchGridModel`` 帧序
  对齐）：样本 = 组内各 ``stable`` 运行覆盖帧的偏离值，``params["deviation_sample"]
  = "frame_level_degree_deviation_cents"``（**推荐**，GUI/CLI 走
  :func:`core_candidates_from_audio` 时默认给出）；
- 未给：退为段级样本（每个 stable 运行取所属 note 的 ``degree_deviation_cents``），
  ``params["deviation_sample"] = "group_stable_runs_degree_deviation_cents"``，
  同 note 多 run 时 MAD 恒 0（诚实退化，不臆造帧级分布）。

``median_ci95_cents`` 用 percentile bootstrap（``n_boot`` 次重采样、``seed`` 固定
⇒ 结果可复现），取 2.5/97.5 分位与中位数的半宽最大值；样本为空 ⇒ 两值 ``None``
（禁 0 回填）。

纯函数、无 UI、不改分段与判定。
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .tunings.templates import get_tuning

__all__ = [
    "CANDIDATES_FORMAT",
    "CANDIDATES_VERSION",
    "DEFAULT_N_BOOT",
    "DEFAULT_SEED",
    "core_candidates_from_audio",
    "core_candidates_v2",
    "export_candidates_json",
]

CANDIDATES_FORMAT = "acouscope-cavity-core-candidates-v2"
CANDIDATES_VERSION = 2

#: bootstrap 次数与随机种子（显式缺省：可复现优先；两者都进 ``params``）
DEFAULT_N_BOOT = 200
DEFAULT_SEED = 0

_STABLE = "stable"
_RUN_ARITY = 5


def _runs_of(note) -> list[tuple[int, int, float, float, str]]:
    """note 的 ``state_runs`` 规范化为五元组列表（非法条目丢弃，不臆造）。"""
    out: list[tuple[int, int, float, float, str]] = []
    for run in getattr(note, "state_runs", ()) or ():
        if len(run) != _RUN_ARITY:
            continue
        out.append((int(run[0]), int(run[1]), float(run[2]), float(run[3]), str(run[4])))
    return out


def _note_frames(runs) -> tuple[int | None, int | None]:
    """note 的帧跨度 (首帧, 末帧)；无 runs ⇒ (None, None)。"""
    if not runs:
        return None, None
    return min(r[0] for r in runs), max(r[1] for r in runs)


def _median_ci95(values: np.ndarray, *, n_boot: int, seed: int) -> float | None:
    """中位数的 percentile bootstrap 95% 半宽（样本 <1 ⇒ None）。"""
    if values.size == 0:
        return None
    if values.size == 1:
        return 0.0
    rng = np.random.default_rng(int(seed))
    picks = rng.integers(0, values.size, size=(int(n_boot), values.size))
    medians = np.median(values[picks], axis=1)
    lo, hi = np.percentile(medians, [2.5, 97.5])
    centre = float(np.median(values))
    return float(max(centre - lo, hi - centre))


def _candidate_id(recording_id: str, start_s: float, end_s: float, degree: int | None) -> str:
    """候选 id：起讫秒（6 位小数）＋ degree ＋ recording_id 的确定性哈希（16 hex）。"""
    payload = f"{recording_id}|{start_s:.6f}|{end_s:.6f}|{degree}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _group_notes(notes, max_gap_s: float):
    """按「degree_index 相同 + 相邻间隔 ≤ max_gap_s」连续成组；degree 为 None 不入组。"""
    groups: list[list] = []
    current: list = []
    for note in notes:
        degree = getattr(note, "degree_index", None)
        if degree is None:
            if current:
                groups.append(current)
                current = []
            continue
        if not current:
            current = [note]
            continue
        prev = current[-1]
        gap = float(getattr(note, "start_s", 0.0)) - float(getattr(prev, "end_s", 0.0))
        if (
            getattr(prev, "degree_index", None) is not None
            and int(degree) == int(getattr(prev, "degree_index"))
            and gap <= float(max_gap_s)
        ):
            current.append(note)
        else:
            groups.append(current)
            current = [note]
    if current:
        groups.append(current)
    return groups


def _build_candidate(
    group, *, recording_id: str, template: str, params: dict, frame_cents=None
) -> dict | None:
    """一个同音级组 → 一个候选（无 stable 运行 ⇒ None）。"""
    stable = []  # (note, run)
    frame_lo: int | None = None
    frame_hi: int | None = None
    for note in group:
        runs = _runs_of(note)
        lo, hi = _note_frames(runs)
        if lo is not None and hi is not None:
            frame_lo = lo if frame_lo is None else min(frame_lo, lo)
            frame_hi = hi if frame_hi is None else max(frame_hi, hi)
        for run in runs:
            if run[4] == _STABLE:
                stable.append((note, run))
    if not stable:
        return None

    start_s = float(stable[0][1][2])
    end_s = float(stable[-1][1][3])
    n_frames = 0 if (frame_lo is None or frame_hi is None) else int(frame_hi - frame_lo + 1)
    stable_frames = int(sum(int(run[1] - run[0] + 1) for _note, run in stable))
    frame_share = None if n_frames <= 0 else float(stable_frames) / float(n_frames)

    if frame_cents is not None:
        array = np.asarray(frame_cents, dtype=float)
        picked: list[float] = []
        for _note, run in stable:
            chunk = array[int(run[0]) : int(run[1]) + 1]
            picked.extend(
                float(value) for value in chunk[np.isfinite(chunk)] if math.isfinite(value)
            )
        devs = picked
    else:
        devs = [
            float(note.degree_deviation_cents)
            for note, _run in stable
            if getattr(note, "degree_deviation_cents", None) is not None
        ]
    values = np.asarray(devs, dtype=float)
    if values.size:
        centre = float(np.median(values))
        mad = float(np.median(np.abs(values - centre)))
    else:
        centre, mad = None, None
    ci95 = _median_ci95(values, n_boot=int(params["n_boot"]), seed=int(params["seed"]))

    confs = [float(getattr(note, "conf", 0.0) or 0.0) for note in group]
    degree = getattr(group[0], "degree_index", None)
    return {
        "candidate_id": _candidate_id(recording_id, start_s, end_s, degree),
        "recording_id": str(recording_id),
        "segment_ids": [
            f"{float(getattr(note, 'start_s', 0.0)):.3f}-{float(getattr(note, 'end_s', 0.0)):.3f}"
            for note in group
        ],
        "start_s": start_s,
        "end_s": end_s,
        "degree_index": None if degree is None else int(degree),
        "degree_deviation_cents": None if centre is None else round(centre, 4),
        "template": str(template),
        "n_frames": int(n_frames),
        "frame_share": None if frame_share is None else round(frame_share, 6),
        "duration_s": round(float(end_s - start_s), 6),
        "stable_runs": [[float(run[2]), float(run[3])] for _note, run in stable],
        "n_stable_runs": int(len(stable)),
        "median_mad_cents": None if mad is None else round(mad, 4),
        "median_ci95_cents": None if ci95 is None else round(ci95, 4),
        "head_deviation_cents": getattr(group[0], "head_deviation_cents", None),
        "tail_deviation_cents": getattr(group[-1], "tail_deviation_cents", None),
        "conf": round(float(np.median(np.asarray(confs, dtype=float))), 6) if confs else None,
        # 全部参数原样随候选（设计约定 §三 W-14-01 最小实现面 3）
        "params": dict(params),
    }


def _frame_degree_deviation_cents(f0, tuning) -> np.ndarray:
    """逐帧到最近律位的有符号音分差（无声帧 ⇒ NaN；口径同 ``_segment_degree``）。"""
    from ..dsp.units import hz_to_cents

    values = np.asarray(f0, dtype=float)
    out = np.full(values.shape, np.nan, dtype=float)
    reference = float(tuning.reference_freq)
    for index, value in enumerate(values):
        freq = float(value)
        if not math.isfinite(freq) or freq <= 0.0:
            continue
        cents = float(hz_to_cents(freq, ref_freq=reference))
        out[index] = cents - float(tuning.degree_to_cents(tuning.freq_to_degree(freq)))
    return out


def _reject_reason(candidate: dict, params: dict) -> tuple[str, float, float] | None:
    """过滤判据（全部显式阈值；命中即返回 (reason, value, threshold)）。"""
    share_min = params.get("min_frame_share")
    if share_min is not None:
        value = candidate["frame_share"]
        if value is None:
            return ("frame_share_missing", None, float(share_min))
        if float(value) < float(share_min):
            return ("frame_share_below_min", float(value), float(share_min))
    dur_min = params.get("min_duration_s")
    if dur_min is not None and float(candidate["duration_s"]) < float(dur_min):
        return ("duration_below_min", float(candidate["duration_s"]), float(dur_min))
    mad_max = params.get("max_median_mad_cents")
    if mad_max is not None:
        value = candidate["median_mad_cents"]
        if value is None:
            return ("median_mad_missing", None, float(mad_max))
        if float(value) > float(mad_max):
            return ("median_mad_above_max", float(value), float(mad_max))
    return None


def core_candidates_v2(
    model,
    *,
    template: str,
    max_gap_s: float,
    min_frame_share: float | None = None,
    min_duration_s: float | None = None,
    max_median_mad_cents: float | None = None,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_SEED,
    recording_id: str = "",
    frame_cents=None,
) -> dict:
    """腔核候选完整流程（设计约定 W-14-01 最小实现面 1—5）。

    参数
    ----
    model : ``PitchGridModel``（或含 ``notes`` 的同形对象；须已带段级音级归属）
    template : 模板 spec（内置 key 或 ``.scl`` 路径）；只作**登记**，不改归属
    max_gap_s : 同音级成组的最大相邻间隔（秒）——**必填**，平台不设默认阈值
    min_frame_share / min_duration_s / max_median_mad_cents : 收缩阈值；
        全为 ``None`` ⇒ ``filter_status="not_applied"``
    n_boot / seed : bootstrap 次数与种子（进 ``params``）
    recording_id : 候选 id 与随件登记用（可空）
    frame_cents : 可选，逐帧到最近律位的有符号音分差（与模型帧序对齐）；
        给出则不确定度按**帧级**样本算，否则按段级（见模块 docstring）

    返回 :data:`CANDIDATES_FORMAT` 载荷：``candidates``（按 ``(start_s, candidate_id)``
    稳定排序）、``rejected``、``params``、``filter_status``、``filter_note``。
    """
    if not template:
        raise ValueError("core_candidates_v2 需要显式 template（禁回退 12TET）")
    if max_gap_s is None:
        raise ValueError("core_candidates_v2 需要显式 max_gap_s（平台不设默认阈值）")
    max_gap = float(max_gap_s)
    if max_gap < 0.0:
        raise ValueError("max_gap_s 须 ≥ 0")

    params = {
        "max_gap_s": max_gap,
        "min_frame_share": None if min_frame_share is None else float(min_frame_share),
        "min_duration_s": None if min_duration_s is None else float(min_duration_s),
        "max_median_mad_cents": (
            None if max_median_mad_cents is None else float(max_median_mad_cents)
        ),
        "n_boot": int(n_boot),
        "seed": int(seed),
        "ci_method": "percentile_bootstrap_median",
        "deviation_sample": (
            "frame_level_degree_deviation_cents"
            if frame_cents is not None
            else "group_stable_runs_degree_deviation_cents"
        ),
    }
    filtered = any(
        params[key] is not None
        for key in ("min_frame_share", "min_duration_s", "max_median_mad_cents")
    )

    notes = list(getattr(model, "notes", ()) or ())
    built: list[dict] = []
    for group in _group_notes(notes, max_gap):
        candidate = _build_candidate(
            group,
            recording_id=recording_id,
            template=str(template),
            params=params,
            frame_cents=frame_cents,
        )
        if candidate is not None:
            built.append(candidate)

    candidates: list[dict] = []
    rejected: list[dict] = []
    for candidate in built:
        hit = _reject_reason(candidate, params) if filtered else None
        if hit is None:
            candidate["filter_status"] = "applied" if filtered else "not_applied"
            candidates.append(candidate)
        else:
            reason, value, threshold = hit
            rejected.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "reason": reason,
                    "value": value,
                    "threshold": threshold,
                    "start_s": candidate["start_s"],
                    "end_s": candidate["end_s"],
                    "degree_index": candidate["degree_index"],
                }
            )
    candidates.sort(key=lambda item: (item["start_s"], item["candidate_id"]))
    rejected.sort(key=lambda item: (item["start_s"], item["candidate_id"]))

    return {
        "format": CANDIDATES_FORMAT,
        "version": CANDIDATES_VERSION,
        "recording_id": str(recording_id),
        "template": str(template),
        "params": params,
        "filter_status": "applied" if filtered else "not_applied",
        "filter_note": (
            "全部过滤参数均为显式阈值；未给参数时为 not_applied，平台不静默套值"
            if filtered
            else "未给任何过滤参数（not_applied）：全部候选按成组规则产出，不做收缩"
        ),
        "n_candidates": len(candidates),
        "n_rejected": len(rejected),
        "candidates": candidates,
        "rejected": rejected,
        "decision_scope": (
            "只给候选，不给判定：本件不裁决「腔核／非腔核」，人工/专家判定另记"
        ),
        "analysis_scope": (
            "同音级成组 + 段内 stable 运行 + 帧占比/时长/中位数稳定性；"
            "不跨 degree_index、不跨 note 组"
        ),
    }


def core_candidates_from_audio(
    audio_path,
    *,
    template: str,
    window_start_s: float = 0.0,
    window_s: float = 30.0,
    fmin: float = 60.0,
    fmax: float = 1500.0,
    segmenter: str = "hmm",
    max_gap_s: float,
    min_frame_share: float | None = None,
    min_duration_s: float | None = None,
    max_median_mad_cents: float | None = None,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_SEED,
    recording_id: str = "",
) -> dict:
    """音频 → 候选表（GUI/CLI 同一入口；与 :func:`core_candidates_v2` 同口径）。

    读窗 → ``stream_pitch`` → ``build_pitch_grid(segmenter, tuning)`` →
    :func:`core_candidates_v2`；返回载荷额外带 ``source``（窗、频段、音频、
    segmentation 口径），供 GUI 表与 CLI 件逐值对拍。
    """
    from ..visualization.figures import _read_window
    from .pitch_grid import build_pitch_grid
    from .pitch_stream import stream_pitch

    tuning = get_tuning(template)
    sig, sr, w0 = _read_window(audio_path, window_start_s, window_s)
    tr = stream_pitch(
        signal=sig, sr=sr, fmin=float(fmin), fmax=float(fmax), block_seconds=float(window_s)
    )
    f0 = np.asarray(tr.f0_hz, dtype=float)
    conf = np.asarray(tr.confidence, dtype=float)
    model = build_pitch_grid(
        tr.times, f0, conf, segmenter=str(segmenter), tuning=tuning
    )
    frame_cents = _frame_degree_deviation_cents(f0, tuning)
    payload = core_candidates_v2(
        model,
        template=str(template),
        max_gap_s=float(max_gap_s),
        min_frame_share=min_frame_share,
        min_duration_s=min_duration_s,
        max_median_mad_cents=max_median_mad_cents,
        n_boot=n_boot,
        seed=seed,
        recording_id=recording_id,
        frame_cents=frame_cents,
    )
    payload["source"] = {
        "audio_path": str(audio_path),
        "window_start_s": float(w0),
        "window_s": float(window_s),
        "sr": int(sr),
        "fmin": float(fmin),
        "fmax": float(fmax),
        "segmenter": str(segmenter),
        "template": str(template),
        "tuning_name": str(tuning.name),
        "n_frames_analyzed": int(f0.size),
        "n_notes": int(len(getattr(model, "notes", ()) or ())),
    }
    return payload


def export_candidates_json(payload: dict, path) -> Path:
    """候选表 → JSON（UTF-8，缩进 2；``delivery_id`` 由调用方另行登记）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return target
