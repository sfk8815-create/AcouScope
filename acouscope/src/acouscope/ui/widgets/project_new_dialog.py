# SPDX-License-Identifier: GPL-3.0-only
"""项目新建弹窗（T-908，模态单页；Beta 前置）。

只采集项目基本信息 + 音频导入：
- 项目名称（必填）
- 项目存储路径（默认 ~/acouscope/YYYYMMDD_HHMMSS，可浏览更改，只读预览）
- 音频导入（可选）：选择一个或多个音频文件 → Project.files

**不含任何元数据填报**（采样率/位深/格式/声道/题名等属 T-912 检查器 /
T-913 批量，防范围蔓延）。

合规豁免：本弹窗为 QDialog 模态，与 GUI 宪法「对话框最小化」冲突，
经最高指挥裁决豁免，已登记 GUI_dialog_inventory.md 模态白名单（DE2）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from acouscope.app.project import ProjectManager
from acouscope.i18n import tr
from acouscope.ui import theme

# 音频导入过滤器（常见无损/有损格式）
AUDIO_FILTER = (
    "Audio files (*.wav *.flac *.mp3 *.ogg *.aiff *.m4a);;All files (*)"
)


def default_storage_dir() -> Path:
    """默认项目存储目录：~/acouscope/YYYYMMDD_HHMMSS（任务书口径）。"""
    return Path.home() / "acouscope" / datetime.now().strftime("%Y%m%d_%H%M%S")


class ProjectNewDialog(QDialog):
    """项目新建弹窗（模态、单页、无步骤）。

    用法：
        dlg = ProjectNewDialog(manager)   # manager 可缺省（内部新建）
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.was_created():
            ...  # manager.current 即新项目（含导入文件）
    """

    def __init__(self, manager: ProjectManager | None = None, parent=None):
        super().__init__(parent)
        self._manager = manager if manager is not None else ProjectManager()
        self._created = False

        self.setWindowTitle(tr("project_new.title"))
        # 宽度由设计令牌推导（禁硬编码 px）：xl(32) * 14 = 448
        self.setMinimumWidth(theme.TOKENS["spacing"]["xl"] * 14)

        t = theme.TOKENS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            t["spacing"]["md"], t["spacing"]["md"],
            t["spacing"]["md"], t["spacing"]["md"],
        )
        layout.setSpacing(t["spacing"]["sm"])

        # ----- 基本信息（名称 + 存储路径）-----
        form = QFormLayout()

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText(tr("project_new.name_ph"))
        form.addRow(QLabel(tr("project_new.name")), self.edit_name)

        # 存储路径：只读预览，仅经「浏览」更改
        self.edit_dir = QLineEdit()
        self.edit_dir.setReadOnly(True)
        self.edit_dir.setText(str(default_storage_dir()))
        row_dir = QHBoxLayout()
        row_dir.addWidget(self.edit_dir, stretch=1)
        self.btn_browse_dir = QPushButton(tr("project_new.browse_dir"))
        self.btn_browse_dir.clicked.connect(self._on_browse_dir)
        row_dir.addWidget(self.btn_browse_dir)
        form.addRow(QLabel(tr("project_new.dir")), row_dir)

        layout.addLayout(form)

        # ----- 音频导入（可选）-----
        layout.addWidget(QLabel(tr("project_new.import")))
        self.list_files = QListWidget()
        self.list_files.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        layout.addWidget(self.list_files, stretch=1)

        row_files = QHBoxLayout()
        row_files.addStretch(1)
        self.btn_browse_files = QPushButton(tr("project_new.browse_files"))
        self.btn_browse_files.clicked.connect(self._on_browse_files)
        row_files.addWidget(self.btn_browse_files)
        layout.addLayout(row_files)

        # ----- 校验错误提示（语义色，默认隐藏）-----
        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("errLabel")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.hide()
        layout.addWidget(self.lbl_error)

        # ----- 按钮行 -----
        row_btns = QHBoxLayout()
        row_btns.addStretch(1)
        self.btn_cancel = QPushButton(tr("project_new.cancel"))
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_create = QPushButton(tr("project_new.create"))
        self.btn_create.setObjectName("primaryBtn")
        self.btn_create.setDefault(True)
        self.btn_create.clicked.connect(self._on_create)
        row_btns.addWidget(self.btn_cancel)
        row_btns.addWidget(self.btn_create)
        layout.addLayout(row_btns)

        # 主题令牌取色（禁硬编码 hex/px）：随主题切换自动重设
        theme.style_when_theme(self, self._build_qss)

    # ------------------------------------------------------------------
    # 主题样式（builder：colors_dict -> QSS，全部引用令牌/角色色）
    # ------------------------------------------------------------------

    @staticmethod
    def _build_qss(c: dict[str, str]) -> str:
        sp = theme.TOKENS["spacing"]
        rd = theme.TOKENS["radius"]
        el = theme.TOKENS["elevation"]
        ty = theme.TOKENS["typography"]
        err = theme.TOKENS["semantic"]["error"]
        return (
            f"QLabel {{ color: {c['text']}; font-size: {ty['body']}px; }}"
            f"QLabel#errLabel {{ color: {err}; font-size: {ty['caption']}px; }}"
            f"QLineEdit, QListWidget {{"
            f" background: {c['input']}; color: {c['text']};"
            f" border: {el['border']}px solid {c['border']};"
            f" border-radius: {rd['sm']}px;"
            f" padding: {sp['xs']}px {sp['sm']}px;"
            f" font-size: {ty['body']}px; }}"
            f"QListWidget::item:selected {{ background: {c['sel_bg']};"
            f" color: {c['text']}; }}"
            f"QPushButton {{"
            f" background: {c['btn']}; color: {c['text']};"
            f" border: {el['border']}px solid {c['border']};"
            f" border-radius: {rd['sm']}px;"
            f" padding: {sp['xs']}px {sp['md']}px;"
            f" font-size: {ty['body']}px; }}"
            f"QPushButton:hover {{ background: {c['btn_hover']}; }}"
            f"QPushButton#primaryBtn {{"
            f" background: {c['accent']}; color: {c['accent_text']};"
            f" border: none; }}"
        )

    # ------------------------------------------------------------------
    # 对外取值
    # ------------------------------------------------------------------

    def project_name(self) -> str:
        """项目名称（已 strip）。"""
        return self.edit_name.text().strip()

    def storage_path(self) -> Path:
        """项目存储路径。"""
        return Path(self.edit_dir.text().strip())

    def import_paths(self) -> list[str]:
        """待导入音频文件路径列表（保持列表顺序）。"""
        return [
            self.list_files.item(i).text() for i in range(self.list_files.count())
        ]

    def was_created(self) -> bool:
        """本次弹窗是否完成了一次成功创建。"""
        return self._created

    # ------------------------------------------------------------------
    # 行为
    # ------------------------------------------------------------------

    def _on_browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, tr("project_new.browse_dir"), self.edit_dir.text()
        )
        if d:
            self.edit_dir.setText(d)

    def _on_browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("project_new.browse_files"), str(Path.home()), AUDIO_FILTER
        )
        existing = set(self.import_paths())
        for f in files:
            if f not in existing:
                self.list_files.addItem(f)

    def _show_error(self, msg: str) -> None:
        self.lbl_error.setText(msg)
        self.lbl_error.show()

    def _clear_error(self) -> None:
        self.lbl_error.setText("")
        self.lbl_error.hide()

    def _on_create(self) -> None:
        if self.create_project():
            self.accept()

    def create_project(self) -> bool:
        """校验并创建项目；返回是否成功。

        校验：名称非空；存储目录可创建（mkdir parents/exist_ok）。
        成功：ProjectManager.new(name) + 追加导入文件 + 持久化
        <存储路径>/<name>.acouproj（保存失败不阻断创建），置位
        was_created。失败：显示错误提示，保持打开，返回 False。
        """
        name = self.project_name()
        if not name:
            self._show_error(tr("project_new.err_name"))
            return False

        dir_path = self.storage_path()
        if not str(dir_path):
            self._show_error(tr("project_new.err_dir").format(err=""))
            return False
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._show_error(tr("project_new.err_dir").format(err=e))
            return False

        self._clear_error()
        self._manager.new(name)
        for p in self.import_paths():
            self._manager.add_file(p)

        # 持久化：项目文件落 <存储路径>/<name>.acouproj；
        # 失败（如权限）不阻断创建，仅提示。
        proj_file = dir_path / (name + ProjectManager.FILE_EXTENSION)
        try:
            self._manager.save(proj_file)
        except OSError as e:
            self._show_error(tr("project_new.err_save").format(err=e))

        self._created = True
        return True
