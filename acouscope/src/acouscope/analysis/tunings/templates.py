# SPDX-License-Identifier: GPL-3.0-only
"""内置音律模板与 .scl 文件加载（T-918，音律标尺链基座）。

首期只提供**少量代表性模板**，每个模板的 ``source`` 标注学术出处（R8：
``.pi/knowledge/RESEARCH_JOURNAL.md`` R8 条，音律格式与各传统音律来源），
来源表述描述“何处记载”，不作“符合/覆盖某项标准”的表述。

不内置下载 Huygens-Fokker 的 4000+ 音阶库（首期＝读任意 .scl + 少量代表模板；
库的下载/管理留后续注记）。.kbm 键盘映射不在本任务范围。
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from ...dsp.units import A4_FREQ
from .tuning_system import OCTAVE_CENTS, TuningSystem

__all__ = [
    "TEMPLATE_KEYS",
    "TEMPLATES",
    "get_template",
    "list_templates",
    "load_scl",
]

_SOURCE_ELLIS = (
    "音分基准：Ellis cent（Huygens-Fokker 度量说明，R8 C 项，"
    "https://www.huygens-fokker.org/docs/measures.html）"
)
_SOURCE_SCALA_LIB = (
    "Huygens-Fokker 基金会 Scala 音阶库（.scl 格式与 4000+ 音阶库，R8 A 项，"
    "https://www.huygens-fokker.org/scala/）"
)
_SOURCE_CHINESE_LUXUE = (
    "中国律学文献（R8 B 项：中国律学综述 euro-acad.eu；UChicago「From Ut Re Mi to "
    "Fourteen-Tone Temperament」；UNT「Lu-Pitch Name Signification」「Perspectives of "
    "Chinese Music」所述传统三分损益/十二律）"
)
_SOURCE_SHRUTI = (
    "印度 22 shruti 概念：Classical Indian Tuning System（R8 B 项，"
    "https://plainsound.org/pdfs/srutis.pdf）；该文献所述 shruti 为不等程音级集合，"
    "本模板写明为 1200/22 等程采样参考值，非文献实测音分值"
)
_SOURCE_MAQAM = (
    "阿拉伯 maqam：The Eastern Modal (Maqam) System and Unequal Temperament / "
    "Arabic maqâmât 与等程比较（R8 B 项，dergipark）；文献强调 maqam 为不等程，"
    "本模板写明为 1200/24 等程采样参考值，非文献实测音分值"
)

# 官方 .scl 格式说明页给出的合法文件样例（原样内联，逐字符取自
# https://www.huygens-fokker.org/scala/scl_format.html 的 example 区块）。
_MEANQUAR_SCL_TEXT = """! meanquar.scl
!
1/4-comma meantone scale. Pietro Aaron's temperament (1523)
 12
!
 76.04900
 193.15686
 310.26471
 5/4
 503.42157
 579.47057
 696.57843
 25/16
 889.73529
 1006.84314
 1082.89214
 2/1
