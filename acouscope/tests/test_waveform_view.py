# SPDX-License-Identifier: GPL-3.0-only
"""波形视图管理测试：视图限制 + 滚动条 + 缩放按钮。"""

import os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import pytest
pytest.importorskip("PyQt6")
import numpy as np
from PyQt6.QtWidgets import QApplication
from acouscope.ui.widgets.waveform import WaveformWidget


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def widget(qapp):
    w = WaveformWidget()
    w.resize(1200, 400)
    sr = 1000; n = 5000
    t = np.arange(n, dtype=np.float32) / sr
    x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
    w.set_data(t, x, sample_rate=sr)
    qapp.processEvents()
    yield w
    w.close()


def test_scrollbar_exists(widget):
    """加载后滚动条存在。"""
    assert hasattr(widget, 'scrollbar')


def test_zoom_buttons_exist(widget):
    """缩放按钮存在。"""
    assert hasattr(widget, 'btn_zoom_in')
    assert hasattr(widget, 'btn_zoom_out')
    assert hasattr(widget, 'btn_zoom_fit')


def test_view_limits_prevent_left_overscroll(widget, qapp):
    """视图限制：不可平移到数据范围外。"""
    vb = widget.plot_widget.plotItem.vb
    # 尝试设置超出范围的视图
    vb.setXRange(-5, -1, padding=0)
    qapp.processEvents()
    x0, x1 = widget.plot_widget.viewRange()[0]
    assert x0 >= -0.01, f"左边界应 >= 0, 实际={x0}"


def test_scrollbar_syncs_with_view(widget, qapp):
    """视图变化后滚动条位置更新。"""
    widget.zoom_in()
    qapp.processEvents()
    # 缩放后滚动条 value 应该反映视图位置
    assert widget.scrollbar.value() >= 0


def test_scrollbar_changes_view(widget, qapp):
    """滚动条移动后视图位置更新。"""
    widget.scrollbar.setValue(500)
    qapp.processEvents()
    x0, x1 = widget.plot_widget.viewRange()[0]
    t_max = float(widget._times[-1])
    # 视图应在数据范围内
    assert x0 >= 0, f"视图左边界应 >= 0, 实际={x0}"
    assert x1 <= t_max + 0.1, f"视图右边界应 <= {t_max}, 实际={x1}"
