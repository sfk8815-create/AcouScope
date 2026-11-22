# SPDX-License-Identifier: GPL-3.0-only
"""双口径音级归属：绝对（A4 校准）与相对主音（拟合归一）。

口径分工（2026-10-25 确定，约定-20261025-P2R2 后续）：
- ``absolute``：按 A4 基准（``dsp.units.get_reference_hz()``，默认 440 Hz，可注入
  415／432／442 等）校准后按律制网格归属。**暴露**录音转速偏差，用于与文献具体
  音高对拍；不改写任何音高。
- ``main_tone``：先拟合主音并整体移调归一，再按同一律制网格归属。用于三型判定、
  跨版对照与类型学检验。**主音拟合是一次推断，必须可审计**：本模块同时输出
  拟合方法参数、拟合度、候选排序与误判敏感性所需的第二候选。

两套口径并存、互不覆盖；每行带 ``ref_mode`` 字段，禁止把两套结果合并成一套。

主音拟合的两阶段（任务-20261025-主音两阶段；口径冻结表 v2.7）：

- **偏移与主音不是同一类量。** 偏移属演奏实践（定弦、转速、传承）或文献，主音属
  乐学判断。两量同时未知时，整体平移与主音选择在音级类分布上等价——「主音 X 偏移
  ＋100」与「主音 Y 偏移 −20」可能给出同一条拟合曲线，**主音不可识别**。
- 故 :func:`fit_tonic` 把偏移作为**显式输入**（``anchor_offset_cents``）：先按锚归一
  （``stage="two_stage"``），再在 ``±50`` 内定主音；无锚时退回联合搜索
  （``stage="joint"``），该结果**只作探索，不得当作已确认主音**。
- 不可识别的三个可判条件：``margin`` 趋 0（best 与 second 同分）、``scale="chromatic"``
  （模板移调不变，margin 恒 0）、锚偏超过 ``search_cents``（主音落到音级类等价位置，
  或残差撞边界、margin 塌陷）。三者都随结果返回，调用方须自行判读。
- 锚值**不由本模块产生、不硬编码任何录音**；具体录音的锚属于调用方（实践／文献）输入。
"""

from __future__ import annotations

import numpy as np

from ..dsp.units import A4_MIDI, NOTES_PER_OCTAVE, hz_to_cents
from .pitch_grid import _segment_degree

__all__ = [
    "JOINT_SEARCH_CENTS",
    "REF_ABSOLUTE",
    "REF_MAIN_TONE",
    "SCALES",
    "TONIC_NAMES",
    "TWO_STAGE_SEARCH_CENTS",
    "degree_rows",
    "degree_rows_both",
    "degree_rows_for_model",
    "fit_tonic",
    "fit_tonic_from_audio",
    "main",
    "pitch_class_hist",
]

REF_ABSOLUTE = "absolute"
REF_MAIN_TONE = "main_tone"

#: 无锚（联合搜索）默认搜索半径（音分）——历史行为，不变
JOINT_SEARCH_CENTS = 150
#: 有锚（两阶段）默认搜索半径（音分）——锚已定偏移，主音只需在受限范围内辨
TWO_STAGE_SEARCH_CENTS = 50

TONIC_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

#: 模板敏感性用的三档音阶（半音偏移）
SCALES = {
    "pentatonic": [0, 2, 4, 7, 9],
    "diatonic": [0, 2, 4, 5, 7, 9, 11],
    "chromatic": list(range(12)),
}


