# SPDX-License-Identifier: GPL-3.0-only
"""底轴刻度密度自适应（G4a-3）：字体度量驱动的刻度档选择。

背景（FORENSICS_20261018_g4a3_axis.md §1.2）：``nice_ticks`` 的 ``min_label_px``
单一像素口径过大（90）时，8 s 数据在窄画布上只剩 1 个主标签——底轴「有刻度线
无数字」的真因。本模块不改 nice_ticks 语义，在其外层按字体度量选档：

- 候选 ``[12, 16, 20, 24, 30, 36, 44, 60, 90]`` 从密到疏逐档试算 ``nice_ticks``；
- 用 ``QFontMetrics.horizontalAdvance(fmt(v))`` 实测该档全部主标签的像素宽；
- 取**首个**满足「任意相邻主标签像素间距 ≥ 最宽主标签宽 + gap_px」的档；
- 全不满足 → 退最疏档（90 仅作末档兜底，不在默认路径上）；
- ``fm is None`` → 回退 ``nice_ticks(min_label_px=22)``（Audacity 原默认，
  纯函数可单测，不依赖 Qt）。

用法（time_axis.refresh_ticks 调用）::

    fm = QFontMetrics(self.font())
    ts = best_tickset(x0, x1, pixel_width, fm, format_seconds)

``t0 >= t1`` 或 ``pixel_width <= 0`` 返回空刻度集（与 nice_ticks 边界一致）。
相邻标签数 < 2 时无重叠可能，视为满足（直接返回该档）。
"""

from __future__ import annotations

from acouscope.ui.widgets.time_axis import TickSet, format_seconds, nice_ticks

# 候选 min_label_px 档：从密到疏。90 仅作末档兜底（A4 全不满足时退此档）。
CANDIDATE_MIN_LABEL_PX = (12, 16, 20, 24, 30, 36, 44, 60, 90)

# fm=None 回退档（Audacity Ruler 默认 22）
FALLBACK_MIN_LABEL_PX = 22.0

# 默认标签间隙（px）：相邻主标签间距 ≥ 最宽标签 + gap_px
DEFAULT_GAP_PX = 8


def _fits(ts: TickSet, t0: float, t1: float, pixel_width: float, fm, fmt, gap_px: float) -> bool:
    """该档是否满足「相邻主标签像素间距 ≥ 最宽标签 + gap_px」。

    相邻主标签数 < 2（0 或 1 个标签）时无重叠可能，恒视为满足。
    """
    majors = ts.majors
    if len(majors) < 2:
        return True
    span = float(t1) - float(t0)
    if span <= 0:
        return False
    px_per_sec = float(pixel_width) / span
    max_w = 0
    for v in majors:
        w = int(fm.horizontalAdvance(fmt(float(v))))
        if w > max_w:
            max_w = w
    need = max_w + float(gap_px)
    for a, b in zip(majors, majors[1:]):
        if (float(b) - float(a)) * px_per_sec < need:
            return False
    return True


def best_tickset(t0: float, t1: float, pixel_width: float, fm, fmt, gap_px: float = DEFAULT_GAP_PX) -> TickSet:
    """按字体度量自适应选择底轴刻度档（G4a-3 核心，纯函数 + 鸭子类型 fm）。

    Args:
        t0, t1: 时间范围（秒；t0 >= t1 返回空刻度集）。
        pixel_width: 标尺像素宽（<= 0 返回空刻度集）。
        fm: 字体度量对象，需提供 ``horizontalAdvance(str) -> int``；
            ``None`` 时回退 ``nice_ticks(min_label_px=22)``。
        fmt: 标签格式化函数（统一传 ``format_seconds``）。
        gap_px: 相邻标签允许的最小额外间隙（默认 8）。

    Returns:
        TickSet：首个满足间距约束的候选档；全不满足退最疏档（90）。
    """
    if t0 >= t1 or pixel_width <= 0:
        return TickSet([], [], 0.0, 0.0, 0)
    if fm is None:
        return nice_ticks(t0, t1, pixel_width, min_label_px=FALLBACK_MIN_LABEL_PX)
    chosen = None
    for cand in CANDIDATE_MIN_LABEL_PX:
        ts = nice_ticks(t0, t1, pixel_width, min_label_px=float(cand))
        chosen = ts
        if _fits(ts, t0, t1, pixel_width, fm, fmt, gap_px):
            return ts
    return chosen  # 全不满足 → 最疏档兜底


__all__ = [
    "CANDIDATE_MIN_LABEL_PX",
    "DEFAULT_GAP_PX",
    "FALLBACK_MIN_LABEL_PX",
    "best_tickset",
]
