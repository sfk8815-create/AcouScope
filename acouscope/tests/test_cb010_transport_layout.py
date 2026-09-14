# SPDX-License-Identifier: GPL-3.0-only
"""CB-010 P0-3 / T-906：传输条归位波形视图顶部 + 全局化测试。

背景：transport_bar 原位于 analysis_panel 底部（analysis_layout 末行）；
CB-010 P0-3 将其迁入波形视图区顶部——与 waveform_widget 同容器
（waveform_view：TransportBar 上、Waveform 下，仿 DAW 内嵌传输条）。
T-906（CB-015-1 契约落地）：传输条**跨视图常驻**，不再随波形视图显隐
（用户真机反馈切 FFT/语谱图/音高/共振峰/音色/3D 时传输条消失）。
TransportBar 内部逻辑与信号连接零改动。

覆盖验收：
  ① 结构：transport_bar 父容器 = 波形区顶部（waveform_view），
     不再挂 analysis_panel；布局序 TransportBar(0) 上、Waveform(1) 下；
  ② 显隐（T-906 新语义）：index0 波形视图 → 传输条可见；
     index>0 分析面板视图 → **仍可见**（恒可见）；
     视图失效（换音频）→ 仍可见（接线三调用点保留，仅不再改变可见性）；
  ③ 源码锚点：`_sync_transport_visibility` 不含 `setVisible(index == 0)`
     式视图门控（防回归）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter, QStackedWidget

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.transport_bar import TransportBar


def _make_window(qapp, monkeypatch, tmp_path):
    """带已加载音频的 MainWindow（不 show）；禁真实分析构建。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 5.0)) / sr
    x = 0.5 * np.sin(2 * np.pi * 440 * t)
    controller.load_from_array(x, sr)

    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    # 禁真实分析构建：本文件只验证布局归属与显隐接线
    monkeypatch.setattr(w, "_build_analysis_view", lambda index: None)
    return w


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    w = _make_window(qapp, monkeypatch, tmp_path)
    qapp.processEvents()
    yield w
    w.close()


def _inner_vertical_splitter(window) -> QSplitter:
    """常规页（central_stack index0）= 垂直 QSplitter（波形视图上 / 分析面板下）。"""
    sp = window.ws_splitter
    stack = sp.widget(1)
    assert isinstance(stack, QStackedWidget), "中心应为 central_stack"
    inner = stack.widget(0)
    assert isinstance(inner, QSplitter), "常规页应为垂直 QSplitter"
    assert inner.orientation() == Qt.Orientation.Vertical
    return inner


def test_transport_bar_parented_to_waveform_view(window):
    """验收①：transport_bar 父容器 = 波形区顶部容器（非 analysis_panel）。"""
    inner = _inner_vertical_splitter(window)
    assert inner.widget(0) is window.waveform_view, "顶部应为波形视图容器"
    assert inner.widget(1) is window.analysis_panel

    assert window.transport_bar.parent() is window.waveform_view
    assert window.waveform_widget.parent() is window.waveform_view
    assert window.transport_bar not in window.analysis_panel.findChildren(TransportBar)


def test_transport_bar_above_waveform_in_layout(window):
    """验收①（布局序）：waveform_view 内 TransportBar(0) 上、Waveform(1) 下。"""
    lay = window.waveform_view.layout()
    assert lay is not None
    assert lay.itemAt(0).widget() is window.transport_bar
    assert lay.itemAt(1).widget() is window.waveform_widget


def test_transport_visible_in_waveform_view(window, qapp):
    """验收②：index0 波形视图 → 传输条可见。"""
    window.analysis_tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    tb = window.transport_bar
    assert not tb.isHidden(), "波形视图下传输条应可见"
    assert tb.isVisibleTo(window.waveform_view)


def test_transport_visible_in_analysis_view(window, qapp):
    """验收②（T-906）：index>0 分析面板视图 → 传输条仍可见（跨视图常驻）。"""
    window.analysis_tab_bar.setCurrentIndex(1)
    qapp.processEvents()
    assert not window.transport_bar.isHidden(), "T-906：分析面板视图下传输条应常驻可见"
    # 切回波形视图 → 仍可见
    window.analysis_tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    assert not window.transport_bar.isHidden()


def test_transport_visible_after_view_invalidate(window, qapp):
    """验收②（T-906）：分析视图失效（换音频/关闭）→ 传输条仍可见。"""
    window.analysis_tab_bar.setCurrentIndex(1)
    qapp.processEvents()
    assert not window.transport_bar.isHidden(), "T-906：分析视图下传输条应常驻可见"

    window._invalidate_analysis_views()
    qapp.processEvents()
    assert not window.transport_bar.isHidden(), "视图失效后传输条应仍可见"
    assert window.transport_bar.isVisibleTo(window.waveform_view)


def test_sync_transport_visibility_no_view_gating():
    """验收③（源码锚点）：`_sync_transport_visibility` 不含视图门控（防回归）。"""
    import inspect

    src = inspect.getsource(MainWindow._sync_transport_visibility)
    assert "setVisible(index == 0)" not in src, (
        "T-906：_sync_transport_visibility 不应再含 setVisible(index == 0) 视图门控"
    )
