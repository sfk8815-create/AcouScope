# SPDX-License-Identifier: GPL-3.0-only
"""音频标注模块（借鉴 Sonic Visualiser 的层概念）。

提供时间点（instant）和时间段（region）两种标注类型，
以及统一的标注数据模型，可在波形/语谱图/频谱等多个视图间共享。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# 预置调色板（用于区域颜色）
REGION_PALETTE = [
    "#ef4444",  # red
    "#f97316",  # orange
    "#eab308",  # yellow
    "#22c55e",  # green
    "#06b6d4",  # cyan
    "#3b82f6",  # blue
    "#8b5cf6",  # violet
    "#ec4899",  # pink
]


@dataclass
class TimeInstant:
    """时间点标注（对应 Sonic Visualiser 的 Instant Layer）。

    用于标记 onset、节拍、事件发生时刻等。
    """
    time: float          # 时间（秒）
    label: str = ""      # 文字标签
    color: str = "#ef4444"
    show_label: bool = True

    def __post_init__(self):
        if self.time < 0:
            self.time = 0.0


@dataclass
class TimeRegion:
    """时间段标注（对应 Sonic Visualiser 的 Region Layer）。

    用于标记乐段、音符、感兴趣区间等，支持循环播放。
    """
    start_time: float    # 起始时间（秒）
    end_time: float      # 结束时间（秒）
    label: str = ""      # 文字标签
    color: str = "#3b82f6"
    show_label: bool = True

    def __post_init__(self):
        if self.start_time < 0:
            self.start_time = 0.0
        if self.end_time < self.start_time:
            self.end_time = self.start_time + 0.01

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def contains(self, t: float) -> bool:
        return self.start_time <= t <= self.end_time


class AnnotationModel:
    """标注数据模型。

    管理所有时间点和时间段标注，支持增删改查。
    多个视图（波形、语谱图等）可以共享同一个模型，
    修改后各自重绘即可。
    """

    def __init__(self):
        self._instants: list[TimeInstant] = []
        self._regions: list[TimeRegion] = []
        self._next_region_color_idx = 0
        self._pitches: list["PitchAnnotation"] = []  # FIELD_PITCH_V1
        # T-322: 变更监听（项目自动保存脏标记统一入口；无监听时零开销）
        self._listeners: list = []

    # ------ 变更监听（T-322）------

    def add_listener(self, fn) -> None:
        """注册变更回调（任一增删改后触发，fn() 无参）。"""
        if fn not in self._listeners:
            self._listeners.append(fn)

    def _changed(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # ------ 时间点 ------

    @property
    def instants(self) -> list[TimeInstant]:
        return list(self._instants)

    def add_instant(self, time: float, label: str = "",
                    color: Optional[str] = None) -> TimeInstant:
        inst = TimeInstant(
            time=time,
            label=label,
            color=color or REGION_PALETTE[len(self._instants) % len(REGION_PALETTE)],
        )
        self._instants.append(inst)
        self._instants.sort(key=lambda x: x.time)
        self._changed()  # T-322
        return inst

    def remove_instant(self, instant: TimeInstant):
        if instant in self._instants:
            self._instants.remove(instant)
            self._changed()  # T-322

    def clear_instants(self):
        if self._instants:
            self._instants.clear()
            self._changed()  # T-322

    def find_instant_near(self, t: float, tolerance: float = 0.02) -> Optional[TimeInstant]:
        """找到指定时间附近最近的时间点。"""
        best = None
        best_dist = float("inf")
        for inst in self._instants:
            dist = abs(inst.time - t)
            if dist < tolerance and dist < best_dist:
                best = inst
                best_dist = dist
        return best

    # ------ 时间段 ------

    @property
    def regions(self) -> list[TimeRegion]:
        return list(self._regions)

    def add_region(self, start: float, end: float, label: str = "",
                   color: Optional[str] = None) -> TimeRegion:
        if color is None:
            color = REGION_PALETTE[self._next_region_color_idx % len(REGION_PALETTE)]
            self._next_region_color_idx += 1
        region = TimeRegion(
            start_time=min(start, end),
            end_time=max(start, end),
            label=label,
            color=color,
        )
        self._regions.append(region)
        self._regions.sort(key=lambda x: x.start_time)
        self._changed()  # T-322
        return region

    def remove_region(self, region: TimeRegion):
        if region in self._regions:
            self._regions.remove(region)
            self._changed()  # T-322

    def clear_regions(self):
        if self._regions:
            self._regions.clear()
            self._changed()  # T-322

    def find_region_at(self, t: float) -> Optional[TimeRegion]:
        """找到包含指定时间的区域（最内层优先）。"""
        for region in reversed(self._regions):
            if region.contains(t):
                return region
        return None

    def find_region_near(self, t: float, tolerance: float = 0.02) -> Optional[TimeRegion]:
        """找到边界附近的区域（用于拖拽调整边界）。"""
        best = None
        best_dist = float("inf")
        for region in self._regions:
            for edge in (region.start_time, region.end_time):
                dist = abs(edge - t)
                if dist < tolerance and dist < best_dist:
                    best = region
                    best_dist = dist
        return best

    # ------ 音高标注（FIELD_PITCH_V1，毫秒时间戳，绑定 Session）------

    @property
    def pitches(self) -> list["PitchAnnotation"]:
        return list(self._pitches)

    def add_pitch(
        self,
        t_ms: int,
        f0_hz: float,
        cent_ref: float = 440.0,
        confidence: float = 1.0,
        label: str = "",
        session_id: str = "",
        note: str = "",
    ) -> "PitchAnnotation":
        """新增音高标注；cents 相对 cent_ref 自动计算（1200*log2(f0/ref)）。"""
        from math import log2

        ann = PitchAnnotation(
            t_ms=int(t_ms),
            f0_hz=float(f0_hz),
            cents=1200.0 * log2(float(f0_hz) / float(cent_ref)),
            cent_ref=float(cent_ref),
            confidence=float(confidence),
            label=label,
            session_id=session_id,
            note=note,
        )
        self._pitches.append(ann)
        self._pitches.sort(key=lambda x: x.t_ms)
        self._changed()  # T-322
        return ann

    def remove_pitch(self, ann: "PitchAnnotation"):
        if ann in self._pitches:
            self._pitches.remove(ann)
            self._changed()  # T-322

    def clear_pitches(self):
        if self._pitches:
            self._pitches.clear()
            self._changed()  # T-322


@dataclass
class PitchAnnotation:
    """音高标注（FIELD_PITCH_V1）。

    t_ms 用整数毫秒存储保证时间戳精度；cents 相对 cent_ref；
    session_id 绑定田野元数据 Session（IASA-TC 04 / IMDI，见 metadata.py）。
    """

    t_ms: int            # 时间戳（毫秒，整数）
    f0_hz: float         # 基频 Hz
    cents: float = 0.0   # 相对 cent_ref 音分
    cent_ref: float = 440.0
    confidence: float = 1.0  # 置信度 [0,1]（pYIN voiced 概率）
    label: str = ""
    session_id: str = ""
    note: str = ""       # 田野笔记
