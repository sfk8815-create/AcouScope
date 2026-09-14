# SPDX-License-Identifier: GPL-3.0-only
"""分析引擎缓存单元测试。"""

import pytest


class _FakeEngine:
    """测试用的假引擎。"""
    def __init__(self, value=0):
        self.value = value
        self.id = id(self)


class TestAnalysisCache:
    """AnalysisCache 测试。"""

    @pytest.fixture
    def cache(self):
        from acouscope.dsp.cache import AnalysisCache
        return AnalysisCache(max_size=3)

    def test_create_and_get(self, cache):
        engine = cache.get_or_create("stft", {"n_fft": 2048}, lambda: _FakeEngine(1))
        assert engine.value == 1
        assert len(cache) == 1

    def test_get_cached_same_object(self, cache):
        e1 = cache.get_or_create("stft", {"n_fft": 2048}, lambda: _FakeEngine(1))
        e2 = cache.get_or_create("stft", {"n_fft": 2048}, lambda: _FakeEngine(999))
        # 应该是同一个对象（第二次调用 factory 不会执行）
        assert e1 is e2
        assert e1.value == 1  # 第一个创建的值

    def test_different_params_different_cache(self, cache):
        e1 = cache.get_or_create("stft", {"n_fft": 2048}, lambda: _FakeEngine(1))
        e2 = cache.get_or_create("stft", {"n_fft": 1024}, lambda: _FakeEngine(2))
        assert e1 is not e2
        assert e1.value == 1
        assert e2.value == 2
        assert len(cache) == 2

    def test_different_prefix_different_cache(self, cache):
        e1 = cache.get_or_create("stft", {"sr": 44100}, lambda: _FakeEngine(1))
        e2 = cache.get_or_create("timbre", {"sr": 44100}, lambda: _FakeEngine(2))
        assert e1 is not e2
        assert len(cache) == 2

    def test_lru_eviction(self, cache):
        """超出 max_size 时淘汰最久未用的。"""
        e1 = cache.get_or_create("a", {"x": 1}, lambda: _FakeEngine(1))
        e2 = cache.get_or_create("b", {"x": 1}, lambda: _FakeEngine(2))
        e3 = cache.get_or_create("c", {"x": 1}, lambda: _FakeEngine(3))
        assert len(cache) == 3

        # 访问 e1，使其变为最近使用
        cache.get_or_create("a", {"x": 1}, lambda: _FakeEngine(99))

        # 添加第 4 个，应淘汰最久未用的 e2
        e4 = cache.get_or_create("d", {"x": 1}, lambda: _FakeEngine(4))
        assert len(cache) == 3

        # e2 应该被淘汰了
        assert cache.get("b", {"x": 1}) is None
        # e1, e3, e4 还在
        assert cache.get("a", {"x": 1}) is e1
        assert cache.get("c", {"x": 1}) is e3
        assert cache.get("d", {"x": 1}) is e4

    def test_clear_all(self, cache):
        cache.get_or_create("a", {"x": 1}, lambda: _FakeEngine(1))
        cache.get_or_create("b", {"x": 1}, lambda: _FakeEngine(2))
        assert len(cache) == 2
        cache.clear()
        assert len(cache) == 0

    def test_clear_by_prefix(self, cache):
        cache.get_or_create("stft", {"a": 1}, lambda: _FakeEngine(1))
        cache.get_or_create("stft", {"a": 2}, lambda: _FakeEngine(2))
        cache.get_or_create("timbre", {"a": 1}, lambda: _FakeEngine(3))
        assert len(cache) == 3

        cache.clear("stft")
        assert len(cache) == 1
        assert cache.get("timbre", {"a": 1}) is not None
        assert cache.get("stft", {"a": 1}) is None

    def test_get_nonexistent_returns_none(self, cache):
        assert cache.get("stft", {"n_fft": 512}) is None

    def test_param_order_independent(self, cache):
        """参数顺序不同应生成相同的键。"""
        e1 = cache.get_or_create("t", {"a": 1, "b": 2}, lambda: _FakeEngine(1))
        e2 = cache.get_or_create("t", {"b": 2, "a": 1}, lambda: _FakeEngine(2))
        assert e1 is e2

    def test_contains(self, cache):
        cache.get_or_create("stft", {"n": 1}, lambda: _FakeEngine(1))
        assert "stft:n=1" in cache
        assert "stft:n=2" not in cache
