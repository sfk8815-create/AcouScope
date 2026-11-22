# SPDX-License-Identifier: GPL-3.0-only
"""律制模板根音（1/1 所对频率）的显式参数化（2026-11-22 · 根音 P1，数据层）。

背景：内置律制模板的 ``reference_freq``（1/1 所对频率）一律取 ``A4_FREQ``（440 Hz），
即「以 A 为宫」。比较不同律制下的音级归属时，根音是与律制模板并列的参照条件：
同一批实测音高，换根音即换归属。本模块把根音做成**分析者显式给定、可记录**的参数，
默认值与现行为逐位一致（``a4``），不改动任何内置模板。

三种取法（``mode``）：

- ``"a4"``（默认）：1/1 = A4（``a4_hz``，缺省 ``A4_FREQ``）——现行为；
- ``"tonic"``：1/1 = 指定音名 + 校准偏移（音分），音名按十二平均律相对 A4 定位，
  落在 A4 所在八度内（C4…B4）；八度位置只影响音级序号的整体平移，不影响音级类；
- ``"hz"``：1/1 = 指定频率（Hz）。

本模块零 Qt 依赖；不修改入参 TuningSystem（``dataclasses.replace`` 返回新对象）。
"""

from __future__ import annotations

import dataclasses
import math

from ...dsp.units import A4_FREQ, NOTE_NAMES
from .tuning_system import TuningSystem

__all__ = [
    "ROOT_A4",
    "ROOT_HZ",
    "ROOT_MODES",
    "ROOT_TONIC",
    "root_hz",
    "root_record",
    "with_root",
]

ROOT_A4 = "a4"
ROOT_TONIC = "tonic"
ROOT_HZ = "hz"
ROOT_MODES = (ROOT_A4, ROOT_TONIC, ROOT_HZ)

_A_INDEX = 9  # NOTE_NAMES 中 "A" 的位置


def _finite(value, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} 须为有限数：{value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{what} 须为有限数：{value!r}")
    return number


def root_hz(
    mode: str = ROOT_A4,
    *,
    tonic: str | None = None,
    anchor_cents: float | None = None,
    hz: float | None = None,
    a4_hz: float | None = None,
) -> float:
    """按取法返回 1/1 所对频率（Hz）。

    - ``a4``：返回 ``a4_hz``（缺省 ``A4_FREQ``）；
    - ``tonic``：``a4 * 2 ** (((NOTE_NAMES.index(tonic) - 9) * 100 + anchor_cents) / 1200)``，
      ``anchor_cents`` 缺省 0.0；
    - ``hz``：返回 ``hz``（须为正有限数）。
    """
    a4 = float(A4_FREQ) if a4_hz is None else _finite(a4_hz, "a4_hz")
    if a4 <= 0.0:
        raise ValueError(f"a4_hz 须为正：{a4_hz!r}")
    if mode == ROOT_A4:
        return a4
    if mode == ROOT_TONIC:
        if tonic not in NOTE_NAMES:
            raise ValueError(f"tonic 须为 {NOTE_NAMES} 之一：{tonic!r}")
        offset = 0.0 if anchor_cents is None else _finite(anchor_cents, "anchor_cents")
        semis = NOTE_NAMES.index(tonic) - _A_INDEX
        return a4 * 2.0 ** ((semis * 100.0 + offset) / 1200.0)
    if mode == ROOT_HZ:
        if hz is None:
            raise ValueError("mode='hz' 须给出 hz")
        value = _finite(hz, "hz")
        if value <= 0.0:
            raise ValueError(f"hz 须为正：{hz!r}")
        return value
    raise ValueError(f"未知根音取法：{mode!r}（可用：{ROOT_MODES}）")


def with_root(tuning: TuningSystem, root: float) -> TuningSystem:
    """返回 1/1 改为 ``root`` Hz 的新模板；音级序列、名称、来源逐字不变。"""
    if not isinstance(tuning, TuningSystem):
        raise TypeError("tuning 须为 TuningSystem")
    value = _finite(root, "root")
    if value <= 0.0:
        raise ValueError(f"root 须为正：{root!r}")
    return dataclasses.replace(tuning, reference_freq=value)


def root_record(
    mode: str = ROOT_A4,
    *,
    tonic: str | None = None,
    anchor_cents: float | None = None,
    hz: float | None = None,
    a4_hz: float | None = None,
) -> dict:
    """运行记录用的根音条目（键固定，供写入 run_config / 图注）。"""
    value = root_hz(mode, tonic=tonic, anchor_cents=anchor_cents, hz=hz, a4_hz=a4_hz)
    if mode == ROOT_A4:
        label = "A4"
    elif mode == ROOT_TONIC:
        offset = 0.0 if anchor_cents is None else float(anchor_cents)
        label = f"{tonic}{offset:+.2f}c"
    else:
        label = f"{value:.3f}Hz"
    return {
        "root_mode": mode,
        "root_tonic": tonic if mode == ROOT_TONIC else None,
        "root_anchor_cents": (
            (0.0 if anchor_cents is None else float(anchor_cents)) if mode == ROOT_TONIC else None
        ),
        "root_hz": value,
        "root_label": label,
    }
