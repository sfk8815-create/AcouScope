# SPDX-License-Identifier: GPL-3.0-only
"""T-305b：UI 零终端收口（AT-410 用户侧验收面）。

覆盖（T-320 三档制适配后）：
- 设置-AI：内置档状态行只读 / 旧下载·外部开关控件负向断言（已随三档制移除，
  下载入口属 T-316~319 bundled 链） / 本地部署档 external_ollama 持久化；
- 释图面板：本地模型 worker 懒启动内置引擎 + provider 注入内置实例动态端口；
- 全 AI 域用户可见文案零终端（禁词扫描，排除开发者注释/文档字符串）。

全部 mock：runtime / model_manager / urlopen 均不触网，不真实启动 ollama 进程，
不真实弹模态。
"""
import ast
import io
import sys
import tokenize
from pathlib import Path

import pytest
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.ui.widgets import settings_dialog as sd  # noqa: E402
from acouscope.ui.widgets import ai_interpret as ai  # noqa: E402

_SRC = Path(__file__).resolve().parents[1] / "src" / "acouscope"

# 零终端禁词表（用户可见文案铁律，AT-410）
BANNED = [
    "ollama serve", "ollama pull", "ollama.com", "终端运行",
    "请安装 Ollama", "请先安装", "brew install", "https://ollama",
]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def dlg(app, monkeypatch):
    """设置对话框（probe_ollama 打桩，零网络；不写真实配置）。"""
    import acouscope.ai.backends.local_registry as lr
    monkeypatch.setattr(lr, "probe_ollama", lambda *a, **k: (False, []))
    return sd.SettingsDialog(ai_config={})


