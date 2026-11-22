# SPDX-License-Identifier: GPL-3.0-only
"""内置音律模板与 .scl 文件加载（T-918，音律标尺链基座）。

首期只提供**少量代表性模板**，每个模板的 ``source`` 标注学术出处（R8：
``内部记录/knowledge/RESEARCH_JOURNAL.md`` R8 条，音律格式与各传统音律来源），
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
    "PAPER_TEMPLATE_KEYS",
    "TEMPLATE_KEYS",
    "TEMPLATES",
    "CUSTOM_PREFIX",
    "get_template",
    "get_tuning",
    "is_custom_spec",
    "list_paper_templates",
    "list_templates",
    "load_scl",
    "template_fingerprint",
    "template_metadata",
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
#: 琴律（古琴复合律制）：文献出处与三条纪律（2026-10-31 起纳入论文模板集）
_SOURCE_QINLU = (
    "古琴复合律制（琴律）：黄翔鹏《中国传统音调的数理逻辑关系问题》"
    "（《中国音乐学》1986(3)：11、12）所述「三分损益」与「纯律三度相生」兼用；"
    "该文 p.11 明记徽位音分 十一徽 mi 386（＝5/4）、五弦九徽 mi 408（＝81/64，"
    "三分损益大三度）、一弦八徽 la 884（＝5/3），本模板据以取「三分损益基列＋纯律"
    "一次低列」两列，列间距为普通音差 81/80＝21.506 音分；R8 B 项登记该项中国律学"
    f"文献来源；{_SOURCE_ELLIS}。"
    "声明：本模板只是参照系音分表，非测音结论；同一音级兼存两列时近邻判别较单列模板"
    "宽容约半个普通音差，故其偏离中位数不可与单列模板等量比较，亦不得据以断言"
    "某录音归属某律"
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


#: 琴律（古琴复合律制）音分表，逐字符取自写作侧交件
#: ``Essay_writing/论文支撑/qin_lu/qin_lu.scl``（2026-10-31，子体 A）。
#: 九音＝三分损益基列（9/8、81/64、4/3、3/2、27/16）＋纯律一次低列
#: （10/9、5/4、5/3），两列相差普通音差 81/80；2/1 收尾。
_QINLU_SCL_TEXT = """! qin_lu.scl
!
琴律（古琴复合律制）：三分损益基列 ＋ 纯律一次低列
 9
!
 10/9
 9/8
 5/4
 81/64
 4/3
 3/2
 5/3
 27/16
 2/1
