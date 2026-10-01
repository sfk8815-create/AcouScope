# SPDX-License-Identifier: GPL-3.0-only
"""T-1103 报告预览面板测试（M-B′-β2·全离屏·不触真实音频文件·不调 apply_theme）。

覆盖：
① 面板 QWidget 非 QDialog（§三-quarter 三计数守卫）；
② ``render_html_pages`` 产逐页图：A4 纵向高>宽 · 横向宽>高（方向切换生效）·
   白底角像素 · 12 大图 html 切页数 ≥2（★ 禁 ``doc.pageCount`` 口径，页数只认
   返回列表长度——α 探针实证 pageCount print 后不可靠）；
③ ``refresh()`` 建页 QLabel 数 == ``render_html_pages`` 同参数返回数；
④ 预览导出同源：面板参数（横向/边距 20/分辨率 96）经 ``options()`` 透传
   ``render_report_pdf`` spy 逐字段核对；
⑤ main_window 三计数 0/0/8 逐值不破（全文本计数·与冻结口径同源）；
⑥ provider 抛 → 面板不崩、页区空（refresh 不落任何 PDF）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor, QImage, QPageLayout, QPixmap
from PyQt6.QtWidgets import QDialog, QFileDialog, QLabel, QWidget

from acouscope.app.controller import AppController
from acouscope.i18n import set_language
from acouscope.ui import report_export, report_pdf
from acouscope.ui.main_window import MainWindow
from acouscope.ui.report_export import ReportFigure
from acouscope.ui.report_preview import ReportPreviewPanel, render_html_pages

import numpy as np

_SR = 8000
_T = np.arange(_SR * 2) / _SR
_SIGNAL = 0.5 * np.sin(2 * np.pi * 440 * _T)

_SMALL_HTML = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
    "<body style='background:white;color:black'>"
    "<h1>报告题名</h1><p>一行正文。</p></body></html>"
)

_MAIN_WINDOW = Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui" / "main_window.py"


# ---------------------------------------------------------------------------
# 夹具 / 工具
# ---------------------------------------------------------------------------


def _figure(width: int = 700, height: int = 900) -> ReportFigure:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    return ReportFigure(image=image, caption="图 1")


def _twelve_figures_html() -> str:
    """经同源 build_report_html 产 12 张大图的自包含串（触几何切页路径）。"""
    return report_export.build_report_html(
        title="多图",
        metadata={},
        figures=[_figure() for _ in range(12)],
        tech_info={},
        degraded_reason="",
        font_family="",
    )


def _stub_save_dialog(monkeypatch, path) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda parent=None, caption="", initial="", filter="": (str(path), "")),
    )


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带合成音频的 MainWindow（离屏构建·不 show·teardown close）。"""
    set_language("zh_CN")
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    controller.load_from_array(_SIGNAL.copy(), _SR)
    w = MainWindow(controller)
    w.waveform_widget.set_data(_T, _SIGNAL.copy(), sample_rate=_SR)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# ① 面板形态
# ---------------------------------------------------------------------------


def test_panel_is_qwidget_not_qdialog(qapp):
    panel = ReportPreviewPanel()
    assert isinstance(panel, QWidget)
    assert not isinstance(panel, QDialog)


# ---------------------------------------------------------------------------
# ② 逐页渲染：比例 / 方向 / 白底 / 分页
# ---------------------------------------------------------------------------


def test_render_html_pages_returns_pixmaps(qapp):
    pages = render_html_pages(_SMALL_HTML)
    assert pages, "空页列表（疑似未产图）"
    assert all(isinstance(page, QPixmap) for page in pages)
    first = pages[0]
    assert first.height() > first.width(), "A4 纵向应高>宽"


def test_orientation_landscape_swaps_aspect(qapp):
    portrait = render_html_pages(_SMALL_HTML)
    landscape = render_html_pages(
        _SMALL_HTML, orientation=QPageLayout.Orientation.Landscape
    )
    assert landscape[0].width() > landscape[0].height(), "横向应宽>高"
    assert portrait[0].height() > portrait[0].width()
    assert landscape[0].width() > portrait[0].width()


def test_white_background(qapp):
    pages = render_html_pages(_SMALL_HTML)
    image = pages[0].toImage()
    assert image.pixelColor(0, 0).name() == "#ffffff"
    assert image.pixelColor(pages[0].width() - 1, pages[0].height() - 1).name() == "#ffffff"


def test_multi_page_split(qapp):
    # ★ 页数判据 = 返回列表长度；禁 doc.pageCount()（α 探针实证不可靠口径）
    pages = render_html_pages(_twelve_figures_html())
    assert len(pages) >= 2, "12 张大图应至少切两页"


# ---------------------------------------------------------------------------
# ③ 面板刷新建页
# ---------------------------------------------------------------------------


def test_panel_refresh_builds_page_labels(qapp):
    panel = ReportPreviewPanel()
    panel.set_html_provider(lambda: _SMALL_HTML)
    panel.refresh()
    labels = panel.pages_host.findChildren(QLabel)
    assert len(labels) == len(render_html_pages(_SMALL_HTML, **panel.options()))
    assert labels and all(
        not label.pixmap().isNull() for label in labels
    ), "页 QLabel 缺图"


# ---------------------------------------------------------------------------
# ④ 预览导出同源：options() 透传
# ---------------------------------------------------------------------------


def test_export_forwards_panel_options(window, monkeypatch, tmp_path):
    captured: dict = {}

    def spy_render(html, target, **kwargs):
        captured["html"] = html
        captured["target"] = Path(target)
        captured.update(kwargs)
        return Path(target)

    monkeypatch.setattr(report_pdf, "render_report_pdf", spy_render)
    # 取数三件套打桩 canned（不触真实渲染管线/真实音频文件）
    window._collect_report_figures = lambda: [_figure(8, 6)]
    window._report_metadata = lambda: {"Title": "预览同源"}
    window._report_tech_info = lambda: {"Filename": "demo.wav"}

    panel = window.report_preview_panel
    panel.combo_orientation.setCurrentIndex(1)  # 横向
    panel.spin_margin.setValue(20)
    panel.combo_dpi.setCurrentIndex(0)  # 96

    target = tmp_path / "forward.pdf"
    _stub_save_dialog(monkeypatch, target)
    window._on_export_report_pdf()

    opt = panel.options()
    assert captured, "render_report_pdf 未被调用"
    assert opt["orientation"] == QPageLayout.Orientation.Landscape
    assert opt["margin_mm"] == 20.0
    assert opt["dpi"] == 96
    for key, value in opt.items():
        assert captured[key] == value, f"透传字段 {key} 与面板 options() 不一致"
    assert captured["html"].startswith("<!DOCTYPE html>")


# ---------------------------------------------------------------------------
# ⑤ main_window 三计数守卫
# ---------------------------------------------------------------------------


def test_main_window_three_counts_unchanged():
    text = _MAIN_WINDOW.read_text(encoding="utf-8")
    assert text.count("QDialog(") == 0
    assert text.count("QThread(") == 0
    assert text.count("QTimer(") == 8, "β2 挂载不得新增/删除 QTimer 构造字面量"


# ---------------------------------------------------------------------------
# ⑥ provider 异常守卫
# ---------------------------------------------------------------------------


def test_provider_error_guarded(qapp):
    def boom() -> str:
        raise RuntimeError("取数失败")

    panel = ReportPreviewPanel()
    panel.set_html_provider(boom)
    panel.refresh()  # 不得上抛
    assert panel.pages_host.findChildren(QLabel) == [], "异常后页区应空"
