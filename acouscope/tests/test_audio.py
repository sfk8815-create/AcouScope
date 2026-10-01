# SPDX-License-Identifier: GPL-3.0-only
"""音频 I/O 模块测试。"""

import numpy as np
import pytest


class TestAudioIO:
    """AudioIO 测试。"""

    @pytest.fixture
    def audio_io(self):
        from acouscope.audio.io import AudioIO
        return AudioIO()

    @pytest.fixture
    def test_signal(self):
        """生成测试信号（440Hz 正弦波）。"""
        sr = 44100
        duration = 0.5
        t = np.arange(int(sr * duration)) / sr
        signal = 0.5 * np.sin(2 * np.pi * 440 * t)
        return signal, sr

    def test_save_and_load_wav(self, audio_io, test_signal, tmp_path):
        signal, sr = test_signal
        filepath = tmp_path / "test.wav"

        # 保存
        audio_io.save(signal, sr, filepath)

        assert filepath.exists()
        assert filepath.stat().st_size > 0

        # 加载
        loaded, loaded_sr = audio_io.load(filepath)

        assert loaded_sr == sr
        assert len(loaded) == len(signal)
        # 检查信号相关性（允许量化误差）
        correlation = np.corrcoef(signal, loaded)[0, 1]
        assert correlation > 0.99

    def test_get_info(self, audio_io, test_signal, tmp_path):
        signal, sr = test_signal
        filepath = tmp_path / "test.wav"
        audio_io.save(signal, sr, filepath)

        info = audio_io.get_info(filepath)

        assert info.sample_rate == sr
        assert info.channels == 1
        assert abs(info.duration - len(signal) / sr) < 0.01
        assert info.format in ("WAV", "WAVEX")

    def test_load_mono_conversion(self, audio_io, test_signal, tmp_path):
        # 创建立体声文件需要额外测试
        # 这里只测试单声道加载
        signal, sr = test_signal
        filepath = tmp_path / "mono.wav"
        audio_io.save(signal, sr, filepath)

        loaded, _ = audio_io.load(filepath, mono=True)
        assert loaded.ndim == 1
