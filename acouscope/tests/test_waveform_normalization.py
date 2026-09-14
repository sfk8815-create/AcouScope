# SPDX-License-Identifier: GPL-3.0-only
"""波形归一化显示单元测试。"""

import numpy as np
import pytest


class TestWaveformNormalization:
    """WaveformWidget 归一化功能测试。"""

    @pytest.fixture
    def widget(self, qapp):
        from acouscope.ui.widgets.waveform import WaveformWidget
        w = WaveformWidget()
        # 生成幅度为 0.3 的信号（不归一时峰值只有 0.3）
        sr = 44100
        t = np.linspace(0, 1.0, sr)
        signal = 0.3 * np.sin(2 * np.pi * 440 * t)
        w.set_data(t, signal, sample_rate=sr)
        return w

    def test_default_not_normalized(self, widget):
        assert widget.is_normalized() is False

    def test_enable_normalization(self, widget):
        widget.set_normalized(True)
        assert widget.is_normalized() is True
        # 归一化后峰值应为 1.0
        peak = np.max(np.abs(widget._data))
        assert abs(peak - 1.0) < 1e-6

    def test_disable_normalization_restores_original(self, widget):
        original_peak = np.max(np.abs(widget._data))
        widget.set_normalized(True)
        widget.set_normalized(False)
        assert widget.is_normalized() is False
        # 恢复后峰值应等于原始值
        peak = np.max(np.abs(widget._data))
        assert abs(peak - original_peak) < 1e-6

    def test_normalized_peak_is_one(self, widget):
        widget.set_normalized(True)
        peak = np.max(np.abs(widget._data))
        assert abs(peak - 1.0) < 1e-6

    def test_toggle_twice_is_idempotent(self, widget):
        widget.set_normalized(True)
        data1 = widget._data.copy()
        widget.set_normalized(True)  # 重复调用
        data2 = widget._data.copy()
        assert np.allclose(data1, data2)

    def test_set_data_with_normalization_enabled(self, qapp):
        """设置数据时如果归一化已开启，自动归一化。"""
        from acouscope.ui.widgets.waveform import WaveformWidget
        w = WaveformWidget()
        w.set_normalized(True)

        sr = 44100
        t = np.linspace(0, 1.0, sr)
        signal = 0.5 * np.sin(2 * np.pi * 440 * t)
        w.set_data(t, signal, sample_rate=sr)

        peak = np.max(np.abs(w._data))
        assert abs(peak - 1.0) < 1e-6

    def test_zero_signal_no_crash(self, qapp):
        """全零信号归一化不应崩溃。"""
        from acouscope.ui.widgets.waveform import WaveformWidget
        w = WaveformWidget()
        sr = 44100
        t = np.linspace(0, 1.0, sr)
        signal = np.zeros(sr)
        w.set_data(t, signal, sample_rate=sr)
        w.set_normalized(True)  # 不应抛异常
        assert w.is_normalized() is True
