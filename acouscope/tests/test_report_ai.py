# SPDX-License-Identifier: GPL-3.0-only
"""T-1104 报告 AI 解读段测试（M-C′·MC-1 · 全离屏 · AI 调用全假 provider）。

覆盖（令书 §一 M-3 八例）：
① ``build_report_html`` 空 ``ai_text`` 逐字节等价（向后兼容·M-A′ 零破坏）；
② AI 节渲染 + escape + 版序（图后 · ``</body>`` 前）；
③ 消息形状（system+user 两条 · 含取数 · 零第三方名 · 零 URL）；
④⑤⑥ worker 三终态路径（success/failed/cancel·均不崩）；
⑦ 面板 ``btn_ai``→``aiRequested`` + ``set_ai_text()/ai_text()`` +
   ``pages_host`` 页标签计数守 β2 例③⑥口径；
⑧ 配置缺失 → 不建 provider（禁自动外发）。

T-1106 MC-2 新增：⑨ 流式逐段回填 + 跑中置灰 + 重生成前清旧文（真槽 ×
同线程直跑 worker × 假 provider·判据全程采展示位）；⑩ failed / cancelled
终态恢复按钮；⑪ 面板 ``set_ai_busy`` 往返回复；⑫ ``lbl_ai`` 入有界
``QScrollArea``（maximumHeight 有界·长文不撑爆·``pages_host`` 零动）。

T-1107 MC-3 新增：⑬ ensure_runtime=False 零触 ``get_runtime``（远程档防误
启）；⑭ ollama 档懒启动 ``start(timeout=30)`` + 就绪后 provider 工厂重建
（动态端口时序）；⑮ 引擎起不来 → ``failed`` 不崩、无 ``finished_ok``；
⑯ llama_cpp 档 ``llama_models`` 三函数 + ``start(timeout=180)`` 路径；
⑰ 模型未下载 → ``failed``。★ 全 mock ``get_runtime``/``llama_models``，
零真引擎零网络；``_wire_ai`` 同步补 mock（槽现对 ollama 档传懒启动入参）。

★ 判据「零网络」：本文件不触真实端点——provider 全为本文件内脚本化假件；
引擎面 ``get_runtime``/``llama_models`` 一律 monkeypatch 假件，零真引擎。
worker 以直调 ``run()`` 同步收信号（无事件循环依赖·结果确定）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QLabel, QScrollArea

from acouscope.ai import interpreter
from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui import report_export
from acouscope.ui.main_window import MainWindow
from acouscope.ui.report_ai import ReportAiWorker, build_report_ai_messages
from acouscope.ui.report_export import ReportFigure
from acouscope.ui.report_preview import ReportPreviewPanel, render_html_pages

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_data_ink_tokens 口径）
_BANNED = ("Mel" + "odyne", "Rea" + "per", "Sonic " + "Visualis")

_SR = 8000
_T = np.arange(_SR * 2) / _SR
_SIGNAL = 0.5 * np.sin(2 * np.pi * 440 * _T)

_SMALL_HTML = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
    "<body style='background:white;color:black'>"
    "<h1>报告题名</h1><p>一行正文。</p></body></html>"
)


def _small_figure() -> ReportFigure:
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    return ReportFigure(image=image, caption="图 1")


class _FakeProvider:
    """脚本化假 provider：回放片段 / 返回全文 / 抛指定异常 / 按取消收敛。"""

    def __init__(self, pieces=(), reply=None, error=None, cancel_midway=False):
        self.pieces = list(pieces)
        self.reply = reply
        self.error = error
        self.cancel_midway = cancel_midway
        self.seen_messages = None

    def chat(self, messages, image_b64="", on_chunk=None, is_cancelled=None,
             timeout=None):
        self.seen_messages = messages
        if self.error is not None:
            raise self.error
        if self.cancel_midway and is_cancelled is not None and is_cancelled():
            raise interpreter.CancelledError("已停止生成")
        for piece in self.pieces:
            if on_chunk is not None:
                on_chunk(piece)
        return self.reply


def _run_sync(worker):
    """当前线程直调 ``run()``：同步收四信号（无 event loop·结果确定）。"""
    ok: list = []
    bad: list = []
    canc: list = []
    chunks: list = []
    worker.finished_ok.connect(ok.append)
    worker.failed.connect(bad.append)
    worker.cancelled.connect(lambda: canc.append(1))
    worker.chunk.connect(chunks.append)
    worker.run()
    return ok, bad, canc, chunks


class _SyncWorker(ReportAiWorker):
    """``start()`` 于当前线程直跑 ``run()`` 后补发 ``finished``（MC-2 真槽测：
    同线程信号直连·宿主槽的回填/置灰在 click 返回前全部完成·零真实线程）。"""

    def start(self, priority=None):  # noqa: D102
        if getattr(self._provider, "request_cancel", False):
            self.cancel()
        self.run()
        self.finished.emit()


class _StreamingFakeProvider:
    """假 provider：每次 ``on_chunk`` 后采面板现状（文本 + 按钮可用态）。"""

    def __init__(self, pieces=(), panel=None, reply=None, error=None,
                 request_cancel=False):
        self.pieces = list(pieces)
        self.panel = panel
        self.reply = reply
        self.error = error
        self.request_cancel = request_cancel
        self.at_start = None
        self.texts: list[str] = []
        self.enabled_while_streaming: list[bool] = []

    def chat(self, messages, image_b64="", on_chunk=None, is_cancelled=None,
             timeout=None):
        if self.error is not None:
            raise self.error
        if is_cancelled is not None and is_cancelled():
            raise interpreter.CancelledError("已停止生成")
        self.at_start = self.panel.ai_text()
        for piece in self.pieces:
            if on_chunk is not None:
                on_chunk(piece)
            self.texts.append(self.panel.ai_text())
            self.enabled_while_streaming.append(self.panel.btn_ai.isEnabled())
        return self.reply


# ---------------------------------------------------------------------------
# ① 向后兼容：空 ai_text 逐字节等价
# ---------------------------------------------------------------------------


def test_build_report_html_backward_compatible(qapp):
    set_language("zh_CN")
    kwargs = dict(
        title="demo",
        metadata={"Title": "样本"},
        figures=[_small_figure()],
        tech_info={"Filename": "demo.wav"},
        degraded_reason="",
        font_family="Noto Sans CJK SC",
    )
    without = report_export.build_report_html(**kwargs)
    with_empty = report_export.build_report_html(**kwargs, ai_text="")
    with_blank = report_export.build_report_html(**kwargs, ai_text="   \n ")
    assert without == with_empty, "ai_text='' 必须逐字节等价旧版"
    assert without == with_blank, "ai_text 全空白同样应零差异"


# ---------------------------------------------------------------------------
# ② AI 节渲染 + 转义 + 版序
# ---------------------------------------------------------------------------


def test_ai_section_rendered_and_escaped(qapp):
    set_language("zh_CN")
    html = report_export.build_report_html(
        title="demo",
        metadata={"Title": "样本"},
        figures=[_small_figure()],
        ai_text="观测: 基频≈220\n<s>x</s>\n\n尾行",
    )
    assert "<section>\n<h2>AI 解读</h2>" in html
    assert "<p>观测: 基频≈220</p>" in html
    assert "&lt;s&gt;x&lt;/s&gt;" in html, "尖括号未转义（标签注入风险）"
    assert "<p>尾行</p>" in html
    assert html.index("<p>观测") > html.index("data:image/png"), "AI 节应在插图之后"
    assert html.rindex("</section>") < html.index("</body>"), "AI 节应在 </body> 前"


# ---------------------------------------------------------------------------
# ③ 消息形状
# ---------------------------------------------------------------------------


def test_build_ai_messages_shape(qapp):
    msgs = build_report_ai_messages(
        metadata={"Title": "鸟鸣样本", "GenreContext": "", "_standard": "ctrl"},
        tech_info={"SamplingRate": "44100 Hz"},
        figure_captions=["图 1 | 波形", ""],
    )
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert all(m.get("content") for m in msgs)
    joined = msgs[0]["content"] + "\n" + msgs[1]["content"]
    assert "鸟鸣样本" in joined
    assert "44100 Hz" in joined
    assert "图 1 | 波形" in joined
    assert "ctrl" not in joined, "控制键（_ 前缀）不应进消息"
    assert "请就上述声学分析结果给出简明技术解读" in joined
    low = joined.lower()
    assert "://" not in low and "www." not in low, "消息含 URL（外发风险）"
    for word in _BANNED:
        assert word.lower() not in low, f"消息命中禁词 {word!r}"


# ---------------------------------------------------------------------------
# ④⑤⑥ worker 三终态路径（假 provider·零网络）
# ---------------------------------------------------------------------------


def test_worker_emits_finished_ok(qapp):
    provider = _FakeProvider(pieces=["第一段", "第二段"])  # chat 返回 None
    ok, bad, canc, chunks = _run_sync(
        ReportAiWorker(provider, [{"role": "user", "content": "x"}])
    )
    assert ok == ["第一段第二段"], "finished_ok 应收到 on_chunk 拼接全文"
    assert chunks == ["第一段", "第二段"]
    assert bad == [] and canc == []
    assert provider.seen_messages == [{"role": "user", "content": "x"}]


def test_worker_failed_on_provider_error(qapp):
    provider = _FakeProvider(error=interpreter.ProviderError("服务不可达"))
    ok, bad, canc, chunks = _run_sync(
        ReportAiWorker(provider, [{"role": "user", "content": "x"}])
    )
    assert ok == [] and canc == [], "失败路径不得发成功/取消终态"
    assert len(bad) == 1 and "服务不可达" in bad[0], "failed 应带可读摘要"


def test_worker_cancel(qapp):
    worker = ReportAiWorker(
        _FakeProvider(cancel_midway=True), [{"role": "user", "content": "x"}]
    )
    worker.cancel()
    ok, bad, canc, chunks = _run_sync(worker)
    assert canc == [1], "取消应发 cancelled 终态"
    assert ok == [] and bad == [], "取消路径不得发成功/失败终态"


# ---------------------------------------------------------------------------
# ⑦ 面板信号 + setter/getter + 页计数守卫
# ---------------------------------------------------------------------------


def test_panel_ai_signal_and_text(qapp):
    set_language("zh_CN")
    panel = ReportPreviewPanel()
    fired: list = []
    panel.aiRequested.connect(lambda: fired.append(1))
    panel.btn_ai.click()
    assert fired == [1], "btn_ai 应发 aiRequested"

    assert panel.ai_text() == ""
    assert panel.lbl_ai.text() == tr("report.ai_placeholder")
    panel.set_ai_text("T")
    assert panel.ai_text() == "T"
    assert panel.lbl_ai.text() == "T"
    panel.set_ai_text("")
    assert panel.ai_text() == ""
    assert panel.lbl_ai.text() == tr("report.ai_placeholder")

    # β2 例③⑥口径：顶栏新钮/展示位不得混入 pages_host 页标签计数
    panel.set_html_provider(lambda: _SMALL_HTML)
    panel.refresh()
    labels = panel.pages_host.findChildren(QLabel)
    assert len(labels) == len(render_html_pages(_SMALL_HTML, **panel.options()))
    assert panel.lbl_ai not in labels


# ---------------------------------------------------------------------------
# ⑧ 配置缺失 → 零外发（禁自动外发红线）
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带合成音频的 MainWindow（离屏构建·不 show·teardown close·同 β2 夹具口径）。"""
    set_language("zh_CN")
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    controller.load_from_array(_SIGNAL.copy(), _SR)
    w = MainWindow(controller)
    w.waveform_widget.set_data(_T, _SIGNAL.copy(), sample_rate=_SR)
    yield w
    w.close()


