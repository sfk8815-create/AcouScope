#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精度标定 CLI（对参考真值口径）（B2-02 / PI-P5 批次 2）。

用法（仓根执行）::

    python3 scripts/calib_precision.py --synth-demo
    python3 scripts/calib_precision.py --pairs pairs.json [--report out.md]
    python3 scripts/calib_precision.py --pairs pairs.csv --dataset D --version V

输入形制：
- ``--pairs`` JSON：``{"dataset": ..., "version": ..., "pairs":
  [[measured_cents, reference_cents], ...]}``，或裸二元组列表；
- ``--pairs`` CSV：每行两列 ``measured_cents,reference_cents``（空行与 ``#``
  注释行跳过；首行 ``measured_cents`` 表头容忍）；
- ``--synth-demo``：内置合成演示（numpy 合成，禁 scipy；固定种子 ⇒ 两次运行
  数值面逐位一致）。

输出（机器可读行，stdout；退出码 0 = 成功，1 = 输入/写盘失败）::

    CALIB_SCHEMA=1
    n=...
    mean_bias_cents=...
    dispersion_cents=...
    p95_abs_cents=...
    dataset=...
    version=...
    report_sha256=...
    report_path=...        # 仅当 --report 指定
    PASS=1

stdout 数值面**不含时间戳**（generated_at 只进 markdown 报告件的「生成时间」
单列一键），故两次运行 stdout 逐位一致。

口径：本 CLI 为「对参考真值」口径；多轨互比口径（p50/p95/bias/shared/
remainder）见 acouscope/src/acouscope/ui/widgets/multitrack/compare_present.py
:1136-1164（p50 :1147 / p95 :1148 / bias :1156 / shared :1163 / remainder
:1134/:1140）——两套读数分列，不得混称；本 CLI 不重实现多轨统计。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "acouscope" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from acouscope.analysis.calibration import (  # noqa: E402
    CALIBRATION_METADATA_KEY,
    calibrate_against_reference,
    calibration_metadata,
    surface_sha256,
    write_report,
)

#: 合成演示固定种子（确定性：两次运行数值面逐位一致）
_SYNTH_SEED = 20261023

#: 合成演示参考真值（音分，12 平均律半音栅格上的取样）
_SYNTH_REFERENCE_CENTS = (0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0)

#: 合成演示的数据集标识与版本号
_SYNTH_DATASET = "synth_demo_reference_grid_v1"
_SYNTH_VERSION = "1.0.0"


def _synth_pairs() -> list[tuple[float, float]]:
    """内置合成演示配对序列（numpy 合成，固定种子 ⇒ 逐位可复现）。"""
    import numpy as np

    rng = np.random.default_rng(_SYNTH_SEED)
    reference = np.array(_SYNTH_REFERENCE_CENTS, dtype=float)
    # 合成「测量」= 参考真值 + 确定性伪随机偏差（含正负，禁 scipy）
    bias = rng.normal(loc=0.0, scale=12.0, size=reference.size)
    measured = reference + bias
    return [
        (float(m), float(r)) for m, r in zip(measured.tolist(), reference.tolist())
    ]


def _pairs_from_json(text: str) -> tuple[list[tuple[float, float]], dict]:
    """JSON 输入 → (配对序列, 附带标识 dict)。"""
    data = json.loads(text)
    meta: dict = {}
    if isinstance(data, dict):
        meta = {
            "dataset": str(data.get("dataset", "")),
            "version": str(data.get("version", "")),
        }
        rows = data.get("pairs", [])
    else:
        rows = data
    if not isinstance(rows, (list, tuple)):
        raise ValueError("JSON pairs 须为列表")
    pairs = [(float(row[0]), float(row[1])) for row in rows]
    return pairs, meta


def _pairs_from_csv(text: str) -> list[tuple[float, float]]:
    """CSV 输入 → 配对序列（两列；空行 / ``#`` 注释行 / 表头行跳过）。"""
    pairs: list[tuple[float, float]] = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        cells = [c.strip() for c in row if c.strip() != ""]
        if not cells or cells[0].startswith("#"):
            continue
        if len(cells) < 2:
            raise ValueError("CSV 每行须两列（measured_cents,reference_cents）")
        try:
            measured = float(cells[0])
            reference = float(cells[1])
        except ValueError:
            continue  # 表头行（非数值）容忍
        pairs.append((measured, reference))
    return pairs


def _read_pairs(path: str) -> tuple[list[tuple[float, float]], dict]:
    """按扩展名读 JSON / CSV（其余按 JSON 解析），返回 (配对序列, 标识)。"""
    text = Path(path).read_text(encoding="utf-8")
    if path.lower().endswith(".csv"):
        return _pairs_from_csv(text), {}
    return _pairs_from_json(text)


def main(argv=None) -> int:
    """CLI：标定 + （可选）写报告；成功退出 0，失败退出 1。"""
    parser = argparse.ArgumentParser(
        description="精度标定（对参考真值口径）：平均偏差 / 离散度 / 95% 分位绝对误差"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synth-demo", action="store_true",
                        help="内置合成演示（numpy，固定种子）")
    source.add_argument("--pairs", metavar="PATH",
                        help="测量/参考音分序列（JSON 或 CSV）")
    parser.add_argument("--dataset", default="", help="数据集标识")
    parser.add_argument("--version", default="", help="版本号")
    parser.add_argument("--report", metavar="PATH", default="",
                        help="可选：markdown 标定报告件输出路径")
    args = parser.parse_args(argv)

    meta = {"dataset": args.dataset, "version": args.version}
    try:
        if args.synth_demo:
            pairs = _synth_pairs()
            meta = {"dataset": _SYNTH_DATASET, "version": _SYNTH_VERSION}
        else:
            pairs, file_meta = _read_pairs(args.pairs)
            meta = {
                "dataset": args.dataset or file_meta.get("dataset", ""),
                "version": args.version or file_meta.get("version", ""),
            }
        stats = calibrate_against_reference(pairs)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        print("ERROR={0}".format(exc))
        return 1

    payload = dict(meta)
    payload["stats"] = stats
    payload["report_sha256"] = surface_sha256(payload)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()

    print("CALIB_SCHEMA=1")
    for key in ("n", "mean_bias_cents", "dispersion_cents", "p95_abs_cents"):
        print("{0}={1}".format(key, stats[key]))
    print("dataset={0}".format(payload["dataset"]))
    print("version={0}".format(payload["version"]))
    print("report_sha256={0}".format(payload["report_sha256"]))

    if args.report:
        try:
            write_report(payload, args.report)
        except OSError as exc:
            print("ERROR={0}".format(exc))
            return 1
        print("report_path={0}".format(Path(args.report)))

    # metadata JSON 串（ProjectFile.metadata[CALIBRATION_METADATA_KEY] 用，
    # 不含时间戳；标定流程显式写入，未接 controller.save_project 自动绑定链）
    print("metadata_key={0}".format(CALIBRATION_METADATA_KEY))
    print("metadata={0}".format(calibration_metadata(payload)))
    print("PASS=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
