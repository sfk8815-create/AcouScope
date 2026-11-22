# SPDX-License-Identifier: GPL-3.0-only
"""段长分布与分段下限敏感性（W-12）：逐例中位段长、短段占比、下限扫描漂移。

**定位**：把「段长分布」这一描述性读数**在平台运行口径内**算出，并给出
「下限参数一动、占比漂多少」的可核数；本模块不改分段逻辑、不改任何已交付读数。

## 口径（与主分析档一致，逐项写进件）

- 音域 60–1500 Hz、HMM 分段（``NoteHMM`` 三态）、窗 30 s／最小窗 5 s、逐窗不拼接；
- **下限参数** ``min_dur_s``：``NoteHMM.segment`` 的「时长 < min_dur_s 丢弃」阈值，
  主分析档取平台默认 **0.08 s**；扫描档在其上变动，**扫描值不构成运行口径**；
- 段长 = ``end_s − start_s``（浮点原值，**不用**三位小数 ``segment_id`` 反算，
  以免 1 ms 舍入在 150 ms 判据上翻面）；
- 短段判据：``< 150 ms``（设计约定口径；边界值 0.150 计为**不短**）。

## 漂移的定义（不掩盖）

``drift_pp = (max − min) × 100``，max/min 取自**本次声明的扫描网格**上该例
「短段占比」的最大与最小值。**漂移幅度依网格而定**，故件内同时给
``scan_grid`` 与**每个网格点**的占比——不把一个数当唯一真理。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from .params_snapshot import analysis_params_snapshot
from .readout import read_window, window_offsets
from .type_distribution import run_id as _content_id

__all__ = [
    "BASE_MIN_DUR_S",
    "DEFAULT_SCAN_GRID",
    "SEGMENT_LENGTH_FORMAT",
    "SEGMENT_LENGTH_VERSION",
    "SHORT_SEGMENT_S",
    "build_segment_length_payload",
    "durations_for",
    "export_segment_length_csv",
    "export_segment_length_json",
    "frame_tracks",
    "length_stats",
    "pairs_within_band",
    "scan_lower_bound",
    "segments_for",
]

SEGMENT_LENGTH_FORMAT = "acouscope-segment-length"
SEGMENT_LENGTH_VERSION = 1

#: 主分析档的下限（与 ``NoteHMM.segment`` 默认值一致）
BASE_MIN_DUR_S = 0.08
#: 短段判据（秒）
SHORT_SEGMENT_S = 0.150
#: 下限扫描网格（秒）——件内登记，换网格即换漂移数
DEFAULT_SCAN_GRID = (0.04, 0.06, 0.08, 0.10, 0.12)


def frame_tracks(
    audio_path,
    *,
    window_s: float = 30.0,
    min_window_s: float = 5.0,
    fmin: float = 60.0,
    fmax: float = 1500.0,
) -> dict:
    """整条录音 → 逐窗帧轨（times／f0／conf）。

    **帧轨与下限无关**：pYIN 只算一次，改 ``min_dur_s`` 只重做 HMM 分段，
    故扫描各档共用同一帧轨（既快，也保证「只动一个参数」）。
    """
    import soundfile as sf

    from .pitch_stream import stream_pitch

    info = sf.info(str(audio_path))
    sr = int(info.samplerate)
    plan = window_offsets(int(info.frames), sr, float(window_s), float(min_window_s))
    windows: list[dict] = []
    for start, count in plan:
        sig, _sr = read_window(audio_path, start, count)
        tr = stream_pitch(
            signal=sig, sr=sr, fmin=float(fmin), fmax=float(fmax),
            block_seconds=float(window_s),
        )
        windows.append(
            {
                "start_frame": int(start),
                "offset_s": start / sr,
                "times": np.asarray(tr.times, dtype=float),
                "f0": np.asarray(tr.f0_hz, dtype=float),
                "conf": np.asarray(tr.confidence, dtype=float),
            }
        )
    return {
        "audio_path": str(audio_path),
        "samplerate": sr,
        "frames": int(info.frames),
        "window_s": float(window_s),
        "min_window_s": float(min_window_s),
        "n_windows": len(windows),
        "windows": windows,
    }


def segments_for(tracks: Mapping, *, min_dur_s: float) -> list[dict]:
    """帧轨 → 该下限下的段表（起讫已加窗偏移，秒为浮点原值）。"""
    from .note_hmm import NoteHMM

    n = NoteHMM()
    out: list[dict] = []
    for window in tracks.get("windows") or ():
        segs = n.segment(
            window["times"], window["f0"], window["conf"],
            min_dur_s=float(min_dur_s),
        )
        offset = float(window["offset_s"])
        for seg in segs:
            start = float(seg.start_s) + offset
            end = float(seg.end_s) + offset
            out.append(
                {
                    "start_s": start,
                    "end_s": end,
                    "duration_s": end - start,
                    "segment_id": f"{start:.3f}-{end:.3f}",
                }
            )
    return out


def durations_for(tracks: Mapping, *, min_dur_s: float) -> list[float]:
    """帧轨 → 该下限下的段长列表（秒，浮点原值）。"""
    return [item["duration_s"] for item in segments_for(tracks, min_dur_s=min_dur_s)]


def length_stats(durations: Sequence[float], *, short_s: float = SHORT_SEGMENT_S) -> dict:
    """段长列表 → 段数、中位、四分位、短段占比（**分母＝段数**）。"""
    vals = np.asarray([float(x) for x in durations], dtype=float)
    n = int(vals.size)
    if n == 0:
        return {
            "n_segments": 0,
            "median_s": None,
            "p25_s": None,
            "p75_s": None,
            "min_s": None,
            "max_s": None,
            "n_short": 0,
            "short_share": None,
            "short_s": float(short_s),
        }
    n_short = int(np.count_nonzero(vals < float(short_s)))
    return {
        "n_segments": n,
        "median_s": round(float(np.median(vals)), 6),
        "p25_s": round(float(np.percentile(vals, 25)), 6),
        "p75_s": round(float(np.percentile(vals, 75)), 6),
        "min_s": round(float(vals.min()), 6),
        "max_s": round(float(vals.max()), 6),
        "n_short": n_short,
        "short_share": round(n_short / n, 6),
        "short_s": float(short_s),
    }


def scan_lower_bound(
    tracks: Mapping,
    *,
    min_dur_values: Iterable[float],
    base_min_dur_s: float = BASE_MIN_DUR_S,
    short_s: float = SHORT_SEGMENT_S,
) -> dict:
    """下限扫描：逐档段数／中位／短段占比 ＋ 漂移幅度（pp，依网格而定）。"""
    grid = [round(float(x), 4) for x in min_dur_values]
    levels: dict[str, dict] = {}
    cache: dict[float, list[float]] = {}
    for value in grid:
        if value not in cache:
            cache[value] = durations_for(tracks, min_dur_s=value)
        levels[f"{value:.2f}"] = length_stats(cache[value], short_s=short_s)
    shares = [
        block["short_share"] for block in levels.values()
        if block["short_share"] is not None
    ]
    drift_pp = (max(shares) - min(shares)) * 100.0 if shares else None
    base_key = f"{round(float(base_min_dur_s), 4):.2f}"
    return {
        "scan_grid": grid,
        "base_min_dur_s": round(float(base_min_dur_s), 4),
        "short_s": float(short_s),
        "levels": levels,
        "drift_pp": None if drift_pp is None else round(float(drift_pp), 2),
        "drift_definition": "drift_pp = (max − min) × 100，max/min 取自本件 scan_grid 上的短段占比",
        "base_share": (
            levels.get(base_key, {}).get("short_share")
        ),
        "drift_one_sided": (
            None if not shares else round(float(max(shares) - levels[base_key]["short_share"]) * 100.0, 2)
            if base_key in levels else None
        ),
    }


def pairs_within_band(
    levels_by_case: Mapping[str, Mapping[str, Mapping]],
    *,
    lo_pp: float = 12.0,
    hi_pp: float = 24.0,
) -> dict:
    """在给定网格上找「四例漂移同时落在 [lo, hi] 个百分点」的**两档配对**。

    用于回答一个具体问题：正文那句「漂移 12 至 24 个百分点」在什么网格上成立？
    ——是**网格条件性**的陈述，不是一个无条件的常数。本函数只摆事实，不给建议。
    """
    from itertools import combinations

    keys = sorted({k for lv in levels_by_case.values() for k in lv}, key=float)
    found: list[dict] = []
    for a, b in combinations(keys, 2):
        drifts: dict[str, float] = {}
        for rid, lv in levels_by_case.items():
            share_a = lv[a]["short_share"]
            share_b = lv[b]["short_share"]
            if share_a is None or share_b is None:
                break
            drifts[rid] = round((share_a - share_b) * 100.0, 2)
        if len(drifts) != len(levels_by_case):
            continue
        if all(lo_pp <= v <= hi_pp for v in drifts.values()):
            found.append(
                {
                    "min_dur_pair": [float(a), float(b)],
                    "drift_pp_by_case": drifts,
                }
            )
    return {
        "band_pp": [float(lo_pp), float(hi_pp)],
        "grid_keys": keys,
        "n_pairs": len(found),
        "pairs": found,
        "note": (
            "仅在**本件网格**上枚举两档配对；n_pairs=0 即该区间在本网格上不可复现。"
            "区间是否成立取决于网格，故引用时须同时给出网格。"
        ),
    }


def build_segment_length_payload(
    per_case: Sequence[Mapping],
    *,
    run_id_: str,
    caliber: Mapping,
    command: str = "",
    scan_grid: Sequence[float] = DEFAULT_SCAN_GRID,
    base_min_dur_s: float = BASE_MIN_DUR_S,
    short_s: float = SHORT_SEGMENT_S,
    provenance_extra: Mapping | None = None,
) -> dict:
    """逐例扫描结果 → 平台段长分布件（含段数基准与漂移）。"""
    params = analysis_params_snapshot()
    cases: list[dict] = []
    for item in per_case:
        scan = item["scan"]
        base = scan["levels"][f"{round(float(base_min_dur_s), 4):.2f}"]
        cases.append(
            {
                "recording_id": str(item["recording_id"]),
                "例": item.get("label") or "",
                "ref_mode": str(item.get("ref_mode", "absolute")),
                "duration_s": item.get("duration_s"),
                "n_segments": int(base["n_segments"]),
                "median_s": base.get("median_s"),
                "p25_s": base.get("p25_s"),
                "p75_s": base.get("p75_s"),
                "min_s": base.get("min_s"),
                "max_s": base.get("max_s"),
                "n_short": int(base.get("n_short") or 0),
                "short_share": base.get("short_share"),
                "short_s": float(short_s),
                "scan": scan,
            }
        )
    descriptor = {
        "format": SEGMENT_LENGTH_FORMAT,
        "version": SEGMENT_LENGTH_VERSION,
        "run_id": run_id_,
        "caliber": dict(caliber),
        "scan_grid": [round(float(x), 4) for x in scan_grid],
        "short_s": float(short_s),
        "params_snapshot": params,
    }
    payload = {
        "format": SEGMENT_LENGTH_FORMAT,
        "version": SEGMENT_LENGTH_VERSION,
        "run_id": run_id_,
        "segment_length_run_id": _content_id(descriptor),
        "caliber": dict(caliber),
        "base_min_dur_s": round(float(base_min_dur_s), 4),
        "short_s": float(short_s),
        "scan_grid": [round(float(x), 4) for x in scan_grid],
        "denominator_note": (
            "段长分布的分母＝该例该口径的**段数**（n_segments，主分析档 0.08 s 下限）；"
            "短段占比＝n_short / n_segments，边界值 0.150 s 计为不短。"
        ),
        "run_identity_note": (
            "本件计数在 `run_id` 所列运行的**同一段集**上核过（段集逐条比对见 "
            "`segment_set_check`）；扫描档只改 min_dur_s 一个参数，**不构成**运行口径，"
            "其数值不得与 `run_id` 绑定引用。"
        ),
        "per_recording": cases,
        "params_snapshot": params,
        "provenance": {
            "run_id": run_id_,
            "segment_length_run_id": _content_id(descriptor),
            "command": str(command),
            "platform_version": str(params.get("version") or ""),
            "content_addressed": (
                "segment_length_run_id = sha256(运行 run_id × 口径 × 扫描网格 × 短段判据 × 参数快照)[:16]"
            ),
            "generated_by": "acouscope.analysis.segment_length",
        },
    }
    if provenance_extra is not None:
        payload["provenance"].update(dict(provenance_extra))
    return payload


def segment_length_csv_rows(payload: Mapping) -> list[dict]:
    """段长件 → CSV 长表（一例 × 一档一行；基准档另标 is_base）。"""
    rows: list[dict] = []
    base = round(float(payload.get("base_min_dur_s") or BASE_MIN_DUR_S), 4)
    for case in payload.get("per_recording") or ():
        scan = dict(case.get("scan") or {})
        for key, block in dict(scan.get("levels") or {}).items():
            rows.append(
                {
                    "recording_id": case.get("recording_id"),
                    "例": case.get("例"),
                    "ref_mode": case.get("ref_mode"),
                    "min_dur_s": float(key),
                    "is_base": int(round(float(key), 4) == base),
                    "n_segments": block.get("n_segments"),
                    "median_s": block.get("median_s"),
                    "p25_s": block.get("p25_s"),
                    "p75_s": block.get("p75_s"),
                    "n_short": block.get("n_short"),
                    "short_share": block.get("short_share"),
                    "short_s": payload.get("short_s"),
                    "drift_pp": scan.get("drift_pp"),
                    "run_id": payload.get("run_id"),
                }
            )
    return rows


def export_segment_length_json(path, payload: Mapping) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return target


def export_segment_length_csv(path, payload: Mapping) -> Path:
    rows = segment_length_csv_rows(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        if not rows:
            fh.write("")
            return target
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return target
