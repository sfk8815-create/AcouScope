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


def test_default_four_segments_registered_and_visible(qapp):
    """验收③：默认四段齐全（注册顺序 = 显示顺序），且各段显隐开关默认全开；
    sample_rate 段已删（与 lbl_audio_info 同源重复）。"""
    seg = StatusBarSegments()
    try:
        assert seg.keys() == tuple(s.key for s in DEFAULT_SEGMENTS)
        assert len(seg.keys()) == 4
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


# ------------------------------------------------------------------
# P2b-D14 正式判据：elide 配方 + 删段正对照
# ------------------------------------------------------------------

def test_elided_label_recipe_and_segment_wiring(qapp):
    """elide 配方确定性 + 段承载接线 + text() 全文不丢。"""
    from PyQt6.QtGui import QFontMetrics
    from acouscope.ui.widgets.statusbar_segments import ElidedLabel, StatusBarSegments

    long = "文件: a-very-long-file-name-indeed.wav"
    lbl = ElidedLabel(long)
    assert lbl.elided_for_width(400) == long                 # 宽裕不省略
    assert lbl.elided_for_width(40).endswith("…")            # 窄宽省略号收尾
    assert "sample_rate" not in StatusBarSegments().keys()   # 删段（正对照）
    seg = StatusBarSegments()
    try:
        assert isinstance(seg.label("file"), ElidedLabel)
        seg.set_text("file", long)
        assert seg.text("file") == long                      # text() 不因 elide 丢数据
        fm = QFontMetrics(seg.label("file").font())
        assert seg.label("file").minimumSizeHint().width() < fm.horizontalAdvance(long)
    finally:
        seg.close()


# ------------------------------------------------------------------
# P2b-D14-fix2 新增判据：elide 绘制判据有齿化（直调绕开 PyQt 异常吞没）
# ------------------------------------------------------------------

def test_elided_label_paint_event_direct_call_no_raise(qapp):
    """paintEvent 有齿配方：直调（绕开 PyQt C++ 边界吞没）不抛 + 窄宽省略。

    为何不用 render()：PyQt6 把 C++→Python 边界的异常打印后吞掉，pytest 见绿；
    直调 paintEvent 走纯 Python 栈，未修码时 AttributeError 正常传播 ⇒ 红。
    （配方真相登记于 AUDIT_20261020_p2b_d14fix_w_result.md §六。）
    """
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPaintEvent

    from acouscope.ui.widgets.statusbar_segments import ElidedLabel

    long = "文件: a-very-long-file-name-indeed.wav"
    lbl = ElidedLabel(long)
    lbl.resize(200, 24)
    # 直调触发 paintEvent 全路径（未修码时 option 死代码在此抛 ⇒ 红）
    lbl.paintEvent(QPaintEvent(QRect(0, 0, 200, 24)))
    # 窄宽省略（纯方法断言保留，与绘制直调互补）
    assert lbl.elided_for_width(40).endswith("…")
