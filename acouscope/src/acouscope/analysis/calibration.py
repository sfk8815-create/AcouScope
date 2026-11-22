# SPDX-License-Identifier: GPL-3.0-only
"""精度标定（对参考真值口径）（B2-02 / PI-P5 批次 2）。

口径声明（两套读数分列，不得混称）：
- **本模块口径 = 「对参考真值」**：给定 (measured_cents, reference_cents)
  配对序列，输出平均偏差、离散度、95% 分位绝对误差，用于标定报告件。
- **多轨互比口径 ≠ 本口径**：仓内既有的 p50 / p95 / bias / shared / remainder
  读数属多轨互比（``ui/widgets/multitrack/compare_present.py``
  ``_diff_analysis_metrics``：1136-1164；p50 :1147 / p95 :1148 / bias :1156 /
  shared :1163 / remainder :1134/:1140）。该口径**仅作行号引用**，本模块
  **禁重实现多轨统计**；两套读数在报告与回执中分列呈现，不得互相替代或称述。
- 报告件只报误差区间，**不得写「精度已获保证」**级宣称。

确定性约束：
- ``calibrate_against_reference`` 同输入两次调用逐位一致；
- 报告 sha256 只覆盖数值面（数据集标识 + 版本号 + 四项统计量）；
- ``generated_at`` 时间戳单列一键，**不进入数值面、不进入 metadata、不参与
  一致性断言**。

纯函数、无 UI、无算法改动（不改测量取法，反量化铁律不动）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

__all__ = [
    "CALIBRATION_METADATA_KEY",
    "calibrate_against_reference",
    "calibration_metadata",
    "numeric_surface",
    "surface_sha256",
    "write_report",
]

#: ProjectFile.metadata 内的键名（值为 JSON 字符串，合 Dict[str, str] 不变式，
#: 先例见 analysis/params_snapshot.py:30 的 ANALYSIS_PARAMS_METADATA_KEY）
CALIBRATION_METADATA_KEY = "calibration_ref"

#: 统计量四键（calibrate_against_reference 的返回面，定死禁增删）
_STAT_KEYS = ("n", "mean_bias_cents", "dispersion_cents", "p95_abs_cents")

#: p95 分位（与 compare_present.py:1148 同 np.percentile 口径）
_P95 = 95


def calibrate_against_reference(pairs) -> dict:
    """对参考真值标定：由 (measured_cents, reference_cents) 序列算四项统计量。

    Args:
        pairs: ``(measured_cents, reference_cents)`` 二元组序列（list / tuple /
            生成器 / shape (n, 2) 的类数组均可）。

    Returns:
        ``{"n": int, "mean_bias_cents": float, "dispersion_cents": float,
        "p95_abs_cents": float}``
        - ``n``：配对数；
        - ``mean_bias_cents``：mean(measured - reference)（带符号，正 = 测量
          相对参考真值偏高）；
        - ``dispersion_cents``：偏差序列标准差（np.std 默认总体口径 ddof=0）；
        - ``p95_abs_cents``：|偏差| 的 95 分位（np.percentile，与
          compare_present.py:1147-1148 同函数口径）。

    空序列 ⇒ ``{"n": 0, 其余三项 None}``（不抛、不填 0——零样本无统计量）。
    纯函数：不改入参、不读全局状态、同输入两次调用逐位一致。
    """
    items = [(float(measured), float(reference)) for measured, reference in pairs]
    n = len(items)
    if n == 0:
        return {"n": 0, "mean_bias_cents": None, "dispersion_cents": None,
                "p95_abs_cents": None}
    bias = np.array([m - r for m, r in items], dtype=float)
    return {
        "n": int(n),
        "mean_bias_cents": float(np.mean(bias)),
        "dispersion_cents": float(np.std(bias)),
        "p95_abs_cents": float(np.percentile(np.abs(bias), _P95)),
    }


def numeric_surface(payload: dict) -> dict:
    """数值面（参与 sha256 与一致性断言的部分）：数据集标识 + 版本号 + 统计量。

    ``generated_at`` 及其它非数值键一律不在数值面内——报告时间戳单列一键，
    不参与任何一致性断言。纯函数，键序由下游 sort_keys 固定。
    """
    stats = payload.get("stats") or {}
    return {
        "dataset": str(payload.get("dataset", "")),
        "version": str(payload.get("version", "")),
        "stats": {key: stats.get(key) for key in _STAT_KEYS},
    }


def surface_sha256(payload: dict) -> str:
    """数值面 sha256（确定性：键排序 + UTF-8 + 无时间戳）。"""
    canonical = json.dumps(
        numeric_surface(payload), sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calibration_metadata(payload: dict) -> str:
    """payload → ``ProjectFile.metadata[CALIBRATION_METADATA_KEY]`` 用的 JSON 字符串。

    内容：数据集标识、版本号、报告 sha256，以及四项统计量（**显式逐键构造，
    非 payload 透传** ⇒ 时间戳类键天然排除）；**不含生成时间**（时间戳不参与
    一致性断言，入 metadata 会让同一标定结果因落盘时刻不同而不可比）。

    返回值合 ``Dict[str, str]`` 不变式（先例：params_snapshot.py:48-51）。
    写入方式（标定流程显式写入，未接 controller.save_project 自动绑定链）::

        project_file.metadata[CALIBRATION_METADATA_KEY] = (
            calibration_metadata(payload)
        )
    """
    stats = payload.get("stats") or {}
    ref: dict = {
        "dataset": str(payload.get("dataset", "")),
        "version": str(payload.get("version", "")),
        "report_sha256": str(payload.get("report_sha256", "")),
    }
    for key in _STAT_KEYS:
        ref[key] = stats.get(key)
    return json.dumps(
        {CALIBRATION_METADATA_KEY: ref}, ensure_ascii=False, sort_keys=True
    )


def write_report(payload: dict, path) -> None:
    """写 markdown 标定报告件（数值面 + 数据集版本 + 报告 sha256）。

    - 报告 sha256 由 ``surface_sha256`` 现算（覆盖数值面，与文件内数值行同源）；
    - ``generated_at`` 时间戳**单列一键**（「生成时间」小节），不进入数值面、
      不进入 sha256——两次标定（同时刻同数据）除该行外逐位一致；
    - 报告只述误差区间，不作「精度已获保证」级宣称。

    纯写盘：不改 payload、不读全局状态。``path`` 为 str / Path。
    """
    stats = payload.get("stats") or {}
    surface = numeric_surface(payload)
    lines = [
        "# 精度标定报告（对参考真值口径）",
        "",
        "## 数据集与版本",
        "",
        "- dataset：{0}".format(surface["dataset"]),
        "- version：{0}".format(surface["version"]),
        "",
        "## 数值面",
        "",
        "- n：{0}".format(stats.get("n")),
        "- mean_bias_cents：{0}".format(stats.get("mean_bias_cents")),
        "- dispersion_cents：{0}".format(stats.get("dispersion_cents")),
        "- p95_abs_cents：{0}".format(stats.get("p95_abs_cents")),
        "- report_sha256：{0}".format(surface_sha256(payload)),
        "",
        "## 生成时间",
        "",
        "- generated_at：{0}".format(payload.get("generated_at", "")),
        "",
        "## 口径说明",
        "",
        "- 本口径为「对参考真值」：measured_cents 相对 reference_cents 的偏差"
        "分布（平均偏差 / 离散度 / 95% 分位绝对误差）。",
        "- 多轨互比口径（p50 / p95 / bias / shared / remainder）见 "
        "ui/widgets/multitrack/compare_present.py:1136-1164"
        "（p50 :1147 / p95 :1148 / bias :1156 / shared :1163 / remainder "
        ":1134/:1140）；两套读数分列，不得混称，本模块不重实现多轨统计。",
        "- 本报告只述误差区间，不作精度保证级宣称。",
        "",
    ]
    target = Path(path)
    if target.parent and str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
