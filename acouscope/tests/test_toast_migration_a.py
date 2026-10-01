# SPDX-License-Identifier: GPL-3.0-only
"""T-504f-a main_window QMessageBox→toast 迁移守卫。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "main_window.py"
from tests._pin_baselines import MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT


def test_modal_notifications_removed():
    text = SRC.read_text(encoding="utf-8")
    for kind in ("information", "warning", "critical"):
        assert f"QMessageBox.{kind}(" not in text, f"仍有 QMessageBox.{kind} 未迁移"


def test_questions_preserved():
    text = SRC.read_text(encoding="utf-8")
    # 常量 MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT 集中把守·迁移每减一处改该常量一处
    assert text.count("QMessageBox.question(") == MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT  # 录音完成 / 模型未安装


def test_show_toast_imported_and_used():
    text = SRC.read_text(encoding="utf-8")
    assert "from acouscope.ui.widgets.toast import" in text
    assert "show_toast(" in text