def test_no_provider_config_no_send(window, monkeypatch):
    calls: list = []

    def spy_make_provider(*args, **kwargs):
        calls.append(args)
        raise AssertionError("配置缺失时不得构造 provider")

    monkeypatch.setattr(
        "acouscope.ui.widgets.ai_interpret.load_ai_config", lambda: {}
    )
    monkeypatch.setattr(interpreter, "make_provider", spy_make_provider)

    window.report_preview_panel.btn_ai.click()  # → aiRequested → 真槽
    assert calls == [], "无配置即止（禁自动外发）"
    assert window._report_ai_worker is None


# ---------------------------------------------------------------------------
# T-1107 MC-3：假 runtime / 假模型目录（零真引擎·零网络）
# ---------------------------------------------------------------------------


class _ScriptRuntime:
    """假 runtime：记录 ``start`` 调用序列，可按脚本成败切换 state。"""

    def __init__(self, state="stopped", start_result=True,
                 base_url="http://127.0.0.1:54321"):
        self.state = state
        self._start_result = start_result
        self.base_url = base_url
        self.start_calls: list = []

    def start(self, *args, **kwargs):
        self.start_calls.append((args, kwargs))
        if self._start_result:
            self.state = "ready"
        return self._start_result


_READY_RUNTIME = _ScriptRuntime(state="ready")


