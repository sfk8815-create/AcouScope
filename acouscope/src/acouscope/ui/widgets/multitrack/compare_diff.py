# SPDX-License-Identifier: GPL-3.0-only
"""T-1005 多轨差异量化层（纯 numpy；以参考轨为基准的逐轨量化）。

口径（放行令裁定，逐条落实）：
- **G′ 差异网格 = 12TET 先行**：差异值报**客观音分差** ``Δcent = 1200·log2(f2/f1)``
  （``f1 / f2 > 0``），**与律制无关**；单位 **Δcent 报主、ΔHz 报辅**。12TET 仅用于
  显示参考半音线 / 吸附 / 单位默认档；本模块**不接入任何音律**（任意律扩展另立任务）。
- **H′ 超阈默认 50 cents**：阈值经 ``Settings`` 可配置（10–200，越界回退 50），
  **报警阈值，非精度承诺**；超阈判据 = ``|Δcent| > 阈值``（严格超出，恰在阈值上不计入）；
  严禁与 ``PITCH_analysis.md §3.4`` 的单轨测量精度硬闸门
  （AT-01-1 ≤±10 / AT-01-2 ≤±15 cent）混用——两者语义不同。
- **I′ 帧率不一致 → 交集时间轴**：只比较两轨**都存在有声帧**的时间点，配对口径 =
  最近帧 + 容差（半个较粗帧移）；**不插值、不静默升采样**。
- **J′ CSV 写盘范式**：参考 ``annotation/export.py:76 export_pitches_csv``
  （``csv.writer`` + ``repr`` 保精度可逆）；**不调用** ``SessionMetadata.to_csv``（该链路已断）。
- 帧处理：``unvoiced / 0 Hz / NaN`` 帧跳过（分母为 0 或非正亦跳过），**禁输出错误数值**。
- 只读引用：``dsp/units``（音分换算，尊重用户 A4 参考）、``analysis/temporal``（RMS，
  禁重写分帧/RMS）。全程 O(n)，无第三方依赖。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field

import numpy as np

# ----------------------------------------------------------------------
# 常量（阈值/单位/列名）
# ----------------------------------------------------------------------

DEFAULT_THRESHOLD_CENTS = 50.0        # 报警阈值默认（cents）
THRESHOLD_MIN_CENTS = 10.0            # 可配置下限（越界回退默认）
THRESHOLD_MAX_CENTS = 200.0           # 可配置上限（越界回退默认）
THRESHOLD_RTOL = 1e-9                 # 超阈判据的浮点容差（恰在阈值上不计入）
DEFAULT_RMS_WINDOW_MS = 50.0          # RMS 窗（毫秒，可调）

UNIT_HZ = "hz"
UNIT_CENTS = "cents"
UNITS = (UNIT_HZ, UNIT_CENTS)
DEFAULT_UNIT = UNIT_CENTS             # 12TET 先行：默认以音分报主

PAIR_MODE_INTERSECTION = "intersection_nearest_frame"
SEMITONE_CENTS = 100.0                # 12TET 半音（仅显示参考/吸附用，不参与差异计算）

# CSV 表头 = 轨 / 时间 / ΔHz / Δcent / 超阈标记 / 参考轨名（ASCII 稳定键，中文列名见注记）
CSV_HEADER = ("track", "time_s", "delta_hz", "delta_cent",
              "over_threshold", "reference_track")
CSV_COLUMN_NAMES = {
    "track": "轨", "time_s": "时间(s)", "delta_hz": "ΔHz",
    "delta_cent": "Δcent", "over_threshold": "超阈标记(1=超阈)",
    "reference_track": "参考轨名",
}

_MIN_TOLERANCE_S = 1e-6
_RATE_EQUAL_RTOL = 1e-6

__all__ = [
    "DEFAULT_THRESHOLD_CENTS", "THRESHOLD_MIN_CENTS", "THRESHOLD_MAX_CENTS",
    "DEFAULT_RMS_WINDOW_MS", "UNIT_HZ", "UNIT_CENTS", "UNITS", "DEFAULT_UNIT",
    "PAIR_MODE_INTERSECTION", "SEMITONE_CENTS", "CSV_HEADER", "CSV_COLUMN_NAMES",
    "normalize_threshold", "settings_threshold", "voiced_mask", "frame_hop_s",
    "pair_frames", "delta_hz", "delta_cents", "over_threshold_mask", "format_delta",
    "overall_rms_db", "rms_diff_db", "TrackDiff", "DiffSummary",
    "compare_track", "build_diff_summary", "iter_diff_rows", "write_diff_csv",
]


def normalize_threshold(value) -> float:
    """报警阈值归一（非法/越界 [10, 200] → 回退默认 50；**非精度承诺**）。"""
    try:
        cents = float(value)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD_CENTS
    if not np.isfinite(cents) or not (THRESHOLD_MIN_CENTS <= cents <= THRESHOLD_MAX_CENTS):
        return DEFAULT_THRESHOLD_CENTS
    return cents


def settings_threshold() -> float:
    """从用户 ``Settings`` 读报警阈值（缺字段/读盘异常 → 默认 50）。"""
    try:
        from acouscope.utils.config import Settings

        return normalize_threshold(
            getattr(Settings.load(), "multitrack_diff_threshold_cents",
                    DEFAULT_THRESHOLD_CENTS)
        )
    except Exception:  # noqa: BLE001 - 配置不可读时回退默认，不影响分析
        return DEFAULT_THRESHOLD_CENTS


def voiced_mask(f0) -> np.ndarray:
    """有声帧掩码（``NaN`` / 非正频率 = 未检出，禁参与任何数值计算）。"""
    values = np.asarray(f0, dtype=float).ravel()
    with np.errstate(invalid="ignore"):
        return np.isfinite(values) & (values > 0.0)


def frame_hop_s(times) -> float:
    """帧移（相邻帧时间差的中位数；不足 2 帧/无正差 → 0.0）。"""
    values = np.asarray(times, dtype=float).ravel()
    values = values[np.isfinite(values)]
    if values.size < 2:
        return 0.0
    diffs = np.diff(np.sort(values))
    diffs = diffs[diffs > 0.0]
    if diffs.size == 0:
        return 0.0
    return float(np.median(diffs))


def pair_frames(ref_times, other_times, *, tolerance_s=None) -> dict:
    """交集时间轴配对（裁定 I′）：**最近帧 + 容差**，不插值、不升采样。

    仅在两轨共同覆盖的时间窗内比较；无对应帧（超出容差）者计入
    ``dropped_frames``。返回 ``ref_index / other_index``（各自入参数组下标）、
    配对时间 ``times``（共享基线）、帧移与容差等口径字段。
    """
    ref = np.asarray(ref_times, dtype=float).ravel()
    other = np.asarray(other_times, dtype=float).ravel()
    ref_ok, other_ok = np.isfinite(ref), np.isfinite(other)
    ref, other = ref[ref_ok], other[other_ok]
    hop_ref, hop_other = frame_hop_s(ref), frame_hop_s(other)
    frame = {
        "ref_index": np.zeros(0, dtype=int), "other_index": np.zeros(0, dtype=int),
        "times": np.zeros(0, dtype=float), "other_times": np.zeros(0, dtype=float),
        "pairs": 0, "dropped_frames": 0,
        "hop_ref_s": hop_ref, "hop_other_s": hop_other,
        "tolerance_s": 0.0, "frame_rates_equal": False,
        "overlap_start": None, "overlap_end": None,
        "ref_frames": int(ref.size), "other_frames": int(other.size),
        "mode": PAIR_MODE_INTERSECTION,
    }
    if ref.size == 0 or other.size == 0:
        return frame

    tolerance = (max(hop_ref, hop_other) * 0.5 if tolerance_s is None
                 else float(tolerance_s))
    if not np.isfinite(tolerance) or tolerance <= 0.0:
        tolerance = _MIN_TOLERANCE_S
    frame["tolerance_s"] = float(tolerance)
    frame["frame_rates_equal"] = bool(
        hop_ref > 0.0 and hop_other > 0.0
        and abs(hop_ref - hop_other) <= max(hop_ref, hop_other) * _RATE_EQUAL_RTOL
    )

    order_ref = np.argsort(ref, kind="stable")
    order_other = np.argsort(other, kind="stable")
    ref_sorted, other_sorted = ref[order_ref], other[order_other]

    start = max(float(ref_sorted[0]), float(other_sorted[0]))
    end = min(float(ref_sorted[-1]), float(other_sorted[-1]))
    if end < start:
        return frame
    frame["overlap_start"], frame["overlap_end"] = start, end

    lo = int(np.searchsorted(ref_sorted, start, side="left"))
    hi = int(np.searchsorted(ref_sorted, end, side="right"))
    window = ref_sorted[lo:hi]
    if window.size == 0:
        return frame

    insert = np.searchsorted(other_sorted, window)
    upper = np.clip(insert, 0, other_sorted.size - 1)
    lower = np.clip(insert - 1, 0, other_sorted.size - 1)
    d_upper = np.abs(other_sorted[upper] - window)
    d_lower = np.abs(other_sorted[lower] - window)
    nearest = np.where(d_lower < d_upper, lower, upper)
    distance = np.abs(other_sorted[nearest] - window)
    keep = distance <= tolerance

    frame["pairs"] = int(np.count_nonzero(keep))
    frame["dropped_frames"] = int(window.size - frame["pairs"])
    if frame["pairs"] == 0:
        return frame
    pos = np.nonzero(keep)[0]
    frame["times"] = window[pos]
    frame["other_times"] = other_sorted[nearest[pos]]
    frame["ref_index"] = order_ref[lo + pos]
    frame["other_index"] = order_other[nearest[pos]]
    return frame


def delta_hz(f_ref, f_other) -> np.ndarray:
    """辅口径：逐配对帧频率差 ``f2 - f1``（Hz；调用方保证两侧 > 0）。"""
    return np.asarray(f_other, dtype=float) - np.asarray(f_ref, dtype=float)


def delta_cents(f_ref, f_other, ref_hz=None) -> np.ndarray:
    """主口径：客观音分差 ``Δcent = 1200·log2(f2/f1)``（与律制无关）。

    经 ``dsp.units.hz_to_cents`` 以**用户 A4 参考**分别换算后相减：同一参考相减抵消，
    故差值数学上与 A4 无关，同时保证换算链路口径与全应用一致。
    """
    from acouscope.dsp.units import hz_to_cents

    f1 = np.asarray(f_ref, dtype=float)
    f2 = np.asarray(f_other, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        c1 = np.asarray(hz_to_cents(f1, ref_hz), dtype=float)
        c2 = np.asarray(hz_to_cents(f2, ref_hz), dtype=float)
    return c2 - c1


def over_threshold_mask(delta_cent, threshold_cents: float = DEFAULT_THRESHOLD_CENTS):
    """超阈掩码：``|Δcent| > 阈值``（**严格超出**；恰在阈值上不计入）。

    判据带 ``THRESHOLD_RTOL`` 相对容差，避免构造值/实测值在阈值边界上因浮点尾差翻转。
    """
    values = np.asarray(delta_cent, dtype=float)
    threshold = normalize_threshold(threshold_cents)
    with np.errstate(invalid="ignore"):
        return np.abs(values) > threshold * (1.0 + THRESHOLD_RTOL) + _MIN_TOLERANCE_S


def format_delta(value, unit: str = DEFAULT_UNIT) -> str:
    """差异读数格式化（单位切换 Hz/cents；无值 → ``--``）。"""
    if value is None or not np.isfinite(float(value)):
        return "--"
    value = float(value)
    if unit == UNIT_HZ:
        return f"{value:+.2f} Hz"
    return f"{value:+.1f} cents"


def overall_rms_db(audio, sample_rate, *, window_ms: float = DEFAULT_RMS_WINDOW_MS):
    """整体电平（dBFS，帧 RMS 中位值）；窗长按采样率换算后复用 ``rms_db``。

    不可测（无音频 / 采样率非法 / 短于一帧）→ ``None``（**不臆造数值**）。
    多声道取逐帧最大值（任一声道有声即视为有声，与 T-1006 帧能量口径一致）。
    """
    if audio is None or not sample_rate or float(sample_rate) <= 0.0:
        return None
    frame = int(round(float(sample_rate) * float(window_ms) / 1000.0))
    if frame <= 0:
        return None
    hop = max(1, frame // 2)
    data = np.asarray(audio)
    if data.ndim == 1:
        channels = [data]
    else:
        channels = [data[:, index] for index in range(data.shape[-1])]

    from acouscope.analysis.temporal import TemporalAnalyzer

    analyzer = TemporalAnalyzer(float(sample_rate))
    curves: list[np.ndarray] = []
    for channel in channels:
        _times, db = analyzer.rms_db(
            np.asarray(channel, dtype=np.float64), frame_size=frame, hop_size=hop
        )
        db = np.asarray(db, dtype=np.float64)
        if db.size:
            curves.append(db)
    if not curves:
        return None
    size = min(curve.size for curve in curves)
    if size == 0:
        return None
    stacked = np.vstack([curve[:size] for curve in curves])
    return float(np.median(stacked.max(axis=0)))


def rms_diff_db(ref_audio, other_audio, sample_rate, *,
                window_ms: float = DEFAULT_RMS_WINDOW_MS):
    """电平差 ``other - ref``（dB；任一侧不可测 → ``None``）。"""
    if ref_audio is None or other_audio is None:
        return None
    ref_db = overall_rms_db(ref_audio, sample_rate, window_ms=window_ms)
    other_db = overall_rms_db(other_audio, sample_rate, window_ms=window_ms)
    if ref_db is None or other_db is None:
        return None
    return float(other_db - ref_db)


# ----------------------------------------------------------------------
# 结果结构（逐轨差异 + 全轨对参考的一致性摘要）
# ----------------------------------------------------------------------


@dataclass
class TrackDiff:
    """一条非参考轨 vs 参考轨的差异（帧级数组 + 统计量；空 = 无可比帧）。"""

    track_id: str
    label: str
    color_index: int = 0
    times: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=float))
    delta_hz: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=float))
    delta_cent: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=float))
    over_threshold: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    threshold_cents: float = DEFAULT_THRESHOLD_CENTS
    pairs: int = 0
    hop_s: float = 0.0
    skipped_unvoiced_ref: int = 0
    skipped_unvoiced_other: int = 0
    dropped_frames: int = 0
    pairing: dict = field(default_factory=dict)
    duration_s: float | None = None
    duration_diff_s: float | None = None
    rms_db_ref: float | None = None
    rms_db: float | None = None
    rms_diff_db: float | None = None
    mean_delta_hz: float | None = None
    mean_delta_cent: float | None = None
    mean_abs_delta_cent: float | None = None
    max_abs_delta_cent: float | None = None
    over_count: int = 0

    @property
    def over_ratio(self) -> float | None:
        """超阈**时长占比**（配对帧等权 → 帧数占比；无可比帧 → None）。"""
        if not self.pairs:
            return None
        return self.over_count / float(self.pairs)

    @property
    def over_time_s(self) -> float:
        """超阈时长（秒，按配对帧移折算）。"""
        return float(self.over_count) * float(self.hop_s)

    @property
    def voiced_time_s(self) -> float:
        """可比有声时长（秒，按配对帧移折算）。"""
        return float(self.pairs) * float(self.hop_s)


@dataclass
class DiffSummary:
    """参考轨基准下的全轨差异汇总（供视觉/CSV 出口消费）。"""

    reference_id: str | None = None
    reference_label: str = ""
    threshold_cents: float = DEFAULT_THRESHOLD_CENTS
    unit: str = DEFAULT_UNIT
    tracks: list[TrackDiff] = field(default_factory=list)
    pairing: dict = field(default_factory=dict)

    def has_data(self) -> bool:
        """是否存在可比帧（无 → 不画差异条、不导出数据行）。"""
        return any(track.pairs for track in self.tracks)

    def consistency(self) -> dict:
        """全轨对参考的一致性摘要（纯数值；不含任何"达标"判定）。"""
        entries = [track for track in self.tracks if track.pairs > 0]
        if not entries:
            return {
                "compared_tracks": 0, "tracks_total": len(self.tracks),
                "mean_over_ratio": None, "max_over_ratio": None,
                "worst_track_id": None, "worst_track_label": "",
                "tracks_with_any_over": 0, "all_within_alarm_threshold": None,
                "mean_abs_delta_cent": None, "max_abs_delta_cent": None,
            }
        ratios = [float(track.over_ratio) for track in entries]
        worst = entries[int(np.argmax(ratios))]
        return {
            "compared_tracks": len(entries),
            "tracks_total": len(self.tracks),
            "mean_over_ratio": float(np.mean(ratios)),
            "max_over_ratio": float(np.max(ratios)),
            "worst_track_id": worst.track_id,
            "worst_track_label": worst.label,
            "tracks_with_any_over": int(sum(1 for t in entries if t.over_count > 0)),
            "all_within_alarm_threshold": bool(
                all(t.over_count == 0 for t in entries)
            ),
            "mean_abs_delta_cent": float(
                np.mean([t.mean_abs_delta_cent for t in entries])
            ),
            "max_abs_delta_cent": float(
                max(t.max_abs_delta_cent for t in entries)
            ),
        }


# ----------------------------------------------------------------------
# 量化主路径
# ----------------------------------------------------------------------


def compare_track(reference, other, *, threshold_cents: float = DEFAULT_THRESHOLD_CENTS,
                  rms_window_ms: float = DEFAULT_RMS_WINDOW_MS,
                  ref_audio=None, ref_sample_rate: float = 0.0,
                  other_audio=None, other_sample_rate: float = 0.0,
                  ref_duration_s=None, other_duration_s=None) -> TrackDiff:
    """一条非参考轨 vs 参考轨：ΔHz / Δcent / 超阈占比 / RMS 差 / 时长差 / 均值·最大。

    ``reference`` / ``other`` 只需提供 ``times`` 与 ``f0_hz``（鸭子类型，避免呈现层循环依赖）。
    """
    threshold = normalize_threshold(threshold_cents)
    result = TrackDiff(
        track_id=str(getattr(other, "track_id", "") or ""),
        label=str(getattr(other, "label", "") or getattr(other, "track_id", "") or ""),
        color_index=int(getattr(other, "color_index", 0) or 0),
        threshold_cents=threshold,
    )

    ref_times = np.asarray(getattr(reference, "times", ()), dtype=float).ravel()
    ref_f0 = np.asarray(getattr(reference, "f0_hz", ()), dtype=float).ravel()
    oth_times = np.asarray(getattr(other, "times", ()), dtype=float).ravel()
    oth_f0 = np.asarray(getattr(other, "f0_hz", ()), dtype=float).ravel()
    size = min(ref_times.size, ref_f0.size)
    ref_times, ref_f0 = ref_times[:size], ref_f0[:size]
    size = min(oth_times.size, oth_f0.size)
    oth_times, oth_f0 = oth_times[:size], oth_f0[:size]

    ref_voiced, oth_voiced = voiced_mask(ref_f0), voiced_mask(oth_f0)
    result.skipped_unvoiced_ref = int(ref_voiced.size - np.count_nonzero(ref_voiced))
    result.skipped_unvoiced_other = int(oth_voiced.size - np.count_nonzero(oth_voiced))

    pairing = pair_frames(ref_times[ref_voiced], oth_times[oth_voiced])
    result.pairing = {
        key: value for key, value in pairing.items()
        if key not in ("ref_index", "other_index", "times", "other_times")
    }
    result.dropped_frames = int(pairing["dropped_frames"])
    result.hop_s = float(max(pairing["hop_ref_s"], pairing["hop_other_s"]))
    pairs = int(pairing["pairs"])
    result.pairs = pairs

    if pairs:
        f1 = ref_f0[ref_voiced][pairing["ref_index"]]
        f2 = oth_f0[oth_voiced][pairing["other_index"]]
        result.times = np.asarray(pairing["times"], dtype=float)
        result.delta_hz = delta_hz(f1, f2)
        result.delta_cent = delta_cents(f1, f2)
        result.over_threshold = over_threshold_mask(result.delta_cent, threshold)
        result.over_count = int(np.count_nonzero(result.over_threshold))
        result.mean_delta_hz = float(np.mean(result.delta_hz))
        result.mean_delta_cent = float(np.mean(result.delta_cent))
        result.mean_abs_delta_cent = float(np.mean(np.abs(result.delta_cent)))
        result.max_abs_delta_cent = float(np.max(np.abs(result.delta_cent)))

    # 时长差（元数据可得时；不可得 → None，不臆造）
    ref_duration = _as_float(ref_duration_s if ref_duration_s is not None
                             else getattr(reference, "duration_s", None))
    oth_duration = _as_float(other_duration_s if other_duration_s is not None
                             else getattr(other, "duration_s", None))
    if oth_duration is not None:
        result.duration_s = oth_duration
    if ref_duration is not None and oth_duration is not None:
        result.duration_diff_s = oth_duration - ref_duration

    # 电平差（需两轨样本均在内存；不可测 → None）
    if ref_audio is not None and other_audio is not None:
        ref_db = overall_rms_db(ref_audio, ref_sample_rate, window_ms=rms_window_ms)
        oth_db = overall_rms_db(other_audio, other_sample_rate, window_ms=rms_window_ms)
        result.rms_db_ref = ref_db
        result.rms_db = oth_db
        if ref_db is not None and oth_db is not None:
            result.rms_diff_db = float(oth_db - ref_db)
    return result


def _as_float(value):
    """宽松转 float（None / 非数值 / 非有限 → None）。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def build_diff_summary(series_list, *, reference_id=None,
                       threshold_cents: float | None = None,
                       unit: str = DEFAULT_UNIT,
                       rms_window_ms: float = DEFAULT_RMS_WINDOW_MS,
                       rms_provider=None, duration_provider=None) -> DiffSummary:
    """参考轨基准的全轨差异汇总（参考轨默认 `series_list` 首项）。

    ``rms_provider(track_id) -> (audio, sample_rate) | None``：仅在样本已载入内存时给值；
    ``duration_provider(track_id) -> float | None``：时长（秒）。
    """
    series = [item for item in (series_list or ())]
    threshold = normalize_threshold(
        settings_threshold() if threshold_cents is None else threshold_cents
    )
    if not series:
        return DiffSummary(None, "", threshold, unit, [], {})
    reference = None
    if reference_id is not None:
        reference = next(
            (item for item in series
             if str(getattr(item, "track_id", "")) == str(reference_id)), None
        )
    if reference is None:
        reference = series[0]
    ref_track_id = str(getattr(reference, "track_id", "") or "")

    ref_audio = ref_sr = None
    ref_duration = None
    if rms_provider is not None:
        loaded = rms_provider(ref_track_id)
        if loaded:
            ref_audio, ref_sr = loaded
    if duration_provider is not None:
        ref_duration = duration_provider(ref_track_id)

    tracks: list[TrackDiff] = []
    for item in series:
        if str(getattr(item, "track_id", "")) == ref_track_id:
            continue
        track_id = str(getattr(item, "track_id", "") or "")
        other_audio = other_sr = None
        if rms_provider is not None:
            loaded = rms_provider(track_id)
            if loaded:
                other_audio, other_sr = loaded
        tracks.append(compare_track(
            reference, item, threshold_cents=threshold, rms_window_ms=rms_window_ms,
            ref_audio=ref_audio, ref_sample_rate=ref_sr or 0.0,
            other_audio=other_audio, other_sample_rate=other_sr or 0.0,
            ref_duration_s=ref_duration,
            other_duration_s=duration_provider(track_id) if duration_provider else None,
        ))

    # 汇总口径：帧率/交集信息取「可比帧最多的轨」（无配对轨则退回首条）
    overall = {}
    if tracks:
        chosen = max(tracks, key=lambda track: track.pairs)
        overall = dict(chosen.pairing)
    overall["unit"] = str(unit)
    return DiffSummary(
        reference_id=ref_track_id or None,
        reference_label=str(getattr(reference, "label", "") or ref_track_id),
        threshold_cents=threshold, unit=str(unit), tracks=tracks, pairing=overall,
    )


# ----------------------------------------------------------------------
# CSV 出口（裁定 J′：csv.writer + repr）
# ----------------------------------------------------------------------


def iter_diff_rows(summary: DiffSummary):
    """逐帧差异行（表头顺序：轨 / 时间 / ΔHz / Δcent / 超阈标记 / 参考轨名）。"""
    for track in summary.tracks:
        for index in range(track.pairs):
            yield [
                track.label,
                repr(float(track.times[index])),
                repr(float(track.delta_hz[index])),
                repr(float(track.delta_cent[index])),
                repr(int(bool(track.over_threshold[index]))),
                summary.reference_label,
            ]


def write_diff_csv(path, summary: DiffSummary) -> int:
    """写差异表 CSV（``csv.writer`` + ``repr`` 保精度可逆）；返回数据行数。"""
    rows = 0
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for row in iter_diff_rows(summary):
            writer.writerow(row)
            rows += 1
    return rows
