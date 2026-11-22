# SPDX-License-Identifier: GPL-3.0-only
"""Scala .scl 音阶文件解析（T-918，音律标尺链基座）。

严格实现 Huygens-Fokker 基金会（Scala 软件）公布的 .scl 文本格式规则：
https://www.huygens-fokker.org/scala/scl_format.html （来源归档见 RESEARCH_JOURNAL R8）

格式要点（实现口径 = 该官方文档原文，不附加其它标准）：
- 每行行首为 ``!`` 者＝注释，忽略；空白行忽略（容错口径）；
- 之后第一条内容行＝描述（只有一行；若无描述，官方规定该处为空行，本实现据此把
  “首条内容行本身即音数整数”的情形判定为无描述，描述记为空串）；
- 再一条内容行＝音数 N（其后应有 N 行音高值；N 下限为 0，因 1/1 是隐含的 0 度）；
- 音高值：**含小数点 ``.`` 者按音分（cents）解释**；否则按比值解释（``a/b`` 写且仅一个
  斜杠；无斜杠的纯整数按 ``n/1``，例 ``2`` = ``2/1``）；一行内有效音高值之后的任何
  内容忽略（例 ``100.0 C#``）。分子分母支持到 2^31-1 以上（本实现用 Fraction 精确承载）；
- 负**比值**无意义，应报读错（本实现抛 ValueError）；官方文档示例把 ``-5.0`` 列为合法
  音高行（负音分），本实现照该示例接受负音分；
- 1/1 或 0.0 音分不在文件内，由调用方隐含补入（见 ``TuningSystem``）；
- 无法按上述规则解析者视为格式错误，抛出 ValueError（调用方捕获）。

.kbm 键盘映射文件不在本模块范围（T-918 需求说明明示）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .tuning_system import OCTAVE_CENTS

__all__ = [
    "SCL_CENTS_DECIMALS",
    "SclScale",
    "SclValue",
    "format_scl",
    "parse_scl",
    "parse_scl_file",
    "save_scl",
]

#: 写出音分值的十进制位数（W-14-06：**至少** 5 位；取 6 位使
#: ``parse_scl(format_scl(t))`` 的往返误差 ≤ 5e-7（< 1e-6 判据）。
SCL_CENTS_DECIMALS = 6

KIND_CENTS = "cents"
KIND_RATIO = "ratio"


@dataclass(frozen=True)
class SclValue:
    """.scl 中的单个音高值。

    kind 为 ``"cents"``（音分值）或 ``"ratio"``（比值）；``cents`` 恒为相对 1/1 的
    音分值（比值条目由 1200*log2(比值) 换算），``ratio`` 仅在比值条目时非 None，
    以 Fraction 精确承载大整数分子分母。
    """

    raw: str
    kind: str
    cents: float
    ratio: Fraction | None = None


@dataclass(frozen=True)
class SclScale:
    """一个 .scl 文件解析结果（不含隐含的 1/1 度）。"""

    description: str
    note_count: int
    values: tuple[SclValue, ...]

    def cents(self) -> tuple[float, ...]:
        """N 个音高值的音分序列（相对 1/1，未含隐含 0 度）。"""
        return tuple(value.cents for value in self.values)


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("!")


def _parse_nonnegative_int(text: str, what: str) -> int:
    token = text.strip()
    if not token.isdigit():
        raise ValueError(f"{what}应为非负整数，实际为 {text!r}")
    return int(token)


def _parse_pitch(line: str) -> SclValue:
    """解析单行音高值（行内首个 token 有效，其余按官方规则忽略）。"""
    stripped = line.strip()
    if not stripped:
        raise ValueError("空行不是合法音高行")
    token = stripped.split()[0]
    if "." in token:  # 官方规则：含小数点即音分
        try:
            cents = float(token)
        except ValueError as exc:  # pragma: no cover - 前置判断已排除多数情形
            raise ValueError(f"非法音分值：{token!r}") from exc
        if not math.isfinite(cents):
            raise ValueError(f"非法音分值（非有限数）：{token!r}")
        return SclValue(raw=token, kind=KIND_CENTS, cents=cents, ratio=None)
    # 其余按比值：n 或 a/b（仅一个斜杠）
    if token.count("/") > 1:
        raise ValueError(f"非法比值（斜杠多于一个）：{token!r}")
    if "/" in token:
        num_text, den_text = token.split("/")
    else:
        num_text, den_text = token, "1"
    if num_text.startswith("-") or den_text.startswith("-"):
        raise ValueError(f"负比值无意义，应报读错：{token!r}")
    num = _parse_nonnegative_int(num_text, "比值分子")
    den = _parse_nonnegative_int(den_text, "比值分母")
    if num == 0 or den == 0:
        raise ValueError(f"零比值无意义：{token!r}")
    cents = 1200.0 * (math.log2(num) - math.log2(den))
    return SclValue(raw=token, kind=KIND_RATIO, cents=cents, ratio=Fraction(num, den))


def parse_scl(text: str) -> SclScale:
    """按 Huygens-Fokker .scl 规则解析文本，返回 :class:`SclScale`。

    任何不符合官方规则的内容（音数非整数、音高行数不足或多余、比值含负号或零等）
    均抛出 ValueError。音数 N 允许为 0（此时 values 为空元组）。
    """
    if not isinstance(text, str):
        raise ValueError(f"parse_scl 需要 str，实际为 {type(text).__name__}")
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    pos = 0
    # 描述行：跳过注释与空白行后取第一条内容行；若该行本身是整数（即无描述，
    # 官方口径“无描述时应为空行”），则描述为空串并把该行当音数行处理。
    while pos < len(lines) and (_is_comment(lines[pos]) or not lines[pos].strip()):
        pos += 1
    description = ""
    if pos < len(lines) and not lines[pos].strip().isdigit():
        description = lines[pos].strip()
        pos += 1
    while pos < len(lines) and (not lines[pos].strip() or _is_comment(lines[pos])):
        pos += 1
    if pos >= len(lines):
        raise ValueError("缺少音数行（描述行之后应给出音数 N）")
    note_count = _parse_nonnegative_int(lines[pos], "音数 N")
    pos += 1
    values: list[SclValue] = []
    while len(values) < note_count and pos < len(lines):
        candidate = lines[pos]
        pos += 1
        if not candidate.strip() or _is_comment(candidate):
            continue
        values.append(_parse_pitch(candidate))
    if len(values) < note_count:
        raise ValueError(f"音高值不足：声明 {note_count} 个，实际仅有 {len(values)} 个")
    for extra in lines[pos:]:
        if extra.strip() and not _is_comment(extra):
            raise ValueError(f"音高值多于声明的音数 {note_count}：出现多余内容 {extra.strip()!r}")
    return SclScale(description=description, note_count=note_count, values=tuple(values))


def parse_scl_file(path: str | Path) -> SclScale:
    """读取并解析 .scl 文件（ASCII/Latin-1 文本，见官方格式脚注 1）。"""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="latin-1")
    return parse_scl(text)


def _scl_slug(text: str) -> str:
    """描述 → 注释首行的文件名片段（仅 ASCII 安全字符；空则 ``scale``）。"""
    kept = "".join(
        ch if (ch.isalnum() and ch.isascii()) or ch in "-_" else "_" for ch in str(text)
    ).strip("_")
    while "__" in kept:
        kept = kept.replace("__", "_")
    return kept or "scale"


def format_scl(tuning) -> str:
    """``TuningSystem`` → 合法 ``.scl`` 文本（W-14-06 写出通路）。

    口径（逐条对齐官方格式与设计约定 A 应见）：
    - 首条内容行 = 描述（取 ``tuning.name``）；
    - 其后音数 N = ``tuning.degree_count``（不含隐含 1/1 的 0 度）；
    - 音高值逐条按音分写出，保留 :data:`SCL_CENTS_DECIMALS` 位小数（≥5 位，
      往返误差 <1e-6）；末值与八度（1200.0 音分）相等时写 ``2/1`` 比值形；
    - ``tuning.source`` 逐行写成 ``!`` 注释（来源不进数值面，但随文件可查）。

    非等八度音律（末值 ≠ 1200）照实写音分值，**不**伪造 ``2/1``。
    """
    degrees = [float(value) for value in getattr(tuning, "degrees", ()) or ()]
    if not degrees:
        raise ValueError("format_scl 需要含 degrees 的音律对象")
    values = degrees[1:]
    if not values:
        raise ValueError("format_scl 需要至少一个音级（除隐含 1/1 外）")
    lines = [
        f"! {_scl_slug(getattr(tuning, 'name', ''))}.scl",
        "! 由 AcouScope 写出（Huygens-Fokker .scl 格式）",
    ]
    source = str(getattr(tuning, "source", "") or "")
    for chunk in source.splitlines() or [""]:
        lines.append(f"! {chunk}".rstrip())
    lines.append(str(getattr(tuning, "name", "") or "untitled"))
    lines.append(f" {len(values)}")
    lines.append("!")
    for index, value in enumerate(values):
        is_last = index == len(values) - 1
        if is_last and abs(value - OCTAVE_CENTS) < 1e-9:
            lines.append(" 2/1")
        else:
            lines.append(f" {value:.{SCL_CENTS_DECIMALS}f}")
    return "\n".join(lines) + "\n"


def save_scl(tuning, path: str | Path) -> Path:
    """把音律写成 ``.scl`` 文件（UTF-8）；返回落盘路径。

    写出后**不**自动回读校验：往返由调用方（或测试）用
    :func:`parse_scl` / :func:`parse_scl_file` 自行比对。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_scl(tuning), encoding="utf-8")
    return target