def _ready_runtime_factory():
    return _READY_RUNTIME


def _no_engine(name):
    def _boom(*args, **kwargs):
        raise AssertionError(f"{name} 被调用：本例禁真启/禁触碰引擎")
    return _boom


# ---------------------------------------------------------------------------
# ⑨ MC-2：流式逐段回填 + 重生成前清旧文 + 跑中置灰（真槽·同线程直跑）
# ---------------------------------------------------------------------------


def _wire_ai(window, monkeypatch, provider):
    """把 AI 路四件套换成假件：有配置 / 假 provider / 同线程直跑 worker /
    就绪态假 runtime（T-1107 后槽对 ollama 档传懒启动入参·须 mock 防真启）。"""
    monkeypatch.setattr(
        "acouscope.ui.widgets.ai_interpret.load_ai_config",
        lambda: {"provider": "ollama"},
    )
    monkeypatch.setattr(interpreter, "make_provider", lambda *a, **k: provider)
    monkeypatch.setattr("acouscope.ui.report_ai.ReportAiWorker", _SyncWorker)
    monkeypatch.setattr(
        "acouscope.ai.ollama_runtime.get_runtime", _ready_runtime_factory
    )


def test_streaming_backfill_and_regen_clear(window, monkeypatch):
    set_language("zh_CN")
    panel = window.report_preview_panel
    panel.set_ai_text("上一轮旧文——重生成前必须清掉")
    provider = _StreamingFakeProvider(["第一段", "第二段", "第三段"], panel)
    _wire_ai(window, monkeypatch, provider)

    panel.btn_ai.click()  # → 真槽：清旧文 + 占位 + 逐段回填 + 终态全文

    assert provider.at_start == tr("report.ai_generating"), \
        "起 worker 前应先清旧文并回填「生成中」占位"
    assert provider.texts == ["第一段", "第一段第二段", "第一段第二段第三段"], \
        "展示位应随 chunk 逐段递增（流式回填·非等全文才显示）"
    assert provider.enabled_while_streaming == [False, False, False], \
        "跑中 btn_ai 必须置灰防重点"
    assert panel.ai_text() == "第一段第二段第三段"
    assert panel.lbl_ai.text() == "第一段第二段第三段"
    assert panel.btn_ai.isEnabled() is True, "finished 终态必须恢复按钮"
    assert window._report_ai_worker is None


