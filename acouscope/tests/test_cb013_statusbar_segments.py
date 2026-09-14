# SPDX-License-Identifier: GPL-3.0-only
"""CB-013b D-2 回归测试：StatusBarSegments 五段注册 / 菜单显隐 / 配置持久化。

CB-013b 硬规则：独立构造 StatusBarSegments（tmp_path 注入 config_path），
禁构造 MainWindow；main_window 的状态栏段接线以源码锚点断言佐证。
"""

import json

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.statusbar_segments import (
    DEFAULT_SEGMENTS,
    StatusBarSegments,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_default_five_segments_registered_and_visible(qapp):
    """验收③：默认五段齐全（注册顺序 = 显示顺序），且各段显隐开关默认全开。"""
    seg = StatusBarSegments()
    try:
        assert seg.keys() == tuple(s.key for s in DEFAULT_SEGMENTS)
        assert len(seg.keys()) == 5
        for key in seg.keys():
            label = seg.label(key)
            assert label is not None, f"段 {key} 缺承载 QLabel"
            assert seg.is_segment_visible(key) is True
            assert not label.isHidden(), f"段 {key} 默认不应显式隐藏"
    finally:
        seg.close()


def test_menu_checkable_toggle_hides_and_persists(qapp, tmp_path):
    """验收④：菜单项 checkable；trigger 取消勾选 → 段隐藏 + json 落盘；再 trigger 恢复。"""
    cfg = tmp_path / "ui_statusbar_segments.json"
    seg = StatusBarSegments(config_path=cfg)
    try:
        menu = seg.build_menu()
        actions = menu.actions()
        assert len(actions) == len(DEFAULT_SEGMENTS)
        assert all(a.isCheckable() for a in actions)

        zoom_action = next(a for a in actions if a.data() == "zoom")
        assert zoom_action.isChecked() is True

        # 取消勾选 zoom → 段隐藏 + 立即持久化
        zoom_action.trigger()
        assert zoom_action.isChecked() is False
        assert seg.is_segment_visible("zoom") is False
        assert seg.label("zoom").isHidden(), "取消勾选后 zoom 段应隐藏"

        assert cfg.exists(), "配置 json 未落盘"
        saved = json.loads(cfg.read_text(encoding="utf-8"))
        assert saved["segments"]["zoom"] is False
        assert saved["segments"]["file"] is True, "未勾选项不应影响其他段"

        # 再次 trigger 勾选 → 段恢复可见 + 配置翻转回 True
        zoom_action.trigger()
        assert zoom_action.isChecked() is True
        assert seg.is_segment_visible("zoom") is True
        assert not seg.label("zoom").isHidden(), "重新勾选后 zoom 段应恢复"
        saved = json.loads(cfg.read_text(encoding="utf-8"))
        assert saved["segments"]["zoom"] is True
    finally:
        seg.close()


def _main_window_source() -> str:
    import inspect
    from pathlib import Path

    return Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")


def test_main_window_status_segments_wiring_anchor():
    """接线锚点：status_segments 宿主/右键菜单/持久化路径出现在 main_window 文本。

    禁构造 MainWindow（CB-013b 硬规则）→ 接线正确性以源码文本佐证：
    宿主构造、QStatusBar addWidget、右键菜单入口与配置文件名。
    """
    src = _main_window_source()
    assert "self.status_segments = StatusBarSegments(" in src, (
        "main_window 未构造 StatusBarSegments 宿主"
    )
    assert "status.addWidget(self.status_segments)" in src, (
        "status_segments 未挂入 QStatusBar"
    )
    assert "def _show_status_segments_menu" in src, (
        "main_window 缺状态栏右键菜单入口"
    )
    assert "ui_statusbar_segments.json" in src, (
        "main_window 未把段显隐配置指向 ui_statusbar_segments.json"
    )
