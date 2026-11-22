# SPDX-License-Identifier: GPL-3.0-only
"""三型分布与 τ 敏感性的一站式公开入口（任务件-20261026 · T-1／T-2／T-3）。

**一次运行 = 一组（输入清单 × 参数面 × 分段快照 × τ／口径面）。** 本模块把
「音频 → 逐窗分析 → 段行」接成平台公开路径，并令**同一批段行**同时供给三件产物：

- ① 三型分布（``absolute``／``main_tone`` 两口径各一份） —— T-1；
- ② τ 敏感性扫描与翻转清单（四例各一件 ＋ 汇总）       —— T-2；
- ③ 图件分面数据（形态 × 往复度），与分布表同源同 τ   —— T-3。

三件产物 ``run_id`` 恒一致（内容定址，非时间戳），故图件计数与表件计数可逐格对账。

**口径（勿自行放宽）：**

- τ 由**平台声明**：取 :data:`cavity_type.TAU_CENTS_PLACEHOLDER` 的当前值；
  其状态随之定，使用方**不得注入** τ 冒充标定结果（T-1 验收②）。
- 主音相对口径 = 先由主音拟合得总偏移，把整段 f0 移调归一后再分段
  （与 ``tonic_ref.degree_rows`` 的 ``main_tone`` 口径同式）。
- 分段器与参数快照随件登记：换窗／换分段器／换律制即换段，换段即换数。

调用方给四例（平台不内建任何具体录音）；命令行一次跑完并落盘。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

from ..dsp.reference_status import get_reference_status
from .cavity_type import (
    LABELS,
    LABEL_UNCLASSIFIED,
    classify_cavity_type,
    repeat_degree_v2,
)
from .pitch_grid import build_pitch_grid
from .pitch_stream import stream_pitch
from .denominator import (
    DENOMINATOR_POLICY,
    INDETERMINATE_NOTE_ZH,
    INDETERMINATE_ZH,
    LOW_FREQ_CLASS,
    LOW_FREQ_NOTE_ZH,
    classify_segment,
    counts_block,
)
from .readout_extras import (
    GRID_MIN_HZ,
    PRIORITY_NOTE,
    counts_by_tau,
    counts_by_tau_matrix,
    grid_boundary_payload,
    pair_flip_detail,
    provenance_block,
    run_config_block,
    three_column_payload,
)
from .tonic_ref import REF_ABSOLUTE, REF_MAIN_TONE, fit_tonic_from_audio
from .tunings.templates import (
    get_template,
    get_tuning,
    is_custom_spec,
    template_metadata,
)
from .type_distribution import (
    CALIBRATION_NOTE,
    DEFAULT_TAU_VALUES,
    TAU_BAND_CONTROL,
    TAU_BAND_MAIN,
    TAU_STATUS_DECLARED_UNCALIBRATED,
    count_labels,
    distribution_payload,
    export_json,
    export_rows_csv,
    pair_segments,
    panels_payload,
    run_descriptor,
    run_id as compute_run_id,
    segment_source_snapshot,
    sweep_summary,
    tau_declaration,
    tau_sweep_payload,
    window_segment_rows,
)

__all__ = [
    "DEFAULT_FMAX",
    "DEFAULT_FMIN",
    "DEFAULT_MIN_WINDOW_S",
    "DEFAULT_OVERLAP_RATIO",
    "DEFAULT_SEGMENTER",
    "DEFAULT_TAU_VALUES",
    "DEFAULT_TEMPLATE",
    "DEFAULT_WINDOW_S",
    "BATCH_SPEC_KEYS",
    "SEGMENT_CSV_FIELDS",
    "SEGMENT_STATE_FIELDS",
    "ReadoutCancelled",
    "RecordingCase",
    "analyze_case",
    "cases_from_json",
    "segment_rows_csv",
    "template_record",
    "count_windows",
    "main",
    "parse_tau_values",
    "read_window",
    "run_batch",
    "run_batch_from_spec",
    "window_offsets",
]


class ReadoutCancelled(Exception):
    """协作式取消：``should_cancel()`` 为真时在窗边界抛出（**不落盘**半成品）。"""


#: ``run_batch_from_spec`` 接受的取数参数键（GUI/脚本填参的**唯一**契约面）
#: ``tau_analysis`` = 主分析 τ 的**运行口径声明**（W-1；与 ``tau_values`` 扫描档分离，
#: 缺省 None ⇒ 不出主档）；它进 ``run_descriptor['config']``，故换值即换 ``run_id``。
BATCH_SPEC_KEYS = (
    "window_s", "min_window_s", "fmin", "fmax", "segmenter", "template",
    "overlap_ratio", "smooth_k", "min_thr", "tonic_window_s", "tau_analysis",
)

DEFAULT_WINDOW_S = 30.0
DEFAULT_MIN_WINDOW_S = 5.0
DEFAULT_FMIN = 60.0
DEFAULT_FMAX = 1500.0
DEFAULT_SEGMENTER = "hmm"
DEFAULT_TEMPLATE = "12tet"
#: 两口径配对的重叠率门槛（分母取绝对口径段时长）
DEFAULT_OVERLAP_RATIO = 0.5


@dataclass(frozen=True)
class RecordingCase:
    """一次运行的一条输入：录音标识 ＋ 音频路径 ＋ 呈现名 ＋ 锚（可空）。

    锚（``anchor_offset_cents``／``anchor_source``）由**调用方**给定：来自演奏
    实践（空弦实测）或文献，平台不猜。``None`` ⇒ 主音拟合退回联合搜索
    （``stage="joint"``，``margin`` 常为 0，不得当作已确认主音）。
    """

    recording_id: str
    audio_path: str
    label: str = ""
    anchor_offset_cents: float | None = None
    anchor_source: str = ""
    #: 本例的音级归属参照系（内置模板键名；``None`` ⇒ 用批次级 ``template``
    #: 参数）。2026-10-31 引入：古琴／二胡诸例的律制参照系不同（《设计约定-20261031-
    #: 律制参照系整体修正》），须逐例指定，并由 :func:`run_batch` 登记进 run_id 哈希面。
    template: str | None = None

    def title(self) -> str:
        """图／表用名：优先调用方给的呈现名，否则退回录音标识。"""
        return self.label or self.recording_id


def cases_from_json(path) -> list[RecordingCase]:
    """输入清单 JSON → :class:`RecordingCase` 列表（键名逐一白名单，缺键报错）。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = payload["cases"] if isinstance(payload, Mapping) else payload
    cases: list[RecordingCase] = []
    for item in entries:
        cases.append(
            RecordingCase(
                recording_id=str(item["recording_id"]),
                audio_path=str(item["audio_path"]),
                label=str(item.get("label", "") or ""),
                anchor_offset_cents=(
                    None
                    if item.get("anchor_offset_cents") is None
                    else float(item["anchor_offset_cents"])
                ),
                anchor_source=str(item.get("anchor_source", "") or ""),
                template=(
                    None
                    if item.get("template") is None
                    else str(item["template"])
                ),
            )
        )
    return cases


# ---------------------------------------------------------------------------
# 底层：窗与段行
# ---------------------------------------------------------------------------