# ---------------------------------------------------------------------------
# ⑩ MC-2：failed / cancelled 终态恢复按钮（防永久灰）
# ---------------------------------------------------------------------------


def test_failed_terminal_restores_button(window, monkeypatch):
    set_language("zh_CN")
    panel = window.report_preview_panel
    provider = _StreamingFakeProvider(
        ["残段"], panel, error=interpreter.ProviderError("服务不可达")
    )
    _wire_ai(window, monkeypatch, provider)

    panel.btn_ai.click()

    assert panel.btn_ai.isEnabled() is True, "failed 终态必须恢复按钮"
    assert panel.ai_text() == "", "failed 应清展示位"
    assert panel.lbl_ai.text() == tr("report.ai_placeholder")
    assert window._report_ai_worker is None


def test_cancelled_terminal_restores_button(window, monkeypatch):
    set_language("zh_CN")
    panel = window.report_preview_panel
    provider = _StreamingFakeProvider(["不会送达"], panel, request_cancel=True)
    _wire_ai(window, monkeypatch, provider)

    panel.btn_ai.click()

    assert panel.btn_ai.isEnabled() is True, "cancelled 终态必须恢复按钮"
    assert provider.texts == [], "取消生效后不得有 chunk 送达展示位"
    assert window._report_ai_worker is None


