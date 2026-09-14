# SPDX-License-Identifier: GPL-3.0-only
"""开头静默检测（去除开头静默功能的核心算法）。

设计原则（保障音频数据安全，宁可少剪、不可剪掉有效声音）：
- 纯 numpy 短时 RMS 包络（帧 20ms、步进 10ms，逐声道取最大）
- 阈值自适应：max(峰值RMS × 1%即-40dB, 本底RMS × 2.5倍即+8dB, 绝对下限 1e-5)
- 要求连续 40ms 超过阈值才认定声音开始（避免瞬间咔哒声误判）
- 起点前再保留 10ms 预备量（防止切掉起振瞬间）
"""

from __future__ import annotations

import numpy as np

# 检测参数（秒）
FRAME_SEC = 0.020
HOP_SEC = 0.010
HOLD_SEC = 0.040   # 连续超过阈值的时长，认定声音开始
PREROLL_SEC = 0.010  # 起点前保留量

# 阈值参数
PEAK_RATIO = 0.01    # 峰值 RMS 的 1%（≈ -40 dB）
FLOOR_RATIO = 2.5    # 本底 RMS 的 2.5 倍（≈ +8 dB）
ABS_FLOOR = 1e-5     # 绝对下限（数字静默的量化噪声级）


def detect_leading_silence(
    data: np.ndarray,
    sample_rate: int,
    frame_sec: float = FRAME_SEC,
    hop_sec: float = HOP_SEC,
    hold_sec: float = HOLD_SEC,
    preroll_sec: float = PREROLL_SEC,
) -> int:
    """检测音频开头静默的采样点数。

    Args:
        data: 音频数据，形状 (n,) 或 (n, channels)
        sample_rate: 采样率
        frame_sec: 分析帧长（秒）
        hop_sec: 帧移（秒）
        hold_sec: 连续有声判定时长（秒）
        preroll_sec: 检测起点前保留时长（秒）

    Returns:
        开头静默的采样点数（含保留量；全程静默返回 0，
        无静默返回 0）
    """
    x = np.asarray(data, dtype=np.float64)
    if x.ndim == 2:
        # 多声道：逐帧取各声道最大幅度（任一声道有声即有声）
        mono = np.max(np.abs(x), axis=1)
    else:
        mono = np.abs(x)

    n = len(mono)
    if n == 0 or sample_rate <= 0:
        return 0

    frame = max(1, int(round(frame_sec * sample_rate)))
    hop = max(1, int(round(hop_sec * sample_rate)))

    # 短时 RMS（滑动窗口均方根）
    n_frames = max(1, (n - frame) // hop + 1)
    rms = np.empty(n_frames, dtype=np.float64)
    for i in range(n_frames):
        seg = mono[i * hop : i * hop + frame]
        rms[i] = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0

    peak_rms = float(np.max(rms))
    if peak_rms <= ABS_FLOOR:
        return 0  # 全程静默，不做处理（避免剪成空文件）

    # 本底噪声估计：开头 0.5s 与全程 10% 分位中的较大者
    head_frames = max(1, int(0.5 / hop_sec))
    floor_est = max(
        float(np.mean(rms[: min(head_frames, n_frames)])),
        float(np.percentile(rms, 10)),
    )

    threshold = max(peak_rms * PEAK_RATIO, floor_est * FLOOR_RATIO, ABS_FLOOR)

    # 连续超过阈值 hold 帧才算声音开始
    hold_frames = max(1, int(round(hold_sec / hop_sec)))
    above = rms > threshold
    run = 0
    onset_frame = -1
    for i, a in enumerate(above):
        if a:
            run += 1
            if run >= hold_frames:
                onset_frame = i - run + 1  # 连续段的第一帧
                break
        else:
            run = 0

    if onset_frame <= 0:
        return 0  # 开头即有声（或全程未检测到有效声音）

    # 声音起点采样位置，再前移保留量（下限 0，且不剪掉超过 60% 的数据）
    onset_sample = onset_frame * hop
    preroll = int(round(preroll_sec * sample_rate))
    cut = max(0, onset_sample - preroll)
    cut = min(cut, int(n * 0.6))
    return int(cut)
