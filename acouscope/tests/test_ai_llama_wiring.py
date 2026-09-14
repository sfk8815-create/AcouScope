# SPDX-License-Identifier: GPL-3.0-only
"""T-314a: llama_cpp provider 接线受管 runtime（全 mock，不 show 主窗）。

口径对齐 tests/test_ai_panel_v2.py：AIInterpretDialog 用 offscreen + 不 show
构造（_config_paths 打桩为空）；_InterpretWorker 直接实例化并同步 run()；
llama_runtime / llama_models / ollama_runtime 全部 monkeypatch（禁真进程/
真下载/真网络）；provider 为 mock 对象。
"""
import sys
sys.path.insert(0, "src")
import pytest
pytest.importorskip("PyQt6")
from acouscope.ai import llama_models, llama_runtime
from acouscope.ai import ollama_runtime
from acouscope.ui.widgets import ai_interpret as ai


# ----------------------------------------------------------------------
# 替身
# ----------------------------------------------------------------------

class _FakeLlamaRT:
    """受管 llama-server 替身：记录 start 调用，状态/地址可注入。"""

    def __init__(self, state="stopped", base_url=""):
        self.state = state
        self.base_url = base_url
        self.last_error = ""
        self.start_calls = []

    def start(self, model_path, ctx_size=4096, timeout=180.0):
        self.start_calls.append({"model_path": model_path,
                                 "ctx_size": ctx_size, "timeout": timeout})
        if self._start_result is True:
            self.state = "ready"
            self.base_url = self.base_url or "http://127.0.0.1:54321/v1"
            return True
        self.state = "failed"
        return self._start_result

    def stop(self):
        self.state = "stopped"

    # 测试注入点
    _start_result = True


class _FakeOllamaRT:
    """ollama 引擎替身（回归保护：确认 llama 路由不触碰 ollama 模块）。"""

    def __init__(self, state="stopped"):
        self.state = state
        self.base_url = ""
        self.start_calls = []

    def start(self, timeout=30.0):
        self.start_calls.append(timeout)
        return True


class _MockProvider:
    def __init__(self, reply="ok"):
        self.reply = reply
        self.chat_calls = []

    def chat(self, messages, image_b64="", on_chunk=None,
             is_cancelled=None):
        self.chat_calls.append({"messages": messages, "image_b64": image_b64})
        if on_chunk:
            on_chunk(self.reply)
        return self.reply

    def check(self):
        return True, "ok"


# ----------------------------------------------------------------------
# 面板 fixture（口径同 test_ai_panel_v2.py：offscreen、不 show、不写真实配置）
# ----------------------------------------------------------------------

@pytest.fixture
def dlg(qapp):
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


def _use_cfg(dlg, monkeypatch, tmp_path, data: dict):
    """T-1018 归因（非静默）：面板内三档下拉/地址/模型名输入已删除 → 配置一律以
    ai_config.json + reload_config 驱动只读装配。"""
    import json as _json
    cfg = tmp_path / "ai_config.json"
    cfg.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    dlg.reload_config()
    dlg._v2_state = dlg._ai_v2()
    return cfg


def _load_legacy_llama(dlg, monkeypatch, tmp_path, model="fake-3b.gguf",
                       llama_model_id="fake-3b", url=""):
    """构造旧 provider=llama_cpp 配置并重载面板（T-1011 三档迁移路径）。"""
    return _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "llama_cpp", "url": url, "model": model, "key": "",
        "send_image": False,
        "ai_v2": {"mode": "official", "llama_model_id": llama_model_id,
                  "external_ollama": False, "external_ollama_url": ""},
    })


def _spy_make_provider(monkeypatch):
    """拦截 interpreter.make_provider，记录入参并返回 mock provider。"""
    calls = []
    monkeypatch.setattr(
        ai.interpreter, "make_provider",
        lambda kind, url, key, model: calls.append(
            {"kind": kind, "url": url, "key": key, "model": model})
            or _MockProvider())
    return calls


# ----------------------------------------------------------------------
# 契约 B.1-B.3：_make_provider 动态端口注入
# ----------------------------------------------------------------------