# ---------------------------------------------------------------------------
# ⑪⑫ MC-2：面板 set_ai_busy 往返 + 展示位有界滚动区
# ---------------------------------------------------------------------------


def test_set_ai_busy_toggles_btn_ai(qapp):
    set_language("zh_CN")
    panel = ReportPreviewPanel()
    assert panel.btn_ai.isEnabled()
    panel.set_ai_busy(True)
    assert not panel.btn_ai.isEnabled()
    panel.set_ai_busy(False)
    assert panel.btn_ai.isEnabled()


def test_ai_display_in_bounded_scroll_area(qapp):
    set_language("zh_CN")
    panel = ReportPreviewPanel()
    scroll = panel.ai_scroll
    assert isinstance(scroll, QScrollArea)
    assert scroll.widget() is panel.lbl_ai
    assert scroll.horizontalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    # lbl_ai 在滚动区内、不在 pages_host（守 β2 例③⑥页标签计数口径）
    assert panel.lbl_ai not in panel.pages_host.findChildren(QLabel)
    bound = scroll.maximumHeight()
    assert 0 < bound < 16777215, "展示容器高度必须有界"
    panel.set_ai_text("长文解读。" * 400)
    assert scroll.maximumHeight() == bound, "长文不得撑爆展示位上界"
    assert panel.pages_host.findChildren(QLabel) == [], "页渲染路径零动"


# ---------------------------------------------------------------------------
# ⑬ MC-3：ensure_runtime=False（远程/custom 档）→ 零触 get_runtime·直连 chat
# ---------------------------------------------------------------------------


def test_lazy_start_skipped_when_not_requested(qapp, monkeypatch):
    monkeypatch.setattr(
        "acouscope.ai.ollama_runtime.get_runtime", _no_engine("ollama.get_runtime")
    )
    monkeypatch.setattr(
        "acouscope.ai.llama_runtime.get_runtime", _no_engine("llama.get_runtime")
    )
    provider = _FakeProvider(reply="远程档直连结果")
    ok, bad, canc, chunks = _run_sync(
        ReportAiWorker(
            provider, [{"role": "user", "content": "x"}], ensure_runtime=False
        )
    )
    assert ok == ["远程档直连结果"], "MC-1 行为零回退"
    assert bad == [] and canc == []
    assert provider.seen_messages == [{"role": "user", "content": "x"}]


# ---------------------------------------------------------------------------
# ⑭ MC-3：ollama 档懒启动 start(timeout=30) + 就绪后 provider 工厂重建
# ---------------------------------------------------------------------------


def test_lazy_start_ollama_then_rebuild_provider(qapp, monkeypatch):
    rt = _ScriptRuntime(state="stopped")
    monkeypatch.setattr("acouscope.ai.ollama_runtime.get_runtime", lambda: rt)
    events: list = []
    stale = _FakeProvider(reply="旧 provider 不得再被使用")
    fresh = _FakeProvider(reply="动态端口结果")
    seen_at_rebuild: list = []

    def factory():
        events.append("rebuild")
        seen_at_rebuild.append((rt.state, rt.base_url))
        return fresh

    w = ReportAiWorker(
        stale, [{"role": "user", "content": "x"}],
        ensure_runtime=True, runtime_kind="ollama", provider_factory=factory,
    )
    orig_start = rt.start

    def counted_start(*a, **k):
        events.append("start")
        return orig_start(*a, **k)

    rt.start = counted_start
    ok, bad, canc, chunks = _run_sync(w)
    assert events == ["start", "rebuild"], "先起引擎、就绪后重建 provider 再 chat"
    assert rt.start_calls == [((), {"timeout": 30.0})], "ollama 档超时 30s"
    assert seen_at_rebuild == [("ready", "http://127.0.0.1:54321")], \
        "重建时必须看到就绪态与动态 base_url（T-1021 时序）"
    assert ok == ["动态端口结果"] and bad == [] and canc == []
    assert stale.seen_messages is None, "chat 必须走重建后的 provider"


