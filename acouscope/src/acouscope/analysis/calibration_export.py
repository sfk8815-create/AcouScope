# SPDX-License-Identifier: GPL-3.0-only
"""平台精度标定导出（任务-20261025-平台图导出 乙）。

**定位：** 精度标定是平台能力，不是支持层脚本的私活。本模块把「参考音 → 偏差
统计 → 报告 + 参数快照」接成平台公开路径；论文 §四 的精度表直接取本模块输出。

三档状态，**不得混称**（``status`` 字段）：

- ``measured``：给了参考音（D 档 A4 参考音或已知音高的稳态长音），真测真算，
  ``is_calibration=True``；
- ``pending``：**未给参考音**（D 档未到）⇒ 四项统计量一律 ``None``，显式
  ``pending``，**不伪造标定数**；
- ``chain_only``：合成信号只验链路（``synth=True``），``is_calibration=False``，
  不得称标定。

统计口径复用 :mod:`acouscope.analysis.calibration`（「对参考真值」口径，四项统计量
n／mean_bias／dispersion／p95_abs 定死），本模块**不重实现**统计、不改测量取法。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .calibration import calibrate_against_reference
from .params_snapshot import analysis_params_snapshot

__all__ = [
    "CALIBRATION_COLUMNS",
    "CALIBRATION_EXPORT_FORMAT",
    "CALIBRATION_EXPORT_VERSION",
    "PRECISION_PRESETS",
    "STATUS_CHAIN_ONLY",
    "STATUS_MEASURED",
    "STATUS_PENDING",
    "build_calibration_payload",
    "calibration_report",
    "calibration_rows",
    "calibration_table_rows",
    "export_calibration_csv",
    "export_calibration_json",
    "reference_pairs_from_signal",
    "reference_pairs_from_tone",
]

CALIBRATION_EXPORT_FORMAT = "acouscope-calibration-export"
CALIBRATION_EXPORT_VERSION = 1

STATUS_MEASURED = "measured"
STATUS_PENDING = "pending"
STATUS_CHAIN_ONLY = "chain_only"

_STAT_KEYS = ("n", "mean_bias_cents", "dispersion_cents", "p95_abs_cents")
_EMPTY_STATS = {"n": 0, "mean_bias_cents": None, "dispersion_cents": None, "p95_abs_cents": None}


def _base_hz(params: dict) -> float:
    """A4 基准：只从参数快照取（平台单一来源；本模块不写死基准值）。"""
    base = params.get("a4_reference_hz")
    if base is None:
        raise ValueError("参数快照缺 a4_reference_hz：基准未定义，标定不可进行")
    return float(base)


def _resolve_ref(ref_hz: float | None, base_hz: float | None) -> tuple[float, float]:
    """参考频率与基准缺省时取参数快照；显式给值一律以调用方为准。"""
    params = analysis_params_snapshot()
    base = _base_hz(params) if base_hz is None else float(base_hz)
    ref = base if ref_hz is None else float(ref_hz)
    return ref, base


def reference_pairs_from_signal(
    signal,
    sr: int,
    *,
    ref_hz: float | None = None,
    base_hz: float | None = None,
    fmin: float = 60.0,
    fmax: float = 1500.0,
    max_frames: int | None = None,
) -> list[tuple[float, float]]:
    """稳态参考信号 → ``(measured_cents, reference_cents)`` 配对序列。

    逐帧取平台音高（``stream_pitch``）的有声帧：``measured_cents`` 为该帧 f0 相对
    A4 基准的音分，``reference_cents`` 为参考频率相对同一基准的音分；二者之差即
    该帧偏差（由 :func:`calibrate_against_reference` 汇总）。无声帧不参与，不补零。

    ``ref_hz``／``base_hz`` 省略时取参数快照（基准 = ``a4_reference_hz``）。
    """
    from .pitch_stream import stream_pitch

    ref, base = _resolve_ref(ref_hz, base_hz)
    sig = np.asarray(signal, dtype=float)
    tr = stream_pitch(signal=sig, sr=int(sr), fmin=float(fmin), fmax=float(fmax), block_seconds=30.0)
    f0 = np.asarray(tr.f0_hz, dtype=float)
    ok = np.isfinite(f0) & (f0 > 0)
    vals = f0[ok]
    if max_frames is not None:
        vals = vals[: int(max_frames)]
    ref_cents = 1200.0 * float(np.log2(ref / base))
    return [(1200.0 * float(np.log2(float(v) / base)), ref_cents) for v in vals]


def reference_pairs_from_tone(audio_path, *, ref_hz: float | None = None, base_hz: float | None = None,
                              fmin: float = 60.0, fmax: float = 1500.0,
                              max_frames: int | None = None) -> list[tuple[float, float]]:
    """参考音文件（单声道或双声道，取均值）→ 配对序列。"""
    import soundfile as sf

    data, sr = sf.read(str(audio_path), dtype="float64", always_2d=True)
    sig = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    return reference_pairs_from_signal(
        sig, int(sr), ref_hz=ref_hz, base_hz=base_hz, fmin=fmin, fmax=fmax, max_frames=max_frames
    )


def _synth_tone(freq_hz: float, sr: int = 44100, dur: float = 1.0) -> np.ndarray:
    t = np.arange(int(sr * dur)) / float(sr)
    return 0.2 * np.sin(2.0 * np.pi * float(freq_hz) * t)


def calibration_report(
    *,
    reference_path=None,
    ref_hz: float | None = None,
    base_hz: float | None = None,
    dataset: str = "",
    synth: bool = False,
    fmin: float = 60.0,
    fmax: float = 1500.0,
) -> dict:
    """**通用标定报告**（平台核心，不含任何论文专用命名或列序）。

    ``pending`` 时四项统计量恒 ``None``（不填 0）；``chain_only`` 时统计量只是
    合成信号的链路验证读数，``is_calibration=False``。``ref_hz``／``base_hz`` 省略
    ⇒ 取参数快照的 A4 基准（参考音本身即基准音）。

    呈现层（论文表列序等）走 :func:`calibration_rows` 的 ``preset``，不进本函数。
    """
    params = analysis_params_snapshot()
    base = _base_hz(params) if base_hz is None else float(base_hz)
    ref = base if ref_hz is None else float(ref_hz)
    payload = {
        "format": CALIBRATION_EXPORT_FORMAT,
        "version": CALIBRATION_EXPORT_VERSION,
        "dataset": str(dataset or ""),
        "ref_hz": float(ref),
        "reference_path": None if reference_path is None else str(reference_path),
        "params_snapshot": params,
        "method": {
            "base_hz": base,
            "fmin": float(fmin),
            "fmax": float(fmax),
            "pitch_backend": str(params.get("pyin_marker", "")),
            "note": "逐帧 f0 相对参考频率的偏差分布；口径见 analysis/calibration.py",
        },
    }

    if reference_path is None and not synth:
        payload.update(
            {
                "status": STATUS_PENDING,
                "is_calibration": False,
                "stats": dict(_EMPTY_STATS),
                "reason": "D 档参考音未提供：平台不出标定数（pending，不伪造）",
            }
        )
        return payload

    if reference_path is None:
        pairs = reference_pairs_from_signal(_synth_tone(ref), 44100, ref_hz=ref, base_hz=base)
        payload.update(
            {
                "status": STATUS_CHAIN_ONLY,
                "is_calibration": False,
                "stats": calibrate_against_reference(pairs),
                "reason": "合成信号只验链路，不构成标定",
                "source": "synthetic",
            }
        )
        return payload

    pairs = reference_pairs_from_tone(reference_path, ref_hz=ref, base_hz=base, fmin=fmin, fmax=fmax)
    payload.update(
        {
            "status": STATUS_MEASURED,
            "is_calibration": True,
            "stats": calibrate_against_reference(pairs),
            "source": "reference_tone",
        }
    )
    return payload


#: 通用全列（一档一行；pending 一格不填数）
CALIBRATION_COLUMNS = (
    "dataset",
    "status",
    "is_calibration",
    "ref_hz",
    "n",
    "mean_bias_cents",
    "dispersion_cents",
    "p95_abs_cents",
    "a4_reference_hz",
    "pitch_backend",
    "reason",
)

#: 呈现层预设（只定列序与取舍，不改数值）：论文精度表取其中一档
PRECISION_PRESETS = {
    "paper": (
        "dataset",
        "status",
        "n",
        "mean_bias_cents",
        "dispersion_cents",
        "p95_abs_cents",
        "a4_reference_hz",
    ),
}


def calibration_rows(payload: dict, *, preset: str | None = None,
                     columns=None) -> list[dict]:
    """标定 payload → 表格行（默认全列；``preset="paper"`` 取论文精度表列序）。

    数值恒取自 payload，与 :func:`calibration_report` 同源；pending 档的统计量为
    ``None`` 而非 0。
    """
    if preset is not None and preset not in PRECISION_PRESETS:
        raise ValueError(f"未知预设：{preset!r}（可用：{list(PRECISION_PRESETS)}）")
    if columns is None:
        columns = PRECISION_PRESETS[preset] if preset else CALIBRATION_COLUMNS
    else:
        unknown = [c for c in columns if c not in CALIBRATION_COLUMNS]
        if unknown:
            raise ValueError(f"未知列：{unknown}（可用：{list(CALIBRATION_COLUMNS)}）")

    stats = payload.get("stats") or {}
    params = payload.get("params_snapshot") or {}
    full = {
        "dataset": payload.get("dataset", ""),
        "status": payload.get("status", ""),
        "is_calibration": int(bool(payload.get("is_calibration"))),
        "ref_hz": payload.get("ref_hz"),
        "n": stats.get("n", 0),
        "mean_bias_cents": stats.get("mean_bias_cents"),
        "dispersion_cents": stats.get("dispersion_cents"),
        "p95_abs_cents": stats.get("p95_abs_cents"),
        "a4_reference_hz": params.get("a4_reference_hz"),
        "pitch_backend": params.get("pyin_marker", ""),
        "reason": payload.get("reason", ""),
    }
    return [{key: full[key] for key in columns}]


def calibration_table_rows(payload: dict) -> list[dict]:
    """兼容别名：等价于 ``calibration_rows(payload)``（全列）。"""
    return calibration_rows(payload)


def build_calibration_payload(**kwargs) -> dict:
    """兼容别名：等价于 :func:`calibration_report`（旧调用点无需改）。"""
    return calibration_report(**kwargs)


def export_calibration_json(path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_calibration_csv(path, payload: dict, *, preset: str | None = None,
                           columns=None) -> None:
    rows = calibration_rows(payload, preset=preset, columns=columns)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
