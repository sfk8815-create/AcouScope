# SPDX-License-Identifier: GPL-3.0-only
"""T-306: 视觉路由 / Prompt 路由 / 上下文预算（mock，禁网络）。

T-1018 归因（非静默，逐条见各用例 docstring）：AI 释图窗改「对话式」后，面板内
设置控件（三档下拉 / 厂商 / 地址 / 模型名 / 密钥 / 发送图像开关）与独立追问区、
预置问题区整体删除；涉及这些控件的用例改写为**同一契约的只读/合流口径**——
配置经 ai_config.json + reload_config 驱动，追问与释图合流为输入框发送（_on_run）。
视觉路由（AT-408）、Prompt 路由（AT-405/409）、上下文预算（AT-405）断言本身不变。
"""
import sys
sys.path.insert(0, "src")
import pytest
pytest.importorskip("PyQt6")
from acouscope.ui.widgets import ai_interpret as ai


def test_prompt_domain_neutral():
    # AT-405: 领域中立——禁单一学科限定；数值上下文为第一依据
    p = ai.SYSTEM_PROMPT_FINAL
    assert "音乐学" in p and "声学" in p and "音频工程" in p
    assert "民族音乐学田野调查助手" not in p
    assert "数值上下文" in p and "推测" in p


def test_text_only_blocks_image():
    assert ai._effective_send_image(send_image=True, text_only=True) is False
    assert ai._effective_send_image(send_image=False, text_only=True) is False
    assert ai._effective_send_image(send_image=True, text_only=False) is True


def test_context_budget():
    hist = [{"role": "user", "content": "x" * 2000}] * 10
    trimmed = ai.trim_history(hist, max_rounds=6, max_chars=6000)
    assert len(trimmed) <= 6 * 2


def test_official_prompt_injection(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai, "build_context", lambda *a, **k: "CTX")
    msgs = ai.build_messages(system=ai.SYSTEM_PROMPT_FINAL, user_question="分析",
                             context="CTX", history=[], mode="official")
    captured["msgs"] = msgs
    assert msgs[0]["role"] == "system"
    assert "CTX" in msgs[1]["content"]  # 数值上下文强制前缀（AT-405）


# ----------------------------------------------------------------------
# 视觉路由（AT-408）
# ----------------------------------------------------------------------

def test_model_text_only_registry():
    """注册表驱动：已知纯文本模型 → True；未知/视觉模型 → False（保守不预锁）。"""
    assert ai._model_text_only("spark-x2.5-1.7b") is True
    assert ai._model_text_only("qwen2.5:3b") is True
    assert ai._model_text_only("moondream") is False
    assert ai._model_text_only("Qwen2.5-VL-72B-Instruct") is False
    assert ai._model_text_only("") is False


def test_worker_forces_no_image_for_text_only(monkeypatch):
    """视觉门禁（T-1022 口径）：纯文本模型 + 带图 → 明确失败并提示更换，不再静默降级。

    T-1022 归因（非静默）：原断言（provider 仍被调用、只是收到空图）正是「静默
    降级」本身——用户带图却只发了文本且无从察觉。现改为**门禁**：已知非视觉
    模型带图时直接 failed（零终端提示），provider **不被调用**；不带图时纯文本
    问答照常。`_effective_send_image` 纯函数语义（兜底不发送图像）保留。
    """
    calls = []

    class _MockProvider:
        def chat(self, messages, image_b64="", on_chunk=None,
                 is_cancelled=None):
            calls.append(image_b64)
            return "ok"

    w = ai._InterpretWorker(_MockProvider(),
                            [{"role": "user", "content": "q"}],
                            image_b64="QUJD", send_image=True, text_only=True)
    assert w.send_image is False          # 兜底语义不变
    results, failures = [], []
    w.finished_ok.connect(results.append)
    w.failed.connect(failures.append)
    w.run()  # 同步直跑（mock provider，无网络）
    assert results == [] and calls == []   # 门禁：带图不调用 provider
    assert failures and failures[0] == ai.tr("ai_panel.vision_blocked")

    # 不带图 → 纯文本问答照常（门禁只拦「带图 + 已知非视觉」）
    w_plain = ai._InterpretWorker(_MockProvider(),
                                  [{"role": "user", "content": "q"}],
                                  image_b64="", send_image=False,
                                  text_only=True)
    ok2 = []
    w_plain.finished_ok.connect(ok2.append)
    w_plain.run()
    assert ok2 == ["ok"] and calls == [""]

    w2 = ai._InterpretWorker(_MockProvider(),
                             [{"role": "user", "content": "q"}],
                             image_b64="QUJD", send_image=True, text_only=False)
    assert w2.send_image is True


class _FakeWorker:
    """替身 worker：记录构造参数，不启动线程、不触网。"""

    def __init__(self, provider, messages, image_b64="",
                 send_image=True, text_only=False):
        self.provider = provider
        self.messages = messages
        self.image_b64 = image_b64
        self.send_image = send_image
        self.text_only = text_only
        self._cancelled = False

    def cancel(self):
        self._cancelled = True


