# SPDX-License-Identifier: GPL-3.0-only
"""数值表达式解析（T-1117）：把「2*pi」「min(4,3)」「1.5k」「440*2**(1/12)」算成数。

安全边界（纯函数、零副作用、不触文件/网络/导入）：
- `ast.parse(mode="eval")` 后**白名单**遍历，只许常量 / 二元一次运算 / 正负号 / 白名单函数调用；
- 白名单函数仅 `min max abs round sqrt`，常量仅 `pi e`；禁属性、下标、推导式、lambda、
  关键字参数、星号展开、f-string、导入等一切其它节点；
- 长度上限 64 字符；结果须有限且 |x| ≤ 1e12；任何异常（语法/除零/溢出/类型）⇒ 返回 None。

单位后缀（**只做乘法/换算，不猜语义**）：`k`=1e3、`khz`=1e3、`hz`=1、`db`=1、`s`=1、
`ms`=1e-3、`%`=0.01、`cent(s)`=1。后缀大小写不敏感，允许中间有空格。
"""

from __future__ import annotations

import ast
import math
import re

MAX_LEN = 64
MAX_ABS = 1e12

_FUNCS = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
}
_CONSTS = {"pi": math.pi, "e": math.e}

_UNIT_FACTORS = {
    "": 1.0,
    "k": 1e3,
    "khz": 1e3,
    "hz": 1.0,
    "db": 1.0,
    "s": 1.0,
    "ms": 1e-3,
    "%": 1e-2,
    "cent": 1.0,
    "cents": 1.0,
}

# 结尾单位后缀（先剥单位，再算表达式）：长度 ≥2 的优先，避免 `ms` 被 `s` 抢先
_UNIT_RE = re.compile(r"\s*(khz|hz|db|ms|cent|cents|k|s|%)\s*$", re.IGNORECASE)

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.UAdd,
    ast.USub,
)


def _split_unit(text: str) -> tuple[str, float]:
    """剥掉结尾单位，返回（表达式主体, 换算系数）。"""
    m = _UNIT_RE.search(text)
    if not m:
        return text, 1.0
    factor = _UNIT_FACTORS.get(m.group(1).lower())
    if factor is None:
        return text, 1.0
    body = text[: m.start()]
    if not body.strip():
        return text, 1.0
    return body, factor


def _check_node(node: ast.AST) -> bool:
    if not isinstance(node, _ALLOWED_NODES):
        return False
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            return False
        if node.keywords:
            return False
        if any(isinstance(a, ast.Starred) for a in node.args):
            return False
    if isinstance(node, ast.Name):
        return node.id in _CONSTS or node.id in _FUNCS
    return True


_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a ** b,
    ast.Mod: lambda a, b: a % b,
    ast.FloorDiv: lambda a, b: a // b,
}


def _eval_node(node: ast.AST) -> float:
    """对已过白名单的 AST 求值（不用 eval / compile，纯递归）。"""
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise ValueError(f"未知名字：{node.id}")
    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.UAdd):
            return +val
        raise ValueError("非法一元运算")
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ValueError("非法二元运算")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.Call):
        func = _FUNCS[node.func.id]  # 白名单已保证存在
        return float(func(*[_eval_node(a) for a in node.args]))
    raise ValueError("非法节点")


def parse_number(text: str) -> float | None:
    """把文本算成 float；不可解析 / 越界 / 非有限 ⇒ None。

    >>> parse_number("2*pi") is not None
    True
    >>> parse_number("1.5k")
    1500.0
    >>> parse_number("__import__('os')") is None
    True
    """
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw or len(raw) > MAX_LEN:
        return None

    # 快路径：纯数字（含科学计数法、正负号）
    try:
        value = float(raw)
    except ValueError:
        body, factor = _split_unit(raw)
        try:
            tree = ast.parse(body.strip(), mode="eval")
        except SyntaxError:
            return None
        if not all(_check_node(node) for node in ast.walk(tree)):
            return None
        try:
            value = float(_eval_node(tree.body)) * factor
        except (ZeroDivisionError, OverflowError, ValueError, TypeError, RecursionError):
            return None

    if not math.isfinite(value) or abs(value) > MAX_ABS:
        return None
    return value
