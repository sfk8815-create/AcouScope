# SPDX-License-Identifier: GPL-3.0-only
"""T-1022 §9.1：退出即停引擎（含崩溃兜底）——离屏 / 进程级自动化回归。

覆盖需求说明 Step 7b 的三组必测项：
1. 正常退出路径：`MainWindow.closeEvent` 显式调用两个受管运行时 `stop()`
   （各一次、幂等、绝不抛）；退出后无残留子进程 / 无监听端口（探针为打桩运行时，
   真实进程级断言见 Step 8 端到端脚本）。
2. 启动清理（崩溃/强杀兜底）：伪造 `engine_state.json`
   - 指向**不属本应用目录**的进程 → 不得终止（禁误杀用户自装引擎）；
   - 指向本应用资源目录内的受控子进程 → 应终止并清状态文件。
3. 语义断言：「卸载模型」＝停进程释放内存，**绝不删除**已下载的模型文件
   （删除只存在于用户显式动作 `ai_interpret.delete_entry` / 设置页按钮）。
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, "src")
pytest.importorskip("PyQt6")

from acouscope.ai import llama_runtime as lr  # noqa: E402


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

class _SpyRuntime:
    """受管运行时替身：只记录 stop() 调用（幂等、绝不抛）。"""

    def __init__(self):
        self.state = "ready"
        self.base_url = "http://127.0.0.1:59999"
        self.stop_calls = 0
        self.start_calls = 0

    def start(self, *a, **k):
        self.start_calls += 1
        return True

    def stop(self, timeout=5.0):
        self.stop_calls += 1


def _spy_runtimes(monkeypatch):
    import acouscope.ai.ollama_runtime as ort

    spies = {"llama": _SpyRuntime(), "ollama": _SpyRuntime()}
    monkeypatch.setattr(lr, "get_runtime", lambda: spies["llama"])
    monkeypatch.setattr(ort, "get_runtime", lambda: spies["ollama"])
    return spies


def _main_window(monkeypatch, tmp_path):
    """主窗（**不 show()**）；HOME / 数据目录 / 配置目录全部重定向到 tmp。"""
    import acouscope.utils.config as _cfg

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_cfg, "get_config_dir", lambda: tmp_path / "cfg")

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 0.5)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 300 * t), sr)
    return MainWindow(controller)


# ----------------------------------------------------------------------
# 1. 正常退出路径：closeEvent → 两 runtime stop()（各一次，幂等）
# ----------------------------------------------------------------------

def test_close_event_stops_both_managed_engines(qapp, monkeypatch, tmp_path):
    spies = _spy_runtimes(monkeypatch)
    win = _main_window(monkeypatch, tmp_path)
    try:
        win.close()                      # 触发 closeEvent（正常退出路径）
        qapp.processEvents()
        assert spies["llama"].stop_calls == 1, "关闭应用必须显式停内置 llama 引擎"
        assert spies["ollama"].stop_calls == 1, "关闭应用必须显式停内置 Ollama 引擎"
        # 幂等：重复 stop 不抛、不产生副作用
        spies["llama"].stop()
        spies["ollama"].stop()
        assert spies["llama"].stop_calls == 2
    finally:
        try:
            win.deleteLater()
        except RuntimeError:
            pass


def test_llama_runtime_stop_is_idempotent_and_never_raises(monkeypatch, tmp_path):
    """stop() 无进程时也安全（幂等、绝不抛）；重复调用状态仍为 stopped。"""
    rt = lr.LlamaRuntime()
    monkeypatch.setattr(lr, "engine_state_path",
                        lambda: tmp_path / "engine_state.json")
    rt.stop()
    rt.stop()
    assert rt.state == "stopped" and rt.base_url == ""


def test_runtime_stop_does_not_delete_model_files(monkeypatch, tmp_path,
                                                  fake_models):
    """「卸载模型」语义 = 停进程释放内存，**不删模型文件**（删除是另一显式动作）。"""
    model = lr.models_dir() / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
    mmproj = lr.models_dir() / "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
    model.write_bytes(b"GGUF" + b"\x00" * 16)
    mmproj.write_bytes(b"GGUF" + b"\x00" * 16)

    monkeypatch.setattr(lr, "engine_state_path",
                        lambda: tmp_path / "engine_state.json")
    lr.LlamaRuntime().stop()
    assert model.exists() and mmproj.exists(), "stop() 不得删除模型文件"

    # 显式删除动作（设置页按钮走这里）才移除文件
    from acouscope.ui.widgets import ai_interpret as ai
    from acouscope.ai import model_recommend as mr
    entry = next(e for e in mr.gguf_catalog()
                 if e.model_id == "qwen2.5-vl-3b-instruct-q4_k_m")
    assert ai.delete_entry(entry) is True
    assert not model.exists() and not mmproj.exists()


@pytest.fixture
def fake_models(monkeypatch, tmp_path):
    """模型沙盒目录 → tmp（不触碰真实用户目录）。"""
    monkeypatch.setattr(lr, "models_dir", lambda: tmp_path)
    return tmp_path


# ----------------------------------------------------------------------
# 2. 启动清理：陈旧实例（伪造 engine_state.json）
# ----------------------------------------------------------------------

def test_stale_entry_outside_app_dir_is_never_killed(monkeypatch, tmp_path):
    """伪造状态文件指向**非本应用目录**的进程 → 三项校验不通过 → 不得终止。"""
    monkeypatch.setattr(lr, "engine_state_path",
                        lambda: tmp_path / "engine_state.json")
    proc = subprocess.Popen(["/bin/sleep", "30"])
    try:
        state = {"kind": "llama_cpp", "pid": proc.pid, "port": 59999,
                 "exe_path": lr._exe_path_of(proc.pid) or "/usr/bin/sleep"}
        assert not lr.is_app_owned_exe(state["exe_path"]), "假进程不应被判为本应用"
        killed = lr.cleanup_stale_engines(
            state, port_pids_fn=lambda port: {proc.pid})
        assert killed == []
        assert proc.poll() is None, "外部引擎绝不能被误杀"
    finally:
        proc.terminate()
        proc.wait(5)


def test_stale_entry_inside_app_dir_is_reaped(monkeypatch, tmp_path):
    """伪造状态文件指向本应用资源目录内的受控子进程 → 应终止并清状态文件。"""
    state_path = tmp_path / "engine_state.json"
    monkeypatch.setattr(lr, "engine_state_path", lambda: state_path)
    proc = subprocess.Popen(["/bin/sleep", "30"])
    try:
        exe = lr._exe_path_of(proc.pid) or "/bin/sleep"
        # 把该进程所在目录视为「本应用资源目录」（真实判定函数 is_app_owned_exe）
        monkeypatch.setattr(lr, "_app_resource_roots",
                            lambda: (Path(exe).parent,))
        assert lr.is_app_owned_exe(exe) is True
        state = {"kind": "llama_cpp", "pid": proc.pid, "port": 59999,
                 "exe_path": exe}
        state_path.write_text(json.dumps(state), encoding="utf-8")

        killed = lr.cleanup_stale_engines(
            port_pids_fn=lambda port: {proc.pid}, kill_fn=lr._kill_pid)
        assert killed == [proc.pid]
        # 子进程被终止后仍是僵尸（未 wait 前 os.kill(pid,0) 仍成功）→ 回收后确认
        proc.wait(timeout=8)
        assert proc.returncode is not None, "陈旧受管实例应被终止"
        assert not state_path.exists(), "清理后必须删除状态文件"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(5)


@pytest.mark.parametrize("broken", [
    {"pid": 0, "port": 59999, "exe_path": "/Applications/ollama"},
    {"pid": 4242, "port": 0, "exe_path": "/Applications/ollama"},
    {"pid": 4242, "port": 59999, "exe_path": ""},
])
def test_stale_entry_partial_match_not_reaped(monkeypatch, tmp_path, broken):
    """三项校验任一不符 → 不得杀（① PID ② 端口归属 ③ exe 属本应用）。"""
    state_path = tmp_path / "engine_state.json"
    state_path.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(lr, "engine_state_path", lambda: state_path)
    calls = []
    killed = lr.cleanup_stale_engines(
        alive_fn=lambda pid: True, exe_fn=lambda pid: "/Applications/ollama",
        port_pids_fn=lambda port: {4242}, kill_fn=calls.append)
    assert killed == [] and calls == []
    assert not state_path.exists()      # 状态文件仍被清（避免反复判定）


def test_stale_entry_missing_pid_not_alive_not_reaped(monkeypatch, tmp_path):
    state_path = tmp_path / "engine_state.json"
    state_path.write_text(json.dumps(
        {"pid": 999999, "port": 1, "exe_path": "/tmp/llama-server"}),
        encoding="utf-8")
    monkeypatch.setattr(lr, "engine_state_path", lambda: state_path)
    calls = []
    killed = lr.cleanup_stale_engines(
        alive_fn=lambda pid: False, exe_fn=lambda pid: None,
        port_pids_fn=lambda port: set(), kill_fn=calls.append)
    assert killed == [] and calls == []


def test_cleanup_without_state_file_is_safe(monkeypatch, tmp_path):
    """无状态文件（首次启动）→ 无操作、绝不抛。"""
    monkeypatch.setattr(lr, "engine_state_path",
                        lambda: tmp_path / "nope.json")
    assert lr.cleanup_stale_engines() == []
    assert lr.read_engine_state() is None


def test_engine_state_file_roundtrip_and_path(monkeypatch, tmp_path):
    """状态文件写/读/清 + 路径落在应用数据目录（kind/pid/port/exe_path）。"""
    state_path = tmp_path / "engine_state.json"
    monkeypatch.setattr(lr, "engine_state_path", lambda: state_path)
    lr.write_engine_state("llama_cpp", 1234, 5678, "/app/resources/llama-server")
    data = lr.read_engine_state()
    assert data["kind"] == "llama_cpp" and data["pid"] == 1234
    assert data["port"] == 5678 and data["exe_path"].endswith("llama-server")
    assert "started_at" in data
    lr.clear_engine_state()
    assert not state_path.exists() and lr.read_engine_state() is None


def test_engine_state_path_is_in_data_dir(tmp_path, monkeypatch):
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    assert lr.engine_state_path() == tmp_path / "engine_state.json"


# ----------------------------------------------------------------------
# 3. 归属判定 / 端口归属（禁误杀的依据）
# ----------------------------------------------------------------------

def test_is_app_owned_exe_rules():
    assert lr.is_app_owned_exe("") is False
    assert lr.is_app_owned_exe(None) is False
    assert lr.is_app_owned_exe("/opt/homebrew/bin/llama-server") is False
    assert lr.is_app_owned_exe("/usr/local/bin/ollama") is False
    # 本应用资源目录内的二进制 → True（dev 形态：<包根>/resources/bin/...）
    assert lr.is_app_owned_exe(lr._DEV_LLAMA_BIN) is True


def test_port_owner_lookup_never_raises(monkeypatch):
    monkeypatch.setattr(lr, "_run", lambda argv: None)
    assert lr._port_owner_pids(59999) == set()
    assert lr._port_owner_pids(0) == set()


def test_serve_args_supports_mmproj_position():
    """§4：视觉塔参数位置固定（纯函数断言 argv，禁真起进程）。"""
    assert lr._serve_args("bin", "m.gguf", 1, 2) == [
        "bin", "-m", "m.gguf", "--host", "127.0.0.1", "--port", "1",
        "--ctx-size", "2",
    ]
    argv = lr._serve_args("bin", "m.gguf", 1, 2, "/x/mmproj.gguf")
    assert argv[-2:] == ["--mmproj", "/x/mmproj.gguf"]
    assert argv.index("--mmproj") > argv.index("--ctx-size")


def test_mmproj_autodetect_by_catalog(monkeypatch, tmp_path):
    """start() 侧自动定位同目录视觉塔：文件存在 → argv 带 --mmproj。"""
    from acouscope.ai import llama_models

    info = llama_models.GGUF_MODELS[0]
    (tmp_path / info.filename).write_bytes(b"GGUF")
    assert lr._mmproj_for(tmp_path / info.filename) is None   # mmproj 未下载
    mm = tmp_path / info.mmproj.filename
    mm.write_bytes(b"GGUF")
    assert lr._mmproj_for(tmp_path / info.filename) == mm
    # 纯文本/未知名字 → None（不臆造视觉塔）
    assert lr._mmproj_for(tmp_path / "unknown.gguf") is None
