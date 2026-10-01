# SPDX-License-Identifier: GPL-3.0-only
"""T-1012 侧栏折叠/展开几何 + 分隔框线（handle 位）交互测试。

覆盖验收（离屏；本文件不构造主窗口，仅可显示极小 host QWidget 以激活
QSplitter handle——挂起黑名单铁律只禁主窗口顶层显示）：
  ① 面板无标题栏横条（panelContainer/workspace 层结构断言）；
  ② 左栏默认收起（无布局记录）/ 右栏默认展开；
  ③ 折叠 → 面板宽度 0（sizes[0]==0 / width()==0）、内容隐藏；
     展开 → 宽度=内容自适应（[220,520] clamp 区间）、内容可见；
  ④ 分隔框线（QSplitter handle）交互：拖拽=改宽（基类）、双击=toggle、
     单击=无动作（T-1056 双击收放改造）；
  ⑤ 用户手动拖拽（splitterMoved）后手动宽度优先于内容自适应；
  ⑥ T-1056 抓手几何：默认态无抓手、缩放不变性（直接杀死通高楔形缺陷）、
     跟随光标、边界 clamp、手柄宽 24；
  ⑦ 静态纪律（禁词/hex 颜色/主窗顶层显示禁用——扫本文件与源码）。
"""

import pathlib

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QEnterEvent, QImage, QMouseEvent, QPixmap, QPainter, QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSplitterHandle, QWidget

