# SPDX-License-Identifier: GPL-3.0-only
"""音频 → 律制推断候选（W-14-08／B6 的公开 helper）。

本模块只把**既有**三段能力接成一条公开路（不新造算法、不改任何阈值）：

``读窗 → stream_pitch → build_pcp → infer_tuning``

口径（设计约定 §3.9 逐条）：

- 推断**只用 f0／PCP**，不经过论文分析模板（不把「参照系模板」当推断先验）；
- 候选按 ``score`` 降序；每条带 ``template_source``（学术出处）与 ``margin``；
- 只给**候选排序**，**不写「符合某律／该曲属于某律」**——表述纪律与
  :mod:`acouscope.analysis.tuning_infer` 同规；
- 模板面：``template_keys=None`` ⇒ 内置**全部八项**（含印度/阿拉伯）；调用方
  可传论文六模板作子集，但**不得**改模板表本身（本模块不写 ``templates.py``）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .pcp import PCPParams, build_pcp
from .pitch_stream import stream_pitch
from .tuning_infer import infer_tuning
from .tunings.templates import TEMPLATE_KEYS, get_template

__all__ = [
    "INFER_FORMAT",
    "INFER_VERSION",
    "infer_tuning_from_audio",
    "matches_to_payload",
]

INFER_FORMAT = "acouscope-tuning-inference"
INFER_VERSION = 1


def _sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_window(audio_path, start_s: float, window_s: float):
    """读一个窗（单声道）；返回 ``(sig, sr, 实际窗起点)``（与出图层同口径）。"""
    import soundfile as sf

    info = sf.info(str(audio_path))
    sr = int(info.samplerate)
    w0 = float(int(float(start_s) // float(window_s)) * float(window_s))
    first = int(round(w0 * sr))
    frames = min(int(round(float(window_s) * sr)), int(info.frames) - first)
    if frames <= 0:
        raise ValueError(
            f"窗口越界：start_s={start_s} window_s={window_s} 时长={info.frames / sr:.3f}s"
        )
    data, _ = sf.read(
        str(audio_path), start=first, frames=frames, dtype="float64", always_2d=True
    )
    sig = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    return np.asarray(sig, dtype=float), sr, w0


def infer_tuning_from_audio(
    audio_path,
    *,
    window_start_s: float = 0.0,
    window_s: float = 30.0,
    fmin: float = 60.0,
    fmax: float = 1500.0,
    template_keys=None,
    top_k: int = 3,
) -> dict:
    """读窗 → 逐帧 f0 → PCP → 模板推断；返回可 JSON 序列化的候选表。

    参数
    ----
    audio_path : 音频路径
    window_start_s / window_s : 取数窗（按 ``window_s`` 对齐到窗格起点；换窗即换数）
    fmin / fmax : 逐帧 f0 提取的音域（与平台出图同口径）
    template_keys : 候选模板子集；``None`` ⇒ 内置全部八模板
    top_k : 返回条数（按 ``score`` 降序）

    返回
    ----
    ``{"format", "version", "matches": [...], "pcp": {...}, "source": {...},
    "template_pool": [...]}``；空/全零 PCP ⇒ ``matches == []``（不臆造结论）。
    """
    keys = tuple(TEMPLATE_KEYS if template_keys is None else template_keys)
    unknown = [key for key in keys if key not in TEMPLATE_KEYS]
    if unknown:
        raise KeyError(f"未知模板键：{unknown}（可用：{', '.join(TEMPLATE_KEYS)}）")

    sig, sr, w0 = _read_window(audio_path, window_start_s, window_s)
    track = stream_pitch(
        signal=sig, sr=sr, fmin=float(fmin), fmax=float(fmax), block_seconds=float(window_s)
    )
    f0 = np.asarray(track.f0_hz, dtype=float)
    confidence = np.asarray(track.confidence, dtype=float)
    pcp = build_pcp(
        f0, confidence, params=PCPParams(), ref_hz=float(get_template("12tet").reference_freq)
    )
    matches = infer_tuning(pcp, template_keys=list(keys), top_k=int(top_k))

    payload = {
        "format": INFER_FORMAT,
        "version": INFER_VERSION,
        "matches": [
            {
                "rank": rank,
                "template_key": match.template_key,
                "template_name": match.template_name,
                "template_source": match.template_source,
                "tonic_cents": round(float(match.tonic_cents), 4),
                "tonic_degree": int(match.tonic_degree),
                "score": round(float(match.score), 6),
                "runner_up_score": round(float(match.runner_up_score), 6),
                "margin": round(float(match.margin), 6),
            }
            for rank, match in enumerate(matches, 1)
        ],
        "pcp": {
            "n_bins": int(np.asarray(pcp.weights).size),
            "bin_cents": float(pcp.bin_cents),
            "cent_min": float(pcp.cent_min),
            "ref_hz": float(pcp.ref_hz),
            "n_frames_used": int(getattr(pcp, "n_frames_used", 0)),
            "weights_sum": round(float(np.asarray(pcp.weights).sum()), 6),
        },
        "source": {
            "audio_path": str(audio_path),
            "audio_name": Path(str(audio_path)).name,
            "audio_sha256": _sha256_file(audio_path),
            "window_start_s": float(w0),
            "window_s": float(window_s),
            "fmin": float(fmin),
            "fmax": float(fmax),
            "n_frames": int(f0.size),
            "template_keys": [str(key) for key in keys],
            "top_k": int(top_k),
            "method": "stream_pitch → build_pcp（120 bin／0–1200 音分）→ infer_tuning",
        },
        "template_pool": [str(key) for key in keys],
        "claim_note": (
            "候选排序，不称「符合某律」、不称「该曲属于某律」；"
            "得分只在本次窗与本次模板池内可比。"
        ),
    }
    return payload


def matches_to_payload(payload: dict) -> list[dict]:
    """候选表 → 表格行（GUI 表与 JSON 同源，逐值一致）。"""
    return [dict(item) for item in (payload.get("matches") or ())]
