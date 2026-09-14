# SPDX-License-Identifier: GPL-3.0-only
"""非模态即时反馈服务（V099_TOAST_V1）。

UI 宪法条 2：轻量、非模态、自动消失、四级语义（info/success/warning/error）。

- ToastWidget(QFrame)：setProperty("level", ...)，语义色左边框由
  T-502 全局 QSS 的 QFrame[level="xxx"] 规则提供；面板背景/边框/圆角走
  theme.colors() 与 TOKENS，经 style_when_theme 注册主题动态刷新。
- show_toast(parent, message, level, duration)：父窗可视区底部居中偏上
  （底边距 TOKENS.spacing.lg），宽度 = 内容提示宽度与父窗 60% 上限取小、
  不小于 200px；WA_ShowWithoutActivating + NoFocus + 非模态
  （无 exec / 无模态 / 不阻塞）；QTimer 到点 close() + deleteLater()。
- 同 parent 连续多条垂直向上堆叠（模块级 weakref 登记，最多 3 条，
  超出立即关闭最旧）。

后续 T-504f 负责把既有 QMessageBox 提示型调用点替换为 show_toast；
本模块只建服务，不替换任何调用点。
"""

from __future__ import annotations

import weakref

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from acouscope.ui import theme
from acouscope.ui.theme import TOKENS

# 四级语义；未知 level 归一为 "info"。
LEVELS = ("info", "success", "warning", "error")

_MAX_STACK = 3        # 同 parent 最多堆叠条数（超出立即关闭最旧）
_MIN_WIDTH = 200      # toast 最小宽度（px）
_WIDTH_RATIO = 0.6    # 宽度上限 = 父窗宽度 × 0.6

# 模块级活动 toast 登记：id(parent) -> [weakref.ref(ToastWidget) 按出现顺序]
_ACTIVE: dict[int, list[weakref.ref]] = {}


def _normalize_level(level: str) -> str:
    return level if level in LEVELS else "info"


def _live_refs(parent) -> list[weakref.ref]:
    """parent 当前可见 toast 的弱引用（按出现顺序），并清理已死亡引用。"""
    refs = _ACTIVE.get(id(parent), [])
    refs[:] = [ref for ref in refs if ref() is not None and ref().isVisible()]
    if refs:
        _ACTIVE[id(parent)] = refs
    return refs


def _close_toast(t: ToastWidget) -> None:
    """关闭并释放：从登记移除 + close() + deleteLater()。"""
    host = t.parent()
    if host is not None:
        refs = _ACTIVE.get(id(host), [])
        for i, ref in enumerate(refs):
            if ref() is t:
                del refs[i]
                break
        if not refs:
            _ACTIVE.pop(id(host), None)
    t.close()
    t.deleteLater()


def _toast_qss(c: dict) -> str:
    """toast 面板样式：颜色一律来自 theme.colors()，几何来自 TOKENS。

    语义色左边框不在此处——由 T-502 全局 QSS 的 QFrame[level="xxx"]
    规则按 level 属性提供。
    """
    rad = TOKENS["radius"]["md"]
    return (
        f"QFrame#toastWidget {{ background: {c['panel']}; "
        f"border: 1px solid {c['border']}; border-radius: {rad}px; }}"
        f"QFrame#toastWidget > QLabel#lblMessage {{ color: {c['text']}; }}"
    )


class ToastWidget(QFrame):
    """单条 toast。level 属性驱动 T-502 语义 QSS 左边框色。"""

    def __init__(self, message: str, level: str = "info", parent=None):
        super().__init__(parent)
        self._level = _normalize_level(level)
        self.setProperty("level", self._level)
        self.setObjectName("toastWidget")

        self.lblMessage = QLabel(message, self)
        self.lblMessage.setObjectName("lblMessage")
        self.lblMessage.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            TOKENS["spacing"]["sm"],
            TOKENS["spacing"]["sm"],
            TOKENS["spacing"]["sm"],
            TOKENS["spacing"]["sm"],
        )
        layout.addWidget(self.lblMessage)

        # 主题动态样式：theme 切换时即时刷新（严禁硬编码 hex）
        self._refresh_style = theme.style_when_theme(self, _toast_qss)

    def level(self) -> str:
        return self._level

    def _reposition(self) -> None:
        """父窗尺寸/堆叠变化时重算位置：底部居中偏上，逐条向上避让。"""
        host = self.parent()
        if not isinstance(host, QWidget):
            return
        stack = _live_refs(host)
        for i, ref in enumerate(stack):
            if ref() is self:
                n = i + 1  # 自底向第 n 条
                break
        else:
            n = 1
        x = max(0, host.width() // 2 - self.width() // 2)
        y = (
            host.height()
            - TOKENS["spacing"]["lg"]
            - n * self.height()
            - (n - 1) * TOKENS["spacing"]["sm"]
        )
        self.setGeometry(x, max(0, y), self.width(), self.height())


def _hook_parent_resize(parent: QWidget) -> None:
    """把父窗 resizeEvent 包一层：尺寸变化后重排所有活动 toast（仅装一次）。"""
    if getattr(parent, "_t504a_hooked", False):
        return
    parent._t504a_hooked = True  # type: ignore[attr-defined]
    orig = parent.resizeEvent

    def hooked(event, _host=parent, _orig=orig) -> None:  # type: ignore[misc]
        _orig(event)
        for ref in list(_ACTIVE.get(id(_host), [])):
            t = ref()
            if t is not None and t.isVisible():
                t._reposition()

    parent.resizeEvent = hooked  # type: ignore[method-assign]


def show_toast(
    parent,
    message: str,
    level: str = "info",
    duration: int = 3500,
) -> ToastWidget:
    """在 parent 可视区底部居中偏上显示一条非模态 toast，duration ms 后自动关闭。

    parent 必须是 QWidget（为 None 时抛 ValueError）。
    全程非模态：不 exec、不设模态、不阻塞调用方。
    返回 ToastWidget（调用方可自行 close 提前关闭）。
    """
    if not isinstance(parent, QWidget):
        raise ValueError("show_toast 的 parent 必须是 QWidget")

    toast = ToastWidget(message, _normalize_level(level), parent)
    toast.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    toast.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # 宽度：内容提示宽度与父窗 60% 上限取小，不小于 200px
    max_w = max(_MIN_WIDTH, int(parent.width() * _WIDTH_RATIO))
    toast.adjustSize()
    toast.setFixedWidth(min(max(_MIN_WIDTH, toast.sizeHint().width()), max_w))
    toast.adjustSize()

    # 堆叠：同 parent 最多 _MAX_STACK 条，超出立即关闭最旧
    refs = _live_refs(parent)
    while len(refs) >= _MAX_STACK:
        _close_toast(refs[0]())

    if not parent.isVisible():
        parent.show()  # toast 需可见：父窗未显示时先显示（仍非模态）
    toast.show()
    toast.raise_()
    toast._reposition()
    refs.append(weakref.ref(toast))
    _ACTIVE.setdefault(id(parent), refs)

    # 到点自动关闭：单发定时器作为 toast 子对象
    timer = QTimer(toast)
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: _close_toast(toast))
    timer.start(duration)

    _hook_parent_resize(parent)
    return toast
