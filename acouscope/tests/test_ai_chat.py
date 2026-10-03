# SPDX-License-Identifier: GPL-3.0-only
"""AI 释图模型调用层与追问对话测试（不发真实网络请求）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from acouscope.ai import interpreter
from acouscope.ai.prompts import (
    DEFAULT_QUESTIONS,
    PRESET_QUESTIONS,
    preset_questions_for,
)


class TestSSEParse:
    def test_chunks_collected(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"你好"}}]}',
            'data: {"choices":[{"delta":{"content":"，世界"}}]}',
            "data: [DONE]",
        ]
        got = []
        meta = interpreter.parse_sse_stream(iter(lines), got.append)
        assert "".join(got) == "你好，世界"
        assert not meta["empty"]

    def test_finish_reason_length(self):
        lines = ['data: {"choices":[{"delta":{"content":"x"},"finish_reason":"length"}]}']
        meta = interpreter.parse_sse_stream(iter(lines), lambda p: None)
        assert meta["finish_reason"] == "length"
        assert not meta["empty"]

    def test_error_object_raises(self):
        lines = ['data: {"error":{"message":"model not found"}}']
        with pytest.raises(interpreter.ProviderError):
            interpreter.parse_sse_stream(iter(lines), lambda p: None)

    def test_empty_stream_flagged(self):
        meta = interpreter.parse_sse_stream(iter(["data: [DONE]"]), lambda p: None)
        assert meta["empty"]

    def test_cancel(self):
        lines = ['data: {"choices":[{"delta":{"content":"a"}}]}'] * 5
        got = []
        with pytest.raises(interpreter.CancelledError):
            interpreter.parse_sse_stream(
                iter(lines), got.append, is_cancelled=lambda: True
            )


class TestNDJSONParse:
    def test_ollama_chunks(self):
        lines = [
            '{"message":{"content":"你好"}}',
            '{"message":{"content":"。"},"done":true}',
        ]
        got = []
        meta = interpreter.parse_ndjson_stream(iter(lines), got.append)
        assert "".join(got) == "你好。"
        assert not meta["empty"]

    def test_ollama_error(self):
        with pytest.raises(interpreter.ProviderError):
            interpreter.parse_ndjson_stream(
                iter(['{"error":"model not loaded"}']), lambda p: None
            )


class TestAttachImage:
    def test_image_attached_to_first_user(self):
        msgs = [{"role": "user", "content": "Q"}]
        out = interpreter._attach_image(msgs, "QUJD")
        assert isinstance(out[0]["content"], list)
        assert out[0]["content"][0]["type"] == "text"
        assert out[0]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;base64,"
        )

    def test_no_image_keeps_text(self):
        msgs = [{"role": "user", "content": "Q"}]
        out = interpreter._attach_image(msgs, "")
        assert out[0]["content"] == "Q"

    def test_only_first_user_gets_image(self):
        msgs = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]
        out = interpreter._attach_image(msgs, "QUJD")
        assert isinstance(out[0]["content"], list)
        assert out[2]["content"] == "Q2"


class TestV1Normalize:
    def test_appends_v1_for_lm_studio_style_url(self, monkeypatch):
        p = interpreter.OpenAICompatProvider("http://203.0.113.2:1234", model="m")

        def fake(url, payload=None, headers=None, timeout=30):
            if url.endswith("/v1/models"):
                return {"data": [{"id": "m"}]}
            raise interpreter.ProviderError("服务返回 404")

        monkeypatch.setattr(interpreter, "_http_json", fake)
        p._ensure_base()
        assert p.base_url == "http://203.0.113.2:1234/v1"

    def test_keeps_existing_v1(self, monkeypatch):
        p = interpreter.OpenAICompatProvider("http://host:1234/v1", model="m")

        def fail(*a, **k):
            raise AssertionError("不应再探测")

        monkeypatch.setattr(interpreter, "_http_json", fail)
        p._ensure_base()
        assert p.base_url == "http://host:1234/v1"

    def test_keeps_url_when_both_fail(self, monkeypatch):
        p = interpreter.OpenAICompatProvider("http://host:1", model="m")
        monkeypatch.setattr(
            interpreter, "_http_json",
            lambda *a, **k: (_ for _ in ()).throw(interpreter.ProviderError("x")),
        )
        p._ensure_base()
        assert p.base_url == "http://host:1"

    def test_check_warns_unknown_model(self, monkeypatch):
        p = interpreter.OpenAICompatProvider("http://h:1/v1", model="wrong")
        monkeypatch.setattr(
            interpreter, "_http_json",
            lambda *a, **k: {"data": [{"id": "real-model"}]},
        )
        ok, msg = p.check()
        assert ok
        assert "wrong" in msg and "real-model" in msg

    def test_check_ok_with_model(self, monkeypatch):
        p = interpreter.OpenAICompatProvider("http://h:1/v1", model="real-model")
        monkeypatch.setattr(
            interpreter, "_http_json",
            lambda *a, **k: {"data": [{"id": "real-model"}]},
        )
        ok, msg = p.check()
        assert ok and "就绪" in msg


class TestChatFallback:
    def _provider(self, monkeypatch, stream_impl):
        p = interpreter.OpenAICompatProvider("http://h:1/v1", model="m")
        monkeypatch.setattr(p, "_ensure_base", lambda: None)
        monkeypatch.setattr(interpreter, "_http_stream", stream_impl)
        return p

    def test_vision_error_raises_for_fallback(self, monkeypatch):
        def fake(url, payload, headers, timeout, on_chunk, is_cancelled=None):
            raise interpreter.ProviderError("400: image content not supported")

        p = self._provider(monkeypatch, fake)
        with pytest.raises(interpreter.VisionUnsupportedError):
            p.chat([{"role": "user", "content": "hi"}], image_b64="QUJD")

    def test_empty_with_image_raises_vision(self, monkeypatch):
        def fake(url, payload, headers, timeout, on_chunk, is_cancelled=None):
            return {"finish_reason": "stop", "empty": True}

        p = self._provider(monkeypatch, fake)
        with pytest.raises(interpreter.VisionUnsupportedError):
            p.chat([{"role": "user", "content": "hi"}], image_b64="QUJD")

    def test_empty_without_image_raises_provider(self, monkeypatch):
        def fake(url, payload, headers, timeout, on_chunk, is_cancelled=None):
            return {"finish_reason": "stop", "empty": True}

        p = self._provider(monkeypatch, fake)
        with pytest.raises(interpreter.ProviderError):
            p.chat([{"role": "user", "content": "hi"}])

    def test_truncation_note_appended(self, monkeypatch):
        def fake(url, payload, headers, timeout, on_chunk, is_cancelled=None):
            on_chunk("部分内容")
            return {"finish_reason": "length", "empty": False}

        p = self._provider(monkeypatch, fake)
        text = p.chat([{"role": "user", "content": "hi"}])
        assert "部分内容" in text and "截断" in text

    def test_partial_output_on_disconnect(self, monkeypatch):
        def fake(url, payload, headers, timeout, on_chunk, is_cancelled=None):
            on_chunk("一半内容")
            raise interpreter.ConnectionInterruptedError("连接中断")

        p = self._provider(monkeypatch, fake)
        text = p.chat([{"role": "user", "content": "hi"}])
        assert "一半内容" in text and "中断" in text

    def test_disconnect_without_output_raises(self, monkeypatch):
        def fake(url, payload, headers, timeout, on_chunk, is_cancelled=None):
            raise interpreter.ConnectionInterruptedError("连接中断")

        p = self._provider(monkeypatch, fake)
        with pytest.raises(interpreter.ConnectionInterruptedError):
            p.chat([{"role": "user", "content": "hi"}])

    def test_stream_chunks_forwarded(self, monkeypatch):
        def fake(url, payload, headers, timeout, on_chunk, is_cancelled=None):
            on_chunk("甲")
            on_chunk("乙")
            return {"finish_reason": "stop", "empty": False}

        p = self._provider(monkeypatch, fake)
        got = []
        text = p.chat([{"role": "user", "content": "hi"}], on_chunk=got.append)
        assert got == ["甲", "乙"]
        assert text == "甲乙"


class TestPresetQuestions:
    def test_all_views_covered(self):
        for view in ["波形", "FFT 频谱", "语谱图", "音高轨迹",
                     "共振峰轨迹", "MFCC 热图", "3D 频谱图"]:
            qs = preset_questions_for(view)
            assert len(qs) >= 3, view
            assert all(isinstance(q, str) and q.strip() for q in qs)

    def test_view_specific_questions_differ(self):
        assert preset_questions_for("波形") != preset_questions_for("FFT 频谱")

    def test_unknown_view_gets_default(self):
        assert preset_questions_for("未知视图") == DEFAULT_QUESTIONS

    def test_preset_dict_keys_match_views(self):
        assert len(PRESET_QUESTIONS) == 7


class TestDialogUI:
    @pytest.fixture(scope="class")
    def qapp(self):
        pytest.importorskip("PyQt6")
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def _make(self):
        from acouscope.ui.widgets.ai_interpret import AIInterpretDialog

        return AIInterpretDialog(
            image_getter=lambda: None,
            context_getter=lambda: "【数值上下文】测试",
            view_name_getter=lambda: "FFT 频谱",
        )

    def test_conversation_starts_empty(self, qapp):
        """T-1018 归因（非静默）：原「释图前追问区禁用」（chat_box）随对话式重做
        删除；等价契约改为「起聊为空 + 起始提示可见 + 发送键可用」。"""
        dlg = self._make()
        try:
            assert dlg.msg_bubbles == []
            assert dlg.msg_hint.isHidden() is False
            assert dlg.btn_send.isEnabled()
            assert dlg.attach_bar.isHidden() is True     # 无附件时不占位
        finally:
            dlg.close()

    def test_preset_questions_removed_from_panel(self, qapp):
        """T-1018 归因（非静默）：预置问题按钮区随追问对话区一并移除（改由对话式
        输入框提问）；引擎侧预置问题纯函数与常量未受影响。"""
        dlg = self._make()
        try:
            assert not hasattr(dlg, "preset_grid")
            assert not hasattr(dlg, "chat_box")
            assert preset_questions_for("FFT 频谱") == PRESET_QUESTIONS["FFT 频谱"]
        finally:
            dlg.close()

    def test_image_attachment_drives_send_flag(self, qapp, monkeypatch):
        """T-1018 归因（非静默）：原「发送图像」勾选（send_image 持久键）已删——
        本轮是否发送图像改由输入框附件决定（无附件 False / 有附件 True）。"""
        from PyQt6.QtGui import QImage, QPixmap

        from acouscope.ui.widgets import ai_interpret as ai

        monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
        dlg = self._make()
        try:
            monkeypatch.setattr(dlg, "_make_provider", lambda: object())
            dlg.input_edit.setPlainText("看图")
            dlg._on_run()
            assert dlg._run_send_image is False
            assert dlg._run_image_b64 == ""

            img = QImage(8, 8, QImage.Format.Format_ARGB32)
            img.fill(0xFF00FF00)
            assert dlg._attach_pixmap(QPixmap.fromImage(img)) is True
            dlg.input_edit.setPlainText("再看")
            dlg._on_run()
            assert dlg._run_send_image is True
            assert dlg._run_image_b64
        finally:
            dlg.close()

    def test_failed_pops_pending_question(self, qapp):
        dlg = self._make()
        try:
            dlg._chat_messages = [
                {"role": "user", "content": "首问"},
                {"role": "assistant", "content": "首答"},
                {"role": "user", "content": "追问"},
            ]
            dlg._mode = "ask"
            dlg._on_failed("测试错误")
            assert dlg._chat_messages[-1]["role"] == "assistant"
        finally:
            dlg.close()
