# SPDX-License-Identifier: GPL-3.0-only
"""三面板工作区骨架（V099_WORKSPACE_V1 · T-1012 形态）。

水平 QSplitter 三栏：左 文件/设置 · 中 画布（现有垂直 splitter）· 右 检查器/AI。
T-1012 真机反馈修订（ARCH §六）：
- 面板无标题栏；折叠态面板宽度压到 **0**（内容隐藏 + maximumWidth 0），
  与相邻栏无缝贴合。
- **边缘三角 = handle 位**（实现选型）：左右栏与中间栏之间的分隔框线即
  QSplitter handle，本模块以 _ToggleSplitter/_ToggleHandle 在其上自绘极小三角
  （theme 语义色），单击切换折叠/展开、拖拽仍可调宽。选型理由：离屏实测
  (1) 子件放在 0 宽父级内会被裁剪不可见；(2) 直接向 QSplitter setParent 添加
  子件会被其视为新 pane（count()/sizes() 污染）——两路「面板外挂」均不可行。
- 展开宽度按内容 sizeHint 自适应（clamp [220, 520]）；用户手动拖拽后以用户
  值为准（_manual_width，持久化不变）。
- 左栏默认收起（restore 无记录时 collapsed=True）；右栏默认展开（检查器）。
- 布局状态（sizes + 折叠态）持久化到 get_data_dir()/"ui_layout.json"；
  save/restore 全程静默：布局读写永不影响应用（缺失/损坏/不可写均不抛）。
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSplitter, QSplitterHandle

from acouscope.ui import theme
from acouscope.ui.widgets.panels import PanelContainer
from acouscope.utils.config import get_data_dir

# 展开宽度自适应范围 / 中央画布最小保留宽（QWIDGETSIZE_MAX）
_AUTO_MIN_W = 220
_AUTO_MAX_W = 520
_MIN_CENTER_W = 60
_MAX_WIDTH = 16777215
# 分隔手柄（分界框线）宽度：容纳 20px 悬停抓手 + 两侧 2px 余量（T-1056 R7）
_HANDLE_WIDTH = 24
# 悬停抓手几何（固定像素，禁由句柄高度/宽度推导臂长或抬高——T-1056 §一/R3，根因修复）
_GRIP_TRI_W = 6.0    # 左右三角 ◁/▷ 宽 6px
_GRIP_TRI_H = 10.0   # 三角主边长 10px（对称于光标 Y）
_GRIP_GAP = 3.0      # 三角与竖杠间隙 3px
_GRIP_BAR_W = 2.0    # ‖ 竖杠宽 2px
_GRIP_BAR_H = 14.0   # ‖ 竖杠高 14px（圆角 1）
_GRIP_TOTAL_W = 20.0  # 总宽 = 6 + 3 + 2 + 3 + 6
_GRIP_CLAMP = 7       # 光标 Y clamp 上下边距（防抓被裁切/越界）
# 初始/恢复参考比例（左默认收起 0 / 中 / 右）；仅在无记录兜底时使用
_DEFAULT_SIZES = [0, 760, 300]
_DEFAULT_SIZES_TOTAL = sum(_DEFAULT_SIZES)
# 持久化文件名
_LAYOUT_FILENAME = "ui_layout.json"


def _default_layout_path() -> Path:
    return get_data_dir() / _LAYOUT_FILENAME


def _auto_width(panel: PanelContainer) -> int:
    """按当前内容 preferred 宽度估算展开宽度（clamp 到 [_AUTO_MIN_W, _AUTO_MAX_W]）。"""
    content = panel.panelContent
    hint = content.sizeHint().width()
    if hint <= 0:
        hint = content.minimumSizeHint().width()
    if hint <= 0:
        hint = _AUTO_MIN_W
    return int(min(_AUTO_MAX_W, max(_AUTO_MIN_W, hint)))


def _splitter_of(panel: PanelContainer):
    sp = panel.parentWidget()
    return sp if isinstance(sp, QSplitter) else None


def _update_handles(splitter) -> None:
    """折叠态变化后刷新 handle 上自绘三角的指向/颜色。"""
    try:
        for h in splitter.findChildren(_ToggleHandle):
            h.update()
    except Exception:  # noqa: BLE001 — 刷新永不抛
        pass


# ----------------------------------------------------------------------
# 边缘三角（handle 位）：QSplitter 分隔框线上的极小自绘三角钮
# ----------------------------------------------------------------------


class _ToggleHandle(QSplitterHandle):
    """分隔框线 handle：默认只画 1px 居中竖线；悬停时在光标 Y 处浮现描边式 ◁ ‖ ▷ 抓手。

    交互语义（T-1056）：
      拖拽 = 改栏宽（基类行为不变）；双击 = 切换该侧栏折叠/展开；单击 = 无动作。
    抓手几何用模块级常量（禁由句柄高度/宽度推导——§一/R3），颜色走 theme 语义色（禁 hex）。
    """

    def __init__(self, splitter):
        super().__init__(splitter.orientation(), splitter)
        self._press_pos = None
        self._dragged = False
        self._hover = False
        self._cursor_y: int | None = None
        # 关键：未按键时也要收到 mouseMoveEvent，抓手才能跟随光标（§五.2）
        self.setMouseTracking(True)

    # -- 交互：拖拽 = 改宽（基类）；双击 = 收放 ；单击 = 无 --
    def _clamp_y(self, y: float, h: int) -> float:
        """光标 Y clamp 到 [7, H-7]，保证抓整体不越出 handle（R2）。"""
        return float(max(_GRIP_CLAMP, min(int(h) - _GRIP_CLAMP, int(y))))

    def _grip_rect(self, y) -> "QRect":
        """抓手包围盒（含 line 余量；用于重绘最小化 update 限定，§五.3）。"""
        if y is None:
            return QRect()
        cy = self._clamp_y(float(y), self.height())
        x0 = (self.width() - _GRIP_TOTAL_W) / 2.0
        return QRect(
            int(x0), int(cy - _GRIP_BAR_H / 2.0),
            int(_GRIP_TOTAL_W), int(_GRIP_BAR_H),
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is not None:
            self._dragged = True
        new_y = int(event.position().y())
        # 重绘最小化：仅悬停且 Y 变化时 update(旧∪新包围盒)，禁整块重绘（§五.3）
        if self._hover and (self._cursor_y is None or new_y != self._cursor_y):
            old = self._grip_rect(self._cursor_y)
            self._cursor_y = new_y
            self.update(old.united(self._grip_rect(new_y)))
        else:
            self._cursor_y = new_y
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press_pos = None
        self._dragged = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            sp = self.splitter()
            if isinstance(sp, _ToggleSplitter):
                panel = sp.panel_for_handle(self)
                if panel is not None:
                    panel.toggle()
                    self.update()
                    event.accept()
        # 不调 super()：避免与 QSplitterHandle 内建「双击展开相邻件」叠加成两次动作（R5）

    # -- 自绘：1px 居中竖线 + 悬停抓手（描边） --
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme.colors()
        h = self.height()
        cx = self.width() / 2.0
        # R1：默认只画 1px 居中竖线（border）；未画线区域透明（露出 pane 底色）
        painter.setPen(QPen(QColor(c["border"]), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(cx, 0.0), QPointF(cx, float(h)))
        # R6：拖拽中隐藏抓手；R2：悬停时在光标 Y 处浮现（未收到 move 取中线 H/2）
        if self._hover and not self._dragged:
            cy = self._cursor_y if self._cursor_y is not None else h / 2.0
            self._draw_grip(painter, c, cx, self._clamp_y(cy, h))
        painter.end()

    def _draw_grip(self, painter, c, cx: float, cy: float) -> None:
        """描边式 ◁ ‖ ▷，以竖线为对称轴左右对称（总宽 20px，禁由高/宽推导）。"""
        pen = QPen(QColor(c["sub"]), 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)  # 只描边不填充（R9）
        x0 = cx - _GRIP_TOTAL_W / 2.0
        half = _GRIP_TRI_H / 2.0
        # 左三角 ◁：尖端在左，底边在右
        painter.drawPolygon(QPolygonF([
            QPointF(x0, cy),
            QPointF(x0 + _GRIP_TRI_W, cy - half),
            QPointF(x0 + _GRIP_TRI_W, cy + half),
        ]))
        # 右三角 ▷：尖端在右，底边在左
        rtip = x0 + _GRIP_TOTAL_W
        painter.drawPolygon(QPolygonF([
            QPointF(rtip, cy),
            QPointF(rtip - _GRIP_TRI_W, cy - half),
            QPointF(rtip - _GRIP_TRI_W, cy + half),
        ]))
        # 竖杠 ‖：2×14 圆角 1（标定元素居中于光标 Y）
        painter.drawRoundedRect(
            QRectF(cx - _GRIP_BAR_W / 2.0, cy - _GRIP_BAR_H / 2.0,
                   _GRIP_BAR_W, _GRIP_BAR_H),
            1.0, 1.0,
        )


class _ToggleSplitter(QSplitter):
    """三栏工作区水平 QSplitter：handle 承载边缘三角（见 _ToggleHandle）。"""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._side_panels: dict[int, PanelContainer] = {}

    def register_side(self, index: int, panel: PanelContainer) -> None:
        """登记 handle index 对应的侧栏面板（0=左栏，1=右栏）。"""
        self._side_panels[index] = panel

    def panel_for_handle(self, handle: QSplitterHandle):
        """按 handle 几何（相对 splitter）判断其对应哪一侧栏面板。"""
        sizes = self.sizes()
        if len(sizes) != 3:
            return None
        hw = self.handleWidth()
        cx = handle.x() + handle.width() / 2.0
        # handle0 区间中心 ≈ sizes[0]+hw/2；handle1 ≈ sizes[0]+hw+sizes[1]+hw/2
        tol = max(float(hw), 1.0)
        b0 = sizes[0] + hw / 2.0
        if abs(cx - b0) <= tol:
            return self._side_panels.get(0)
        b1 = sizes[0] + hw + sizes[1] + hw / 2.0
        if abs(cx - b1) <= tol:
            return self._side_panels.get(1)
        return None

    def toggle_index(self, index: int) -> None:
        """单击 handle（程序化等价入口）：切换对应侧栏折叠态。"""
        panel = self._side_panels.get(index)
        if panel is not None:
            panel.toggle()

    def createHandle(self):  # noqa: N802  (override QSplitter, PyQt6 无参)
        return _ToggleHandle(self)


# ----------------------------------------------------------------------
# 折叠 / 展开 / 宽度
# ----------------------------------------------------------------------


def _collapse_slot(panel: PanelContainer) -> None:
    """折叠：记录当前宽并把面板宽度压到 0（handle 上三角仍可见可点）。"""
    try:
        sp = _splitter_of(panel)
        panel._last_width = max(int(panel.width()), 0)
        panel.setMaximumWidth(0)
        if sp is None or sp.count() != 3:
            return
        idx = sp.indexOf(panel)
        if idx not in (0, 2):
            return
        sizes = [max(0, int(s)) for s in sp.sizes()]
        freed = sizes[idx]
        sizes[idx] = 0
        sizes[1] = sizes[1] + freed
        sp.setSizes(sizes)
        _update_handles(sp)
    except Exception:  # noqa: BLE001 — 布局操作永不抛
        pass


def _expand_slot(panel: PanelContainer) -> None:
    """展开：解除宽度限制并按内容自适应恢复宽度（手动拖拽值优先）。"""
    try:
        sp = _splitter_of(panel)
        panel.setMaximumWidth(_MAX_WIDTH)
        if sp is None or sp.count() != 3:
            return
        idx = sp.indexOf(panel)
        if idx not in (0, 2):
            return
        other_idx = 2 if idx == 0 else 0
        sizes = [max(0, int(s)) for s in sp.sizes()]
        target = _auto_width(panel)
        manual = getattr(panel, "_manual_width", None)
        if isinstance(manual, int) and manual >= _AUTO_MIN_W:
            target = min(_AUTO_MAX_W, manual)
        other_w = sizes[other_idx]
        free = sum(sizes) - other_w
        center = free - target
        if center < _MIN_CENTER_W:
            target = free - _MIN_CENTER_W
        if target < 0:
            target = 0
        center = free - target
        sizes[idx] = int(target)
        sizes[1] = int(center)
        sp.setSizes(sizes)
        _update_handles(sp)
    except Exception:  # noqa: BLE001 — 布局操作永不抛
        pass


def _on_splitter_moved(panel_left: PanelContainer, panel_right: PanelContainer,
                       splitter: QSplitter, pos: int, index: int) -> None:
    """用户拖拽分隔手柄 → 记录手动宽度（展开/内容切换自适应不覆盖）。"""
    sizes = splitter.sizes()
    if len(sizes) == 3:
        if index == 0:
            panel_left._manual_width = max(0, int(sizes[0]))
        elif index == 1:
            panel_right._manual_width = max(0, int(sizes[2]))


def build_workspace_splitter(center_widget) -> dict:
    """组装水平三栏工作区。

    Args:
        center_widget: 中间画布（现有垂直 QSplitter：波形上/分析面板下）。

    Returns:
        {"splitter": 水平 QSplitter, "left": 左 PanelContainer,
         "right": 右 PanelContainer, "center": center_widget}
    """
    sp = _ToggleSplitter(Qt.Orientation.Horizontal)
    sp.setHandleWidth(_HANDLE_WIDTH)
    sp.setChildrenCollapsible(False)

    left = PanelContainer()
    right = PanelContainer()

    # 允许程序化压到 0 宽（折叠）；展开由 _expand_slot 重新 setSizes
    left.setMinimumWidth(0)
    right.setMinimumWidth(0)

    sp.addWidget(left)
    sp.addWidget(center_widget)
    sp.addWidget(right)
    sp.register_side(0, left)
    sp.register_side(1, right)

    # 未布局时 QSplitter 默认宽 640，setSizes 按当前宽做最小值感知分配；
    # 先按参考总宽（+2×手柄）建立基准宽（测试/恢复口径：resize 基准宽 +
    # 往返实测，禁硬编码绝对像素）
    sp.resize(_DEFAULT_SIZES_TOTAL + _HANDLE_WIDTH * 2, 500)
    sp.setSizes([_DEFAULT_SIZES[0], _DEFAULT_SIZES[1], _DEFAULT_SIZES[2]])

    left._last_width = None
    right._last_width = None
    left._manual_width = None
    right._manual_width = None

    left.collapsedChanged.connect(lambda c: _collapse_slot(left) if c else _expand_slot(left))
    right.collapsedChanged.connect(lambda c: _collapse_slot(right) if c else _expand_slot(right))
    sp.splitterMoved.connect(
        lambda pos, index: _on_splitter_moved(left, right, sp, pos, index)
    )

    return {"splitter": sp, "left": left, "right": right, "center": center_widget}


def fit_panel_width(panel: PanelContainer) -> None:
    """内容切换后宽度自适应（展开态且非用户手动宽度时生效）。"""
    try:
        sp = _splitter_of(panel)
        if sp is None or panel.is_collapsed():
            return
        manual = getattr(panel, "_manual_width", None)
        if isinstance(manual, int) and manual >= _AUTO_MIN_W:
            return
        _expand_slot(panel)
    except Exception:  # noqa: BLE001 — 布局操作永不抛
        pass


def save_workspace(ws: dict, path=None) -> None:
    """持久化布局状态（sizes + 折叠态）；path 为 None 时用 get_data_dir()/"ui_layout.json"。

    一切 OSError 静默吞掉——布局保存永不影响应用。
    """
    try:
        state = {
            "sizes": list(ws["splitter"].sizes()),
            "left_collapsed": bool(ws["left"].is_collapsed()),
            "right_collapsed": bool(ws["right"].is_collapsed()),
        }
        target = Path(path) if path is not None else _default_layout_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass
    except Exception:  # noqa: BLE001 — 布局保存永不抛
        pass


def restore_workspace(ws: dict, path=None) -> None:
    """从 json 恢复布局状态。

    文件缺失/损坏/类型错误均静默返回（缺失时左栏默认收起、右栏默认展开）；
    sizes 仅当为长度 3 的 int 列表（排除 bool）时才 setSizes。
    """
    data = None
    try:
        target = Path(path) if path is not None else _default_layout_path()
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        data = None
    except Exception:  # noqa: BLE001 — 布局恢复永不抛
        data = None

    splitter = ws["splitter"]
    left = ws["left"]
    right = ws["right"]
    try:
        if isinstance(data, dict):
            sizes = data.get("sizes")
            if (
                isinstance(sizes, list)
                and len(sizes) == 3
                and all(isinstance(s, int) and not isinstance(s, bool) for s in sizes)
            ):
                clean = [max(0, int(s)) for s in sizes]
                # 未布局时 setSizes 按当前宽等比缩放：先把 splitter 宽设为保存总宽+手柄，
                # 使恢复的绝对像素值不被缩放（嵌入窗口后由布局按比例重算）
                try:
                    splitter.resize(
                        sum(clean) + _HANDLE_WIDTH * 2,
                        max(100, splitter.height()),
                    )
                except Exception:  # noqa: BLE001 — 布局恢复永不抛
                    pass
                splitter.setSizes(clean)
            left.set_collapsed(bool(data.get("left_collapsed", False)))
            right.set_collapsed(bool(data.get("right_collapsed", False)))
        else:
            # 无记录（含缺失/损坏）：左栏默认收起、右栏默认展开（T-1012）
            left.set_collapsed(True)
            right.set_collapsed(False)
    except Exception:  # noqa: BLE001 — 布局恢复永不抛
        return
    _update_handles(splitter)
