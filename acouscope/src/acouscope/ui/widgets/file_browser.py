# SPDX-License-Identifier: GPL-3.0-only
"""FileBrowser：文件管理器（左抽屉内容组件，T-910）。

显示**项目文件夹的所有文件**（本目录平铺；子目录导航属 T-915 候选，不列目录行）：
- 支持格式（`audio/io.py AudioIO.SUPPORTED_FORMATS`）→ 正常前景色；
  不支持格式 → 次级灰（theme `sub` 角色，禁硬编码 hex）。
- 选中/多选信号（下游契约）：
  - 点选单个 → `fileSelected(path)`（T-912 检查器据此加载单文件元数据）
  - 多选（Ctrl/Shift）→ `selectionChanged(paths)`（T-913/T-914 批处理文件集）
  - 双击/回车 → `fileActivated(path)`（接线方调 controller.open_file；
    本组件不 import main_window、不直接耦合 controller）
- 右键菜单：打开 / 在 Finder 显示（QDesktopServices）/ 从项目移除
  （`ProjectManager.remove_file`，已入档才可用）+「批处理…」（T-913 框架级
  入口，触发 → `batchRequested(paths)` 预载文件集进批处理工作区）+
  `addContextAction(text, slot)` 扩展点（T-914 据此追加「批量更改元数据…」）。
- 入档标识：已入 `Project.files` 的文件名尾追加 "✓"（经
  `ProjectManager.get_file(path)` 判定，T-907；仅视觉标识）。
- 目录源解析（架构定案）：有项目（manager.filepath 非空）→ filepath.parent；
  无项目但打开过音频（current_file）→ current_file.parent；皆无 → 空态提示。
- `refresh()`：重列目录并尽力保留选中（按路径匹配）。

样式走 theme.style_when_theme + colors()/TOKENS，严禁硬编码 hex/px。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QBrush
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from acouscope.audio.io import AudioIO
from acouscope.i18n import tr
from acouscope.ui import theme

# 入档标识（文件名尾角标，仅视觉；与侧栏“就绪/归档”同形标记一致）
_IN_PROJECT_MARK = "✓"

# item data role：UserRole+0 = 绝对路径 str；UserRole+1 = 是否支持格式 bool
_ROLE_PATH = Qt.ItemDataRole.UserRole
_ROLE_SUPPORTED = Qt.ItemDataRole.UserRole + 1


class FileBrowser(QWidget):
    """文件管理器：项目文件夹平铺列表 + 选中/多选信号 + 右键扩展点。"""

    fileSelected = pyqtSignal(str)      # 点选单个文件 → 绝对路径
    selectionChanged = pyqtSignal(list)  # 选中集合变化 → [绝对路径, ...]
    fileActivated = pyqtSignal(str)      # 双击/回车/右键「打开」→ 绝对路径
    batchRequested = pyqtSignal(list)    # 右键「批处理…」→ 右键目标文件集（T-913）

    def __init__(self, manager=None, current_file: str | Path | None = None, parent=None):
        """
        Args:
            manager: ProjectManager（可注入；None 时不判定入档、移除项不可用）。
            current_file: 最近打开的音频路径（无项目时的目录回退源，可 None）。
            parent: 父控件。
        """
        super().__init__(parent)
        self._manager = manager
        self._current_file: Path | None = (
            Path(current_file) if current_file is not None else None
        )
        self._extra_actions: list[QAction] = []  # addContextAction 扩展点

        sp = theme.TOKENS["spacing"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp["xs"], sp["xs"], sp["xs"], sp["xs"])
        layout.setSpacing(sp["xs"])

        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.list)

        self._lbl_empty = QLabel(self)
        self._lbl_empty.hide()
        layout.addWidget(self._lbl_empty)

        # 信号接线（内部处理，见 _on_*）
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(self._on_item_activated)
        self.list.customContextMenuRequested.connect(self._on_context_menu)

        # 样式注册：随主题刷新（含逐 item 前景色重刷，严禁硬编码 hex）
        self._refresh_style = theme.style_when_theme(self, self._on_theme_refresh)

        self.refresh()

    # ------------------------------------------------------------------
    # 目录源（架构定案规则）
    # ------------------------------------------------------------------

    def set_manager(self, manager) -> None:
        """更新 ProjectManager 引用（接线方在项目切换后调用），触发 refresh。"""
        self._manager = manager
        self.refresh()

    def set_current_file(self, current_file: str | Path | None) -> None:
        """更新最近打开音频路径（接线方在打开文件后调用），触发 refresh。"""
        self._current_file = (
            Path(current_file) if current_file is not None else None
        )
        self.refresh()

    def _resolve_directory(self) -> Path | None:
        """有项目 → .acouproj 所在目录；无项目有音频 → 音频所在目录；皆无 → None。"""
        if self._manager is not None and self._manager.filepath is not None:
            return Path(self._manager.filepath).parent
        if self._current_file is not None:
            return self._current_file.parent
        return None

    # ------------------------------------------------------------------
    # 列表与刷新
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """重列目录（尽力保留选中：按绝对路径匹配）。"""
        directory = self._resolve_directory()
        prev_selected = self.selected_paths()

        self.list.blockSignals(True)
        try:
            self.list.clear()
            if directory is None or not directory.is_dir():
                self._show_empty(True)
                return
            self._show_empty(False)
            for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
                if not entry.is_file():
                    continue  # 本任务只列本目录文件（子目录导航属 T-915）
                path = entry.resolve()
                supported = path.suffix.lower() in AudioIO.SUPPORTED_FORMATS
                item = QListWidgetItem(path.name)
                item.setData(_ROLE_PATH, str(path))
                item.setData(_ROLE_SUPPORTED, supported)
                self.list.addItem(item)
            self._mark_in_project()
            # 尽力恢复选中（仅命中现存路径者）
            existing = {self._path_of(i) for i in range(self.list.count())}
            restore = [p for p in prev_selected if p in existing]
            if restore:
                self._select_paths(restore)
        finally:
            self.list.blockSignals(False)

        # 选中恢复在 blockSignals 内完成（不重复发信号）；颜色/样式随主题重刷
        self._apply_item_colors()
        self._refresh_style()

    def _show_empty(self, empty: bool) -> None:
        """空态提示（无项目且无打开文件）与列表互斥显隐。"""
        self._lbl_empty.setText(tr("file_browser.empty"))
        self._lbl_empty.setVisible(empty)
        self.list.setVisible(not empty)

    def _mark_in_project(self) -> None:
        """已入 Project.files 的文件名尾追加 "✓"（get_file 判定，T-907；仅视觉）。"""
        if self._manager is None:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = item.data(_ROLE_PATH)
            if self._manager.get_file(path) is not None:
                item.setText(Path(path).name + "  " + _IN_PROJECT_MARK)

    def _apply_item_colors(self) -> None:
        """支持格式 → 正文色；不支持 → 次级灰（主题角色，随主题重刷）。"""
        c = theme.colors()
        text_color = QColor(c["text"])
        sub_color = QColor(c["sub"])
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setForeground(
                QBrush(text_color if item.data(_ROLE_SUPPORTED) else sub_color)
            )

    def _path_of(self, index: int) -> str | None:
        item = self.list.item(index)
        return item.data(_ROLE_PATH) if item is not None else None

    def selected_paths(self) -> list[str]:
        """当前选中项的绝对路径列表（按列表顺序）。"""
        return [it.data(_ROLE_PATH) for it in self.list.selectedItems()]

    def _select_paths(self, paths: list[str]) -> None:
        wanted = set(paths)
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setSelected(item.data(_ROLE_PATH) in wanted)

    # ------------------------------------------------------------------
    # 信号内部处理（下游契约）
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(_ROLE_PATH)
        if path is not None:
            self.fileSelected.emit(path)

    def _on_selection_changed(self) -> None:
        self.selectionChanged.emit(self.selected_paths())

    def _on_item_activated(self, item: QListWidgetItem | None) -> None:
        """双击 → fileActivated（以发出项为准；无则回退当前项）。"""
        if item is None:
            self._activate_current()
            return
        path = item.data(_ROLE_PATH)
        if path is not None:
            self.fileActivated.emit(path)

    def _activate_current(self) -> None:
        item = self.list.currentItem()
        if item is None and self.list.count() > 0:
            item = self.list.item(0)
        if item is not None:
            self.fileActivated.emit(item.data(_ROLE_PATH))

    def keyPressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        """回车/Return → fileActivated（与双击同语义）。"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate_current()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # 右键菜单（常规项 + 「批处理…」占位 + addContextAction 扩展点）
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        # IM-26（β 选中归一）：右键落在**未选中**项时先归一选中，使
        # selected_paths() ≡ 即时 paths ≡ 批处理目标（扩展点 slot 自读
        # selected_paths()）→ 三向一致；多选内右键（已选中）跳过、不降级。
        if item is not None and not item.isSelected():
            self.list.clearSelection()
            item.setSelected(True)
        paths = self.selected_paths() if (
            item is not None and item.isSelected()
        ) else ([item.data(_ROLE_PATH)] if item is not None else [])
        if not paths:
            return

        menu = QMenu(self)
        act_open = QAction(tr("file_browser.open"), self)
        act_open.triggered.connect(
            lambda _checked=False: self.fileActivated.emit(paths[0])
        )
        menu.addAction(act_open)

        act_reveal = QAction(tr("file_browser.reveal"), self)
        act_reveal.triggered.connect(
            lambda _checked=False: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(paths[0]).parent))
            )
        )
        menu.addAction(act_reveal)

        in_project = self._manager is not None and all(
            self._manager.get_file(p) is not None for p in paths
        )
        act_remove = QAction(tr("file_browser.remove"), self)
        act_remove.setEnabled(in_project)
        act_remove.triggered.connect(
            lambda _checked=False: self._remove_from_project(paths)
        )
        menu.addAction(act_remove)

        menu.addSeparator()

        # 框架级入口（T-913 接线）：进入批处理工作区并预载右键目标文件集；
        # 具体业务项（如「批量更改元数据…」）由 T-914 经 addContextAction 追加。
        act_batch = QAction(tr("file_browser.batch"), self)
        act_batch.triggered.connect(
            lambda _checked=False: self.batchRequested.emit(list(paths))
        )
        menu.addAction(act_batch)

        # 扩展点：T-914 等经 addContextAction 追加的项
        for action in self._extra_actions:
            menu.addAction(action)

        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _remove_from_project(self, paths: list[str]) -> None:
        """右键「从项目移除」：逐路径 remove_file（T-907）+ 重列。"""
        if self._manager is None:
            return
        for p in paths:
            self._manager.remove_file(p)
        self.refresh()

    def addContextAction(self, text: str, slot) -> QAction:
        """右键菜单扩展点：追加自定义项（T-914「批量更改元数据…」入口）。

        Args:
            text: 菜单项文本（调用方自行 i18n）。
            slot: 触发回调（无参；作用对象由接线方经 selected_paths() 取）。

        Returns:
            创建的 QAction（可后续 setEnabled 等调整）。
        """
        action = QAction(text, self)
        action.triggered.connect(lambda _checked=False: slot())
        self._extra_actions.append(action)
        return action

    # ------------------------------------------------------------------
    # 样式（theme 令牌，严禁硬编码 hex/px）
    # ------------------------------------------------------------------

    def _on_theme_refresh(self, c: dict) -> str:
        """主题变化 → 逐 item 前景色重刷 + 重建 QSS（builder 副作用）。"""
        self._apply_item_colors()
        return self._build_qss(c)

    def _build_qss(self, c: dict) -> str:
        """列表 QSS：选中底/悬停底走主题角色；字体走 TOKENS 字阶。"""
        rad = theme.TOKENS["radius"]
        body_font = theme.TOKENS["typography"]["body"]
        sm = theme.TOKENS["spacing"]["sm"]
        return (
            "QListWidget {"
            f"  background: transparent; "
            f"  color: {c['text']}; "
            f"  border: none; "
            f"  font-size: {body_font}px;"
            "}"
            "QListWidget::item {"
            f"  padding: {theme.TOKENS['spacing']['xxs']}px "
            f"{sm}px; "
            f"  border-radius: {rad['sm']}px;"
            "}"
            "QListWidget::item:hover {"
            f"  background: {c['btn_hover']};"
            "}"
            "QListWidget::item:selected {"
            f"  background: {c['sel_bg']}; "
            f"  color: {c['text']};"
            "}"
            "QLabel {"
            f"  color: {c['sub']}; "
            f"  font-size: {body_font}px;"
            "}"
        )