"""


def _build_qin_lu() -> TuningSystem:
    """琴律／古琴复合律制：三分损益基列 ＋ 纯律一次低列。

    文献依据为黄翔鹏 1986：11 的三条实数（十一徽 mi 386＝5/4、五弦九徽 mi 408＝
    81/64、一弦八徽 la 884＝5/3），三条在本模板中逐位复现；其余音由「列间相差
    81/80」的路向推出。``source`` 内写明：只是参照系音分表，不作「符合某律」的
    断言（与设计约定 §五 趋近口径一致）。
    """
    return TuningSystem.from_scl(
        _QINLU_SCL_TEXT,
        source=_SOURCE_QINLU,
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
    "qin_lu": _build_qin_lu,
    "indian_22_shruti": _build_indian_22_shruti_sampling,
    "arabic_24_tone": _build_arabic_24_tone_sampling,
}

#: **论文-facing 模板集**（2026-10-31 确定律制参照系整体修正后定格）：
#: 十二平均律降为**对照索引**，印度二十二律、阿拉伯二十四律**移出论文**（代码仍
#: 保留于 :data:`TEMPLATES`，论文不引用、不出图）；其余为同奏语境下的候选参照系。
PAPER_TEMPLATE_KEYS: tuple[str, ...] = (
    "12tet",
    "just_major",
    "pythagorean_diatonic",
    "quarter_comma_meantone",
    "chinese_sanfen_sunyi_12",
    "qin_lu",
)

TEMPLATE_KEYS: tuple[str, ...] = tuple(_BUILDERS)

TEMPLATES: dict[str, TuningSystem] = {key: builder() for key, builder in _BUILDERS.items()}


def list_templates() -> list[str]:
    """内置模板键名（与 `TEMPLATES` 键一致）。"""
    return list(TEMPLATE_KEYS)


def list_paper_templates() -> list[str]:
    """论文模板集键名：出图／出表的默认取模板集（不含印度／阿拉伯）。"""
    return list(PAPER_TEMPLATE_KEYS)


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


#: 自定义音阶的显式前缀（``custom:<path>``；与裸路径等价，供调用方明确标注口径）
CUSTOM_PREFIX = "custom:"


def is_custom_spec(spec) -> bool:
    """该模板 spec 是否指向用户 ``.scl``（而非内置 key）。"""
    text = "" if spec is None else str(spec).strip()
    if not text:
        return False
    if text in TEMPLATES:
        return False
    if text.startswith(CUSTOM_PREFIX):
        return True
    return text.lower().endswith(".scl") or ("/" in text) or ("\\" in text)


def get_tuning(
    spec: str,
    *,
    source: str | None = None,
    name: str | None = None,
    reference_freq: float = float(A4_FREQ),
) -> TuningSystem:
    """模板 spec → :class:`TuningSystem`（内置 key 或用户 ``.scl`` 的统一入口）。

    - 内置 key（:data:`TEMPLATES` 键）⇒ :func:`get_template`；
    - ``custom:<path>`` 或裸 ``.scl`` 路径 ⇒ :func:`load_scl`；
    - 其余 ⇒ **报错**（``KeyError``／``ValueError``），**禁回退 12TET**
      （设计约定 W-14-06：坏 spec 必须显式失败，不得静默改口径）。
    """
    text = "" if spec is None else str(spec).strip()
    if not text:
        raise ValueError("模板 spec 为空：内置 key 或 .scl 路径必须显式给出（禁回退 12TET）")
    if text.startswith(CUSTOM_PREFIX):
        path = text[len(CUSTOM_PREFIX):].strip()
        if not path:
            raise ValueError(f"自定义音阶 spec 缺路径：{spec!r}")
        return load_scl(path, source=source, name=name, reference_freq=reference_freq)
    if text in TEMPLATES:
        return get_template(text)
    if is_custom_spec(text):
        return load_scl(text, source=source, name=name, reference_freq=reference_freq)
    raise KeyError(
        f"未知音律 spec：{text!r}（可用内置：{', '.join(TEMPLATE_KEYS)}；"
        "或给 .scl 路径／custom:<path>）"
    )


def template_fingerprint(key: str, tuning: TuningSystem | None = None) -> str:
    """模板内容指纹：``sha256`` of canonical ``{key,name,source,degrees}``（64 hex）。

    **source 进指纹**（设计约定 W-14-05）：同参数同模板而文献来源改变 ⇒ 指纹变 ⇒
    ``run_id`` 变；仅新增字段而值不变 ⇒ 指纹不变 ⇒ 历史运行件不受影响。
    """
    import hashlib
    import json

    resolved = get_template(key) if tuning is None else tuning
    payload = {
        "key": str(key),
        "name": str(resolved.name),
        "source": str(resolved.source),
        "degrees": [float(value) for value in resolved.degrees],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def template_metadata(
    spec: str,
    *,
    tuning: TuningSystem | None = None,
    sha256: str | None = None,
) -> dict:
    """模板记录块（W-14-05／W-14-06 共用的随件字段面）。

    返回 ``template_key``／``template_name``／``template_source``／
    ``template_degree_count``／``template_fingerprint``，自定义音阶另带
    ``template_sha256``（``.scl`` 文件哈希）与 ``template_custom=True``。
    ``template_key`` 对自定义音阶为 ``custom:<文件名>``（不冒充内置 key）。
    """
    text = "" if spec is None else str(spec).strip()
    custom = is_custom_spec(text)
    resolved = get_tuning(text) if tuning is None else tuning
    if custom:
        raw = text[len(CUSTOM_PREFIX):].strip() if text.startswith(CUSTOM_PREFIX) else text
        key = f"{CUSTOM_PREFIX}{Path(raw).name}"
    else:
        key = text
    block = {
        "template_key": key,
        "template_name": str(resolved.name),
        "template_source": str(resolved.source),
        # 音级数＝.scl 声明的音数 N（不含隐含 1/1）⇒ qin_lu 9、sanfen 12
        "template_degree_count": int(resolved.degree_count),
        "template_fingerprint": template_fingerprint(key, resolved),
    }
    if custom:
        block["template_custom"] = True
        block["template_sha256"] = sha256
    return block