def test_make_provider_injects_llama_url(dlg, monkeypatch, tmp_path):
    """旧 llama_cpp 配置迁移自建档 → 受管 runtime ready 注入动态端口。"""
    fake = _FakeLlamaRT(state="ready", base_url="http://127.0.0.1:54321/v1")
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake)
    calls = _spy_make_provider(monkeypatch)
    _load_legacy_llama(dlg, monkeypatch, tmp_path)   # T-1018：空 url 由配置给出
    dlg._make_provider()
    assert calls, "make_provider 未被调用"
    assert calls[0]["kind"] == "llama_cpp"
    assert calls[0]["url"] == "http://127.0.0.1:54321/v1"
    assert "8080" not in calls[0]["url"]


def test_make_provider_manual_url_wins(dlg, monkeypatch, tmp_path):
    """配置中的地址最高优先 → 不注入受管端口（原面板输入框已删，改配置驱动）。"""
    fake = _FakeLlamaRT(state="ready", base_url="http://127.0.0.1:54321/v1")
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake)
    calls = _spy_make_provider(monkeypatch)
    _load_legacy_llama(dlg, monkeypatch, tmp_path,
                       url="http://127.0.0.1:9999/v1")
    dlg._make_provider()
    assert calls[0]["url"] == "http://127.0.0.1:9999/v1"


def test_make_provider_runtime_not_ready_no_inject(dlg, monkeypatch, tmp_path):
    """runtime 未 ready → url 以空串传 make_provider（异常吞掉，不崩）。"""
    fake = _FakeLlamaRT(state="stopped")
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake)
    calls = _spy_make_provider(monkeypatch)
    _load_legacy_llama(dlg, monkeypatch, tmp_path)
    dlg._make_provider()  # 不抛异常
    assert calls[0]["url"] == ""


# ----------------------------------------------------------------------
# 契约 B.4-B.7：worker 懒启动路由
# ----------------------------------------------------------------------

def _run_worker(monkeypatch, provider, runtime_kind, ensure_runtime=True):
    """同步直跑 worker.run()（mock provider 无网络），返回 (worker, ok, fail)。"""
    results, failures = [], []
    w = ai._InterpretWorker(provider, [{"role": "user", "content": "q"}],
                            text_only=False, ensure_runtime=ensure_runtime,
                            runtime_kind=runtime_kind)
    w.finished_ok.connect(results.append)
    w.failed.connect(failures.append)
    w.run()
    return w, results, failures


def test_worker_llama_starts_with_model(monkeypatch):
    """llama 路由：模型就绪 → start(模型路径, timeout=180) 后正常 chat。"""
    fake_models_ready = True
    monkeypatch.setattr(llama_models, "is_model_ready",
                        lambda mid: fake_models_ready)
    fake_path = "fake-model-path.gguf"
    monkeypatch.setattr(llama_models, "model_path", lambda mid: fake_path)
    fake_rt = _FakeLlamaRT(state="stopped")
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake_rt)

    provider = _MockProvider()
    _w, results, failures = _run_worker(monkeypatch, provider, "llama_cpp")
    assert fake_rt.start_calls, "llama get_runtime().start 未被调用"
    assert fake_rt.start_calls[0]["model_path"] == fake_path
    assert fake_rt.start_calls[0]["timeout"] == 180
    assert failures == []
    assert results == ["ok"]
    assert provider.chat_calls, "provider.chat 未被调用"


def test_worker_llama_model_not_ready_fails(monkeypatch):
    """模型未就绪 → 友好文案 failed，start/chat 零调用。"""
    monkeypatch.setattr(llama_models, "is_model_ready", lambda mid: False)
    fake_path = "fake-model-path.gguf"
    monkeypatch.setattr(llama_models, "model_path", lambda mid: fake_path)
    fake_rt = _FakeLlamaRT(state="ready")  # 即使 ready 也不应被触碰 start
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake_rt)

    provider = _MockProvider()
    _w, results, failures = _run_worker(monkeypatch, provider, "llama_cpp")
    assert len(failures) == 1
    assert "下载本地模型" in failures[0]
    assert "://" not in failures[0]  # 零终端文案
    assert fake_rt.start_calls == []
    assert provider.chat_calls == []
    assert results == []


def test_worker_llama_start_fails_friendly(monkeypatch):
    """start 失败 → 零终端友好文案，chat 零调用。"""
    monkeypatch.setattr(llama_models, "is_model_ready", lambda mid: True)
    monkeypatch.setattr(llama_models, "model_path",
                        lambda mid: "fake-model-path.gguf")
    fake_rt = _FakeLlamaRT(state="stopped")
    fake_rt._start_result = False
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake_rt)

    provider = _MockProvider()
    _w, results, failures = _run_worker(monkeypatch, provider, "llama_cpp")
    assert len(failures) == 1
    assert "://" not in failures[0]
    assert "重试" in failures[0]
    assert fake_rt.start_calls, "start 应被调用一次"
    assert provider.chat_calls == []
    assert results == []