# ---------------------------------------------------------------------------
# ⑮ MC-3：引擎 start() 返 False → failed 不崩、无 finished_ok、不进 chat
# ---------------------------------------------------------------------------


def test_lazy_start_engine_fail_emits_failed(qapp, monkeypatch):
    rt = _ScriptRuntime(state="stopped", start_result=False)
    monkeypatch.setattr("acouscope.ai.ollama_runtime.get_runtime", lambda: rt)
    provider = _FakeProvider(reply="不应送达")
    ok, bad, canc, chunks = _run_sync(
        ReportAiWorker(
            provider, [{"role": "user", "content": "x"}],
            ensure_runtime=True, runtime_kind="ollama",
        )
    )
    assert ok == [] and canc == [], "引擎失败不得伪装成功终态"
    assert len(bad) == 1 and "启动失败" in bad[0], "failed 应带可读提示"
    assert provider.seen_messages is None, "引擎未就绪不得发起 chat"


# ---------------------------------------------------------------------------
# ⑯ MC-3：llama_cpp 档 → llama_models 三函数 + start(timeout=180) 路径
# ---------------------------------------------------------------------------


def test_lazy_start_llama_cpp_path(qapp, monkeypatch):
    from types import SimpleNamespace
    from acouscope.ai import llama_models

    models = (SimpleNamespace(model_id="small"), SimpleNamespace(model_id="mid"))
    ready_seen: list = []
    monkeypatch.setattr(llama_models, "list_models", lambda: models)
    monkeypatch.setattr(
        llama_models, "is_model_ready",
        lambda mid: ready_seen.append(mid) or True,
    )
    monkeypatch.setattr(
        llama_models, "model_path", lambda mid: Path(f"/fake/{mid}.gguf")
    )
    rt = _ScriptRuntime(state="stopped")
    monkeypatch.setattr("acouscope.ai.llama_runtime.get_runtime", lambda: rt)
    rebuilt: list = []

    def factory():
        rebuilt.append(rt.base_url)
        return _FakeProvider(reply="llama 结果")

    ok, bad, canc, chunks = _run_sync(
        ReportAiWorker(
            _FakeProvider(reply="旧"), [{"role": "user", "content": "x"}],
            ensure_runtime=True, runtime_kind="llama_cpp",
            llama_model_id="mid", provider_factory=factory,
        )
    )
    assert ready_seen == ["mid"], "按 llama_model_id 选中，而非回退 [0]"
    assert rt.start_calls == [((Path("/fake/mid.gguf"),), {"timeout": 180.0})], \
        "llama_cpp 档传模型路径 + 超时 180s"
    assert rebuilt == ["http://127.0.0.1:54321"]
    assert ok == ["llama 结果"] and bad == [] and canc == []


# ---------------------------------------------------------------------------
# ⑰ MC-3：llama_cpp 档模型未下载 → failed（未下载提示）·不起引擎不 chat
# ---------------------------------------------------------------------------


def test_lazy_start_llama_model_not_downloaded(qapp, monkeypatch):
    from types import SimpleNamespace
    from acouscope.ai import llama_models

    monkeypatch.setattr(
        llama_models, "list_models",
        lambda: (SimpleNamespace(model_id="small"),),
    )
    monkeypatch.setattr(llama_models, "is_model_ready", lambda mid: False)
    monkeypatch.setattr(
        llama_models, "model_path",
        lambda mid: (_ for _ in ()).throw(AssertionError("未就绪不得取路径")),
    )
    rt = _ScriptRuntime(state="stopped")
    monkeypatch.setattr("acouscope.ai.llama_runtime.get_runtime", lambda: rt)
    provider = _FakeProvider(reply="不应送达")
    ok, bad, canc, chunks = _run_sync(
        ReportAiWorker(
            provider, [{"role": "user", "content": "x"}],
            ensure_runtime=True, runtime_kind="llama_cpp",
            llama_model_id="small",
        )
    )
    assert ok == [] and canc == []
    assert len(bad) == 1 and "尚未下载" in bad[0], "未下载应有明确提示"
    assert rt.start_calls == [], "模型未就绪不得起引擎"
    assert provider.seen_messages is None
