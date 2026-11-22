# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-B T05：测量元数据记录与区间统计导出（纯标准库，零 Qt／零第三方）。

一条「测量记录」= 17 个固定顺序字段（:data:`MEASUREMENT_FIELDS`）的 dict。
顺序固定是 CSV 无表头单行落盘／按位还原的契约：写手按本元组逐列写，
读方按同一元组 zip 还原，故 CSV 不依赖表头即可无损往返。

纪律（T05 设计约定）：
- ``format_version`` 恒 1、``generated_at`` 恒 UTC ISO8601（自动生成，不臆造）；
- 其余字段缺项一律填 ``None``（不臆造默认值）；
- ``input_sha256`` 若提供且非 ``None``，必须 64 位十六进制，否则 ``ValueError``；
- ``resample_quality`` / ``extra`` 为 dict（导出 CSV 时序列化为 JSON 字符串）；
- 零新增运行时依赖：仅 import 标准库。
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# 固定顺序，17 项（判据 2：MEASUREMENT_FIELDS 17 项齐）
MEASUREMENT_FIELDS = (
    "format_version",
    "generated_at",
    "sample_rate",
    "frame_size",
    "hop_length",
    "window",
    "zero_pad",
    "backend",
    "backend_version",
    "a4_reference_hz",
    "n_eff",
    "snr_db",
    "input_sha256",
    "calibration_status",
    "resample_quality",
    "uncertainty_cent",
    "extra",
)

_JSON_STRING_FIELDS = frozenset({"resample_quality", "extra"})
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def build_measurement_record(**kwargs) -> dict:
    """构建测量记录 dict（17 字段，顺序即 :data:`MEASUREMENT_FIELDS`）。

    ``format_version`` 恒为 ``1``；``generated_at`` 恒为
    ``datetime.now(timezone.utc).isoformat()``（UTC ISO8601）。其余字段从
    ``kwargs`` 取同名值，缺项填 ``None``（不臆造）；``kwargs`` 里的未知键忽略。

    ``input_sha256`` 若非 ``None``，必须是 64 位十六进制字符串（大小写 hex
    均可），否则抛 :class:`ValueError`；``None`` 表示未知／未提供，合法。
    """
    record = {field: kwargs.get(field) for field in MEASUREMENT_FIELDS}
    record["format_version"] = 1
    record["generated_at"] = datetime.now(timezone.utc).isoformat()

    sha = record["input_sha256"]
    if sha is not None:
        if not isinstance(sha, str) or _SHA256_RE.fullmatch(sha) is None:
            raise ValueError("input_sha256 必须为 64 位十六进制字符串")
    return record


def write_measurement_json(path, record: dict) -> None:
    """写 UTF-8 JSON（保留字段顺序，dict／None／数值原样，供 read 严格往返）。"""
    p = Path(path)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def read_measurement_json(path) -> dict:
    """读回 :func:`write_measurement_json` 的记录（往返一致）。"""
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _csv_cell(field: str, value) -> str:
    """单字段 → CSV 单元格：None → 空串；dict/list → JSON 字符串；其余 → str。"""
    if value is None:
        return ""
    if field in _JSON_STRING_FIELDS or isinstance(value, (dict, list, tuple, bool)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def write_measurement_csv(path, record: dict) -> None:
    """写单行 17 列 CSV（无表头，按 :data:`MEASUREMENT_FIELDS` 固定顺序）。

    ``resample_quality`` / ``extra`` 序列化为 JSON 字符串（含逗号／引号由
    ``csv.writer`` 正确转义）；``None`` 写空串。字段顺序固定即还原契约：
    读方用 ``zip(MEASUREMENT_FIELDS, row)`` 即可无损往返。
    """
    row = [_csv_cell(field, record.get(field)) for field in MEASUREMENT_FIELDS]
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(row)


def read_measurement_csv(path) -> dict:
    """按固定顺序读回单行 17 列 CSV（结构化字段还原，标量保持 str）。

    ``resample_quality`` / ``extra`` 列 ``json.loads`` 还原为对象；空串还原为
    ``None``；其余标量保持字符串（CSV 本身无类型，往返以字符串化等价为口径）。
    """
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if len(rows) != 1:
        raise ValueError("测量记录 CSV 必须恰好 1 行")
    if len(rows[0]) != len(MEASUREMENT_FIELDS):
        raise ValueError("测量记录 CSV 必须恰好 17 列")
    record = {}
    for field, cell in zip(MEASUREMENT_FIELDS, rows[0]):
        if cell == "":
            record[field] = None
        elif field in _JSON_STRING_FIELDS:
            record[field] = json.loads(cell)
        else:
            record[field] = cell
    return record
