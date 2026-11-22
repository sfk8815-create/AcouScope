# SPDX-License-Identifier: GPL-3.0-only
"""多轨测量结果汇总（每文件一行）与 CSV 落盘。

消费 T-1008/T-1019 逐轨结果缓存，将 measure + pitch 两类结果拼成一张表，
用于多文件批处理场景的结果对照与导出。只做取数与落盘，不做算法计算。
"""

from __future__ import annotations

import ast
import csv
import math

import numpy as np

from acouscope.ui.widgets.multitrack.analysis_source import (
    MEASURE_KIND,
    TrackResultCache,
)

__all__ = [
    "MEASUREMENT_COLUMNS",
    "rows_from_cache",
    "write_measurements_csv",
    "read_measurements_csv",
]

# 固定列序（导出 CSV 表头与行键一一对应）
MEASUREMENT_COLUMNS = (
    "track",
    "file",
    "duration_s",
    "sample_rate",
    "channels",
    "rms_db",
    "peak_db",
    "crest_db",
    "silence_ratio",
    "f0_median_hz",
    "f0_voiced_ratio",
    "offset_ms",
    "status",
)


def _pitch_f0_stats(result):
    """从 pitch 结果提取 F0 中位数与有声比；无有效帧返回 (None, None)。"""
    try:
        f0 = np.asarray(getattr(result, "f0_hz", ()), dtype=float)
    except Exception:  # noqa: BLE001 - 结果对象类型未知时不抛
        return None, None
    if f0.size == 0:
        return None, None
    valid = np.isfinite(f0) & (f0 > 0)
    n_valid = int(valid.sum())
    if n_valid == 0:
        return None, None
    median = float(np.median(f0[valid]))
    ratio = n_valid / f0.size
    return median, ratio


def rows_from_cache(
    session,
    cache,
    *,
    measure_kind=MEASURE_KIND,
    pitch_kind="pitch",
) -> list[dict]:
    """从逐轨结果缓存按轨道顺序提取每文件一行的测量汇总。

    返回 dict 列表（长度 = session.tracks() 长度），每行键集合 ==
    ``set(MEASUREMENT_COLUMNS)``；缺值一律 ``None``。session/cache 为 None
    或空会话时返回 ``[]``。任何单轨异常不中断整表（该轨按缺失处理）。
    """
    if session is None or cache is None:
        return []
    tracks = []
    try:
        tracks = session.tracks()
    except Exception:  # noqa: BLE001 - 会话异常时退化为空表
        return []
    if not tracks:
        return []

    rows: list[dict] = []
    for track in tracks:
        row = {col: None for col in MEASUREMENT_COLUMNS}
        try:
            track_id = getattr(track, "track_id", None)
            row["track"] = track_id
            row["file"] = getattr(track, "label", "") or ""
            row["offset_ms"] = float(getattr(track, "offset_ms", 0.0) or 0.0)
        except Exception:  # noqa: BLE001 - track 字段异常时按缺失处理
            continue

        has_measure = False
        try:
            key_m = TrackResultCache.key(track_id, measure_kind, None)
            result = cache.get(key_m)
            if isinstance(result, dict):
                has_measure = True
                for field in (
                    "duration_s",
                    "sample_rate",
                    "channels",
                    "rms_db",
                    "peak_db",
                    "crest_db",
                    "silence_ratio",
                ):
                    if field in result:
                        row[field] = result[field]
        except Exception:  # noqa: BLE001 - cache.get 异常按缺失处理
            pass

        has_pitch = False
        try:
            key_p = TrackResultCache.key(track_id, pitch_kind, None)
            result = cache.get(key_p)
            if result is not None:
                has_pitch = True
                med, ratio = _pitch_f0_stats(result)
                row["f0_median_hz"] = med
                row["f0_voiced_ratio"] = ratio
        except Exception:  # noqa: BLE001 - cache.get 异常按缺失处理
            pass

        if has_measure and has_pitch:
            row["status"] = "measured"
        elif has_measure or has_pitch:
            row["status"] = "partial"
        else:
            row["status"] = "missing"

        rows.append(row)

    return rows


def write_measurements_csv(path, rows: list[dict]) -> int:
    """每文件一行写测量汇总 CSV（repr 保精度可逆）；返回数据行数。"""
    count = 0
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(MEASUREMENT_COLUMNS)
        for row in rows:
            csv_row = []
            for col in MEASUREMENT_COLUMNS:
                value = row.get(col)
                if value is None:
                    csv_row.append("")
                else:
                    csv_row.append(repr(value))
            writer.writerow(csv_row)
            count += 1
    return count


def read_measurements_csv(path) -> list[dict]:
    """读测量汇总 CSV，还原为 dict 列表（空串 → None）。"""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if tuple(header) != MEASUREMENT_COLUMNS:
            raise ValueError(
                f"CSV header mismatch: expected {MEASUREMENT_COLUMNS}, got {tuple(header)}"
            )
        rows: list[dict] = []
        for raw in reader:
            row = {}
            for col, cell in zip(MEASUREMENT_COLUMNS, raw):
                if cell == "":
                    row[col] = None
                else:
                    row[col] = ast.literal_eval(cell)
            rows.append(row)
        return rows
