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
- 展开宽度按内容 sizeHint 自适应（clamp [220, 520]，且不低于内容可读保底宽
  _AUTO_FIT_MIN_W）；用户手动拖拽后以用户值为准（_manual_width，持久化不变），
  但下限不低于内容的 minimumSizeHint 宽（H1：内容切换即抬宽，只升不降）。
- 左栏默认收起（restore 无记录时 collapsed=True）；右栏默认展开（检查器）。
- 布局状态（sizes + 折叠态）持久化到 get_data_dir()/"ui_layout.json"；
  save/restore 全程静默：布局读写永不影响应用（缺失/损坏/不可写均不抛）。
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSplitter, QSplitterHandle

from acouscope.ui import theme
from acouscope.ui.widgets.panels import PanelContainer
from acouscope.utils.config import get_data_dir

# 展开宽度自适应范围 / 内容可读保底宽 / 中央画布最小保留宽（QWIDGETSIZE_MAX）
_AUTO_MIN_W = 220
# H1①：内容切换后的「可读保底宽」——恢复出的旧宽/手动宽再小也要抬到该值，
# 否则设置页两列、快捷键表会被右缘整片裁掉（离屏实测只剩一列残条）。
_AUTO_FIT_MIN_W = 380
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
# 内容包壳解套上限（正常为 1 层 QScrollArea；设上限防环状父链死循环）
_MAX_UNWRAP_DEPTH = 3
# 初始/恢复参考比例（左默认收起 0 / 中 / 右）；仅在无记录兜底时使用
_DEFAULT_SIZES = [0, 760, 300]
_DEFAULT_SIZES_TOTAL = sum(_DEFAULT_SIZES)
# 持久化文件名
_LAYOUT_FILENAME = "ui_layout.json"


def _default_layout_path() -> Path:
    return get_data_dir() / _LAYOUT_FILENAME


def _inner_widget(host):
    """容器内唯一子控件（无布局/无子件 → None）。"""
    layout = host.layout() if host is not None else None
    if layout is None or layout.count() == 0:
        return None
    item = layout.itemAt(0)
    return item.widget() if item is not None else None


def _unwrap_scroll(widget):
    """解开 QScrollArea 包壳（侧栏内容一律经 _wrap_side_scroll 包一层）。

    不解壳时量到的是包壳自身的极小 sizeHint（离屏实测 194），而真实内容页
    （设置页 485）整片被裁——这正是 H1 的根因。
    """
    from PyQt6.QtWidgets import QScrollArea

    for _ in range(_MAX_UNWRAP_DEPTH):
        if not isinstance(widget, QScrollArea):
            break
        inner = widget.widget()
        if inner is None:
            break
        widget = inner
    return widget


def _current_page(panel: PanelContainer):
    """面板内容区里「当前可见页」：解开包壳后若为 QStackedWidget 取其当前页。"""
    area = _unwrap_scroll(_inner_widget(panel.panelContent) or panel.panelContent)
    current = getattr(area, "currentWidget", None)
    if callable(current):
        page = current()
        if page is not None:
            return page
    return area


def _content_widths(panel: PanelContainer) -> tuple:
    """当前内容页的 (preferred, minimum) 宽（取页与内容区两者的较大值）。

    量为空时返回 (0, 0)，由调用方回落到保底常量。
    """
    pref = floor = 0
    for widget in (_current_page(panel), panel.panelContent):
        if widget is None:
            continue
        try:
            pref = max(pref, int(widget.sizeHint().width()))
        except Exception:  # noqa: BLE001 — 度量失败不阻断布局
            pass
        try:
            floor = max(floor, int(widget.minimumSizeHint().width()))
        except Exception:  # noqa: BLE001
            pass
    return pref, floor