from acouscope.ui import theme
from acouscope.ui.widgets.panels import PanelContainer
from acouscope.ui.widgets.panels.workspace import (
    build_workspace_splitter,
    fit_panel_width,
    restore_workspace,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "acouscope"


# ----------------------------------------------------------------------
# workspace 层夹具（不构造 MainWindow）
# ----------------------------------------------------------------------


@pytest.fixture
def ws(qapp, tmp_path):
    """裸三栏 workspace：左右栏带文本内容；no-file restore（默认左收起）。"""
    state = build_workspace_splitter(QLabel("center"))
    left = state["left"]; right = state["right"]
    # 长文本使内容 preferred 宽落在 [220, 520] 之间（clamp 内可感知自适应）
    left.set_content(QLabel("L" * 60))
    right.set_content(QLabel("R" * 60))
    restore_workspace(state, path=tmp_path / "missing.json")
    return state


def _refresh(qapp):
    qapp.processEvents()


# ----------------------------------------------------------------------
# ① 无标题栏 / 默认态
# ----------------------------------------------------------------------


def test_panels_have_no_header_bar(ws):
    for panel in (ws["left"], ws["right"]):
        assert isinstance(panel, PanelContainer)
        assert not hasattr(panel, "panelHeader")
        assert not hasattr(panel, "lblTitle")
        assert not hasattr(panel, "btnCollapse")


def test_default_left_collapsed_right_expanded(ws):
    assert ws["left"].is_collapsed()
    assert not ws["right"].is_collapsed()
    assert ws["splitter"].sizes()[0] == 0
    assert ws["splitter"].sizes()[2] > 0


# ----------------------------------------------------------------------
# ③ 折叠宽度 0 / 展开自适应
# ----------------------------------------------------------------------


def test_collapse_zero_width_and_auto_expand(qapp, ws):
    sp = ws["splitter"]; left = ws["left"]
    _refresh(qapp)
    assert left.is_collapsed()
    assert left.width() == 0

    left.set_collapsed(False)  # → workspace._expand_slot 自适应
    _refresh(qapp)
    assert not left.is_collapsed()
    assert left.panelContent.isVisible()
    w = left.width()
    assert 220 <= w <= 520, f"自适应宽度越界: {w}"

    left.set_collapsed(True)
    _refresh(qapp)
    assert left.is_collapsed()
    assert left.width() == 0
    assert not left.panelContent.isVisible()


# ----------------------------------------------------------------------
# ④ 分隔框线 handle 交互：拖拽=改宽（基类）/ 双击=toggle / 单击=无（T-1056）
# ----------------------------------------------------------------------


@pytest.fixture
def shown(qapp, tmp_path):
    """host.show() 激活 QSplitter handle（极小 QWidget，非 MainWindow）。"""
    state = build_workspace_splitter(QLabel("center"))
    left = state["left"]; right = state["right"]
    left.set_content(QLabel("L" * 60))
    right.set_content(QLabel("R" * 60))
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


def _boundary_handle(ws, panel) -> "object":
    """该面板与中间栏之间的分界 handle（可见、由本 workspace 自绘）。"""
    sp = ws["splitter"]
    for h in sp.findChildren(QSplitterHandle):
        if h.isVisible() and sp.panel_for_handle(h) is panel:
            return h
    raise AssertionError("未找到边缘三角 handle")


def test_edge_handle_double_click_toggles(qapp, shown):
    ws = shown
    sp = ws["splitter"]; left = ws["left"]; right = ws["right"]

    # 左栏默认收起 → 双击左分界 handle 展开
    assert left.is_collapsed()
    h0 = _boundary_handle(ws, left)
    QTest.mouseDClick(h0, Qt.MouseButton.LeftButton, pos=h0.rect().center())
    _refresh(qapp)
    assert not left.is_collapsed()

    # 再次双击 → 折叠为 0 宽（几何断言：sizes[0]==0 且 width()==0）
    QTest.mouseDClick(h0, Qt.MouseButton.LeftButton, pos=h0.rect().center())
    _refresh(qapp)
    assert left.is_collapsed()
    assert left.width() == 0

    # 右栏默认展开 → 双击右分界 handle 折叠，再双击展开
    assert not right.is_collapsed()
    h1 = _boundary_handle(ws, right)
    QTest.mouseDClick(h1, Qt.MouseButton.LeftButton, pos=h1.rect().center())
    _refresh(qapp)
    assert right.is_collapsed()
    QTest.mouseDClick(h1, Qt.MouseButton.LeftButton, pos=h1.rect().center())
    _refresh(qapp)
    assert not right.is_collapsed()


def test_single_click_does_not_toggle(qapp, shown):
    """T-1056 R4：单击 = 无动作，折叠态必须不变。"""
    ws = shown
    sp = ws["splitter"]; left = ws["left"]; right = ws["right"]
    left_collapsed = left.is_collapsed()
    right_collapsed = right.is_collapsed()
    QTest.mouseClick(_boundary_handle(ws, left), Qt.MouseButton.LeftButton,
                     pos=_boundary_handle(ws, left).rect().center())
    QTest.mouseClick(_boundary_handle(ws, right), Qt.MouseButton.LeftButton,
                     pos=_boundary_handle(ws, right).rect().center())
    _refresh(qapp)
    assert left.is_collapsed() == left_collapsed
    assert right.is_collapsed() == right_collapsed


# ----------------------------------------------------------------------
# ⑤ 手动拖拽宽度优先于内容自适应
# ----------------------------------------------------------------------


def test_manual_width_beats_auto_fit(qapp, ws):
    sp = ws["splitter"]; left = ws["left"]
    left.set_collapsed(False)
    _refresh(qapp)

    # 模拟用户拖拽：resize 基准宽后 setSizes 定宽，再发 splitterMoved（index 0）
    # 记录实际生效的手动宽度（避免绝对像素：以生效实测为准）
    manual, center = 360, 700
    right = sp.sizes()[2]
    hw = sp.handleWidth()
    sp.resize(manual + center + right + 2 * hw, 500)
    sp.setSizes([manual, center, right])
    _refresh(qapp)
    manual_now = sp.sizes()[0]
    sp.splitterMoved.emit(manual_now, 0)
    _refresh(qapp)
    assert left._manual_width == manual_now

    # 内容切换触发的自适应不得覆盖手动宽度
    before = sp.sizes()[0]
    fit_panel_width(left)
    _refresh(qapp)
    assert sp.sizes()[0] == before


# ----------------------------------------------------------------------
# ⑥ 静态纪律
# ----------------------------------------------------------------------


def test_sidebar_static_discipline():
    import re

    for name in ("panel_container", "workspace", "main_window"):
        src = pathlib.Path(_SRC / "ui" / "widgets" / "panels" / f"{name}.py")
        if not src.exists():
            src = pathlib.Path(_SRC / "ui" / f"{name}.py")
        text = src.read_text(encoding="utf-8")
        assert "btn_toggle_ribbon" not in text, f"{name} 残留旧开关符号"
        # 禁词 0（品牌词禁止；拼接避免字面量自身命中）
        assert ("Melod" + "yne") not in text
        # 禁硬编码 hex 颜色字面量（theme 键名允许；禁 #rgb/#rrggbb）
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", text), f"{name} 含硬编码 hex"
    # 本任务改动文件（panel_container/workspace）禁新建 QDialog；
    # main_window 既有「关于」模态为 CB-010 用户特批例外，不作全局断言
    for name in ("panel_container", "workspace"):
        text = pathlib.Path(_SRC / "ui" / "widgets" / "panels" / f"{name}.py").read_text(
            encoding="utf-8"
        )
        assert ("Q" + "Dialog") not in text, f"{name} 含 QDialog"
    # 本文件禁用主窗口顶层 show 调用（拼接检查防自命中）
    this = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert ("MainWindow" + ".show()") not in this


# ----------------------------------------------------------------------
# ⑥ T-1056 抓手几何（像素渲染断言：默认态无抓手 / 缩放不变 / 跟光标 / clamp）
# 断言仅基于「渲染出的像素」，与 drawing 内部实现细节解耦。
# ----------------------------------------------------------------------


def _make_shown(qapp, tmp_path, width=1300, height=600):
    """按指定大小构造并 show 三栏 workspace，返回 state 字典。"""
    state = build_workspace_splitter(QLabel("center"))
    left = state["left"]; right = state["right"]
    left.set_content(QLabel("L" * 60))
    right.set_content(QLabel("R" * 60))
    restore_workspace(state, path=tmp_path / "missing.json")
    host = QWidget()
    host.resize(width, height)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(state["splitter"])
    host.show()
    qapp.processEvents()
    state["host"] = host
    return state


def _render(widget):
    """把控件独立渲染到透明底 pixmap（仅含控件自身绘制，不含父背景）。"""
    pm = QPixmap(widget.size())
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    widget.render(painter)
    painter.end()
    return pm


def _bbox_of_color(pm, hexcolor):
    """pixmap 中恰为该色（忽略 alpha）像素的 (x0, y0, x1, y1)；无则 None。"""
    target = QColor(hexcolor).rgb()
    img = pm.toImage()
    xs = []; ys = []
    for y in range(img.height()):
        for x in range(img.width()):
            if QColor(img.pixel(x, y)).rgb() == target:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _leave(widget):
    """显式离开 handle（复位 _hover），用于默认态断言免受离屏光标残留影响。"""
    QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))
    QCoreApplication.processEvents()


