# SPDX-License-Identifier: GPL-3.0-only
"""通用图表模板：段曲线／形态×往复度／参照系对比（平台能力，非论文专用）。

**分层**（2026-10-25 返工：图模块不得是论文专用命名）：

- 本模块 = **通用绘图与读数层**，名字描述图形本身：
  ``segment_curve``（一段的波形＋归一音高曲线）、``type_oscillation``（分面计数
  矩阵）、``reference_comparison``（多参照系归属对比）。
- :mod:`acouscope.visualization.presets` = **预设层**，只放裁剪／轴／图注参数
  （如 ``paper_A``／``paper_B``／``paper_C``）；论文图 = 通用图形 ＋ 预设。
- 数据一律现取自平台分析模块；图注／图题归写作侧，平台不写结论句。

数据层（``*_data``）与绘图层（同名无后缀）分开：前者纯计算可单测，后者只画。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from ..analysis.cavity_type import LABELS, LABEL_UNCLASSIFIED, repeat_degree_v2
from ..analysis.pitch_grid import _segment_degree, build_pitch_grid
from ..analysis.pitch_stream import stream_pitch
from ..analysis.tunings.root import with_root
from ..analysis.tunings.templates import get_template, list_templates
from .mpl_style import apply_style

__all__ = [
    "DEFAULT_DPI",
    "DENOMINATORS",
    "FIGURE_FORMATS",
    "NOTE_NAMES_SHARP",
    "TYPE_LABELS",
    "TURN_BINS",
    "degree_to_note_name",
    "load_panels",
    "main",
    "reference_comparison",
    "reference_comparison_data",
    "reference_comparison_from_audio",
    "segment_curve",
    "segment_curve_data",
    "type_oscillation",
    "type_oscillation_data",
]

DEFAULT_DPI = 300
FIGURE_FORMATS = ("png", "pdf")

#: 音名口径的显示序（十二平均律半音＝显示/索引约定，**不是**律学断言）
NOTE_NAMES_SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

#: 图件分母口径（W-14-04）：现行为／可判段／正文基准
DENOMINATORS = ("all", "judgable", "body")

#: 三型（不动、不设第四类）；「未分类」不入分类轴，只单列计数
TYPE_LABELS = tuple(label for label in LABELS if label != LABEL_UNCLASSIFIED)
#: 往复度描述分档（fixed 计数）
TURN_BINS = ("0", "1-2", "3-5", ">5")

_COLORS = {
    "waveform": "#333333",
    "trace": "#1f77b4",
    "segment": "#ffd9b3",
    "bound": "#d62728",
    "zero": "#999999",
}


# ---------------------------------------------------------------------------
# 读数层
# ---------------------------------------------------------------------------


def _read_window(audio_path, start_s: float, window_s: float):
    """读段起所在窗（单声道）；返回 ``(sig, sr, window_start_s)``。"""
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
    return sig, sr, w0


def _analyze(sig, sr, *, template: str, fmin: float, fmax: float, segmenter: str):
    tr = stream_pitch(signal=sig, sr=sr, fmin=fmin, fmax=fmax, block_seconds=30.0)
    f0 = np.asarray(tr.f0_hz, dtype=float)
    tuning = get_template(template)
    model = build_pitch_grid(tr.times, f0, tr.confidence, segmenter=segmenter, tuning=tuning)
    return tr, f0, model, tuning


def segment_curve_data(
    audio_path,
    start_s: float,
    end_s: float,
    *,
    window_s: float = 30.0,
    template: str = "12tet",
    fmin: float = 60.0,
    fmax: float = 1500.0,
    segmenter: str = "hmm",
) -> dict:
    """一段的曲线与统计量：波形、相对段中位音分、turns／峰峰／净差／振荡率。

    统计量与图同源：``turns``／``pp_cents``／``rate_hz`` 取 ``repeat_degree_v2``
    的 fixed 行；``net_cents`` ＝ 段尾偏离 − 段首偏离。段必须真实存在于平台分段
    结果中，否则报错（不臆造）。
    """
    start_s = float(start_s)
    end_s = float(end_s)
    if end_s <= start_s:
        raise ValueError("段终点须大于起点")
    sig, sr, w0 = _read_window(audio_path, start_s, window_s)
    tr, f0, model, _tuning = _analyze(
        sig, sr, template=template, fmin=fmin, fmax=fmax, segmenter=segmenter
    )

    local_s, local_e = start_s - w0, end_s - w0
    note = next(
        (
            cand
            for cand in model.notes
            if abs(cand.start_s - local_s) <= 2e-3 and abs(cand.end_s - local_e) <= 2e-3
        ),
        None,
    )
    if note is None:
        nearest = min(
            model.notes, key=lambda n: abs(n.start_s - local_s) + abs(n.end_s - local_e), default=None
        )
        hint = (
            "（最近段 {0:.3f}-{1:.3f}）".format(nearest.start_s + w0, nearest.end_s + w0)
            if nearest is not None
            else "（该窗无段）"
        )
        raise ValueError(f"段 {start_s:.3f}-{end_s:.3f} 不在平台分段结果中{hint}")

    seg_id = f"{note.start_s:.3f}-{note.end_s:.3f}"
    row = {r["segment_id"]: r for r in repeat_degree_v2(model, f0, mode="fixed")}[seg_id]

    ts = np.arange(sig.size) / float(sr) + w0
    mask = (tr.times >= start_s) & (tr.times <= end_s)
    seg_f0 = f0[mask]
    seg_f0 = seg_f0[np.isfinite(seg_f0) & (seg_f0 > 0)]
    median_hz = float(np.median(seg_f0)) if seg_f0.size else float("nan")
    if not np.isfinite(median_hz) or median_hz <= 0:
        raise ValueError("段内无有效 f0，无法归一（不臆造基线）")

    head = getattr(note, "head_deviation_cents", None)
    tail = getattr(note, "tail_deviation_cents", None)
    net = None if (head is None or tail is None) else float(tail) - float(head)

    return {
        "audio_path": str(audio_path),
        "start_s": start_s,
        "end_s": end_s,
        "window_start_s": w0,
        "window_s": float(window_s),
        "segmenter": segmenter,
        "template": template,
        "sr": sr,
        "times": ts,
        "signal": sig,
        "f0_times": tr.times[mask],
        "f0_cents": 1200.0 * np.log2(f0[mask] / median_hz),
        "median_hz": median_hz,
        "segment_id": f"{start_s:.3f}-{end_s:.3f}",
        "stats": {
            "turns": row["turns"],
            "pp_cents": row["pp_cents"],
            "rate_hz": row["rate_hz"],
            "valid": bool(row["valid"]),
            "thr_cents": row["thr_cents"],
            "net_cents": None if net is None else round(net, 2),
        },
    }


def type_oscillation_data(panels, *, types=None, bins=None, denominator: str = "all") -> dict:
    """段行 → 形态×往复度分面计数矩阵（每面板一份）。

    ``panels``：``[{"label": str, "rows": [...]}]``；行含 ``cavity_type``（或
    ``type``）与 turns（``turns``／``turns_fixed``／``osc_turns``）。非三型与缺计数
    行**不入矩阵**，只单列计数（三型不动、不设第四类）。

    ``denominator``（W-14-04，三档，**不改**三型／档位定义）：

    - ``all``（默认，**现行为**）：所有有 type 且有 turns 的行入矩阵；
    - ``judgable``：再要求 ``valid is True``（往复度有效；``osc_invalid`` 段不入）；
    - ``body``：在 ``judgable`` 基础上再剔除 ``low_frequency_unreliable is True`` 的段
      （正文基准分母）。

    ``excluded_by_reason`` **按原因独立计数**（``composite``／``no_turns``／
    ``osc_invalid``／``low_frequency``）：同一行可同时计入两类（如既非三型又低频
    不可靠），故**四者之和不得当排除总数**；当前档实际排除的行数见
    ``excluded``（＝``n_excluded_total``）及 ``excluded_active``。``reason_totals``
    与档位无关（同一批行同一原因数），故三档可比。
    """
    if denominator not in DENOMINATORS:
        raise ValueError(
            f"denominator 须为 {'/'.join(DENOMINATORS)} 之一，得到 {denominator!r}"
        )
    type_labels = tuple(types) if types else TYPE_LABELS
    bin_labels = tuple(bins) if bins else TURN_BINS
    out = []
    for panel in panels:
        counts = [[0] * len(bin_labels) for _ in type_labels]
        excluded = 0
        excluded_active = {"composite": 0, "no_turns": 0, "osc_invalid": 0, "low_frequency": 0}
        reason_totals = {"composite": 0, "no_turns": 0, "osc_invalid": 0, "low_frequency": 0}
        rows = panel.get("rows") or ()
        for row in rows:
            kind = row.get("cavity_type", row.get("type"))
            raw = row.get("turns", row.get("turns_fixed", row.get("osc_turns")))
            is_composite = kind not in type_labels
            no_turns = raw is None or raw == ""
            invalid = row.get("valid") is not True
            low_freq = row.get("low_frequency_unreliable") is True
            # 原因面：与档位无关的**独立**计数（同一行可计多类，故不相加当排除数）
            reason_totals["composite"] += int(is_composite)
            reason_totals["no_turns"] += int(no_turns)
            reason_totals["osc_invalid"] += int(invalid)
            reason_totals["low_frequency"] += int(low_freq)
            if is_composite:
                excluded += 1
                excluded_active["composite"] += 1
                continue
            if no_turns:
                excluded += 1
                excluded_active["no_turns"] += 1
                continue
            if denominator in ("judgable", "body") and invalid:
                excluded += 1
                excluded_active["osc_invalid"] += 1
                continue
            if denominator == "body" and low_freq:
                excluded += 1
                excluded_active["low_frequency"] += 1
                continue
            turns = int(raw)
            idx = 0 if turns == 0 else 1 if turns <= 2 else 2 if turns <= 5 else 3
            idx = min(idx, len(bin_labels) - 1)
            counts[type_labels.index(kind)][idx] += 1
        entry = {
            "label": str(panel.get("label", "")),
            "counts": counts,
            "n_total": len(rows),
            "n_plotted": int(sum(sum(r) for r in counts)),
            "excluded": excluded,
            "n_excluded_total": int(excluded),
            "denominator": str(denominator),
            "denominators_by_type": {
                label: int(sum(counts[index])) for index, label in enumerate(type_labels)
            },
            "excluded_by_reason": dict(excluded_active),
            "reason_totals": dict(reason_totals),
            "denominator_note": (
                "counts 为该档（all/judgable/body）下入矩阵的行；"
                "excluded_by_reason 为**该档**实际排除的原因计数；"
                "reason_totals 为与档位无关的原因总数（同一行可计多类，不得相加当排除数）"
            ),
        }
        # W-10：分面自带分母块时原样带出（不可判／低频不可靠各在何处可回查），
        # 计数口径仍只由 counts 决定——**不**把不可判段算进 n_plotted。
        for key in (
            "denominators",
            "counts_per_recording",
            "counts_per_recording_excluding_low_freq",
            "low_frequency_unreliable_segments",
        ):
            if key in panel:
                entry[key] = panel[key]
        out.append(entry)
    return {"types": list(type_labels), "bins": list(bin_labels), "panels": out}


def degree_to_note_name(tuning, degree: int) -> str | None:
    """音级 → 升号音名（``C``…``B``；W-14-03 的**显示/索引约定**）。

    口径：``tuning.degree_to_cents(degree) % 1200`` → 最近十二平均律半音（0–11）
    → 升号音名。**只用十二平均律作显示约定**：本函数不断言「该律符合某音名／
    某律」，也不作跨律学比较的结论；音名口径只解决「不同音级数模板不可按
    degree 序号直比」的问题。
    """
    if degree is None:
        return None
    cents = float(tuning.degree_to_cents(int(degree))) % 1200.0
    index = int(round(cents / 100.0)) % 12
    return NOTE_NAMES_SHARP[index]


def _template_at(name: str, root_hz: float | None):
    """取模板；``root_hz`` 给定时把 1/1 换到该频率（根音参数，2026-11-22 根音 P2）。

    ``root_hz=None`` ⇒ 原样返回内置模板（1/1＝A4，现行为逐位不变）。
    """
    tuning = get_template(name)
    if root_hz is None:
        return tuning
    return with_root(tuning, root_hz)


def reference_comparison_data(
    model,
    *,
    anchor_offset_cents: float | None = None,
    anchor_source: str | None = None,
    templates=None,
    limit: int = 60,
    note_name: bool = False,
    root_hz: float | None = None,
) -> dict:
    """多参照系归属对比（``absolute`` 口径）。

    **两个量必须分开**（2026-10-25 返工，来件三-1）：

    - ``anchor``：**锚定偏移**——由演奏实践／文献给定（如空弦实测、文献律高），
      调用方传入；这是论文 §三（二）意义上的整体偏移。缺省 ⇒ ``state="pending"``，
      本图不得据此作参照系切换论断。
    - ``median_deviation_cents``：各模板下**逐段「到最近律位的有符号偏离」的中位数**。
      它是**描述量**，不是锚定偏移，旧版本误作「整体偏移」，已改名。

    另有 ``changed_share``（相对首模板归属改变段占比）与逐段差 ``diffs_vs_first``。

    **两套口径并陈**（W-14-03，``note_name=True`` 时）：

    - ``changed_share``（旧键，**语义不变**）现另存为 ``changed_share_degree``——
      degree 口径按**音级序号**比，**不可**跨音级数不同的模板比较；
    - ``changed_share_note`` 为**音名口径**（跨模板比较以此为准）：该段该模板音名
      ≠ 首模板（如 12tet）音名，且两者均非 ``None``；分母
      ``comparable_segments_note`` ＝ 两者均非 ``None`` 的段数。

    **模板根音**（2026-11-22 根音 P2）：``root_hz`` 为各模板 1/1 所对频率，全部模板
    共用同一根音；缺省 ``None`` ⇒ 内置模板原样（1/1＝A4），输出与旧版逐位相同。
    给定时以 :func:`acouscope.analysis.tunings.root.with_root` 换根（取值见
    :func:`acouscope.analysis.tunings.root.root_hz`），并登记于 ``template_root_hz``
    ／``template_root_state``。音名口径的音名本就相对 1/1 取（见
    :func:`degree_to_note_name`），换根后仍相对该根音，跨模板比较口径不变。
    根音与锚定偏移是两个参数：锚只登记，不参与换根。
    """
    names = list(templates) if templates else list_templates()
    notes = list(getattr(model, "notes", ()))[: int(limit)]
    if not notes:
        raise ValueError("模型无段，无法作参照系对比")
    grid: list[list[int | None]] = []
    devs: list[list[float | None]] = []
    median_dev: dict[str, float | None] = {}
    for name in names:
        tuning = _template_at(name, root_hz)
        pairs = [_segment_degree(note.f0_hz, tuning) for note in notes]
        grid.append([deg for deg, _dev in pairs])
        devs.append([None if dev is None else round(float(dev), 2) for _deg, dev in pairs])
        vals = [float(dev) for _deg, dev in pairs if dev is not None]
        median_dev[name] = round(float(np.median(vals)), 2) if vals else None
    first = grid[0]
    diffs = [
        [None if (a is None or b is None) else int(a) - int(b) for a, b in zip(row, first)]
        for row in grid
    ]
    comparable = [sum(1 for a, b in zip(row, first) if a is not None and b is not None) for row in grid]
    changed = [
        sum(1 for a, b in zip(row, first) if a is not None and b is not None and a != b) for row in grid
    ]
    changed_share = {
        name: (round(changed[i] / comparable[i], 4) if comparable[i] else None)
        for i, name in enumerate(names)
    }
    anchor = (
        None
        if anchor_offset_cents is None
        else {"offset_cents": float(anchor_offset_cents), "source": anchor_source or ""}
    )
    payload = {
        "templates": names,
        "degrees": grid,
        "deviations_cents": devs,
        "median_deviation_cents": median_dev,
        "changed_share": changed_share,
        # 旧键语义不变；另存一份显式 degree 口径名（W-14-03），供两口径并陈
        "changed_share_degree": dict(changed_share),
        "diffs_vs_first": diffs,
        "anchor": anchor,
        "anchor_state": "given" if anchor else "pending",
        "n_segments": len(notes),
        "ref_mode": "absolute",
    }
    if root_hz is not None:
        # 只在显式给根音时登记：缺省输出逐键不变（既有严格相等契约，含对话框返回值）
        payload.update({"template_root_hz": float(root_hz), "template_root_state": "given"})
    if note_name:
        payload.update(_note_name_calibre(grid, names, root_hz=root_hz))
    return payload


def _note_name_calibre(grid, names, *, root_hz: float | None = None) -> dict:
    """音名口径块（W-14-03）：``note_names`` 与逐模板改判计数。

    ``grid`` 为 degree 口径的「模板 × 段」音级序号（与 ``reference_comparison_data``
    的 ``degrees`` 同源、同段序），本函数**只加口径、不动 degree 数值**。
    """
    names_list = list(names)
    tunings = {name: _template_at(name, root_hz) for name in names_list}
    note_grid: list[list[str | None]] = []
    for index, name in enumerate(names_list):
        tuning = tunings[name]
        note_grid.append(
            [
                None if degree is None else degree_to_note_name(tuning, int(degree))
                for degree in grid[index]
            ]
        )
    if not note_grid:
        raise ValueError("音名口径需要至少一个模板")
    first = note_grid[0]
    comparable = [
        sum(1 for a, b in zip(row, first) if a is not None and b is not None)
        for row in note_grid
    ]
    changed_indices: dict[str, list[int]] = {}
    changed_count: dict[str, int] = {}
    changed_share_note: dict[str, float | None] = {}
    for index, name in enumerate(names_list):
        hits = [
            position
            for position, (a, b) in enumerate(zip(note_grid[index], first))
            if a is not None and b is not None and a != b
        ]
        changed_indices[name] = hits
        changed_count[name] = len(hits)
        changed_share_note[name] = (
            round(len(hits) / comparable[index], 4) if comparable[index] else None
        )
    return {
        "note_names": {name: note_grid[index] for index, name in enumerate(names_list)},
        "note_names_reference": names_list[0] if names_list else None,
        "changed_count_note": changed_count,
        "changed_share_note": changed_share_note,
        "changed_indices_note": changed_indices,
        "comparable_segments_note": {
            name: comparable[index] for index, name in enumerate(names_list)
        },
        "note_name_note": (
            "音名口径为**显示/索引约定**（最近十二平均律半音，升号写法），不是律学断言；"
            "跨模板比较以音名口径为准；degree 口径（音级序号）不可跨音级数不同的模板比较。"
        ),
    }


# ---------------------------------------------------------------------------
# 绘图层
# ---------------------------------------------------------------------------


def _prepare_mpl(style: tuple[str, str], font_cjk: str, font_latin: str) -> None:
    import matplotlib

    matplotlib.use("Agg", force=False)
    apply_style(style[0], style[1], font_latin=font_latin, font_cjk=font_cjk)


def _save(fig, out_path, *, dpi: int, formats, stem: str) -> dict[str, str]:
    import matplotlib.pyplot as plt

    out_dir = Path(out_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        fig.savefig(path, dpi=dpi, format=fmt)
        paths[fmt] = str(path)
    plt.close(fig)
    return paths


DEFAULT_AXIS_LABELS = {"waveform": "波形", "cents": "相对段中位音分", "time": "时间 s"}


def segment_curve(
    data: dict,
    out_path,
    *,
    stem: str = "segment_curve",
    dpi: int = DEFAULT_DPI,
    formats=FIGURE_FORMATS,
    pad_left: float = 0.30,
    pad_right: float = 0.30,
    labels: dict | None = None,
    title: str | None = None,
    annotate_segment: bool = True,
    style: tuple[str, str] = ("default", "zh_CN"),
    font_cjk: str = "auto",
    font_latin: str = "auto",
) -> dict:
    """段曲线：上排波形、下排相对段中位音分；段界与判定段可标可去。"""
    import matplotlib.pyplot as plt

    labels = {**DEFAULT_AXIS_LABELS, **(labels or {})}
    _prepare_mpl(style, font_cjk, font_latin)

    lo = max(float(data["window_start_s"]), data["start_s"] - float(pad_left))
    hi = data["end_s"] + float(pad_right)
    ts, sig = data["times"], data["signal"]
    tm = (ts >= lo) & (ts <= hi)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True)
    ax1.plot(ts[tm], sig[tm], lw=0.5, color=_COLORS["waveform"])
    ax1.set_ylabel(labels["waveform"])
    if title:
        fig.suptitle(str(title), fontsize=12, x=0.012, y=0.985, ha="left", va="top")

    ax2.plot(data["f0_times"], data["f0_cents"], lw=1.0, color=_COLORS["trace"], marker=".", ms=2)
    if annotate_segment:
        ax2.axvspan(data["start_s"], data["end_s"], color=_COLORS["segment"], alpha=0.35, lw=0)
        for edge in (data["start_s"], data["end_s"]):
            ax2.axvline(edge, color=_COLORS["bound"], lw=0.8, ls="--")
    ax2.axhline(0.0, color=_COLORS["zero"], lw=0.6)
    ax2.set_ylabel(labels["cents"])
    ax2.set_xlabel(labels["time"])
    ax2.set_xlim(lo, hi)
    span = float(np.nanmax(np.abs(data["f0_cents"]))) if data["f0_cents"].size else 60.0
    lim = max(20.0, math.ceil(1.10 * span / 10.0) * 10.0)
    ax2.set_ylim(-lim, lim)
    if annotate_segment:
        # 放轴内左上角：作 ax 标题会与上排面板边框相撞（目验返工）
        ax2.text(
            0.006, 0.965, "段界虚线；底色为判定段",
            transform=ax2.transAxes, fontsize=7, color="#444444", va="top", ha="left",
        )
    for ax in (ax1, ax2):
        ax.tick_params(labelsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.955 if title else 0.99))

    paths = _save(fig, out_path, dpi=dpi, formats=formats, stem=stem)
    return {
        "kind": "segment_curve",
        "paths": paths,
        "dpi": int(dpi),
        "formats": list(formats),
        "labels": dict(labels),
        "title": title,
        "segment_id": data["segment_id"],
        "start_s": data["start_s"],
        "end_s": data["end_s"],
        "window_s": data["window_s"],
        "segmenter": data["segmenter"],
        "stats": data["stats"],
        "median_hz": data["median_hz"],
        "y_lim_cents": lim,
    }


def type_oscillation(
    data: dict,
    out_path,
    *,
    stem: str = "type_oscillation",
    dpi: int = DEFAULT_DPI,
    formats=FIGURE_FORMATS,
    labels: dict | None = None,
    title: str | None = None,
    style: tuple[str, str] = ("default", "zh_CN"),
    font_cjk: str = "auto",
    font_latin: str = "auto",
) -> dict:
    """形态×往复度分面计数热力图（分面数据由调用方给）。"""
    import matplotlib.pyplot as plt

    # 图面文案不含字段名（内部 key 仍是 `turns`；与 paper_B 预设同文案）
    labels = {"x": "往复度（分档）", "count": "段数", **(labels or {})}
    panels = data["panels"]
    if not panels:
        raise ValueError("至少需要一个分面")
    _prepare_mpl(style, font_cjk, font_latin)

    n = len(panels)
    ncols = 1 if n == 1 else 2
    nrows = int(math.ceil(n / ncols))
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(10, 3.2 * nrows + 0.8), squeeze=False, constrained_layout=True
    )
    vmax = max((max(max(r) for r in p["counts"]) for p in panels), default=0)
    for ax, panel in zip(axes.ravel(), panels):
        arr = np.asarray(panel["counts"], dtype=float)
        # pcolormesh（非 imshow）：出版 PDF 须为真矢量，热图不得内嵌位图
        im = ax.pcolormesh(
            np.arange(arr.shape[1] + 1) - 0.5,
            np.arange(arr.shape[0] + 1) - 0.5,
            arr,
            cmap="Blues",
            vmin=0,
            vmax=max(vmax, 1),
            shading="flat",
        )
        ax.invert_yaxis()
        ax.set_xticks(range(len(data["bins"])), data["bins"], fontsize=8)
        ax.set_yticks(range(len(data["types"])), data["types"], fontsize=8)
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                if arr[i, j]:
                    ax.text(
                        j, i, int(arr[i, j]), ha="center", va="center", fontsize=8,
                        color="white" if arr[i, j] > 0.6 * max(vmax, 1) else "#222222",
                    )
        ax.set_title(
            f"{panel['label']}（n={panel['n_plotted']}，未入三型 {panel['excluded']}）",
            fontsize=8, loc="left",
        )
        ax.set_xlabel(labels["x"], fontsize=8)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    if title:
        fig.suptitle(str(title), fontsize=12, x=0.012, y=0.995, ha="left", va="top")
    cbar = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.8, label=labels["count"])
    cbar.solids.set_rasterized(False)  # 出版 PDF 保真矢量（色条默认会被压成位图）

    paths = _save(fig, out_path, dpi=dpi, formats=formats, stem=stem)
    return {
        "kind": "type_oscillation",
        "paths": paths,
        "dpi": int(dpi),
        "formats": list(formats),
        "matrix": data,
        "labels": dict(labels),
        "title": title,
    }


def reference_comparison(
    data: dict,
    out_path,
    *,
    stem: str = "reference_comparison",
    dpi: int = DEFAULT_DPI,
    formats=FIGURE_FORMATS,
    labels: dict | None = None,
    title: str | None = None,
    require_anchor: bool = False,
    style: tuple[str, str] = ("default", "zh_CN"),
    font_cjk: str = "auto",
    font_latin: str = "auto",
) -> dict:
    """多参照系归属热力图；标注**锚定偏移**，中位偏离只作描述量。

    ``require_anchor=True``（论文预设）时，``data["anchor"]`` 为空即报错——不给出
    锚定偏移的参照系对比不得冒充「整体偏移已定」。
    """
    import matplotlib.pyplot as plt

    labels = {
        "y": "律制模板",
        "x": "段序号",
        "colorbar": "音级序号",
        "anchor_pending": "未提供锚定偏移：本图不作参照系切换的「整体偏移」论断",
        # 口径名的图面写法（内部 key 仍是 absolute，JSON／API 不变）
        "no_shift_note": "绝对口径不施加移调",
        # 模板刻度显示名：{内部 key: 图面名}；缺省则原样显示内部 key
        "template_labels": {},
        **(labels or {}),
    }
    if require_anchor and not data.get("anchor"):
        raise ValueError("该预设要求锚定偏移（anchor_offset_cents／anchor_source），未提供则不出图")
    anchor = data.get("anchor")
    _prepare_mpl(style, font_cjk, font_latin)

    arr = np.asarray(
        [[np.nan if v is None else float(v) for v in row] for row in data["degrees"]], dtype=float
    )
    fig, ax = plt.subplots(figsize=(11, 4.8))
    # pcolormesh：出版 PDF 保持真矢量（imshow 会把热图压成内嵌位图）
    im = ax.pcolormesh(
        np.arange(arr.shape[1] + 1) - 0.5,
        np.arange(arr.shape[0] + 1) - 0.5,
        np.ma.masked_invalid(arr),
        cmap="viridis",
        shading="flat",
    )
    ax.invert_yaxis()
    tick_names = [
        labels["template_labels"].get(name, name)  # 显示名可换；内部 key 不变
        for name in data["templates"]
    ]
    ax.set_yticks(range(len(data["templates"])), tick_names, fontsize=7)
    ax.set_xlabel(f"{labels['x']}（前 {data['n_segments']} 段）", fontsize=9)
    ax.set_ylabel(labels["y"], fontsize=9)
    if title:
        fig.suptitle(str(title), fontsize=12, x=0.012, y=0.985, ha="left", va="top")
    if anchor:
        note = (
            f"锚定偏移 {anchor['offset_cents']:+.2f} 音分"
            + (f"（{anchor['source']}）" if anchor.get("source") else "")
            + f"；{labels['no_shift_note']}"
        )
    else:
        note = labels["anchor_pending"]
    ax.set_title(note, fontsize=8, loc="left")
    cbar = fig.colorbar(im, ax=ax, shrink=0.85, label=labels["colorbar"])
    cbar.solids.set_rasterized(False)  # 同上：色条不栅格化
    fig.tight_layout(rect=(0, 0, 1, 0.94 if title else 0.97))

    paths = _save(fig, out_path, dpi=dpi, formats=formats, stem=stem)
    return {
        "kind": "reference_comparison",
        "paths": paths,
        "dpi": int(dpi),
        "formats": list(formats),
        "anchor": anchor,
        "anchor_state": data.get("anchor_state"),
        "tick_labels": tick_names,
        "note": note,
        "matrix": data,
        "labels": dict(labels),
        "title": title,
    }


# ---------------------------------------------------------------------------
# 一站式公开入口：音频 → 读数 → 出图（调用方不再拼私有名）
# ---------------------------------------------------------------------------


def reference_comparison_from_audio(
    audio_path,
    out_path,
    *,
    window_start_s: float = 0.0,
    window_s: float = 30.0,
    anchor_offset_cents: float | None = None,
    anchor_source: str | None = None,
    templates=None,
    limit: int = 60,
    require_anchor: bool = False,
    tuning_template: str = "12tet",
    note_name: bool = False,
    root_hz: float | None = None,
    **render_kwargs,
) -> dict:
    """参照系对比的一站式公开路径：读窗 → 分析 → 读数 → 出图。

    **窗起点是取数参数、不是呈现参数**：``window_start_s`` 只决定取哪一段音频
    （按 ``window_s`` 对齐到窗格起点），换窗即换数，出图前必须在论文表里登记
    实际取数窗与调音模板——故返回值追加 ``window_start_s``／``window_s``／
    ``tuning_template`` 三键（``window_start_s`` 为对齐后的**实际**窗起点）。

    ``render_kwargs`` 透传给 :func:`reference_comparison`（``dpi``／``formats``／
    ``labels``／``title``／``stem``／``style``／``font_*``）；``require_anchor``
    的硬闸在绘图层，缺锚即报错（不替调用方猜 0）。

    ``root_hz``：模板根音（Hz，缺省 ``None``＝1/1 取 A4，现行为）；透传
    :func:`reference_comparison_data`，返回值追加 ``template_root_hz``。
    """
    sig, sr, w0 = _read_window(audio_path, window_start_s, window_s)
    _tr, _f0, model, _tuning = _analyze(
        sig,
        sr,
        template=tuning_template,
        fmin=60.0,
        fmax=1500.0,
        segmenter="hmm",
    )
    data = reference_comparison_data(
        model,
        anchor_offset_cents=anchor_offset_cents,
        anchor_source=anchor_source,
        templates=templates,
        limit=int(limit),
        note_name=bool(note_name),
        root_hz=root_hz,
    )
    result = reference_comparison(
        data,
        out_path,
        require_anchor=bool(require_anchor),
        **render_kwargs,
    )
    out = {
        **result,
        "window_start_s": float(w0),
        "window_s": float(window_s),
        "tuning_template": str(tuning_template),
    }
    if root_hz is not None:
        out["template_root_hz"] = float(root_hz)
    return out


# ---------------------------------------------------------------------------
# CLI：--preset 选图形与参数（预设名不带 {a,b,c} 硬编码）
# ---------------------------------------------------------------------------


def load_panels(path) -> list:
    path = Path(path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload["panels"] if isinstance(payload, dict) else payload
    groups: dict[str, list[dict]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            groups.setdefault(row.get("label", ""), []).append(row)
    return [{"label": k, "rows": v} for k, v in groups.items()]


#: 兼容别名：旧调用点写的 ``figures._load_panels`` 仍等价可用（同一函数对象，
#: 不是第二份实现）；新代码一律走公开名 ``load_panels``。
_load_panels = load_panels


def main(argv=None) -> int:
    from .presets import get_preset, list_presets

    ap = argparse.ArgumentParser(
        prog="figures",
        description="通用图表导出（--preset 选预设；论文图 = 通用图形＋预设）",
    )
    ap.add_argument("--preset", required=True, choices=list_presets())
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--audio")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--panels")
    ap.add_argument("--anchor-cents", type=float, default=None)
    ap.add_argument("--anchor-source", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--window-start",
        type=float,
        default=0.0,
        help="取数窗起点（秒；仅 reference_comparison 预设用，按 --window_s 对齐）",
    )
    ap.add_argument(
        "--denominator",
        choices=list(DENOMINATORS),
        default="all",
        help="图件分母口径（W-14-04）：all=现行为／judgable=可判段／body=正文基准",
    )
    ap.add_argument(
        "--note-name",
        action="store_true",
        help="参照系对比增出音名口径（W-14-03；degree 口径仍随件保留）",
    )
    ap.add_argument("--title", default=None)
    ap.add_argument("--dpi", type=int, default=None)
    ap.add_argument("--stem", default=None)
    args = ap.parse_args(argv)

    preset = get_preset(args.preset)
    kind = preset["figure"]
    dpi = int(args.dpi or preset.get("dpi", DEFAULT_DPI))
    stem = args.stem or args.preset.lower()
    common = {
        "dpi": dpi,
        "formats": tuple(preset.get("formats", FIGURE_FORMATS)),
        "labels": preset.get("labels"),
        "title": args.title,
        "style": tuple(preset.get("style", ("default", "zh_CN"))),
        "stem": stem,
    }

    if kind == "segment_curve":
        if args.audio is None or args.start is None or args.end is None:
            ap.error("preset 需要 --audio --start --end")
        data = segment_curve_data(
            args.audio,
            args.start,
            args.end,
            window_s=float(preset.get("window_s", 30.0)),
            template=preset.get("tuning_template", "12tet"),
            segmenter=preset.get("segmenter", "hmm"),
        )
        result = segment_curve(
            data,
            args.out,
            pad_left=float(preset.get("pad_left", 0.30)),
            pad_right=float(preset.get("pad_right", 0.30)),
            annotate_segment=bool(preset.get("annotate_segment", True)),
            **common,
        )
    elif kind == "type_oscillation":
        if not args.panels:
            ap.error("preset 需要 --panels")
        data = type_oscillation_data(
            load_panels(args.panels), denominator=str(args.denominator)
        )
        result = type_oscillation(data, args.out, **common)
    else:
        if not args.audio:
            ap.error("preset 需要 --audio")
        if preset.get("require_anchor") and args.anchor_cents is None:
            ap.error("该预设要求 --anchor-cents（锚定偏移由演奏实践／文献给，平台不猜）")
        # 一站式公开入口：窗起点在此传入（换窗即换数，须登记）
        result = reference_comparison_from_audio(
            args.audio,
            args.out,
            window_start_s=float(args.window_start),
            window_s=float(preset.get("window_s", 30.0)),
            anchor_offset_cents=args.anchor_cents,
            anchor_source=args.anchor_source,
            templates=preset.get("templates"),
            limit=int(args.limit or preset.get("limit", 60)),
            require_anchor=bool(preset.get("require_anchor", False)),
            tuning_template=preset.get("tuning_template", "12tet"),
            note_name=bool(args.note_name),
            **common,
        )

    print(json.dumps(result, ensure_ascii=False, default=list))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