def test_worker_ollama_path_unchanged(monkeypatch):
    """回归：runtime_kind=ollama → 仍走 ollama_runtime.start(timeout=30.0)，
    不触碰 llama 模块。"""
    fake_ollama = _FakeOllamaRT(state="stopped")
    monkeypatch.setattr(ollama_runtime, "get_runtime", lambda: fake_ollama)
    llama_rt_calls = []

    def _boom():
        llama_rt_calls.append(1)
        raise AssertionError("llama get_runtime 不应被调用")
    monkeypatch.setattr(llama_runtime, "get_runtime", _boom)

    provider = _MockProvider()
    _w, results, failures = _run_worker(monkeypatch, provider, "ollama")
    assert fake_ollama.start_calls == [30.0]
    assert failures == []
    assert results == ["ok"]
    assert llama_rt_calls == []


# ----------------------------------------------------------------------
# 契约 B.8-B.9：_make_worker 标志 / _on_provider_changed 字段
# ----------------------------------------------------------------------

def test_make_worker_ensure_flags(dlg, monkeypatch, tmp_path):
    """T-1011 三档 ensure_runtime 语义：builtin(ollama) 懒启动；自建/云不懒启。

    T-1018 归因（非静默）：档位不再由面板下拉给出，改由 ai_config.json 只读驱动；
    懒启动语义与旧 llama_cpp 遗留路由断言不变。
    """
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)

    def _mk():
        return ai.AIInterpretDialog._make_worker(
            dlg, _MockProvider(), [], "q", "【数值上下文】c")

    # builtin → ollama，无 external → 懒启动
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin", "external_ollama": False,
                  "external_ollama_url": ""},
    })
    w3 = _mk()
    assert w3.ensure_runtime is True
    assert w3.runtime_kind == "ollama"

    # builtin + 遗留 external 开关（外部 Ollama 地址）→ 不懒启动
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "",
        "key": "",
        "ai_v2": {"source": "builtin", "external_ollama": True,
                  "external_ollama_url": "http://127.0.0.1:11434"},
    })
    w2 = _mk()
    assert w2.ensure_runtime is False
    assert w2.runtime_kind is None

    # 旧 provider=llama_cpp 迁移自建档 → 受管 llama-server 懒启动
    _load_legacy_llama(dlg, monkeypatch, tmp_path, model="qwen2.5:3b")
    w5 = _mk()
    assert w5.ensure_runtime is True
    assert w5.runtime_kind == "llama_cpp"

    # 本地部署（custom，非 llama_cpp）→ 不懒启动
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "custom", "url": "http://127.0.0.1:11434",
        "model": "qwen2.5:3b", "key": "",
        "ai_v2": {"source": "self_hosted", "external_ollama": False,
                  "external_ollama_url": ""},
    })
    w6 = _mk()
    assert w6.ensure_runtime is False
    assert w6.runtime_kind is None

    # 云端 openai → 不懒启动
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "openai", "url": "https://api.openai.com/v1",
        "model": "gpt-4o", "key": "sk-x",
        "ai_v2": {"source": "cloud", "external_ollama": False,
                  "external_ollama_url": ""},
    })
    w4 = _mk()
    assert w4.ensure_runtime is False
    assert w4.runtime_kind is None


def test_legacy_llama_fields_on_reload(dlg, monkeypatch, tmp_path):
    """旧 llama_cpp 配置 → 自建档 + 引擎路由保留（字段/只读语义按档迁移）。

    T-1011 归因：llama_cpp 不再是顶层可选 provider（T-320 三档收口）。
    T-1018 归因（非静默）：面板内地址/模型名输入已删除，字段断言改读只读状态
    （_source/_eng_model/_url_self），配置保留语义不变。"""
    _load_legacy_llama(dlg, monkeypatch, tmp_path, model="fake-3b.gguf",
                       llama_model_id="fake-3b")
    assert dlg._source == "self_hosted"
    assert dlg._eng_model == "fake-3b.gguf"
    assert dlg._url_self == ""
    assert dlg._engine_for_current()["kind"] == "llama_cpp"