@pytest.fixture(scope="module")
def dlg(qapp, request):
    """真实对话框（不写真实配置：_config_paths 打桩为空）。"""
    mp = pytest.MonkeyPatch()
    mp.setattr(ai, "_config_paths", lambda: [])
    d = ai.AIInterpretDialog(
        image_getter=lambda: b"fake-png",
        context_getter=lambda: "【数值上下文】测试上下文",
        view_name_getter=lambda: "FFT 频谱",
    )
    yield d
    mp.undo()
    d.deleteLater()


def _stop_mock(qapp):
    """测试后停止残留 worker 线程（mock provider 不触网，仅资源清理）。"""
    for obj in qapp.allWidgets():
        w = getattr(obj, "_worker", None)
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(2000)
    qapp.processEvents()


def test_text_only_model_no_image_delivery(dlg, monkeypatch, tmp_path):
    """纯文本模型 → worker 按 send_image=False 执行；视觉模型 → 图片按附带走。

    T-1018 归因（非静默）：面板内「发送图像」开关已删除（图像发送随附件走、设置归
    设置-AI），AT-408 视觉路由改验**只读口径**——模型名由 ai_config 决定，双保险
    仍在 _make_worker 单点生效（原 test_dialog_text_only_switch 的被测控件消失）。
    """
    import json as _json
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
    cfg = tmp_path / "ai_config.json"

    def _switch(model):
        cfg.write_text(_json.dumps({
            "provider": "custom", "url": "http://127.0.0.1:11434",
            "model": model, "key": "",
            "ai_v2": {"source": "self_hosted", "mode": "official"},
        }), encoding="utf-8")
        monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
        dlg.reload_config()
        dlg._v2_state = dlg._ai_v2()
        dlg._run_image_b64 = "QUJD"
        dlg._run_send_image = True
        return ai.AIInterpretDialog._make_worker(
            dlg, None, [], "q", "【数值上下文】c")

    w = _switch("spark-x2.5-1.7b")
    assert w.text_only is True
    assert w.send_image is False       # 双保险：纯文本模型不发送图像

    w2 = _switch("qwen2.5-vl-72b-instruct")
    assert w2.text_only is False
    assert w2.send_image is True       # 视觉模型按附带的图片发送
    dlg._run_send_image = False
    dlg._run_image_b64 = ""


