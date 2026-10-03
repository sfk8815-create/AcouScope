# SPDX-License-Identifier: GPL-3.0-only
"""T-1021 P0：本地引擎「懒启动时序」端到端回归（不 stub 被测环节）。

### 被测时序链（真实参与，禁打桩绕过）
    ai_config.json → AIInterpretDialog._engine_for_current()
    → _on_run() → 真实 _make_provider()（URL 解析就在这里）
    → _InterpretWorker.run()（先确保受管运行时就绪）
    → 实际发起请求所用 provider 的 base_url

### 修前缺陷（真机取证 E1~E6）
`_make_provider()` 在 `_on_run()` 时刻解析 URL，而受管运行时尚未启动
（state != ready）→ url 留空 → `interpreter.make_provider` 回退到
`PROVIDERS["llama_cpp"].base_url`（127.0.0.1:8080）/ `OLLAMA_DEFAULT`
（127.0.0.1:11434）这两个**无监听**的硬编码默认端口；随后 worker 才把受管服务
起在**动态端口**，但 provider 已构造且 `run()` 内从不重建 → 首次发送必断。

### 本文件纪律
* **禁 monkeypatch `_make_provider` 的返回值绕过**：`_make_provider` 与
  `interpreter.make_provider` 全程真实；只把 provider 的 `chat`（真网络）换成
  记录器，记录「实际请求时用的 base_url」。
* **禁真起进程/线程网络行为**：运行时模块 `get_runtime` 全换 fake（idle →
  `start()` 置 ready + 伪动态端口 59999）；`QThread.start` 打桩为空，worker 在
  本测试内同步 `run()`。
* 禁主窗 `show()`（宿主为普通 QWidget）、禁新建对话框类、禁真实 API Key（仅占位串）。
"""
import json
import sys

import pytest

sys.path.insert(0, "src")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QMessageBox

from acouscope.ai import interpreter, llama_models, llama_runtime, ollama_runtime
from acouscope.ui.widgets import ai_interpret as ai

#: 受管运行时替身的「伪动态端口」（真机实测为 51837，此处固定值仅用于断言）
_RUNTIME_URL = "http://127.0.0.1:59999/v1"
#: 用户手填 URL 场景
_USER_URL = "http://127.0.0.1:61234/v1"


class _FakeRuntime:
    """受管运行时替身：初始 idle/base_url 空 → start() 置 ready + 伪动态端口。"""

    def __init__(self, start_ok=True, raise_on_start=False):
        self.state = "idle"
        self.base_url = ""
        self.start_ok = start_ok
        self.raise_on_start = raise_on_start
        self.start_calls = []

    def start(self, *args, **kwargs):
        self.start_calls.append({"args": args, "kwargs": kwargs})
        if self.raise_on_start:
            raise RuntimeError("boom")
        if self.start_ok:
            self.state = "ready"
            self.base_url = _RUNTIME_URL
            return True
        self.state = "failed"
        return False

    def stop(self, timeout=5.0):
        self.state = "stopped"
        self.base_url = ""


def _fake_models():
    """受管 GGUF 目录打桩（假 id/假文件名，不触碰真实模型沙盒目录）。"""
    def mk(mid, fn):
        return llama_models.ModelInfo(
            model_id=mid, display_name=mid, filename=fn,
            urls=(), est_bytes=0, sha256=None)
    return (mk("fake-1.5b", "fake-1.5b.gguf"),
            mk("fake-3b", "fake-3b.gguf"))


def _patch_llama_models(monkeypatch):
    monkeypatch.setattr(llama_models, "list_models", _fake_models)
    monkeypatch.setattr(llama_models, "is_model_ready", lambda mid: True)
    monkeypatch.setattr(llama_models, "model_path", lambda mid: f"{mid}.gguf")


def _spy_chat(monkeypatch):
    """把「真实发请求」换成记录器：记录 provider 实际使用的 base_url。

    注意：只替换网络调用，**不碰** provider 的构造与 URL 解析链。
    """
    seen = []

    def _chat(self, messages, image_b64="", on_chunk=None, is_cancelled=None):
        seen.append(self.base_url)
        if on_chunk:
            on_chunk("ok")
        return "ok"

    monkeypatch.setattr(interpreter.OpenAICompatProvider, "chat", _chat)
    monkeypatch.setattr(interpreter.OllamaProvider, "chat", _chat)
    return seen


def _boom(*_a, **_k):
    raise AssertionError("云端/自填地址档不应触碰受管运行时")


# ----------------------------------------------------------------------
# 面板 fixture（口径同 test_ai_llama_wiring.py：offscreen、不 show、不写真实配置）
# ----------------------------------------------------------------------

