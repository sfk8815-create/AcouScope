# SPDX-License-Identifier: GPL-3.0-only
"""T-908 项目新建弹窗（ProjectNewDialog）测试。

覆盖需求说明 Step 4 全部要求：
① 项目名称为空 → 校验拦截（不创建、保持打开）；非空 → 通过；
② 默认存储目录形如 ~/acouscope/YYYYMMDD_HHMMSS；
③ 导入文件（tmp_path 造伪路径/空文件）→ 进入 Project.files；
④ 取消 → 不创建；
⑤ 弹窗内不存在任何元数据填报控件（防范围蔓延回归）；
⑥ 禁词（02_References 下 "The Pitch Grid" 文档文件名首段品牌词）0 命中。

口径：离屏独立构造（qapp fixture），禁 MainWindow.show()；
QFileDialog 静态方法 monkeypatch，不触碰真实文件选择器。
"""

import re
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QDialog, QFileDialog

from acouscope.app.project import ProjectManager
from acouscope.ui.widgets.project_new_dialog import (
    ProjectNewDialog,
    default_storage_dir,
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_project_metadata.py 口径）。
_BANNED = "Mel" + "odyne"

_DIALOG_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "widgets" / "project_new_dialog.py"
)

# 元数据字段名（中英）：弹窗内任何控件文本/占位符命中即视为范围蔓延。
_METADATA_TERMS = [
    "采样率", "位深", "声道", "时长", "题名", "责任者", "格式",
    "标准", "说明", "著录",
    "SamplingRate", "BitDepth", "Channels", "Duration",
    "Title", "Creator", "Format", "Standard", "Note",
]


@pytest.fixture()
def dialog(qapp):
    """离屏独立构造弹窗（不 exec、不 show 主窗）。"""
    dlg = ProjectNewDialog(ProjectManager())
    yield dlg
    dlg.close()


class TestNameValidation:
    def test_empty_name_blocked(self, dialog):
        """① 名称为空 → create_project 返回 False，不创建、弹窗保持打开。"""
        dialog.edit_name.setText("")
        assert dialog.create_project() is False
        assert dialog.was_created() is False
        assert dialog._manager.current.name == "未命名项目"  # new() 未被调用
        assert dialog.result() == QDialog.DialogCode.Rejected  # 未 accept

    def test_whitespace_only_name_blocked(self, dialog):
        """① 纯空白名称视同空 → 拦截。"""
        dialog.edit_name.setText("   ")
        assert dialog.create_project() is False
        assert dialog.was_created() is False

    def test_nonempty_name_passes(self, dialog, tmp_path):
        """① 名称非空 → 创建成功，manager.current 为新项目。"""
        dialog.edit_name.setText("测试项目")
        dialog.edit_dir.setText(str(tmp_path / "proj"))
        assert dialog.create_project() is True
        assert dialog.was_created() is True
        assert dialog._manager.current.name == "测试项目"


class TestDefaultDir:
    def test_default_dir_shape(self, dialog):
        """② 默认目录形如 ~/acouscope/YYYYMMDD_HHMMSS。"""
        p = dialog.storage_path()
        assert p.parent.name == "acouscope"
        assert re.fullmatch(r"\d{8}_\d{6}", p.name)

    def test_default_storage_dir_helper(self):
        """② 模块级默认目录助手同形（home 下 acouscope/时间戳）。"""
        p = default_storage_dir()
        assert p.parts[-2] == "acouscope"
        assert re.fullmatch(r"\d{8}_\d{6}", p.name)

    def test_dir_edit_is_readonly(self, dialog):
        """② 路径为只读预览（仅经浏览按钮更改）。"""
        assert dialog.edit_dir.isReadOnly()


class TestImportFiles:
    def test_import_files_enter_project(self, dialog, tmp_path):
        """③ 导入文件（tmp_path 空文件）→ 进入 Project.files。"""
        f1 = tmp_path / "a.wav"
        f2 = tmp_path / "b.flac"
        f1.write_bytes(b"")
        f2.write_bytes(b"")
        dialog.edit_name.setText("导入测试")
        dialog.edit_dir.setText(str(tmp_path / "store"))
        for f in (f1, f2):
            dialog.list_files.addItem(str(f))
        assert dialog.create_project() is True
        files = dialog._manager.current.files
        assert [pf.path for pf in files] == [str(f1), str(f2)]

    def test_import_paths_order(self, dialog):
        """③ import_paths 保持列表顺序。"""
        dialog.list_files.addItem("/x/1.wav")
        dialog.list_files.addItem("/x/2.wav")
        assert dialog.import_paths() == ["/x/1.wav", "/x/2.wav"]

    def test_browse_files_appends_unique(self, dialog, monkeypatch):
        """③ 浏览选择追加到列表（去重）；QFileDialog 打桩不触真实选择器。"""
        def fake_open(parent, caption, directory, filter_=""):
            return ["/sel/one.wav", "/sel/two.ogg"], ""
        monkeypatch.setattr(QFileDialog, "getOpenFileNames", fake_open)
        dialog._on_browse_files()
        dialog._on_browse_files()  # 重复选择不重复追加
        assert dialog.import_paths() == ["/sel/one.wav", "/sel/two.ogg"]


class TestCancel:
    def test_cancel_no_create(self, dialog):
        """④ 取消（reject）→ 不创建。"""
        dialog.edit_name.setText("将被取消")
        dialog.reject()
        assert dialog.was_created() is False
        assert dialog._manager.current.name == "未命名项目"  # new() 未被调用


class TestNoMetadataControls:
    def test_no_metadata_controls(self, dialog):
        """⑤ 弹窗内不存在任何元数据填报控件（防范围蔓延回归）。"""
        from PyQt6.QtWidgets import (
            QComboBox, QLabel, QLineEdit, QListWidget, QPushButton, QWidget,
        )
        # 控件类型白名单：弹窗只允许基础输入/展示控件，
        # 不得出现下拉（标准/格式选择）等元数据填报形态。
        assert dialog.findChildren(QComboBox) == []
        texts = []
        for w in dialog.findChildren(QWidget):
            if isinstance(w, QLabel):
                texts.append(w.text())
            elif isinstance(w, (QLineEdit,)):
                texts.extend([w.text(), w.placeholderText()])
            elif isinstance(w, QPushButton):
                texts.append(w.text())
            elif isinstance(w, QListWidget):
                for i in range(w.count()):
                    texts.append(w.item(i).text())
        joined = "\n".join(texts)
        for term in _METADATA_TERMS:
            assert term not in joined, f"弹窗文本出现元数据字段词 {term!r}"

    def test_control_inventory(self, dialog):
        """⑤ 控件清单核对：2 行编辑（名称+路径）/1 列表/4 按钮。"""
        from PyQt6.QtWidgets import QLineEdit, QListWidget, QPushButton
        edits = dialog.findChildren(QLineEdit)
        lists = dialog.findChildren(QListWidget)
        buttons = dialog.findChildren(QPushButton)
        assert len(edits) == 2
        assert len(lists) == 1
        assert len(buttons) == 4


class TestBannedWord:
    def test_banned_word_zero_hits(self):
        """⑥ 禁词（品牌词）在弹窗源文件与本测试文件中 0 命中。"""
        for f in (_DIALOG_PY, Path(__file__).resolve()):
            src = f.read_text(encoding="utf-8")
            assert _BANNED not in src, f"{f.name} 出现禁词 {_BANNED!r}"
