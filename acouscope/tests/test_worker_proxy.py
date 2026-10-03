# SPDX-License-Identifier: GPL-3.0-only
"""T-902a: analysis/worker 子包测试（协议/路由/回显 roundtrip/进度中继/无 onnx 泄漏）。

铁律（需求说明）：
- 测试严禁 MainWindow.show()/QDialog；worker 测试用 EchoBackend（无模型依赖）
- env 开关：ACOUSECOPE_ANALYSIS_WORKER 默认 OFF；=1 才 spawn 子进程
- 全量回归 env 铁律由外部命令带（TERM/LC_ALL/LANG/QT_QPA_PLATFORM）
"""
import inspect
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest

from acouscope.analysis.backends.base import PitchBackend
from acouscope.analysis.worker import (
    PROTOCOL_VERSION,
    WorkerProxy,
    route,
)
from acouscope.analysis.worker import protocol as wproto


def _set_worker_env(monkeypatch, value):
    """设置/移除 worker 开关 env。"""
    if value is None:
        monkeypatch.delenv(wproto.ENV_WORKER, raising=False)
    else:
        monkeypatch.setenv(wproto.ENV_WORKER, value)


class _DirectBackend:
    """env=0 直连工厂用的进程内哑后端（满足 PitchBackend 结构）。"""

    name = "Direct"
    is_streaming = False

    def __init__(self, marker):
        self.marker = marker

    def detect(self, signal, sr, fmin=40.0, fmax=2000.0, progress_cb=None):
        raise AssertionError("直连后端不应被调用（本测试只验证路由对象）")

    def is_available(self):
        return True


# ---------------------------------------------------------------------------
# B1: 协议一致性（isinstance + 同签名）
# ---------------------------------------------------------------------------

def test_proxy_matches_protocol():
    """WorkerProxy 满足 PitchBackend（runtime_checkable）且 detect 同签名。"""
    proxy = WorkerProxy("SwiftF0Backend")
    assert isinstance(proxy, PitchBackend)
    assert proxy.name == "SwiftF0Backend"
    assert proxy.is_streaming is False  # 深度分析离线（与 SOTA 真实后端一致）

    # detect 签名：参数名/默认值与 base.py PitchBackend.detect 一致
    base_sig = inspect.signature(
        PitchBackend.detect
    )
    proxy_sig = inspect.signature(proxy.detect)
    base_params = {
        k: (v.default, v.annotation) for k, v in base_sig.parameters.items()
        if k != "self"
    }
    proxy_params = {
        k: (v.default, v.annotation) for k, v in proxy_sig.parameters.items()
        if k != "self"
    }
    assert list(proxy_params) == list(base_params) == [
        "signal", "sr", "fmin", "fmax", "progress_cb",
    ]
    for k in base_params:
        assert proxy_params[k][0] == base_params[k][0], f"default mismatch: {k}"
    # 默认值逐字核验
    assert proxy_params["fmin"][0] == 40.0
    assert proxy_params["fmax"][0] == 2000.0
    assert proxy_params["progress_cb"][0] is None

    # is_available 同签名（不实际调用 SwiftF0 的 is_available——实读：真实类
    # __init__ 即载模型会 import onnxruntime，污染 B5 无泄漏断言；Echo 路径
    # 的 is_available 调用在 test_is_available_echo_without_spawn 覆盖）
    assert list(
        k for k in inspect.signature(proxy.is_available).parameters if k != "self"
    ) == []

    # 未知后端名 → ValueError（防御）
    with pytest.raises(ValueError):
        WorkerProxy("NopeBackend")


# ---------------------------------------------------------------------------
# B2: env=0 路由直连（不 spawn）
# ---------------------------------------------------------------------------

