# SPDX-License-Identifier: GPL-3.0-only
"""T-504f-b widgets QMessageBox→toast 迁移守卫。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

W = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "widgets"
MIGRATED = ["ai_interpret", "room_acoustics_dialog", "settings_dialog",
            "spectrogram3d", "timbre"]


def test_modal_notifications_removed():
    for name in MIGRATED:
        text = (W / f"{name}.py").read_text(encoding="utf-8")
        for kind in ("information", "warning", "critical"):
            assert f"QMessageBox.{kind}(" not in text, f"{name} 仍有 QMessageBox.{kind}"


def test_overwrite_question_permanently_modal():
    text = (W / "record_settings_dialog.py").read_text(encoding="utf-8")
    assert text.count("QMessageBox.question(") == 1  # 文件已存在：破坏性确认白名单
    for kind in ("information", "warning", "critical"):
        assert f"QMessageBox.{kind}(" not in text


def test_show_toast_used():
    for name in MIGRATED:
        text = (W / f"{name}.py").read_text(encoding="utf-8")
        assert "show_toast(" in text, f"{name} 未引入 show_toast"
