# SPDX-License-Identifier: GPL-3.0-only
"""命令索引（T-1119）：把窗口内 QAction 收成可检索条目，并提供子序列模糊匹配。

口径（与既有 `main_window._rebuild_shortcuts_overview` 一致：以 `QAction` 为唯一事实源）：
- 跳过分隔符、无文本、带子菜单的容器动作（`act.menu() is not None`）；
- 文本去助记符 `&`；分类取父 `QMenu` 标题（无则空串）；
- 同一（文本, 快捷键）只留一条；排序按（分类, 文本）稳定序；
- 匹配：大小写不敏感**子序列**（"adcu" → "Add Cube"），连续命中与前缀命中加分，
  空查询返回全部。
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QWidget

_CONT_MATCH_BONUS = 5
_PREFIX_BONUS = 10


@dataclass(frozen=True)
class CommandEntry:
    """一条可执行命令（不可变，便于比较与排序）。"""

    text: str
    shortcut: str = ""
    category: str = ""
    enabled: bool = True


def strip_mnemonic(text: str) -> str:
    """去掉 Qt 助记符 `&`（含转义 `&&`）并压缩首尾空白。"""
    return (text or "").replace("&&", "\x00").replace("&", "").replace("\x00", "&").strip()


def collect_commands(root: QWidget) -> list[CommandEntry]:
    """遍历 `root` 下全部 QAction，返回去重排序后的命令表。"""
    seen: dict[tuple[str, str], CommandEntry] = {}
    for act in root.findChildren(QAction):
        if act.isSeparator():
            continue
        text = strip_mnemonic(act.text())
        if not text or act.menu() is not None:
            continue
        shortcut = act.shortcut().toString() if not act.shortcut().isEmpty() else ""
        category = ""
        for owner in act.associatedObjects():
            if isinstance(owner, QMenu):
                category = strip_mnemonic(owner.title())
                break
        if not category and isinstance(act.parent(), QMenu):
            category = strip_mnemonic(act.parent().title())
        key = (text, shortcut)
        if key in seen:
            continue
        seen[key] = CommandEntry(
            text=text, shortcut=shortcut, category=category, enabled=act.isEnabled()
        )
    return sorted(seen.values(), key=lambda e: (e.category, e.text))


def fuzzy_score(query: str, text: str) -> int | None:
    """子序列匹配得分；不匹配返回 None。分数越高越靠前。"""
    q = (query or "").strip().lower()
    t = (text or "").lower()
    if not q:
        return 0
    score = 0
    pos = 0
    last = -2
    for ch in q:
        idx = t.find(ch, pos)
        if idx < 0:
            return None
        score += 1
        if idx == last + 1:
            score += _CONT_MATCH_BONUS
        last = idx
        pos = idx + 1
    if t.startswith(q):
        score += _PREFIX_BONUS
    return score


def filter_commands(entries: list[CommandEntry], query: str) -> list[CommandEntry]:
    """按查询过滤并排序：文本得分优先，其次快捷键命中，同等分保持原序。"""
    q = (query or "").strip()
    if not q:
        return list(entries)
    scored: list[tuple[int, int, CommandEntry]] = []
    for order, entry in enumerate(entries):
        text_score = fuzzy_score(q, entry.text)
        sc_score = fuzzy_score(q, entry.shortcut) if entry.shortcut else None
        best = max((s for s in (text_score, sc_score) if s is not None), default=None)
        if best is None:
            continue
        scored.append((-best, order, entry))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored]


def collect_commands_with_actions(root: QWidget) -> list[tuple[CommandEntry, QAction]]:
    """与 `collect_commands` 同口径，但同时返回 QAction 引用（供命令面板触发）。"""
    out: list[tuple[CommandEntry, QAction]] = []
    seen: set[tuple[str, str]] = set()
    for act in root.findChildren(QAction):
        if act.isSeparator():
            continue
        text = strip_mnemonic(act.text())
        if not text or act.menu() is not None:
            continue
        shortcut = act.shortcut().toString() if not act.shortcut().isEmpty() else ""
        key = (text, shortcut)
        if key in seen:
            continue
        seen.add(key)
        category = ""
        for owner in act.associatedObjects():
            if isinstance(owner, QMenu):
                category = strip_mnemonic(owner.title())
                break
        if not category and isinstance(act.parent(), QMenu):
            category = strip_mnemonic(act.parent().title())
        out.append((
            CommandEntry(text=text, shortcut=shortcut,
                         category=category, enabled=act.isEnabled()),
            act,
        ))
    out.sort(key=lambda pair: (pair[0].category, pair[0].text))
    return out
