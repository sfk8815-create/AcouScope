# SPDX-License-Identifier: GPL-3.0-only
"""命令面板（T-1120）：主窗上的非模态浮层，模糊检索并执行既有 QAction。

宪法约束（`ARCH_ui_visual_language` §八）：**禁新增 QDialog / 模态** ⇒ 本件是
`Qt.WindowType.Popup` 浮层：点外部即关（Qt 内置）、Esc 关、Enter 执行；
无 `exec()`、无事件循环。取色与尺寸一律走 `theme` 令牌，零字面 hex/px。
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.command_index import (
    CommandEntry,
    collect_commands_with_actions,
    filter_commands,
)


class CommandPalette(QWidget):
    """模糊检索入口：输入即过滤，Enter 触发选中项。"""

    commandActivated = pyqtSignal(str)

    MAX_ROWS = 40
    WIDTH_RATIO = 0.55
    HEIGHT_RATIO = 0.55

    def __init__(self, host: QWidget):
        super().__init__(host, Qt.WindowType.Popup)
        self.setObjectName("commandPalette")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._host = host
        self._pairs: list[tuple[CommandEntry, object]] = []
        self._rows: list[tuple[CommandEntry, object]] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(*([int(theme.TOKENS["spacing"]["md"])] * 4))
        col.setSpacing(int(theme.TOKENS["spacing"]["sm"]))

        self.edit = QLineEdit(self)
        self.edit.setObjectName("commandPaletteInput")
        self.edit.setClearButtonEnabled(True)
        self.edit.installEventFilter(self)
        self.edit.textChanged.connect(self._refresh)
        self.edit.returnPressed.connect(self.activate_current)
        col.addWidget(self.edit)

        self.list = QListWidget(self)
        self.list.setObjectName("commandPaletteList")
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(lambda _item: self.activate_current())
        col.addWidget(self.list, 1)

        self.hint = QLabel(tr("command_palette.hint"), self)
        self.hint.setObjectName("commandPaletteHint")
        col.addWidget(self.hint)

        theme.style_when_theme(self, self._build_qss)
        self.hide()

    # ------------------------------------------------------------------
    # 展示 / 关闭
    # ------------------------------------------------------------------
    def show_over(self, entries=None) -> None:
        """采集命令（或注入条目）后浮在主窗中央。"""
        if entries is None:
            self._pairs = collect_commands_with_actions(self._host)
        else:
            self._pairs = list(entries)
        self.edit.setPlaceholderText(tr("command_palette.placeholder"))
        self.edit.clear()
        self._refresh("")
        self._place()
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def close_palette(self) -> None:
        self.hide()

    def _place(self) -> None:
        host = self._host
        win = host.window() if host is not None else self
        w = max(int(win.width() * self.WIDTH_RATIO), int(theme.TOKENS["spacing"]["xxl"]) * 10)
        h = max(int(win.height() * self.HEIGHT_RATIO), int(theme.TOKENS["spacing"]["xxl"]) * 6)
        center = win.mapToGlobal(win.rect().center())
        self.setGeometry(center.x() - w // 2, center.y() - h // 2, w, h)

    # ------------------------------------------------------------------
    # 过滤 / 执行
    # ------------------------------------------------------------------
    def _refresh(self, text: str) -> None:
        entries = [entry for entry, _act in self._pairs]
        matched = filter_commands(entries, text)[: self.MAX_ROWS]
        lookup = {id(entry): act for entry, act in self._pairs}
        self._rows = [(entry, lookup[id(entry)]) for entry in matched]

        self.list.clear()
        if not self._rows:
            item = QListWidgetItem(tr("command_palette.empty"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
            return
        row_h = (QFontMetrics(self.list.font()).height()
                 + 2 * int(theme.TOKENS["control"]["pad_y"]))
        for entry, _act in self._rows:
            label = f"{entry.text}    {entry.shortcut}" if entry.shortcut else entry.text
            item = QListWidgetItem(label)
            item.setToolTip(f"{entry.category} · {entry.text}" if entry.category else entry.text)
            item.setSizeHint(QSize(0, row_h))
            if not entry.enabled:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def activate_current(self) -> None:
        """触发当前选中项的 QAction 并关闭面板。"""
        row = self.list.currentRow()
        if row < 0 or row >= len(self._rows):
            return
        entry, act = self._rows[row]
        if not entry.enabled:
            return
        self.hide()
        if act is not None:
            act.trigger()
        self.commandActivated.emit(entry.text)

    # ------------------------------------------------------------------
    # 键盘 / 主题
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 (Qt 命名)
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if key == Qt.Key.Key_Down else -1
                count = self.list.count()
                if count:
                    self.list.setCurrentRow(
                        max(0, min(count - 1, self.list.currentRow() + step)))
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802 (Qt 命名)
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def _build_qss(self, c: dict) -> str:
        t = theme.TOKENS
        radius = int(t["radius"]["md"])
        pad = int(t["control"]["pad_x"])
        return (
            "QWidget#commandPalette {"
            f"  background: {c['bg1']};"
            f"  border: {int(t['elevation']['border'])}px solid {c['border_strong']};"
            f"  border-radius: {radius}px;"
            "}"
            "QLineEdit#commandPaletteInput {"
            f"  background: {c['bg0']}; color: {c['text']};"
            f"  border: {int(t['elevation']['border'])}px solid {c['border']};"
            f"  border-radius: {int(t['radius']['sm'])}px;"
            f"  padding: {int(t['control']['pad_y'])}px {pad}px;"
            "}"
            "QLineEdit#commandPaletteInput:focus {"
            f"  border-color: {c['accent']};"
            "}"
            "QListWidget#commandPaletteList {"
            f"  background: transparent; color: {c['text']};"
            f"  border: none; outline: 0;"
            "}"
            "QListWidget#commandPaletteList::item {"
            f"  padding: {int(t['control']['pad_y'])}px {pad}px;"
            f"  border-radius: {int(t['radius']['sm'])}px;"
            "}"
            "QListWidget#commandPaletteList::item:selected {"
            f"  background: {c['sel_bg']}; color: {c['text']};"
            "}"
            "QLabel#commandPaletteHint {"
            f"  color: {c['text_sub']};"
            f"  font-size: {int(t['typography']['caption'])}px;"
            "}"
        )
