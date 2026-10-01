# SPDX-License-Identifier: GPL-3.0-only
"""T-1093 M-A/M-D handle 与中央分隔条守卫测（全离屏，禁 MainWindow.show()）。

M-A 边缘三角 handle 拖拽释放后的悬停状态复位：

缺陷（B-1 残影·状态侧）：`_ToggleHandle` 的 `_hover` 只由 enter/leave 驱动；
拖拽期 handle 持隐式 grab ⇒ 光标移出时 leaveEvent 被抑制，`mouseReleaseEvent`
旧实现只清 `_dragged` 不清 `_hover/_cursor_y` → 释放后 `_hover` 卡真 +
`_cursor_y` 陈旧，每次 repaint 仍在钳底位主动重画抓手 = 残影
（T-1079 ③ 只修了 backing-store 清底，未修状态残留）。

口径（PI-T84 N-5）：真实隐式 grab 拖拽释放瞬间 `underMouse` 仍为 True ⇒
守卫测须**测侧注入 `underMouse()->False`** 建模「光标已离开」，并同时保留
`underMouse()->True` 分支（防把守卫写成永真分支）。
「残影是否消失」的视觉终判归 N5（真机）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PyQt6.QtGui import QColor, QEnterEvent, QImage, QMouseEvent, QPainter, QPixmap

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSplitterHandle, QWidget

from acouscope.app.controller import AppController
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.panels.workspace import (
    build_workspace_splitter,
    restore_workspace,
)

# ----------------------------------------------------------------------
# 夹具与事件仿真（不构造 MainWindow；host 为极小 QWidget，非主窗顶层）
# ----------------------------------------------------------------------


@pytest.fixture
def shown(qapp, tmp_path):
    """裸三栏 workspace + show 的极小 host（激活 handle 几何）。"""
    state = build_workspace_splitter(QLabel("center"))
    state["left"].set_content(QLabel("L" * 60))
    state["right"].set_content(QLabel("R" * 60))
    restore_workspace(state, path=tmp_path / "missing.json")

    host = QWidget()
    host.resize(1300, 600)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(state["splitter"])
    host.show()
    qapp.processEvents()
    state["host"] = host
    yield state
    host.close()


def _right_handle(ws):
    """右分界 handle（中央栏 ↔ 右栏），由 workspace 自绘且可见。"""
    sp = ws["splitter"]
    for h in sp.findChildren(QSplitterHandle):
        if h.isVisible() and sp.panel_for_handle(h) is ws["right"]:
            return h
    raise AssertionError("未找到右分界 handle")


def _enter(handle, y):
    QCoreApplication.sendEvent(
        handle, QEnterEvent(QPointF(5, y), QPointF(5, y), QPointF(5, y))
    )


def _mouse(handle, etype, y, button=Qt.MouseButton.LeftButton):
    g = handle.mapToGlobal(QPointF(5, y))
    QCoreApplication.sendEvent(
        handle,
        QMouseEvent(
            etype, QPointF(5.0, float(y)), QPointF(float(g.x()), float(g.y())),
            button, button, Qt.KeyboardModifier.NoModifier,
        ),
    )


def _drag_then_release(handle, y_press=30, y_release=120, *, cursor_left):
    """仿真「悬停 → 按下 → 拖动 → 释放」，释放时按 cursor_left 建模光标是否离开。

    ★ PI-T84 N-5：离屏合成链下真实 underMouse 恒 True ⇒ 测侧 patch 实例方法。
    """
    _enter(handle, y_press)
    _mouse(handle, QEvent.Type.MouseButtonPress, y_press)
    _mouse(handle, QEvent.Type.MouseMove, y_release)
    handle.underMouse = lambda: not cursor_left
    _mouse(handle, QEvent.Type.MouseButtonRelease, y_release)
    QCoreApplication.processEvents()


def _render(handle) -> QImage:
    pm = QPixmap(handle.size())
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    handle.render(painter)
    painter.end()
    return pm.toImage()


def _count_color(img: QImage, hexcolor: str) -> int:
    target = QColor(hexcolor).rgb()
    return sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if QColor(img.pixel(x, y)).rgb() == target
    )


# ----------------------------------------------------------------------
# ① 光标已离开时释放 → 悬停态复位（B-1 状态侧修复本体）
# ----------------------------------------------------------------------


def test_release_after_drag_outside_handle_resets_hover_state(shown):
    h = _right_handle(shown)
    _drag_then_release(h, cursor_left=True)

    assert h._press_pos is None
    assert h._dragged is False
    assert h._hover is False, "释放后 _hover 卡真 = 残影状态源未清"
    assert h._cursor_y is None, "_cursor_y 陈旧未复位"


def test_hover_without_drag_renders_grip(shown):
    """像素正对照：纯悬停（未拖拽）在光标位画出抓手——防「计数恒 0」使断言空心。"""
    cc = theme.colors()
    h = _right_handle(shown)
    y = int(h.height() * 0.75)

    _enter(h, 10)
    _mouse(h, QEvent.Type.MouseMove, y, button=Qt.MouseButton.NoButton)
    QCoreApplication.processEvents()
    assert _count_color(_render(h), cc["sub"]) > 0, "悬停态应画出抓手（对照失效）"


def test_release_outside_handle_renders_no_grip_pixels(shown):
    """复位须落到像素：拖拽后在光标已离开的情况下释放，整帧无 sub 级描边像素。"""
    cc = theme.colors()
    h = _right_handle(shown)
    y_release = int(h.height() * 0.75)

    _drag_then_release(h, y_release=y_release, cursor_left=True)
    assert _count_color(_render(h), cc["sub"]) == 0, "离开态释放后仍绘抓手 = 残影"



# ----------------------------------------------------------------------
# ② 光标仍在 handle 上时释放 → 悬停态保持（守卫非永真分支）
# ----------------------------------------------------------------------


def test_release_while_cursor_still_inside_keeps_hover(shown):
    h = _right_handle(shown)
    _drag_then_release(h, y_release=120, cursor_left=False)

    assert h._press_pos is None
    assert h._dragged is False
    assert h._hover is True, "光标未离开即复位 = 抓手误灭（守卫写成永真分支）"
    assert h._cursor_y == 120


# ----------------------------------------------------------------------
# ③ 反证：还原旧 release 逻辑（只清 _dragged）→ _hover 卡真 + 像素残留
# ----------------------------------------------------------------------


def test_counter_evidence_legacy_release_leaves_hover_stuck(shown, monkeypatch):
    from acouscope.ui.widgets.panels import workspace as workspace_mod

    def legacy_release(self, event):  # 修复前本体（T-1079 ③ 后状态残留原样）
        self._press_pos = None
        self._dragged = False
        QSplitterHandle.mouseReleaseEvent(self, event)

    monkeypatch.setattr(workspace_mod._ToggleHandle, "mouseReleaseEvent", legacy_release)

    cc = theme.colors()
    h = _right_handle(shown)
    y_release = int(h.height() * 0.75)
    _drag_then_release(h, y_release=y_release, cursor_left=True)

    assert h._hover is True, "旧码竟已复位 ⇒ 本反证失去判别力"
    assert h._cursor_y == y_release
    assert _count_color(_render(h), cc["sub"]) > 0, "旧码离开态应仍在陈旧位重画抓手"


# ----------------------------------------------------------------------
# ④ 正常悬停出入（无拖拽）语义不回退：enter 亮 / leave 灭
# ----------------------------------------------------------------------


def test_plain_enter_leave_still_toggles_hover(shown):
    h = _right_handle(shown)
    _enter(h, 40)
    assert h._hover is True
    QCoreApplication.sendEvent(h, QEvent(QEvent.Type.Leave))
    QCoreApplication.processEvents()
    assert h._hover is False


# ======================================================================
# M-D：中央垂直 splitter handle 走**局部 QSS**（不碰 theme 全局色值·§十二 R-1）
# ★ PI-T84 N-7：QSS 设在 handle 自身无效，落点＝splitter 本体 + objectName 选择器；
#   色值经 theme.colors() 运行时插值（禁 hex 字面量）。色带观感归 N5（真机）。
# ======================================================================


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    """离屏 MainWindow（构造重 ⇒ 模块级复用；禁 show）+ 数据目录隔离。"""
    import os

    from acouscope.i18n import set_language
    import acouscope.utils.config as _cfg

    tmp = tmp_path_factory.mktemp("t1093a")
    old_home = os.environ.get("HOME")
    old_data_dir = _cfg.get_data_dir
    os.environ["HOME"] = str(tmp)
    _cfg.get_data_dir = lambda: tmp
    set_language("zh_CN")

    controller = AppController()
    sr = 8000
    t = np.arange(sr) / sr
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()
    _cfg.get_data_dir = old_data_dir
    if old_home is not None:
        os.environ["HOME"] = old_home


def _vsplitter(window):
    """index0 常规页内的中央垂直 splitter（M-D 落点）。"""
    from PyQt6.QtWidgets import QSplitter

    sp = window.central_stack.widget(0)
    assert isinstance(sp, QSplitter) and sp.orientation() == Qt.Orientation.Vertical
    return sp


def _handle_pixel(widget, x=None, y=None):
    """把 handle 自身渲染到 pixmap 并取一点生效底色（离屏可判）。"""
    widget.ensurePolished()
    wdt, hgt = max(1, widget.width()), max(1, widget.height())
    pm = QPixmap(wdt, hgt)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    widget.render(painter)
    painter.end()
    img = pm.toImage()
    return img.pixelColor(x if x is not None else wdt // 2,
                         y if y is not None else hgt // 2).name()


@pytest.fixture
def global_handle_qss(qapp):
    """装上生产侧那一条全局 `QSplitter::handle` 色值规则（复刻 theme._qss），用完还原。"""
    old = qapp.styleSheet()
    border = theme.colors()["border"]
    qapp.setStyleSheet(f"QSplitter::handle {{ background: {border}; }}")
    qapp.processEvents()
    yield border
    qapp.setStyleSheet(old)
    qapp.processEvents()


def _plain_splitter(qss_for=None, qss_on_handle=False, object_name=""):
    """独立等宽 splitter（几何可控），按指定方式挂/不挂 QSS。"""
    from PyQt6.QtWidgets import QLabel, QSplitter

    sp = QSplitter()
    sp.setHandleWidth(6)
    sp.addWidget(QLabel("a"))
    sp.addWidget(QLabel("b"))
    sp.resize(200, 100)
    if qss_for:
        if qss_on_handle:
            sp.setObjectName(object_name)
            sp.handle(1).setStyleSheet(qss_for)
        else:
            sp.setObjectName(object_name)
            sp.setStyleSheet(qss_for)
    return sp


# ----------------------------------------------------------------------
# ① 局部 QSS 落地：本体 + objectName 选择器，色值来自 theme 运行时插值
# ----------------------------------------------------------------------


def test_central_vsplitter_carries_objectname_scoped_local_qss(window):
    sp = _vsplitter(window)
    c = theme.colors()
    assert sp.objectName() == "centralVerticalSplitter"
    css = sp.styleSheet()
    assert css, "中央垂直 splitter 未挂局部 QSS（M-D 未落地）"
    assert "::handle" in css and "background" in css, f"局部 QSS 缺 handle 底色规则: {css}"
    assert f"#{sp.objectName()}::handle" in css, (
        f"局部 QSS 未按 objectName 限定（会污染全局所有 splitter）: {css}"
    )
    assert c["border_strong"] in css, (
        f"色值未经 theme.colors() 插值: {css}（当前主题 border_strong={c['border_strong']}）"
    )
    assert sp.handle(1).styleSheet() == "", "QSS 设在 handle 自身（N-7 判定无效落点）"


def test_local_qss_is_registered_as_theme_derived_builder(window):
    """色值非冻结字面量：动态样式 builder 按传入配色求值（换主题即重插值）。

    ★ 不打真 `apply_theme`——它会装上 app 级全局 QSS 并改度量，泄漏到同进程
    其余测试（离屏实测：图表设计器页自然 min 高 578→594）。此处直接求值已注册
    的 builder，副作用为零。
    """
    from acouscope.ui import theme as theme_mod

    sp = _vsplitter(window)
    builders = [b for (ref, b) in theme_mod._dynamic if ref() is sp]
    assert builders, "中央垂直 splitter 未注册 style_when_theme 动态样式"
    seen = set()
    for theme_id in ("light", "dark", "ocean"):
        palette = dict(theme_mod.THEMES[theme_id])
        css = builders[-1](palette)
        assert palette["border_strong"] in css, (
            f"{theme_id} 配色下 builder 未插值 border_strong: {css}"
        )
        seen.add(css)
    assert len(seen) >= 2, f"builder 输出与主题无关（色值被冻结）: {seen}"


# ----------------------------------------------------------------------
# ② 优先级生效（像素）：局部压过全局，且不改全局色值
# ----------------------------------------------------------------------


def test_local_qss_wins_over_global_handle_color(window, global_handle_qss, qapp):
    c = theme.colors()
    h = _vsplitter(window).handle(1)
    h.resize(640, 6)
    qapp.processEvents()
    px = _handle_pixel(h)
    assert px == QColor(c["border_strong"]).name().lower(), (
        f"handle 渲染色 {px} ≠ 局部 QSS 声明色 {c['border_strong']}"
    )
    assert px != QColor(global_handle_qss).name().lower(), "局部 QSS 未覆盖全局 handle 色"


def test_global_theme_handle_rule_untouched(global_handle_qss):
    """R-1：theme 的全局 `QSplitter::handle` 色值仍为 border（本任务零改动）。"""
    import re

    from acouscope.ui.theme import _qss

    sheet = _qss(theme.colors())
    m = re.search(r"QSplitter::handle\s*\{\s*background:\s*(#[0-9A-Fa-f]{3,8})\s*;", sheet)
    assert m, "全局 QSS 已无 `QSplitter::handle` 底色规则（R-1 面被改动？）"
    assert m.group(1).lower() == theme.colors()["border"].lower(), (
        f"全局 handle 色值被改动: {m.group(1)} != border"
    )


def test_counter_evidence_qss_on_handle_self_is_ignored(global_handle_qss, window, qapp):
    """反证：把同一条规则从 splitter 本体移到 handle 自身 → 渲染色回落到全局色。"""
    c = theme.colors()
    rule = _vsplitter(window).styleSheet()
    sp = _plain_splitter(
        qss_for=rule, qss_on_handle=True, object_name="centralVerticalSplitter"
    )
    qapp.processEvents()
    px_on_handle = _handle_pixel(sp.handle(1), x=3, y=2)
    assert px_on_handle == QColor(global_handle_qss).name().lower(), (
        f"QSS 设在 handle 自身竟生效（{px_on_handle}）⇒ N-7 落点判定失真"
    )
    # 对照：同一规则挂在 splitter 本体 ⇒ 压过全局
    sp2 = _plain_splitter(qss_for=rule, object_name="centralVerticalSplitter")
    qapp.processEvents()
    assert _handle_pixel(sp2.handle(1), x=3, y=2) == QColor(c["border_strong"]).name().lower()
