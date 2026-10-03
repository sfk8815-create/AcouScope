# SPDX-License-Identifier: GPL-3.0-only
"""音律模型 TuningSystem（T-918，音律标尺链基座）。

以 Ellis 音分（cent，Huygens-Fokker 基准）为主计量，承载一个音律的音级序列，
并提供 音级↔音分↔频率 换算；后续任务（T-919+：PCP / 调式推断 / A4 校准 /
音律标尺叠加层 / 工尺谱谱名）复用本模型。

口径约定：
- ``degrees``：**含隐含 1/1（0.0 音分）在内的完整升序音分序列**，即
  ``degrees[0] == 0.0``，``degrees[k]`` 为第 k 音级相对 1/1 的音分；
  等八度音律（.scl 末值 2/1）时 ``degrees[-1] == 1200.0``。
- ``degree_count``：音级数＝``len(degrees) - 1``，与 .scl 文件的“音数 N”一致
  （1/1 是隐含的 0 度，不在文件内）。
- ``reference_freq``：1/1 对应的频率（默认 A4=440.0 的分工见需求说明；本任务只固定
  该字段并允许构造时指定，A4 注入链路由 T-919+ 承担）。
- 频率换算复用 ``dsp/units.py`` 的 ``cents_to_hz`` / ``hz_to_cents``（只读引用）。
- 超出 0..degree_count 的音级按八度（1200 音分）折叠外推——对末值为 2/1 的音律
  等价，对非等八度 .scl 属外推近似（文件本身仍按原样承载）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from ...dsp.units import A4_FREQ, cents_to_hz, hz_to_cents

__all__ = ["TuningSystem"]

OCTAVE_CENTS = 1200.0


@dataclass(frozen=True)
class TuningSystem:
    """一个音律（音阶）的音级序列与其换算能力。"""

    name: str
    source: str
    degrees: tuple[float, ...]
    reference_freq: float = field(default=float(A4_FREQ))

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TuningSystem.name 不可为空")
        if not self.source:
            raise ValueError("TuningSystem.source 不可为空（学术诚信：音律来源须标注）")
        if not self.degrees:
            raise ValueError("TuningSystem.degrees 不可为空（至少含隐含 1/1 的 0.0 音分）")
        degrees = tuple(float(value) for value in self.degrees)
        if not math.isfinite(degrees[0]) or abs(degrees[0]) > 1e-9:
            raise ValueError("TuningSystem.degrees[0] 必须是隐含 1/1 的 0.0 音分")
        for value in degrees:
            if not math.isfinite(value):
                raise ValueError("TuningSystem.degrees 含非有限值")
        if not math.isfinite(float(self.reference_freq)) or float(self.reference_freq) <= 0:
            raise ValueError("TuningSystem.reference_freq 必须是正有限值")
        object.__setattr__(self, "degrees", degrees)
        object.__setattr__(self, "reference_freq", float(self.reference_freq))

    @property
    def degree_count(self) -> int:
        """音级数（不含隐含 1/1；等价 .scl 文件声明的音数 N）。"""
        return len(self.degrees) - 1

    @property
    def is_octave_repeating(self) -> bool:
        """末音级是否为八度（等八度音律）。"""
        return self.degree_count > 0 and abs(self.degrees[-1] - OCTAVE_CENTS) < 1e-6

    def degree_to_cents(self, degree: int) -> float:
        """音级 → 相对 1/1 的音分（超界按八度折叠外推）。"""
        if not isinstance(degree, int) or isinstance(degree, bool):
            raise TypeError("degree 需为 int")
        count = self.degree_count
        if count == 0:
            return OCTAVE_CENTS * degree
        if 0 <= degree <= count:
            return self.degrees[degree]
        octave, index = divmod(degree - 1, count)
        return self.degrees[index + 1] + OCTAVE_CENTS * octave

    def degree_to_freq(self, degree: int, ref: float | None = None) -> float:
        """音级 → 频率（Hz）；ref 省略时用本音律的 reference_freq。"""
        reference = self.reference_freq if ref is None else float(ref)
        return float(cents_to_hz(self.degree_to_cents(degree), ref_freq=reference))

    def cents_to_degree(self, cents: float) -> int:
        """音分 → 最近音级（就近取整；超界按八度折叠后仍取最近）。"""
        target = float(cents)
        if not math.isfinite(target):
            raise ValueError("cents 需为有限值")
        count = self.degree_count
        if count == 0:
            return int(round(target / OCTAVE_CENTS))
        octave = math.floor(target / OCTAVE_CENTS)
        best_degree = 0
        best_diff = math.inf
        for candidate_octave in (octave - 1, octave, octave + 1):
            for index in range(count + 1):
                degree = candidate_octave * count + index
                diff = abs(self.degree_to_cents(degree) - target)
                if diff < best_diff - 1e-12:
                    best_diff = diff
                    best_degree = degree
        return best_degree

    def freq_to_degree(self, freq_hz: float, ref: float | None = None) -> int:
        """频率（Hz）→ 最近音级（先按参考频率换成音分再就近）。"""
        reference = self.reference_freq if ref is None else float(ref)
        return self.cents_to_degree(float(hz_to_cents(float(freq_hz), ref_freq=reference)))

    @classmethod
    def from_cents(
        cls,
        name: str,
        source: str,
        cents: tuple[float, ...] | list[float],
        reference_freq: float = float(A4_FREQ),
    ) -> "TuningSystem":
        """由音分序列构造（输入为 .scl 口径的 N 个音级，隐含 1/1 自动补入）。"""
        return cls(
            name=name,
            source=source,
            degrees=(0.0, *[float(value) for value in cents]),
            reference_freq=reference_freq,
        )

    @classmethod
    def from_ratios(
        cls,
        name: str,
        source: str,
        ratios: tuple[Fraction | int | str, ...] | list[Fraction | int | str],
        reference_freq: float = float(A4_FREQ),
    ) -> "TuningSystem":
        """由比值序列构造（比值 → 音分 = 1200*log2(n/d)，Fraction 精确承载）。"""
        cents: list[float] = []
        for item in ratios:
            ratio = item if isinstance(item, Fraction) else Fraction(str(item))
            if ratio <= 0:
                raise ValueError(f"比值须为正：{item!r}")
            cents.append(OCTAVE_CENTS * math.log2(ratio.numerator / ratio.denominator))
        return cls.from_cents(name, source, cents, reference_freq=reference_freq)

    @classmethod
    def from_scl(
        cls,
        text: str,
        *,
        source: str,
        name: str | None = None,
        reference_freq: float = float(A4_FREQ),
    ) -> "TuningSystem":
        """由 .scl 文本构造（解析规则见 :mod:`acouscope.analysis.tunings.scl`）。

        ``source`` 为必填关键字参数：音律来源须标注（学术诚信口径），且来源表述
        描述“何处记载/何文献”，不表述为“符合/覆盖某项标准”。
        """
        from .scl import parse_scl

        scale = parse_scl(text)
        return cls.from_cents(
            name=name or scale.description or "untitled",
            source=source,
            cents=list(scale.cents()),
            reference_freq=reference_freq,
        )
