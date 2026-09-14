# SPDX-License-Identifier: GPL-3.0-only
"""分析模块测试。"""

import numpy as np
import pytest


class TestTemporalAnalyzer:
    """时域分析测试。"""

    @pytest.fixture
    def analyzer(self):
        from acouscope.analysis.temporal import TemporalAnalyzer
        return TemporalAnalyzer(sample_rate=44100.0)

    @pytest.fixture
    def test_signal(self):
        """生成带幅度调制的测试信号。"""
        sr = 44100
        duration = 0.2
        t = np.arange(int(sr * duration)) / sr
        # 正弦波 + 指数衰减包络
        envelope = np.exp(-t * 10)
        signal = 0.5 * envelope * np.sin(2 * np.pi * 440 * t)
        return signal

    def test_rms(self, analyzer, test_signal):
        times, rms = analyzer.rms(test_signal, frame_size=1024, hop_size=512)

        assert len(times) == len(rms)
        assert np.all(rms >= 0)
        # RMS 应该小于峰值
        assert np.max(rms) < 0.5

    def test_rms_db(self, analyzer, test_signal):
        times, rms_db = analyzer.rms_db(test_signal, frame_size=1024, hop_size=512)

        assert len(times) == len(rms_db)
        # dB 值应该在合理范围
        assert np.max(rms_db) < 0  # 幅度小于1，所以dB小于0
        assert np.min(rms_db) > -100

    def test_envelope(self, analyzer, test_signal):
        times, envelope = analyzer.envelope(
            test_signal, frame_size=1024, hop_size=512
        )

        assert len(times) == len(envelope)
        assert np.all(envelope >= 0)
        assert np.max(envelope) <= 0.51  # 不超过峰值

    def test_attack_time(self, analyzer, test_signal):
        attack_time = analyzer.attack_time(test_signal, threshold_db=-20)

        assert attack_time >= 0
        # 衰减信号的起振时间应该很短
        assert attack_time < 0.05  # 50ms


class TestSpectralAnalyzer:
    """频谱分析测试。"""

    @pytest.fixture
    def analyzer(self):
        from acouscope.analysis.spectral import SpectralAnalyzer
        return SpectralAnalyzer(sample_rate=44100.0)

    @pytest.fixture
    def test_signal(self):
        """生成 1000Hz 正弦测试信号。"""
        sr = 44100
        n = 8192
        t = np.arange(n) / sr
        signal = np.sin(2 * np.pi * 1000 * t)
        # 加窗减少频谱泄漏
        signal *= np.hanning(n)
        return signal

    def test_fft_spectrum(self, analyzer, test_signal):
        freqs, mag = analyzer.fft_spectrum(test_signal, fft_size=8192, db_scale=False)

        assert len(freqs) == len(mag)
        assert freqs[0] == 0
        assert freqs[-1] > 20000  # 超过 20kHz

        # 峰值应该在 1000Hz 附近
        peak_idx = np.argmax(mag)
        peak_freq = freqs[peak_idx]
        assert abs(peak_freq - 1000) < 20  # 允许 20Hz 误差

    def test_fft_spectrum_db(self, analyzer, test_signal):
        freqs, mag_db = analyzer.fft_spectrum(test_signal, fft_size=8192, db_scale=True)

        assert len(freqs) == len(mag_db)
        # 峰值应该最高
        peak_idx = np.argmax(mag_db)
        assert mag_db[peak_idx] == np.max(mag_db)


class TestPitchAnalyzer:
    """音高分析测试。"""

    @pytest.fixture
    def analyzer(self):
        from acouscope.analysis.pitch import PitchAnalyzer
        return PitchAnalyzer(sample_rate=44100.0, fmin=50, fmax=2000)

    @pytest.fixture
    def test_signal_440(self):
        """生成带谐波的 440Hz 测试信号（锯齿波近似）。"""
        sr = 44100
        duration = 0.2
        t = np.arange(int(sr * duration)) / sr
        # 包含多个谐波，更适合 HPS 检测
        signal = np.zeros_like(t)
        for h in range(1, 8):
            signal += (1.0 / h) * np.sin(2 * np.pi * 440 * h * t)
        # 归一化
        signal = signal / np.max(np.abs(signal)) * 0.5
        # 加淡入淡出
        fade_len = 500
        signal[:fade_len] *= np.linspace(0, 1, fade_len)
        signal[-fade_len:] *= np.linspace(1, 0, fade_len)
        return signal

    def test_detect_hps(self, analyzer, test_signal_440):
        f0 = analyzer.detect_hps(test_signal_440, fft_size=4096, n_harmonics=5)

        # HPS 应该能检测到接近 440Hz 的基频
        # 冒烟测试：HPS 为粗检测算法，精度验收以 pYIN 为准
        # （AT-01-2 谐波复合 ±15 cent，2026-09-03 用户确认，
        #   见 tests/test_pitch_pyin_entry.py::test_at01_2_harmonic）
        assert f0 > 0
        assert abs(f0 - 440) < 50  # 冒烟：仅要求量级正确

    def test_detect_yin(self, analyzer, test_signal_440):
        """测试 YIN 算法检测音高。"""
        # 取中间稳定段
        mid = len(test_signal_440) // 2
        frame = test_signal_440[mid - 1024 : mid + 1024]

        times, f0 = analyzer.detect_yin(frame, frame_size=1024, hop_length=512)

        assert len(times) == len(f0)
        # YIN 精度：cent 口径（AT-01-2 谐波复合 ±15 cent，2026-09-03 用户确认；
        # 消除双标准：本断言为既有 YIN 精度的唯一标准）
        valid = f0 > 0
        assert np.sum(valid) > 0
        mean_f0 = np.mean(f0[valid])
        assert abs(1200.0 * np.log2(mean_f0 / 440.0)) <= 15  # AT-01-2 口径