def _auto_width(panel: PanelContainer) -> int:
    """按当前内容所需宽度估算展开宽度。

    H1①：下限抬到「内容可读保底宽」_AUTO_FIT_MIN_W（内容再窄也保证设置页
    两列/快捷键表整表可读），上限仍是 _AUTO_MAX_W。
    """
    hint, floor = _content_widths(panel)
    need = max(hint, floor)
    if need <= 0:
        need = _AUTO_FIT_MIN_W
    return int(min(_AUTO_MAX_W, max(_AUTO_MIN_W, max(need, _AUTO_FIT_MIN_W))))


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
            sp = self.splitter()
            if isinstance(sp, _ToggleSplitter):
                sp.begin_drag()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is not None:
            self._dragged = True
        new_y = int(event.position().y())
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
        sp = self.splitter()
        if isinstance(sp, _ToggleSplitter):
            sp.end_drag()
        # IM-29（T-1079 补完）：拖拽期 handle 持隐式 grab，leaveEvent 被抑制 ⇒
        # 释放后 _hover/_cursor_y 可能残留。释放后 grab 已解除，underMouse() 此时
        # 可靠反映光标实际位置；光标不在即复位状态源。无论光标在哪都强制全框重绘，
        # 防止 backing store 残留旧描边像素。
        if not self.underMouse():
            self._hover = False
            self._cursor_y = None
        self.update(self.rect())
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
        c = theme.colors()
        # T-1079 ③：先清底铺满本帧脏区——部分 update（旧∪新包围盒）下不清底，
        # 会把前次悬停位的描边像素留在 backing store 里 = 残影。底色取窗底 bg0（pane 同色）。
        painter.fillRect(self.rect(), QColor(c["bg0"]))
        h = self.height()
        cx = self.width() / 2.0
        # R1：默认只画 1px 居中竖线（border）。T-1079 ③：画在像素中心 + 关抗锯齿——
        # 分数坐标 + AA 会把 1px 摊成两列半覆盖，观感误读为「竖虚线」。
        lx = float(self.width() // 2) + 0.5
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(c["border"]), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(lx, 0.0), QPointF(lx, float(h)))
        # R6：拖拽中隐藏抓手；R2：悬停时在光标 Y 处浮现（未收到 move 取中线 H/2）
        if self._hover and not self._dragged:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
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
    """三栏工作区水平 QSplitter：handle 承载边缘三角（见 _ToggleHandle）。

    IM-30 修复：拖拽期间临时把中央 stretch 置 0，使 QSplitter 按光标位直接分配
    相邻两栏宽度（不被 stretch 拉偏）；释放后恢复 stretch(1,1) 让中央吸收窗口
    缩放富余。
    """

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._side_panels: dict[int, PanelContainer] = {}
        self._dragging = False

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

    def begin_drag(self) -> None:
        """handle 按下时调用：暂停中央 stretch 使拖拽直接跟光标。"""
        if not self._dragging:
            self._dragging = True
            self.setStretchFactor(1, 0)

    def end_drag(self) -> None:
        """handle 释放时调用：恢复中央 stretch 吸收窗口缩放富余。"""
        if self._dragging:
            self._dragging = False
            self.setStretchFactor(1, 1)

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


def _target_width(panel: PanelContainer) -> int:
    """展开目标宽：手动拖拽值优先（H1②），否则走内容自适应（H1①）。

    - 无手动宽：`min(max(内容 preferred 宽, _AUTO_FIT_MIN_W), _AUTO_MAX_W)`；
    - 有手动宽：尊重用户值，但下限抬到内容 `minimumSizeHint().width()`
      （用户拖得再窄，也不把内容压到不可读），上限仍 `_AUTO_MAX_W`。
    """
    manual = getattr(panel, "_manual_width", None)
    _pref, floor = _content_widths(panel)
    # 「手动拖过」= _manual_width 非 None 且 > 0（0 是折叠/拖到零的记账值，
    # 不是用户想要的展开宽，按无手动宽处理）。
    if isinstance(manual, int) and manual > 0:
        return int(min(_AUTO_MAX_W, max(int(manual), floor)))
    return _auto_width(panel)


