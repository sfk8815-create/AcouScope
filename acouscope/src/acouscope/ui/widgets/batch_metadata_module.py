# SPDX-License-Identifier: GPL-3.0-only
"""批量更改元数据模块（Batch Workspace 首个业务模块 · T-914）。

定位：T-913 交付的批处理工作区框架（`batch_workspace.py`）只是**通用平台**；
本模块是该平台的**首个业务模块**——用户在文件管理器多选音频 → 右键「批量更改
元数据…」→ 进入批处理工作区**并激活本模块**。

核心设计问题（项目负责人）：**如何批量减少输入量又保证填报质量**。三步页：
1. 范围与标准：复用框架文件集区带入的文件；明示 N（勾选）/新登记 X/已入档 Y；
   标准下拉 3 项 + 说明区（文案照抄，i18n 键与 T-912 检查器元数据区**复用同一批键**，
   避免双份维护、保证两处口径逐字一致）。
2. 批量字段：共同字段一次填写 → 应用全部文件；技术元数据**逐文件自动提取、只读**；
   题名三种方式（文件名/统一前缀+文件名/逐条编辑）；标识符按规则自动生成（含序号）。
3. 核对与应用：逐文件核对清单（文件名 | 题名 | 技术元数据（只读）| 将写入的元数据摘要
   | 空字段警告），题名可逐行微调；责任者空 → 拦截；「应用并完成」→ 逐文件写
   `ProjectFile.metadata`（含 `_standard`）→ 结果交框架报告区 → 回常规页。

标准依据（只引用、不自行解读）：`内部记录/knowledge/METADATA_standards_mapping.md`；
未覆盖字段一律标"自定义扩展（非标准元素）"，禁宣称"符合/覆盖标准"。

契约（以 T-913 已交付 API 为准）：
- `name` / `build_config_ui(parent)` / `apply(files, params, progress_cb)`；
- `apply` 的 `files` = 框架勾选行绝对路径（`BatchWorkspace.included_paths()`）；
  `params` = 本模块 `build_config_ui()` 返回的控件本体（本模块用自身状态，忽略它）；
  `progress_cb(str)` 直连框架进度标签；返回 `[{"path":…, "ok":bool, "reason":…}]`
  （框架 `_fmt_result` 依 `path`/`ok` 格式化）。
- 登记途径：**只用框架注入的 `BatchWorkspace.manager`**
  （MainWindow 进入批处理页时已 `set_manager(controller.project)`）；
  禁自建 ProjectManager、禁直连 controller。缺条目 → `add_file`（T-907 约束 1）。

样式走 theme.TOKENS（禁硬编码 hex/px），i18n 走 tr()，禁新建 QDialog。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from acouscope.audio.io import AudioIO
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.batch_workspace import BaseBatchModule

# 模块名 i18n 键（导航文本；MainWindow 接线处经 module_name() 取当前语言名）
MODULE_NAME_KEY = "batch.meta.module_name"

# 标准下拉：(落盘代码, 下拉文本键, 说明区键)；与 T-912 检查器元数据区同一批 i18n 键
_STANDARDS = (
    ("DAT63", "inspector.meta.std_dat", "inspector.meta.desc_dat"),
    ("GBT31219.4", "inspector.meta.std_gbt", "inspector.meta.desc_gbt"),
    ("custom", "inspector.meta.std_custom", "inspector.meta.desc_custom"),
)
_DEFAULT_STANDARD = "custom"

# 字段键 = ProjectFile.metadata 键（同 annotation/metadata.py FIELD_TERMS.key）
_TECH_KEYS = ("SamplingRate", "BitDepth", "Format", "Channels", "Duration")
_MANUAL_KEYS = (
    "Title", "Creator", "Identifier", "Date",
    "Recorder", "Location", "GenreContext", "ActorRole",
)
_FIELD_KEYS = _MANUAL_KEYS + _TECH_KEYS

# 题名方式（下拉顺序）
_TITLE_MODE_FILE = 0
_TITLE_MODE_PREFIX = 1
_TITLE_MODE_MANUAL = 2

# 核对清单列序
_COL_FILE = 0
_COL_TITLE = 1
_COL_TECH = 2
_COL_SUMMARY = 3
_COL_WARN = 4

# 步骤页序
_PAGE_SCOPE = 0
_PAGE_FIELDS = 1
_PAGE_REVIEW = 2
_PAGE_COUNT = 3

_PLACEHOLDER = "—"


def module_name() -> str:
    """模块名（当前语言）。"""
    return tr(MODULE_NAME_KEY)


def _fmt_hms(seconds) -> str:
    """时长（秒）→ hh:mm:ss（DA/T M17 口径；负数截 0）。"""
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _file_mtime(p: Path) -> datetime | None:
    """文件 mtime → 本地 datetime；stat 失败回 None（不抛）。"""
    try:
        return datetime.fromtimestamp(p.stat().st_mtime)
    except OSError:
        return None


def _fmt_file_date(p: Path) -> str:
    """单文件采集日期初值 = 文件时间戳（DA/T M14 系统自动提取口径）。"""
    dt = _file_mtime(p)
    return dt.strftime("%Y-%m-%d") if dt is not None else ""


def _fmt_file_mtime(p: Path) -> str:
    """单文件时间戳（范围显示用）。"""
    dt = _file_mtime(p)
    return dt.strftime("%Y-%m-%d %H:%M") if dt is not None else ""


def _readonly(item: QTableWidgetItem) -> QTableWidgetItem:
    """表格项设为只读（保留可选/可复制）。"""
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


class MetadataBatchModule(BaseBatchModule):
    """批量更改元数据：三步页 + 逐文件写 metadata（实现 BaseBatchModule）。

    Args:
        workspace: 框架 `BatchWorkspace` 实例（读勾选文件集 `included_paths()` +
            框架注入的 `manager`）。为 None 时仅可独立调用 `apply()`（无文件集/无登记）。
    """

    def __init__(self, workspace=None):
        super().__init__()
        self._ws = workspace
        self.name = module_name()

        # 跨 UI 重建（每次激活重挂 config_ui）持久化的编辑状态
        self._state: dict[str, str] = {
            "standard": _DEFAULT_STANDARD,
            "title_mode": str(_TITLE_MODE_FILE),
            "prefix": "",
            "id_prefix": "",
            "date": "",
            "creator": "",
            "recorder": "",
            "location": "",
            "genre": "",
            "actor_role": "",
        }
        # 逐行题名微调（path → 文本）；空文本 = 回退默认题名（兜底）
        self._title_overrides: dict[str, str] = {}
        self._last_results: list[dict] = []
        self._page = _PAGE_SCOPE

        # 控件引用（build_config_ui 后有效）
        self.ui: QWidget | None = None
        self.stack: QStackedWidget | None = None
        self.step_chips: list[QLabel] = []
        self.standard_combo: QComboBox | None = None
        self.desc_label: QLabel | None = None
        self.scope_summary_label: QLabel | None = None
        self.creator_edit: QLineEdit | None = None
        self.recorder_edit: QLineEdit | None = None
        self.date_edit: QLineEdit | None = None
        self.date_range_label: QLabel | None = None
        self.location_edit: QLineEdit | None = None
        self.genre_edit: QLineEdit | None = None
        self.actor_role_edit: QLineEdit | None = None
        self.title_mode_combo: QComboBox | None = None
        self.prefix_edit: QLineEdit | None = None
        self.id_prefix_edit: QLineEdit | None = None
        self.review_table: QTableWidget | None = None
        self.status_label: QLabel | None = None
        self.warn_label: QLabel | None = None
        self.btn_prev: QPushButton | None = None
        self.btn_next: QPushButton | None = None
        self.btn_apply: QPushButton | None = None
        self.btn_cancel: QPushButton | None = None

    # ------------------------------------------------------------------
    # 框架/接线接口
    # ------------------------------------------------------------------

    def set_workspace(self, workspace) -> None:
        """注入框架工作区（绑定文件集与 manager 来源）。"""
        self._ws = workspace

    def manager(self):
        """框架注入的 ProjectManager（登记途径唯一；无 → None）。"""
        return getattr(self._ws, "manager", None) if self._ws is not None else None

    def current_paths(self) -> list[str]:
        """本次待处理文件（框架勾选行绝对路径）。"""
        if self._ws is None:
            return []
        return [str(p) for p in self._ws.included_paths()]

    def refresh(self) -> None:
        """刷新范围摘要 + 核对清单（文件集/入档状态变化后调用）。"""
        self._refresh_scope()
        self._refresh_review()

    # ------------------------------------------------------------------
    # ① 范围与标准（config_ui 三步页装配）
    # ------------------------------------------------------------------

    def build_config_ui(self, parent: QWidget) -> QWidget:
        """构建三步页（页面内 QStackedWidget + 顶部步骤条 + 底部操作）。"""
        sp = theme.TOKENS["spacing"]
        root = QWidget(parent)
        root.setObjectName("metaBatchConfig")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(sp["sm"])

        # 顶部步骤条
        steps = QHBoxLayout()
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setSpacing(sp["sm"])
        self.step_chips = []
        for key in ("batch.meta.step1", "batch.meta.step2", "batch.meta.step3"):
            chip = QLabel(tr(key), root)
            chip.setObjectName("metaStepChip")
            steps.addWidget(chip)
            self.step_chips.append(chip)
        steps.addStretch(1)
        root_layout.addLayout(steps)

        self.stack = QStackedWidget(root)
        self.stack.setObjectName("metaStepStack")
        self.stack.addWidget(self._build_scope_page(root))
        self.stack.addWidget(self._build_fields_page(root))
        self.stack.addWidget(self._build_review_page(root))
        root_layout.addWidget(self.stack, 1)

        # 底部操作行：[上一步][下一步] / [应用并完成][取消并退出]
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(sp["sm"])
        self.btn_prev = QPushButton(tr("batch.meta.prev"), root)
        self.btn_prev.setObjectName("metaPrevButton")
        self.btn_prev.clicked.connect(self._on_prev)
        self.btn_next = QPushButton(tr("batch.meta.next"), root)
        self.btn_next.setObjectName("metaNextButton")
        self.btn_next.clicked.connect(self._on_next)
        self.btn_apply = QPushButton(tr("batch.meta.apply"), root)
        self.btn_apply.setObjectName("metaApplyButton")
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_cancel = QPushButton(tr("batch.meta.cancel"), root)
        self.btn_cancel.setObjectName("metaCancelButton")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.warn_label = QLabel("", root)
        self.warn_label.setObjectName("metaWarnLabel")
        self.warn_label.setWordWrap(True)
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.btn_next)
        bottom.addWidget(self.warn_label, 1)
        bottom.addWidget(self.btn_apply)
        bottom.addWidget(self.btn_cancel)
        root_layout.addLayout(bottom)

        self.ui = root
        self._goto(_PAGE_SCOPE)
        return root

    def _group_label(self, text: str, page: QWidget) -> QLabel:
        lbl = QLabel(text, page)
        lbl.setObjectName("metaGroupTitle")
        return lbl

    def _build_scope_page(self, parent: QWidget) -> QWidget:
        sp = theme.TOKENS["spacing"]
        page = QWidget(parent)
        page.setObjectName("metaScopePage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sp["sm"])

        lay.addWidget(self._group_label(tr("batch.meta.scope_standard"), page))
        self.standard_combo = QComboBox(page)
        self.standard_combo.setObjectName("metaStandardCombo")
        for code, label_key, _desc_key in _STANDARDS:
            self.standard_combo.addItem(tr(label_key), code)
        self.standard_combo.currentIndexChanged.connect(self._on_standard_changed)
        self.standard_combo.setCurrentIndex(self._standard_index(self._state["standard"]))
        lay.addWidget(self.standard_combo)

        self.desc_label = QLabel("", page)
        self.desc_label.setObjectName("metaStandardDesc")
        self.desc_label.setWordWrap(True)
        lay.addWidget(self.desc_label)

        self.scope_summary_label = QLabel("", page)
        self.scope_summary_label.setObjectName("metaScopeSummary")
        self.scope_summary_label.setWordWrap(True)
        lay.addWidget(self.scope_summary_label)

        note = QLabel(tr("batch.meta.scope_note"), page)
        note.setObjectName("metaScopeNote")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)

        self._sync_desc()
        self._refresh_scope()
        return page

    def _standard_index(self, code: str) -> int:
        """标准代码 → 下拉下标；未知回默认。"""
        for i, (c, _l, _d) in enumerate(_STANDARDS):
            if c == code:
                return i
        return 0

    def _standard_code(self) -> str:
        """当前标准代码（控件缺失回默认）。"""
        if self.standard_combo is None:
            return self._state["standard"]
        data = self.standard_combo.currentData()
        return str(data) if data is not None else _DEFAULT_STANDARD

    def _sync_desc(self) -> None:
        """说明区文案随当前标准（i18n 照抄，禁改写）。"""
        if self.desc_label is None or self.standard_combo is None:
            return
        idx = self.standard_combo.currentIndex()
        if 0 <= idx < len(_STANDARDS):
            self.desc_label.setText(tr(_STANDARDS[idx][2]))

    def _on_standard_changed(self, index: int) -> None:
        """标准切换 → 记录状态 + 说明区随动。"""
        if 0 <= index < len(_STANDARDS):
            self._state["standard"] = _STANDARDS[index][0]
        self._sync_desc()

    def _refresh_scope(self) -> None:
        """① 范围摘要：N（勾选）/新登记 X/已入档 Y（入档经框架 manager 判定）。"""
        if self.scope_summary_label is None:
            return
        paths = self.current_paths()
        manager = self.manager()
        archived = sum(
            1 for p in paths
            if manager is not None and manager.get_file(p) is not None
        )
        self.scope_summary_label.setText(
            tr("batch.meta.scope_summary").format(
                n=len(paths), new=len(paths) - archived, archived=archived
            )
        )

    # ------------------------------------------------------------------
    # ② 批量字段
    # ------------------------------------------------------------------

    def _build_fields_page(self, parent: QWidget) -> QWidget:
        sp = theme.TOKENS["spacing"]
        page = QWidget(parent)
        page.setObjectName("metaFieldsPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sp["sm"])

        # -- 共同字段（一次填写，应用全部文件）--
        lay.addWidget(self._group_label(tr("batch.meta.common_title"), page))
        common = QFormLayout()
        common.setContentsMargins(0, 0, 0, 0)
        common.setSpacing(sp["xxs"])
        self.creator_edit = self._add_row(
            common, page, "creator", "inspector.meta.creator", suffix=" *"
        )
        self.recorder_edit = self._add_row(
            common, page, "recorder", "batch.meta.recorder"
        )
        self.date_edit = self._add_row(
            common, page, "date", "inspector.meta.date",
            placeholder=tr("batch.meta.date_placeholder"),
        )
        lay.addLayout(common)
        self.date_range_label = QLabel("", page)
        self.date_range_label.setObjectName("metaDateRange")
        self.date_range_label.setWordWrap(True)
        lay.addWidget(self.date_range_label)

        # -- 标准外字段（自定义扩展（非标准元素），诚实标注）--
        lay.addWidget(self._group_label(tr("inspector.meta.custom_note"), page))
        custom = QFormLayout()
        custom.setContentsMargins(0, 0, 0, 0)
        custom.setSpacing(sp["xxs"])
        self.location_edit = self._add_row(
            custom, page, "location", "inspector.meta.location"
        )
        self.genre_edit = self._add_row(
            custom, page, "genre", "inspector.meta.genre_context"
        )
        self.actor_role_edit = self._add_row(
            custom, page, "actor_role", "inspector.meta.actor_role"
        )
        lay.addLayout(custom)

        # -- 题名方式 --
        lay.addWidget(self._group_label(tr("batch.meta.title_mode"), page))
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(sp["xs"])
        self.title_mode_combo = QComboBox(page)
        self.title_mode_combo.setObjectName("metaTitleModeCombo")
        for key in (
            "batch.meta.title_mode_file",
            "batch.meta.title_mode_prefix",
            "batch.meta.title_mode_manual",
        ):
            self.title_mode_combo.addItem(tr(key))
        self.title_mode_combo.setCurrentIndex(int(self._state["title_mode"]))
        self.title_mode_combo.currentIndexChanged.connect(self._on_title_mode_changed)
        title_row.addWidget(self.title_mode_combo)
        self.prefix_edit = QLineEdit(page)
        self.prefix_edit.setObjectName("metaPrefixEdit")
        self.prefix_edit.setText(self._state["prefix"])
        self.prefix_edit.setPlaceholderText(tr("batch.meta.prefix"))
        self.prefix_edit.textChanged.connect(
            lambda text: self._state.__setitem__("prefix", text)
        )
        title_row.addWidget(self.prefix_edit, 1)
        lay.addLayout(title_row)

        # -- 标识符/档号（按规则自动生成，含序号）--
        lay.addWidget(self._group_label(tr("batch.meta.identifier_prefix"), page))
        id_row = QHBoxLayout()
        id_row.setContentsMargins(0, 0, 0, 0)
        id_row.setSpacing(sp["xs"])
        self.id_prefix_edit = QLineEdit(page)
        self.id_prefix_edit.setObjectName("metaIdPrefixEdit")
        self.id_prefix_edit.setText(self._state["id_prefix"])
        self.id_prefix_edit.setPlaceholderText(tr("batch.meta.id_prefix_placeholder"))
        self.id_prefix_edit.textChanged.connect(
            lambda text: self._state.__setitem__("id_prefix", text)
        )
        id_row.addWidget(self.id_prefix_edit, 1)
        lay.addLayout(id_row)
        id_hint = QLabel(tr("batch.meta.identifier_hint"), page)
        id_hint.setObjectName("metaIdHint")
        id_hint.setWordWrap(True)
        lay.addWidget(id_hint)

        # -- 技术元数据（逐文件自动提取、只读，绝不手填）--
        lay.addWidget(self._group_label(tr("batch.meta.tech_title"), page))
        tech_note = QLabel(tr("batch.meta.tech_note"), page)
        tech_note.setObjectName("metaTechNote")
        tech_note.setWordWrap(True)
        lay.addWidget(tech_note)

        lay.addStretch(1)
        self._sync_prefix_enabled()
        return page

    def _add_row(
        self,
        form: QFormLayout,
        page: QWidget,
        state_key: str,
        label_key: str,
        suffix: str = "",
        placeholder: str = "",
    ) -> QLineEdit:
        """按字段键追加一行（标签 i18n；文本变化即存模块状态，UI 重建不丢）。"""
        lab = QLabel(tr(label_key) + suffix, page)
        lab.setObjectName("metaFieldLabel")
        edit = QLineEdit(page)
        edit.setObjectName("metaLineEdit")
        edit.setText(self._state.get(state_key, ""))
        if placeholder:
            edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(
            lambda text, key=state_key: self._state.__setitem__(key, text)
        )
        form.addRow(lab, edit)
        return edit

    def _sync_prefix_enabled(self) -> None:
        """题名方式②才启用统一前缀输入。"""
        if self.prefix_edit is not None and self.title_mode_combo is not None:
            self.prefix_edit.setEnabled(
                self.title_mode_combo.currentIndex() == _TITLE_MODE_PREFIX
            )

    def _on_title_mode_changed(self, index: int) -> None:
        self._state["title_mode"] = str(index)
        self._sync_prefix_enabled()
        if self._page == _PAGE_REVIEW:
            self._refresh_review()

    def _title_for(self, path: Path) -> str:
        """题名：逐行微调优先 → 统一前缀+文件名 → 文件名（去扩展名）；空则兜底文件名。"""
        stem = path.stem
        override = self._title_overrides.get(str(path))
        if override is not None:
            candidate = override
        elif int(self._state["title_mode"]) == _TITLE_MODE_PREFIX:
            candidate = f"{self._state['prefix']}{stem}"
        else:
            candidate = stem
        return candidate.strip() or stem

    def _identifier_for(self, index: int) -> str:
        """标识符/档号：`<前缀>-<三位序号>`（前缀默认 ID；第 3 步可校正）。"""
        base = self._state["id_prefix"].strip() or "ID"
        return f"{base}-{index:03d}"

    def _date_for(self, path: Path) -> str:
        """采集日期：统一值优先；留空 → 按该文件时间戳（DA/T M14 自动提取口径）。"""
        return self._state["date"].strip() or _fmt_file_date(path)

    # ------------------------------------------------------------------
    # ③ 核对与应用
    # ------------------------------------------------------------------

    def _build_review_page(self, parent: QWidget) -> QWidget:
        sp = theme.TOKENS["spacing"]
        page = QWidget(parent)
        page.setObjectName("metaReviewPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sp["sm"])

        lay.addWidget(self._group_label(tr("batch.meta.step3_hint"), page))
        self.review_table = QTableWidget(0, 5, page)
        self.review_table.setObjectName("metaReviewTable")
        self.review_table.setHorizontalHeaderLabels([
            tr("batch.meta.col_file"),
            tr("batch.meta.col_title"),
            tr("batch.meta.col_tech"),
            tr("batch.meta.col_summary"),
            tr("batch.meta.col_warn"),
        ])
        self.review_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.review_table.verticalHeader().setVisible(False)
        self.review_table.itemChanged.connect(self._on_review_item_changed)
        lay.addWidget(self.review_table, 1)

        self.status_label = QLabel("", page)
        self.status_label.setObjectName("metaStatus")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)
        return page

    def _refresh_review(self) -> None:
        """重建核对清单：每文件 = 文件名 | 题名（可微调）| 技术（只读）| 摘要 | 警告。"""
        if self.review_table is None:
            return
        paths = self.current_paths()
        table = self.review_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(paths))
            for row, raw in enumerate(paths):
                path = Path(raw)
                tech = self._read_tech(path)
                index = row + 1
                table.setItem(row, _COL_FILE, _readonly(self._file_item(path, raw)))
                table.setItem(row, _COL_TITLE, QTableWidgetItem(self._title_for(path)))
                table.setItem(
                    row, _COL_TECH, _readonly(QTableWidgetItem(self._tech_text(tech)))
                )
                table.setItem(
                    row, _COL_SUMMARY,
                    _readonly(QTableWidgetItem(self._summary_text(path, index))),
                )
                warn = QTableWidgetItem(self._warn_text())
                if self._missing_required():
                    # 必填缺失高亮：语义色令牌（禁硬编码 hex）
                    warn.setForeground(
                        QBrush(QColor(theme.TOKENS["semantic"]["error"]))
                    )
                table.setItem(row, _COL_WARN, _readonly(warn))
        finally:
            table.blockSignals(False)
        self._refresh_date_range(paths)

    def _file_item(self, path: Path, raw: str) -> QTableWidgetItem:
        """文件名单元格（UserRole 存该行绝对路径，供逐行微调回填定位）。"""
        item = QTableWidgetItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole, raw)
        return item

    def _on_review_item_changed(self, item: QTableWidgetItem) -> None:
        """逐行微调题名（列 2）：记录覆盖值；空文本 → 回退默认题名（兜底）。"""
        if item is None or item.column() != _COL_TITLE:
            return
        path_item = self.review_table.item(item.row(), _COL_FILE)
        if path_item is None:
            return
        raw = path_item.data(Qt.ItemDataRole.UserRole)
        if raw:
            self._title_overrides[str(raw)] = item.text()

    def _refresh_date_range(self, paths: list[str]) -> None:
        """显示检测到的文件时间戳范围（采集日期留空时的逐文件口径）。"""
        if self.date_range_label is None:
            return
        stamps = [s for s in (_fmt_file_mtime(Path(p)) for p in paths) if s]
        if not stamps:
            self.date_range_label.setText("")
            return
        self.date_range_label.setText(
            tr("batch.meta.date_range").format(
                rng=stamps[0] if len(stamps) == 1 else f"{min(stamps)} ~ {max(stamps)}"
            )
        )

    def _tech_text(self, tech: dict) -> str:
        """技术元数据只读文本（逐文件；缺失项以占位符表示）。"""
        if not tech:
            return _PLACEHOLDER
        return " · ".join([
            f"{tr('inspector.meta.sampling_rate')}={tech.get('SamplingRate', _PLACEHOLDER)}",
            f"{tr('inspector.meta.bit_depth')}={tech.get('BitDepth', _PLACEHOLDER)}",
            f"{tr('inspector.meta.format')}={tech.get('Format', _PLACEHOLDER)}",
            f"{tr('inspector.meta.channels')}={tech.get('Channels', _PLACEHOLDER)}",
            f"{tr('inspector.meta.duration')}={tech.get('Duration', _PLACEHOLDER)}",
        ])

    def _summary_text(self, path: Path, index: int) -> str:
        """该行将写入 metadata 的摘要（含 _standard）。"""
        creator = self._state["creator"].strip()
        return "; ".join([
            f"{tr('inspector.meta.title')}={self._title_for(path)}",
            f"{tr('inspector.meta.creator')}={creator or _PLACEHOLDER}",
            f"{tr('inspector.meta.identifier')}={self._identifier_for(index)}",
            f"{tr('inspector.meta.date')}={self._date_for(path) or _PLACEHOLDER}",
            f"{tr('batch.meta.standard_label')}={self._standard_code()}",
        ])

    def _missing_required(self) -> bool:
        """必填缺失（当前仅责任者/传承人）——决定核对清单高亮与执行拦截。"""
        return not self._state["creator"].strip()

    def _warn_text(self) -> str:
        """空字段警告（当前仅必填责任者；缺失将拦截执行）。"""
        if not self._missing_required():
            return _PLACEHOLDER
        return tr("batch.meta.warn_creator")

    def _read_tech(self, path: Path) -> dict:
        """复用 audio/io.py 读取技术参数（禁新写解码器）；失败回空 dict（不抛）。"""
        try:
            info = AudioIO().get_info(path)
        except Exception:
            return {}
        return {
            "SamplingRate": str(info.sample_rate),
            "BitDepth": str(info.bit_depth),
            "Format": str(info.format),
            "Channels": str(info.channels),
            "Duration": _fmt_hms(info.duration),
        }

    # ------------------------------------------------------------------
    # 步骤导航与底部操作
    # ------------------------------------------------------------------

    def _goto(self, index: int) -> None:
        index = max(0, min(_PAGE_COUNT - 1, int(index)))
        self._page = index
        if self.stack is not None:
            self.stack.setCurrentIndex(index)
        for i, chip in enumerate(self.step_chips):
            mark = "▸ " if i == index else ""
            chip.setText(mark + tr(("batch.meta.step1", "batch.meta.step2",
                                    "batch.meta.step3")[i]))
        if index == _PAGE_SCOPE:
            self._refresh_scope()
        elif index == _PAGE_REVIEW:
            self._refresh_review()
        if self.btn_prev is not None:
            self.btn_prev.setEnabled(index > _PAGE_SCOPE)
        if self.btn_next is not None:
            self.btn_next.setEnabled(index < _PAGE_COUNT - 1)

    def _on_prev(self) -> None:
        self._goto(self._page - 1)

    def _on_next(self) -> None:
        self._goto(self._page + 1)

    def _on_cancel(self) -> None:
        """取消并退出：不改动任何文件，框架回常规页。"""
        if self._ws is not None:
            self._ws.exitRequested.emit()

    def _on_apply(self) -> None:
        """应用并完成：必填校验 → 框架执行 apply（结果入框架报告区）→ 回常规页。"""
        if not self._state["creator"].strip():
            if self.warn_label is not None:
                self.warn_label.setText(tr("batch.meta.blocked"))
            self._goto(_PAGE_FIELDS)
            if self.creator_edit is not None:
                self.creator_edit.setFocus()
            return
        if self._ws is None:
            return
        self._goto(_PAGE_REVIEW)  # 执行前刷新核对清单（最终摘要）
        self._ws.run_active()     # 框架调本模块 apply，逐文件结果写入框架报告区
        ok = sum(1 for r in self._last_results if r.get("ok"))
        fail = len(self._last_results) - ok
        summary = tr("batch.meta.applied").format(ok=ok, fail=fail)
        if self.status_label is not None:
            self.status_label.setText(summary)
        if self.warn_label is not None:
            self.warn_label.clear()
        self._toast(summary)
        self._ws.exitRequested.emit()

    def _toast(self, message: str) -> None:
        """结果提示走既有 toast（禁新建 QDialog）；宿主不可见时静默跳过。"""
        if self.ui is None or not self.ui.isVisible():
            return
        from acouscope.ui.widgets.toast import show_toast

        show_toast(self.ui, message, level="info")

    # ------------------------------------------------------------------
    # apply（框架调用：files=勾选行绝对路径；params=本模块 config_ui 本体）
    # ------------------------------------------------------------------

    def apply(self, files, params, progress_cb) -> list:
        """逐文件写 `ProjectFile.metadata`，返回 [{"path","ok","reason"}]。

        登记约束（T-907 约束 1）：无 ProjectFile 条目 → 经**框架注入的
        ProjectManager** `add_file` 登记后再写（禁自建 manager / 禁直连 controller）。
        """
        paths = [str(p) for p in (files or [])]
        creator = self._state["creator"].strip()
        manager = self.manager()

        if not creator:
            results = [
                {"path": p, "ok": False, "reason": tr("batch.meta.err_creator_required")}
                for p in paths
            ]
            self._last_results = results
            return results
        if manager is None:
            results = [
                {"path": p, "ok": False, "reason": tr("batch.meta.err_no_manager")}
                for p in paths
            ]
            self._last_results = results
            return results

        shared = {
            "Creator": creator,
            "Recorder": self._state["recorder"].strip(),
            "Location": self._state["location"].strip(),
            "GenreContext": self._state["genre"].strip(),
            "ActorRole": self._state["actor_role"].strip(),
        }
        standard = self._standard_code()
        total = len(paths)
        results: list[dict] = []
        for index, raw in enumerate(paths, start=1):
            path = Path(raw)
            progress_cb(
                tr("batch.meta.progress").format(i=index, n=total, name=path.name)
            )
            try:
                pf = manager.get_file(raw)
                if pf is None:
                    pf = manager.add_file(raw, label=path.name)
                fields = dict(shared)
                fields.update({
                    "Title": self._title_for(path),
                    "Identifier": self._identifier_for(index),
                    "Date": self._date_for(path),
                })
                fields.update(self._read_tech(path))
                merged = {
                    k: v for k, v in pf.metadata.items()
                    if k not in _FIELD_KEYS and k != "_standard"
                }
                merged.update({k: v for k, v in fields.items() if v})
                merged["_standard"] = standard
                pf.metadata = merged
                results.append({"path": raw, "ok": True, "reason": ""})
            except Exception as exc:  # noqa: BLE001 — 单文件失败不中断整批
                results.append({"path": raw, "ok": False, "reason": str(exc)})
        self._last_results = results
        return results
