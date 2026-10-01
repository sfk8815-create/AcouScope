# SPDX-License-Identifier: GPL-3.0-only
"""T-302: LLMBackend Protocol 一致性与工厂（AT-401 协议统一性）。"""
import sys
sys.path.insert(0, "src")
import pytest
from acouscope.ai.backends import get_backend


def test_factory_kinds():
    for kind in ("openai", "ollama"):
        b = get_backend(kind, base_url="http://x", model="m", api_key="k")
        assert b.kind == kind
        assert b.supports_vision is True


def test_protocol_conformance():
    b = get_backend("openai", base_url="http://x", model="m", api_key="k")
    assert callable(b.chat_stream)
    assert hasattr(b, "kind") and hasattr(b, "supports_vision")


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        get_backend("nope")


def test_delegate_chat_called(monkeypatch):
    b = get_backend("openai", base_url="http://x", model="m", api_key="k")
    called = {}
    monkeypatch.setattr(b._p, "chat",
                        lambda *a, **k: called.update(k) or "ok")
    out = b.chat_stream([{"role": "user", "content": "hi"}],
                        image_b64="zz", on_chunk=print, is_cancelled=None)
    assert out == "ok" and called.get("image_b64") == "zz"
