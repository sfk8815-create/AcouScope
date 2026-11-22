# SPDX-License-Identifier: GPL-3.0-only
"""D8 守卫：FFT 幅度读数取曲线在游标处之值。

离屏实例化 SpectrumWidget，注入已知峰值，断言 lbl_mag 读数等于注入值；
覆盖 linear 与 dBFS 两档。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.dsp.units import linear_to_dbfs
from acouscope.ui.widgets.spectrum import SpectrumWidget


@pytest.fixture
def spectrum(qapp):
    w = SpectrumWidget()
    yield w
    w.close()


def _inject_peak(w, freq_hz=520.73, mag_lin=0.7029):
    """注入包含单峰的频谱数据，freq_unit 改 hz 简化换算。"""
    freqs = np.array([100.0, freq_hz, 1000.0, 2000.0, 4000.0])
    mags = np.array([0.1, mag_lin, 0.05, 0.02, 0.01])
    w.set_data(freqs, mags, sample_rate=44100.0)
    w._freq_unit = "hz"
    return freq_hz, mag_lin


def test_spectrum_readout_linear(spectrum, qapp):
    """linear 档：lbl_mag 应显示曲线在游标处的线幅值（.4f）。"""
    freq_hz, mag_lin = _inject_peak(spectrum)
    spectrum.v_line.setPos(freq_hz)
    spectrum._on_cursor_moved()
    assert f"{mag_lin:.4f}" in spectrum.lbl_mag.text()


def test_spectrum_readout_dbfs(spectrum, qapp):
    """dBFS 档：lbl_mag 应与 linear_to_dbfs(注入值) 一致（±0.1）。"""
    freq_hz, mag_lin = _inject_peak(spectrum)
    spectrum.cmb_y_unit.setCurrentIndex(2)  # dBFS
    spectrum.v_line.setPos(freq_hz)
    spectrum._on_cursor_moved()
    expected = linear_to_dbfs(mag_lin)
    assert f"{expected:.1f}" in spectrum.lbl_mag.text()


def test_spectrum_readout_h_line_synced(spectrum, qapp):
    """h_line 位置应等于曲线在游标处的当前显示单位值（±1e-6）。"""
    freq_hz, mag_lin = _inject_peak(spectrum)
    spectrum.v_line.setPos(freq_hz)
    spectrum._on_cursor_moved()
    expected_y = spectrum._linear_to_display_y(mag_lin, freq_hz)
    assert abs(spectrum.h_line.value() - expected_y) < 1e-6


def test_spectrum_readout_h_line_not_movable(spectrum, qapp):
    """h_line 已成读数指示线，movable 必为 False。"""
    assert spectrum.h_line.movable is False
