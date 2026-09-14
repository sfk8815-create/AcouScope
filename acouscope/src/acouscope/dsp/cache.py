# SPDX-License-Identifier: GPL-3.0-only
"""分析引擎缓存。

避免参数变化时重复创建分析引擎对象，提升响应速度。
按参数组合缓存引擎实例，相同参数直接复用。
"""

from __future__ import annotations

from typing import Any, Optional


class AnalysisCache:
    """分析引擎 LRU 风格缓存。

    用法::

        cache = AnalysisCache(max_size=10)

        # 获取或创建
        engine = cache.get_or_create("stft", {"n_fft": 2048, "hop_length": 512},
                                     lambda: STFTEngine(n_fft=2048, hop_length=512))

        # 清空缓存
        cache.clear()
    """

    def __init__(self, max_size: int = 10):
        self._max_size = max_size
        self._cache: dict[str, Any] = {}
        self._access_order: list[str] = []  # 最近使用的在末尾

    @staticmethod
    def _make_key(prefix: str, params: dict) -> str:
        """将参数转为稳定的字符串键。"""
        # 对 key 排序保证参数顺序不影响键
        items = sorted(params.items(), key=lambda x: x[0])
        param_str = ",".join(f"{k}={v}" for k, v in items)
        return f"{prefix}:{param_str}"

    def get_or_create(self, prefix: str, params: dict, factory) -> Any:
        """获取缓存的引擎，不存在则用 factory 创建并缓存。

        Args:
            prefix: 类别前缀（如 "stft", "timbre", "formant"）
            params: 参数字典，用于生成缓存键
            factory: 无参工厂函数，用于创建新实例

        Returns:
            缓存的引擎实例
        """
        key = self._make_key(prefix, params)

        if key in self._cache:
            # 移到末尾表示最近使用
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]

        # 创建新实例
        obj = factory()
        self._cache[key] = obj
        self._access_order.append(key)

        # 超出最大容量时淘汰最久未用的
        if len(self._cache) > self._max_size:
            oldest = self._access_order.pop(0)
            del self._cache[oldest]

        return obj

    def get(self, prefix: str, params: dict) -> Optional[Any]:
        """仅获取，不创建。"""
        key = self._make_key(prefix, params)
        if key in self._cache:
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None

    def clear(self, prefix: Optional[str] = None):
        """清空缓存。

        Args:
            prefix: 只清除指定前缀的缓存，None 清除全部
        """
        if prefix is None:
            self._cache.clear()
            self._access_order.clear()
        else:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix + ":")]
            for k in keys_to_remove:
                del self._cache[k]
                self._access_order.remove(k)

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, item) -> bool:
        return item in self._cache
