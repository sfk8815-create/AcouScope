# SPDX-License-Identifier: GPL-3.0-only
"""波形交互测试：播放头加载后可见 + 拖拽状态机初始化 + 缩放（蓝条已移除）。"""

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


def test_playhead_visible_after_load(widget):
    """加载音频后播放头必须可见（T-AUD-08 hide() 副作用修复）。"""
    assert widget.playhead.isVisible()


def test_drag_mode_initialized(widget):
    """_drag_mode 初始化为 None（蓝条移除后 selection 为唯一模式）。"""
    assert widget._drag_mode is None


def test_zoom_around_playhead(widget, qapp):
    """缩放以播放头位置为中心（播放头可见时）。"""
    widget.playhead.setPos(2.5)
    widget.playhead.show()
    qapp.processEvents()
    x0_0, x1_0 = widget.plot_widget.viewRange()[0]
    widget.zoom_in()
    qapp.processEvents()
    x0_1, x1_1 = widget.plot_widget.viewRange()[0]
    center = (x0_1 + x1_1) / 2.0
    assert abs(center - 2.5) < 0.5, f"缩放中心应≈2.5, 实际={center}"
