# SPDX-License-Identifier: GPL-3.0-only
"""自定义律制模板编辑器（P2）。

提供 ``parse_degrees_text`` 纯函数与 ``TuningTemplateEditorDialog`` QDialog；
对话框仅依赖 PyQt6 + P1 数据层 ``acouscope.analysis.tunings.user_templates``
+ ``scl`` / ``tuning_system`` / ``templates`` + ``i18n.tr``。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from acouscope.analysis.tunings.scl import parse_scl
from acouscope.analysis.tunings.tuning_system import TuningSystem
from acouscope.analysis.tunings.user_templates import (
    add_user_template,
    delete_user_template,
    export_user_scl,
    get_user_tuning,
    import_user_scl,
    list_user_templates,
    update_user_template,
    validate_cents,
)
from acouscope.i18n import tr


def parse_degrees_text(text: str) -> list[float]:
    """解析音级文本（每行一个值：音分值或 n/d 比值），返回 [float(cents), ...]。

    按行取非空、非 ``!`` 注释行；拼成合法 .scl 文本（描述行 ``"editor"`` +
    音数 N + 逐行值）交既有 ``parse_scl`` 解析，返回 ``list(scale.cents())``。
    空文本 / 非法 token / 负比值一律 ``ValueError``（原文上抛，禁回退 12TET）。
    """
    if not isinstance(text, str):
        raise ValueError(f"parse_degrees_text 需要 str，实际为 {type(text).__name__}")
    lines = text.splitlines()
    values: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        values.append(stripped)
    if not values:
        raise ValueError("音级文本为空（无有效值行）")
    scl_text = 'editor\n' + str(len(values)) + "\n" + "\n".join(values)
    scale = parse_scl(scl_text)
    return list(scale.cents())


def build_tuning(name: str, source: str, cents) -> TuningSystem:
    """先 validate_cents，再由音分序列构造 TuningSystem。"""
    validate_cents(cents)
    return TuningSystem.from_cents(name=name, source=source, cents=cents)


class TuningTemplateEditorDialog(QDialog):
    """自定义律制模板编辑器对话框（CRUD + .scl 导入导出）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tuningTemplateEditorDialog")
        self.setWindowTitle(tr("tuning.user.title"))
        self._delete_armed = False

        # 左侧：模板列表
        self.tuningTemplateList = QListWidget()
        self.tuningTemplateList.setObjectName("tuningTemplateList")

        # 右侧表单
        name_label = QLabel(tr("tuning.user.name"))
        self.tuningTemplateNameEdit = QLineEdit()
        self.tuningTemplateNameEdit.setObjectName("tuningTemplateNameEdit")

        source_label = QLabel(tr("tuning.user.source"))
        self.tuningTemplateSourceEdit = QLineEdit()
        self.tuningTemplateSourceEdit.setObjectName("tuningTemplateSourceEdit")

        degrees_label = QLabel(tr("tuning.user.degrees"))
        self.tuningTemplateDegreesEdit = QPlainTextEdit()
        self.tuningTemplateDegreesEdit.setObjectName("tuningTemplateDegreesEdit")

        # 按钮行
        self.tuningTemplateNewBtn = QPushButton(tr("tuning.user.new"))
        self.tuningTemplateNewBtn.setObjectName("tuningTemplateNewBtn")
        self.tuningTemplateSaveBtn = QPushButton(tr("tuning.user.save"))
        self.tuningTemplateSaveBtn.setObjectName("tuningTemplateSaveBtn")
        self.tuningTemplateDeleteBtn = QPushButton(tr("tuning.user.delete"))
        self.tuningTemplateDeleteBtn.setObjectName("tuningTemplateDeleteBtn")
        self.tuningTemplateImportBtn = QPushButton(tr("tuning.user.import"))
        self.tuningTemplateImportBtn.setObjectName("tuningTemplateImportBtn")
        self.tuningTemplateExportBtn = QPushButton(tr("tuning.user.export"))
        self.tuningTemplateExportBtn.setObjectName("tuningTemplateExportBtn")
        self.tuningTemplateCloseBtn = QPushButton(tr("tuning.user.close"))
        self.tuningTemplateCloseBtn.setObjectName("tuningTemplateCloseBtn")

        # 状态栏
        self.tuningTemplateStatus = QLabel()
        self.tuningTemplateStatus.setObjectName("tuningTemplateStatus")

        # 连接信号
        self.tuningTemplateList.itemSelectionChanged.connect(self._on_selection_changed)
        self.tuningTemplateNewBtn.clicked.connect(self._on_new)
        self.tuningTemplateSaveBtn.clicked.connect(self._on_save)
        self.tuningTemplateDeleteBtn.clicked.connect(self._on_delete)
        self.tuningTemplateImportBtn.clicked.connect(self._on_import)
        self.tuningTemplateExportBtn.clicked.connect(self._on_export)
        self.tuningTemplateCloseBtn.clicked.connect(self.accept)

        # 布局：左列表 + 右表单
        form_layout = QVBoxLayout()
        form_layout.addWidget(name_label)
        form_layout.addWidget(self.tuningTemplateNameEdit)
        form_layout.addWidget(source_label)
        form_layout.addWidget(self.tuningTemplateSourceEdit)
        form_layout.addWidget(degrees_label)
        form_layout.addWidget(self.tuningTemplateDegreesEdit, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.tuningTemplateNewBtn)
        btn_layout.addWidget(self.tuningTemplateSaveBtn)
        btn_layout.addWidget(self.tuningTemplateDeleteBtn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.tuningTemplateImportBtn)
        btn_layout.addWidget(self.tuningTemplateExportBtn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.tuningTemplateCloseBtn)

        form_layout.addLayout(btn_layout)
        form_layout.addWidget(self.tuningTemplateStatus)

        main_layout = QHBoxLayout(self)
        main_layout.addWidget(self.tuningTemplateList, 1)
        main_layout.addLayout(form_layout, 2)

        self.refresh_list()

    def refresh_list(self) -> None:
        """以 list_user_templates() 为唯一数据源重建列表。"""
        self._delete_armed = False
        self.tuningTemplateDeleteBtn.setText(tr("tuning.user.delete"))
        self.tuningTemplateList.clear()
        templates = list_user_templates()
        if not templates:
            item = QListWidgetItem(tr("tuning.user.empty_hint"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tuningTemplateList.addItem(item)
        else:
            for entry in templates:
                self.tuningTemplateList.addItem(entry["name"])

    def current_name(self) -> str:
        """当前选中模板名；无选中则空串。"""
        items = self.tuningTemplateList.selectedItems()
        if not items:
            return ""
        text = items[0].text()
        if text == tr("tuning.user.empty_hint"):
            return ""
        return text

    def load_form(self, name: str) -> None:
        """按模板名填充表单（编辑态 name 只读）。"""
        self._delete_armed = False
        self.tuningTemplateDeleteBtn.setText(tr("tuning.user.delete"))
        tuning = get_user_tuning(name)
        self.tuningTemplateNameEdit.setText(tuning.name)
        self.tuningTemplateNameEdit.setReadOnly(True)
        self.tuningTemplateSourceEdit.setText(tuning.source)
        degrees = tuning.degrees[1:]
        self.tuningTemplateDegreesEdit.setPlainText(
            "\n".join(f"{v:.6f}" for v in degrees)
        )

    def save_current(self) -> dict:
        """保存当前表单（新建或更新）。"""
        name = self.tuningTemplateNameEdit.text().strip()
        source = self.tuningTemplateSourceEdit.text().strip()
        degrees_text = self.tuningTemplateDegreesEdit.toPlainText()
        if not name or not source or not degrees_text.strip():
            msg = tr("tuning.user.err_empty")
            self.tuningTemplateStatus.setText(msg)
            raise ValueError(msg)
        try:
            cents = parse_degrees_text(degrees_text)
        except ValueError as exc:
            msg = tr("tuning.user.err_bad").format(error=str(exc))
            self.tuningTemplateStatus.setText(msg)
            raise
        is_new = not self._is_in_list(name)
        if is_new:
            entry = add_user_template(name, source, cents)
        else:
            entry = update_user_template(name, source=source, cents=cents)
        self.refresh_list()
        self.tuningTemplateStatus.setText(tr("tuning.user.saved").format(name=name))
        return entry

    def delete_current(self) -> bool:
        """两击确认删除。"""
        name = self.current_name()
        if not name:
            return False
        if not self._delete_armed:
            self._delete_armed = True
            self.tuningTemplateDeleteBtn.setText(tr("tuning.user.delete_arm"))
            return False
        user_templates_entry = self._find_entry(name)
        if user_templates_entry is None:
            return False
        self._delete_armed = False
        delete_user_template(name)
        self.tuningTemplateDeleteBtn.setText(tr("tuning.user.delete"))
        self.refresh_list()
        self.tuningTemplateStatus.setText(tr("tuning.user.deleted").format(name=name))
        return True

    def import_scl(self) -> dict | None:
        """导入 .scl 文件为用户模板。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("tuning.user.import"),
            "",
            tr("w14.template.custom_filter"),
        )
        if not path:
            return None
        try:
            entry = import_user_scl(path)
            self.refresh_list()
            self.tuningTemplateStatus.setText(tr("tuning.user.saved").format(name=entry["name"]))
            return entry
        except (ValueError, OSError, KeyError) as exc:
            self.tuningTemplateStatus.setText(
                tr("w14.template.custom_failed").format(error=str(exc))
            )
            raise

    def export_scl(self) -> Path | None:
        """导出当前模板为 .scl 文件。"""
        name = self.current_name()
        if not name:
            return None
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("tuning.user.export"),
            name + ".scl",
            tr("w14.template.custom_filter"),
        )
        if not path:
            return None
        return export_user_scl(name, path)

    def _on_selection_changed(self) -> None:
        name = self.current_name()
        if not name:
            return
        try:
            self.load_form(name)
        except Exception as exc:
            self.tuningTemplateStatus.setText(str(exc))

    def _on_new(self) -> None:
        self._delete_armed = False
        self.tuningTemplateDeleteBtn.setText(tr("tuning.user.delete"))
        self.tuningTemplateNameEdit.clear()
        self.tuningTemplateNameEdit.setReadOnly(False)
        self.tuningTemplateSourceEdit.clear()
        self.tuningTemplateDegreesEdit.clear()
        self.tuningTemplateStatus.setText("")

    def _on_save(self) -> None:
        try:
            self.save_current()
        except ValueError:
            pass

    def _on_delete(self) -> None:
        try:
            self.delete_current()
        except ValueError:
            pass

    def _on_import(self) -> None:
        self.import_scl()

    def _on_export(self) -> None:
        self.export_scl()

    def _is_in_list(self, name: str) -> bool:
        for i in range(self.tuningTemplateList.count()):
            item = self.tuningTemplateList.item(i)
            if item and item.text() == name:
                return True
        return False

    def _find_entry(self, name: str) -> dict | None:
        for entry in list_user_templates():
            if entry["name"] == name:
                return entry
        return None
