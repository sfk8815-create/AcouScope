# SPDX-License-Identifier: GPL-3.0-only
"""音律标尺叠加层（T-922）：把音律模板的音级换算为可绘制的刻度线。

纯数据层，不做任何绘制：
- 只读消费 :class:`~acouscope.analysis.tunings.tuning_system.TuningSystem`；
- 参考频率缺省取 :func:`acouscope.dsp.units.get_reference_hz`（与音分/音名显示同一口径）；
- 空/未知音律一律返回空列表，绝不抛异常。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...dsp.units import get_reference_hz

__all__ = ["OverlayLine", "build_overlay_lines"]


@dataclass(frozen=True)
class OverlayLine:
    """一条音律刻度线：音级 → 音分（相对 1/1）与频率（按参考频率换算）。"""

    cents: float
    freq_hz: float
    degree: int
    label: str = ""

    def __post_init__(self) -> None:
        # 默认标签为音级序（谱名映射留给后续任务）
        if not self.label:
            object.__setattr__(self, "label", str(self.degree))


def build_overlay_lines(
    tuning,
    *,
    ref_hz: float | None = None,
    min_hz: float | None = None,
    max_hz: float | None = None,
) -> list[OverlayLine]:
    """按音律模板生成叠加刻度线。

    口径：
    - 逐级取 ``tuning.degrees``（含隐含 1/1 = 0.0 音分），频率复用 ``degree_to_freq``（只读）；
    - 等八度音律（末音级为 2/1）不重复输出边界八度线：12TET → 12 条、22 shruti → 22 条；
      非等八度音律不假设 2/1 折叠，按声明音级全量输出（沿用 TuningSystem 既有外推语义）；
    - ``ref_hz`` 缺省取 ``dsp.units.get_reference_hz()``；
    - ``min_hz``/``max_hz`` 为闭区间裁剪（None = 不限）；
    - 空/未知 tuning、非法参考频率 → 返回空列表，绝不抛异常。
    """
    if tuning is None:
        return []
    degrees = getattr(tuning, "degrees", None)
    degree_to_freq = getattr(tuning, "degree_to_freq", None)
    if not degrees or not callable(degree_to_freq):
        return []  # 未知/空音律：静默返回空

    reference = get_reference_hz() if ref_hz is None else ref_hz
    try:
        reference = float(reference)
    except (TypeError, ValueError):
        return []
    if not math.isfinite(reference) or reference <= 0.0:
        return []

    try:
        count = len(degrees)
        if getattr(tuning, "is_octave_repeating", False):
            count -= 1  # 末音级为重复的 2/1 边界：不重复输出
        lines: list[OverlayLine] = []
        for degree in range(count):
            freq_hz = float(degree_to_freq(degree, ref=reference))
            if not math.isfinite(freq_hz) or freq_hz <= 0.0:
                continue
            if min_hz is not None and freq_hz < float(min_hz):
                continue
            if max_hz is not None and freq_hz > float(max_hz):
                continue
            lines.append(
                OverlayLine(
                    cents=float(tuning.degree_to_cents(degree)),
                    freq_hz=freq_hz,
                    degree=degree,
                )
            )
    except Exception:
        return []  # 任何异常口径（未知 tuning/坏 degrees）→ 空列表，绝不外抛
    return lines
