# SPDX-License-Identifier: GPL-3.0-only
"""长录音分块流式 pYIN（T-003-1）。PITCH_STREAM_V1

- 候选提取：分块流水，块间携带 frame_size 样本重叠，保证与整段
  pyin_candidates 逐帧一致；峰值内存 O(block)。
- 解码：PitchHMM.decode(fixed_lag=100)，回溯缓冲 O(lag)。
- 后台：stream_pitch_async 在守护线程执行，不阻塞主线程。
底层算法（clean-room）见 analysis/pyin.py 与 analysis/pitch_hmm.py 的 docstring。
"""

from __future__ import annotations

import threading
from typing import Callable

import numpy as np

from acouscope.analysis.pitch import PitchTrack


def _iter_blocks_array(sig: np.ndarray, sr: float, block_samples: int, frame_size: int, hop_length: int):
    """ndarray 分块迭代（含重叠携带，保证帧与整段一致）。yields (global_start, block)。"""
    n = len(sig)
    pos = 0
    while pos < n:
        end = min(pos + block_samples, n)
        yield pos, sig[pos:end]
        # 下一块起点：本块内最后完整帧之后的 hop 位置
        n_frames = 1 + (end - pos - frame_size) // hop_length if end - pos >= frame_size else 0
        nxt = pos + n_frames * hop_length if n_frames > 0 else end
        if nxt <= pos:
            nxt = end
        pos = nxt
        if pos >= n:
            break


def _iter_blocks_file(path: str, sr_expected: float | None, block_samples: int, frame_size: int, hop_length: int):
    """文件分块迭代（soundfile 懒加载）。yields (global_start, block_float64)。"""
    import soundfile as sf

    with sf.SoundFile(path) as f:
        if sr_expected is not None and abs(f.samplerate - sr_expected) > 1:
            raise ValueError(f"采样率不符: 文件 {f.samplerate} vs 期望 {sr_expected}")
        pos = 0
        carry = np.zeros(0, dtype=np.float64)
        while True:
            raw = f.read(block_samples - len(carry), dtype="float64", always_2d=False)
            if raw.ndim > 1:
                raw = raw.mean(axis=1)
            block = np.concatenate([carry, raw]) if len(carry) else raw
            if len(block) == 0:
                break
            yield pos, block
            n_frames = 1 + (len(block) - frame_size) // hop_length if len(block) >= frame_size else 0
            consumed = n_frames * hop_length if n_frames > 0 else len(block)
            carry = block[consumed:]
            pos += consumed
            if len(raw) == 0:
                break


