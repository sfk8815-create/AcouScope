# SPDX-License-Identifier: GPL-3.0-only
"""T-1102 报告 PDF 导出接线测试（M-B′-β1·全离屏·不触真实音频文件·不调 apply_theme）。

覆盖：
① 菜单动作在位：``action_export_report_pdf`` · objectName · 零快捷键 · 初始 disabled ·
   挂入「导出」子菜单 · i18n 新键三语齐备；
② enable 汇聚（``_update_measure_actions``）随 ``has_audio`` 双向刷新；
③ 槽端到端：存盘对话框 → 取数 → ``build_report_html`` → ``render_report_pdf``
   真落 ``.pdf``（%PDF-1.4 头·非空）；
④ 同源接线：spy ``render_report_pdf`` 入参 ⇒ html 即 ``build_report_html`` 产物、
   target 后缀 .pdf（导出侧与预览共用同一 HTML 模型）；
⑤ 防御分支：无音频 → toast info 零落盘；取数抛 → toast error · ``_report_tmp`` 释放；
⑥ 后缀强制：无名/异后缀路径 → 补 .pdf。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor, QImage, QKeySequence
from PyQt6.QtWidgets import QFileDialog, QMenu

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui import report_export, report_pdf
from acouscope.ui.main_window import MainWindow
from acouscope.ui.report_export import ReportFigure

_SR = 8000
_T = np.arange(_SR * 2) / _SR
_SIGNAL = 0.5 * np.sin(2 * np.pi * 440 * _T)


# ---------------------------------------------------------------------------
# 夹具 / 工具
# ---------------------------------------------------------------------------


def _build_window(with_audio: bool) -> MainWindow:
    set_language("zh_CN")
    controller = AppController()
    if with_audio:
        controller.load_from_array(_SIGNAL.copy(), _SR)
        window = MainWindow(controller)
        window.waveform_widget.set_data(_T, _SIGNAL.copy(), sample_rate=_SR)
        return window
    return MainWindow(controller)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的 MainWindow（合成信号·离屏构建·不 show·teardown close）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    w = _build_window(with_audio=True)
    yield w
    w.close()


@pytest.fixture
def window_noaudio(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（初始 disabled / toast 防御分支用）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    w = _build_window(with_audio=False)
    yield w
    w.close()


@pytest.fixture(autouse=True)
def toasts(monkeypatch):
    """捕获主窗 toast（不弹真实组件）。"""
    import acouscope.ui.main_window as mw_mod

    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mw_mod,
        "show_toast",
        lambda parent, msg, level="info": captured.append((msg, level)),
    )
    return captured


def _stub_save_dialog(monkeypatch, path) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda parent=None, caption="", initial="", filter="": (str(path), "")),
    )


def _tiny_figure() -> ReportFigure:
    image = QImage(1, 1, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    return ReportFigure(image=image, caption="waveform")


def _wire_canned(window) -> None:
    """取数三件套打桩为 canned（不触真实渲染管线/真实音频文件）。"""
    window._collect_report_figures = lambda: [_tiny_figure()]
    window._report_metadata = lambda: {"Title": "阿诗玛", "Creator": "佚名"}
    window._report_tech_info = lambda: {"Filename": "demo.wav"}


def _menus(window) -> list:
    return window.findChildren(QMenu)


# ---------------------------------------------------------------------------
# ① 动作在位 · 初始 disabled（无音频）
# ---------------------------------------------------------------------------


def test_pdf_action_exists_and_initially_disabled(window_noaudio):
    from acouscope.i18n import _STRINGS

    act = window_noaudio.action_export_report_pdf
    assert act.objectName() == "export_report_pdf"
    assert act.shortcut() == QKeySequence()  # 不设快捷键（避撞 Ctrl+Shift+P HTML 快导）
    assert act.isEnabled() is False
    assert act.text() == tr("action.export_report_pdf")
    # T-1109 IM-32：action 不再挂入导出子菜单（收敛至预览页按钮），但 action 保留
    # i18n 新键三语齐备
    for key in ("action.export_report_pdf", "report.filter_pdf", "report.pdf_dialog_title"):
        entry = _STRINGS[key]
        assert set(entry) == {"en_US", "zh_CN", "zh_TW"}, f"{key} 语言不全"
        assert all(entry.values()), f"{key} 存在空文案"


# ---------------------------------------------------------------------------
# ② enable 汇聚随 has_audio
# ---------------------------------------------------------------------------


def test_pdf_action_enabled_with_audio(window, monkeypatch):
    act = window.action_export_report_pdf
    monkeypatch.setattr(window.controller, "has_audio", lambda: True)
    window._update_measure_actions()
    assert act.isEnabled() is True
    monkeypatch.setattr(window.controller, "has_audio", lambda: False)
    window._update_measure_actions()
    assert act.isEnabled() is False


# ---------------------------------------------------------------------------
# ③ 槽端到端：真落合法 PDF
# ---------------------------------------------------------------------------


def test_slot_writes_valid_pdf(window, monkeypatch, tmp_path, toasts):
    _wire_canned(window)
    target = tmp_path / "x.pdf"
    _stub_save_dialog(monkeypatch, target)
    window._on_export_report_pdf()
    assert target.exists(), ".pdf 未落盘"
    raw = target.read_bytes()
    assert raw.startswith(b"%PDF-1.4"), "缺 %PDF-1.4 头"
    assert len(raw) > 1024, "PDF 内容过小（疑似空渲）"
    assert toasts and toasts[-1][1] == "success"
    assert getattr(window, "_report_tmp", None) is None  # 临时目录已释放（幂等 getattr）


# ---------------------------------------------------------------------------
# ④ 同源接线：render 收到 build_report_html 产物
# ---------------------------------------------------------------------------


def test_slot_calls_render_with_same_source_html(window, monkeypatch, tmp_path):
    captured: dict = {}
    real_build = report_export.build_report_html

    def spy_build(**kwargs):
        html = real_build(**kwargs)
        captured["built"] = html
        return html

    def spy_render(html, target, **kwargs):
        captured["html"] = html
        captured["target"] = Path(target)
        return Path(target)

    monkeypatch.setattr(report_export, "build_report_html", spy_build)
    monkeypatch.setattr(report_pdf, "render_report_pdf", spy_render)
    _wire_canned(window)
    _stub_save_dialog(monkeypatch, tmp_path / "s.pdf")
    window._on_export_report_pdf()

    assert captured["html"].startswith("<!DOCTYPE html>")
    assert captured["html"] == captured["built"], "render 入参非 build_report_html 产物"
    assert captured["target"].suffix == ".pdf"
    assert not (tmp_path / "s.pdf").exists()  # spy 不落盘


# ---------------------------------------------------------------------------
# ⑤ 无音频：toast info · 零落盘
# ---------------------------------------------------------------------------


def test_no_audio_toast_no_file(window_noaudio, monkeypatch, tmp_path, toasts):
    _stub_save_dialog(monkeypatch, tmp_path / "never.pdf")
    window_noaudio._on_export_report_pdf()
    assert toasts == [(tr("msg.no_audio"), "info")]
    assert not list(tmp_path.rglob("*.pdf")), "无音频不得落盘"


# ---------------------------------------------------------------------------
# ⑥ 后缀强制 .pdf
# ---------------------------------------------------------------------------


def test_suffix_forced(window, monkeypatch, tmp_path):
    _wire_canned(window)
    _stub_save_dialog(monkeypatch, tmp_path / "nameless")
    window._on_export_report_pdf()
    assert (tmp_path / "nameless.pdf").exists()

    _stub_save_dialog(monkeypatch, tmp_path / "wrong.txt")
    window._on_export_report_pdf()
    assert (tmp_path / "wrong.pdf").exists()
    assert not (tmp_path / "wrong.txt").exists()


# ---------------------------------------------------------------------------
# ⑦ 取数抛 → 不崩 · _report_tmp 释放 · toast error
# ---------------------------------------------------------------------------


def test_cleanup_called_on_error(window, monkeypatch, tmp_path, toasts):
    class _TmpSentinel:
        def __init__(self):
            self.released = False

        def cleanup(self):
            self.released = True

    sentinel = _TmpSentinel()

    def _boom():
        window._report_tmp = sentinel
        raise RuntimeError("view unavailable")

    window._collect_report_figures = _boom
    _stub_save_dialog(monkeypatch, tmp_path / "e.pdf")
    window._on_export_report_pdf()  # 不抛
    assert sentinel.released is True
    assert window._report_tmp is None
    assert toasts and toasts[-1][1] == "error"
    assert "view unavailable" in toasts[-1][0]
    assert not (tmp_path / "e.pdf").exists()
