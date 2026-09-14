# SPDX-License-Identifier: GPL-3.0-only
"""播放速率控制单元测试。"""

import numpy as np
import pytest


class TestPlaybackRate:
    """AudioPlayer 播放速率功能测试。"""

    @pytest.fixture
    def player(self):
        from acouscope.audio.player import AudioPlayer
        p = AudioPlayer()
        p._data = np.zeros(44100 * 3, dtype=np.float32)
        p._sample_rate = 44100
        return p

    def test_default_rate_is_1(self, player):
        assert abs(player.get_rate() - 1.0) < 1e-9

    def test_set_rate_faster(self, player):
        player.set_rate(2.0)
        assert abs(player.get_rate() - 2.0) < 1e-9

    def test_set_rate_slower(self, player):
        player.set_rate(0.5)
        assert abs(player.get_rate() - 0.5) < 1e-9

    def test_rate_clamped_to_min(self, player):
        player.set_rate(0.1)
        assert abs(player.get_rate() - 0.25) < 1e-9  # 下限 0.25

    def test_rate_clamped_to_max(self, player):
        player.set_rate(10.0)
        assert abs(player.get_rate() - 4.0) < 1e-9  # 上限 4.0

    def test_rate_1_is_noop(self, player):
        player.set_rate(1.0)
        assert abs(player.get_rate() - 1.0) < 1e-9

    def test_resample_chunk_same_length(self, player):
        data = np.sin(np.linspace(0, 2 * np.pi, 100)).astype(np.float32)
        result = player._resample_chunk(data, 100)
        assert len(result) == 100
        assert np.allclose(result, data)

    def test_resample_chunk_upsample(self, player):
        data = np.sin(np.linspace(0, 2 * np.pi, 100)).astype(np.float32)
        result = player._resample_chunk(data, 200)
        assert len(result) == 200
        # 端点应一致
        assert abs(result[0] - data[0]) < 1e-6
        assert abs(result[-1] - data[-1]) < 1e-6

    def test_resample_chunk_downsample(self, player):
        data = np.sin(np.linspace(0, 2 * np.pi, 200)).astype(np.float32)
        result = player._resample_chunk(data, 100)
        assert len(result) == 100
        assert abs(result[0] - data[0]) < 1e-6

    def test_resample_chunk_empty(self, player):
        data = np.array([], dtype=np.float32)
        result = player._resample_chunk(data, 100)
        assert len(result) == 100
        assert np.all(result == 0)

    def test_resample_chunk_target_zero(self, player):
        data = np.ones(100, dtype=np.float32)
        result = player._resample_chunk(data, 0)
        assert len(result) == 0


class TestRateConsumptionDirection:
    """样本消耗方向（防速率倒挂回归；用户真机发现后修正）。

    语义：输出块固定 chunk_size 样本；rate>1（快放）应消耗更多源样本，
    rate<1（慢放）消耗更少。历史 bug：n_read = chunk_size / rate 写反，
    0.5x 反而 2x 快放（用户真机发现）。
    """

    @pytest.fixture
    def player(self):
        from acouscope.audio.player import AudioPlayer
        p = AudioPlayer()
        p._data = np.zeros(44100 * 3, dtype=np.float32)
        p._sample_rate = 44100
        # mock 写入恒成功（不触真实设备），只观测 _position 推进
        p._write_chunk_full = lambda chunk: True
        return p

    def test_rate_2_consumes_double_source_samples(self, player):
        """rate=2.0：每输出块消耗 2x chunk_size 源样本（快放）。"""
        player._position = 0
        assert player._write_next_chunk(2048, 2.0) is True
        assert player._position == int(2048 * 2.0)

    def test_rate_05_consumes_half_source_samples(self, player):
        """rate=0.5：每输出块消耗 0.5x chunk_size 源样本（慢放）。"""
        player._position = 0
        assert player._write_next_chunk(2048, 0.5) is True
        assert player._position == int(2048 * 0.5)

    def test_consumption_monotonic_in_rate(self, player):
        """消耗量随 rate 单调递增（0.5 < 1.0 < 2.0），防倒挂。"""
        consumed = {}
        for rate in (0.5, 1.0, 2.0):
            player._position = 0
            assert player._write_next_chunk(2048, rate) is True
            consumed[rate] = player._position
        assert consumed[0.5] < consumed[1.0] < consumed[2.0]


class TestControllerRate:
    """Controller 速率接口测试。"""

    @pytest.fixture
    def controller(self):
        from acouscope.app.controller import AppController
        c = AppController()
        c.audio_player._data = np.zeros(44100 * 3, dtype=np.float32)
        c.audio_player._sample_rate = 44100
        return c

    def test_set_and_get_rate(self, controller):
        controller.set_playback_rate(1.5)
        assert abs(controller.audio_player.get_rate() - 1.5) < 1e-9

    def test_default_rate(self, controller):
        assert abs(controller.audio_player.get_rate() - 1.0) < 1e-9