@pytest.fixture
def dlg(qapp, monkeypatch):
    """面板 fixture（offscreen、不 show、不写真实配置）。

    注意：`_config_paths` 一律经**同一个** monkeypatch 实例打桩（面板构造期先兜底
    为空候选，用例内 `_use_cfg` 再指向 tmp 配置）——若另用独立 MonkeyPatch 实例，
    两层打桩的撤销顺序会互相压栈，导致 `_config_paths` 残留为空候选并污染后续
    用例（实测：致 test_ai_config_persist 档位落盘 4 例失败）。
    """
    monkeypatch.setattr(ai, "_config_paths", lambda: [])
    d = ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: "【数值上下文】测试上下文",
        view_name_getter=lambda: "FFT 频谱",
    )
    yield d
    d.deleteLater()


def _use_cfg(dlg, monkeypatch, tmp_path, data: dict):
    cfg = tmp_path / "ai_config.json"
    cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    dlg.reload_config()
    dlg._v2_state = dlg._ai_v2()
    return cfg


def _cfg_llama(dlg, monkeypatch, tmp_path, url=""):
    """旧 provider=llama_cpp 配置（自建档迁移路径，T-1011 三档）。"""
    return _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "llama_cpp", "url": url, "model": "fake-3b.gguf", "key": "",
        "send_image": False,
        "ai_v2": {"mode": "official", "llama_model_id": "fake-3b",
                  "external_ollama": False, "external_ollama_url": ""},
    })


def _send_sync(dlg, monkeypatch):
    """真实 `_on_run()`（含真实 _make_provider）→ 同步跑 `worker.run()`。

    返回 (worker, 懒启动**之前**构造的 provider.base_url)：后者即修前打进
    请求的默认端口，用于锁死「时序」这一被测点。
    """
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
    dlg.input_edit.setPlainText("这页图怎么读")
    dlg._on_run()
    worker = dlg._worker
    assert worker is not None
    before = worker.provider.base_url
    worker.run()                      # 不真起 QThread（同步化，禁网络/线程行为）
    return worker, before


# ----------------------------------------------------------------------
# 1) llama_cpp 档：首次发送必须用受管运行时就绪后的动态端口
# ----------------------------------------------------------------------

def test_llama_cpp_first_send_uses_runtime_port(dlg, monkeypatch, tmp_path):
    fake = _FakeRuntime()                      # idle，base_url 空（未就绪）
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake)
    _patch_llama_models(monkeypatch)
    seen = _spy_chat(monkeypatch)
    _cfg_llama(dlg, monkeypatch, tmp_path, url="")     # 用户未填 url

    worker, before = _send_sync(dlg, monkeypatch)

    # 修前证据（时序缺陷本体）：懒启动前构造的 provider 只能落到硬编码默认端口
    assert before == interpreter.PROVIDERS["llama_cpp"].base_url
    assert "8080" in before
    # 修后断言：实际请求使用的就是受管运行时就绪后的动态端口
    assert fake.start_calls, "受管 llama 运行时未被懒启动"
    assert fake.state == "ready"
    assert worker.provider.base_url == _RUNTIME_URL
    assert worker.provider.base_url != interpreter.PROVIDERS["llama_cpp"].base_url
    assert "8080" not in worker.provider.base_url
    assert seen == [_RUNTIME_URL], "实际发起请求时的 base_url 不是运行时端口"


# ----------------------------------------------------------------------
# 2) ollama 档：同构 race（不得落 11434 默认端口）
# ----------------------------------------------------------------------

def test_ollama_first_send_uses_runtime_port(dlg, monkeypatch, tmp_path):
    fake = _FakeRuntime()
    monkeypatch.setattr(ollama_runtime, "get_runtime", lambda: fake)
    monkeypatch.setattr(llama_runtime, "get_runtime", _boom)
    seen = _spy_chat(monkeypatch)
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin", "external_ollama": False,
                  "external_ollama_url": ""},
    })

    worker, before = _send_sync(dlg, monkeypatch)

    assert before == interpreter.OLLAMA_DEFAULT          # 修前：无监听的 11434
    assert fake.start_calls, "受管 ollama 运行时未被懒启动"
    assert worker.provider.base_url == _RUNTIME_URL
    assert worker.provider.base_url != interpreter.OLLAMA_DEFAULT
    assert "11434" not in worker.provider.base_url
    assert seen == [_RUNTIME_URL]


# ----------------------------------------------------------------------
# 3) 用户显式填 URL：仍以用户 URL 为准（运行时不得覆盖）
# ----------------------------------------------------------------------

