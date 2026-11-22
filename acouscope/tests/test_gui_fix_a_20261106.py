# SPDX-License-Identifier: GPL-3.0-only
"""A 分面 GUI 呈现层修复回归（A1 设置导航 / A2 AI 窄栏 / A3 赞助节流）。

全部离屏（conftest 已设 QT_QPA_PLATFORM=offscreen）：不构造 MainWindow、
不跑事件循环、不 exec 模态框。判据逐条对应：

- A1：设置导航 6 项显式图标尺寸 ≤24、逐项行高 ≥28 且相邻不重叠、最小宽
  含图标宽、内容超高/超宽允许滚动；
- A2：AI 右栏默认 300 宽下长文本标签 wordWrap + tooltip 全文、按钮/下拉
  不撑出容器、``_layout_top_row(300)`` 进两行、动作钮保留 sizeHint；
- A3：赞助「继续使用」节流 5 次启动、永久停弹语义不变、阈值常量 5 不变、
  旧 app_state.json 缺键 / 非整数兼容。
"""

from __future__ import annotations

import json
import pathlib

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QComboBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

import acouscope.state as _state  # noqa: E402
from acouscope.ui.widgets.ai_interpret import (  # noqa: E402
    AIInterpretDialog,
    _KEEP_SIZE_HINT,
)
from acouscope.ui.widgets.settings_dialog import SettingsDialog  # noqa: E402
from acouscope.ui.widgets.sponsor_dialog import SponsorDialog  # noqa: E402


# ---------------------------------------------------------------------------
# A1：设置导航（图标 / 行高 / 最小宽 / 滚动）
# ---------------------------------------------------------------------------


def test_a1_settings_nav_icon_and_row_geometry(qapp):
    """6 项图标显式 ≤24、行高 ≥28 且相邻 rect 不重叠、最小宽含图标宽。"""
    dlg = SettingsDialog()
    try:
        nav = dlg.nav_list
        dlg.resize(560, 640)
        dlg.show()
        qapp.processEvents()

        assert nav.count() == 6
        # 显式 setIconSize（默认 -1 会让图标与文字互压、行距塌为 0）
        assert 0 < nav.iconSize().width() <= 24

        rects = [nav.visualItemRect(nav.item(i)) for i in range(nav.count())]
        assert all(r.height() >= 28 for r in rects), [
            r.height() for r in rects
        ]
        assert all(
            rects[i].bottom() < rects[i + 1].top()
            for i in range(len(rects) - 1)
        ), "相邻导航项 visualItemRect 重叠"

        need = (nav.sizeHintForColumn(0) + nav.iconSize().width()
                + 2 * nav.frameWidth())
        assert nav.minimumWidth() >= need

        # 导航列内容超高/超宽允许滚动，不得裁切
        assert nav.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert nav.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

        # 既有两栏约束不回归：文本不被省略、导航列显著窄于内容区
        assert nav.sizeHintForColumn(0) <= nav.viewport().width()
        assert nav.viewport().width() < dlg.stack.width()
    finally:
        dlg.close()
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# A2：AI 窄栏（长文本 / 越界 / 两行 / 动作钮 sizeHint）
# ---------------------------------------------------------------------------


