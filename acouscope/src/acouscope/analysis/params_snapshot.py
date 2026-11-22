# SPDX-License-Identifier: GPL-3.0-only
"""分析参数快照（B1-03 / R9）：采集本次分析所用参数面，供项目文件绑定与复算复现。

口径：
- 只做「参数快照 + 绑定」，不做结果版本化 diff；
- 参考频率一律走 dsp.units 全局单源读取（本模块不写死任何参考值）；
- 快照为纯数据 dict（JSON 可序列化），经 params_snapshot_to_metadata 以
  JSON 字符串写入 ProjectFile.metadata（Dict[str, str] 不变式）。
"""

from __future__ import annotations

import json
from dataclasses import asdict

import acouscope

from ..dsp.reference_status import get_reference_status
from ..dsp.units import get_reference_hz
from .note_hmm import NOTE_HMM_PARAMS
from .pcp import PCPParams
from .pyin import PYIN_MARKER

__all__ = [
    "ANALYSIS_PARAMS_METADATA_KEY",
    "analysis_params_snapshot",
    "params_snapshot_to_metadata",
]

#: 项目文件 files[i].metadata 内的键名（值为 JSON 字符串，合 Dict[str, str] 不变式）
ANALYSIS_PARAMS_METADATA_KEY = "analysis_params"


def analysis_params_snapshot() -> dict:
    """采集当前分析参数面（纯数据，JSON 可序列化）。

    采集项：A4 参考频率与**其来源语义**（全局单源实读，见
    :func:`dsp.units.get_reference_status`）／note_hmm 参数表（逐字拷贝）／
    pYIN clean-room 标记 / PCP 分箱参数 / 平台版本。
    """
    ref = get_reference_status()
    return {
        "a4_reference_hz": float(get_reference_hz()),
        "a4_reference_status": ref["reference_status"],
        "a4_reference_source": ref["source"],
        "note_hmm_params": dict(NOTE_HMM_PARAMS),
        "pyin_marker": PYIN_MARKER,
        "pcp_params": asdict(PCPParams()),
        "version": acouscope.__version__,
    }


def params_snapshot_to_metadata(snapshot: dict | None = None) -> str:
    """快照 → ProjectFile.metadata 值（JSON 字符串；键排序保证确定性）。"""
    snap = analysis_params_snapshot() if snapshot is None else snapshot
    return json.dumps(snap, ensure_ascii=False, sort_keys=True)
