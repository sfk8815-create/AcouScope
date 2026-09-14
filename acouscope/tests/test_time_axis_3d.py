# SPDX-License-Identifier: GPL-3.0-only
"""3D 频谱图时间轴接入 NiceTicksLocator 的集成测试。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget
from acouscope.ui.widgets.time_axis import NiceTicksLocator, nice_ticks

SR = 44100


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _chirp(dur=3.0, f0=300.0, f1=2500.0):
    """线性扫频（3s，保证 STFT 有足够帧）。"""
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * (f0 * t + (f1 - f0) / (2 * dur) * t**2)
    return np.sin(phase)


@pytest.fixture
def widget(qapp):
    w = Spectrogram3DWidget()
    w.resize(1000, 600)
    w.set_audio(_chirp(), SR)
    qapp.processEvents()
    w.canvas.draw()
    yield w
    w.close()


def test_3d_yaxis_major_locator_is_nice_ticks(widget):
    """曲面模式：y 轴主 Locator 必须是 NiceTicksLocator。"""
    loc = widget.ax_3d.yaxis.get_major_locator()
    assert isinstance(loc, NiceTicksLocator)
    assert loc._minor is False


def test_3d_yaxis_minor_locator_is_nice_ticks(widget):
    """曲面模式：y 轴次 Locator 必须是 minor=True 的 NiceTicksLocator。"""
    loc = widget.ax_3d.yaxis.get_minor_locator()
    assert isinstance(loc, NiceTicksLocator)
    assert loc._minor is True


def test_3d_major_ticks_match_nice_ticks(widget):
    """渲染后主刻度位置与 nice_ticks(当前视图范围, 实际像素宽) 一致且不越界。"""
    ax = widget.ax_3d
    vmin, vmax = ax.yaxis.get_view_interval()
    loc = ax.yaxis.get_major_locator()
    pixel_width = loc._get_pixel_width()
    expected = nice_ticks(float(vmin), float(vmax), pixel_width, 90.0)
    actual = [float(v) for v in ax.yaxis.get_majorticklocs()]
    actual_in = [v for v in actual if vmin - 1e-6 <= v <= vmax + 1e-6]
    exp_in = [float(v) for v in expected.majors
              if vmin - 1e-6 <= v <= vmax + 1e-6]
    assert len(actual_in) == len(exp_in)
    for a, b in zip(sorted(actual_in), sorted(exp_in)):
        assert abs(a - b) < 1e-6, f"主刻度 {a} 与 nice_ticks 期望 {b} 不一致"


def test_3d_waterfall_mode_also_uses_nice_ticks(widget, qapp):
    """瀑布模式（ylim 反向）：Locator 仍为 NiceTicksLocator 且不崩。"""
    widget.cmb_mode.setCurrentIndex(1)  # 0=曲面 1=瀑布 2=消隐瀑布
    qapp.processEvents()
    widget.canvas.draw()
    assert isinstance(widget.ax_3d.yaxis.get_major_locator(), NiceTicksLocator)
    assert isinstance(widget.ax_3d.yaxis.get_minor_locator(), NiceTicksLocator)


def test_3d_rerender_keeps_nice_locator(widget, qapp):
    """重绘（ax.clear() 会复位 Locator）后必须重新挂上 NiceTicksLocator。"""
    widget.render()
    qapp.processEvents()
    widget.canvas.draw()
    assert isinstance(widget.ax_3d.yaxis.get_major_locator(), NiceTicksLocator)
    assert isinstance(widget.ax_3d.yaxis.get_minor_locator(), NiceTicksLocator)


def test_3d_waterfall_time_ticks_present(widget, qapp):
    """瀑布/消隐瀑布模式（反向 ylim）：时间轴主刻度必须非空（bug 修复端到端）。"""
    for mode_idx in (1, 2):  # 1=瀑布 2=消隐瀑布
        widget.cmb_mode.setCurrentIndex(mode_idx)
        qapp.processEvents()
        widget.canvas.draw()
        major = [float(v) for v in widget.ax_3d.yaxis.get_majorticklocs()]
        assert major, f"模式 {mode_idx} 时间轴主刻度为空（反转区间未修复）"
        assert isinstance(widget.ax_3d.yaxis.get_major_locator(), NiceTicksLocator)