# ----------------------------------------------------------------------
# 契约 B（T-314c）：选中模型接线 + GGUF text_only 路由 + ai_v2 附加键保护
# ----------------------------------------------------------------------

def _fake_models():
    """受管 GGUF 目录打桩（假 id/假 filename，不触碰真实模型沙盒目录）。"""
    def mk(mid, fn):
        return llama_models.ModelInfo(
            model_id=mid, display_name=mid, filename=fn,
            urls=(), est_bytes=0, sha256=None)
    return (mk("fake-1.5b", "fake-1.5b.gguf"),
            mk("fake-3b", "fake-3b.gguf"))


def test_text_only_managed_gguf(monkeypatch):
    """受管 GGUF filename（含 strip 后）→ text_only=True；非受管外部
    gguf / 注册表外模型 → False（既有注册表路由回归）。"""
    models = _fake_models()
    monkeypatch.setattr(llama_models, "list_models", lambda: models)
    assert ai._model_text_only(models[0].filename) is True
    assert ai._model_text_only(models[1].filename) is True
    assert ai._model_text_only("  " + models[1].filename + "  ") is True
    # 外部 llama-server 的未来 VL GGUF 不命中受管集合 → 不预设为纯文本，
    # 仍走既有「发送失败 → 自动降级纯文本重试」兜底
    assert ai._model_text_only("some-external-vl.gguf") is False
    # 回归：注册表外/未知模型保持 False
    assert ai._model_text_only("gpt-4o") is False


def test_managed_gguf_text_only_on_reload(dlg, monkeypatch, tmp_path):
    """自建档含受管 GGUF 模型名 → 视觉路由判定为纯文本（text_only 按模型名）。

    T-1011 归因：原「切到 llama_cpp 填选中 GGUF」UI 随旧下拉删除。
    T-1018 归因（非静默）：「发送图像」开关已删除，改验同一视觉路由契约的判定源
    （受管 GGUF 文件名 → _model_text_only True）。"""
    models = _fake_models()
    monkeypatch.setattr(llama_models, "list_models", lambda: models)
    _load_legacy_llama(dlg, monkeypatch, tmp_path,
                       model=models[1].filename,
                       llama_model_id=models[1].model_id)
    assert dlg._eng_model == models[1].filename
    assert ai._model_text_only(dlg._eng_model) is True
    assert ai._model_text_only("some-external-vl.gguf") is False   # 非受管不预锁


def test_legacy_llama_persist_select_id(dlg, monkeypatch, tmp_path):
    """迁移后选中 id 保留；面板只读装配不改写配置文件（T-1018 写回删撤）。"""
    models = _fake_models()
    monkeypatch.setattr(llama_models, "list_models", lambda: models)
    cfg = _load_legacy_llama(dlg, monkeypatch, tmp_path,
                             model=models[1].filename,
                             llama_model_id=models[1].model_id)
    before = cfg.read_bytes()
    assert dlg._llama_model_id == models[1].model_id
    dlg.reload_config()
    dlg._update_model_label()
    assert cfg.read_bytes() == before      # 面板不写回（设置归设置-AI）


def test_worker_uses_selected_model(monkeypatch):
    """worker 携带选中 id → 懒启动 start 首参 = 选中（3B）模型路径，非 [0]。"""
    models = _fake_models()
    monkeypatch.setattr(llama_models, "list_models", lambda: models)
    monkeypatch.setattr(llama_models, "is_model_ready", lambda mid: True)
    monkeypatch.setattr(llama_models, "model_path",
                        lambda mid: f"{mid}-path.gguf")
    fake_rt = _FakeLlamaRT(state="stopped")
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake_rt)

    provider = _MockProvider()
    w = ai._InterpretWorker(
        provider, [{"role": "user", "content": "q"}],
        text_only=True, ensure_runtime=True, runtime_kind="llama_cpp",
        llama_model_id=models[1].model_id)
    results, failures = [], []
    w.finished_ok.connect(results.append)
    w.failed.connect(failures.append)
    w.run()
    assert fake_rt.start_calls, "llama get_runtime().start 未被调用"
    assert fake_rt.start_calls[0]["model_path"] == "fake-3b-path.gguf"
    assert fake_rt.start_calls[0]["model_path"] != "fake-1.5b-path.gguf"
    assert failures == []
    assert results == ["ok"]