def _hover(widget, y):
    """穿越真实的 enter + mouseMove 事件处理链，把光标置于 widget 内 (x, y)。"""
    enter = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
    QCoreApplication.sendEvent(widget, enter)
    g = widget.mapToGlobal(widget.rect().center())
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(widget.width() / 2.0, y),
        QPointF(g.x(), g.y()),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QCoreApplication.sendEvent(widget, move)
    QCoreApplication.processEvents()


def test_handle_width_24(qapp, shown):
    """§6.1-5：手柄加宽到 24px（R7）。"""
    assert shown["splitter"].handleWidth() == 24


def test_default_state_no_grip(qapp, shown):
    """§6.1-1：默认（未悬停）只画 1px 居中竖线，手柄内无 sub 级着色。"""
    cc = theme.colors()
    for panel in (shown["left"], shown["right"]):
        h0 = _boundary_handle(shown, panel)
        _leave(h0)  # 归位：默认态（未悬停），免受离屏光标残留影响
        assert _bbox_of_color(_render(h0), cc["sub"]) is None


def test_grip_scale_invariant(qapp, tmp_path):
    """§6.1-2：悬停抓手包围盒高随 H 不变（直接杀死通高楔形缺陷）。"""
    cc = theme.colors()
    heights = []
    for H in (400, 800):
        ws = _make_shown(qapp, tmp_path, 1300, H)
        h0 = _boundary_handle(ws, ws["left"])
        _hover(h0, h0.height() // 2)
        bbox = _bbox_of_color(_render(h0), cc["sub"])
        assert bbox is not None, "悬停态应绘出抓手"
        heights.append(bbox[3] - bbox[1] + 1)
    assert heights[0] == heights[1], f"抓手高度随手柄高变化: {heights}"
    assert heights[0] <= 16, f"抓手高度超标: {heights[0]}"


def test_grip_follows_cursor(qapp, tmp_path):
    """§6.1-3：抓手随光标 Y 移动，且以 1px 竖线为对称轴。"""
    cc = theme.colors()
    ws = _make_shown(qapp, tmp_path, 1300, 600)
    h0 = _boundary_handle(ws, ws["left"])
    h = h0.height()
    cx = h0.width() / 2.0
    for frac in (0.3, 0.7):
        target = frac * h
        _hover(h0, target)
        bbox = _bbox_of_color(_render(h0), cc["sub"])
        assert bbox is not None
        cy = (bbox[1] + bbox[3]) / 2.0
        assert abs(cy - target) <= 3, (frac, cy, target)
        xc = (bbox[0] + bbox[2]) / 2.0
        assert abs(xc - cx) <= 1.0, (frac, xc, cx)


def test_grip_clamped_stays_in_handle(qapp, tmp_path):
    """§6.1-4：悬停到上下边缘后，抓整体仍在 handle 矩形内（不裁切/不越界）。"""
    cc = theme.colors()
    ws = _make_shown(qapp, tmp_path, 1300, 600)
    h0 = _boundary_handle(ws, ws["left"])
    rect = h0.rect()
    for y in (1, h0.height() - 1):
        _hover(h0, y)
        bbox = _bbox_of_color(_render(h0), cc["sub"])
        assert bbox is not None
        assert bbox[0] >= rect.left() and bbox[2] <= rect.right()
        assert bbox[1] >= rect.top() and bbox[3] <= rect.bottom()


# ----------------------------------------------------------------------
# ⑧ T-1079 ③：handle 清底去残影
# 事件驱动重绘时 Qt 不为该 handle 清背景（无 autoFillBackground/WA_StyledBackground，
# 实测离屏 render() 却会画窗底、遮蔽缺陷），故残影守卫必须**仿真 backing store 语义**：
# 共享 pixmap 当 backing store + 代理 QPainter 注入脏区 clip，直接驱动 paintEvent 本体。
# 旧码（不清底）在此判据下必红；新码 paintEvent 起始 fillRect 铺满 → 旧位描边被抹平。
# ----------------------------------------------------------------------


def _count_color(img, hexcolor, y0, y1):
    target = QColor(hexcolor).rgb()
    return sum(1 for y in range(max(0, y0), min(img.height(), y1))
               for x in range(img.width()) if img.pixel(x, y) == target)


def test_grip_partial_repaint_no_ghost(qapp, tmp_path, monkeypatch):
    """§6.1-6（T-1079 ③）：只重绘旧悬停位脏区后，该带内不得残留旧描边像素（残影）。"""
    from acouscope.ui.widgets.panels import workspace as workspace_mod

    cc = theme.colors()
    ws = _make_shown(qapp, tmp_path, 1300, 600)
    h0 = _boundary_handle(ws, ws["left"])

    pm = QPixmap(h0.size())
    pm.fill(QColor(cc["bg0"]))
    real_qp = QPainter
    clips = []

    def proxy(widget=None, *a, **k):
        p = real_qp(pm)
        if clips:
            p.setClipRect(clips[-1])
        return p

    proxy.RenderHint = real_qp.RenderHint
    monkeypatch.setattr(workspace_mod, "QPainter", proxy)

    y1, y2 = int(h0.height() * 0.25), int(h0.height() * 0.75)
    h0._hover, h0._dragged = True, False
    h0._cursor_y = y1
    clips.append(h0.rect())
    h0.paintEvent(None)
    assert _count_color(pm.toImage(), cc["sub"], y1 - 12, y1 + 13) > 0, \
        "前置：y1 悬停应画出抓手"

    h0._cursor_y = y2
    clips.append(QRect(0, y1 - 10, h0.width(), 20))  # Qt 只把旧位带标脏
    h0.paintEvent(None)
    assert _count_color(pm.toImage(), cc["sub"], y1 - 10, y1 + 11) == 0, \
        "旧悬停位描边像素残留 = 残影（paintEvent 未清底）"


def test_grip_move_full_frame_clean_and_evidence(qapp, tmp_path):
    """§6.1-7（T-1079 ③）：悬停位 y1→y2 整帧重绘后 y1 带无描边残留；出前后帧自证图。"""
    cc = theme.colors()
    ws = _make_shown(qapp, tmp_path, 1300, 600)
    h0 = _boundary_handle(ws, ws["left"])
    h = h0.height()

    _hover(h0, int(h * 0.25))
    img_a = _render(h0).toImage()
    assert _count_color(img_a, cc["sub"], int(h * 0.25) - 12, int(h * 0.25) + 13) > 0, \
        "前置：y1 悬停应画出抓手"
    _hover(h0, int(h * 0.75))
    img_b = _render(h0).toImage()
    assert _count_color(img_b, cc["sub"], int(h * 0.25) - 12, int(h * 0.25) + 13) == 0, \
        "y1 旧位抓手像素残留（残影）"
    assert _count_color(img_b, cc["sub"], int(h * 0.75) - 12, int(h * 0.75) + 13) > 0

    # 自证图：同 handle 悬停 y1 / y2 两帧并排（幕僚目测复核用）
    gap = 8
    canvas = QImage(img_a.width() * 2 + gap, img_a.height(), QImage.Format.Format_RGB32)
    canvas.fill(QColor(cc["bg3"]))
    cp = QPainter(canvas)
    cp.drawImage(0, 0, img_a)
    cp.drawImage(img_a.width() + gap, 0, img_b)
    cp.end()
    assert canvas.save("/tmp/pi_t1079_handle.png")