def pitch_class_hist(f0_hz, *, sigma_cents: float = 30.0) -> np.ndarray:
    """有声 f0 → 音级类直方图（1200 bin，1 音分/bin，相对 A4 基准）。

    A4 基准不写死：走 ``dsp.units`` 的单一来源 ``hz_to_cents``（默认取
    ``get_reference_hz()``，可注入 415／432／442 等），使本模块与平台其余换算同源。
    """
    f = np.asarray(f0_hz, dtype=float)
    f = f[np.isfinite(f) & (f > 0)]
    hist = np.zeros(1200)
    if f.size == 0:
        return hist
    midi = A4_MIDI + np.asarray(hz_to_cents(f), dtype=float) / 100.0
    pc = np.mod(midi, NOTES_PER_OCTAVE) * 100.0  # 0..1200 音分
    idx = np.floor(pc).astype(int) % 1200
    np.add.at(hist, idx, 1.0)
    k = int(max(1, round(sigma_cents)))
    if k > 1:
        kernel = np.exp(-0.5 * (np.arange(-3 * k, 3 * k + 1) / k) ** 2)
        hist = np.convolve(np.r_[hist, hist, hist], kernel, mode="same")[1200:2400]
    return hist / max(hist.sum(), 1e-12)


def _template(tonic: str, scale: str = "pentatonic") -> np.ndarray:
    t0 = TONIC_NAMES.index(tonic)
    idx = np.arange(1200)
    ref = np.zeros(1200)
    for off in SCALES[scale]:
        center = ((t0 + off) % 12) * 100
        d = np.minimum(np.abs(idx - center), 1200 - np.abs(idx - center))
        ref += np.exp(-0.5 * (d / 30.0) ** 2)
    return ref / ref.max()


def fit_tonic(
    f0_hz,
    *,
    scale: str = "pentatonic",
    search_cents: int | None = None,
    step_cents: int = 2,
    anchor_offset_cents: float | None = None,
    anchor_source: str | None = None,
) -> dict:
    """主音拟合：两阶段（先锚定整体偏移，再于受限范围内定主音）。

    两种模式，由 ``anchor_offset_cents`` 是否给出决定，互不混用：

    - **有锚（``stage="two_stage"``，推荐／论文 §三（二）的落点）**：先把 f0 按
      ``anchor_offset_cents`` 归一，再在 ``±search_cents``（默认 50）内拟合主音。
      偏移来自演奏实践或文献（定弦、转速、传承），属**调用方输入**，本函数不猜、
      不硬编码任何具体录音的锚值。
    - **无锚（``stage="joint"``）**：保持历史行为，主音与偏移（``±150``）同时搜索。

      ⚠ 主音与偏移同时未知时，**整体平移不可识别**——「主音 X 偏移 +100」与
      「主音 Y 偏移 −20」在音级类分布上可能等价。故无锚结果只作探索，
      **不得当作已确认主音**；判读须同时看 ``margin``／``ranking``／``second``。

    返回 ``{"best", "second", "ranking", "margin", "method"}``：

    - ``best``／``ranking`` 每项含 ``tonic``、``offset_cents``（**总偏移＝锚＋残差**）、
      ``residual_offset_cents``（有锚时＝归一后搜索到的残差，无锚时同 ``offset_cents``）、
      ``score``。
    - ``method`` 含 ``stage``、``anchor_offset_cents``、``anchor_source``、
      ``search_cents``（生效值）、``step_cents``、``scale``、``hist_bins``、
      ``bin_cents``、``template_sigma_cents``。
    - ``margin`` = best − second 的拟合度差；很小意味着主音不可辨，调用方不得当作
      已确认（结构性盲区见 ``scale="chromatic"``：模板移调不变，margin 恒 0）。

    不修改入参 f0；不把结果写回任何音高数组。
    """
    if anchor_offset_cents is not None and not np.isfinite(float(anchor_offset_cents)):
        raise ValueError("anchor_offset_cents 须为有限数（锚值由调用方给定）")

    anchored = anchor_offset_cents is not None
    anchor = float(anchor_offset_cents) if anchored else 0.0
    if search_cents is None:
        search = TWO_STAGE_SEARCH_CENTS if anchored else JOINT_SEARCH_CENTS
    else:
        search = int(search_cents)
    if search <= 0:
        raise ValueError("search_cents 须为正")

    f = np.asarray(f0_hz, dtype=float)
    if anchored:
        # 第一阶段：按锚归一（只在本地副本上移，入参不动）
        f = f * 2.0 ** (-anchor / 1200.0)
    hist = pitch_class_hist(f)

    ranking = []
    offsets = range(-search, search + 1, step_cents)
    for tonic in TONIC_NAMES:
        ref = _template(tonic, scale)
        best_off, best_score = 0, -1.0
        for off in offsets:
            score = float(np.dot(np.roll(hist, -off), ref))
            if score > best_score:
                best_off, best_score = off, score
        residual = float(best_off)
        ranking.append(
            {
                "tonic": tonic,
                "offset_cents": float(anchor + residual),
                "residual_offset_cents": residual,
                "score": round(best_score, 4),
            }
        )
    ranking.sort(key=lambda r: -r["score"])
    margin = round(ranking[0]["score"] - ranking[1]["score"], 4) if len(ranking) > 1 else None
    return {
        "best": ranking[0],
        "second": ranking[1] if len(ranking) > 1 else None,
        "ranking": ranking,
        "margin": margin,
        "method": {
            "stage": "two_stage" if anchored else "joint",
            "anchor_offset_cents": anchor if anchored else None,
            "anchor_source": anchor_source if anchored else None,
            "hist_bins": 1200,
            "bin_cents": 1,
            "scale": scale,
            "template_sigma_cents": 30.0,
            "search_cents": search,
            "step_cents": step_cents,
        },
    }


