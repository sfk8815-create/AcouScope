# SPDX-License-Identifier: GPL-3.0-only
"""音频播放器循环播放功能单元测试。"""

import numpy as np
import pytest


class TestPlayerLoop:
    """AudioPlayer 循环播放功能测试。"""

    @pytest.fixture
    def player(self):
        from acouscope.audio.player import AudioPlayer
        p = AudioPlayer()
        # 填充测试数据
        p._data = np.zeros(44100 * 3, dtype=np.float32)  # 3 秒
        p._sample_rate = 44100
        return p

    def test_set_loop_valid_region(self, player):
        player.set_loop(0.5, 1.5)
        start, end = player.get_loop_region()
        assert abs(start - 0.5) < 1e-9
        assert abs(end - 1.5) < 1e-9

    def test_set_loop_not_enabled_by_default(self, player):
        player.set_loop(0.5, 1.5)
        assert player.is_loop_enabled() is False

    def test_enable_loop(self, player):
        player.set_loop(0.5, 1.5)
        player.set_loop_enabled(True)
        assert player.is_loop_enabled() is True

    def test_disable_loop(self, player):
        player.set_loop(0.5, 1.5)
        player.set_loop_enabled(True)
        player.set_loop_enabled(False)
        assert player.is_loop_enabled() is False

    def test_set_loop_none_clears(self, player):
        player.set_loop(0.5, 1.5)
        player.set_loop_enabled(True)
        player.set_loop(None, None)
        start, end = player.get_loop_region()
        assert start is None
        assert end is None
        assert player.is_loop_enabled() is False

    def test_set_loop_invalid_start_after_end(self, player):
        """起始时间大于结束时间时，应清除循环。"""
        player.set_loop(2.0, 1.0)
        start, end = player.get_loop_region()
        assert start is None
        assert end is None

    def test_set_loop_equal_times(self, player):
        """起始等于结束时，应清除循环。"""
        player.set_loop(1.0, 1.0)
        start, end = player.get_loop_region()
        assert start is None

    def test_enable_loop_without_region(self, player):
        """没有设置区域时启用循环，应保持禁用。"""
        player.set_loop_enabled(True)
        assert player.is_loop_enabled() is False

    def test_loop_region_clamped_to_data_length(self, player):
        """循环区域超出数据长度时应被裁剪。"""
        player.set_loop(2.0, 5.0)  # 数据只有 3 秒
        start, end = player.get_loop_region()
        assert abs(start - 2.0) < 1e-9
        assert abs(end - 3.0) < 1e-9  # 被裁到 3 秒

    def test_loop_region_negative_start_clamped(self, player):
        player.set_loop(-1.0, 1.0)
        start, end = player.get_loop_region()
        assert abs(start - 0.0) < 1e-9
        assert abs(end - 1.0) < 1e-9

    def test_loop_without_data(self, player):
        """没有音频数据时设置循环。"""
        player._data = None
        player.set_loop(0.5, 1.5)
        start, end = player.get_loop_region()
        # 没有数据时也可以设置（内部不裁剪）
        assert start is not None
        assert end is not None


class TestControllerLoop:
    """Controller 循环播放接口测试。"""

    @pytest.fixture
    def controller(self):
        from acouscope.app.controller import AppController
        c = AppController()
        # 手动设置播放器数据
        c.audio_player._data = np.zeros(44100 * 3, dtype=np.float32)
        c.audio_player._sample_rate = 44100
        return c

    def test_set_loop_via_controller(self, controller):
        controller.set_loop(0.5, 1.5)
        start, end = controller.get_loop_region()
        assert abs(start - 0.5) < 1e-9
        assert abs(end - 1.5) < 1e-9

    def test_enable_disable_loop(self, controller):
        controller.set_loop(0.5, 1.5)
        controller.set_loop_enabled(True)
        assert controller.is_loop_enabled() is True
        controller.set_loop_enabled(False)
        assert controller.is_loop_enabled() is False
