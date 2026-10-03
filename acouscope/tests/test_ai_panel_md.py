# SPDX-License-Identifier: GPL-3.0-only
"""T-1055 守卫：AI 释图气泡 Markdown 渲染（零依赖）+ 对话窗口通用基本功能。

覆盖（需求说明 §交付内容 3 的 7 类断言）：
  ① MD 渲染生效：setMarkdown 被使用 / 表格渲染出 <table>
  ② 流式节流：连续小 chunk 不触发逐 token 重渲染（计数 spy）
  ③ 语法降级：`$x$` 等 Qt 不支持语法原样保留、不抛异常
  ④ 复制写入剪贴板：内容 = MD 原文（非 HTML）
  ⑤ 清空/新会话生效（二次点击确认）
  ⑥ 滚动跟随判据：接近底部才跟随，上滑解除
  ⑦ 既有 ai_panel.* i18n 键未破 + 新增键三语非空

构造口径与 tests/test_ai_chat.py 一致：直接实例化 AIInterpretDialog（不
show），打桩 worker 启动与 provider，避免真实网络/模型/运行时。
"""

import pytest

from acouscope.i18n import _STRINGS

# T-1055 新增键（三语齐，report 用）
_NEW_KEYS = (
    "ai_panel.copy", "ai_panel.copy_tip",
    "ai_panel.regenerate", "ai_panel.regenerate_tip",
    "ai_panel.regenerate_none",
    "ai_panel.clear", "ai_panel.clear_tip",
    "ai_panel.clear_confirm", "ai_panel.cleared",
)
_EXISTING_KEYS = (
    "ai_panel.send", "ai_panel.stop", "ai_panel.sending",
    "ai_panel.role_assistant", "ai_panel.input_hint",
    "ai_panel.attach_full", "ai_panel.switch_remote",
)


