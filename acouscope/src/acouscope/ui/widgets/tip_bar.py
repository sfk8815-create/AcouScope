# SPDX-License-Identifier: GPL-3.0-only
"""主工具栏 Tips 条：定宽（约 40 个汉字），文本超出时跑马灯右→左滚动。

动画：出现时从下方滑入，切换/消失时向上滑出。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QToolButton, QWidget

_CHAR_W = 12          # 界面字号 12px（用户偏好 10~12px）
_N_CHARS = 40         # 可见宽度按 40 个汉字设计（60 条 tip 三语 ≥80% 不跑马灯）
_PAD = 10.0           # 左右内边距
_SCROLL_SPEED = 48.0  # 跑马灯速度 px/s
_CLOSE_RESERVE = 20   # 右侧 × 关闭钮占位（从最大宽另加，不挤压跑马灯可视宽度）
_CLOSE_SIZE = 16      # × 钮边长


class TipBar(QWidget):
    """提示条：定宽、跑马灯、滑入滑出动画。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        # 定宽上限（约 40 个汉字 + 右侧 × 钮占位）；下限 0——窗口缩小时可被压缩至
        # 没有，把空间让给同行最右侧的 LOGO（LOGO 永不隐藏）。★ 文本可视宽仍为
        # _CHAR_W×_N_CHARS（口径同产品既有「60 条 ≥80% 不跑马灯」判据）。
        self.setMaximumWidth(
            int(_CHAR_W * _N_CHARS + _PAD * 2) + _CLOSE_RESERVE
        )
        self.setMinimumWidth(0)

        # G14：右侧 × 关闭钮——点击只隐藏本条（不落盘），下一轮 show_text 重新显示。
        # 原提示条无关闭路径且带输入框式描边，易被误读成可输入控件。
        self.btn_close = QToolButton(self)
        self.btn_close.setObjectName("tipBarClose")
        self.btn_close.setText("×")
        self.btn_close.setAutoRaise(True)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFixedSize(_CLOSE_SIZE, _CLOSE_SIZE)
        self.btn_close.clicked.connect(self.dismiss)
        # 文案走 i18n：本模块不在 test_no_hardcoded_ui_strings 汇点扫描内，
        # 但保持「用户可见文本禁硬编码」纪律
        from acouscope.i18n import tr as _tr

        self.btn_close.setToolTip(_tr("tip.close"))
        self.btn_close.setAccessibleName(_tr("tip.close"))
        # 取色/字号走令牌（无边框透明底：不额外抬高提示条观感层级）
        from acouscope.ui import theme as _theme

        _theme.style_when_theme(
            self.btn_close,
            lambda c: (
                f"QToolButton#tipBarClose {{ background: transparent; border: none;"
                f" color: {c['sub']};"
                f" font-size: {_theme.TOKENS['typography']['body']}px; }}"
            ),
        )
        self.btn_close.hide()

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
    # 尺寸：正常状态取满宽（40 汉字），布局压缩时可以缩到 0
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
        # G14：上一次已按 × 关闭过 → 本条/下一轮重新显示（关闭只作用于当前这条）
        if self.isHidden():
            self.show()
        self.btn_close.show()
        if text == self._text and prefix == self._prefix:
            return
        self._pending = (prefix, text)
        if self._text:               # 有旧文本 → 先向上滑出
            self._run_anim(0.0, -float(self.height()), 140)
        else:                        # 直接从下方滑入
            self._start_pending()

    def dismiss(self) -> None:
        """关闭本条提示（G14）：仅隐藏本条，不落盘、不改轮换节奏。"""
        self._pending = None
        self._anim.stop()
        self._tick_timer.stop()
        self._prefix = ""
        self._text = ""
        self._scroll = 0.0
        self._hold = 0
        self._y = 0.0
        self.btn_close.hide()
        self.update()
        self.hide()

    def resizeEvent(self, event):  # noqa: N802（Qt 命名）
        super().resizeEvent(event)
        # × 钮贴右内边距垂直居中（不参与跑马灯绘制，故用子控件而非自绘）
        self.btn_close.move(
            max(0, self.width() - _CLOSE_SIZE - int(_PAD) // 2),
            max(0, (self.height() - _CLOSE_SIZE) // 2),
        )

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
        # 右侧预留给 × 钮（文本不钻到钮底下）
        return self.width() - _PAD * 2 - _CLOSE_RESERVE

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

        # G14：无边框浅底（原「面板底 + 1px 描边」= 输入框观感）；层级只靠底色差
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["btn"]))
        p.drawRoundedRect(r, 4, 4)

        if not self._text:
            p.end()
            return

        p.setFont(self._font)
        # 文本裁剪区右侧让出 × 钮占位（跑马灯不钻到关闭钮下）
        p.setClipRect(r.adjusted(1, 1, -1 - _CLOSE_RESERVE, -1))
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
