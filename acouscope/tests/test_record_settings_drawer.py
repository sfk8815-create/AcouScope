# SPDX-License-Identifier: GPL-3.0-only
"""T-504c 录音设置去模态化（RecordSettingsDialog → 可嵌入抽屉的非模态面板）测试。

模式照抄 tests/test_settings_drawer.py（sys.path.insert 指向 src）。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QWidget, QDialog
from acouscope.ui.widgets.record_settings_dialog import RecordSettingsDialog

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def test_record_settings_is_widget_not_modal(qapp):
    d = RecordSettingsDialog()
    assert isinstance(d, QWidget)
    assert not isinstance(d, QDialog)


def test_accepted_on_valid_accept(qapp, tmp_path):
    d = RecordSettingsDialog()
    d.edit_dir.setText(str(tmp_path))
    d.edit_filename.setText("t")          # 自动补 .wav，路径不存在 → 无覆盖弹窗
    assert d.file_path() == str(tmp_path / "t.wav")
    seen = []
    d.accepted.connect(lambda: seen.append("a"))
    d.btn_start.click()
    assert seen == ["a"]
    assert d.was_accepted() is True


def test_cancelled_on_cancel_and_close(qapp):
    # 实例 1：点取消按钮 → cancelled（面板不自关，由宿主决定）
    d1 = RecordSettingsDialog()
    seen1 = []
    d1.cancelled.connect(lambda: seen1.append("c"))
    d1.btn_cancel.click()
    assert seen1 == ["c"]
    assert not d1.was_accepted()

    # 实例 2：未 accepted 直接 close() → closeEvent 兜底发 cancelled
    d2 = RecordSettingsDialog()
    seen2 = []
    d2.cancelled.connect(lambda: seen2.append("c"))
    d2.close()
    assert seen2 == ["c"]


def test_validation_failure_no_signal(qapp):
    d = RecordSettingsDialog()
    d.edit_filename.setText("")           # 空文件名 → 校验失败，面板保持打开
    acc, canc = [], []
    d.accepted.connect(lambda: acc.append("a"))
    d.cancelled.connect(lambda: canc.append("c"))
    d.btn_start.click()
    assert acc == []
    assert canc == []
    assert not d.was_accepted()
    assert "文件名" in d.lbl_note.text()


def test_was_accepted_flag(qapp, tmp_path):
    d = RecordSettingsDialog()
    assert d.was_accepted() is False
    d.edit_dir.setText(str(tmp_path))
    d.edit_filename.setText("t2")
    d.btn_start.click()
    assert d.was_accepted() is True


def test_main_window_de_modalized():
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    assert "RecordSettingsDialog.DialogCode" not in mw
    assert "open_drawer" in mw
    assert "was_accepted" in mw
    assert "audio_data is None" in mw
    assert mw.count("QMessageBox.question") == 2   # 录音完成白名单 + 模型未安装

    sd = (UI / "widgets" / "record_settings_dialog.py").read_text(encoding="utf-8")
    assert "class RecordSettingsDialog(QWidget)" in sd
    assert "QDialogButtonBox" not in sd
    assert ".exec(" not in sd