def test_routing_env_off(monkeypatch):
    """env=0（默认）：route 返回 factory() 实例（直连不 spawn）。"""
    _set_worker_env(monkeypatch, "0")
    got = route("SwiftF0Backend", lambda: _DirectBackend("off-explicit"))
    assert isinstance(got, _DirectBackend)
    assert not isinstance(got, WorkerProxy)
    assert isinstance(got, PitchBackend)  # 直连对象仍是协议符合者

    # 缺省（未设置 env）同样直连
    _set_worker_env(monkeypatch, None)
    got2 = route("RMVPEBackend", lambda: _DirectBackend("off-default"))
    assert isinstance(got2, _DirectBackend)
    assert not isinstance(got2, WorkerProxy)

    # 非 "1" 的任意值（如 "true"/"2"）一律直连（HARD-RULE 4 口径）
    for bogus in ("true", "2", "yes"):
        _set_worker_env(monkeypatch, bogus)
        got3 = route("EchoBackend", lambda: _DirectBackend("off-bogus"))
        assert isinstance(got3, _DirectBackend), f"bogus env {bogus!r} 应直连"


def test_routing_env_on(monkeypatch):
    """env=1：route 返回 WorkerProxy（本任务不接线，仅验证路由对象）。"""
    _set_worker_env(monkeypatch, "1")
    got = route("EchoBackend", lambda: _DirectBackend("never"))
    assert isinstance(got, WorkerProxy)
    assert got.backend_name == "EchoBackend"
    assert isinstance(got, PitchBackend)


# ---------------------------------------------------------------------------
# B3: Echo roundtrip（env=1，子进程 + SharedMemory）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def echo_proxy():
    """模块级 Echo WorkerProxy（spawn 一次，多个用例复用同一子进程）。"""
    proxy = WorkerProxy("EchoBackend")
    yield proxy
    proxy.close()


def _check_spawned_child(proxy):
    """断言 proxy 背后确有存活子进程（env=1 语义实证）。"""
    assert proxy._proc is not None and proxy._proc.poll() is None, (
        "env=1 应已 spawn 子进程"
    )


def test_worker_echo_roundtrip(monkeypatch, echo_proxy):
    """env=1 + EchoBackend：1s@16k 正弦 → proxy.detect → PitchTrack（f0 常 220）。

    Echo 语义以 server.py 实现为准（测试注释同步）：
      times = arange(n)/sr；f0_hz 全 220.0；confidence 全 1.0；
      "输入信号×2" 语义校验 = RESULT 附属 echo_amp 字段：
        echo_amp 应 == mean(|signal*2|) = 2*mean(|signal|)。
    """
    _set_worker_env(monkeypatch, "1")
    sr = 16000
    n = sr  # 1s @16k
    t = np.arange(n) / sr
    sig = 0.5 * np.sin(2 * np.pi * 440.0 * t)

    track = echo_proxy.detect(sig, sr)
    from acouscope.analysis.pitch import PitchTrack

    assert isinstance(track, PitchTrack)
    _check_spawned_child(echo_proxy)

    # f0 常 220Hz 轨
    assert track.f0_hz.shape == (n,)
    assert np.allclose(track.f0_hz, 220.0)
    # times/confidence 语义
    assert np.allclose(track.times, np.arange(n) / sr)
    assert np.allclose(track.confidence, 1.0)
    assert track.fmin == 40.0 and track.fmax == 2000.0  # 默认参数透传

    # signal×2 语义校验（server 实现为准）：echo_amp == 2*mean(|sig|)
    expected_echo = float(2.0 * np.mean(np.abs(sig)))
    assert track._worker_echo_amp is not None
    assert abs(track._worker_echo_amp - expected_echo) < 1e-9, (
        f"echo_amp={track._worker_echo_amp} expected={expected_echo}"
    )