def fit_tonic_from_audio(
    audio_path,
    *,
    window_start_s: float = 0.0,
    window_s: float = 30.0,
    anchor_offset_cents: float | None = None,
    anchor_source: str | None = None,
    scale: str = "pentatonic",
    fmin: float = 60.0,
    fmax: float = 1500.0,
) -> dict:
    """录音 → 主音拟合的**标准取数口径**（多方复算必须同参，2026-10-25 复核令）。

    三项固定，写在代码里，不靠口头约定：

    1. **窗口**：从 ``window_start_s`` 起取 ``window_s``（默认 0–30 s），**不跨窗拼接**；
    2. **分段**：**不过 HMM**——直接用逐帧 f0 拟合（HMM 只改段级特征，不改主音判定）；
    3. **静音剔除**：只取 ``isfinite(f0) & f0 > 0`` 的帧，不补零、不插值。

    返回值在 :func:`fit_tonic` 结果上多一个 ``source`` 键（录音、窗口、帧数、剔除规则），
    供论文与回执登记；锚值仍由调用方给（不猜）。
    """
    import soundfile as sf

    from .pitch_stream import stream_pitch

    info = sf.info(str(audio_path))
    sr = int(info.samplerate)
    first = int(round(float(window_start_s) * sr))
    frames = min(int(round(float(window_s) * sr)), int(info.frames) - first)
    if frames <= 0:
        raise ValueError(
            f"窗口越界：window_start_s={window_start_s} window_s={window_s} 时长={info.frames / sr:.3f}s"
        )
    data, _ = sf.read(str(audio_path), start=first, frames=frames, dtype="float64", always_2d=True)
    sig = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    tr = stream_pitch(signal=sig, sr=sr, fmin=float(fmin), fmax=float(fmax), block_seconds=30.0)
    f0 = np.asarray(tr.f0_hz, dtype=float)
    voiced = f0[np.isfinite(f0) & (f0 > 0)]

    result = fit_tonic(
        voiced,
        scale=scale,
        anchor_offset_cents=anchor_offset_cents,
        anchor_source=anchor_source,
    )
    result["source"] = {
        "audio_path": str(audio_path),
        "window_start_s": float(window_start_s),
        "window_s": float(window_s),
        "hmm": False,
        "silence_rule": "keep isfinite(f0) & f0>0; no zero-fill, no interpolation",
        "voiced_frames": int(voiced.size),
        "total_frames": int(f0.size),
        "fmin": float(fmin),
        "fmax": float(fmax),
    }
    return result


