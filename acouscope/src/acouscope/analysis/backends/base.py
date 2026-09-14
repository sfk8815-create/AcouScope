# SPDX-License-Identifier: GPL-3.0-only
"""音高检测后端统一接口。

BACKEND_PROTOCOL_V1 — 定义 PitchBackend Protocol，使 pYIN、SwiftF0、RMVPE
可在业务层无缝热切换。

设计约束（用户强制指令 2026-09-04）：
- 流式 vs 离线：pYIN 为流式预览（is_streaming=True），
  SOTA 后端为离线全局分析（is_streaming=False），严禁接入实时流式管线。
- 16kHz 重采样：SOTA 后端内部负责 44.1k/48k → 16k 高质量重采样。
- 反量化铁律：输出必须为连续 Hz，禁止离散网格/ MIDI 量化。
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

import numpy as np

# 复用既有 PitchTrack（不复制定义）
from acouscope.analysis.pitch import PitchTrack, detect_pyin


@runtime_checkable
class PitchBackend(Protocol):
    """音高检测后端统一接口。"""

    name: str
    is_streaming: bool  # pYIN=True, SOTA=False

    def detect(
        self,
        signal: np.ndarray,
        sr: float,
        fmin: float = 40.0,
        fmax: float = 2000.0,
        progress_cb: "Callable[[float], None] | None" = None,
    ) -> PitchTrack:
        """检测音高，返回 PitchTrack（连续 Hz，NaN=未检出）。"""
        ...

    def is_available(self) -> bool:
        """后端是否可用（模型已加载 / 依赖已安装）。"""
        ...


class PyinBackend:
    """pYIN 后端适配器（适配既有 detect_pyin）。"""

    name = "pYIN"
    is_streaming = True

    def detect(
        self,
        signal: np.ndarray,
        sr: float,
        fmin: float = 40.0,
        fmax: float = 2000.0,
        progress_cb: "Callable[[float], None] | None" = None,
    ) -> PitchTrack:
        """调用既有 detect_pyin，不复制代码。"""
        return detect_pyin(signal, sr, fmin=fmin, fmax=fmax)

    def is_available(self) -> bool:
        """pYIN 仅依赖 numpy，始终可用。"""
        return True


BACKEND_PROTOCOL_V1 = "1"
