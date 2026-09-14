# SPDX-License-Identifier: GPL-3.0-only
"""工尺谱 / 简谱 谱名映射层（T-923，音律标尺链第 6 项）。

本模块只做 **音级（degree）→ 谱名** 的纯数据/纯函数映射，**不做任何界面渲染**
（渲染与联动另立任务）。只读消费 T-918 的 :class:`~acouscope.analysis.tunings.tuning_system.TuningSystem`
（``degrees`` / ``degree_count`` / ``degree_to_cents`` / ``is_octave_repeating``），
不新增第三方依赖。

适用性规则（本层自定口径，非对某项标准的声称）：

- **七声等八度音律**（``degree_count == 7`` 且八度重复）：音级序直接对应简谱 1–7
  / 工尺谱 上 尺 工 凡 六 五 乙。
- **十二音等八度音律**（``degree_count == 12`` 且八度重复）：先取与该音律自身音分
  最接近十二平均律大调七声位置（0/200/400/500/700/900/1100 音分）的七个音级作
  **七声骨架**；骨架上记 1–7（工尺 上尺工凡六五乙），骨架外音级按**相对骨架上
  最近音级的实际音分偏差**记升/降号（偏差超出容差则判不适用，见下）。
- **其余情形**（音级数既非 7 也非 12、或非八度重复，如 22 shruti 等程采样、
  24 音等程采样、非八度 .scl）一律 ``applicable=False``，并在 ``note`` 写明原因，
  **不做硬凑**。
- 十二音音律下，**工尺谱对骨架外（升降）音级不给出谱字**：文献（泉州南音工乂谱
  考述）明确工尺谱七声谱字可表 4（凡）与 7（乙），但对 #4 / b7 一类升降音级无
  专用字形、须借调名处理；本层据此返回 ``applicable=False`` 而非臆造升降谱字。

文本约定（write-up 见 ``.pi/reports/T-923_report.json``）：

- 简谱：数字 1–7；升/降记号以 ``#`` / ``b`` **前置**；八度以组合上加点（U+0307，
  高八度）/ 组合下加点（U+0323，低八度）**后置**，每高/低一个八度加一个点：
  ``"1"``、``"#4"``、``"1̇"``、``"7̣"``。
- 工尺谱：本位七声用字 上 尺 工 凡 六 五 乙；低八度三音（徵/羽/变宫）用传统专用字
  合 四 一；高八度在字**前加「亻」旁**（每高一个八度加一个「亻」，如 ``"亻上"``）；
  其余低八度以组合下加点承载曳尾记号。高八度变体在本层以「亻」+ 本字的**拼接串**
  表示——文献中存在复合字形（仩 / 伬 / 仜 / 亿 等，另有扩展区生僻字），为免依赖
  生僻字形渲染，统一采用拼接形式。

``octave_offset`` 的基准是**主音（宫）所在的八度**：主音所在八度记 0，低一个八度
记 -1，高一个八度记 +1（与 ``text`` 中的八度修饰一致）。

锚点口径（报告同步说明）：参照音级 ``tonic_degree`` 同时充当简谱的 **1** 与工尺谱的
**上（宫）** 锚点——工尺谱唱名以宫（谱字「上」）为基准（见 S1/S2），中国音乐实践中
简谱的 1 亦对应宫音。若调用方手中的主音不是宫音（如徵调式），应改传宫音音级：本层
只做映射，**不推断调式**（调式推断属 T-919/T-920 职责）。

文献依据（逐条见 :data:`MAPPING_SOURCES` 与 ``.pi/reports/T-923_report.json``）；
中国律学综述出处同 ``.pi/knowledge/RESEARCH_JOURNAL.md`` R8 B 项。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["NoteName", "MAPPING_SOURCES", "available_systems", "degree_to_name"]

OCTAVE_CENTS = 1200.0

SYSTEMS: tuple[str, ...] = ("jianpu", "gongche")

# 简谱数字（相对主音的第 1–7 个七声音级）
_JIANPU_DIGITS: tuple[str, ...] = ("1", "2", "3", "4", "5", "6", "7")
# 工尺谱本位七声用字（与简谱 1–7 一一对应，见 MAPPING_SOURCES S1/S2）
_GONGCHE_BASE: tuple[str, ...] = ("上", "尺", "工", "凡", "六", "五", "乙")
# 低八度徵 / 羽 / 变宫的传统专用字（S1/S4）
_GONGCHE_LOW_REGISTER: dict[int, str] = {4: "合", 5: "四", 6: "一"}
# 八度记号（组合附加符号）：上加点 = 高八度，下加点 = 低八度（简谱）/ 曳尾（工尺）
_OCTAVE_UP = "\u0307"
_OCTAVE_DOWN = "\u0323"
_GONGCHE_UP_RADICAL = "亻"

# 十二平均律大调七声位置（音分），仅用作**十二音音律**的骨架音级选取参照
_TWELVE_TET_MAJOR_CENTS: tuple[float, ...] = (0.0, 200.0, 400.0, 500.0, 700.0, 900.0, 1100.0)
# 骨架音级选取容差：骨架音级与其十二平均律参照位置的实际音分偏差上限
_SKELETON_TOL_CENTS = 50.0
# 升降号容差：音级相对最近骨架音级的偏差与 0 / ±100 音分的允许残差
_ACCIDENTAL_TOL_CENTS = 50.0
_EPS = 1e-9

# 映射表文献依据（每条：主张 → 出处）。报告与 docstring 同步引用。
MAPPING_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "gongche-7-base",
        "工尺谱本位七声用字为 上 尺 工 凡 六 五 乙，对应唱名 do re mi fa sol la si"
        "（即简谱 1–7）；近代通行谱字十个为 合 四 一 上 尺 工 凡 六 五 乙。",
        "中華思想文化術語庫（中國社會科學院等）「Gong-che Notation」词条 "
        "https://www.chinesethought.cn/phone/EN/shuyu_show.aspx?shuyu_id=4623 ；"
        "维基百科「Gongche notation」条目谱字与简谱对照表 "
        "https://en.wikipedia.org/wiki/Gongche_notation （本次实读镜像 "
        "https://a.osmarks.net/content/wikipedia_en_all_maxi_2020-08/A/Gongche_notation）",
    ),
    (
        "gongche-low-register",
        "低八度三音（徵/羽/变宫）用传统专用字 合 四 一；低八度的 上 尺 工 凡 以曳尾"
        "（末笔下垂小撇）记号书写。",
        "维基百科「Gongche notation」条目「Usual variations」：合 四 一 对应 5̣ 6̣ 7̣，"
        "昆曲传统中上尺工凡末笔加下垂小撇表示低八度 "
        "https://en.wikipedia.org/wiki/Gongche_notation ；"
        "ISO/IEC JTC1/SC2/WG2 N4967（2018）提案说明中「带下垂小撇」的工尺谱字形与"
        "陈根方《中国工尺谱的数字实现研究》谱字表 https://unicode.org/wg2/docs/n4967-gongche.pdf",
    ),
    (
        "gongche-high-octave",
        "高八度在字左旁加「亻」旁（如 仩 / 伬 / 仜 / 亿 等复合字形），表示比本位音高"
        "一个八度。",
        "教育部《異體字字典》B00021「仩」：「工尺譜以上、尺、工、反、六、五、乙代表 "
        "do、re、mi、fa、sol、la、si」，「仩」是「上」的高八度 "
        "https://dict.variants.moe.edu.tw/dictView.jsp?ID=54092 ；"
        "维基百科「Gongche notation」条目昆曲工尺谱字表（仩 伬 仜 … 伍 亿 = 1̇–7̇）"
        "https://en.wikipedia.org/wiki/Gongche_notation",
    ),
    (
        "gongche-no-chromatic",
        "工尺谱七声谱字无升降记号字形：可表 4（凡）与 7（乙），但对 #4 / b7 一类升降"
        "音级不作专用谱字，须借调名（宫调）处理。",
        "魏朝阳《泉州弦管工乂谱与古乐工尺谱考述》：「工尺谱能表示 4 fa 却不能表示 #4，"
        "能表示 7 si 却不能表示 b7」 http://www.qznanyin.cn/gcpks.html ；"
        "维基百科「Gongche notation」条目亦记 凡/乙 在清角与变徵、变宫与闰之间的"
        "记名歧义（variations） https://en.wikipedia.org/wiki/Gongche_notation",
    ),
    (
        "jianpu-digits-and-octave",
        "简谱以数字 1–7 记七声唱名，数字上方点表示高八度、下方点表示低八度。",
        "维基百科「Gongche notation」条目简谱对照列（1–7 及 1̇ / 5̣ 等八度点写法）"
        "https://en.wikipedia.org/wiki/Gongche_notation ；"
        "中華思想文化術語庫「Gong-che Notation」词条（上尺工凡六五乙 与 do–si 对应）"
        "https://www.chinesethought.cn/phone/EN/shuyu_show.aspx?shuyu_id=4623",
    ),
    (
        "chinese-12lu-background",
        "中国十二律（三分损益 / 五度相生）与七声骨架的关系背景：本层的十二音骨架"
        "选取仅作记名参照，音高一律取音律自身音级音分，不折算为十二平均律值。",
        "中国律学文献（RESEARCH_JOURNAL R8 B 项）：euro-acad 中国律学综述 "
        "https://euro-acad.eu ；UChicago「From Ut Re Mi to Fourteen-Tone Temperament」；"
        "UNT「Lu-Pitch Name Signification」「Perspectives of Chinese Music」",
    ),
)


@dataclass(frozen=True)
class NoteName:
    """一个音级在某一谱名体系下的记名。

    Attributes:
        system: 谱名体系（``"jianpu"`` / ``"gongche"``）。
        text: 记名文本（含升降与八度修饰）；``applicable`` 为 False 时为空串。
        degree: 传入的音级（原样保留，含超界外推值）。
        octave_offset: 相对**主音（宫）所在八度**的八度偏移（0 / +1 / -1 / …）；
            不适用时为 0。
        cents: 该音级相对音律 1/1 的音分（取自 ``tuning.degree_to_cents``）。
        applicable: 本体系对本音级是否适用。
        note: 不适用原因的显式说明（不适用时非空）；适用时为空串或口径备注
            （十二音骨架路径会注明骨架选取口径与实际音分偏差）。
    """

    system: str
    text: str
    degree: int
    octave_offset: int
    cents: float
    applicable: bool
    note: str

    def __post_init__(self) -> None:
        if self.system not in SYSTEMS:
            raise ValueError(f"未知谱名体系：{self.system!r}（可用：{', '.join(SYSTEMS)}）")
        if not isinstance(self.octave_offset, int) or isinstance(self.octave_offset, bool):
            raise TypeError("octave_offset 需为 int")
        if not self.applicable and not self.note:
            raise ValueError("applicable=False 时 note 必须写明原因（禁默认/臆造）")
        if not self.applicable and self.text:
            raise ValueError("applicable=False 时 text 必须为空（不给出硬凑记名）")


def available_systems() -> tuple[str, ...]:
    """本层支持的谱名体系（``("jianpu", "gongche")``）。"""
    return SYSTEMS


def _require_tuning(tuning: object) -> None:
    for attr in ("degrees", "degree_count", "is_octave_repeating", "degree_to_cents"):
        if not hasattr(tuning, attr):
            raise TypeError(f"tuning 需具备 TuningSystem 接口（缺 {attr}）")


def _nearest_skeleton(offsets: list[float], target: float) -> tuple[int, float]:
    """在升序骨架音分（``offsets[0] == 0`` 为主音/宫）中取最接近 ``target`` 者。

    Returns:
        (骨架下标, 偏差)；偏差归一到 [-600, 600] 音分。
    """
    best_index = 0
    best_delta = math.inf
    for index, value in enumerate(offsets):
        delta = target - value
        if delta > OCTAVE_CENTS / 2:
            delta -= OCTAVE_CENTS
        elif delta < -OCTAVE_CENTS / 2:
            delta += OCTAVE_CENTS
        if abs(delta) < abs(best_delta) - 1e-12:
            best_index = index
            best_delta = delta
    return best_index, best_delta


def _seven_skeleton(tuning: object) -> tuple[tuple[int, ...], str]:
    """七声骨架音级下标（升序）与其选取口径说明（十二音路径专用）。"""
    count = int(tuning.degree_count)  # type: ignore[attr-defined]
    picked: list[int] = []
    for target in _TWELVE_TET_MAJOR_CENTS:
        best = min(
            range(count),
            key=lambda index: abs((float(tuning.degree_to_cents(index)) % OCTAVE_CENTS) - target),  # type: ignore[attr-defined]
        )
        deviation = (float(tuning.degree_to_cents(best)) % OCTAVE_CENTS) - target  # type: ignore[attr-defined]
        if abs(deviation) > _SKELETON_TOL_CENTS:
            return (), (
                f"该音律音级与十二平均律大调七声位置（0/200/400/500/700/900/1100 音分）"
                f"的最大偏差达 {deviation:+.2f} 音分，超出本层骨架选取容差 "
                f"{_SKELETON_TOL_CENTS:.0f} 音分，七声相对化不适用"
            )
        picked.append(best)
    if len(set(picked)) != len(_TWELVE_TET_MAJOR_CENTS):
        return (), "该音律的最近七声骨架音级出现重复，无法构成七声骨架，七声相对化不适用"
    return tuple(sorted(picked)), ""


def _skeleton(tuning: object) -> tuple[tuple[int, ...] | None, str, str]:
    """定位七声骨架。

    Returns:
        (骨架音级下标 / None, 不适用原因 / "", 骨架口径说明 / "")。
    """
    count = int(tuning.degree_count)  # type: ignore[attr-defined]
    if not bool(tuning.is_octave_repeating):  # type: ignore[attr-defined]
        return None, (f"该音律非八度重复（末音级非 2/1），{count} 音级无八度周期，"
                      f"简谱/工尺谱的八度记号无处可依，不适用"), ""
    if count == 7:
        return tuple(range(7)), "", ""
    if count == 12:
        picked, reason = _seven_skeleton(tuning)
        if not picked:
            return None, reason, ""
        return picked, "", (
            "该音律为十二音体系：1–7 对应其七声骨架音级（骨架音级按其音分与十二平均律"
            "大调七声位置的最近者选取，属本层采用的对应约定；实际音高取该音律自身音级音分，"
            "未折算为十二平均律值）"
        )
    return None, (f"该音律为 {count} 音级，不属本层七声（含十二音七声骨架）记名范围——"
                  f"简谱/工尺谱谱字仅覆盖七声（含其升降），本层不硬凑"), ""


def _jianpu_text(index: int, accidental: float, octave_offset: int) -> str:
    prefix = "#" if accidental > 0 else ("b" if accidental < 0 else "")
    digits = _JIANPU_DIGITS[index]
    suffix = _OCTAVE_UP * octave_offset if octave_offset > 0 else _OCTAVE_DOWN * (-octave_offset)
    return f"{prefix}{digits}{suffix}"


def _gongche_text(index: int, octave_offset: int) -> str:
    if octave_offset >= 1:
        return f"{_GONGCHE_UP_RADICAL * octave_offset}{_GONGCHE_BASE[index]}"
    if octave_offset == 0:
        return _GONGCHE_BASE[index]
    if octave_offset == -1 and index in _GONGCHE_LOW_REGISTER:
        return _GONGCHE_LOW_REGISTER[index]
    return f"{_GONGCHE_BASE[index]}{_OCTAVE_DOWN * (-octave_offset)}"


def degree_to_name(
    tuning: object,
    degree: int,
    *,
    system: str = "jianpu",
    tonic_degree: int = 0,
) -> NoteName:
    """音级 → 简谱 / 工尺谱记名。

    Args:
        tuning: :class:`TuningSystem`（只读消费其 ``degrees`` / ``degree_count`` /
            ``degree_to_cents`` / ``is_octave_repeating``）。
        degree: 目标音级（可超界，按音律八度折叠外推）。
        system: ``"jianpu"``（默认）或 ``"gongche"``。
        tonic_degree: 主音（宫）音级，默认 0；按音律音级数取模后使用。

    Returns:
        :class:`NoteName`；体系/音律/音级不适用时 ``applicable=False`` 且 ``note`` 写明原因。
    """
    _require_tuning(tuning)
    if system not in SYSTEMS:
        raise ValueError(f"未知谱名体系：{system!r}（可用：{', '.join(SYSTEMS)}）")
    if not isinstance(degree, int) or isinstance(degree, bool):
        raise TypeError("degree 需为 int")
    if not isinstance(tonic_degree, int) or isinstance(tonic_degree, bool):
        raise TypeError("tonic_degree 需为 int")

    cents = float(tuning.degree_to_cents(degree))  # type: ignore[attr-defined]
    skeleton, reason, skeleton_note = _skeleton(tuning)
    if skeleton is None:
        return NoteName(system, "", degree, 0, cents, False, reason)

    count = int(tuning.degree_count)  # type: ignore[attr-defined]
    tonic = tonic_degree % count
    if tonic not in skeleton:
        return NoteName(
            system, "", degree, 0, cents, False,
            "主音不是该音律七声骨架上的音级（十二音体系的升降音级），"
            "本层七声相对化以骨架音级为 1，故不适用",
        )

    tonic_cents = float(tuning.degree_to_cents(tonic))  # type: ignore[attr-defined]
    offsets = sorted({
        round((float(tuning.degree_to_cents(index)) - tonic_cents) % OCTAVE_CENTS, 9)  # type: ignore[attr-defined]
        for index in skeleton
    })
    if len(offsets) != 7 or abs(offsets[0]) > _EPS:
        return NoteName(
            system, "", degree, 0, cents, False,
            "该音律主音相对化后不足七声骨架（音级在八度内重合或缺失），七声记名不适用",
        )

    raw = cents - tonic_cents
    octave_offset = math.floor(raw / OCTAVE_CENTS)
    remainder = raw - OCTAVE_CENTS * octave_offset
    if remainder >= OCTAVE_CENTS - _EPS:  # 浮点贴近八度边界时归位，保证偏移与记名一致
        remainder -= OCTAVE_CENTS
        octave_offset += 1

    index, delta = _nearest_skeleton(offsets, remainder)
    accidental = min((0.0, 100.0, -100.0), key=lambda value: abs(delta - value))
    residual = delta - accidental

    if abs(residual) > _ACCIDENTAL_TOL_CENTS:
        return NoteName(
            system, "", degree, 0, cents, False,
            f"该音级相对最近七声骨架音级偏 {delta:+.2f} 音分，超出本层十二音记名容差 "
            f"（0/±100 音分的残差上限 {_ACCIDENTAL_TOL_CENTS:.0f} 音分），不硬凑记名",
        )
    if system == "gongche" and accidental != 0.0:
        return NoteName(
            system, "", degree, 0, cents, False,
            "工尺谱七声谱字无升降记号字形（文献记载其可表 4 凡 与 7 乙，但对 #4 / b7 "
            "一类升降音级须借调名处理），本层不臆造升降谱字",
        )

    text = (
        _jianpu_text(index, accidental, octave_offset)
        if system == "jianpu"
        else _gongche_text(index, octave_offset)
    )
    note = skeleton_note
    if skeleton_note and abs(delta) > _EPS:
        note = f"{skeleton_note}；该音级相对骨架音级偏 {delta:+.2f} 音分，记名按其最近骨架音级加记升降号"
    return NoteName(system, text, degree, octave_offset, cents, True, note)