class TestAiPanelMd:
    @pytest.fixture(scope="class")
    def qapp(self):
        pytest.importorskip("PyQt6")
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def _make(self, monkeypatch):
        from acouscope.ui.widgets import ai_interpret as ai
        from acouscope.ui.widgets.ai_interpret import AIInterpretDialog

        # 打桩 worker 启动与 provider，杜绝真实网络/引擎运行时
        monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
        dlg = AIInterpretDialog(
            image_getter=lambda: None,
            context_getter=lambda: "【数值上下文】测试",
            view_name_getter=lambda: "FFT 频谱",
        )
        monkeypatch.setattr(dlg, "_make_provider", lambda: object())
        return dlg

    def _send(self, dlg, text: str) -> None:
        dlg.input_edit.setPlainText(text)
        dlg._on_run()

    # ① MD 渲染生效：表格渲染出 <table>，setMarkdown 走 Qt 内建通道
    def test_md_table_rendered(self, qapp, monkeypatch):
        from acouscope.ui.widgets.ai_interpret import _MessageBubble

        dlg = self._make(monkeypatch)
        try:
            self._send(dlg, "看图")
            bubble = dlg._stream_bubble
            assert isinstance(bubble, _MessageBubble)
            assert bubble._md_mode is True
            md = "# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**粗体** `code`"
            dlg._on_done(md)
            html = bubble.text_view.toHtml()
            assert "<table" in html, "Markdown 表格未渲染出 <table>"
            assert "font-weight" in html, "Markdown 粗体未渲染"
        finally:
            dlg.close()

    # ② 流式节流：小 chunk 累积，未达阈值不逐 token 重渲染
    def test_stream_throttle(self, qapp, monkeypatch):
        dlg = self._make(monkeypatch)
        try:
            self._send(dlg, "看图")
            bubble = dlg._stream_bubble
            renders = {"n": 0}
            orig = bubble._apply_markdown

            def spy():
                renders["n"] += 1
                return orig()

            monkeypatch.setattr(bubble, "_apply_markdown", spy)
            chunk = "这是一段普通文本用于流式累积。"  # 约 16 字符 < 160 阈值
            for _ in range(10):
                dlg._on_chunk(chunk)
            assert renders["n"] < 10, (
                f"节流失效：10 个 chunk 触发 {renders['n']} 次重渲染")
            assert bubble._md_buffer, "缓冲应累积全文"
            dlg._on_done(bubble._md_buffer + "\n\n**结尾**")
            assert renders["n"] > 0, "流结束应补一次完整渲染"
        finally:
            dlg.close()

    # ③ 语法降级：$x$ 原样保留、不抛异常
    def test_latex_kept_no_exc(self, qapp, monkeypatch):
        dlg = self._make(monkeypatch)
        try:
            self._send(dlg, "看图")
            bubble = dlg._stream_bubble
            md = "公式 $x^2 + y^2$ 原样保留\n\n行内 \\[E=mc^2\\]"
            dlg._on_done(md)  # 不抛即通过
            plain = bubble.text_view.toPlainText()
            assert "$x^2 + y^2$" in plain, "LaTeX 内容丢失"
            assert "E=mc^2" in plain, "降级后内容不应丢失"
        finally:
            dlg.close()

    # ④ 复制写入剪贴板：内容 = MD 原文（非 HTML）
    def test_copy_writes_md_source(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QApplication

        dlg = self._make(monkeypatch)
        try:
            self._send(dlg, "看图")
            bubble = dlg._stream_bubble
            md = "# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |"
            dlg._on_done(md)
            assert bubble.btn_copy is not None
            QApplication.clipboard().clear()
            bubble.btn_copy.click()
            copied = QApplication.clipboard().text()
            assert copied == md, f"复制内容非 MD 原文：{copied!r}"
            assert "<table" not in copied, "复制不得带 HTML"
        finally:
            dlg.close()

    # ⑤ 清空/新会话：二次点击确认后生效
    def test_clear_second_click(self, qapp, monkeypatch):
        dlg = self._make(monkeypatch)
        try:
            self._send(dlg, "看图")
            dlg._on_done("答复")
            assert dlg.msg_bubbles and dlg._chat_messages
            dlg._on_clear()      # 首次：仅进入待确认
            assert dlg.msg_bubbles, "首次点击不应立即清空"
            dlg._on_clear()      # 二次：确认清空
            assert dlg.msg_bubbles == [], "二次点击应清空气泡"
            assert dlg._chat_messages == []
            assert dlg._stream_bubble is None
            assert dlg.msg_hint.isVisible(), "清空后起始提示应可见"
            assert dlg._last_question == ""
        finally:
            dlg.close()

    # ⑥ 滚动跟随判据：接近底部才跟随，上滑解除
    def test_scroll_follow_near_bottom(self, qapp, monkeypatch):
        dlg = self._make(monkeypatch)
        try:
            bar = dlg.msg_scroll.verticalScrollBar()
            bar.setRange(0, 1000)
            # 远离底部（上滑）→ 解除跟随
            bar.setValue(500)
            dlg._on_scroll_value_changed(500)
            assert dlg._follow_bottom is False, "上滑应解除强制贴底"
            # 接近底部（≤ _SCROLL_FOLLOW_EPS）→ 恢复跟随
            bar.setValue(995)
            dlg._on_scroll_value_changed(995)
            assert dlg._follow_bottom is True, "接近底部应恢复跟随"
        finally:
            dlg.close()

    # ⑦ i18n：既有键未破 + 新增键三语非空
    def test_i18n_keys_intact(self):
        ai_keys = [k for k in _STRINGS if k.startswith("ai_panel.")]
        assert len(ai_keys) >= 75, f"ai_panel.* 键数异常：{len(ai_keys)}"
        for key in _EXISTING_KEYS:
            assert key in _STRINGS, f"既有键丢失：{key}"
        for key in _NEW_KEYS:
            assert key in _STRINGS, f"新增键缺失：{key}"
            for lang in ("en_US", "zh_CN", "zh_TW"):
                val = _STRINGS[key].get(lang, "")
                assert val and val.strip(), f"{key}[{lang}] 为空"
