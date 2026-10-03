# SPDX-License-Identifier: GPL-3.0-only
"""T-1006 M2 多轨开头对齐：起点检测引擎 + 偏移合成 + 会话编排。

口径与红线（细则见需求说明 `内部记录/tasks/T-1006.txt` 与放行令 `RELEASE_T-1006.md`）：

- **无损语义**：本模块只产出「对齐偏移元数据」（`TrackModel.offset_ms`），
  **绝不裁剪 / 改写音频 buffer / 另存音频**；检测路径对输入数组只读。
- **帧能量复用** `analysis/temporal.py` 的 `TemporalAnalyzer.rms_db`
  （禁自行重写 RMS/分帧）；门限为**固定 dB 门限**（跨轨同门限才可比）。
  既有开头静默检测工具（`analysis/silence.py`）走**自适应阈值**（逐轨不同）、含
  preroll 预量、且全程静默与无静默都返回 0（**无法区分**）——不满足跨轨对齐与
  「无起点」判定的需要，故不作为主路径（理由另见 T-1006 报告 deviations）。
- **起点定义**：首个「连续有声 ≥ `min_speech_ms`」的帧起始时刻（毫秒）；
  全静默 / 空输入 / 采样率非法 → None（防御，不崩）。
- **多轨偏移**：参考轨（默认最早发声轨，可与 T-1005 口径一致地显式指定）
  为基线，`offset = 参考起点 − 本轨起点`（对齐后参考轨 0、其余 ≤ 0，
  即各轨前导静音被抛到时间轴左界之外；只影响呈现与后续测量基线）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# 检测参数（模块常量：禁代码内散落魔法数）
DEFAULT_GATE_DB = -36.0        # 有声门限（dBFS，相对满幅）
DEFAULT_MIN_SPEECH_MS = 200.0  # 连续有声判定时长（防单帧瞬态误判）
FRAME_MS = 10.0                # 分析帧长（毫秒）
HOP_MS = 10.0                  # 帧移（毫秒）

# 微调步进（轨道头 ±1ms / ±10ms）
NUDGE_FINE_MS = 1.0
NUDGE_COARSE_MS = 10.0
# 偏移可调范围（毫秒；防误输入导致轨道飞出时间轴）
OFFSET_MIN_MS = -60000.0
OFFSET_MAX_MS = 60000.0


def _frame_shape(sample_rate, frame_ms: float = FRAME_MS, hop_ms: float = HOP_MS):
    """返回 (sr, frame_size, hop_size)；采样率非法时返回 None。"""
    sr = int(sample_rate or 0)
    if sr <= 0:
        return None
    frame = max(1, int(round(sr * float(frame_ms) / 1000.0)))
    hop = max(1, int(round(sr * float(hop_ms) / 1000.0)))
    return sr, frame, hop


def frame_db_curve(audio, sample_rate, *, frame_ms: float = FRAME_MS, hop_ms: float = HOP_MS):
    """逐帧 RMS(dB) 曲线：复用 `analysis/temporal.py` 的 rms_db（禁重写分帧/RMS）。

    多声道逐声道求帧 RMS 后取**逐帧最大值**（任一声道有声即视为有声）。

    Args:
        audio: 音频数据，形状 (n,) 或 (n, channels)
        sample_rate: 采样率

    Returns:
        (times, db)：times 为帧起始时刻（秒），db 为帧 RMS(dBFS)；
        空输入 / 过短 / 采样率非法 → 两个空数组。
    """
    empty = (np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64))
    shape = _frame_shape(sample_rate, frame_ms, hop_ms)
    if shape is None:
        return empty
    sr, frame, hop = shape
    arr = np.asarray(audio)
    if arr.ndim == 0 or arr.size == 0:
        return empty
    if arr.ndim == 1:
        channels = [arr]
    elif arr.ndim == 2:
        channels = [arr[:, i] for i in range(arr.shape[1])]
    else:
        return empty

    from acouscope.analysis.temporal import TemporalAnalyzer

    analyzer = TemporalAnalyzer(sr)
    curves: list[np.ndarray] = []
    times = np.zeros(0, dtype=np.float64)
    for channel in channels:
        t, db = analyzer.rms_db(
            np.asarray(channel, dtype=np.float64), frame_size=frame, hop_size=hop
        )
        if db.size == 0:
            continue
        times = np.asarray(t, dtype=np.float64)
        curves.append(np.asarray(db, dtype=np.float64))
    if not curves:
        return empty
    n = min(c.size for c in curves)
    stacked = np.vstack([c[:n] for c in curves])
    return times[:n], stacked.max(axis=0)


def first_speech_frame(db, *, gate_db: float = DEFAULT_GATE_DB, frames_needed: int = 1):
    """首个「连续 ≥ frames_needed 帧有声」的起始帧号；无 → None。

    O(n) 单次前向扫描（分段边界用向量化差分求出，无逐样本 Python 循环）。
    """
    if db is None or np.asarray(db).size == 0:
        return None
    active = np.asarray(db, dtype=np.float64) >= float(gate_db)
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return None
    need = max(1, int(frames_needed))
    if need == 1:
        return int(idx[0])
    # 连续段切分：idx 内相邻差 > 1 即断点
    gaps = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([idx[0]], idx[gaps + 1]))
    ends = np.concatenate((idx[gaps], [idx[-1]]))
    long_enough = (ends - starts + 1) >= need
    if not long_enough.any():
        return None
    return int(starts[np.flatnonzero(long_enough)[0]])


def detect_onset_ms(
    audio,
    sample_rate,
    *,
    gate_db: float = DEFAULT_GATE_DB,
    min_speech_ms: float = DEFAULT_MIN_SPEECH_MS,
):
    """检测首个有声起点（毫秒）；全静默 / 空输入 / 无有效起点 → None。

    Args:
        audio: 音频数据 (n,) 或 (n, channels)；**只读**，不会被改写
        sample_rate: 采样率
        gate_db: 有声门限（dBFS，相对满幅）；各轨必须用同一门限才可比
        min_speech_ms: 连续有声判定时长（毫秒），防单帧瞬态误判

    Returns:
        首个有声帧起始毫秒（int）；无有效起点返回 None
    """
    times, db = frame_db_curve(audio, sample_rate)
    if db.size == 0:
        return None
    frames_needed = max(1, int(math.ceil(float(min_speech_ms) / float(HOP_MS))))
    index = first_speech_frame(db, gate_db=gate_db, frames_needed=frames_needed)
    if index is None:
        return None
    return int(round(float(times[index]) * 1000.0))


def clamp_offset_ms(value) -> float:
    """偏移夹紧到可调范围（毫秒）。"""
    return float(min(OFFSET_MAX_MS, max(OFFSET_MIN_MS, float(value))))


def nudge_offset_ms(current_ms, delta_ms) -> float:
    """在现有偏移上叠加一步微调（毫秒，夹紧）。"""
    return clamp_offset_ms(float(current_ms) + float(delta_ms))


def shifted_times(times, offset_ms) -> np.ndarray:
    """把包络时刻按对齐偏移平移（秒）；正偏移 = 内容右移。"""
    return np.asarray(times, dtype=np.float64) + float(offset_ms) / 1000.0


@dataclass
class AlignResult:
    """一次自动对齐的结果（纯数据，便于测试与呈现）。"""

    onsets: dict = field(default_factory=dict)          # track_id -> onset ms | None
    offsets: dict = field(default_factory=dict)         # track_id -> offset ms
    reference_id: str | None = None
    skipped: list = field(default_factory=list)         # 未检测到起点的轨（偏移不动）

    @property
    def applied(self) -> int:
        """本次写入偏移的轨数。"""
        return len(self.offsets)

    @property
    def reference_ms(self):
        return self.onsets.get(self.reference_id)


def choose_reference(onsets: dict, order, *, reference_id=None):
    """参考轨：显式指定（且已检出）优先；否则最早发声轨；并列取会话序在前者。"""
    if reference_id is not None and onsets.get(reference_id) is not None:
        return reference_id
    best = None
    for track_id in order:
        if onsets.get(track_id) is None:
            continue
        if best is None or onsets[track_id] < onsets[best]:
            best = track_id
    return best


def compute_offsets(onsets: dict, order, *, reference_id=None) -> AlignResult:
    """按参考轨合成各轨偏移（纯逻辑；未检出起点的轨不写偏移）。"""
    reference = choose_reference(onsets, order, reference_id=reference_id)
    result = AlignResult(
        onsets=dict(onsets), offsets={}, reference_id=reference, skipped=[],
    )
    if reference is None:
        result.skipped = list(order)
        return result
    base = onsets[reference]
    for track_id in order:
        onset = onsets.get(track_id)
        if onset is None:
            result.skipped.append(track_id)
            continue
        result.offsets[track_id] = float(base - onset)
    return result


def detect_session_onsets(
    session,
    *,
    gate_db: float = DEFAULT_GATE_DB,
    min_speech_ms: float = DEFAULT_MIN_SPEECH_MS,
) -> dict:
    """逐轨检测起点（毫秒）：经 `session.load_full` 载入样本（LRU 释放，内存有界）。"""
    onsets: dict = {}
    for track in session.tracks():
        data = session.load_full(track.track_id)
        if data is None:
            onsets[track.track_id] = None
            continue
        onsets[track.track_id] = detect_onset_ms(
            data, track.sample_rate, gate_db=gate_db, min_speech_ms=min_speech_ms,
        )
    return onsets


def align_session(
    session,
    *,
    gate_db: float = DEFAULT_GATE_DB,
    min_speech_ms: float = DEFAULT_MIN_SPEECH_MS,
    reference_id=None,
) -> AlignResult:
    """一键自动对齐（幂等覆盖）：检测 → 合成偏移 → 写 `TrackModel.offset_ms`。

    **只写偏移元数据**，不改动任何音频数据；未检出起点的轨保持原偏移并记入 skipped。
    """
    order = [track.track_id for track in session.tracks()]
    onsets = detect_session_onsets(
        session, gate_db=gate_db, min_speech_ms=min_speech_ms,
    )
    result = compute_offsets(onsets, order, reference_id=reference_id)
    for track_id, offset_ms in result.offsets.items():
        session.set_offset_ms(track_id, offset_ms)
    return result