def degree_rows(model, tuning, *, ref_mode: str, fit: dict | None = None) -> list[dict]:
    """按指定口径输出段级音级归属行（每行带 ``ref_mode``）。

    ``REF_ABSOLUTE``：直接用段 f0 归属，报告 A4 校准下的绝对音级。
    ``REF_MAIN_TONE``：先用 ``fit["best"]["offset_cents"]`` 把段 f0 整体移调，
    再归属；``offset_applied_cents`` 记录该段实际施加的移调量（审计用）。
    """
    if ref_mode not in (REF_ABSOLUTE, REF_MAIN_TONE):
        raise ValueError(f"未知 ref_mode：{ref_mode}")
    offset = 0.0
    if ref_mode == REF_MAIN_TONE:
        if not fit or "best" not in fit:
            raise ValueError("main_tone 口径须提供 fit_tonic 结果")
        offset = float(fit["best"]["offset_cents"])
    rows: list[dict] = []
    for note in getattr(model, "notes", ()):
        hz = float(note.f0_hz)
        if hz <= 0 or not np.isfinite(hz):
            degree, dev = None, None
        else:
            shifted = hz * 2.0 ** (-offset / 1200.0) if offset else hz
            degree, dev = _segment_degree(shifted, tuning)
        rows.append(
            {
                "segment_id": f"{float(note.start_s):.3f}-{float(note.end_s):.3f}",
                "ref_mode": ref_mode,
                "degree_index": degree,
                "deviation_cents": dev,
                "offset_applied_cents": round(offset, 2),
            }
        )
    return rows


def degree_rows_for_model(model, tuning, *, ref_mode: str, fit: dict | None = None) -> list[dict]:
    """公开调用路径：音高网格模型 → 指定口径的段级音级行（主流程与外围脚本共用）。

    ``model`` 为 ``build_pitch_grid`` 的返回（或任何含 ``notes``、每个 note 带
    ``start_s``／``end_s``／``f0_hz`` 的对象）；``ref_mode`` 取
    ``REF_ABSOLUTE``／``REF_MAIN_TONE``；``main_tone`` 必须给 ``fit_tonic`` 的返回。

    一次调用只出一种口径；两口径并报请用 :func:`degree_rows_both`（分键返回，
    禁把两组行合并成一个列表）。
    """
    return degree_rows(model, tuning, ref_mode=ref_mode, fit=fit)


def degree_rows_both(model, tuning, *, fit: dict) -> dict[str, list[dict]]:
    """两口径一次取回：``{REF_ABSOLUTE: [...], REF_MAIN_TONE: [...]}``。

    键即 ``ref_mode``，两组行**分开放**，不合并、不互相覆盖；``main_tone`` 那组
    每行 ``offset_applied_cents`` 为总偏移（锚＋残差），``absolute`` 那组恒 0。
    """
    return {
        REF_ABSOLUTE: degree_rows(model, tuning, ref_mode=REF_ABSOLUTE),
        REF_MAIN_TONE: degree_rows(model, tuning, ref_mode=REF_MAIN_TONE, fit=fit),
    }


def main(argv=None) -> int:
    """一行命令跑标准取数口径（多方复算同参）::

        python -m acouscope.analysis.tonic_ref --audio 录音.wav \
            --window-start 0 --window 30 --anchor-cents 90.45 --anchor-source 空弦四弦中位
    """
    import argparse
    import json

    ap = argparse.ArgumentParser(
        prog="tonic_ref",
        description="主音拟合（标准取数口径：窗口 30 s／不过 HMM／只取有声帧）",
    )
    ap.add_argument("--audio", required=True)
    ap.add_argument("--window-start", type=float, default=0.0)
    ap.add_argument("--window", type=float, default=30.0)
    ap.add_argument("--anchor-cents", type=float, default=None)
    ap.add_argument("--anchor-source", default=None)
    ap.add_argument("--scale", default="pentatonic")
    args = ap.parse_args(argv)

    result = fit_tonic_from_audio(
        args.audio,
        window_start_s=args.window_start,
        window_s=args.window,
        anchor_offset_cents=args.anchor_cents,
        anchor_source=args.anchor_source,
        scale=args.scale,
    )
    print(json.dumps(result, ensure_ascii=False, default=list))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
