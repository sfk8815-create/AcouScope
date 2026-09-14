# SPDX-License-Identifier: GPL-3.0-only
"""CB-003 G-2：SOTA 模型下载进度非模态化（库存 D10 收口）测试。

QProgressDialog 模态进度 → show_toast 开始提示 + 状态栏内联进度面板
（_DownloadProgressPanel：QWidget 容器，非模态不阻塞，QProgressBar +
取消按钮语义保留）。下载完成/失败仍走 _on_download_done toast。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QDialog, QProgressBar, QPushButton, QWidget

from acouscope.ui.main_window import MainWindow, _DownloadProgressPanel

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def test_download_panel_is_non_modal_widget(qapp):
    """进度面板：QWidget 且非 QDialog（非模态容器铁律）。"""
    panel = _DownloadProgressPanel()
    assert isinstance(panel, QWidget)
    assert not isinstance(panel, QDialog)


def test_download_panel_cancel_semantics(qapp):
    """进度区可取消：QProgressBar + “取消”按钮，点击发 canceled 信号。"""
    panel = _DownloadProgressPanel()
    assert isinstance(panel.progress, QProgressBar)
    assert isinstance(panel.btn_cancel, QPushButton)
    assert panel.btn_cancel.text() == "取消"
    seen = []
    panel.canceled.connect(lambda: seen.append("cancel"))
    panel.btn_cancel.click()
    assert seen == ["cancel"]


def test_download_sota_source_de_modalized():
    """_download_sota_model 函数体：无模态进度对话框、非阻塞 + 取消 + toast。"""
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    chunks = [c for c in mw.split("\n    def ") if c.startswith("_download_sota_model")]
    assert len(chunks) == 1
    body = chunks[0].split("\n    def ")[0]
    assert "QProgressDialog" not in body
    assert ".exec(" not in body
    assert "show_toast" in body
    # 取消语义保留（进度区可取消 → 宿主终止下载线程）
    assert "canceled.connect" in body
    assert "btn_cancel" in body or "_DownloadProgressPanel" in body
    # 完成/失败走 toast（_on_download_done 仍被调用）
    assert "_on_download_done" in body


def test_main_window_no_progress_dialog_leftover():
    """全文件锚点：main_window.py 已无 QProgressDialog 遗留。"""
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    assert "QProgressDialog" not in mw


def test_cancel_helper_present(qapp):
    """取消与面板清理辅助方法就位（供 _on_backend_changed 下载流调用）。"""
    assert hasattr(MainWindow, "_ensure_download_panel")
    assert hasattr(MainWindow, "_hide_download_progress")
    assert hasattr(MainWindow, "_cancel_sota_download")
