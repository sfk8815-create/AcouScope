# SPDX-License-Identifier: GPL-3.0-only
"""主工具栏 Tips 条：定宽（约 24 个汉字），文本超出时跑马灯右→左滚动。

动画：出现时从下方滑入，切换/消失时向上滑出。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

_CHAR_W = 12          # 界面字号 12px（用户偏好 10~12px）
_N_CHARS = 24         # 可见宽度按 24 个汉字设计
_PAD = 10.0           # 左右内边距
_SCROLL_SPEED = 48.0  # 跑马灯速度 px/s


class TipBar(QWidget):
    """提示条：定宽、跑马灯、滑入滑出动画。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        # 定宽上限（约 24 个汉字）；下限 0——窗口缩小时可被压缩至没有，
        # 把空间让给同行最右侧的 LOGO（LOGO 永不隐藏）
        self.setMaximumWidth(int(_CHAR_W * _N_CHARS + _PAD * 2))
        self.setMinimumWidth(0)

        self._font = QFont(self.font())
        self._font.setPointSizeF(10.5)
        self._fm = QFontMetrics(self._font)

        self._prefix = ""
        self._text = ""
        self._pending: tuple[str, str] | None = None

        self._y = float(self.height())   # 竖向偏移：height→0 滑入
        self._scroll = 0.0               # 跑马灯横向偏移
        self._hold = 0                   # 端点停留计数（tick）

        # 滑入/滑出动画
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.finished.connect(self._on_anim_finished)

        # 跑马灯定时器（仅文本超宽时运行）
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(33)
        self._tick_timer.timeout.connect(self._tick_scroll)

    # ------------------------------------------------------------------
    # 尺寸：正常状态取满宽（24 汉字），布局压缩时可以缩到 0
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(self.maximumWidth(), 28)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 28)

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    def show_text(self, prefix: str, text: str) -> None:
        """显示一条提示（相同文本不重复动画）。"""
        if not text:
            return
        if text == self._text and prefix == self._prefix:
            return
        self._pending = (prefix, text)
        if self._text:               # 有旧文本 → 先向上滑出
            self._run_anim(0.0, -float(self.height()), 140)
        else:                        # 直接从下方滑入
            self._start_pending()

    # ------------------------------------------------------------------
    # 动画
    # ------------------------------------------------------------------

    def _start_pending(self) -> None:
        prefix, text = self._pending or ("", "")
        self._pending = None
        self._prefix = prefix
        self._text = text
        self._scroll = 0.0
        self._hold = 18              # 开头先静止 ~0.6s
        self._update_scroll_timer()
        self._run_anim(float(self.height()), 0.0, 170)

    def _run_anim(self, start: float, end: float, ms: int) -> None:
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.setDuration(ms)
        self._anim.start()

    def _on_anim_value(self, v) -> None:
        self._y = float(v)
        self.update()

    def _on_anim_finished(self) -> None:
        if self._pending is not None:
            self._start_pending()
        else:
            self._y = 0.0
        self.update()

    # ------------------------------------------------------------------
    # 跑马灯
    # ------------------------------------------------------------------

    def _text_width(self) -> float:
        return float(self._fm.horizontalAdvance(
            f"{self._prefix}  {self._text}" if self._prefix else self._text))

    def _inner_width(self) -> float:
        return self.width() - _PAD * 2

    def _update_scroll_timer(self) -> None:
        if self._text and self._text_width() > self._inner_width():
            if not self._tick_timer.isActive():
                self._tick_timer.start()
        else:
            self._tick_timer.stop()
            self._scroll = 0.0

    def _tick_scroll(self) -> None:
        overflow = self._text_width() - self._inner_width()
        if overflow <= 0:
            self._tick_timer.stop()
            self.update()
            return
        if self._hold > 0:
            self._hold -= 1
            # 结尾停留结束 → 环回到开头并短暂停留
            if self._hold == 0 and self._scroll >= overflow - 1e-6:
                self._scroll = 0.0
                self._hold = 18
        else:
            self._scroll = min(self._scroll + _SCROLL_SPEED * 0.033, overflow)
            if self._scroll >= overflow - 1e-6:
                self._hold = 24   # 到达结尾，停留 ~0.8s
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        from acouscope.ui.theme import colors

        c = colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["panel"]))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawRoundedRect(r, 4, 4)

        if not self._text:
            p.end()
            return

        p.setFont(self._font)
        p.setClipRect(r.adjusted(1, 1, -1, -1))
        p.translate(0.0, self._y)

        x = _PAD - self._scroll
        if self._prefix:
            p.setPen(QPen(QColor(c["sub"]), 1))
            p.drawText(QPointF(x, self._fm.height() - self._fm.descent() + 4),
                       self._prefix)
            x += self._fm.horizontalAdvance(self._prefix) + 8
        p.setPen(QPen(QColor(c["text"]), 1))
        p.drawText(QPointF(x, self._fm.height() - self._fm.descent() + 4),
                   self._text)
        p.end()
