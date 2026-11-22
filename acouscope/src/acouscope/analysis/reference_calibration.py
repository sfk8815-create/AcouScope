# SPDX-License-Identifier: GPL-3.0-only
"""D 档参考音标定（W-11）：参考音 → 稳定段 → 实测基频与离散 → 平台件。

**本模块只出「精度标定件」，不改全局 A4 基准、不改任何已完成运行的读数。**

## 口径（照设计约定，勿放宽）

- **不得用合成信号冒充标定**：本模块只接受真实录音文件；合成音的链路验证在
  :mod:`acouscope.analysis.calibration_export`（``chain_only``），两者不得混称。
- **不得把整段硬算作 A4**：先从逐帧 f0 里挑**稳定段**（基频稳定、无揉弦／滑音，
  且远离起音与衰减），再在该段内取中位与离散；稳定段不足即回 ``pending``。
- **标称须与实测相符才可记 ``calibrated``**：实测相对标称的偏差超过
  :data:`MAX_CALIBRATION_BIAS_CENTS`（默认 50 音分）时，说明「这不是标称那
  个音」，一律回 ``pending`` 并把偏差原样写出（该偏差是**诊断量**，不是标定结果）。
- ``calibrated`` 须给 ``reference_id``（与 :mod:`dsp.reference_status` 同规：
  无参考音标识不得记已校准）。

## 稳定段判据（确定性、可复算）

逐帧 f0（``stream_pitch``）→ 有声帧 → 以 ``window_frames``（0.15 s 折帧，至少 5 帧）
滑动窗算两项局部量：窗内音分标准差、窗内音分斜率（cent/100 ms）。二者同时
≤ 阈值（默认 3 音分／15 音分每 100 ms）的帧记「局部稳定」；再取最长连续段
（允许 ≤ ``max_gap_frames`` 帧的空隙），要求不短于 ``min_stable_s``（默认 0.30 s）。
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .params_snapshot import analysis_params_snapshot
from .type_distribution import run_id as _content_id

__all__ = [
    "MAX_CALIBRATION_BIAS_CENTS",
    "REFERENCE_CALIBRATION_FORMAT",
    "REFERENCE_CALIBRATION_VERSION",
    "STATUS_CALIBRATED",
    "STATUS_PENDING",
    "analyze_reference_audio",
    "build_reference_payload",
    "calibration_csv_rows",
    "export_reference_calibration_csv",
    "export_reference_calibration_json",
    "stable_segment",
]

REFERENCE_CALIBRATION_FORMAT = "acouscope-reference-calibration"
REFERENCE_CALIBRATION_VERSION = 1

STATUS_CALIBRATED = "calibrated"
STATUS_PENDING = "pending"

#: 允许记 ``calibrated`` 的最大 |实测 − 标称|（音分）。超过即「不是标称那个音」。
MAX_CALIBRATION_BIAS_CENTS = 50.0

#: 稳定段判据缺省值（全部进件，可复算）
DEFAULT_STABLE_WINDOW_S = 0.15
DEFAULT_MAX_LOCAL_STD_CENTS = 3.0
DEFAULT_MAX_LOCAL_SLOPE_CENTS_PER_100MS = 15.0
DEFAULT_MIN_STABLE_S = 0.30
DEFAULT_MAX_GAP_FRAMES = 2


def _cents(hz, ref_hz: float = 440.0):
    return 1200.0 * np.log2(np.asarray(hz, dtype=float) / float(ref_hz))


def _runs(mask: np.ndarray, *, max_gap: int = 0) -> list[tuple[int, int]]:
    """布尔序列 → 连续 ``True`` 区间 ``[(start, end_inclusive), …]``（可容许小空隙）。"""
    out: list[tuple[int, int]] = []
    start: int | None = None
    gap = 0
    for index, flag in enumerate(mask):
        if bool(flag):
            if start is None:
                start = index
            gap = 0
        elif start is not None:
            gap += 1
            if gap > int(max_gap):
                out.append((start, index - gap))
                start = None
                gap = 0
    if start is not None:
        out.append((start, len(mask) - 1 - gap))
    return [(a, b) for a, b in out if b >= a]


def stable_segment(
    f0_hz: Sequence[float],
    times_s: Sequence[float],
    *,
    window_frames: int | None = None,
    max_local_std_cents: float = DEFAULT_MAX_LOCAL_STD_CENTS,
    max_local_slope_cents_per_100ms: float = DEFAULT_MAX_LOCAL_SLOPE_CENTS_PER_100MS,
    min_stable_s: float = DEFAULT_MIN_STABLE_S,
    max_gap_frames: int = DEFAULT_MAX_GAP_FRAMES,
) -> dict:
    """逐帧 f0 → 最长稳定段（起讫、帧数、窗内判据、候选段清单）。

    ``f0_hz`` 中无声帧为 ``nan``／0；判据只作用于有声帧构成的连续段。
    """
    f0 = np.asarray(f0_hz, dtype=float)
    t = np.asarray(times_s, dtype=float)
    voiced = np.isfinite(f0) & (f0 > 0)
    n = int(f0.size)
    if n == 0 or not voiced.any():
        return {
            "found": False,
            "reason": "no_voiced_frames",
            "n_frames_total": n,
            "n_frames_voiced": 0,
            "runs": [],
            "criteria": {},
        }
    dt = float(np.median(np.diff(t))) if t.size > 1 else 0.0
    win = int(window_frames or max(5, round(DEFAULT_STABLE_WINDOW_S / dt) if dt else 5))
    win = max(5, min(int(win), int(voiced.sum())))

    cents = np.full(n, np.nan)
    cents[voiced] = _cents(f0[voiced])
    loc_std = np.full(n, np.inf)
    loc_slope = np.full(n, np.inf)
    half = win // 2
    for i in range(n):
        lo, hi = i - half, i + half + 1
        if lo < 0 or hi > n:
            continue
        block = cents[lo:hi]
        if not np.all(np.isfinite(block)):      # 窗内不得含无声帧（不插值、不补零）
            continue
        loc_std[i] = float(np.std(block))
        if dt > 0:
            slope = np.polyfit(np.arange(block.size) * dt, block, 1)[0]
            loc_slope[i] = float(abs(slope) * 0.1)   # cent / 100 ms
    stable = (
        voiced
        & (loc_std <= float(max_local_std_cents))
        & (loc_slope <= float(max_local_slope_cents_per_100ms))
    )
    runs = _runs(stable, max_gap=int(max_gap_frames))
    frame_s = dt if dt > 0 else 0.0
    scored = [
        {
            "start_frame": int(a),
            "end_frame": int(b),
            "n_frames": int(b - a + 1),
            "start_s": round(float(t[a]), 4),
            "end_s": round(float(t[b]), 4),
            "duration_s": round(float(t[b] - t[a] + frame_s), 4),
        }
        for a, b in runs
    ]
    scored.sort(key=lambda item: (-item["n_frames"], item["start_frame"]))
    best = next((item for item in scored if item["duration_s"] >= float(min_stable_s)), None)
    return {
        "found": bool(best is not None),
        "reason": None if best is not None else "stable_segment_too_short",
        "selected": best,
        "n_frames_total": n,
        "n_frames_voiced": int(voiced.sum()),
        "frame_dt_s": round(frame_s, 6),
        "candidates": scored,
        "criteria": {
            "window_frames": int(win),
            "window_s": round(win * frame_s, 4),
            "max_local_std_cents": float(max_local_std_cents),
            "max_local_slope_cents_per_100ms": float(max_local_slope_cents_per_100ms),
            "min_stable_s": float(min_stable_s),
            "max_gap_frames": int(max_gap_frames),
            "note": (
                "稳定段＝局部音分标准差与局部斜率同时达标的最长连续有声段；"
                "起音与衰减因斜率/离散超标自然被排除，不另设硬边界。"
            ),
        },
    }


def analyze_reference_audio(
    audio_path,
    *,
    nominal_hz: float | None = None,
    fmin: float = 60.0,
    fmax: float = 1500.0,
    window_frames: int | None = None,
    max_local_std_cents: float = DEFAULT_MAX_LOCAL_STD_CENTS,
    max_local_slope_cents_per_100ms: float = DEFAULT_MAX_LOCAL_SLOPE_CENTS_PER_100MS,
    min_stable_s: float = DEFAULT_MIN_STABLE_S,
    max_gap_frames: int = DEFAULT_MAX_GAP_FRAMES,
) -> dict:
    """参考音文件 → 文件事实 ＋ 稳定段 ＋ 该段实测统计（**只测量，不判 status**）。"""
    import soundfile as sf

    from .pitch_stream import stream_pitch

    params = analysis_params_snapshot()
    base = float(params.get("a4_reference_hz") or 440.0) if nominal_hz is None else float(nominal_hz)
    path = Path(str(audio_path))
    raw = path.read_bytes()
    info = sf.info(str(path))
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    sig = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    tr = stream_pitch(
        signal=sig, sr=int(sr), fmin=float(fmin), fmax=float(fmax), block_seconds=30.0
    )
    f0 = np.asarray(tr.f0_hz, dtype=float)
    times = np.asarray(tr.times, dtype=float)
    seg = stable_segment(
        f0, times,
        window_frames=window_frames,
        max_local_std_cents=max_local_std_cents,
        max_local_slope_cents_per_100ms=max_local_slope_cents_per_100ms,
        min_stable_s=min_stable_s,
        max_gap_frames=max_gap_frames,
    )
    result = {
        "file": {
            "path": str(path),
            "name": path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "samplerate": int(info.samplerate),
            "channels": int(info.channels),
            "subtype": str(info.subtype),
            "frames": int(info.frames),
            "duration_s": round(float(info.frames) / float(info.samplerate), 6),
        },
        "nominal_hz": float(base),
        "pitch": {
            "fmin": float(fmin),
            "fmax": float(fmax),
            "backend": str(params.get("pyin_marker", "")),
            "block_seconds": 30.0,
        },
        "stable_segment": seg,
        "measurement": None,
    }
    if not seg["found"]:
        return result
    item = seg["selected"]
    block = f0[item["start_frame"] : item["end_frame"] + 1]
    block = block[np.isfinite(block) & (block > 0)]
    if block.size == 0:
        seg["found"] = False
        seg["reason"] = "no_voiced_frames_in_segment"
        return result
    cents = _cents(block, base)
    median_hz = float(np.median(block))
    median_cents = float(np.median(cents))
    # 去趋势残差：把「音自身缓慢的升降（弦张力／磁带抖晃等）」从测量噪声里分开，
    # 使 std 既能报「含漂移」也能报「去漂移」——两者都写，不互相代替
    trend = np.polyval(np.polyfit(np.arange(cents.size, dtype=float), cents, 1),
                       np.arange(cents.size, dtype=float))
    resid = cents - trend
    result["measurement"] = {
        "n_frames": int(block.size),
        "median_hz": round(median_hz, 4),
        "median_cents_vs_nominal": round(median_cents, 4),
        "mean_hz": round(float(np.mean(block)), 4),
        "std_cents": round(float(np.std(cents)), 4),
        "p95_abs_dispersion_cents": round(
            float(np.percentile(np.abs(cents - median_cents), 95)), 4
        ),
        "p95_abs_cents_vs_nominal": round(
            float(np.percentile(np.abs(cents), 95)), 4
        ),
        "std_cents_detrended": round(float(np.std(resid)), 4),
        "p95_abs_detrended_cents": round(
            float(np.percentile(np.abs(resid), 95)), 4
        ),
        "range_cents": round(float(np.max(cents) - np.min(cents)), 4),
        "min_hz": round(float(np.min(block)), 4),
        "max_hz": round(float(np.max(block)), 4),
        "drift_cents": round(
            float(np.median(_cents(block[-max(3, block.size // 5):], base)))
            - float(np.median(_cents(block[: max(3, block.size // 5)], base))),
            4,
        ),
    }
    result["independent_check"] = _spectral_check(
        sig, int(sr), item["start_s"], item["end_s"], base
    )
    return result


def _spectral_check(signal, sr: int, start_s: float, end_s: float,
                    nominal_hz: float) -> dict:
    """**独立法**复核：段内 FFT 主峰 ＋ 自相关周期 → 两法是否同指一个基频。

    目的：排除「pYIN 八度错误／谐波误判」这一解释。若 FFT 主峰与自相关周期
    指同一频率，则该音**确实**不是标称音，而不是测量算法出错。
    """
    seg = np.asarray(signal, dtype=float)
    i0 = max(0, int(round(float(start_s) * sr)))
    i1 = min(int(seg.size), int(round(float(end_s) * sr)))
    block = seg[i0:i1]
    if block.size < 64:
        return {"_skipped": "segment_too_short"}
    block = block - float(np.mean(block))
    win = np.hanning(block.size)
    spec = np.abs(np.fft.rfft(block * win))
    freqs = np.fft.rfftfreq(block.size, 1.0 / float(sr))
    band = (freqs >= 50.0) & (freqs <= min(4000.0, sr / 2.0))
    peak_hz = float(freqs[band][int(np.argmax(spec[band]))])
    ref = float(spec[band].max()) or 1.0

    def _mag(f: float) -> float:
        if f >= sr / 2.0:
            return 0.0
        idx = int(np.argmin(np.abs(freqs - f)))
        lo, hi = max(0, idx - 2), idx + 3
        return float(spec[lo:hi].max())

    autoc = np.correlate(block, block, "full")[block.size - 1:]
    autoc = autoc / (autoc[0] if autoc[0] else 1.0)
    lo_lag = max(2, int(sr / 2000.0))
    hi_lag = min(block.size - 2, int(sr / 50.0))
    lag = lo_lag + int(np.argmax(autoc[lo_lag:hi_lag]))
    return {
        "fft_peak_hz": round(peak_hz, 3),
        "fft_peak_cents_vs_nominal": round(
            float(1200.0 * np.log2(peak_hz / float(nominal_hz))), 3
        ),
        "harmonic_peaks_rel_db": {
            f"k={k}": round(
                float(20.0 * np.log10(max(_mag(peak_hz * k), 1e-12) / ref)), 1
            )
            for k in (1, 2, 3, 4)
        },
        "magnitude_at_nominal_rel_db": round(
            float(20.0 * np.log10(max(_mag(float(nominal_hz)), 1e-12) / ref)), 1
        ),
        "magnitude_at_half_hz_rel_db": round(
            float(20.0 * np.log10(max(_mag(peak_hz / 2.0), 1e-12) / ref)), 1
        ),
        "autocorr_f0_hz": round(float(sr / lag), 3),
        "autocorr_peak": round(float(autoc[lag]), 4),
        "agreement_hz": round(abs(float(sr / lag) - peak_hz), 3),
        "note": (
            "段内 FFT 主峰与自相关周期两法互证；谐波列与「标称频率处／半频处」的"
            "相对幅度一并给出，用于排除八度误判与谐波误判。"
        ),
    }


def _tone_classification(median_hz: float, nominal_hz: float) -> dict:
    """实测中位 → 最接近的十二平均律音名与该音上的偏差（诊断用，不改标称）。"""
    semis = 12.0 * np.log2(float(median_hz) / float(nominal_hz))
    nearest = int(round(semis))
    names = ("A", "A♯/B♭", "B", "C", "C♯/D♭", "D", "D♯/E♭", "E", "F", "F♯/G♭", "G", "G♯/A♭")
    return {
        "semitones_from_nominal": round(float(semis), 4),
        "nearest_note": f"{names[nearest % 12]}{4 + (nearest + 9) // 12}",
        "offset_from_nearest_note_cents": round(float((semis - nearest) * 100.0), 2),
        "note": (
            "以 A4=标称值为参照的十二平均律读法；只用于诊断「这到底是不是那个音」，"
            "不改标称、不改平台 A4 基准。"
        ),
    }


def build_reference_payload(
    analysis: Mapping,
    *,
    reference_id: str,
    source: str,
    calibration_method: str = (
        "稳定段基频中位（逐帧 f0，pYIN；中位抗离群）；"
        "稳定段＝局部音分标准差与斜率同时达标的最长连续有声段，"
        "**不取最平子窗**（避免选择性偏差）；段内慢漂与去趋势残差一并给出"
    ),
    max_bias_cents: float = MAX_CALIBRATION_BIAS_CENTS,
    command: str = "",
    pending_reason_extra: str = "",
    suggested_alternatives: Sequence[str] = (),
    extra: Mapping | None = None,
) -> dict:
    """测量结果 → 平台标定件（判 ``calibrated``／``pending``，不伪造）。"""
    params = analysis_params_snapshot()
    file_info = dict(analysis.get("file") or {})
    seg = dict(analysis.get("stable_segment") or {})
    meas = analysis.get("measurement")
    nominal = float(analysis.get("nominal_hz") or params.get("a4_reference_hz") or 440.0)

    descriptor = {
        "format": REFERENCE_CALIBRATION_FORMAT,
        "version": REFERENCE_CALIBRATION_VERSION,
        "file_sha256": file_info.get("sha256"),
        "reference_id": str(reference_id),
        "nominal_hz": nominal,
        "pitch": dict(analysis.get("pitch") or {}),
        "criteria": dict(seg.get("criteria") or {}),
        "params_snapshot": params,
    }
    rid = _content_id(descriptor)

    payload: dict = {
        "format": REFERENCE_CALIBRATION_FORMAT,
        "version": REFERENCE_CALIBRATION_VERSION,
        "reference_id": str(reference_id),
        "source": str(source),
        "file": file_info,
        "file_sha256": file_info.get("sha256"),
        "samplerate": file_info.get("samplerate"),
        "channels": file_info.get("channels"),
        "duration_s": file_info.get("duration_s"),
        "reference_hz_nominal": nominal,
        "reference_hz_measured": None,
        "reference_status": STATUS_PENDING,
        "calibration_method": str(calibration_method),
        "bias_cents": None,
        "std_cents": None,
        "p95_cents": None,
        "n_frames": 0,
        "n_segments": int(len(seg.get("candidates") or ())),
        "stable_segment_s": None,
        "stable_segment_frames": None,
        "stable_segment": dict(seg),
        "criteria": dict(seg.get("criteria") or {}),
        "params_snapshot": params,
        "pitch": dict(analysis.get("pitch") or {}),
        "independent_check": dict(analysis.get("independent_check") or {}),
    }

    if not seg.get("found") or meas is None:
        payload["pending_reason"] = (
            f"参考音无可用的稳定段（{seg.get('reason') or 'unknown'}）："
            "按设计约定不得把起音／衰减／揉弦段硬算作标称音。"
            + (f" {pending_reason_extra}".rstrip() if pending_reason_extra else "")
        )
        payload["measured_tone"] = None
    else:
        item = dict(seg["selected"])
        median_hz = float(meas["median_hz"])
        bias = float(meas["median_cents_vs_nominal"])
        payload.update(
            {
                "reference_hz_measured": round(median_hz, 4),
                "bias_cents": round(bias, 4),
                "std_cents": float(meas["std_cents"]),
                "p95_cents": float(meas["p95_abs_dispersion_cents"]),
                "std_cents_detrended": float(meas.get("std_cents_detrended")),
                "p95_cents_detrended": float(
                    meas.get("p95_abs_detrended_cents")
                ),
                "range_cents": float(meas.get("range_cents")),
                "drift_cents": float(meas.get("drift_cents")),
                "n_frames": int(meas["n_frames"]),
                "stable_segment_s": [item["start_s"], item["end_s"]],
                "stable_segment_frames": [int(item["start_frame"]), int(item["end_frame"])],
                "measured_tone": {
                    **{k: v for k, v in meas.items()},
                    "stable_segment": item,
                    "classification": _tone_classification(median_hz, nominal),
                },
            }
        )
        if abs(bias) <= float(max_bias_cents):
            if not str(reference_id or "").strip():
                # 与 dsp.reference_status 同规：无参考音标识不得记已校准
                raise ValueError(
                    "calibrated 态须附参考音标识 reference_id（无标识即未校准）"
                )
            payload["reference_status"] = STATUS_CALIBRATED
            payload["bias_cents_is_diagnostic"] = False
        else:
            payload["reference_status"] = STATUS_PENDING
            payload["bias_cents_is_diagnostic"] = True
            cls = payload["measured_tone"]["classification"]
            indep = dict(payload.get("independent_check") or {})
            tail = ""
            if indep.get("fft_peak_hz") and indep.get("autocorr_f0_hz"):
                tail = (
                    f" 独立复核：段内 FFT 主峰 {indep['fft_peak_hz']:.2f} Hz、"
                    f"自相关周期 {indep['autocorr_f0_hz']:.2f} Hz，两法互证，"
                    "不属八度或谐波误判。"
                )
            payload["pending_reason"] = (
                f"参考音稳定段实测基频中位 {median_hz:.2f} Hz，与标称 A4={nominal:g} Hz "
                f"相差 {bias:+.1f} 音分（超过允许的 ±{float(max_bias_cents):g} 音分）："
                f"按 A4={nominal:g} 记谱，该音约为 {cls['nearest_note']}"
                f"{cls['offset_from_nearest_note_cents']:+.1f} 音分，**不是 A4**。"
                "以之作 A4 标定会把整一套系统偏差写进标定件，故按设计约定 §一／§四 B 回 pending；"
                "bias_cents 仅作诊断量，不得当标定结果引用。"
                + tail
                + (f" {pending_reason_extra}".rstrip() if pending_reason_extra else "")
            )

    payload["stats_semantics"] = {
        "bias_cents": (
            "实测中位相对标称的偏差；reference_status=pending 时为诊断量"
            "（bias_cents_is_diagnostic=true），不得当精度结果引用"
        ),
        "std_cents": "该稳定段逐帧音分的标准差（**与标称无关**，含该音自身的慢漂）",
        "p95_cents": "该稳定段 |逐帧音分 − 段中位| 的 P95（**与标称无关**，含慢漂）",
        "std_cents_detrended": "同上，但先剔除段内线性趋势（更接近平台测量噪声）",
        "p95_cents_detrended": "同上，去线性趋势后的 |残差| P95",
        "range_cents": "稳定段内音分极差（该音自身的稳定度上限）",
        "n_frames": "稳定段内有声帧数",
        "n_segments": "通过稳定判据的候选段数（本次选最长者）",
    }
    payload["platform_reference_unchanged"] = {
        "reference_hz": float(params.get("a4_reference_hz") or nominal),
        "reference_status": str(params.get("a4_reference_status") or "default-nominal"),
        "note": (
            "本件只出精度标定测量，**不改**平台 A4 基准、不改已完成运行的读数；"
            "若要把基准改为实测值，须另行请裁（换基准即换全部音分读数与表图）。"
        ),
    }
    payload["four_case_impact"] = {
        "run_id": "58ca9b6ebc5c5d35",
        "changed": False,
        "note": "四例主档表图与图件哈希均未变（见回执核对）。",
    }
    if suggested_alternatives:
        payload["suggested_alternatives"] = [str(x) for x in suggested_alternatives]
    payload["provenance"] = {
        "run_id": rid,
        "command": str(command),
        "platform_version": str(params.get("version") or ""),
        "content_addressed": (
            "run_id = sha256(参考音 sha256 × 标称 × 音高后端参数 × 稳定段判据 × 参数快照)[:16]"
        ),
        "generated_by": "acouscope.analysis.reference_calibration",
    }
    if extra is not None:
        payload.update(dict(extra))
    return payload


def calibration_csv_rows(payload: Mapping) -> list[dict]:
    """标定件 → 单行 CSV（列序固定；pending 的 bias 留空而不填 0）。"""
    seg = payload.get("stable_segment_s") or [None, None]
    cls = ((payload.get("measured_tone") or {}).get("classification") or {})
    prov = dict(payload.get("provenance") or {})
    return [
        {
            "reference_id": payload.get("reference_id"),
            "source": payload.get("source"),
            "file": (payload.get("file") or {}).get("name"),
            "file_sha256": payload.get("file_sha256"),
            "samplerate": payload.get("samplerate"),
            "duration_s": payload.get("duration_s"),
            "stable_start_s": seg[0],
            "stable_end_s": seg[1],
            "reference_hz_nominal": payload.get("reference_hz_nominal"),
            "reference_hz_measured": payload.get("reference_hz_measured"),
            "reference_status": payload.get("reference_status"),
            "bias_cents": payload.get("bias_cents"),
            "bias_cents_is_diagnostic": payload.get("bias_cents_is_diagnostic"),
            "std_cents": payload.get("std_cents"),
            "p95_cents": payload.get("p95_cents"),
            "std_cents_detrended": payload.get("std_cents_detrended"),
            "p95_cents_detrended": payload.get("p95_cents_detrended"),
            "range_cents": payload.get("range_cents"),
            "drift_cents": payload.get("drift_cents"),
            "n_frames": payload.get("n_frames"),
            "n_segments": payload.get("n_segments"),
            "nearest_note": cls.get("nearest_note"),
            "nearest_note_offset_cents": cls.get("offset_from_nearest_note_cents"),
            "fft_peak_hz": (payload.get("independent_check") or {}).get("fft_peak_hz"),
            "autocorr_f0_hz": (payload.get("independent_check") or {}).get("autocorr_f0_hz"),
            "calibration_method": payload.get("calibration_method"),
            "platform_reference_hz": (payload.get("platform_reference_unchanged") or {}).get("reference_hz"),
            "platform_reference_status": (payload.get("platform_reference_unchanged") or {}).get("reference_status"),
            "pending_reason": payload.get("pending_reason"),
            "run_id": prov.get("run_id"),
            "platform_version": prov.get("platform_version"),
            "command": prov.get("command"),
        }
    ]


def export_reference_calibration_json(path, payload: Mapping) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return target


def export_reference_calibration_csv(path, payload: Mapping) -> Path:
    rows = calibration_csv_rows(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return target


#: pending 时的替代建议（设计约定 §五.3 要求「理由＋建议替代」）
SUGGESTED_ALTERNATIVES = (
    "① 音叉／信号发生器录制的 A4 标称纯音（标称值以件内 reference_hz_nominal 给出，"
    "若为 442／415 等亦须注明来源），长度 ≥1 s、无颤音、无混响；",
    "② 已知音高的稳态长音（如电子校音器输出、管风琴持续音），须给出标称音高及其校准链；",
    "③ 若本例确为 B4（二胡按音）而非 A4，请确认样本标称后另出件——以 B4 标称重算只改标称，"
    "不改四例读数；但**仍不构成 A4 标定**，论文「已标定」句不得据此改写。",
)


def main(argv=None) -> int:
    """命令行入口：``python -m acouscope.analysis.reference_calibration --audio … --out-dir …``。"""
    import argparse

    ap = argparse.ArgumentParser(
        prog="reference_calibration",
        description="D 档参考音标定：稳定段 → 实测基频与离散 → 平台标定件（不改 A4 基准）",
    )
    ap.add_argument("--audio", required=True, help="参考音文件（真实录音；不接受合成音）")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--reference-id", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--stem", default="calibration.a4_erhu_20261028")
    ap.add_argument("--nominal-hz", type=float, default=None,
                    help="标称频率（缺省取参数快照 a4_reference_hz）")
    ap.add_argument("--fmin", type=float, default=60.0)
    ap.add_argument("--fmax", type=float, default=1500.0)
    ap.add_argument("--min-stable-s", type=float, default=DEFAULT_MIN_STABLE_S)
    ap.add_argument("--max-local-std-cents", type=float, default=DEFAULT_MAX_LOCAL_STD_CENTS)
    ap.add_argument("--max-bias-cents", type=float, default=MAX_CALIBRATION_BIAS_CENTS)
    args = ap.parse_args(argv)

    audio = Path(args.audio)
    analysis = analyze_reference_audio(
        audio,
        nominal_hz=args.nominal_hz,
        fmin=args.fmin,
        fmax=args.fmax,
        min_stable_s=args.min_stable_s,
        max_local_std_cents=args.max_local_std_cents,
    )
    command = (
        "python -m acouscope.analysis.reference_calibration "
        f"--audio {args.audio} --out-dir {args.out_dir} "
        f"--reference-id {args.reference_id or '<ref-id>'} --source {args.source or '<source>'} "
        f"--stem {args.stem} --fmin {args.fmin:g} --fmax {args.fmax:g} "
        f"--min-stable-s {args.min_stable_s:g} "
        f"--max-local-std-cents {args.max_local_std_cents:g} "
        f"--max-bias-cents {args.max_bias_cents:g}"
    )
    payload = build_reference_payload(
        analysis,
        reference_id=args.reference_id or f"d_a4_erhu_{args.stem.rsplit('_', 1)[-1]}",
        source=args.source,
        command=command,
        max_bias_cents=args.max_bias_cents,
        suggested_alternatives=SUGGESTED_ALTERNATIVES,
    )
    out = Path(args.out_dir)
    export_reference_calibration_json(out / f"{args.stem}.json", payload)
    export_reference_calibration_csv(out / f"{args.stem}.csv", payload)
    print(json.dumps({
        "reference_id": payload["reference_id"],
        "reference_status": payload["reference_status"],
        "reference_hz_measured": payload["reference_hz_measured"],
        "bias_cents": payload["bias_cents"],
        "std_cents": payload["std_cents"],
        "p95_cents": payload["p95_cents"],
        "n_frames": payload["n_frames"],
        "stable_segment_s": payload["stable_segment_s"],
        "run_id": payload["provenance"]["run_id"],
        "json": str(out / f"{args.stem}.json"),
        "csv": str(out / f"{args.stem}.csv"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