def _expand_slot(panel: PanelContainer) -> None:
    """展开：解除宽度限制并按内容自适应恢复宽度（手动拖拽值优先）。

    H1：目标宽算完后**只升不降**——当前宽已够内容用时不再收窄，避免切页把
    用户/窗口给出的宽度改小（内容变宽时才抬，见 `_target_width`）。
    """
    try:
        sp = _splitter_of(panel)
        # 既有外部上限（main_window 的侧栏 28% 收口）必须原样保留：本函数只解除
        # 「折叠」写入的 0 上限，不越过外部策略上限（否则切页会把栏宽顶破 28%）。
        prev_max = int(panel.maximumWidth())
        capped = 0 < prev_max < _MAX_WIDTH
        panel.setMaximumWidth(prev_max if capped else _MAX_WIDTH)
        if sp is None or sp.count() != 3:
            return
        idx = sp.indexOf(panel)
        if idx not in (0, 2):
            return
        other_idx = 2 if idx == 0 else 0
        sizes = [max(0, int(s)) for s in sp.sizes()]
        target = _target_width(panel)
        if capped:
            target = min(target, prev_max)
        if sizes[idx] >= target:
            return  # 已够宽：不动布局（禁把宽度改小，H1 只抬不压）
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
    # T-1093 B-2：中央画布吸收全部富余宽（左右栏 stretch 0）。不设本行时
    # QSplitter 把窗口增减的宽度按比例摊给三栏，中央画布被侧栏牵动（配合
    # 全铺页 min 传播即观感为「拖一下整窗抖」）。
    sp.setStretchFactor(1, 1)

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
    """内容切换后宽度自适应（H1）。

    展开态一律走 `_expand_slot`：手动宽由 `_target_width` 优先取用，但仍受
    「内容 minimumSizeHint 下限」约束（H1②）——此前手动宽直接早退，导致
    手动拖窄后再切设置页，内容被右缘裁掉。
    """
    try:
        sp = _splitter_of(panel)
        if sp is None or panel.is_collapsed():
            return
        _expand_slot(panel)
    except Exception:  # noqa: BLE001 — 布局操作永不抛
        pass


def make_layout_save_timer(parent, save_fn, msec: int = 150) -> QTimer:
    """布局落盘「尾部合并」定时器（T-1093 B-2 次要项·拖拽卡顿）。

    `splitterMoved` 在 opaque 拖拽下逐像素发射，直连 `save_workspace` 即逐像素
    json.dump（GUI 线程磁盘 IO）。本工厂给出一个单发定时器：接线层把
    `splitterMoved` 接到 `timer.start()`，一段拖拽停手 msec 后才落盘一次；
    调用方在退出前 `stop()` + 直接 `save_fn()` 补存，即不丢末次布局。

    定时器以 `parent`（主窗）为父 ⇒ 随窗体析构，无悬垂回调。落盘本体仍是同步
    的 `save_workspace`（其语义一字未改，PI-T84 N-6）。
    """
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(max(1, int(msec)))
    timer.timeout.connect(save_fn)
    return timer


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
                # F1（真机 GUI 审计）：恢复时对三栏施加内容可读下限，杜绝病态
                # 窄栏被持久化后原样恢复（实测 ui_layout.json 曾写入
                # [194, 560, 146]——右栏内容组约 606px 被硬裁到 147px，
                # 「复制」「导出测量记录…」按钮永远 offscreen，窗口拉宽后
                # 侧栏仍保持病态窄值）。左右各 ≥ _AUTO_MIN_W、中央 ≥ 320；
                # 先抬到下界（下限优先），若抬完总和超出「保存时的可用总宽」，
                # 再只按各栏高于下界的富余部分等比缩减，绝不把任何一栏
                # 压回下界以下。save_workspace 一字未改，round-trip 不变。
                _min_center_restore_w = 320
                _restore_mins = [_AUTO_MIN_W, _min_center_restore_w, _AUTO_MIN_W]
                _available = sum(clean)
                raised = [max(clean[i], _restore_mins[i]) for i in range(3)]
                _overflow = sum(raised) - _available
                if _overflow > 0 and _available >= sum(_restore_mins):
                    _slack = [raised[i] - _restore_mins[i] for i in range(3)]
                    _slack_total = sum(_slack)
                    if _slack_total > 0:
                        _cuts = [(_overflow * _slack[i]) // _slack_total
                                 for i in range(3)]
                        raised = [raised[i] - _cuts[i] for i in range(3)]
                        # 整除法可能留 1~2px 余量：从富余最大的栏位继续扣，
                        # 保证缩减后总和恰好回到可用宽且各栏仍 ≥ 下界。
                        _residual = sum(raised) - _available
                        for _i in sorted(
                            range(3),
                            key=lambda j: raised[j] - _restore_mins[j],
                            reverse=True,
                        ):
                            if _residual <= 0:
                                break
                            _take = min(_residual,
                                        raised[_i] - _restore_mins[_i])
                            raised[_i] -= _take
                            _residual -= _take
                clean = raised
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