def _sha256_file(path) -> str:
    """文件 sha256（分块读，避免整卷入内存）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _window_offsets(frames: int, sr: int, window_s: float, min_window_s: float) -> list[tuple[int, int]]:
    """逐窗切分（首尾对齐窗格；尾窗不足 ``min_window_s`` 者舍去）。"""
    step = int(round(float(window_s) * sr))
    floor = int(round(float(min_window_s) * sr))
    out: list[tuple[int, int]] = []
    start = 0
    while start < frames:
        count = min(step, frames - start)
        if count >= floor:
            out.append((start, count))
        start += step
    return out


def _read_window(audio_path, start: int, frames: int) -> tuple[np.ndarray, int]:
    """读一个窗（多声道取等权下混），返回 ``(sig, sr)``。"""
    import soundfile as sf

    data, sr = sf.read(
        str(audio_path), start=start, frames=frames, dtype="float64", always_2d=True
    )
    sig = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    return np.asarray(sig, dtype=float), int(sr)


#: 公开别名：窗切分与读窗是**同一实现**（供段长分布件等复用同一窗口口径，
#: 不另立第二套切窗/读音频逻辑，避免「同名不同数」）。
window_offsets = _window_offsets
read_window = _read_window


def template_record(spec: str, *, recording_id: str = "") -> dict:
    """模板记录块（W-14-05／W-14-06）：key／name／source／degree_count／fingerprint。

    自定义 ``.scl`` 另带 ``template_sha256``（文件哈希）与 ``template_custom=True``；
    未知 spec 由 :func:`acouscope.analysis.tunings.templates.get_tuning` 显式报错
    （**禁回退 12TET**）。
    """
    sha: str | None = None
    spec_text = str(spec)
    if is_custom_spec(spec_text):
        raw = (
            spec_text[len("custom:"):].strip()
            if spec_text.startswith("custom:")
            else spec_text
        )
        if Path(raw).is_file():
            sha = _sha256_file(raw)
    block = template_metadata(spec_text, sha256=sha)
    if recording_id:
        block["recording_id"] = str(recording_id)
    return block


def _build_model(times, f0, conf, *, segmenter: str, tuning, ref_mode: str):
    """分段建模；``ref_mode`` 只作**口径标注**（写进模型供段行报出），不改分段逻辑。"""
    model = build_pitch_grid(times, f0, conf, segmenter=segmenter, tuning=tuning)
    model.ref_mode = str(ref_mode)
    return model


def _attach_turns(rows, model, f0, *, smooth_k: int, min_thr: float,
                  window_stats: Mapping | None = None) -> list[dict]:
    """给段行挂往复度读数（``repeat_degree_v2`` fixed 口径；同源同段）。

    同时挂**段级分母与钳位面**（W-4／W-6 用，均为同段同帧的原始读数，不改判定）：

    - ``conf``：段中位置信度（``note.conf``）；
    - ``n_valid_frames``：段内有效帧数（``isfinite(f0) & f0 > 0``）；
    - ``frames_total``：段内帧跨度（首末 ``state_runs`` 帧数）；
    - ``clamped_candidate_frames``：段内**候选**低于网格下界的帧数
      （由候选面掩码计数，非由输出反推）；
    - ``output_at_grid_min_frames``：段内解码落在最低格的帧数。
    """
    osc = {r["segment_id"]: r for r in repeat_degree_v2(
        model, f0, mode="fixed", smooth_k=int(smooth_k), min_thr=float(min_thr)
    )}
    notes = list(getattr(model, "notes", ()) or ())
    cand_mask = None if window_stats is None else window_stats.get("_cand_below_mask")
    out_mask = None if window_stats is None else window_stats.get("_output_at_grid_min_mask")
    f0_arr = np.asarray(f0, dtype=float)
    out = []
    for position, row in enumerate(rows):
        item = dict(row)
        # 往复度按**窗内** id 出，行已是全局 id ⇒ 用 segment_id_local 对表
        reading = osc.get(str(row.get("segment_id_local", row["segment_id"]))) or {}
        item["turns"] = reading.get("turns")
        item["turns_valid"] = bool(reading.get("valid"))
        item["pp_cents"] = reading.get("pp_cents")
        item["rate_hz"] = reading.get("rate_hz")
        note = notes[position] if position < len(notes) else None
        item["conf"] = (None if note is None else round(float(note.conf), 6))
        runs = tuple(getattr(note, "state_runs", ()) or ()) if note is not None else ()
        if runs:
            i, j = int(runs[0][0]), int(runs[-1][1])
            vals = f0_arr[i : j + 1]
            valid = vals[np.isfinite(vals) & (vals > 0)]
            item["n_valid_frames"] = int(valid.size)
            item["frames_total"] = int(j - i + 1)
            if cand_mask is not None and len(cand_mask) >= j + 1:
                item["clamped_candidate_frames"] = int(np.count_nonzero(cand_mask[i : j + 1]))
            else:
                item["clamped_candidate_frames"] = None
            if out_mask is not None and len(out_mask) >= j + 1:
                item["output_at_grid_min_frames"] = int(np.count_nonzero(out_mask[i : j + 1]))
            else:
                item["output_at_grid_min_frames"] = None
        else:
            item["n_valid_frames"] = None
            item["frames_total"] = None
            item["clamped_candidate_frames"] = None
            item["output_at_grid_min_frames"] = None
        out.append(item)
    return out


def _accumulate_grid_stats(acc: dict, stats: Mapping, *, times) -> None:
    """把一个窗的候选面／输出面诊断计数并入本例合计（W-6；两面严格分列）。

    只做加法与极值合并，不做任何推断：``candidate_*`` 来自候选面，
    ``output_*`` 来自解码输出面，二者**不得**互相反证。
    """
    for key in (
        "frames",
        "candidate_frames",
        "candidate_count",
        "candidate_below_grid_min_frames",
        "candidate_below_grid_min_count",
        "voiced_frames",
        "output_at_grid_min_frames",
    ):
        acc[key] = int(acc.get(key) or 0) + int(stats.get(key) or 0)
    for key, op in (
        ("candidate_min_hz", min),
        ("candidate_max_hz", max),
        ("output_min_hz", min),
        ("output_max_hz", max),
    ):
        value = stats.get(key)
        if value is None:
            continue
        acc[key] = float(value) if acc.get(key) is None else op(float(acc[key]), float(value))
    for key in ("grid_min_hz", "grid_freq_max_hz"):
        if stats.get(key) is not None:
            acc[key] = float(stats[key])
    arr = np.asarray(times, dtype=float)
    if arr.size > 1:
        dt = float(np.median(np.diff(arr)))
        if dt > 0:
            acc["frame_dts_s"].append(dt)


def criterion_window_frames(frame_dts: Sequence[float]) -> int:
    """判据窗长（帧）：头尾偏离窗 0.10 s 折帧数，至少 2 帧（W-4 的不可判判据用）。

    与 ``note_hmm._edge_deviation_cents`` 的 ``min(0.10 s, 段长/3)`` 同源：本函数取
    **上限**（0.10 s）折帧，作为「段内有效帧是否够一个判据窗」的阈值。
    """
    dts = [float(x) for x in frame_dts if float(x) > 0]
    if not dts:
        return 2
    dt = float(np.median(dts))
    return max(2, int(round(0.10 / dt)))


#: 段行里的段内状态字段（W-14-02；只导出，不改判定）
SEGMENT_STATE_FIELDS: tuple[str, ...] = (
    "state",
    "state_runs",
    "dominant_state",
    "attack_ratio",
    "stable_ratio",
    "inter_ratio",
    "segment_type_signal",
)

#: 段行 CSV 的列序（前段为既有段级读数，后段为 W-14-02 新列）
SEGMENT_CSV_FIELDS: tuple[str, ...] = (
    "segment_id",
    "start_s",
    "end_s",
    "ref_mode",
    "f0_hz",
    "degree_index",
    "degree_deviation_cents",
    "head_deviation_cents",
    "tail_deviation_cents",
    "conf",
    "turns",
    "turns_valid",
    "pp_cents",
    "rate_hz",
    "state",
    "state_runs",
    "dominant_state",
    "attack_ratio",
    "stable_ratio",
    "inter_ratio",
    "segment_type_signal",
)


def segment_rows_csv(rows, *, fields: Sequence[str] = SEGMENT_CSV_FIELDS) -> list[dict]:
    """段行 → CSV 行（列序定死；``state_runs`` 写成紧凑 JSON 文本，其余原值）。

    None 保留为空串以外的 ``None``（由 ``csv`` 模块写成空单元格）——**不以 0 冒充
    缺值**；浮点原值不四舍五入（段行已是平台定值）。
    """
    out: list[dict] = []
    for row in rows:
        item: dict = {}
        for key in fields:
            value = row.get(key)
            if key == "state_runs":
                item[key] = json.dumps(value or [], ensure_ascii=False, separators=(",", ":"))
            else:
                item[key] = value
        out.append(item)
    return out


def _command_line(
    *,
    cases_source: str,
    out_dir,
    window_s: float,
    min_window_s: float,
    fmin: float,
    fmax: float,
    segmenter: str,
    template: str,
    tau_values: Sequence[float | None],
    tau_analysis: float | None,
    overlap_ratio: float,
    smooth_k: int,
    min_thr: float,
    tonic_window_s: float,
    figure_out=None,
    figure_stem: str = "figure_b",
) -> str:
    """生成命令（溯源面必备项）：可由人直接照抄复跑的那一行。

    τ 扫描档写 ``none,10,20,30``；主档另写 ``--tau-analysis``（**与扫描档分离**）。
    调用方若给了 ``command``（如实际 argv），以调用方为准。
    """
    def _tau_text(values: Sequence[float | None]) -> str:
        return ",".join(
            "none" if v is None else f"{float(v):g}" for v in values
        )

    parts = [
        "python -m acouscope.analysis.readout",
        f"--cases {cases_source or '<cases.json>'}",
        f"--out {out_dir}",
        f"--window-s {float(window_s):g}",
        f"--min-window-s {float(min_window_s):g}",
        f"--fmin {float(fmin):g}",
        f"--fmax {float(fmax):g}",
        f"--segmenter {segmenter}",
        f"--template {template}",
        f"--tau {_tau_text(tau_values)}",
        f"--overlap-ratio {float(overlap_ratio):g}",
        f"--smooth-k {int(smooth_k)}",
        f"--min-thr {float(min_thr):g}",
        f"--tonic-window-s {float(tonic_window_s):g}",
    ]
    if tau_analysis is not None:
        parts.append(f"--tau-analysis {float(tau_analysis):g}")
    if figure_out is not None:
        parts.append(f"--figure-out {figure_out}")
        parts.append(f"--figure-stem {figure_stem}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 单例：录音 → 段行 → 分布／扫描
# ---------------------------------------------------------------------------


def analyze_case(
    case: RecordingCase,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    min_window_s: float = DEFAULT_MIN_WINDOW_S,
    fmin: float = DEFAULT_FMIN,
    fmax: float = DEFAULT_FMAX,
    segmenter: str = DEFAULT_SEGMENTER,
    template: str = DEFAULT_TEMPLATE,
    tau_values: Iterable[float | None] = DEFAULT_TAU_VALUES,
    ref_modes: Iterable[str] = (REF_ABSOLUTE, REF_MAIN_TONE),
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
    smooth_k: int = 5,
    min_thr: float = 10.0,
    run_id_: str | None = None,
    tonic_window_s: float = 30.0,
    on_window: Callable[[int, int, float], None] | None = None,
) -> dict:
    """单条录音 → 段行 ＋ 三型分布 ＋ τ 扫描（τ 由平台声明，分段快照随件）。

    ``tonic_window_s``（主音拟合取数窗）默认 **30 s**：与 ``fit_tonic_from_audio``
    的平台标准口径一致（逐帧 f0 直接拟合、只取 ``isfinite(f0)&f0>0`` 的帧），
    且论文 §四 主口径已约定为 0–30 s（约定 #32）；换窗即换数，故随件登记。

    返回 ``{"recording_id", "label", "audio", "tonic", "total_offset_cents",
    "windows", "rows", "distributions", "sweeps", "pairing"}``。
    ``rows``／``distributions``／``sweeps`` 均按 ``ref_mode`` 分键（**不合并**）。

    ``on_window``：每窗处理完回调 ``on_window(第几窗, 总窗数, 该窗起点秒)``，
    供调用方做确定式进度；不传即不上报（语义不变）。
    """
    import soundfile as sf

    modes = [str(mode) for mode in ref_modes]
    taus = list(tau_values)
    audio_path = str(case.audio_path)

    info = sf.info(audio_path)
    sr = int(info.samplerate)
    duration_s = float(info.frames) / sr
    # W-14-06：template 接受内置 key 或 .scl 路径（未知 spec 显式报错，不回退 12TET）
    tuning = get_tuning(str(template))

    fit = fit_tonic_from_audio(
        audio_path,
        window_start_s=0.0,
        window_s=float(tonic_window_s),
        anchor_offset_cents=case.anchor_offset_cents,
        anchor_source=case.anchor_source,
        fmin=float(fmin),
        fmax=float(fmax),
    )
    total_offset = float(fit["best"]["offset_cents"])

    rows_by_mode: dict[str, list[dict]] = {mode: [] for mode in modes}
    windows: list[dict] = []
    plan = _window_offsets(int(info.frames), sr, window_s, min_window_s)
    window_count = max(1, len(plan))
    grid_acc: dict = {
        "frames": 0,
        "candidate_frames": 0,
        "candidate_count": 0,
        "candidate_below_grid_min_frames": 0,
        "candidate_below_grid_min_count": 0,
        "voiced_frames": 0,
        "output_at_grid_min_frames": 0,
        "candidate_min_hz": None,
        "candidate_max_hz": None,
        "output_min_hz": None,
        "output_max_hz": None,
        "grid_min_hz": None,
        "grid_freq_max_hz": None,
        "frame_dts_s": [],
    }
    for index, (start, count) in enumerate(plan, 1):
        offset_s = start / sr
        sig, _sr = _read_window(audio_path, start, count)
        wstats: dict = {}
        tr = stream_pitch(
            signal=sig, sr=sr, fmin=float(fmin), fmax=float(fmax),
            block_seconds=float(window_s), stats=wstats,
        )
        f0 = np.asarray(tr.f0_hz, dtype=float)
        conf = np.asarray(tr.confidence, dtype=float)
        windows.append(
            {
                "window_start_s": round(offset_s, 3),
                "frames": int(count),
                "seconds": round(count / sr, 3),
            }
        )
        _accumulate_grid_stats(grid_acc, wstats, times=tr.times)
        for mode in modes:
            shift = 0.0 if mode == REF_ABSOLUTE else total_offset
            f0_in = f0 * 2.0 ** (-shift / 1200.0)
            model = _build_model(tr.times, f0_in, conf, segmenter=segmenter, tuning=tuning,
                                 ref_mode=mode)
            rows = window_segment_rows(model, window_start_s=offset_s, ref_mode=mode)
            rows_by_mode[mode].extend(
                _attach_turns(rows, model, f0_in, smooth_k=smooth_k, min_thr=min_thr,
                              window_stats=wstats)
            )
        if on_window is not None:
            on_window(index, window_count, round(offset_s, 3))

    starts = [float(w["window_start_s"]) for w in windows]
    seg_src = segment_source_snapshot(
        segmenter=segmenter,
        window_s=window_s,
        min_window_s=min_window_s,
        fmin=fmin,
        fmax=fmax,
        block_seconds=window_s,
        tuning_template=template,
        window_starts_s=starts,
    )
    # W-14-05：分段快照里同步模板来源面（旧键 tuning_template 保留，兼容）
    seg_src["template"] = template_record(
        str(template), recording_id=str(case.recording_id)
    )

    distributions = {
        mode: distribution_payload(rows_by_mode[mode], recording_id=case.recording_id,
                                   ref_mode=mode, segment_source=seg_src, run_id_=run_id_)
        for mode in modes
    }
    sweeps = {
        mode: tau_sweep_payload(rows_by_mode[mode], tau_values=taus,
                                recording_id=case.recording_id, ref_mode=mode,
                                segment_source=seg_src, run_id_=run_id_)
        for mode in modes
    }

    pairing = None
    if REF_ABSOLUTE in rows_by_mode and REF_MAIN_TONE in rows_by_mode:
        pairing = pair_segments(rows_by_mode[REF_ABSOLUTE], rows_by_mode[REF_MAIN_TONE],
                                overlap_ratio=overlap_ratio)
        pairing["unpaired_segments"] = int(pairing["unmatched_a"])
        pairing["matched_pairs"] = int(pairing["matched"])
        pairing["n_absolute"] = int(len(rows_by_mode[REF_ABSOLUTE]))
        pairing["n_main_tone"] = int(len(rows_by_mode[REF_MAIN_TONE]))
        pairing["overlap_ratio"] = float(overlap_ratio)

    return {
        "recording_id": str(case.recording_id),
        "label": case.title(),
        "audio": {
            "audio_name": Path(audio_path).name,
            "audio_path": audio_path,
            "sha256": _sha256_file(audio_path),
            "frames": int(info.frames),
            "samplerate": sr,
            "duration_s": round(duration_s, 3),
            "channels": int(info.channels),
        },
        "tonic": fit["best"].get("tonic"),
        "total_offset_cents": total_offset,
        "anchor_offset_cents": case.anchor_offset_cents,
        "anchor_source": case.anchor_source,
        "windows": windows,
        "rows": rows_by_mode,
        "distributions": distributions,
        "sweeps": sweeps,
        "pairing": pairing,
        "extras": {
            "criterion_window_frames": criterion_window_frames(grid_acc["frame_dts_s"]),
            "grid": grid_acc,
            # 逐例实际采用的音级归属参照系（随件登记，供稿件与 C 对账）
            "tuning_template": str(template),
            # W-14-05/06：模板名称＋学术来源＋指纹（自定义音阶另带 .scl 文件哈希）
            "template": template_record(str(template), recording_id=str(case.recording_id)),
        },
    }


# ---------------------------------------------------------------------------
# 批量运行与落盘
# ---------------------------------------------------------------------------


def _distribution_rows(cases_result: Sequence[Mapping],
                       *, tau_band: str = TAU_BAND_CONTROL) -> list[dict]:
    """三型分布 → 表格行（一例一口径一行；列序固定，供论文表 4-2 直接取数）。

    ``tau_band`` 只标该行所属档位（主档／对照档），数值仍取自分布件的
    ``counts_per_recording``（同一批段行，不同判型容差）。

    **W-8**：四值分母为**可判段**（``合计`` 即四值之和 ＋ 未分类），故本表另列
    ``n_all``／``n_indeterminate``／``n_low_freq_unreliable``／``n_denominator_body``
    与置信三态，使 CSV 与 JSON 逐格同步、且不会被读成「四值之和＝全部段」。
    """
    rows: list[dict] = []
    for result in cases_result:
        for mode, payload in result["distributions"].items():
            rows.append(
                _payload_row(
                    label=result["label"], mode=mode, payload=payload,
                    tau_band=tau_band,
                )
            )
    return rows


def _payload_rows(payloads_by_mode: Mapping[str, Sequence[Mapping]],
                  cases_result: Sequence[Mapping],
                  *, tau_band: str) -> list[dict]:
    """分布件（按口径分组）→ 表行：与 JSON 同值，逐格可对拍（W-8 的 CSV 同步）。"""
    label_of = {str(r["recording_id"]): r["label"] for r in cases_result}
    rows: list[dict] = []
    for mode, payloads in payloads_by_mode.items():
        for payload in payloads:
            rows.append(
                _payload_row(
                    label=label_of.get(str(payload.get("recording_id")), ""),
                    mode=mode, payload=payload, tau_band=tau_band,
                )
            )
    return rows


def _payload_row(*, label: str, mode: str, payload: Mapping,
                 tau_band: str) -> dict:
    """单格（例 × 口径 × 档）→ CSV 行（列序固定；与 JSON 字段一一对应）。"""
    counts = payload["counts_per_recording"]
    body = payload.get("counts_per_recording_excluding_low_freq") or {}
    return {
        "例": label,
        "recording_id": payload.get("recording_id"),
        "ref_mode": mode,
        "上趋": counts["上趋"],
        "下趋": counts["下趋"],
        "平直": counts["平直"],
        "未分类": counts["未分类"],
        "合计": counts["合计"],
        "n_all": payload.get("n_all"),
        "n_judgable": payload.get("n_judgable"),
        "n_axis": payload.get("n_axis"),
        "n_composite": payload.get("n_composite"),
        "n_indeterminate": payload.get("n_indeterminate"),
        "置信_高": payload.get("n_high_conf"),
        "置信_低": payload.get("n_low_conf"),
        "置信_缺": payload.get("n_conf_missing"),
        "n_coexist": payload.get("n_coexist"),
        "n_low_freq_unreliable": payload.get("n_low_freq_unreliable"),
        "n_denominator_body": payload.get("n_denominator_body"),
        "正文分母_上趋": body.get("上趋"),
        "正文分母_下趋": body.get("下趋"),
        "正文分母_平直": body.get("平直"),
        "正文分母_未分类": body.get("未分类"),
        "正文分母_合计": body.get("合计"),
        "counts_denominator": payload.get("counts_denominator"),
        "tau_band": str(tau_band),
        "tau_cents": payload.get("tau_cents"),
        "tau_status": payload.get("tau_status"),
        "run_id": payload.get("run_id"),
    }


def _pairing_rows_for_band(
    cases_result: Sequence[Mapping],
    *,
    tau_cents: float | None,
    band: str,
    rid: str,
    flips_by_rid: Mapping[str, Mapping[str, Mapping]],
    provenance: Callable[..., dict],
) -> list[dict]:
    """两口径配对 → 表格行（一例一行，含 W-2 改判**明细**与逐方向计数）。

    ``未配对段``／``配对段数`` **按该档重出**（旧值 4／1／32／33 不得沿用）；
    ``type_flips`` 为逐对明细，``type_flip_counts`` 为方向计数，
    ``flip_rate_dual`` 分母＝配对段数（与 τ 扫描的 ``flip_rate`` 不同分母）。
    """
    rows: list[dict] = []
    for result in cases_result:
        pairing = result.get("pairing")
        if not pairing:
            continue
        rkey = str(result["recording_id"])
        detail = dict(flips_by_rid.get(rkey, {}).get(band) or {})
        abs_counts = count_labels(result["rows"][REF_ABSOLUTE], tau_cents=tau_cents)
        mt_counts = count_labels(result["rows"][REF_MAIN_TONE], tau_cents=tau_cents)
        rows.append(
            {
                "例": result["label"],
                "recording_id": rkey,
                "绝对_上趋": abs_counts["上趋"],
                "绝对_下趋": abs_counts["下趋"],
                "绝对_平直": abs_counts["平直"],
                "绝对_未分类": abs_counts["未分类"],
                "主音_上趋": mt_counts["上趋"],
                "主音_下趋": mt_counts["下趋"],
                "主音_平直": mt_counts["平直"],
                "主音_未分类": mt_counts["未分类"],
                "配对段数": int(detail.get("matched_pairs") or pairing["matched"]),
                "未配对段": int(detail.get("unpaired_segments") or 0),
                "unmatched_b": int(detail.get("unmatched_b") or 0),
                "n_absolute": int(detail.get("n_absolute") or 0),
                "n_main_tone": int(detail.get("n_main_tone") or 0),
                "type_flips": list(detail.get("type_flips") or []),
                "type_flip_counts": dict(detail.get("type_flip_counts") or {}),
                "flip_numerator": int(detail.get("flip_numerator") or 0),
                "flip_denominator": "matched_pairs",
                "flip_rate_dual": detail.get("flip_rate_dual"),
                "overlap_ratio": float(pairing["overlap_ratio"]),
                "tau_band": str(band),
                "tau_cents": None if tau_cents is None else float(tau_cents),
                "run_id": rid,
                "provenance": provenance(rkey),
            }
        )
    return rows


def _pairing_csv_rows(rows: Sequence[Mapping]) -> list[dict]:
    """配对表 → CSV 行：明细数组／字典按紧凑 JSON 串落格（CSV 不承载嵌套）。"""
    out: list[dict] = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if key == "provenance":
                continue
            if isinstance(value, (list, dict)):
                item[key] = json.dumps(value, ensure_ascii=False)
            else:
                item[key] = value
        out.append(item)
    return out


def reconcile(results: Sequence[Mapping], *, tau_cents: float | None = None,
              tau_status: str | None = None) -> dict:
    """图件 ↔ 表件逐格对账（T-3 验收③；**W-10 同分母**）。

    对账式（三段，逐例给结果）：

    - ``入图段数`` ＝ ``n_axis``（三型入图）；
    - ``未入三型`` ＝ ``n_composite``（未分类＝复合型，定义不入三型轴）；
    - ``单列_往复窗不可判`` ＝ ``n_indeterminate``（不入图、不入四值）；
    - 恒等：``入图 ＋ 未入三型 ＋ 不可判 ＝ n_all``，且 ``入图 ＋ 未入三型 ＝ 表四值合计``。

    自 W-8 起四值分母为可判段，故图与表**不再有**「表合计含不可判、图不含」的
    错位；``n_low_freq_unreliable``（W-9）是重叠类，另列给出，不影响上述恒等。

    ``tau_cents``：判型容差（``None`` = 平台占位、按符号判）；主档须传入本次
    运行声明的 τ，使对账与主档分布表同档（W-1 双档各跑一次闸门）。
    """
    per: list[dict] = []
    decl = tau_declaration()
    for result in results:
        rows = result["rows"][REF_ABSOLUTE]
        crit = int(result["extras"]["criterion_window_frames"])
        block = counts_block(
            rows, tau_cents=tau_cents, criterion_window_frames=crit
        )
        no_turns = sum(
            1
            for row in rows
            if classify_segment(
                row, criterion_window_frames=crit, tau_cents=tau_cents
            )["in_judgable"]
            and row.get("turns") is None
        )
        plotted = int(block["n_axis"]) - int(no_turns)
        per.append(
            {
                "recording_id": result["recording_id"],
                "label": result["label"],
                "n_segments": int(block["n_all"]),
                "n_judgable": int(block["n_judgable"]),
                "表_三型合计": int(block["n_axis"]),
                "表_未分类": int(block["n_composite"]),
                "表_四值合计": int(block["counts_per_recording"]["合计"]),
                "图_入图段数": plotted,
                "图_未入三型": int(block["n_composite"]),
                "单列_往复窗不可判": int(block["n_indeterminate"]),
                "单列_低频不可靠": int(block["n_low_freq_unreliable"]),
                "差_无往复度读数段": int(no_turns),
                "入图段数+未入三型=合计": bool(
                    plotted + int(block["n_composite"])
                    == int(block["counts_per_recording"]["合计"])
                ),
                "入图+未入三型+不可判=全部": bool(
                    plotted
                    + int(block["n_composite"])
                    + int(block["n_indeterminate"])
                    == int(block["n_all"])
                ),
                "run_id": result["distributions"][REF_ABSOLUTE]["run_id"],
                "tau_cents": None if tau_cents is None else float(tau_cents),
                "tau_status": (
                    decl["tau_status"] if tau_status is None else str(tau_status)
                ),
            }
        )
    return {
        "format": "acouscope-figure-table-reconciliation",
        "version": 1,
        "denominator_policy": DENOMINATOR_POLICY,
        "per_recording": per,
        "note": (
            "「未入三型」＝未分类（复合型，定义不入三型轴）；「往复窗不可判」单列，"
            "既不进图也不进四值；低频不可靠是重叠类，另列、不入正文分母。"
        ),
    }


def run_batch(
    cases: Sequence[RecordingCase],
    *,
    out_dir,
    window_s: float = DEFAULT_WINDOW_S,
    min_window_s: float = DEFAULT_MIN_WINDOW_S,
    fmin: float = DEFAULT_FMIN,
    fmax: float = DEFAULT_FMAX,
    segmenter: str = DEFAULT_SEGMENTER,
    template: str = DEFAULT_TEMPLATE,
    tau_values: Iterable[float | None] = DEFAULT_TAU_VALUES,
    ref_modes: Iterable[str] = (REF_ABSOLUTE, REF_MAIN_TONE),
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
    smooth_k: int = 5,
    min_thr: float = 10.0,
    figure_out=None,
    figure_stem: str = "figure_b",
    tonic_window_s: float = 30.0,
    tau_analysis: float | None = None,
    tau_provenance: str = "",
    command: str = "",
    cases_source: str = "",
    on_progress: Callable[[str, float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    """一次批量运行：跑全部录音 → 落盘读数件／图件分面数据 → 可选出图。

    产物（落在 ``out_dir``）：``run_descriptor.json``、``type_distribution.<ref_mode>.json``、
    ``type_distribution.csv``、``dual_calibre_pairing.csv／.json``、``tau_sweep.<recording_id>.<ref_mode>.json``、
    ``tau_sweep_summary.<ref_mode>.json``、``tau_sweep_summary.csv``、``figure_b_panels[.<ref_mode>].json``、
    ``MANIFEST.md``。

    **丙案出件补项（W-1—W-7）**：

    - ``tau_analysis``：**主分析 τ 的运行口径声明**（与扫描档 ``tau_values`` 分离）。
      给定即同时产出主档（``tau_status = run_config_declared_uncalibrated``）与
      按符号判对照档（``unspecified_sign_based``）两套分布／配对／分面件；
      ``None``（缺省）⇒ 只出对照档，主档件不落盘（不伪造主档）。
      **不改** :data:`cavity_type.TAU_CENTS_PLACEHOLDER`，也不设全局默认。
    - 另出 ``counts_by_tau[.summary].json``（W-3）、``three_column[.summary].json``（W-4）、
      ``dual_calibre_flips.<recording_id>.json``（W-2）、``grid_boundary[.summary].json``（W-6）。
    - 口径面（W-7）写进 ``run_descriptor['config']``，故 ``run_id`` 随口径维变化。

    ``figure_out`` 给定 ⇒ 同时用 ``paper_B`` 预设渲出图件（**与表同源同 τ**，T-3），
    图件哈希登记进 MANIFEST；``tau_analysis`` 给定 ⇒ 主档图件另出一套
    （``<stem>_tau_analysis``）并各跑一次图—表闸。

    **长任务友好**（GUI 用）：``on_progress(stage, value)`` 按「窗」粒度上报确定式
    进度；``should_cancel()`` 为协作式取消探针，为真即在**窗边界**抛
    :class:`ReadoutCancelled` —— 半途不落盘，故目录中不留半成品。
    """
    modes = [str(mode) for mode in ref_modes]
    taus = list(tau_values)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    inputs = []
    for case in cases:
        import soundfile as sf

        info = sf.info(str(case.audio_path))
        sr = int(info.samplerate)
        inputs.append(
            {
                "recording_id": str(case.recording_id),
                "audio_name": Path(str(case.audio_path)).name,
                "sha256": _sha256_file(str(case.audio_path)),
                "frames": int(info.frames),
                "samplerate": sr,
                "duration_s": round(float(info.frames) / sr, 3),
                "anchor_offset_cents": case.anchor_offset_cents,
                "anchor_source": case.anchor_source,
            }
        )

    base_source = segment_source_snapshot(
        segmenter=segmenter,
        window_s=window_s,
        min_window_s=min_window_s,
        fmin=fmin,
        fmax=fmax,
        block_seconds=window_s,
        tuning_template=template,
    )
    base_source["template"] = template_record(str(template))
    cfg = run_config_block(
        window_s=window_s,
        min_window_s=min_window_s,
        fmin=fmin,
        fmax=fmax,
        segmenter=segmenter,
        template=template,
        overlap_ratio=overlap_ratio,
        smooth_k=smooth_k,
        min_thr=min_thr,
        tonic_window_s=tonic_window_s,
        tau_values=taus,
        tau_analysis=tau_analysis,
        ref_modes=modes,
        anchors=[
            {
                "recording_id": str(case.recording_id),
                "anchor_offset_cents": case.anchor_offset_cents,
                "anchor_source": case.anchor_source,
            }
            for case in cases
        ],
        # 逐例参照系（**既有形状，零改动**）：与 anchors 同理须进 run_id 哈希面，
        # 否则「换参照系」不换运行标识，违内容定址。★ 本键的形状由既有守卫
        # `tests/test_readout.py::test_run_batch_registers_per_case_template_in_run_id`
        # 逐字锁定（缺省不出现、出现时只含 recording_id＋template），故 W-14-05 的
        # 5 字段来源面另立 `template_metadata` 键（同进 run_id，见下）。
        templates=(
            [
                {
                    "recording_id": str(case.recording_id),
                    "template": str(case.template),
                }
                for case in cases
                if case.template
            ]
            or None
        ),
        # W-14-05／06：**全例**模板来源面（template_key/name/source/degree_count/
        # fingerprint；自定义音阶另带 template_sha256）。改 source 即改本块 ⇒
        # run_id 必变；历史 running 件不重算、不受影响。
        template_metadata=[
            template_record(
                str(case.template) if case.template else str(template),
                recording_id=str(case.recording_id),
            )
            for case in cases
        ],
        reference=get_reference_status(),
    )
    descriptor = run_descriptor(inputs=inputs, segment_source=base_source,
                                tau_values=taus, ref_modes=modes, config=cfg)
    rid = compute_run_id(descriptor)
    descriptor["run_id"] = rid
    cmd = command or _command_line(
        cases_source=cases_source, out_dir=out, window_s=window_s,
        min_window_s=min_window_s, fmin=fmin, fmax=fmax, segmenter=segmenter,
        template=template, tau_values=taus, tau_analysis=tau_analysis,
        overlap_ratio=overlap_ratio, smooth_k=smooth_k, min_thr=min_thr,
        tonic_window_s=tonic_window_s, figure_out=figure_out,
        figure_stem=figure_stem,
    )
    main_band = tau_analysis is not None
    reads_tau = float(tau_analysis) if main_band else None
    reads_band = TAU_BAND_MAIN if main_band else TAU_BAND_CONTROL
    reads_status = (
        TAU_STATUS_DECLARED_UNCALIBRATED if main_band
        else tau_declaration()["tau_status"]
    )

    def _cancel_point() -> None:
        if should_cancel is not None and should_cancel():
            raise ReadoutCancelled("批量运行已取消（协作式：在窗边界停止）")

    def _emit(done_windows: int, stage: str) -> None:
        if on_progress is None:
            return
        on_progress(stage, min(100.0, done_windows / max(1, total_windows) * 100.0))

    plan = [(count_windows(str(case.audio_path), window_s=window_s,
                           min_window_s=min_window_s), case) for case in cases]
    total_windows = sum(n for n, _ in plan)

    results: list[dict] = []
    done = 0
    for position, (n_windows, case) in enumerate(plan, 1):
        _cancel_point()
        stage = f"({position}/{len(plan)}) {case.title()}"
        _emit(done, stage)

        def _window_tick(index: int, _stage: str = stage, _base: int = done) -> None:
            _emit(_base + index, _stage)

        results.append(
            analyze_case(
                case,
                window_s=window_s,
                min_window_s=min_window_s,
                fmin=fmin,
                fmax=fmax,
                segmenter=segmenter,
                # 逐例参照系优先：用例自带 template 覆盖批次级（为 None 时取批次级）
                template=str(case.template) if case.template else template,
                tau_values=taus,
                ref_modes=modes,
                overlap_ratio=overlap_ratio,
                smooth_k=smooth_k,
                min_thr=min_thr,
                run_id_=rid,
                tonic_window_s=tonic_window_s,
                on_window=_window_tick,
            )
        )
        done += int(n_windows)
        _emit(done, stage)
    _cancel_point()

    export_json(out / "run_descriptor.json", descriptor)

    # ---- W-4：三栏并行布尔＋不可判单列（先算，六分母量供全件的溯源面复用）----
    three_by_rid: dict[str, dict] = {}
    denoms_run: dict[str, dict] = {}
    for result in results:
        rkey = str(result["recording_id"])
        by_mode = {}
        for mode in modes:
            payload = three_column_payload(
                result["rows"][mode],
                tau_cents=reads_tau,
                criterion_window_frames=int(
                    result["extras"]["criterion_window_frames"]
                ),
                mode=mode,
                tau_band=reads_band,
                tau_status=reads_status,
            )
            by_mode[mode] = payload
        three_by_rid[rkey] = by_mode
        denoms_run[rkey] = {
            mode: dict(block["denominators"]) for mode, block in by_mode.items()
        }

    def _prov(rkey: str | None = None, *, extra: Mapping | None = None) -> dict:
        return provenance_block(
            run_id_=rid,
            run_config=cfg,
            command=cmd,
            denominators=(
                denoms_run if rkey is None else denoms_run.get(rkey, {})
            ),
            extra=extra,
        )

    # ---- W-3：各 τ 档的类别分布（逐例 ＋ 跨例矩阵）----
    counts_rows: list[dict] = []
    for result in results:
        crit = int(result["extras"]["criterion_window_frames"])
        by_mode = {
            mode: counts_by_tau(
                result["rows"][mode], tau_values=taus, mode=mode,
                criterion_window_frames=crit,
            )
            for mode in modes
        }
        case = {
            "例": result["label"],
            "recording_id": result["recording_id"],
            "by_ref_mode": by_mode,
        }
        counts_rows.append(case)
        export_json(
            out / f"counts_by_tau.{result['recording_id']}.json",
            {
                "format": "acouscope-counts-by-tau-case",
                "version": 1,
                "run_id": rid,
                "例": result["label"],
                "recording_id": result["recording_id"],
                **by_mode,
                "by_ref_mode": by_mode,
                "provenance": _prov(str(result["recording_id"])),
            },
        )
    export_json(
        out / "counts_by_tau_summary.json",
        {
            "run_id": rid,
            "records": counts_rows,
            **counts_by_tau_matrix(counts_rows),
            "provenance": _prov(),
        },
    )

    # ---- W-4：逐例三栏件 ＋ 跨例汇总 ----
    for result in results:
        rkey = str(result["recording_id"])
        export_json(
            out / f"three_column.{rkey}.json",
            {
                "format": "acouscope-three-column",
                "version": 1,
                "run_id": rid,
                "例": result["label"],
                "recording_id": rkey,
                "by_ref_mode": three_by_rid[rkey],
                "priority_note": PRIORITY_NOTE,
                "provenance": _prov(rkey),
            },
        )
    export_json(
        out / "three_column_summary.json",
        {
            "format": "acouscope-three-column-summary",
            "version": 1,
            "run_id": rid,
            "tau_band": reads_band,
            "tau_cents": reads_tau,
            "tau_status": reads_status,
            "per_recording": [
                {
                    "例": result["label"],
                    "recording_id": str(result["recording_id"]),
                    "by_ref_mode": {
                        mode: {
                            "tau_cents": three_by_rid[str(result["recording_id"])][mode]["tau_cents"],
                            "tau_status": three_by_rid[str(result["recording_id"])][mode]["tau_status"],
                            "low_confidence_count": three_by_rid[str(result["recording_id"])][mode]["low_confidence_count"],
                            "coexist_and_low_conf": three_by_rid[str(result["recording_id"])][mode]["coexist_and_low_conf"],
                            "n_coexist_ge2_turns": three_by_rid[str(result["recording_id"])][mode]["denominators"]["n_coexist"],
                            "denominators": three_by_rid[str(result["recording_id"])][mode]["denominators"],
                            "identity_check": three_by_rid[str(result["recording_id"])][mode]["identity_check"],
                            "identity_checks": three_by_rid[str(result["recording_id"])][mode]["identity_checks"],
                            "counts_per_recording": three_by_rid[str(result["recording_id"])][mode]["counts_per_recording"],
                            "counts_per_recording_excluding_low_freq": three_by_rid[str(result["recording_id"])][mode]["counts_per_recording_excluding_low_freq"],
                            "n_low_frequency_unreliable_segments": three_by_rid[str(result["recording_id"])][mode]["denominators"]["n_low_freq_unreliable"],
                            "counts_cross": three_by_rid[str(result["recording_id"])][mode]["counts_cross"],
                        }
                        for mode in modes
                    },
                }
                for result in results
            ],
            "priority_note": PRIORITY_NOTE,
            "denominator_policy": DENOMINATOR_POLICY,
            "indeterminate_name_zh": INDETERMINATE_ZH,
            "indeterminate_note_zh": INDETERMINATE_NOTE_ZH,
            "low_frequency_class": LOW_FREQ_CLASS,
            "low_frequency_note_zh": LOW_FREQ_NOTE_ZH,
            "denominator_note": (
                "n_all／n_judgable／n_axis／n_composite／n_indeterminate／n_high_conf／"
                "n_low_conf／n_conf_missing／n_coexist／n_low_freq_unreliable／"
                "n_denominator_body 逐例逐口径给出；n_coexist 与 n_low_freq_unreliable "
                "是重叠量，各列之和不得当总段数使用。"
            ),
            "provenance": _prov(),
        },
    )

    # ---- W-6：网格边界钳位与频率范围分列（逐例 ＋ 汇总）----
    grid_rows: list[dict] = []
    for result in results:
        rkey = str(result["recording_id"])
        grid = result["extras"]["grid"]
        crit = int(result["extras"]["criterion_window_frames"])
        affected: dict[str, dict] = {}
        denominators: dict[str, dict] = {}
        for mode in modes:
            hit = [
                row for row in result["rows"][mode]
                if int(row.get("clamped_candidate_frames") or 0) > 0
                or int(row.get("output_at_grid_min_frames") or 0) > 0
            ]
            block = counts_block(
                result["rows"][mode], tau_cents=reads_tau,
                criterion_window_frames=crit,
            )
            denominators[mode] = block
            affected[mode] = {
                "n_affected_segments": int(len(hit)),
                "n_segments": int(len(result["rows"][mode])),
                "segments": [
                    {
                        "segment_id": row.get("segment_id"),
                        "clamped_candidate_frames": row.get("clamped_candidate_frames"),
                        "output_at_grid_min_frames": row.get("output_at_grid_min_frames"),
                        "entered_cavity_type": classify_cavity_type(row, tau_cents=reads_tau),
                        "indeterminate": not classify_segment(
                            row, criterion_window_frames=crit,
                            tau_cents=reads_tau,
                        )["in_judgable"],
                        "head_deviation_cents": row.get("head_deviation_cents"),
                        "tail_deviation_cents": row.get("tail_deviation_cents"),
                        "turns": row.get("turns"),
                        "in_turn_stats": bool(row.get("turns_valid")),
                    }
                    for row in hit
                ],
            }
        payload = grid_boundary_payload(
            recording_id=rkey,
            label=result["label"],
            grid={
                "min_hz": grid.get("grid_min_hz") or GRID_MIN_HZ,
                "max_hz": grid.get("grid_freq_max_hz"),
                "pitch_bins": 345,
                "bins_per_semitone": 5,
                "bin_cents": 20.0,
            },
            candidate=grid,
            output={**grid, "frames": grid.get("frames")},
            affected=affected,
            tau_cents=reads_tau,
            denominators=denominators,
        )
        payload.update(
            {
                "format": "acouscope-grid-boundary",
                "version": 1,
                "run_id": rid,
                "fminfmax_variant": cfg["fminfmax_variant"],
                "provenance": _prov(rkey),
            }
        )
        grid_rows.append(payload)
        export_json(out / f"grid_boundary.{rkey}.json", payload)
    export_json(
        out / "grid_boundary_summary.json",
        {
            "format": "acouscope-grid-boundary-summary",
            "version": 1,
            "run_id": rid,
            "fminfmax_variant": cfg["fminfmax_variant"],
            "grid_min_hz": GRID_MIN_HZ,
            "per_recording": [
                {
                    "recording_id": row["recording_id"],
                    "例": row["label"],
                    "candidate_range_hz": row["candidate_face"]["candidate_range_hz"],
                    "grid_clamp_below_frames": row["candidate_face"]["grid_clamp_below_frames"],
                    "grid_clamp_below_candidates": row["candidate_face"]["grid_clamp_below_candidates"],
                    "grid_clamp_below_frame_share": row["candidate_face"]["grid_clamp_below_frame_share"],
                    "output_at_grid_min_frames": row["output_face"]["output_at_grid_min_frames"],
                    "hmm_output_range_hz": row["output_face"]["hmm_output_range_hz"],
                    "n_affected_segments": row["n_affected_segments"],
                    "low_frequency_unreliable_segments": row[
                        "n_low_frequency_unreliable_segments"
                    ],
                    "excluded_from_denominators": row["excluded_from_denominators"],
                    "denominator_impact": row["denominator_impact"],
                }
                for row in grid_rows
            ],
            "low_frequency_class": LOW_FREQ_CLASS,
            "low_frequency_note_zh": LOW_FREQ_NOTE_ZH,
            "note": (
                "候选面与输出面分列；钳位计数只由候选面成立。低频不可靠段单列一类，"
                "不入正文分母（n_denominator_body），但仍在 W-8 的四值分母 n_judgable 内。"
            ),
            "provenance": _prov(),
        },
    )

    # ---- W-2：两口径改判明细（双档各一份，逐例件 ＋ 汇总件）----
    flips_by_rid: dict[str, dict] = {}
    for result in results:
        rkey = str(result["recording_id"])
        bands: dict[str, dict] = {
            TAU_BAND_CONTROL: pair_flip_detail(
                result["rows"][REF_ABSOLUTE], result["rows"][REF_MAIN_TONE],
                tau_cents=None, overlap_ratio=overlap_ratio, band=TAU_BAND_CONTROL,
            )
        }
        if main_band:
            bands[TAU_BAND_MAIN] = pair_flip_detail(
                result["rows"][REF_ABSOLUTE], result["rows"][REF_MAIN_TONE],
                tau_cents=float(tau_analysis), overlap_ratio=overlap_ratio,
                band=TAU_BAND_MAIN,
            )
        flips_by_rid[rkey] = bands
        export_json(
            out / f"dual_calibre_flips.{rkey}.json",
            {
                "format": "acouscope-dual-calibre-flips",
                "version": 1,
                "run_id": rid,
                "例": result["label"],
                "recording_id": rkey,
                "calibration_note": CALIBRATION_NOTE,
                "bands": bands,
                "provenance": _prov(rkey),
            },
        )

    # ---- 分布件：对照档（既有名）＋ 主档（.tau_analysis）；四值分母＝可判段（W-8）----
    control_payloads_by_mode: dict[str, list[dict]] = {}
    main_payloads_by_mode: dict[str, list[dict]] = {}
    for mode in modes:
        control_payloads = [
            distribution_payload(
                r["rows"][mode],
                recording_id=r["recording_id"],
                ref_mode=mode,
                segment_source=r["distributions"][mode]["segment_source"],
                run_id_=rid,
                tau_band=TAU_BAND_CONTROL,
                tau_analysis=reads_tau,
                tau_provenance="platform_placeholder:TAU_CENTS_PLACEHOLDER",
                criterion_window_frames=int(
                    r["extras"]["criterion_window_frames"]
                ),
                provenance=_prov(str(r["recording_id"])),
            )
            for r in results
        ]
        control_payloads_by_mode[mode] = control_payloads
        export_json(out / f"type_distribution.{mode}.json", control_payloads)
        sweeps = [r["sweeps"][mode] for r in results]
        export_json(out / f"tau_sweep_summary.{mode}.json", {
            **sweep_summary(sweeps, ref_mode=mode, run_id_=rid),
            "provenance": _prov(),
        })
        if main_band:
            main_payloads = [
                distribution_payload(
                    r["rows"][mode],
                    recording_id=r["recording_id"],
                    ref_mode=mode,
                    segment_source=r["distributions"][mode]["segment_source"],
                    run_id_=rid,
                    tau_band=TAU_BAND_MAIN,
                    tau_analysis=reads_tau,
                    tau_provenance=tau_provenance or "cli:--tau-analysis",
                    criterion_window_frames=int(
                        r["extras"]["criterion_window_frames"]
                    ),
                    provenance=_prov(str(r["recording_id"])),
                )
                for r in results
            ]
            main_payloads_by_mode[mode] = main_payloads
            export_json(
                out / f"type_distribution.tau_analysis.{mode}.json", main_payloads
            )
    for result in results:
        for mode, sweep in result["sweeps"].items():
            export_json(
                out / f"tau_sweep.{result['recording_id']}.{mode}.json",
                {**sweep, "provenance": _prov(str(result["recording_id"]))},
            )

    export_rows_csv(
        out / "type_distribution.csv",
        _payload_rows(control_payloads_by_mode, results, tau_band=TAU_BAND_CONTROL),
    )
    # ---- W-14-02：段行 CSV／JSON（含段内状态、主导态、三态占比）----
    for result in results:
        rkey = str(result["recording_id"])
        for mode in modes:
            rows = result["rows"][mode]
            export_rows_csv(
                out / f"segment_rows.{rkey}.{mode}.csv", segment_rows_csv(rows)
            )
            export_json(
                out / f"segment_rows.{rkey}.{mode}.json",
                {
                    "format": "acouscope-segment-rows",
                    "version": 1,
                    "run_id": rid,
                    "例": result["label"],
                    "recording_id": rkey,
                    "ref_mode": mode,
                    "state_fields": list(SEGMENT_STATE_FIELDS),
                    "state_note": (
                        "段内状态只导出不改判定：state 与 NoteSegment.state 逐字相同；"
                        "三态占比分母＝段内总帧数；未映射为腔头/腔腹/腔尾"
                    ),
                    "rows": rows,
                    "provenance": _prov(rkey),
                },
            )
    if main_band:
        export_rows_csv(
            out / "type_distribution.tau_analysis.csv",
            _payload_rows(main_payloads_by_mode, results, tau_band=TAU_BAND_MAIN),
        )
    export_json(out / "reconciliation.json", {
        **reconcile(results), "tau_band": TAU_BAND_CONTROL,
        "provenance": _prov(),
    })
    if main_band:
        export_json(out / "reconciliation.tau_analysis.json", {
            **reconcile(results, tau_cents=reads_tau, tau_status=reads_status),
            "tau_band": TAU_BAND_MAIN,
            "calibration_note": CALIBRATION_NOTE,
            "provenance": _prov(),
        })

    pairing: dict[str, list[dict]] = {}
    for band, tau_value in (
        [(TAU_BAND_CONTROL, None)]
        + ([(TAU_BAND_MAIN, float(tau_analysis))] if main_band else [])
    ):
        rows = _pairing_rows_for_band(
            results, tau_cents=tau_value, band=band, rid=rid,
            flips_by_rid=flips_by_rid, provenance=_prov,
        )
        pairing[band] = rows
        suffix = "" if band == TAU_BAND_CONTROL else ".tau_analysis"
        if rows:
            export_rows_csv(
                out / f"dual_calibre_pairing{suffix}.csv", _pairing_csv_rows(rows)
            )
            export_json(out / f"dual_calibre_pairing{suffix}.json", rows)

    # 判据窗长逐例（hop 可能不同）：分面数据按例取同一值，保证图／表同集合
    criteria = {
        str(r["label"]): int(r["extras"]["criterion_window_frames"])
        for r in results
    }
    for mode in modes:
        payload = panels_payload(
            [(r["label"], r["rows"][mode]) for r in results],
            run_id_=rid,
            ref_mode=mode,
            criterion_window_frames=criteria,
            provenance=_prov(),
        )
        suffix = "" if mode == REF_ABSOLUTE else f".{mode}"
        export_json(out / f"figure_b_panels{suffix}.json", payload)
        if main_band and mode == REF_ABSOLUTE:
            export_json(
                out / "figure_b_panels.tau_analysis.json",
                panels_payload(
                    [(r["label"], r["rows"][mode]) for r in results],
                    run_id_=rid,
                    ref_mode=mode,
                    tau_cents=reads_tau,
                    tau_band=TAU_BAND_MAIN,
                    tau_status_=reads_status,
                    tau_analysis=reads_tau,
                    criterion_window_frames=criteria,
                    provenance=_prov(),
                ),
            )

    figures: dict[str, dict] = {}
    if figure_out is not None:
        if main_band:
            # W-10：正文主图 ＝ **主档**（与表 4-2 主档同分母、同 run_id）
            figures["main_declared"] = render_figure_b(
                out / "figure_b_panels.tau_analysis.json", figure_out,
                stem=figure_stem,
            )
            verify_figure_table(
                out,
                panels_path=out / "figure_b_panels.tau_analysis.json",
                tables_path=out / "type_distribution.tau_analysis.absolute.json",
                check_name="figure_table_check.tau_analysis.json",
                provenance=_prov(),
            )
            # 对照档图另存一件，不作正文主图
            figures["control"] = render_figure_b(
                out / "figure_b_panels.json", figure_out,
                stem=f"{figure_stem}_control",
            )
            verify_figure_table(
                out,
                check_name="figure_table_check.json",
                provenance=_prov(),
            )
        else:
            figures["control"] = render_figure_b(
                out / "figure_b_panels.json", figure_out, stem=figure_stem
            )
            verify_figure_table(
                out,
                check_name="figure_table_check.json",
                provenance=_prov(),
            )

    manifest = write_manifest(
        out,
        run_id_=rid,
        descriptor=descriptor,
        figures=figures,
        tau_values=taus,
        ref_modes=modes,
        window_s=window_s,
        min_window_s=min_window_s,
        fmin=fmin,
        fmax=fmax,
        segmenter=segmenter,
        template=template,
        overlap_ratio=overlap_ratio,
        smooth_k=smooth_k,
        min_thr=min_thr,
        tonic_window_s=tonic_window_s,
        tau_analysis=reads_tau,
        fminfmax_variant=cfg["fminfmax_variant"],
        command=cmd,
        denominator_policy=DENOMINATOR_POLICY,
        figure_mapping={
            f"{figure_stem}.png": f"{figure_stem}_tau_analysis.png",
            f"{figure_stem}.pdf": f"{figure_stem}_tau_analysis.pdf",
            f"{figure_stem}_control.png": f"{figure_stem}.png",
            f"{figure_stem}_control.pdf": f"{figure_stem}.pdf",
        } if main_band else {},
    )

    return {
        "run_id": rid,
        "out_dir": str(out),
        "manifest": str(manifest),
        "figures": figures,
        "reconciliation": reconcile(results),
        "results": results,
        "config": cfg,
        "three_column": three_by_rid,
        "grid_boundary": grid_rows,
        "pairing": pairing,
    }


def verify_figure_table(run_dir, *, panels_path=None, tables_path=None,
                        check_name: str = "figure_table_check.json",
                        provenance: Mapping | None = None) -> dict:
    """图件计数 ↔ 分布表计数**逐格核验**（走图件渲染的同一计数路径）。

    ``type_oscillation_data`` 即 ``paper_B`` 渲染所用的计数函数；本函数用它重算分面
    计数（``n_plotted``／``excluded``／``n_total``），与分布表的四值＋合计逐格比对，
    输出 ``figure_table_check.json``。任一行不等 ⇒ ``"pass": false``（不掩盖）。

    ``panels_path``／``tables_path`` 可显式给定（GUI 里 panels 未必落在运行目录中）；
    缺省取 ``run_dir/figure_b_panels.json`` 与 ``run_dir/type_distribution.absolute.json``。
    ``check_name`` 指定落盘名：主档须另出一份（``figure_table_check.tau_analysis.json``），
    使**主档与对照档各跑一次**闸门、互不覆盖。
    """
    from ..visualization.figures import load_panels, type_oscillation_data

    base = Path(run_dir)
    panels_file = Path(panels_path) if panels_path else base / "figure_b_panels.json"
    tables_file = Path(tables_path) if tables_path else base / "type_distribution.absolute.json"
    if not panels_file.is_file():
        raise ValueError(f"图件分面数据不存在：{panels_file}")
    if not tables_file.is_file():
        raise ValueError(f"分布件不存在（无法同源核验）：{tables_file}")
    panels = json.loads(panels_file.read_text(encoding="utf-8"))
    matrix = type_oscillation_data(load_panels(panels_file))
    tables = json.loads(tables_file.read_text(encoding="utf-8"))

    per: list[dict] = []
    ok = len(matrix["panels"]) == len(tables)  # 例数不齐 ⇒ 判不通过（不静默截断）
    if not ok:
        per.append({
            "pass": False,
            "reason": f"分面数 {len(matrix['panels'])} 与分布件例数 {len(tables)} 不等",
        })
    # 分面与分布表同源于同一 results 列表 ⇒ 逐位配对
    for panel, table in zip(matrix["panels"], tables):
        counts = table["counts_per_recording"]
        in_types = int(counts["上趋"] + counts["下趋"] + counts["平直"])
        entry = {
            "label": panel["label"],
            "recording_id": table["recording_id"],
            "run_id": panels.get("run_id"),
            "tau_cents": panels.get("tau_cents"),
            "tau_status": panels.get("tau_status"),
            "denominator_policy": table.get("counts_denominator"),
            "figure_plotted": int(panel["n_plotted"]),
            "figure_excluded": int(panel["excluded"]),
            "figure_total": int(panel["n_total"]),
            "table_n_axis": table.get("n_axis"),
            "table_n_composite": table.get("n_composite"),
            "table_n_judgable": table.get("n_judgable"),
            "table_n_indeterminate": table.get("n_indeterminate"),
            "table_n_low_freq_unreliable": table.get("n_low_freq_unreliable"),
            "table_in_types": in_types,
            "table_unclassified": int(counts["未分类"]),
            "table_total": int(counts["合计"]),
        }
        entry["pass"] = bool(
            entry["figure_plotted"] == in_types
            and entry["figure_excluded"] == entry["table_unclassified"]
            and entry["figure_total"] == entry["table_total"]
        )
        # W-10 A 应见：入图＝n_axis、未入三型＝n_composite、分母＝n_judgable。
        # 旧表件（无这三字段）不因此判负——只在字段在场时逐项核。
        named: dict[str, bool] = {}
        if entry["table_n_axis"] is not None:
            named["figure_plotted == table_n_axis"] = bool(
                entry["figure_plotted"] == entry["table_n_axis"]
            )
        if entry["table_n_composite"] is not None:
            named["figure_excluded == table_n_composite"] = bool(
                entry["figure_excluded"] == entry["table_n_composite"]
            )
        if entry["table_n_judgable"] is not None:
            named["figure_total == table_n_judgable"] = bool(
                entry["figure_total"] == entry["table_n_judgable"]
            )
        entry["checks_named"] = named
        entry["pass"] = bool(entry["pass"] and all(named.values()))
        ok = ok and bool(entry["pass"])
        per.append(entry)

    payload = {
        "format": "acouscope-figure-table-check",
        "version": 1,
        "run_id": panels.get("run_id"),
        "tau_band": panels.get("tau_band"),
        "pass": bool(ok),
        "panels": str(panels_file.name),
        "tables": str(tables_file.name),
        "per_recording": per,
        "note": "计数走图件渲染同一路径 type_oscillation_data；与分布表逐格比对。",
    }
    if provenance is not None:
        payload["provenance"] = dict(provenance)
    export_json(base / check_name, payload)
    return payload


def render_figure_b(panels_path, out_dir, *, stem: str = "figure_b") -> dict:
    """图件分面数据 → PNG／PDF（走通用图形公开 API ＋ ``paper_B`` 预设）。

    **与表同源同 τ**：渲染只消费 ``figure_b_panels.json``，而该文件由同一次运行
    的段行按平台声明的 τ 判出，故图件计数与分布表逐格相等（T-3）。
    导入在函数内延后进行 —— 避免 ``analysis`` ← ``visualization`` 的导入期环。
    """
    from ..visualization.figures import load_panels, type_oscillation, type_oscillation_data
    from ..visualization.presets import get_preset

    preset = get_preset("paper_B")
    data = type_oscillation_data(load_panels(panels_path))
    result = type_oscillation(
        data,
        out_dir,
        dpi=int(preset.get("dpi", 300)),
        formats=tuple(preset.get("formats", ("png", "pdf"))),
        labels=preset.get("labels"),
        title=None,
        style=tuple(preset.get("style", ("default", "zh_CN"))),
        stem=stem,
    )
    return {str(fmt): str(path) for fmt, path in dict(result["paths"]).items()}


def write_manifest(out_dir, *, run_id_: str, descriptor: Mapping,
                   figures: Mapping | None = None, **facets) -> Path:
    """写 ``MANIFEST.md``：run_id ＋ 全部产物 sha256 ＋ 取数面（既有交付惯例）。

    **人读面**；机读面以 ``run_descriptor['config']`` 为准（W-7 明定）。
    ``figures`` 支持两种形状：``{fmt: path}``（单档）与
    ``{档位: {fmt: path}}``（主档／对照档双档并陈），双档逐行记字节与 sha256。
    ``facets`` 另可含 ``denominator_policy``（W-8）与 ``figure_mapping``
    （W-10 新旧件对照：``{新档名: 旧档名}``）。
    """
    policy = facets.pop("denominator_policy", None)
    figure_mapping = facets.pop("figure_mapping", None)
    lines = [
        "# 平台运行交付 · 三型分布与 τ 敏感性（任务件-20261026 · T-1／T-2／T-3；丙案补项 W-1—W-10）",
        "",
        f"- **run_id**：`{run_id_}`（内容定址：sha256(输入清单 × 参数面 × 分段快照 × τ／口径面)[:16]，非时间戳）",
        f"- **日期**：2026-10-28 ｜ **产出方**：开发侧（acouscope 平台）",
        f"- **绝对路径**：`{Path(out_dir).resolve()}/`",
        "",
        "## 一、取数面（换任一参数即换数；**机读面以 `run_descriptor.json` 的 `config` 为准**）",
        "",
        "| 项 | 值 |",
        "|---|---|",
    ]
    for key in ("window_s", "min_window_s", "fmin", "fmax", "fminfmax_variant",
                "segmenter", "template", "overlap_ratio", "smooth_k", "min_thr",
                "tonic_window_s", "tau_values", "tau_analysis", "ref_modes"):
        if key in facets:
            lines.append(f"| `{key}` | `{facets[key]}` |")
    if facets.get("command"):
        lines += ["", "```bash", str(facets["command"]), "```"]
    lines += [
        "",
        "## 二、产物与 sha256",
        "",
        "| 文件 | 字节 | sha256 |",
        "|---|---:|---|",
    ]
    for path in sorted(Path(out_dir).iterdir()):
        if path.name == "MANIFEST.md" or not path.is_file():
            continue
        lines.append(
            f"| `{path.name}` | {path.stat().st_size} | `{_sha256_file(path)}` |"
        )
    if figures:
        lines += ["", "## 三、图件（与表同源同 τ；主档与对照档各一套）", "",
                  "| 档 | 格式 | 路径 | 字节 | sha256 |", "|---|---|---|---:|---|"]
        for band, entry in figures.items():
            if isinstance(entry, Mapping):
                for fmt, fpath in entry.items():
                    p = Path(fpath)
                    lines.append(
                        f"| `{band}` | `{fmt}` | `{p}` | {p.stat().st_size} | `{_sha256_file(p)}` |"
                    )
            else:
                p = Path(entry)
                lines.append(
                    f"| `-` | `{band}` | `{p}` | {p.stat().st_size} | `{_sha256_file(p)}` |"
                )
        lines += [
            "",
            "- **正文主图 = 主档**（`main_declared`，与表 4-2 主档同分母、同 `run_id`）；"
            "`control` 一件为对照档（按符号判），**不作正文主图**。",
        ]
        if figure_mapping:
            lines += ["", "### 新旧图件对照（W-10 换件）", "",
                      "| 新件 | 旧件（`run_id=ffa3de9ba823d582`，已归档） |", "|---|---|"]
            for new_name, old_name in dict(figure_mapping).items():
                lines.append(f"| `{new_name}` | `{old_name}` |")
    lines += [
        "",
        "## 四、口径声明（不掩盖）",
        "",
    ]
    if policy:
        lines += [
            f"- **四值分母 = 可判段**（`{policy}`）：`counts_per_recording` 的分母为"
            "`n_judgable = n_all − n_indeterminate`，故四值之和**不等于** `n_all`；"
            "`n_indeterminate`（**往复窗不可判**：段内有效帧 < 判据窗长 ≈ 0.10 s）"
            "不拿类型标签、不进四值。**此不可判不等于「类型不可判」**。",
            "- **低频不可靠单列**（`low_frequency_unreliable`）：候选低于网格下界 61.735 Hz "
            "或输出落最低格的段，另列计数与 `segment_id` 清单；正文比例分母取 "
            "`n_denominator_body = n_judgable − n_low_freq_unreliable`（件内与 W-8 分母并陈）。"
            "**不得**用 `hmm_output_range_hz` 的下限反证网格已覆盖低频。",
            "- **图／表同分母**：图分面只含可判段，入图＝`n_axis`、未入三型＝`n_composite`、"
            "分面 `n_total`＝四值之和＝`n_judgable`；闸件 `figure_table_check*.json` 逐例给结果。",
        ]
    lines += [
        "- **τ 双档并陈**：主档取**本次运行的口径声明** `tau_analysis`，"
        "`tau_status = run_config_declared_uncalibrated`（**未经参考语料标定**）；"
        "对照档取 `TAU_CENTS_PLACEHOLDER` 当前值（本运行 `null` ⇒ `unspecified_sign_based`，按符号判）。"
        "主档件与对照档件同 `run_id`，可逐格比对。",
        "- **扫描 τ ≠ 标定 τ**：`tau_sweep.*.json` 的 `tau_values` 含 10／20／30 音分，其 `tau_status_by_tau` 一律记 `assumed_for_scan`，**不得**当作主档或标定值引用。",
        "- **`未分类` = 复合型（头尾倾向相反）**，见各件 `label_gloss`；不等于「未达分段资格」。",
        "- **三栏并行**：`cavity_type`／`low_confidence`／`coexist_netflat_segturn` 可重叠，"
        "`indeterminate` 单列；六分母量与恒等式见 `three_column*.json`。",
        "- **网格边界**：候选面与 HMM 输出面分列（`grid_boundary*.json`）；钳位计数只由候选面成立。",
        f"- **A4 基准**：`reference_hz = {get_reference_status()['reference_hz']}`，`reference_status = {get_reference_status()['reference_status']}`，`source = {get_reference_status()['source']}`；"
        + (
            "A4 来源经参考音实测声明；D 档真实录音的精度标定不在本次运行范围"
            "（口径见 `dsp/reference_status.py`）。"
            if get_reference_status()["reference_status"] == "calibrated"
            else "平台缺 D 档参考音 ⇒ **未经参考音实测校准**"
            "（口径见 `dsp/reference_status.py`）。"
        ),
        "",
    ]
    target = Path(out_dir) / "MANIFEST.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def count_windows(audio_path, *, window_s: float, min_window_s: float) -> int:
    """窗数（**只读时长，不读样本**）：用于确定式进度的分母。"""
    import soundfile as sf

    info = sf.info(str(audio_path))
    return len(_window_offsets(int(info.frames), int(info.samplerate),
                              float(window_s), float(min_window_s)))


def parse_tau_values(text: str) -> list[float | None]:
    """``none,10,20,30`` → ``[None, 10.0, 20.0, 30.0]``（空串 ⇒ 默认四档）。

    ``None`` 一档即「平台未标定、按符号判」，用 ``none``／``null`` 表示。
    """
    raw = str(text or "").strip()
    if not raw:
        return list(DEFAULT_TAU_VALUES)
    out: list[float | None] = []
    for token in raw.split(","):
        item = token.strip().lower()
        if item in ("none", "null", ""):
            out.append(None)
        else:
            out.append(float(item))
    return out


def run_batch_from_spec(spec: Mapping, *, on_stage=None, on_progress=None,
                        should_cancel=None) -> dict:
    """**spec 驱动**的批量入口（GUI 与脚本共用同一条路）。

    ``spec`` 是纯 dict（JSON 可序列化），形如::

        {"cases": [{"recording_id": ..., "audio_path": ..., "label": ...,
                    "anchor_offset_cents": 90.45, "anchor_source": "空弦四弦中位"}],
         "out_dir": "...", "figure_out": null, "figure_stem": "figure_b",
         "tau_values": [null, 10.0, 20.0, 30.0],
         "ref_modes": ["absolute", "main_tone"],
         "params": {"window_s": 30.0, ...}}

    回调一律可选且**不带 UI 类型**（``report(text)``／``report(stage, value)``／
    ``should_cancel() -> bool``），故 analysis 层不依赖 Qt；GUI 侧把
    ``TaskReporter`` 包成这三个 callable。
    """
    cases_spec = list(spec.get("cases") or ())
    out_dir = spec.get("out_dir")
    if not cases_spec:
        raise ValueError("批量运行至少需要一条录音（spec.cases 为空）")
    if not out_dir:
        raise ValueError("批量运行必须给输出目录（spec.out_dir）")

    cases = [
        RecordingCase(
            recording_id=str(item.get("recording_id") or Path(str(item["audio_path"])).stem),
            audio_path=str(item["audio_path"]),
            label=item.get("label") or None,
            anchor_offset_cents=item.get("anchor_offset_cents"),
            anchor_source=item.get("anchor_source") or "",
            template=(
                None if item.get("template") is None else str(item["template"])
            ),
        )
        for item in cases_spec
    ]
    for case in cases:
        if not Path(str(case.audio_path)).is_file():
            raise ValueError(f"音频不存在：{case.audio_path}")

    params = dict(spec.get("params") or {})

    def _report(stage: str, value: float) -> None:
        if on_stage is not None:
            on_stage(stage)
        if on_progress is not None:
            on_progress(stage, value)

    tau_analysis = spec.get("tau_analysis")
    if tau_analysis is None:
        tau_analysis = params.get("tau_analysis")

    return run_batch(
        cases,
        out_dir=out_dir,
        window_s=float(params.get("window_s", DEFAULT_WINDOW_S)),
        min_window_s=float(params.get("min_window_s", DEFAULT_MIN_WINDOW_S)),
        fmin=float(params.get("fmin", DEFAULT_FMIN)),
        fmax=float(params.get("fmax", DEFAULT_FMAX)),
        segmenter=str(params.get("segmenter", DEFAULT_SEGMENTER)),
        template=str(params.get("template", DEFAULT_TEMPLATE)),
        tau_values=list(spec.get("tau_values") or DEFAULT_TAU_VALUES),
        ref_modes=tuple(spec.get("ref_modes") or (REF_ABSOLUTE, REF_MAIN_TONE)),
        overlap_ratio=float(params.get("overlap_ratio", DEFAULT_OVERLAP_RATIO)),
        smooth_k=int(params.get("smooth_k", 5)),
        min_thr=float(params.get("min_thr", 10.0)),
        figure_out=spec.get("figure_out") or None,
        figure_stem=str(spec.get("figure_stem") or "figure_b"),
        tonic_window_s=float(params.get("tonic_window_s", 30.0)),
        tau_analysis=None if tau_analysis is None else float(tau_analysis),
        tau_provenance=str(
            spec.get("tau_provenance")
            or ("spec:tau_analysis" if tau_analysis is not None else "")
        ),
        cases_source=str(spec.get("cases_source") or ""),
        on_progress=_report,
        should_cancel=should_cancel,
    )


def main(argv=None) -> int:
    """命令行入口：``python -m acouscope.analysis.readout --cases cases.json --out DIR``。"""
    ap = argparse.ArgumentParser(
        prog="readout",
        description="三型分布与 τ 敏感性的一站式运行（τ 由平台声明，图／表同源）",
    )
    ap.add_argument("--cases", required=True, help="输入清单 JSON（含 cases 列表）")
    ap.add_argument("--out", required=True, help="读数件输出目录")
    ap.add_argument("--figure-out", default=None, help="图件输出目录（给则渲图）")
    ap.add_argument("--figure-stem", default="figure_b")
    ap.add_argument("--window-s", type=float, default=DEFAULT_WINDOW_S)
    ap.add_argument("--min-window-s", type=float, default=DEFAULT_MIN_WINDOW_S)
    ap.add_argument("--fmin", type=float, default=DEFAULT_FMIN)
    ap.add_argument("--fmax", type=float, default=DEFAULT_FMAX)
    ap.add_argument("--segmenter", default=DEFAULT_SEGMENTER)
    ap.add_argument("--template", default=DEFAULT_TEMPLATE)
    ap.add_argument("--tau", default="none,10,20,30", help="扫描 τ 档（逗号分隔；none＝平台占位）")
    ap.add_argument("--tau-analysis", type=float, default=None,
                    help="主分析 τ 的运行口径声明（音分；与 --tau 扫描档**分离**；"
                         "缺省 ⇒ 只出按符号判对照档，不伪造主档）")
    ap.add_argument("--ref-modes", default="absolute,main_tone")
    ap.add_argument("--overlap-ratio", type=float, default=DEFAULT_OVERLAP_RATIO)
    ap.add_argument("--tonic-window-s", type=float, default=30.0,
                    help="主音拟合取数窗（秒）；平台标准口径 0–30 s（约定 #32）")
    ap.add_argument("--smooth-k", type=int, default=5)
    ap.add_argument("--min-thr", type=float, default=10.0)
    args = ap.parse_args(argv)

    cases = cases_from_json(args.cases)
    summary = run_batch(
        cases,
        out_dir=args.out,
        window_s=args.window_s,
        min_window_s=args.min_window_s,
        fmin=args.fmin,
        fmax=args.fmax,
        segmenter=args.segmenter,
        template=args.template,
        tau_values=parse_tau_values(args.tau),
        ref_modes=[m.strip() for m in args.ref_modes.split(",") if m.strip()],
        overlap_ratio=args.overlap_ratio,
        smooth_k=args.smooth_k,
        min_thr=args.min_thr,
        figure_out=args.figure_out,
        figure_stem=args.figure_stem,
        tonic_window_s=args.tonic_window_s,
        tau_analysis=args.tau_analysis,
        tau_provenance=(
            f"cli:--tau-analysis {args.tau_analysis:g}"
            if args.tau_analysis is not None
            else ""
        ),
        cases_source=str(args.cases),
    )
    print(json.dumps(
        {
            "run_id": summary["run_id"],
            "out_dir": summary["out_dir"],
            "manifest": summary["manifest"],
            "figures": summary["figures"],
            "per_recording": [
                {
                    "recording_id": r["recording_id"],
                    "label": r["label"],
                    "n_windows": len(r["windows"]),
                    "counts": {m: p["counts_per_recording"] for m, p in r["distributions"].items()},
                    "tau_cents": r["distributions"]["absolute"]["tau_cents"],
                    "tau_status": r["distributions"]["absolute"]["tau_status"],
                    "flip_count": {m: s["flip_count"] for m, s in r["sweeps"].items()},
                    "flip_rate": {m: s["flip_rate"] for m, s in r["sweeps"].items()},
                    "unpaired_segments": None if not r["pairing"] else r["pairing"]["unpaired_segments"],
                }
                for r in summary["results"]
            ],
        },
        ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