@pytest.fixture
def idlg(qapp, monkeypatch, tmp_path):
    """AI 释图对话框（T-1018：配置改由 ai_config.json 只读驱动，内置档）。

    _config_paths 打桩到 tmp，绝不写真实用户配置。
    """
    import json as _json

    cfg = tmp_path / "ai_config.json"
    cfg.write_text(_json.dumps({
        "provider": "ollama", "url": "", "model": "", "key": "",
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    d = ai.AIInterpretDialog(
        image_getter=lambda: b"fake-png",
        context_getter=lambda: "【数值上下文】测试上下文",
        view_name_getter=lambda: "FFT 频谱",
    )
    yield d
    d.deleteLater()


class _FakeRuntime:
    def __init__(self, state="ready", base_url="http://127.0.0.1:5555",
                 start_ok=True):
        self.state = state
        self.base_url = base_url
        self._start_ok = start_ok
        self.start_calls = 0

    def start(self, timeout=30.0):
        self.start_calls += 1
        if self._start_ok:
            self.state = "ready"
            if not self.base_url:
                self.base_url = "http://127.0.0.1:5555"
            return True
        self.state = "failed"
        return False


def _patch_runtime(monkeypatch, rt):
    """注入假 runtime：get_runtime() 是模块级单例函数，补丁须落在其返回的
    _runtime 对象上（补丁模块属性 get_runtime 对 run() 内局部 from-import 无效）。"""
    import acouscope.ai.ollama_runtime as ort
    monkeypatch.setattr(ort, "_runtime", rt)


def _patch_pull(monkeypatch, progress=0.5):
    """model_manager.pull_model 打桩：进度回调 + 成功返回（零网络）。"""
    from acouscope.ai import model_manager
    calls = {"n": 0, "progress": []}

    def fake_pull(model, on_progress=None, is_cancelled=None, base_url=None):
        calls["n"] += 1
        calls["model"] = model
        calls["base_url"] = base_url
        if is_cancelled is not None and is_cancelled():
            raise ai.interpreter.CancelledError
        if on_progress is not None:
            on_progress(progress)
            on_progress(1.0)
    monkeypatch.setattr(model_manager, "pull_model", fake_pull)
    return calls


# ---------------------------------------------------------------------------
# A 组：设置-AI 选项卡
# ---------------------------------------------------------------------------

def test_builtin_status_line(dlg):
    """内置档状态行只读展示：引擎未运行 → 「首次使用」中性文案（A1 收口，
    T-320 三档制改版：原「本地引擎状态：」前缀标签随官方组移除）。"""
    text = dlg.lbl_ai_builtin_status.text()
    assert text.strip()
    assert "首次使用" in text
    for b in BANNED:
        assert b not in text


def test_download_controls_removed(dlg):
    """T-320 归因：官方组下载按钮/进度标签/外部开关 UI 已随三档制移除
    （下载入口由 T-316~319 bundled 链重建），负向断言防回潮。"""
    for attr in ("btn_download", "lbl_download", "cmb_provider",
                 "chk_external", "edit_external_url"):
        assert not hasattr(dlg, attr), f"旧控件回潮: {attr}"
    assert not hasattr(sd, "_ModelPullWorker"), "旧下载 worker 回潮"


def test_external_persist(dlg, monkeypatch):
    """本地部署档 + 服务地址经既有 ai_config() 保存流程持久化（A4/A5，
    T-320 三档制：原外部 Ollama 开关语义并入「本地部署的模型」档）。"""
    url = "http://203.0.113.20:11434"
    dlg.rbtn_ai_self.setChecked(True)
    dlg.edit_self_url.setText(url)
    cfg = dlg.ai_config()
    v2 = cfg["ai_v2"]
    assert v2["external_ollama"] is True
    assert v2["external_ollama_url"] == url
    assert v2["source"] == "self_hosted"
    # 既有 5 键仍在
    for k in ("provider", "url", "model", "key", "send_image"):
        assert k in cfg
    # 恢复：新对话框从该配置恢复本地部署档与服务地址
    import acouscope.ai.backends.local_registry as lr
    monkeypatch.setattr(lr, "probe_ollama", lambda *a, **k: (False, []))
    d2 = sd.SettingsDialog(ai_config=cfg)
    assert d2.rbtn_ai_self.isChecked() is True
    assert d2.edit_self_url.text() == url
    d2.deleteLater()


# ---------------------------------------------------------------------------
# B 组：释图面板
# ---------------------------------------------------------------------------

def test_worker_lazy_start_fail(monkeypatch):
    """本地模型 worker 懒启动引擎失败 → failed 信号文案零终端。"""
    rt = _FakeRuntime(state="stopped", start_ok=False)
    _patch_runtime(monkeypatch, rt)

    class _NoProvider:
        def chat(self, *a, **k):
            raise AssertionError("引擎启动失败后不应触达 provider")

    w = ai._InterpretWorker(_NoProvider(), [], ensure_runtime=True)
    msg = []
    w.failed.connect(lambda m: msg.append(m))
    w.run()  # 同步调用，禁 start 线程

    assert rt.start_calls == 1
    assert len(msg) == 1
    for b in BANNED:
        assert b not in msg[0]


def test_worker_lazy_start_success_then_chat(monkeypatch):
    """懒启动成功（stopped → start→ready）→ 继续 provider 调用，finished_ok 回传。"""
    rt = _FakeRuntime(state="stopped", start_ok=True)
    _patch_runtime(monkeypatch, rt)

    class _OkProvider:
        def chat(self, messages, image_b64="", on_chunk=None, is_cancelled=None):
            if on_chunk:
                on_chunk("释读结果")
            return "释读结果"

    w = ai._InterpretWorker(_OkProvider(),
                            [{"role": "user", "content": "q"}],
                            ensure_runtime=True)
    ok, failed = [], []
    w.finished_ok.connect(lambda t: ok.append(t))
    w.failed.connect(lambda m: failed.append(m))
    w.run()  # 同步调用，禁 start 线程

    assert rt.start_calls == 1
    assert rt.state == "ready"
    assert ok == ["释读结果"]
    assert failed == []


def _pick_builtin(d):
    """内置档（引擎 ollama）选择。

    T-1011：原 cmb_provider 旧下拉已删除。
    T-1018 归因（非静默）：面板三档下拉整体删除，档位改由 ai_config.json 只读
    驱动（idlg fixture 已写内置档配置），此处仅断言解析结果。
    """
    assert d._source == "builtin"
    assert d._engine_for_current()["kind"] == "ollama"


def test_provider_uses_runtime_port(idlg, monkeypatch):
    """ollama 路由：内置档 URL 空 + 无外部开关 → 注入内置实例动态端口。"""
    rt = _FakeRuntime(state="ready", base_url="http://127.0.0.1:5555")
    _patch_runtime(monkeypatch, rt)
    captured = {}
    monkeypatch.setattr(
        ai.interpreter, "make_provider",
        lambda kind, url="", key="", model="":
            captured.update(kind=kind, url=url, key=key, model=model) or object())

    _pick_builtin(idlg)
    idlg._persisted_v2 = {"external_ollama": False, "external_ollama_url": ""}
    idlg._make_provider()
    assert captured["kind"] == "ollama"
    assert captured["url"] == "http://127.0.0.1:5555"


def test_provider_external_ollama_wins(idlg, monkeypatch):
    """遗留外部 Ollama 键开启且 URL 非空 → 传外部 URL（优先于运行时注入）。"""
    captured = {}
    monkeypatch.setattr(
        ai.interpreter, "make_provider",
        lambda kind, url="", key="", model="":
            captured.update(kind=kind, url=url, key=key, model=model) or object())

    _pick_builtin(idlg)
    idlg._persisted_v2 = {"external_ollama": True,
                          "external_ollama_url": "http://203.0.113.20:11434"}
    idlg._make_provider()
    assert captured["url"] == "http://203.0.113.20:11434"


def test_worker_ensure_runtime_kwarg_via_make_worker(idlg, monkeypatch):
    """_make_worker：内置档且未开外部开关 → ensure_runtime=True（懒启动入口）。"""
    captured = {}
    monkeypatch.setattr(ai, "_InterpretWorker",
                        lambda *a, **k: captured.update(args=a, kwargs=k)
                        or _StubWorker())
    monkeypatch.setattr(ai, "build_messages", lambda **k: [
        {"role": "user", "content": "q"}])

    _pick_builtin(idlg)
    idlg._v2_state = {"mode": "official", "official_model": "spark-x2.5-1.7b",
                      "byom_model": "", "byom_prompt": "",
                      "external_ollama": False, "external_ollama_url": ""}
    idlg._persisted_v2 = {"external_ollama": False,
                          "external_ollama_url": ""}
    idlg._run_image_b64 = ""
    idlg._run_send_image = False
    idlg._make_worker(object(), [], "问题", "【数值上下文】ctx")
    assert captured["kwargs"].get("ensure_runtime") is True

    # 外部开关开启 → 不懒启动（走外部端口，进程不受管）
    idlg._persisted_v2 = {"external_ollama": True,
                          "external_ollama_url": "http://203.0.113.20:11434"}
    idlg._v2_state["external_ollama"] = True
    idlg._v2_state["external_ollama_url"] = "http://203.0.113.20:11434"
    idlg._make_worker(object(), [], "问题", "【数值上下文】ctx")
    assert captured["kwargs"].get("ensure_runtime") is False


class _Sig:
    """最小信号替身：仅需 connect 不抛异常。"""
    def connect(self, fn):
        pass


class _StubWorker:
    """_make_worker 打桩返回体：仅需可被连接信号即可。"""
    chunk = _Sig()
    notice = _Sig()
    finished_ok = _Sig()
    failed = _Sig()


def test_make_worker_stub_connectable(idlg, monkeypatch):
    """_StubWorker 占位：_make_worker 的信号连接不抛异常（契约自检）。"""
    # 该测试确保上一个测试的 stub 契约与真实调用面兼容：
    # 真实 _InterpretWorker 具备四个信号
    for sig in ("chunk", "notice", "finished_ok", "failed"):
        assert hasattr(ai._InterpretWorker, sig)


# ---------------------------------------------------------------------------
# C 组：全 AI 域零终端禁词扫描
# ---------------------------------------------------------------------------

def _user_visible_strings(path: Path) -> list[str]:
    """源码中「用户可见」字符串：全部字符串字面量（含 f-string）
    扣除模块/类/函数 docstring；注释由 tokenize 天然排除。

    开发者面向的文档字符串（模块 docstring 中的架构说明）不属于
    用户可见文案，故剔除；命令行/URL/安装指引若出现在代码串中仍会被命中。
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    doc_spans = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                d = body[0].value
                doc_spans.add((d.lineno, d.col_offset, d.end_lineno,
                               d.end_col_offset))
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.STRING:
            continue
        span = (tok.start[0], tok.start[1], tok.end[0], tok.end[1])
        if span in doc_spans:
            continue
        out.append(tok.string)
    return out


SWEEP_FILES = [
    "ai/backends/local_registry.py",
    "ai/model_manager.py",
    "ai/interpreter.py",
    "ai/ollama_runtime.py",
    "ui/widgets/settings_dialog.py",
    "ui/widgets/ai_interpret.py",
]


def test_no_terminal_copy_sweep():
    """6 个 AI 域文件：用户可见文案 0 命中禁词表（零终端铁律）。"""
    for rel in SWEEP_FILES:
        p = _SRC / rel
        assert p.exists(), f"缺失文件 {rel}"
        hits = []
        for lit in _user_visible_strings(p):
            for b in BANNED:
                if b in lit:
                    hits.append((rel, b, lit[:60]))
        assert not hits, f"零终端禁词命中: {hits}"


def test_c1_c2_reworded_zero_terminal():
    """C1/C2 定点：OllamaProvider.check 两条失败文案已收口且零终端。"""
    src = (_SRC / "ai" / "interpreter.py").read_text(encoding="utf-8")
    assert "本地引擎未就绪；首次释图会自动启动内置引擎" in src
    assert "尚未下载。请到「设置-AI」点击「下载选中模型」" in src
    for lit in _user_visible_strings(_SRC / "ai" / "interpreter.py"):
        for b in BANNED:
            assert b not in lit, (b, lit[:60])