"""


def _fifth_chain_ratios(exponents: tuple[int, ...]) -> list[Fraction]:
    """3/2 相生链：按给定相生次数取 3-limit 比值并折入八度（Fraction 精确）。"""
    ratios: list[Fraction] = []
    for exponent in exponents:
        ratio = Fraction(3, 2) ** exponent
        while ratio >= 2:
            ratio /= 2
        while ratio < 1:
            ratio *= 2
        ratios.append(ratio)
    return ratios


def _sorted_by_cents(ratios: list[Fraction]) -> list[Fraction]:
    return sorted(ratios, key=lambda item: item.numerator / item.denominator)


def _equal_division_cents(steps: int) -> list[float]:
    return [OCTAVE_CENTS * index / steps for index in range(1, steps + 1)]


def _build_twelve_tet() -> TuningSystem:
    return TuningSystem.from_cents(
        name="十二平均律（12-tone equal temperament）",
        source=f"等程十二音为 1200/12 的数学定义；{_SOURCE_ELLIS}",
        cents=_equal_division_cents(12),
    )


def _build_just_major() -> TuningSystem:
    return TuningSystem.from_ratios(
        name="纯律大调（5-limit just intonation major）",
        source=f"{_SOURCE_SCALA_LIB}（just intonation 条目）；{_SOURCE_ELLIS}",
        ratios=["9/8", "5/4", "4/3", "3/2", "5/3", "15/8", "2/1"],
    )


def _build_pythagorean_diatonic() -> TuningSystem:
    ratios = _sorted_by_cents(_fifth_chain_ratios((2, 4, -1, 1, 3, 5)))
    ratios.append(Fraction(2, 1))
    return TuningSystem.from_ratios(
        name="五度相生七音（3/2 相生链自然七声）",
        source=f"3/2 相生链（五度相生）为文献记载律法；{_SOURCE_CHINESE_LUXUE}；{_SOURCE_SCALA_LIB}",
        ratios=ratios,
    )


def _build_quarter_comma_meantone() -> TuningSystem:
    return TuningSystem.from_scl(
        _MEANQUAR_SCL_TEXT,
        source=(
            "Huygens-Fokker Scala 音阶库 meanquar.scl（1/4-comma meantone，"
            "Pietro Aaron 1523；R8 B 项收录，样例亦见官方 .scl 格式说明页）"
        ),
    )


def _build_chinese_twelve_lu() -> TuningSystem:
    ratios = _sorted_by_cents(_fifth_chain_ratios(tuple(range(1, 12))))
    ratios.append(Fraction(2, 1))
    return TuningSystem.from_ratios(
        name="中国三分损益十二律（3-limit 十二律）",
        source=(
            f"三分损益相生（3/2 与 4/3 交替）所得十二律音级集合；{_SOURCE_CHINESE_LUXUE}；"
            f"{_SOURCE_ELLIS}"
        ),
        ratios=ratios,
    )


def _build_indian_22_shruti_sampling() -> TuningSystem:
    return TuningSystem.from_cents(
        name="印度 22 shruti 等程采样（1200/22）",
        source=f"{_SOURCE_SHRUTI}；{_SOURCE_ELLIS}",
        cents=_equal_division_cents(22),
    )


def _build_arabic_24_tone_sampling() -> TuningSystem:
    return TuningSystem.from_cents(
        name="阿拉伯 24 音等程采样（1200/24）",
        source=f"{_SOURCE_MAQAM}；{_SOURCE_ELLIS}",
        cents=_equal_division_cents(24),
    )


_BUILDERS = {
    "12tet": _build_twelve_tet,
    "just_major": _build_just_major,
    "pythagorean_diatonic": _build_pythagorean_diatonic,
    "quarter_comma_meantone": _build_quarter_comma_meantone,
    "chinese_sanfen_sunyi_12": _build_chinese_twelve_lu,
    "indian_22_shruti": _build_indian_22_shruti_sampling,
    "arabic_24_tone": _build_arabic_24_tone_sampling,
}

TEMPLATE_KEYS: tuple[str, ...] = tuple(_BUILDERS)

TEMPLATES: dict[str, TuningSystem] = {key: builder() for key, builder in _BUILDERS.items()}


def list_templates() -> list[str]:
    """内置模板键名（与 `TEMPLATES` 键一致）。"""
    return list(TEMPLATE_KEYS)


def get_template(key: str) -> TuningSystem:
    """按键名取内置模板；未知键名抛 KeyError。"""
    if key not in TEMPLATES:
        raise KeyError(f"未知内置音律模板：{key!r}（可用：{', '.join(TEMPLATE_KEYS)}）")
    return TEMPLATES[key]


def load_scl(
    path: str | Path,
    *,
    source: str | None = None,
    name: str | None = None,
    reference_freq: float = float(A4_FREQ),
) -> TuningSystem:
    """读用户 .scl 文件 → :class:`TuningSystem`。

    ``source`` 省略时按“用户提供文件”如实标注（不臆造文献出处）；调用方已知出处
    时应显式传入。
    """
    file_path = Path(path)
    from .scl import parse_scl_file

    scale = parse_scl_file(file_path)
    return TuningSystem.from_cents(
        name=name or scale.description or file_path.stem or "untitled",
        source=source or f"用户提供的 .scl 文件：{file_path.name}（Huygens-Fokker .scl 格式；未随附文献出处）",
        cents=list(scale.cents()),
        reference_freq=reference_freq,
    )
