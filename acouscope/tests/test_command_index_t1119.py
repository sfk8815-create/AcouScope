# SPDX-License-Identifier: GPL-3.0-only
"""T-1119 命令索引：QAction 收集口径 + 子序列模糊匹配。"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMenu, QWidget

from acouscope.ui.command_index import (
    CommandEntry,
    collect_commands,
    filter_commands,
    fuzzy_score,
    strip_mnemonic,
)


def _host_with_actions():
    host = QWidget()
    menu = QMenu("视图(&V)", host)
    a1 = QAction("图表设计器(&D)", host)
    a1.setShortcut(QKeySequence("Ctrl+Shift+D"))
    a2 = QAction("房间模态分析", host)
    a3 = QAction("Add Cube", host)
    sub = QMenu("导出(&E)", host)
    a4 = QAction("导出音频文件", host)
    sub.addAction(a4)
    for act in (a1, a2, a3):
        menu.addAction(act)
    menubar_like = QWidget(host)
    menubar_like.addAction(menu.menuAction())
    a_disabled = QAction("禁用项", host)
    a_disabled.setEnabled(False)
    host.addAction(a_disabled)
    host.addAction(QAction("", host))       # 空文本
    host.addAction(QAction(host))           # 分隔符
    host.addAction(menu.menuAction())       # 菜单容器（带子菜单）
    return host


def test_collect_skips_containers_and_dedupes(qapp):
    entries = collect_commands(_host_with_actions())
    texts = [e.text for e in entries]
    assert "视图" not in texts, "菜单容器不应入表"
    assert "" not in texts
    assert "图表设计器(D)" in texts   # 助记符 & 去掉后保留 (D)
    assert "房间模态分析" in texts
    assert "Add Cube" in texts
    assert "禁用项" in texts

    by_text = {e.text: e for e in entries}
    assert by_text["图表设计器(D)"].shortcut == "Ctrl+Shift+D"
    assert by_text["图表设计器(D)"].category == "视图(V)"
    assert by_text["禁用项"].enabled is False


def test_strip_mnemonic():
    assert strip_mnemonic("图表设计器(&D)") == "图表设计器(D)"
    assert strip_mnemonic("A && B") == "A & B"


@pytest.mark.parametrize("query,text,hit", [
    ("adcu", "Add Cube", True),
    ("AdCu", "add cube", True),
    ("导出", "导出音频文件", True),
    ("音出", "导出音频文件", False),
    ("xyz", "导出音频文件", False),
])
def test_fuzzy(query, text, hit):
    got = fuzzy_score(query, text)
    assert (got is not None) is hit


def test_prefix_beats_scattered():
    prefix = fuzzy_score("导出", "导出音频文件")
    scattered = fuzzy_score("导出", "导语出文件")
    assert prefix is not None and scattered is not None
    assert prefix > scattered


def test_filter_orders_and_empty_query():
    entries = [
        CommandEntry(text="导出音频文件", shortcut="Ctrl+E"),
        CommandEntry(text="房间模态分析", shortcut=""),
        CommandEntry(text="Chart Designer", shortcut="Ctrl+Shift+D"),
    ]
    assert filter_commands(entries, "") == entries
    hits = [e.text for e in filter_commands(entries, "导出")]
    assert hits[0] == "导出音频文件"
    assert "房间模态分析" not in hits
    # 快捷键也可检索
    assert filter_commands(entries, "shift")[0].text == "Chart Designer"