def test_worker_unknown_id_falls_back(monkeypatch):
    """worker 携带未知 id → 回退目录 [0] 的模型路径。"""
    models = _fake_models()
    monkeypatch.setattr(llama_models, "list_models", lambda: models)
    monkeypatch.setattr(llama_models, "is_model_ready", lambda mid: True)
    monkeypatch.setattr(llama_models, "model_path",
                        lambda mid: f"{mid}-path.gguf")
    fake_rt = _FakeLlamaRT(state="stopped")
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake_rt)

    provider = _MockProvider()
    w = ai._InterpretWorker(
        provider, [{"role": "user", "content": "q"}],
        text_only=False, ensure_runtime=True, runtime_kind="llama_cpp",
        llama_model_id="ghost")
    results, failures = [], []
    w.finished_ok.connect(results.append)
    w.failed.connect(failures.append)
    w.run()
    assert fake_rt.start_calls
    assert fake_rt.start_calls[0]["model_path"] == "fake-1.5b-path.gguf"
    assert failures == []
    assert results == ["ok"]


def test_make_worker_passes_model_id(dlg, monkeypatch, tmp_path):
    """_make_worker 透传遗留选中 id 至 worker.llama_model_id（三档迁移路径）。"""
    models = _fake_models()
    monkeypatch.setattr(llama_models, "list_models", lambda: models)
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
    _load_legacy_llama(dlg, monkeypatch, tmp_path,
                       model=models[1].filename,
                       llama_model_id=models[1].model_id)
    dlg._v2_state = dlg._ai_v2()
    w = ai.AIInterpretDialog._make_worker(
        dlg, _MockProvider(), [], "q", "【数值上下文】c")
    assert w.llama_model_id == models[1].model_id
    assert w.ensure_runtime is True
    assert w.runtime_kind == "llama_cpp"


def test_panel_has_no_config_writeback(dlg, monkeypatch, tmp_path):
    """T-1018 归因（非静默）：面板设置控件全部删除后，本面板不再写回 ai_config.json
    （模型/厂商/密钥设置归设置-AI）。原 _save_config 合并写入用例的被测方法已随
    写回链路一并删除，改验「只读装配」硬约束：① 类内无 _save_config / 无写盘调用；
    ② 反复 reload 不改动配置文件；③ ai_v2 附加键只读保留。"""
    import pathlib
    src = pathlib.Path(ai.__file__).read_text(encoding="utf-8")
    cls_src = src.split("class AIInterpretDialog(QWidget):", 1)[1]
    assert "_save_config" not in cls_src
    assert "write_text(" not in cls_src        # 类内零写盘（模块级兜底链路除外）

    cfg = _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "custom", "url": "http://fake:11434",
        "model": "qwen2.5:3b", "key": "",
        "ai_v2": {"mode": "official", "llama_model_id": "fake-3b",
                  "external_ollama": False, "external_ollama_url": ""},
    })
    before = cfg.read_bytes()
    dlg.reload_config()
    dlg._update_model_label()
    assert cfg.read_bytes() == before
    assert dlg._persisted_v2["llama_model_id"] == "fake-3b"   # 附加键只读保留
    assert dlg._ai_v2()["mode"] == "official"


def test_load_config_reads_llama_model_id(dlg, monkeypatch, tmp_path):
    """_load_config 读 ai_v2.llama_model_id 与全量附加键 _persisted_v2。"""
    cfg = tmp_path / "ai_config.json"
    import json as _json
    cfg.write_text(_json.dumps({
        "provider": "free_remote",
        "ai_v2": {"llama_model_id": "fake-3b",
                  "external_ollama": True,
                  "external_ollama_url": "http://fake:11434"},
    }), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    dlg._load_config()
    assert dlg._llama_model_id == "fake-3b"
    assert dlg._persisted_v2["external_ollama"] is True
    assert dlg._persisted_v2["external_ollama_url"] == "http://fake:11434"


# ----------------------------------------------------------------------
# 契约 B.10：测试纪律自断言
# ----------------------------------------------------------------------

def test_no_dialog_no_show():
    """本测试文件禁 show 调用/模态对话框/主窗构造（非模态铁律 + backlog #6/#7）。
    搜索串以片段拼接，避免断言自身命中。"""
    import pathlib
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "." + "show(" not in src
    assert "QD" + "ialog" not in src
    assert "Main" + "Window(" not in src