def test_worker_detect_passes_fmin_fmax(monkeypatch, echo_proxy):
    """fmin/fmax 参数经协议透传到 server 侧（Echo 原样回显于 track 字段）。"""
    _set_worker_env(monkeypatch, "1")
    sr = 16000
    sig = np.zeros(sr // 2, dtype=np.float64)
    track = echo_proxy.detect(sig, sr, fmin=55.0, fmax=1500.0)
    assert track.fmin == 55.0
    assert track.fmax == 1500.0


# ---------------------------------------------------------------------------
# B4: progress_cb 经 PROGRESS 消息中继
# ---------------------------------------------------------------------------

def test_progress_callback_relayed(monkeypatch, echo_proxy):
    """EchoBackend 分 10 段上报 → 主进程 cb 恰收 10 次（0.1..1.0）。"""
    _set_worker_env(monkeypatch, "1")
    sr = 16000
    sig = np.ones(sr // 4, dtype=np.float64)

    got = []

    def cb(value):
        got.append(float(value))

    echo_proxy.detect(sig, sr, progress_cb=cb)
    assert len(got) == 10, f"应收 10 次进度，实收 {len(got)}: {got}"
    assert np.allclose(got, np.linspace(0.1, 1.0, 10))
    # 无 cb 时不报错
    echo_proxy.detect(sig, sr)  # 默认 progress_cb=None


def test_progress_cb_not_called_without_cb(monkeypatch, echo_proxy):
    """无 cb 的 detect 正常完成（PROGRESS 消息被服务端发出、客户端忽略）。"""
    _set_worker_env(monkeypatch, "1")
    track = echo_proxy.detect(np.zeros(1600, dtype=np.float64), 16000.0)
    assert np.allclose(track.f0_hz, 220.0)


# ---------------------------------------------------------------------------
# B5: 无 onnxruntime 泄漏（proxy/server 模块 import 后 sys.modules 无 onnxruntime）
# ---------------------------------------------------------------------------

def _onnx_modules():
    return {m for m in sys.modules if m == "onnxruntime" or m.startswith("onnxruntime.")}


def test_no_onnxruntime_leak():
    """import worker 全部模块不得【新增】onnxruntime（delta 口径，防测试顺序污染）。

    契约 B5 的语义是"worker 模块 import 不触发 onnxruntime 加载"。全量回归中
    其他测试可能已先行 import onnxruntime，故用 before/after delta 断言：
    import worker 模块前后，onnxruntime 相关模块集合不得新增任何条目。
    绝对缺席口径（全新解释器）由锚点 f 独立解释器实测保证。
    """
    # 先清掉 worker 模块自身，确保本次是真正的 import（而非命中缓存）
    for m in list(sys.modules):
        if m == "acouscope.analysis.worker" or m.startswith("acouscope.analysis.worker."):
            del sys.modules[m]

    before = _onnx_modules()
    import acouscope.analysis.worker  # noqa: F401
    import acouscope.analysis.worker.proxy  # noqa: F401
    import acouscope.analysis.worker.server  # noqa: F401
    import acouscope.analysis.worker.routing  # noqa: F401
    import acouscope.analysis.worker.protocol  # noqa: F401

    added = _onnx_modules() - before
    assert not added, f"worker import 新增 onnxruntime 模块: {sorted(added)}"

    # 模块级 API 存在性
    assert hasattr(sys.modules["acouscope.analysis.worker.proxy"], "WorkerProxy")
    assert hasattr(sys.modules["acouscope.analysis.worker.server"], "main")
    assert wproto.PROTOCOL_VERSION == PROTOCOL_VERSION == "1"


# ---------------------------------------------------------------------------
# 附加：env=0 时 detect 不可达（HARD-RULE 4，T-902b 接线前 raise）
# ---------------------------------------------------------------------------

def test_detect_raises_when_env_off(monkeypatch):
    """env=0（默认）：proxy.detect raise RuntimeError("worker disabled")。"""
    _set_worker_env(monkeypatch, None)
    proxy = WorkerProxy("EchoBackend")
    with pytest.raises(RuntimeError, match="worker disabled"):
        proxy.detect(np.zeros(100), 16000.0)
    assert proxy._proc is None  # 未 spawn
    proxy.close()


def test_is_available_echo_without_spawn(monkeypatch):
    """is_available 走进程内（Echo 恒真）且绝不 spawn 子进程。"""
    _set_worker_env(monkeypatch, "1")
    proxy = WorkerProxy("EchoBackend")
    assert proxy.is_available() is True
    assert proxy._proc is None  # is_available 不 spawn
