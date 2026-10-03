# SPDX-License-Identifier: GPL-3.0-only
"""T-1063: AudioPlayer._resample_chunk ON/OFF 逐位对等测试（原生 Rust vs numpy）。

覆盖：等长 / 升2× / 降非整比 / m=1 / 空 / 单样本 / 真实尺寸（R-2 分叉点）
      / dtype f32·f64·int32 / 负对照
"""

import os as _os

import numpy as np
import pytest


class TestResampleChunkNative:
    """ON vs OFF 逐位对等全覆盖。"""

    @pytest.fixture
    def player(self):
        from acouscope.audio.player import AudioPlayer
        return AudioPlayer()

    # ------------------------------------------------------------------
    # 核心帮助：用同一组输入，分别跑 OFF 和 ON，assert_array_equal
    # ------------------------------------------------------------------
    def _off(self, player, data, target_length):
        old = _os.environ.get("ACOUSCOPE_NATIVE")
        try:
            _os.environ["ACOUSCOPE_NATIVE"] = "0"
            return player._resample_chunk(data, target_length)
        finally:
            if old is None:
                _os.environ.pop("ACOUSCOPE_NATIVE", None)
            else:
                _os.environ["ACOUSCOPE_NATIVE"] = old

    def _on(self, player, data, target_length):
        old = _os.environ.get("ACOUSCOPE_NATIVE")
        try:
            _os.environ["ACOUSCOPE_NATIVE"] = "1"
            return player._resample_chunk(data, target_length)
        finally:
            if old is None:
                _os.environ.pop("ACOUSCOPE_NATIVE", None)
            else:
                _os.environ["ACOUSCOPE_NATIVE"] = old

    def _assert_equal(self, player, data, target_length):
        off = self._off(player, data, target_length)
        on = self._on(player, data, target_length)
        np.testing.assert_array_equal(on, off)
        assert on.dtype == off.dtype

    # ------------------------------------------------------------------
    # 1. 基本形状与边界
    # ------------------------------------------------------------------
    def test_equal_length_pass_through(self, player):
        data = np.arange(100, dtype=np.float64)
        self._assert_equal(player, data, 100)

    def test_up_2x(self, player):
        data = np.arange(50, dtype=np.float64)
        self._assert_equal(player, data, 100)

    def test_down_non_integer(self, player):
        data = np.arange(500, dtype=np.float64)
        self._assert_equal(player, data, 333)

    def test_m_returns_first_sample(self, player):
        """np.linspace(0, n-1, 1) = [0.0] → interp = [data[0]]"""
        data = np.array([3.14, 1.41, 2.71], dtype=np.float64)
        self._assert_equal(player, data, 1)

    def test_empty_data(self, player):
        """n=0, m>0 → np.zeros(m)"""
        data = np.array([], dtype=np.float64)
        self._assert_equal(player, data, 10)

    def test_zero_target(self, player):
        """m=0 → 空数组"""
        data = np.arange(20, dtype=np.float64)
        self._assert_equal(player, data, 0)

    def test_single_sample(self, player):
        """n=1, m=5"""
        data = np.array([7.0], dtype=np.float64)
        self._assert_equal(player, data, 5)

    # ------------------------------------------------------------------
    # 2. R-2 真实尺寸（先除 vs 先乘分叉点 · 审计实测 n=2001/m=2048 非逐位）
    # ------------------------------------------------------------------
    def test_real_size_n2001_m2048(self, player):
        rs = np.random.RandomState(42)
        data = rs.randn(2001).astype(np.float64)
        self._assert_equal(player, data, 2048)

    def test_real_size_n4096_m1000(self, player):
        rs = np.random.RandomState(42)
        data = rs.randn(4096).astype(np.float64)
        self._assert_equal(player, data, 1000)

    def test_real_size_random_1000(self, player):
        """≥1e3 随机样·与判据②完全同口径"""
        rs = np.random.RandomState(7)
        data = rs.randn(1000).astype(np.float64)
        self._assert_equal(player, data, 777)

    # ------------------------------------------------------------------
    # 3. dtype 覆盖
    # ------------------------------------------------------------------
    def test_dtype_float32(self, player):
        data = np.arange(100, dtype=np.float32)
        self._assert_equal(player, data, 55)
        # 等长分支（原样返回）
        self._assert_equal(player, data, 100)

    def test_dtype_float64(self, player):
        data = np.arange(100, dtype=np.float64)
        self._assert_equal(player, data, 55)

    def test_dtype_int32(self, player):
        """int 入·np.interp 算 f64·astype(int32) 出"""
        data = np.arange(0, 200, 2, dtype=np.int32)
        self._assert_equal(player, data, 77)

    # ------------------------------------------------------------------
    # 4. 负对照：改 data 一点 → ON 侧必变（证对等断言非恒真）
    # ------------------------------------------------------------------
    def test_negative_control(self, player):
        rs = np.random.RandomState(99)
        data = rs.randn(200).astype(np.float64)
        off_orig = self._off(player, data, 150)
        # 改一个值后，ON 侧应与 off_orig 不同
        data2 = data.copy()
        data2[50] = 999.0
        on_changed = self._on(player, data2, 150)
        # 改了一个值，输出必定至少有一个位置不同
        assert not np.array_equal(on_changed, off_orig), \
            "负对照失败：改 data[50]=999.0 后 ON 侧输出未变 → 对等断言可能恒真"

    # ------------------------------------------------------------------
    # 5. 默认 OFF 守卫：不传 env / env!=1 时走原 numpy 分支
    # ------------------------------------------------------------------
    def test_default_off_unchanged(self, player):
        """清除 env 后跑，结果与手动 OFF 完全一致"""
        data = np.arange(200, dtype=np.float64)
        old = _os.environ.get("ACOUSCOPE_NATIVE")
        try:
            _os.environ.pop("ACOUSCOPE_NATIVE", None)
            default = player._resample_chunk(data, 123)
            _os.environ["ACOUSCOPE_NATIVE"] = "0"
            off = player._resample_chunk(data, 123)
            np.testing.assert_array_equal(default, off)
        finally:
            if old is not None:
                _os.environ["ACOUSCOPE_NATIVE"] = old
