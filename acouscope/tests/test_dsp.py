# SPDX-License-Identifier: GPL-3.0-only
"""DSP 模块测试。"""

import numpy as np
import pytest


class TestFFTEngine:
    """FFTEngine 测试。"""

    @pytest.fixture
    def fft_engine(self):
        from acouscope.dsp.fft import FFTEngine
        return FFTEngine(size=1024, window="hann")

    @pytest.fixture
    def test_signal(self):
        """生成 440Hz 正弦测试信号。"""
        sr = 44100
        n = 1024
        t = np.arange(n) / sr
        signal = np.sin(2 * np.pi * 440 * t)
        return signal

    def test_compute_fft_shape(self, fft_engine, test_signal):
        spectrum = fft_engine.compute_fft(test_signal)
        assert len(spectrum) == 1024
        assert np.iscomplexobj(spectrum)

    def test_magnitude_spectrum(self, fft_engine, test_signal):
        freqs, mag = fft_engine.magnitude_spectrum(test_signal, db_scale=False)
        assert len(freqs) == 513  # n_half = size//2 + 1
        assert len(mag) == len(freqs)
        assert np.all(mag >= 0)

    def test_magnitude_spectrum_db(self, fft_engine, test_signal):
        freqs, mag_db = fft_engine.magnitude_spectrum(test_signal, db_scale=True)
        # dB 范围应该合理
        assert np.max(mag_db) > -100
        assert np.max(mag_db) < 100

    def test_power_spectrum(self, fft_engine, test_signal):
        freqs, power = fft_engine.power_spectrum(test_signal, db_scale=False)
        assert len(freqs) == len(power)
        assert np.all(power >= 0)

    def test_phase_spectrum(self, fft_engine, test_signal):
        freqs, phase = fft_engine.phase_spectrum(test_signal)
        assert len(freqs) == len(phase)
        # 相位在 [-pi, pi] 范围内
        assert np.all(phase >= -np.pi - 0.01)
        assert np.all(phase <= np.pi + 0.01)


class TestWindowFunction:
    """WindowFunction 测试。"""

    def test_hann_window(self):
        from acouscope.dsp.windows import WindowFunction
        w = WindowFunction.get("hann", 1024)
        assert len(w) == 1024
        assert np.all(w >= 0)
        assert np.isclose(w[0], 0, atol=0.01)
        assert np.isclose(w[-1], 0, atol=0.01)
        assert np.isclose(w[512], 1.0, atol=0.01)

    def test_rectangular_window(self):
        from acouscope.dsp.windows import WindowFunction
        w = WindowFunction.get("rectangular", 100)
        assert len(w) == 100
        assert np.all(w == 1.0)


class TestSTFTEngine:
    """STFTEngine 测试。"""

    @pytest.fixture
    def stft_engine(self):
        from acouscope.dsp.stft import STFTEngine
        return STFTEngine(n_fft=256, hop_length=128)

    @pytest.fixture
    def test_signal(self):
        """生成测试信号。"""
        sr = 44100
        duration = 0.1
        t = np.arange(int(sr * duration)) / sr
        signal = 0.5 * np.sin(2 * np.pi * 1000 * t)
        return signal, sr

    def test_compute_shape(self, stft_engine, test_signal):
        signal, sr = test_signal
        freqs, times, S = stft_engine.compute(signal, sr)

        assert len(freqs) == 129  # n_fft//2 + 1
        assert S.shape[0] == len(freqs)
        assert S.shape[1] == len(times)
        assert np.iscomplexobj(S)

    def test_magnitude(self, stft_engine, test_signal):
        signal, sr = test_signal
        freqs, times, mag = stft_engine.magnitude(signal, sr, db_scale=False)

        assert len(freqs) == mag.shape[0]
        assert len(times) == mag.shape[1]
        assert np.all(mag >= 0)

    def test_magnitude_db(self, stft_engine, test_signal):
        signal, sr = test_signal
        freqs, times, mag_db = stft_engine.magnitude(signal, sr, db_scale=True)

        assert mag_db.shape == (len(freqs), len(times))
        # dB 值应该在合理范围
        assert np.nanmax(mag_db) < 100
        assert np.nanmin(mag_db) > -200
