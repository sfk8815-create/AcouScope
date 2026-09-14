# SPDX-License-Identifier: GPL-3.0-only
"""批处理工作区框架层（Batch Workspace 平台骨架 · T-913）。

定位（ARCH_workbench_layout §四ter）：中央工作区「批处理模式」（波形随整页
隐藏、中间全区归批处理）是**通用平台**，容纳多个批处理功能模块；本模块只交付
平台骨架，**不实现任何具体批处理业务模块**（首个业务模块 = 批量元数据，由
T-914 单独交付并注册进来）。

组成：
1. `BaseBatchModule`：业务模块统一接口（name / build_config_ui / apply）。
2. 模块注册表：`register_module` / `registered_modules` / `activate_module`
   （最小可扩展机制，只做注册/枚举/激活；初始为空）。
3. `BatchWorkspace(QWidget)`：任务类型导航 + 待处理文件集区 + 参数与编辑宿主
   + 进度与结果报告 + [执行][退出]。公共组件与具体任务解耦。

中央接线（main_window）：`central_stack` index1 = 本工作区；进入/退出由外部
切换 index（波形随整页隐藏/恢复），本组件只发 `exitRequested` 信号。

样式走 theme.style_when_theme + colors()/TOKENS，i18n 走 tr()；
严禁硬编码 hex/px，禁新建 QDialog。
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme

# ---------------------------------------------------------------------------
# 模块抽象/接口（T-914 及未来模块实现此契约）
# ---------------------------------------------------------------------------


class BaseBatchModule:
    """批处理业务模块基类。

    - `name`: 模块唯一名称（导航展示文本，非空）。
    - `build_config_ui(parent) -> QWidget`: 参数/编辑区 UI；返回的控件由
      框架装入参数宿主（调用方保持引用即 params 载体）。
    - `apply(files, params, progress_cb) -> list[逐文件结果]`: 对文件集执行
      任务；`files` 为绝对路径 str 列表，`params` 为框架传入的配置控件，
      `progress_cb(str)` 上报进度文本；返回逐文件结果列表（元素可为 dict
      或可显示文本，框架按 dict['path']/['ok'] 兜底格式化）。
    """

    name: str = ""

    def build_config_ui(self, parent: QWidget) -> QWidget:
        """构建参数/编辑区 UI；未实现时抛 NotImplementedError。"""
        raise NotImplementedError

    def apply(self, files, params, progress_cb) -> list:
        """逐文件执行；未实现时抛 NotImplementedError。"""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 模块注册表（最小可扩展机制；初始为空 → 导航空态）
# ---------------------------------------------------------------------------

_REGISTRY: "OrderedDict[str, BaseBatchModule]" = OrderedDict()


def register_module(module: BaseBatchModule) -> BaseBatchModule:
    """注册一个模块（同名覆盖，保持插入序）。

    Args:
        module: BaseBatchModule 子类实例，name 非空。

    Returns:
        传入的 module（便于链式/断言）。
    """
    if not isinstance(module, BaseBatchModule):
        raise TypeError("模块须为 BaseBatchModule 实例")
    if not module.name:
        raise ValueError("模块 name 不能为空")
    _REGISTRY[module.name] = module
    return module


def registered_modules() -> list[BaseBatchModule]:
    """当前已注册模块列表（插入序）。"""
    return list(_REGISTRY.values())


def activate_module(name: str) -> BaseBatchModule | None:
    """按 name 取已注册模块；未注册返回 None。"""
    return _REGISTRY.get(name)


def clear_modules() -> None:
    """清空注册表（测试/工具用；与业务运行无关）。"""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# item data role：文件行存绝对路径、导航行存模块名
# ---------------------------------------------------------------------------

_ROLE_PATH = Qt.ItemDataRole.UserRole
_ROLE_NAME = Qt.ItemDataRole.UserRole


def _fmt_result(result) -> str:
    """逐文件结果通用兜底格式化（dict 优先 path/ok，其余转文本）。"""
    if isinstance(result, dict):
        path = result.get("path") or result.get("file") or ""
        ok = result.get("ok", result.get("success"))
        if ok is not None:
            mark = tr("batch.result_ok") if ok else tr("batch.result_fail")
            return f"{mark} {path}"
        return str(result)
    return str(result)


class BatchWorkspace(QWidget):
    """中央批处理工作区（框架通用 UI，与具体业务模块解耦）。

    信号：exitRequested（点 [退出] → 接线方切回常规页 index0）。
    """

    exitRequested = pyqtSignal()

    def __init__(self, manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("batchWorkspace")
        self._manager = manager
        self._active_module: BaseBatchModule | None = None
        self._config_ui: QWidget | None = None  # 当前模块 build_config_ui 产物
        # T-928：任务进度中心聚合观察者（None = 既有行为零变化）
        self._task_observer = None

        sp = theme.TOKENS["spacing"]
        root = QVBoxLayout(self)
        root.setContentsMargins(sp["md"], sp["md"], sp["md"], sp["md"])
        root.setSpacing(sp["sm"])

        # -- 顶部：标题 + [执行] + [退出] --
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(sp["sm"])
        self.title_lbl = QLabel(tr("batch.title"), self)
        self.title_lbl.setObjectName("batchTitle")
        header.addWidget(self.title_lbl)
        header.addStretch(1)
        self.btn_run = QPushButton(tr("batch.run"), self)
        self.btn_run.setObjectName("batchRunBtn")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.run_active)
        header.addWidget(self.btn_run)
        self.btn_exit = QPushButton(tr("batch.exit"), self)
        self.btn_exit.setObjectName("batchExitBtn")
        self.btn_exit.clicked.connect(self.exitRequested)
        header.addWidget(self.btn_exit)
        root.addLayout(header)

        # -- 主体：导航 | 文件集 | 参数宿主 | 进度与结果 --
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(sp["lg"])

        # 左列：任务类型导航 + 待处理文件集
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(sp["xs"])

        left.addWidget(self._group_label("batch.nav_title", "batchNavTitle"))
        self.nav_list = QListWidget(self)
        self.nav_list.setObjectName("batchNavList")
        self.nav_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.nav_list.itemClicked.connect(self._on_nav_clicked)
        left.addWidget(self.nav_list)
        self.lbl_nav_empty = QLabel(tr("batch.nav_empty"), self)
        self.lbl_nav_empty.setObjectName("batchNavEmpty")
        self.lbl_nav_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_nav_empty.hide()
        left.addWidget(self.lbl_nav_empty)

        left.addSpacing(sp["md"])
        left.addWidget(self._group_label("batch.files_title", "batchFilesTitle"))
        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(sp["xs"])
        self.btn_add = QPushButton(tr("batch.files_add"), self)
        self.btn_add.setObjectName("batchAddBtn")
        self.btn_add.clicked.connect(self._on_add_files)
        tools.addWidget(self.btn_add)
        self.btn_remove = QPushButton(tr("batch.files_remove"), self)
        self.btn_remove.setObjectName("batchRemoveBtn")
        self.btn_remove.clicked.connect(self.remove_selected)
        tools.addWidget(self.btn_remove)
        self.btn_check_all = QPushButton(tr("batch.files_check_all"), self)
        self.btn_check_all.setObjectName("batchCheckAllBtn")
        self.btn_check_all.clicked.connect(self.set_all_checked)
        tools.addWidget(self.btn_check_all)
        tools.addStretch(1)
        left.addLayout(tools)

        self.file_list = QListWidget(self)
        self.file_list.setObjectName("batchFileList")
        left.addWidget(self.file_list, stretch=1)
        self.lbl_files_empty = QLabel(tr("batch.files_empty"), self)
        self.lbl_files_empty.setObjectName("batchFilesEmpty")
        self.lbl_files_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_files_empty.hide()
        left.addWidget(self.lbl_files_empty)
        self._update_files_empty()  # 初始空态：列表隐藏、空态提示可见
        body.addLayout(left, 2)

        # 中列：参数与编辑宿主（当前模块 build_config_ui 容器）
        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(sp["xs"])
        center.addWidget(self._group_label("batch.param_title", "batchParamTitle"))
        self.param_host = QWidget(self)
        self.param_host.setObjectName("batchParamHost")
        self._ph_layout = QVBoxLayout(self.param_host)
        self._ph_layout.setContentsMargins(0, 0, 0, 0)
        self._ph_layout.setSpacing(sp["sm"])
        self.lbl_param_empty = QLabel(tr("batch.param_empty"), self.param_host)
        self.lbl_param_empty.setObjectName("batchParamEmpty")
        self.lbl_param_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_param_empty.setWordWrap(True)
        self._ph_layout.addWidget(self.lbl_param_empty)
        self._ph_layout.addStretch(1)
        center.addWidget(self.param_host, stretch=1)
        body.addLayout(center, 3)

        # 右列：进度与结果报告
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(sp["xs"])
        right.addWidget(self._group_label("batch.progress_title", "batchProgressTitle"))
        self.lbl_progress = QLabel("", self)
        self.lbl_progress.setObjectName("batchProgress")
        self.lbl_progress.setWordWrap(True)
        right.addWidget(self.lbl_progress)
        self.results_list = QListWidget(self)
        self.results_list.setObjectName("batchResultsList")
        right.addWidget(self.results_list, stretch=1)
        body.addLayout(right, 2)
        root.addLayout(body, 1)

        self._refresh_style = theme.style_when_theme(self, self._on_theme_refresh)
        self.refresh_modules()

    # ------------------------------------------------------------------
    # 小组件 helper
    # ------------------------------------------------------------------

    def _group_label(self, key: str, object_name: str) -> QLabel:
        lbl = QLabel(tr(key), self)
        lbl.setObjectName(object_name)
        return lbl

    def _on_theme_refresh(self, c: dict) -> str:
        """主题变化 → 重建 QSS（组标题/空态提示走主题角色，禁硬编码 hex）。"""
        cap = theme.TOKENS["typography"]["caption"]
        body_font = theme.TOKENS["typography"]["body"]
        sub = c["sub"]
        return (
            f"QLabel#batchTitle {{ font-size: {theme.TOKENS['typography']['h3']}px; }}"
            f"QLabel#batchNavTitle, QLabel#batchFilesTitle, "
            f"QLabel#batchParamTitle, QLabel#batchProgressTitle {{ "
            f"  color: {sub}; font-size: {cap}px; }}"
            f"QLabel#batchNavEmpty, QLabel#batchFilesEmpty, "
            f"QLabel#batchParamEmpty {{ color: {sub}; font-size: {body_font}px; }}"
            "QListWidget#batchNavList, QListWidget#batchFileList, "
            "QListWidget#batchResultsList {"
            f"  background: {c['panel']}; border: 1px solid {c['border']}; "
            f"  border-radius: {theme.TOKENS['radius']['sm']}px;"
            "}"
        )

    # ------------------------------------------------------------------
    # 管理器（入档状态判定用）
    # ------------------------------------------------------------------

    def set_manager(self, manager) -> None:
        """注入 ProjectManager（文件集各行『已入档/新登记』随其判定刷新）。"""
        self._manager = manager
        self._refresh_row_statuses()

    @property
    def manager(self):
        return self._manager

    # ------------------------------------------------------------------
    # 模块注册表 ↔ 导航联动
    # ------------------------------------------------------------------

    def refresh_modules(self) -> None:
        """从注册表重建导航列表（无模块 → 空态提示，无业务 UI）。"""
        self.nav_list.blockSignals(True)
        try:
            self.nav_list.clear()
            mods = registered_modules()
            empty = not mods
            self.nav_list.setVisible(not empty)
            self.lbl_nav_empty.setVisible(empty)
            self.lbl_nav_empty.setText(tr("batch.nav_empty"))
            for mod in mods:
                item = QListWidgetItem(mod.name)
                item.setData(_ROLE_NAME, mod.name)
                self.nav_list.addItem(item)
        finally:
            self.nav_list.blockSignals(False)
        # 激活模块被清出注册表时回退空态
        if self._active_module is not None and activate_module(self._active_module.name) is None:
            self._set_active(None)
        else:
            self._update_run_state()

    def _on_nav_clicked(self, item: QListWidgetItem) -> None:
        name = item.data(_ROLE_NAME)
        if name:
            self.activate(name)

    def activate(self, name: str) -> bool:
        """激活某模块：参数宿主装入其 config_ui；未注册返回 False。"""
        mod = activate_module(name)
        if mod is None:
            return False
        self._set_active(mod)
        return True

    def current_module(self) -> BaseBatchModule | None:
        return self._active_module

    def _set_active(self, mod: BaseBatchModule | None) -> None:
        """内部激活/清空：重挂参数宿主 + 同步导航选中 + 执行钮状态。"""
        self._active_module = mod
        self._mount_config(mod)
        if mod is None:
            self.nav_list.clearSelection()
        else:
            self.nav_list.blockSignals(True)
            try:
                for i in range(self.nav_list.count()):
                    it = self.nav_list.item(i)
                    if it.data(_ROLE_NAME) == mod.name:
                        self.nav_list.setCurrentRow(i)
                        break
            finally:
                self.nav_list.blockSignals(False)
        self._update_run_state()

    def _mount_config(self, mod: BaseBatchModule | None) -> None:
        """清空参数宿主并装入模块 config_ui（无模块 → 空态提示）。"""
        lay = self._ph_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._config_ui = None
        if mod is None:
            self.lbl_param_empty.setText(tr("batch.param_empty"))
            self.lbl_param_empty.setVisible(True)
            lay.addWidget(self.lbl_param_empty)
            lay.addStretch(1)
            return
        self.lbl_param_empty.setVisible(False)
        ui = mod.build_config_ui(self.param_host)
        self._config_ui = ui
        if ui is not None:
            lay.addWidget(ui)
        lay.addStretch(1)

    def _update_run_state(self) -> None:
        self.btn_run.setEnabled(self._active_module is not None)

    # ------------------------------------------------------------------
    # 待处理文件集区：增删 / 勾选 / 全选 + 入档状态
    # ------------------------------------------------------------------

    def add_paths(self, paths) -> None:
        """追加文件路径到待处理文件集（绝对路径去重；新行默认勾选）。"""
        existing = {self._path_of(i) for i in range(self.file_list.count())}
        added = 0
        self.file_list.blockSignals(True)
        try:
            for p in paths:
                raw = str(p)
                path = str(Path(raw).resolve()) if Path(raw).exists() else raw
                if path in existing:
                    continue
                existing.add(path)
                item = QListWidgetItem()
                item.setData(_ROLE_PATH, path)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                item.setCheckState(Qt.CheckState.Checked)
                self.file_list.addItem(item)
                added += 1
        finally:
            self.file_list.blockSignals(False)
        if added:
            self._refresh_row_statuses()
        self._update_files_empty()

    def set_files(self, paths) -> None:
        """整体替换文件集（批处理入口预载选中文件集用）。"""
        self.file_list.clear()
        self.lbl_files_empty.hide()
        if paths:
            self.add_paths(paths)
        else:
            self._update_files_empty()

    def remove_selected(self) -> None:
        """移除当前高亮选中的文件行。"""
        rows = sorted(
            (self.file_list.row(i) for i in self.file_list.selectedItems()),
            reverse=True,
        )
        for r in rows:
            self.file_list.takeItem(r)
        self._update_files_empty()

    def set_all_checked(self) -> None:
        """全选（全部勾选；逐行取消勾选 = 从执行集剔除）。"""
        for i in range(self.file_list.count()):
            self.file_list.item(i).setCheckState(Qt.CheckState.Checked)

    def included_paths(self) -> list[str]:
        """勾选中的文件路径列表（绝对路径 str，列表顺序）。"""
        return [
            self._path_of(i)
            for i in range(self.file_list.count())
            if self.file_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _path_of(self, row: int) -> str:
        item = self.file_list.item(row)
        return item.data(_ROLE_PATH) if item is not None else ""

    def _update_files_empty(self) -> None:
        empty = self.file_list.count() == 0
        self.file_list.setVisible(not empty)
        self.lbl_files_empty.setVisible(empty)
        self.lbl_files_empty.setText(tr("batch.files_empty"))

    def _refresh_row_statuses(self) -> None:
        """逐行显示入档状态（已入档/新登记；无 manager 时只显文件名）。"""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = item.data(_ROLE_PATH)
            name = Path(path).name if path else ""
            if self._manager is not None:
                status = (
                    tr("batch.status_archived")
                    if self._manager.get_file(path) is not None
                    else tr("batch.status_new")
                )
                name = f"{name}  ·  {status}"
            item.setText(name)

    def _on_add_files(self) -> None:
        """原生多选文件对话框追加到文件集（仅真机 GUI 触发；测试走 add_paths）。"""
        paths, _ = QFileDialog.getOpenFileNames(self, tr("batch.files_add"))
        if paths:
            self.add_paths(paths)

    # ------------------------------------------------------------------
    # 进度与结果报告 + 执行
    # ------------------------------------------------------------------

    def _on_progress(self, text) -> None:
        self.lbl_progress.setText(str(text))
        # T-928：进度文本透传任务进度中心（聚合条目阶段文本；无观察者则空操作）
        self._notify_task_observer("stage", text=str(text))

    # -- T-928：任务进度中心聚合桥接（最小接线；内联进度区保留为批处理明细） --

    def set_task_observer(self, observer) -> None:
        """注册任务进度聚合观察者。

        observer(event: str, payload: dict)，主线程调用；事件：
        `start`（files/module/n）、`stage`（text）、`finish`（ok/error）。
        `None` = 关闭桥接（既有行为零变化）。
        """
        self._task_observer = observer

    def _notify_task_observer(self, event: str, **payload) -> None:
        observer = self._task_observer
        if observer is None:
            return
        try:
            observer(event, payload)
        except Exception:  # noqa: BLE001 — 观察者异常不得影响批处理执行
            pass

    def run_active(self) -> None:
        """对勾选文件集执行当前模块 apply，结果写入结果区（无模块 → 空操作）。"""
        mod = self._active_module
        if mod is None:
            return
        files = self.included_paths()
        params = self._config_ui
        self.results_list.clear()
        self.lbl_progress.setText("")
        self.btn_run.setEnabled(False)
        self._notify_task_observer("start", files=list(files), module=mod.name,
                                   n=len(files))
        ok = False
        error = ""
        try:
            results = mod.apply(files, params, self._on_progress)
            for r in results or []:
                self.results_list.addItem(_fmt_result(r))
            self.lbl_progress.setText(tr("batch.run_done").format(n=len(files)))
            ok = True
        except Exception as exc:  # noqa: BLE001 — 模块执行异常不崩框架
            error = str(exc)
            msg = tr("batch.run_error") + " " + error
            self.results_list.addItem(msg)
            self.lbl_progress.setText(msg)
        finally:
            self.btn_run.setEnabled(mod is not None)
            self._notify_task_observer("finish", ok=ok, error=error)
