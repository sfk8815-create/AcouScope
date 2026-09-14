# SPDX-License-Identifier: GPL-3.0-only
"""右侧滑入覆盖式抽屉（V099_DRAWER_V1）。

UI 宪法条 3：对话框最小化——可内联展开的次要内容（设置 / 房间声学 / 导出
选项）用非模态抽屉代替独立对话框，主窗口工作区不被遮挡阻断。

- DrawerWidget(QFrame)：parent 右侧滑入的覆盖式抽屉，是 parent 的子部件
  （drawer.window() 返回顶层窗而非自身），非模态：不调用 exec、不设任何窗口模态、
  不阻塞调用方。
  - set_content(widget)  替换内容区（内容区 objectName="drawerContent"）
  - set_icon_row(items, default_index)  内容区上方渲染顶部图标切换行
    （CB-012 C-1）：items=[(icon_name, tooltip), ...] 走 get_icon + i18n 双语
    tooltip，互斥 checkable、默认选中 default_index，点击发 iconSelected(index)；
    传空隐藏该行。
  - open()               定位到 parent 右缘内侧；duration>0 时 QPropertyAnimation
                         ("pos") 从右缘外滑入，duration<=0 时直接 setGeometry；
                         关→开时发 opened 信号
  - close_drawer()       隐藏；开→关时发 closed 信号
  - toggle() / is_open() 开关心跳（is_open 为状态位，不依赖 isVisible）
  - 面板头（T-1043）      顶部面板头（遵 ARCH §五-1）：左标题（可空，set_title 可设）
                        + 右**可见关闭按钮**（get_icon("close") → close_drawer）；
                        底边 1px 取 TOKENS.elevation.border；Esc/点外部为**额外**路径
  - 事件过滤器（父窗 installEventFilter(self)）：
      a) 父窗 Resize   → 未开也预定位（开时免跳），开着则跟随右缘/高度
      b) 外部点击      → 父窗内 MouseButtonPress 且位置在抽屉几何之外 → 关闭
      c) Escape 按键   → 关闭
    其余事件一律放行（eventFilter 返回 False）；仅被拦截的关闭类返回 True。
- 样式：背景 colors()["panel"]、左边框 1px colors()["border"]，全部颜色走
  theme.colors() / 几何走 TOKENS，经 theme.style_when_theme 注册主题动态刷新
  （严禁硬编码 hex）。
- open_drawer(parent, widget, width, icons=None, default_index=0,
              toggle_on_same_content=True)  模块级便捷函数：按 (parent, width)
  复用实例（挂 parent 属性 _v099_drawer_<width>），set_content + set_icon_row
  + open，返回实例。toggle_on_same_content=True（T-1043 N4）时「同一内容对象
  再次请求」= **关闭**（幂等 toggle；关闭前先触发内容 closeEvent 清理）。

本模块只建基础设施，不改动任何既有文件；调用点接入在后续任务。
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.theme import TOKENS, get_icon

__all__ = ["DrawerWidget", "open_drawer"]


def _drawer_qss(c: dict) -> str:
    """抽屉面板样式：颜色一律来自 theme.colors()，几何来自 TOKENS（无硬编码）。"""
    elev = TOKENS["elevation"]["border"]
    return (
        f"QFrame#drawerWidget {{ background: {c['panel']}; "
        f"border: none; border-left: {elev}px solid {c['border']}; }}"
        f"QFrame#drawerContent {{ background: transparent; border: none; }}"
    )


def _header_qss(c: dict) -> str:
    """抽屉面板头样式（ARCH §五-1）：底边 1px 分隔 + 可见关闭按钮；无硬编码。"""
    elev = TOKENS["elevation"]["border"]
    rad = TOKENS["radius"]["sm"]
    pad_x = TOKENS["control"]["pad_x"]
    return (
        f"QFrame#drawerHeader {{ background: {c['panel']}; border: none; "
        f"border-bottom: {elev}px solid {c['border']}; }}"
        f"QLabel#drawerTitle {{ background: transparent; color: {c['text']}; }}"
        f"QPushButton#drawerCloseBtn {{ background: transparent; border: none; "
        f"border-radius: {rad}px; padding: {pad_x}px; }}"
        f"QPushButton#drawerCloseBtn:hover {{ background: {c['btn_hover']}; }}"
    )


def _icon_row_qss(c: dict) -> str:
    """抽屉顶图标切换行样式：颜色 theme 派生，几何走 TOKENS（禁硬编码 hex）。"""
    elev = TOKENS["elevation"]["border"]
    rad = TOKENS["radius"]["sm"]
    sp = TOKENS["spacing"]
    return (
        f"QFrame#drawerIconRow {{ background: {c['panel']}; border: none; "
        f"border-bottom: {elev}px solid {c['border']}; }}"
        f"QPushButton#drawerIconBtn {{ background: transparent; border: none; "
        f"border-radius: {rad}px; padding: {sp['xs']}px; }}"
        f"QPushButton#drawerIconBtn:hover {{ background: {c['btn_hover']}; }}"
        f"QPushButton#drawerIconBtn:checked {{ background: {c['accent']}; }}"
    )


class DrawerWidget(QFrame):
    """主窗口右侧滑入的覆盖式抽屉（子部件，非顶层窗口，非模态）。"""

    opened = pyqtSignal()   # 仅从关到开时发出
    closed = pyqtSignal()   # 仅从开到关时发出
    iconSelected = pyqtSignal(int)  # 顶图标切换行点击：发出所选索引（CB-012 C-1）

    def __init__(self, parent, width: int = 360, duration: int = 200):
        if not isinstance(parent, QWidget):
            raise ValueError("DrawerWidget 的 parent 必须是 QWidget")
        super().__init__(parent)
        self._width = width
        self._duration = duration
        self._open = False
        self._anim: QPropertyAnimation | None = None
        self._content: QWidget | None = None

        self.setObjectName("drawerWidget")
        self.setFixedWidth(width)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 覆盖式抽屉不抢焦点、不要求父窗置顶于其他应用窗口之上
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # 顶部图标切换行（CB-012 C-1）：默认隐藏，set_icon_row 传 items 时显示；
        # 内容区之前插入，两者共用一个 QVBoxLayout。
        self.icon_row = QFrame(self)
        self.icon_row.setObjectName("drawerIconRow")
        self.icon_row.setVisible(False)
        self._icon_row_layout = QHBoxLayout(self.icon_row)
        self._icon_row_layout.setContentsMargins(
            TOKENS["spacing"]["sm"], TOKENS["spacing"]["xs"],
            TOKENS["spacing"]["sm"], TOKENS["spacing"]["xs"],
        )
        self._icon_row_layout.setSpacing(TOKENS["spacing"]["xs"])
        self._icon_buttons: list[QPushButton] = []
        self._icon_group = QButtonGroup(self)
        self._icon_group.setExclusive(True)
        self._refresh_icon_style = theme.style_when_theme(self.icon_row, _icon_row_qss)

        # T-1043 §五-1：面板头 = 左标题（可空）+ 右可见关闭出口；
        # Esc / 点击外部为额外路径（多路径不互斥）。
        self.header = QFrame(self)
        self.header.setObjectName("drawerHeader")
        self.header.setFixedHeight(TOKENS["control"]["h_lg"])
        head = QHBoxLayout(self.header)
        head.setContentsMargins(
            TOKENS["spacing"]["md"], 0, TOKENS["spacing"]["xs"], 0,
        )
        head.setSpacing(TOKENS["spacing"]["xs"])
        self.title_label = QLabel("")
        self.title_label.setObjectName("drawerTitle")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.btn_close = QPushButton(self.header)
        self.btn_close.setObjectName("drawerCloseBtn")
        self.btn_close.setIcon(get_icon("close"))
        self.btn_close.setIconSize(QSize(20, 20))
        self.btn_close.setToolTip(tr("btn.close"))
        self.btn_close.setAutoDefault(False)
        self.btn_close.clicked.connect(self.close_drawer)
        head.addWidget(self.btn_close)
        self._refresh_header_style = theme.style_when_theme(self.header, _header_qss)

        # 内容区：内部 QVBoxLayout 承载，objectName 固定为 drawerContent
        self.content_frame = QFrame(self)
        self.content_frame.setObjectName("drawerContent")
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.header)
        body.addWidget(self.icon_row)
        body.addWidget(self.content_frame, stretch=1)
        content = QVBoxLayout(self.content_frame)
        content.setContentsMargins(
            TOKENS["spacing"]["md"],
            TOKENS["spacing"]["md"],
            TOKENS["spacing"]["md"],
            TOKENS["spacing"]["md"],
        )
        self._content_layout = content

        # 主题动态样式：主题切换时即时刷新（严禁硬编码 hex）
        self._refresh_style = theme.style_when_theme(self, _drawer_qss)

        # 事件过滤器：父窗 Resize 跟随 / 外部点击关闭 / Escape 关闭
        parent.installEventFilter(self)

    # ------------------------------------------------------------------
    # 内容
    # ------------------------------------------------------------------

    def set_content(self, widget: QWidget) -> None:
        """替换抽屉内容区（原内容先 close 触发其 closeEvent 清理，再移除并释放）。"""
        if self._content is not None:
            # 先 close 旧内容：触发内容 closeEvent（如 AI 释图面板 cancel worker），
            # 修复此前直接 removeWidget+deleteLater 导致内容清理逻辑不执行的漏洞
            self._content.close()
            self._content_layout.removeWidget(self._content)
            self._content.deleteLater()
        self._content = widget
        widget.setParent(self.content_frame)
        self._content_layout.addWidget(widget)

    def content(self) -> QWidget | None:
        """当前内容部件（未装载为 None）——供 toggle 判定「同内容再请求」。"""
        return self._content

    def set_title(self, text: str) -> None:
        """设置面板头标题（可空：内容面板自带标题时保持留空）。"""
        self.title_label.setText(text)

    def set_icon_row(self, items, default_index: int = 0) -> None:
        """在内容区上方渲染顶部图标切换行（CB-012 C-1）。

        items: list[tuple[icon_name, tooltip]]——icon_name 走 get_icon，
        tooltip 为已翻译文本（调用侧用 i18n tr 传双语）。传空/None 隐藏该行
        （保持既有无图标抽屉行为）。默认选中 default_index 对应项（checkable
        互斥）；点击任意项发 iconSelected(index)。
        """
        # 清空旧图标行：按钮从互斥组移除并释放，布局项（按钮 + 弹簧）全清
        for btn in self._icon_buttons:
            self._icon_group.removeButton(btn)
        self._icon_buttons.clear()
        while self._icon_row_layout.count():
            item = self._icon_row_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not items:
            self.icon_row.setVisible(False)
            return

        for index, (icon_name, tooltip) in enumerate(items):
            btn = QPushButton(self.icon_row)
            btn.setObjectName("drawerIconBtn")
            btn.setIcon(get_icon(icon_name))
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setAutoDefault(False)
            btn.clicked.connect(
                lambda checked, idx=index: self.iconSelected.emit(idx)
            )
            self._icon_group.addButton(btn, index)
            self._icon_row_layout.addWidget(btn)
            self._icon_buttons.append(btn)

        self._icon_row_layout.addStretch(1)
        if 0 <= default_index < len(self._icon_buttons):
            self._icon_buttons[default_index].setChecked(True)
        self.icon_row.setVisible(True)

    def shutdown_content(self) -> None:
        """关闭当前内容（触发其 closeEvent）；幂等，close() 对已 hide 部件安全。

        供主窗退出时调用，保证内容侧的 worker 取消/等待等清理逻辑执行。
        """
        if self._content is not None:
            self._content.close()

    # ------------------------------------------------------------------
    # 开 / 关
    # ------------------------------------------------------------------

    def _target_geometry(self) -> tuple[int, int, int, int]:
        """右缘内侧目标几何：x = parent.width() - width, y=0, 高 = parent.height()。"""
        host = self.parent()
        w = self._width
        return (max(0, host.width() - w), 0, w, host.height())

    def _sync_geometry(self) -> None:
        """把抽屉几何同步到目标位（动画中不覆盖，避免与 QPropertyAnimation 争抢）。"""
        if self._anim is not None and self._anim.state() == QPropertyAnimation.State.Running:
            return
        x, y, w, h = self._target_geometry()
        self.setGeometry(x, y, w, h)

    def open(self) -> None:
        """打开抽屉：定位/滑入到 parent 右缘内侧，show + raise；置状态位并发 opened。"""
        host = self.parent()
        x, y, w, h = self._target_geometry()

        if self._duration > 0:
            if self._anim is None:
                self._anim = QPropertyAnimation(self, b"pos", self)
                self._anim.setDuration(self._duration)
                self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                # 动画结束后钉回目标几何（防平台侧舍入漂移）
                self._anim.finished.connect(self._sync_geometry)
            # 已在开态重入：从当前位继续滑回目标位；首开：自右缘外滑入
            start = self.pos() if self._open else QPoint(host.width(), 0)
            self._anim.setStartValue(start)
            self._anim.setEndValue(QPoint(x, y))               # 右缘内侧目标位
            self.show()
            self.raise_()
            self._anim.start()
        else:
            if self._anim is not None:
                self._anim.stop()
            self.setGeometry(x, y, w, h)
            self.show()
            self.raise_()

        if not self._open:
            self._open = True
            self.opened.emit()

    def close_drawer(self) -> None:
        """关闭抽屉：停止动画并隐藏；开→关时发 closed。"""
        if self._anim is not None and \
                self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        if self._open:
            self._open = False
            self.closed.emit()
        self.hide()

    def toggle(self) -> None:
        """开/关切换。"""
        if self._open:
            self.close_drawer()
        else:
            self.open()

    def is_open(self) -> bool:
        """状态位（不依赖 isVisible）。"""
        return self._open

    # ------------------------------------------------------------------
    # 事件过滤器：父窗 Resize 跟随 / 外部点击关闭 / Escape 关闭
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        if obj is self.parent() and self._open:
            t = event.type()
            if t == QEvent.Type.Resize:
                # 开着时跟随父窗尺寸（右缘对齐、满高）
                self._sync_geometry()
            elif t == QEvent.Type.MouseButtonPress:
                # 外部点击：位置在抽屉几何之外 → 关闭（拦截该次按下）
                pos = event.position().toPoint()
                if not self.geometry().contains(pos):
                    self.close_drawer()
                    return True
            elif t == QEvent.Type.KeyPress:
                # Escape → 关闭（拦截）
                if event.key() == Qt.Key.Key_Escape:
                    self.close_drawer()
                    return True
        return False


def open_drawer(parent, widget, width: int = 360,
                icons=None, default_index: int = 0,
                toggle_on_same_content: bool = True,
                title: str | None = None) -> DrawerWidget:
    """在 parent 右侧打开 width 宽的抽屉并装载 widget（按 (parent, width) 复用实例）。

    已存在同宽抽屉则复用（换内容后重新打开）；否则新建。parent 必须是 QWidget。
    icons 非空时在内容区上方渲染顶部图标切换行（见 DrawerWidget.set_icon_row），
    默认选中 default_index；icons 为 None 时保持无图标行（既有行为）。
    title 非 None 时写入面板头标题（默认保持留空）。
    toggle_on_same_content=True（T-1043 N4）：抽屉已开着且请求的是**同一内容对象**
    → **关闭而非重开**（幂等 toggle）；关闭路径先触发内容 closeEvent 清理
    （与 set_content 的清理语义一致，不绕过）。
    """
    if not isinstance(parent, QWidget):
        raise ValueError("open_drawer 的 parent 必须是 QWidget")
    attr = f"_v099_drawer_{width}"
    drawer = getattr(parent, attr, None)
    if isinstance(drawer, DrawerWidget):
        if toggle_on_same_content and drawer.is_open() and drawer.content() is widget:
            drawer.close_drawer()
            drawer.shutdown_content()   # 触发内容 closeEvent（N4 清理不绕过）
            return drawer
    else:
        drawer = DrawerWidget(parent, width=width)
        setattr(parent, attr, drawer)
    drawer.set_content(widget)
    drawer.set_icon_row(icons, default_index)
    if title is not None:
        drawer.set_title(title)
    drawer.open()
    return drawer