def stream_candidates(
    signal: "np.ndarray | None" = None,
    sr: "float | None" = None,
    path: "str | None" = None,
    block_seconds: float = 30.0,
    frame_size: int = 4096,
    hop_length: int = 256,
    fmin: float = 40.0,
    fmax: float = 2000.0,
    beta_mean: float = 0.15,
    progress: "Callable[[float, str], None] | None" = None,
    stats: "dict | None" = None,
):
    """分块流式提取 pYIN 候选。

    Returns:
        (times, cand_lists, voiced_probs)——与整段 pyin_candidates 等价。

    ``stats``（可选，**诊断面**，不影响算法）：传入空 dict 时回填**候选面**的
    原始计数与范围，供「网格边界钳位」类读数（T-14／W-6）**由候选面自身**成立，
    而不是由输出最小值反推（反推属被明令禁止的口径）。回填键：

    - ``frames``：帧数；``candidate_frames``：有候选的帧数；
    - ``candidate_count``：候选条目总数；
    - ``candidate_min_hz``／``candidate_max_hz``：候选频率范围（正有限值）；
    - ``grid_min_hz``：HMM 有效网格下界（``pitch_hmm.MIN_FREQ``，61.735 Hz）；
    - ``candidate_below_grid_min_frames``／``candidate_below_grid_min_count``：
      至少一个候选低于网格下界（装入时必被钳到最低格）的帧数与条目数；
    - ``_cand_below_mask``：逐帧布尔掩码（与返回的 ``times`` 等长，内部用）。
    """
    from acouscope.analysis.pyin import pyin_frame
    from acouscope.analysis.pitch_hmm import MIN_FREQ as _GRID_MIN_HZ

    if (signal is None) == (path is None):
        raise ValueError("signal 与 path 二选一")
    if path is not None and sr is None:
        import soundfile as sf

        sr = sf.info(path).samplerate
    sr = float(sr)

    block_samples = int(block_seconds * sr)
    if block_samples < frame_size:
        # 块长下限保护：默认 frame=4096 时 0.5s@8kHz=4000<4096，
        # 每块出 0 帧会导致流式无输出（2026-09-04 沙箱实测）
        block_samples = frame_size
    if signal is not None:
        blocks = _iter_blocks_array(np.asarray(signal), sr, block_samples, frame_size, hop_length)
        total = len(signal)
    else:
        blocks = _iter_blocks_file(path, sr, block_samples, frame_size, hop_length)
        import soundfile as sf

        total = sf.info(path).frames

    times_list: list[np.ndarray] = []
    cands_all: list = []
    voiced_list: list[np.ndarray] = []
    below_frames: list[np.ndarray] = []
    cand_count = 0
    cand_below_count = 0
    cand_min: float | None = None
    cand_max: float | None = None
    done = 0
    for start, block in blocks:
        b = np.asarray(block, dtype=np.float64)
        if len(b) < frame_size:
            break
        n_frames = 1 + (len(b) - frame_size) // hop_length
        strided = np.lib.stride_tricks.as_strided(
            b,
            shape=(n_frames, frame_size),
            strides=(b.strides[0] * hop_length, b.strides[0]),
        )
        blk_cands = []
        blk_voiced = np.zeros(n_frames)
        blk_below = np.zeros(n_frames, dtype=bool)
        for i in range(n_frames):
            c, vp = pyin_frame(strided[i], sr, fmin, fmax, beta_mean)
            blk_cands.append(c)
            blk_voiced[i] = vp
            if stats is not None:
                for f0, _p in c:
                    f0v = float(f0)
                    if not np.isfinite(f0v) or f0v <= 0.0:
                        continue
                    cand_count += 1
                    cand_min = f0v if cand_min is None else min(cand_min, f0v)
                    cand_max = f0v if cand_max is None else max(cand_max, f0v)
                    if f0v < float(_GRID_MIN_HZ):
                        cand_below_count += 1
                        blk_below[i] = True
        times_list.append((start + np.arange(n_frames) * hop_length + frame_size // 4) / sr)
        cands_all.extend(blk_cands)
        voiced_list.append(blk_voiced)
        if stats is not None:
            below_frames.append(blk_below)
        done = start + n_frames * hop_length
        if progress is not None:
            progress(min(done / max(total, 1), 1.0), "candidates")
    times = np.concatenate(times_list) if times_list else np.array([])
    voiced = np.concatenate(voiced_list) if voiced_list else np.array([])
    if stats is not None:
        mask = np.concatenate(below_frames) if below_frames else np.zeros(0, dtype=bool)
        stats.update(
            {
                "frames": int(len(cands_all)),
                "candidate_frames": int(sum(1 for c in cands_all if c)),
                "candidate_count": int(cand_count),
                "candidate_min_hz": cand_min,
                "candidate_max_hz": cand_max,
                "grid_min_hz": float(_GRID_MIN_HZ),
                "candidate_below_grid_min_frames": int(mask.sum()),
                "candidate_below_grid_min_count": int(cand_below_count),
                "_cand_below_mask": mask,
            }
        )
    return times, cands_all, voiced


def stream_pitch(
    signal: "np.ndarray | None" = None,
    sr: "float | None" = None,
    path: "str | None" = None,
    block_seconds: float = 30.0,
    frame_size: int = 4096,
    hop_length: int = 256,
    fmin: float = 40.0,
    fmax: float = 2000.0,
    cent_ref: "float | None" = None,
    fixed_lag: "int | None" = 100,
    progress: "Callable[[float, str], None] | None" = None,
    stats: "dict | None" = None,
) -> PitchTrack:
    """流式 pYIN：候选提取（O(block) 内存）+ 固定滞后解码（O(lag) 内存）。

    ``stats``（可选，**诊断面**）：传入空 dict 时回填候选面（见
    :func:`stream_candidates`）**与输出面**的计数／范围，两类**分列**
    （候选范围不得由输出范围反证）。输出面追加键：

    - ``voiced_frames``：解码为有声的帧数；
    - ``output_min_hz``／``output_max_hz``：HMM **输出**频率范围（有声帧）；
    - ``output_at_grid_min_frames``：解码状态落在最低格（bin 0）的有声帧数；
    - ``grid_freq_min_hz``／``grid_freq_max_hz``：有效网格两端（61.735 Hz 起）；
    - ``_output_at_grid_min_mask``：逐帧布尔掩码（内部用）。
    """
    from acouscope.analysis.pitch_hmm import PitchHMM

    times, cands, voiced = stream_candidates(
        signal=signal, sr=sr, path=path, block_seconds=block_seconds,
        frame_size=frame_size, hop_length=hop_length, fmin=fmin, fmax=fmax,
        progress=progress, stats=stats,
    )

    hmm = PitchHMM()
    n = len(cands)

    def decode_progress(frac: float, _stage: str) -> None:
        if progress is not None:
            progress(frac, "decode")

    # 分批喂给固定滞后 Viterbi（长序列时避免单次调用不可中断）
    res = hmm.decode(cands, fixed_lag=fixed_lag)
    if progress is not None:
        decode_progress(1.0, "decode")
    f0 = np.where(res.voiced & np.isfinite(res.f0_hz), res.f0_hz, np.nan)
    if stats is not None:
        states = np.asarray(res.states)
        voiced_mask = np.asarray(res.voiced, dtype=bool)
        at_min = voiced_mask & (states == 0)
        finite = f0[np.isfinite(f0)]
        stats.update(
            {
                "voiced_frames": int(voiced_mask.sum()),
                "output_min_hz": (float(finite.min()) if finite.size else None),
                "output_max_hz": (float(finite.max()) if finite.size else None),
                "output_at_grid_min_frames": int(at_min.sum()),
                "grid_freq_min_hz": float(hmm.grid_freqs[0]),
                "grid_freq_max_hz": float(hmm.grid_freqs[-1]),
                "_output_at_grid_min_mask": at_min,
            }
        )
    _ = n, decode_progress  # 进度语义保留
    return PitchTrack(
        times=times,
        f0_hz=f0,
        confidence=np.asarray(voiced, dtype=float),
        fmin=fmin,
        fmax=fmax,
        cent_ref=cent_ref,
    )


def stream_pitch_async(
    on_done: Callable[[PitchTrack], None],
    on_error: "Callable[[Exception], None] | None" = None,
    **kwargs,
) -> threading.Thread:
    """后台线程执行 stream_pitch（守护线程，不阻塞主线程）。"""

    def _run():
        try:
            result = stream_pitch(**kwargs)
            on_done(result)
        except Exception as exc:  # noqa: BLE001
            if on_error is not None:
                on_error(exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
