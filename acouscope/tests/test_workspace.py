# SPDX-License-Identifier: GPL-3.0-only
"""T-503b 三栏骨架与布局持久化测试（不构造 MainWindow，绕开 backlog #6）。"""
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSplitter
from acouscope.ui.widgets.panels import PanelContainer
from acouscope.ui.widgets.panels.workspace import (
    build_workspace_splitter, save_workspace, restore_workspace)


def _ws():
    return build_workspace_splitter(QLabel("center"))


def test_three_columns(qapp):
    ws = _ws()
    sp = ws["splitter"]
    assert isinstance(sp, QSplitter)
    assert sp.orientation() == Qt.Orientation.Horizontal
    assert sp.count() == 3
    assert sp.widget(1).text() == "center"
    assert isinstance(ws["left"], PanelContainer)
    assert isinstance(ws["right"], PanelContainer)
    # T-1012：无标题栏横条（标题文字不再呈现）
    assert not hasattr(ws["left"], "lblTitle")
    assert not hasattr(ws["right"], "lblTitle")


def test_save_restore_roundtrip(qapp, tmp_path):
    ws = _ws()
    ws["left"].set_collapsed(True)
    p = tmp_path / "ui_layout.json"
    save_workspace(ws, path=p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data["sizes"]) == 3
    assert data["left_collapsed"] is True and data["right_collapsed"] is False

    ws2 = _ws()
    restore_workspace(ws2, path=p)
    assert ws2["left"].is_collapsed() is True
    assert ws2["right"].is_collapsed() is False


def test_restore_missing_and_corrupt_silent(qapp, tmp_path):
    ws = _ws()
    restore_workspace(ws, path=tmp_path / "nope.json")  # 不存在不抛
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    restore_workspace(ws, path=bad)  # 损坏不抛
    ws["left"].set_collapsed(False)


def test_persist_sizes(qapp, tmp_path):
    # 离屏 splitter 未 show 时按当前几何分配尺寸；基准宽 = 目标宽和 + 2×手柄宽，
    # 使 setSizes 数值精确落到可用区（几何断言口径：resize 基准宽 + 往返实测）
    ws = _ws()
    sp = ws["splitter"]
    target = [300, 600, 250]
    base = sum(target) + 2 * sp.handleWidth()
    sp.resize(base, 500)
    sp.setSizes(target)
    expected = list(sp.sizes())
    p = tmp_path / "ui_layout.json"
    save_workspace(ws, path=p)
    ws2 = _ws()
    ws2["splitter"].resize(base, 500)
    restore_workspace(ws2, path=p)
    # 持久化往返：恢复值必须与保存实测值精确一致
    assert list(ws2["splitter"].sizes()) == expected
    assert expected == target


def test_no_qsettings(qapp):
    src = pathlib.Path(sys.path[0]) / "acouscope" / "ui" / "widgets" / "panels" / "workspace.py"
    if not src.exists():
        src = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "widgets" / "panels" / "workspace.py"
    text = src.read_text(encoding="utf-8")
    assert "QSettings" not in text
    assert "get_data_dir" in text
