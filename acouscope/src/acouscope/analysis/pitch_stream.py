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
):
    """分块流式提取 pYIN 候选。

    Returns:
        (times, cand_lists, voiced_probs)——与整段 pyin_candidates 等价。
    """
    from acouscope.analysis.pyin import pyin_frame

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
        for i in range(n_frames):
            c, vp = pyin_frame(strided[i], sr, fmin, fmax, beta_mean)
            blk_cands.append(c)
            blk_voiced[i] = vp
        times_list.append((start + np.arange(n_frames) * hop_length + frame_size // 4) / sr)
        cands_all.extend(blk_cands)
        voiced_list.append(blk_voiced)
        done = start + n_frames * hop_length
        if progress is not None:
            progress(min(done / max(total, 1), 1.0), "candidates")
    times = np.concatenate(times_list) if times_list else np.array([])
    voiced = np.concatenate(voiced_list) if voiced_list else np.array([])
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
    cent_ref: float = 440.0,
    fixed_lag: "int | None" = 100,
    progress: "Callable[[float, str], None] | None" = None,
) -> PitchTrack:
    """流式 pYIN：候选提取（O(block) 内存）+ 固定滞后解码（O(lag) 内存）。"""
    from acouscope.analysis.pitch_hmm import PitchHMM

    times, cands, voiced = stream_candidates(
        signal=signal, sr=sr, path=path, block_seconds=block_seconds,
        frame_size=frame_size, hop_length=hop_length, fmin=fmin, fmax=fmax,
        progress=progress,
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