def test_legacy_free_remote_migrates_to_cloud(dlg, monkeypatch, tmp_path):
    """旧 provider=free_remote → 云端档 custom 兜底（地址/模型原样保留）。

    T-1018 归因（非静默）：原断言依赖已删除的「发送图像」开关，改验只读迁移结果
    （档位/厂商/模型名），迁移判定 _source_from_config 契约不变。
    """
    cfg = tmp_path / "ai_config.json"
    import json as _json
    cfg.write_text(_json.dumps({
        "provider": "free_remote",
        "url": ai.interpreter.FREE_REMOTE_BASE,
        "model": ai.interpreter.FREE_REMOTE_MODEL,
        "key": "", "send_image": True,
        "ai_v2": {"mode": "official"},
    }), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    dlg.reload_config()
    assert dlg._source == "cloud"
    assert dlg._vendor == "custom"
    assert dlg._eng_model == ai.interpreter.FREE_REMOTE_MODEL


def test_dialog_official_run_routing(dlg, monkeypatch, tmp_path):
    """official 释图：system=SYSTEM_PROMPT_FINAL + 首条 user 前缀数值上下文。

    T-1018 归因（非静默）：模型名改由 ai_config 只读解析（原面板内模型名输入
    已删除），路由断言本身不变。
    """
    import json as _json
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
    sent = {}

    class _MockProvider:
        def check(self):
            return True, "ok"

    cfg = tmp_path / "ai_config.json"
    cfg.write_text(_json.dumps({
        "provider": "custom", "url": "http://127.0.0.1:11434",
        "model": "spark-x2.5-1.7b", "key": "",
        "ai_v2": {"source": "self_hosted", "mode": "official"},
    }), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    dlg.reload_config()
    monkeypatch.setattr(dlg, "_make_provider", lambda: _MockProvider())
    monkeypatch.setattr(dlg, "image_getter", lambda: b"fake-png")

    dlg._ai_mode = "official"
    dlg._official_model = "spark-x2.5-1.7b"
    dlg._byom_model = ""
    dlg._byom_prompt = ""
    dlg._v2_state = dlg._ai_v2()

    worker = ai.AIInterpretDialog._make_worker(
        dlg, _MockProvider(),
        [{"role": "user",
          "content": "【数值上下文】测试上下文\n\n释图指令"}],
        "释图指令", "【数值上下文】测试上下文")
    sent["worker"] = worker
    assert worker.messages[0] == {"role": "system",
                                  "content": ai.SYSTEM_PROMPT_FINAL}
    assert worker.messages[1]["role"] == "user"
    assert worker.messages[1]["content"].startswith("【数值上下文")
    assert worker.text_only is True
    assert worker.send_image is False  # 双保险生效


def test_dialog_byom_run_routing(dlg, monkeypatch):
    """byom 释图：system=用户 prompt + 数值上下文强制追加在末尾（AT-409）。

    T-1018 归因（非静默）：byom 模型名取自 ai_v2（面板内模型名输入已删除）。
    """
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)

    class _MockProvider:
        def check(self):
            return True, "ok"

    dlg._ai_mode = "byom"
    dlg._official_model = ""
    dlg._byom_model = "my-vl-model"
    dlg._byom_prompt = "我的自定义规范"
    dlg._v2_state = dlg._ai_v2()

    worker = ai.AIInterpretDialog._make_worker(
        dlg, _MockProvider(),
        [{"role": "user", "content": "释图指令\n\n【数值上下文】测试上下文"}],
        "释图指令", "【数值上下文】测试上下文")
    assert worker.messages[0] == {"role": "system", "content": "我的自定义规范"}
    assert worker.messages[1]["content"].endswith("【数值上下文】测试上下文")
    assert worker.text_only is False  # 自定义模型不在注册表 → 保守不预锁


def test_dialog_byom_empty_prompt_no_system(dlg, qapp, monkeypatch):
    """byom 且未填自定义 prompt → 不设 system 消息，上下文仍强制附带。"""
    _stop_mock(qapp)
    dlg._ai_mode = "byom"
    dlg._byom_model = ""
    dlg._byom_prompt = ""
    dlg._v2_state = dlg._ai_v2()

    worker = ai.AIInterpretDialog._make_worker(
        dlg, None, [], "q", "【数值上下文】ctx")
    assert worker.messages[0]["role"] == "user"
    assert worker.messages[0]["content"].endswith("【数值上下文】ctx")


def test_followup_budget_and_reinject(dlg, qapp, monkeypatch):
    """追问：历史预算 6 轮/6000 字符；截断丢上下文时自动重注入。

    T-1018 归因（非静默）：追问入口与释图入口合流为底部输入框发送（原独立追问
    区 _ask / 预置问题按钮已删除），预算与重注入契约不变，改由 _on_run 驱动。
    """
    _stop_mock(qapp)
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
    dlg._ai_mode = "official"
    dlg._byom_prompt = ""
    dlg._v2_state = dlg._ai_v2()
    dlg._busy(False)

    # 构造 10 轮历史（首轮带上下文），超预算 → 应截断且重注入上下文
    hist = [{"role": "user",
             "content": "【数值上下文】首轮上下文\n\n释图指令"}]
    for i in range(10):
        hist.append({"role": "user", "content": f"追问{i}"})
        hist.append({"role": "assistant", "content": "a" * 998})
    dlg._chat_messages = hist
    dlg._run_send_image = False
    dlg._run_image_b64 = ""

    class _MockProvider:
        def check(self):
            return True, "ok"

    monkeypatch.setattr(dlg, "_make_provider", lambda: _MockProvider())
    monkeypatch.setattr(dlg, "context_getter",
                        lambda: "【数值上下文】重注入上下文")

    dlg.input_edit.setPlainText("新追问")
    dlg._on_run()
    worker = dlg._worker
    chat_msgs = [m for m in worker.messages if m["role"] != "system"]
    # 预算：≤6 轮（≤12 条对话消息）+ 末尾新追问
    assert len(chat_msgs) <= 6 * 2 + 1
    # 上下文重注入：至少一条 user 消息含数值上下文
    assert any(isinstance(m.get("content"), str)
               and "【数值上下文" in m["content"] for m in chat_msgs)
    assert chat_msgs[-1] == {"role": "user", "content": "新追问"}
    # system 路由：official → 占位常量
    assert worker.messages[0] == {"role": "system",
                                  "content": ai.SYSTEM_PROMPT_FINAL}


def test_stop_is_idempotent(dlg, qapp, monkeypatch):
    """停止控件：cancel 幂等（重复调用仅置位，重复点击不重复建 worker）。

    T-1018 归因（非静默）：原用例打桩 _save_config（面板已不写回配置，方法删除），
    停控断言本身不变。
    """
    _stop_mock(qapp)
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)

    started = []

    class _MockProvider:
        def check(self):
            return True, "ok"

    monkeypatch.setattr(dlg, "_make_provider", lambda: _MockProvider())

    dlg._worker = None
    dlg._on_stop()  # 无 worker：安全 no-op
    assert dlg._worker is None

    worker = ai._InterpretWorker(None, [{"role": "user", "content": "q"}])
    worker._cancelled = False

    def fake_running(self):
        started.append(1)
        return True

    monkeypatch.setattr(type(worker), "isRunning", fake_running)
    dlg._worker = worker
    dlg._on_stop()
    dlg._on_stop()  # 幂等：再次调用不抛错、不新建
    assert worker._cancelled is True
    assert len(started) >= 1
    assert dlg._worker is worker  # 未重复建 worker