def test_user_url_wins_over_runtime(dlg, monkeypatch, tmp_path):
    fake = _FakeRuntime()
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake)
    _patch_llama_models(monkeypatch)
    seen = _spy_chat(monkeypatch)
    _cfg_llama(dlg, monkeypatch, tmp_path, url=_USER_URL)

    worker, before = _send_sync(dlg, monkeypatch)

    assert before == _USER_URL
    assert worker.provider.base_url == _USER_URL     # 即使运行时已 ready 也不覆盖
    assert worker.provider.base_url != _RUNTIME_URL
    assert seen == [_USER_URL]


def test_external_ollama_url_wins_and_runtime_untouched(dlg, monkeypatch,
                                                        tmp_path):
    """外部 Ollama（自填地址）→ ensure_runtime=False：受管运行时零触碰。"""
    monkeypatch.setattr(llama_runtime, "get_runtime", _boom)
    monkeypatch.setattr(ollama_runtime, "get_runtime", _boom)
    seen = _spy_chat(monkeypatch)
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "ollama", "url": "http://203.0.113.9:11434", "model": "",
        "key": "",
        "ai_v2": {"source": "builtin", "external_ollama": True,
                  "external_ollama_url": "http://203.0.113.9:11434"},
    })

    worker, _before = _send_sync(dlg, monkeypatch)

    assert worker.provider_factory is None
    assert seen == ["http://203.0.113.9:11434"]


# ----------------------------------------------------------------------
# 4) 云端档：零影响（不触碰运行时、不重建 provider）
# ----------------------------------------------------------------------

def test_cloud_provider_untouched(dlg, monkeypatch, tmp_path):
    monkeypatch.setattr(llama_runtime, "get_runtime", _boom)
    monkeypatch.setattr(ollama_runtime, "get_runtime", _boom)
    seen = _spy_chat(monkeypatch)
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "openai", "url": "https://api.openai.com/v1",
        "model": "gpt-4o", "key": "PLACEHOLDER-NOT-A-REAL-KEY",
        "ai_v2": {"source": "cloud"},
    })

    worker, before = _send_sync(dlg, monkeypatch)

    assert worker.provider_factory is None
    assert before == "https://api.openai.com/v1"
    assert worker.provider.base_url == "https://api.openai.com/v1"
    assert seen == ["https://api.openai.com/v1"]


# ----------------------------------------------------------------------
# 5) 运行时启动失败：走既有 failed 文案（不崩、不静默、不发请求）
# ----------------------------------------------------------------------

@pytest.mark.parametrize("raise_on_start", [False, True])
def test_runtime_start_failure_keeps_friendly_message(dlg, monkeypatch,
                                                      tmp_path, raise_on_start):
    fake = _FakeRuntime(start_ok=False, raise_on_start=raise_on_start)
    monkeypatch.setattr(llama_runtime, "get_runtime", lambda: fake)
    _patch_llama_models(monkeypatch)
    seen = _spy_chat(monkeypatch)
    _cfg_llama(dlg, monkeypatch, tmp_path, url="")
    # 首轮 + 本地引擎失败 → 既有 T-307 兜底框（QMessageBox）会 exec 阻塞；
    # 按既有测试口径打桩 exec（不打桩被测时序链，仅为离屏无阻塞）。
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

    failures, results = [], []
    monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
    dlg.input_edit.setPlainText("这页图怎么读")
    dlg._on_run()
    worker = dlg._worker
    worker.failed.connect(failures.append)
    worker.finished_ok.connect(results.append)
    worker.run()

    assert failures == ["本地引擎启动失败。可在「设置-AI」重试，或一键切换远程模型。"]
    assert "://" not in failures[0]      # 用户可见文案零终端
    # 未就绪 → 一次请求都不发（绝不用默认端口 8080 冒充受管引擎）
    assert seen == []
    assert results == []


# ----------------------------------------------------------------------
# 纪律自断言（防回潮：stub 被测环节 / 真起线程 / 主窗 show / 真实 Key）
# ----------------------------------------------------------------------

def test_static_discipline():
    """本文件禁：主窗 show / 新建对话框类 / stub 被测环节（_make_provider·_make_worker·run）。

    以 AST 扫描 `setattr(...)` 的目标名，避免「断言串自身命中」的假守卫。
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "MainWindow" + ".show()" not in src
    assert "QD" + "ialog" not in src

    forbidden = {"_make_provider", "_make_worker", "run", "provider"}
    patched = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "setattr"):
            continue
        for arg in node.args[:2]:
            if isinstance(arg, ast.Attribute):
                patched.add(arg.attr)
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                patched.add(arg.value)
    assert not (patched & forbidden), f"被测环节被 stub：{patched & forbidden}"
