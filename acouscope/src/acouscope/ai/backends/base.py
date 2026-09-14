# SPDX-License-Identifier: GPL-3.0-only
"""LLMBackend Protocol：本地/远程后端统一流式对话接口。

LLM_BACKEND_V1 — T-302。仅包装既有 provider（interpreter.make_provider），
不重写任何网络逻辑；行为回归不变（AT-401）。
"""
from __future__ import annotations
from typing import Protocol, Callable, Any
from acouscope.ai.interpreter import make_provider


class LLMBackend(Protocol):
    kind: str
    supports_vision: bool

    def chat_stream(self, messages: list[dict], image_b64: str = "",
                    on_chunk: Callable[[str], None] | None = None,
                    is_cancelled: Any = None) -> str: ...


class _ProviderBackend:
    """组合包装：持有既有 provider 实例，chat_stream 委托 chat()。"""

    def __init__(self, provider, kind: str, supports_vision: bool):
        self._p = provider
        self.kind = kind
        self.supports_vision = supports_vision

    def chat_stream(self, messages, image_b64="", on_chunk=None, is_cancelled=None) -> str:
        return self._p.chat(messages, image_b64=image_b64,
                            on_chunk=on_chunk, is_cancelled=is_cancelled)


class OpenAIBackend(_ProviderBackend):
    def __init__(self, **cfg):
        super().__init__(make_provider("openai", **cfg), "openai", True)


class OllamaBackend(_ProviderBackend):
    def __init__(self, **cfg):
        super().__init__(make_provider("ollama", **cfg), "ollama", True)


def get_backend(kind: str, **cfg) -> LLMBackend:
    if kind == "openai":
        return OpenAIBackend(**cfg)
    if kind == "ollama":
        return OllamaBackend(**cfg)
    raise ValueError(f"unknown backend kind: {kind}")