def test_a2_ai_narrow_column_no_clip(qapp):
    """宿主 300 宽：长文本不横向裁断、按钮/下拉不越界、顶部进两行。"""
    panel = AIInterpretDialog(lambda: None, lambda: "", lambda: "")
    host = QWidget()
    try:
        # 无布局宿主 + setGeometry：宿主定死 300，面板拿到真实窄宽
        # （有布局宿主会被子件 minimumSizeHint 撑宽，掩盖真机症状）
        panel.setParent(host)
        host.resize(300, 700)
        panel.setGeometry(0, 0, 300, 700)
        host.show()
        qapp.processEvents()
        panel._layout_top_row(300)
        qapp.processEvents()

        assert host.width() == 300
        assert panel.width() <= 300 + 8

        # 长文本标签：wordWrap 两行 + tooltip 全文（elide 兜底），不横向裁断
        for name in ("lbl_source", "lbl_model", "lbl_probe",
                     "msg_hint", "lbl_input_hint"):
            lab = getattr(panel, name)
            assert isinstance(lab, QLabel), name
            assert lab.wordWrap() is True, f"{name} 未开 wordWrap（横向裁断）"
            assert lab.toolTip(), f"{name} 缺 tooltip 全文"
            assert lab.text() in lab.toolTip(), f"{name} tooltip 未含全文"

        # 按钮 / 下拉不得撑出容器（只验可见且已布局者：隐藏页里的控件
        # geometry 仍是 Qt 默认 QRect(0,0,640,480)，不参与窄栏布局）
        visible = [
            w for w in panel.findChildren(QPushButton) + panel.findChildren(QComboBox)
            if w.isVisible() and w.width() > 0
        ]
        assert len(visible) >= 4, f"可见控件过少，判据空转: {len(visible)}"
        for w in visible:
            assert w.geometry().right() <= 300 + 8, (
                f"{w.objectName()} right={w.geometry().right()} 越界"
            )

        # 顶部行必须进入两行模式
        assert panel._top_two_row is True

        # _KEEP_SIZE_HINT 动作钮保留 sizeHint（不得被压成 Ignored / 0 宽）
        for name in _KEEP_SIZE_HINT:
            if not name.endswith("Btn"):
                continue
            btn = panel.findChild(QPushButton, name)
            assert btn is not None, name
            assert btn.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Ignored, (
                f"{name} 动作钮被压缩"
            )

        # 横向溢出根因：面板最小宽不再顶宿主（未修复时为 359）
        assert panel.minimumSizeHint().width() <= 300 + 8
    finally:
        panel.close()
        panel.setParent(None)
        host.close()
        host.deleteLater()


# ---------------------------------------------------------------------------
# A3：赞助节流（状态隔离）
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """把 app_state.json 钉到临时文件（缺键 / 损坏场景可控）。"""
    path = tmp_path / "app_state.json"
    monkeypatch.setattr(_state, "state_path", lambda: path)
    return path


def _write_state(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_a3_sponsor_snooze_lifecycle(qapp, isolated_state):
    """点「继续使用」节流 5 次；dismissed 永久停弹；阈值常量 5 不变。"""
    p = isolated_state
    # 旧状态（无 snooze 键）：launch_count=5 达标即弹，绝不抛
    _write_state(p, {"launch_count": 5, "sponsor_reminder_dismissed": False})
    assert _state.get_sponsor_snooze_until_launch() == 0
    assert _state.should_show_sponsor_reminder() is True

    dlg = SponsorDialog()
    try:
        dlg.show()
        assert dlg.isVisible()
        dlg.btn_continue.click()
        assert not dlg.isVisible()
    finally:
        dlg.close()
        dlg.deleteLater()

    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw.get("sponsor_snooze_until_launch") == 10  # 5 + 5
    assert _state.should_show_sponsor_reminder() is False  # 点击后节流

    for count, expected in ((9, False), (10, True), (11, True)):
        _write_state(p, {
            "launch_count": count,
            "sponsor_reminder_dismissed": False,
            "sponsor_snooze_until_launch": 10,
        })
        assert _state.should_show_sponsor_reminder() is expected, count

    # 「已支持，不再提醒」永久停弹语义不变
    for count in (5, 10, 99):
        _write_state(p, {
            "launch_count": count,
            "sponsor_reminder_dismissed": True,
            "sponsor_snooze_until_launch": 0,
        })
        assert _state.should_show_sponsor_reminder() is False, count

    assert _state.SPONSOR_PROMPT_LAUNCH_THRESHOLD == 5


def test_a3_snooze_function_and_legacy_compat(isolated_state):
    """snooze_sponsor_reminder(5) 落盘；旧文件缺键 / 非整数一律兼容不抛。"""
    p = isolated_state
    _write_state(p, {"launch_count": 5})
    assert _state.snooze_sponsor_reminder(5) is True
    assert _state.get_sponsor_snooze_until_launch() == 10
    assert _state.should_show_sponsor_reminder() is False

    # 缺 snooze 键：按 0，达标照弹
    _write_state(p, {"launch_count": 6})
    assert _state.get_sponsor_snooze_until_launch() == 0
    assert _state.should_show_sponsor_reminder() is True

    # 非整数 / 非法值：按 0，绝不抛
    for bad in ("abc", None, [], ""):
        _write_state(p, {"launch_count": 6,
                         "sponsor_snooze_until_launch": bad})
        assert _state.get_sponsor_snooze_until_launch() == 0
        assert _state.should_show_sponsor_reminder() is True
