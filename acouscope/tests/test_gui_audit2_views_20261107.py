# SPDX-License-Identifier: GPL-3.0-only
"""GUI 审计批2（2026-11-07）视图缺陷守卫：H1 / M2 / L1 / L5 / L6。

离屏、不建主窗、不触网。每条守卫在未修复代码上红（B）、修复后绿（A），
并附变异自检（临时回退修复→红→恢复）。
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QToolBar,
    QWidget,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _squeeze(page, width=900, height=700):
    host = QWidget()
    page.setParent(host)
    page.setGeometry(0, 0, width, height)
    host.resize(width + 10, height + 20)
    host.show()
    page.show()
    QApplication.processEvents()
    return host


def _sr_sig():
    sr = 8000
    t = np.arange(int(sr * 8.0)) / sr
    return sr, 0.5 * np.sin(2 * np.pi * 440 * t)


def _make_fft():
    from acouscope.ui.widgets.spectrum import SpectrumWidget
    sr, sig = _sr_sig()
    freqs = np.linspace(0.0, sr / 2, 2048)
    mag = np.exp(-((freqs - 440.0) ** 2) / (2 * 40.0 ** 2)) + 0.02
    w = SpectrumWidget()
    w.set_data(freqs, mag, "FFT", sample_rate=sr, signal_data=sig)
    return w


def _make_spec():
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget
    ft = np.linspace(0.0, 4000.0, 256)
    tt = np.linspace(0.0, 8.0, 400)
    db = -60.0 + 55.0 * np.exp(-((ft[:, None] - 440.0) ** 2) / 2e4)
    w = SpectrogramWidget()
    w.set_data(ft, tt, np.broadcast_to(db, (256, 400)), 8000)
    return w


def _expanding_spacers(row: QToolBar):
    """工具行内纯弹性占位件（add_tool_stretch 产物，H1 根因）。"""
    out = []
    for w in row.findChildren(
        QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
    ):
        if w.layout() is None and not w.findChildren(QWidget) and \
                w.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding:
            out.append(w)
    return out


def test_h1_no_expanding_spacer_and_overflow_reachable(qapp):
    """H1：工具行不得塞 Expanding 占位件；被藏控件须经扩展菜单可达。"""
    from acouscope.ui.widgets.formants import FormantWidget
    from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget
    views = {"FFT": _make_fft(), "语谱图": _make_spec()}
    sr, sig = _sr_sig()
    views["3D"] = Spectrogram3DWidget()
    views["3D"].set_audio(sig, sr)
    times = np.linspace(0.0, 8.0, 200)
    fr = np.tile(np.array([[700.0, 1200.0, 2600.0]]), (200, 1))
    bw = np.tile(np.array([[80.0, 90.0, 120.0]]), (200, 1))
    views["共振峰"] = FormantWidget()
    views["共振峰"].set_data(times, fr, bw)

    for name, page in views.items():
        row = page.tool_row
        host = _squeeze(page, 900)
        try:
            assert _expanding_spacers(row) == [], (
                f"{name} 工具行含 Expanding 占位件（与 Qt 溢出机制冲突）")
            ext = row.findChild(QWidget, "qt_toolbar_ext_button")
            hidden = [a for a in row.actions() if not a.isVisible()]
            if ext is not None and ext.isVisible() and hidden:
                assert ext.isEnabled(), f"{name} 扩展钮可见但 disabled，被藏项不可达"
        finally:
            page.setParent(None)
            host.deleteLater()


def _colorbar_gradient_width(w, bar_attr):
    """渐变区净宽 = 色标总宽 - 左轴宽（ViewBox 有最小宽钳制，不能直接读 vb）。"""
    bar = getattr(w, bar_attr)
    host = _squeeze(w, 900)
    try:
        return float(bar.width() - bar.getAxis("left").width())
    finally:
        w.setParent(None)
        host.deleteLater()


def test_m2_spectrogram_colorbar_gradient_visible(qapp):
    w = _make_spec()
    assert _colorbar_gradient_width(w, "colorbar_widget") >= 8, "语谱图色标渐变区被轴压没"


def test_m2_timbre_colorbar_gradient_visible(qapp):
    from acouscope.ui.widgets.timbre import TimbreWidget
    w = TimbreWidget()
    for i in range(w.tabs.count()):
        if "MFCC" in w.tabs.tabText(i):
            w.tabs.setCurrentIndex(i)
    assert _colorbar_gradient_width(w, "mfcc_colorbar") >= 8, "MFCC 色标渐变区被轴压没"


def test_l1_peak_annotation_single_and_clear_of_marker(qapp):
    import pyqtgraph as pg
    w = _make_fft()
    host = _squeeze(w, 900)
    try:
        w._manual_peaks = [{"freq": 440.0, "magnitude": 0.5,
                            "note": "A4", "cents": -8.0, "midi": 69}]
        w._refresh_marks()
        texts = [i for i in w._mark_items if isinstance(i, pg.TextItem)]
        assert len(texts) == 1, "峰顶注记应为单条合并注记"
        assert texts[0].toPlainText() == "A4 -8¢", "音名与音分之间须有分隔空格"
        tr = texts[0].sceneBoundingRect()
        px = w._hz_to_display_x(440.0)
        py = w._linear_to_display_y(0.5, 440.0)
        vb = w.plot_widget.getPlotItem().vb
        from PyQt6.QtCore import QPointF
        peak_scene = vb.childGroup.mapToScene(QPointF(px, py))
        assert tr.bottom() <= peak_scene.y() - 6, (
            "峰顶注记底边未与峰顶标记垂直错开（叠字）")
    finally:
        w.setParent(None)
        host.deleteLater()


def test_l5_cmap_combo_fits_longest_item(qapp):
    w = _make_spec()
    cmb = w.cmb_cmap
    fm = cmb.fontMetrics()
    longest = max((cmb.itemText(i) for i in range(cmb.count())),
                  key=lambda s: fm.horizontalAdvance(s))
    need = fm.horizontalAdvance(longest)
    assert cmb.minimumWidth() >= need, (
        f"色板下拉最小宽 {cmb.minimumWidth()} < 最长项文本宽 {need}（窄宽被压裁切）")


def test_l6_3d_time_axis_unit_and_ticks(qapp):
    from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget
    sr, sig = _sr_sig()
    w = Spectrogram3DWidget()
    w.set_audio(sig, sr)
    w.spn_t0.setValue(3.5)
    w.spn_t1.setValue(4.5)
    w.render()
    w.figure.canvas.draw()
    ax = w.ax_3d
    # 单位口径：3D 时间轴用自定义格式（毫秒/分秒） convey 单位，轴题不带 (s)
    # （test_spectrogram3d::test_all_modes_render 的既定约定，二者不可同时加后缀）。
    assert ax.get_ylabel() == "时间"
    lo, hi = ax.yaxis.get_view_interval()
    ticks = ax.yaxis.get_major_locator().tick_values(lo, hi)
    assert len(ticks) >= 2, f"3D 时间轴刻度仅 {len(ticks)} 个"
