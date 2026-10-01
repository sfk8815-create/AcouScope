# SPDX-License-Identifier: GPL-3.0-only
"""语义化版本比较（UP-0 提取为公共模块，原属 ai/ollama_engines.py）。

服务两条线：
1. ollama_engines 引擎升级——本地内置模型引擎的新旧判定；
2. update_checker（UP-2）——app 自更新判定。

零网络、零第三方依赖：仅用标准库 re。
"""
from __future__ import annotations

import re


def ver_tuple(s: str) -> tuple[int, ...]:
    """'v0.33.3' / '0.34.0-rc1' → 数值元组（不足位补 0）。"""
    out: list[int] = []
    for seg in re.split(r"[.\-+]", s.strip().lstrip("vV")):
        if seg.isdigit():
            out.append(int(seg))
        elif out:
            break
    while len(out) < 4:
        out.append(0)
    return tuple(out[:4])


def is_newer(new: str, old: str) -> bool:
    """new 严格高于 old（语义化版本比较；带预发布后缀按主版本比）。"""
    return ver_tuple(new) > ver_tuple(old)


#: 旧调用式别名（语义零变）。
_ver_tuple = ver_tuple
