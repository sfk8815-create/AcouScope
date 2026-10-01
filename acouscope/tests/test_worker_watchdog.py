# SPDX-License-Identifier: GPL-3.0-only
"""T-902b: 后端接线 + watchdog（AT-1006）测试。

铁律（任务书）：
- 测试严禁 MainWindow.show()/QDialog；主进程存活断言用
  kill/respawn 前后同一 QApplication 实例存活（无需 MainWindow）
- watchdog 测试全部 env=1 + EchoBackend（无模型依赖）
- watchdog 状态机：heartbeat 2s/5s（可注入缩短）→ 死亡自动 respawn 一次
  （单 detect 调用至多一次 spawn）→ 连续 2 次失败 → 本会话 fallback
  直连（logging，非模态，env 语义不变）
"""
import os
import signal as _sig
import sys
import time

sys.path.insert(0, "src")

import numpy as np
import pytest

from acouscope.analysis.worker import protocol as wproto
from acouscope.analysis.worker.proxy import WorkerProxy
from acouscope.analysis.worker.routing import (
    _get_session_proxy,
    route,
    route_or_detect,
)
from acouscope.analysis.worker.server import EchoBackend


def _set_worker_env(monkeypatch, value):
    """设置/移除 worker 开关 env。"""
    if value is None:
        monkeypatch.delenv(wproto.ENV_WORKER, raising=False)
    else:
        monkeypatch.setenv(wproto.ENV_WORKER, value)


def _make_qapp():
    """主 qapp（离屏）：遵循既有测试惯例（test_spectrogram3d）：
    QApplication.instance() or QApplication([])。返回实例供前后同一性断言。"""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _sig_of(n=8000):
    return np.zeros(n, dtype=np.float64)


def _sabotage_send(proxy, orig_send):
    """respawn 窗口内再杀：包装 _send_detect，发送前 SIGKILL 刚 spawn 的
    子进程 → 本次 detect 必然失败（send 缓冲成功则 recv 遇 ECONNRESET/EOF，
    两种路径都归一为 RuntimeError("worker ... lost")）。"""
    def sabotage(req, rid):
        p = proxy._proc
        if p is not None and p.poll() is None:
            try:
                os.kill(p.pid, _sig.SIGKILL)
            except ProcessLookupError:
                pass
        return orig_send(req, rid)
    return sabotage


class _DirectSpy:
    """进程内直连 spy 后端（验证 env=0 直连路径与 fallback 后行为）。"""

    name = "DirectSpy"
    is_streaming = False

    def __init__(self):
        self.calls = 0

    def detect(self, signal, sr, fmin=40.0, fmax=2000.0, progress_cb=None):
        self.calls += 1
        from acouscope.analysis.pitch import PitchTrack

        n = np.asarray(signal, dtype=np.float64).ravel().size
        return PitchTrack(
            times=np.arange(n, dtype=np.float64) / float(sr),
            f0_hz=np.full(n, 110.0, dtype=np.float64),
            confidence=np.ones(n, dtype=np.float64),
            fmin=fmin,
            fmax=fmax,
            cent_ref=440.0,
        )

    def is_available(self):
        return True


class _EchoShim:
    """模拟生产接线形态：detect 首行 route_or_detect + 直连兜底
    （与 swift_f0.py/rmvpe.py 接法同构；直连用进程内 EchoBackend）。"""

    name = "EchoBackend"
    is_streaming = False

    def __init__(self):
        self._direct = EchoBackend()

    def detect(self, signal, sr, fmin=40.0, fmax=2000.0, progress_cb=None):
        routed = route_or_detect(
            "EchoBackend", self, signal, sr, fmin, fmax, progress_cb
        )
        if routed is not None:
            return routed
        out = self._direct.detect(
            signal, sr, fmin=fmin, fmax=fmax, progress_cb=progress_cb
        )
        return out[0] if isinstance(out, tuple) else out


# ---------------------------------------------------------------------------
# B1: kill worker → 下次 detect 自动 respawn → 主 qapp 存活（AT-1006 ②）
# ---------------------------------------------------------------------------

def test_kill_worker_respawn(monkeypatch):
    """① detect 成功 → client 侧 kill 子进程 → 再次 detect 自动 respawn
    成功 → 主 qapp 存活（kill/respawn 前后同一 QApplication 实例存活，
    无需 MainWindow）。"""
    _set_worker_env(monkeypatch, "1")
    from PyQt6.QtWidgets import QApplication

    app = _make_qapp()  # 主 qapp（offscreen）
    sig = _sig_of()
    proxy = WorkerProxy("EchoBackend")
    try:
        t1 = proxy.detect(sig, 16000.0)
        assert np.allclose(t1.f0_hz, 220.0)
        gen1, pid1 = proxy._proc_gen, proxy._proc.pid

        # client 侧 kill（模拟 worker OOM/崩溃，主进程无感）
        proxy._kill_for_test()
        assert proxy._proc is None

        # 下次 detect 自动 respawn 一次（无用户干预）
        t2 = proxy.detect(sig, 16000.0)
        assert np.allclose(t2.f0_hz, 220.0)
        assert proxy._proc is not None and proxy._proc.poll() is None
        assert proxy._proc.pid != pid1        # 新子进程
        assert proxy._proc_gen == gen1 + 1    # 代次 +1（respawn 一次）
        assert proxy._consecutive_fails == 0  # 成功路径无失败记账

        # AT-1006：主进程（含同一 qapp 实例）存活且可用
        assert QApplication.instance() is app
    finally:
        proxy.close()


# ---------------------------------------------------------------------------
# B2: 连续 2 次 worker 失败 → 本会话 fallback 直连（AT-1006 ③④）
# ---------------------------------------------------------------------------

def test_double_fail_fallback(monkeypatch, caplog):
    """连续两次强制 worker 失败（kill + respawn 窗口内再杀）→ 触发
    fallback 的该次 detect 经直连 EchoBackend 成功；caplog 含
    'fallback' + backend 名；fallback 后 env 语义不变（恒直连）。"""
    _set_worker_env(monkeypatch, "1")
    import logging

    sig = _sig_of()
    shim = _EchoShim()
    proxy = _get_session_proxy("EchoBackend")
    try:
        # #1 worker 路径成功
        t1 = shim.detect(sig, 16000.0)
        assert np.allclose(t1.f0_hz, 220.0)

        # kill → #2 自动 respawn 成功（尚无失败）
        proxy._kill_for_test()
        t2 = shim.detect(sig, 16000.0)
        assert np.allclose(t2.f0_hz, 220.0)
        assert not proxy.is_fallback_active()

        # 连续失败注入：#3/#4 的 respawn 窗口内再杀
        proxy._send_detect = _sabotage_send(proxy, proxy._send_detect)

        # #3：worker 失败 ①（向调用方传播——此时尚未达 fallback 阈值）
        with pytest.raises(RuntimeError):
            shim.detect(sig, 16000.0)
        assert proxy._consecutive_fails == 1
        assert not proxy.is_fallback_active()

        # #4：worker 失败 ② → 触发 fallback → 本次调用落直连成功
        with caplog.at_level(logging.WARNING, logger="acouscope.analysis"):
            t4 = shim.detect(sig, 16000.0)
        assert np.allclose(t4.f0_hz, 220.0)  # 直连 EchoBackend 结果
        assert proxy.is_fallback_active()
        assert any("fallback" in r.message for r in caplog.records)
        assert any(
            "EchoBackend" in r.message and "fallback" in r.message
            for r in caplog.records
        )

        # ④ fallback 后 env 语义不变：env 仍为 1，本会话恒直连（不自动改回）
        assert os.environ[wproto.ENV_WORKER] == "1"
        t5 = shim.detect(sig, 16000.0)
        assert np.allclose(t5.f0_hz, 220.0)
        assert proxy.is_fallback_active()  # 标志恒真，不自动改回
    finally:
        proxy.close()
        # 清理会话注册表（防跨用例污染）
        import acouscope.analysis.worker.routing as routing

        routing._proxy_registry.pop("EchoBackend", None)


# ---------------------------------------------------------------------------
# B3: env=0 → route_or_detect 返回 None，detect 走直连（零行为变化）
# ---------------------------------------------------------------------------

def test_env_off_zero_change(monkeypatch):
    """env=0：route_or_detect 返回 None、detect 走直连（monkeypatch env
    + 直连 spy）；未 spawn、未建会话代理。"""
    _set_worker_env(monkeypatch, "0")
    import acouscope.analysis.worker.routing as routing

    # 清空会话注册表，断言 env=0 路径绝不创建 WorkerProxy
    saved = routing._proxy_registry.pop("EchoBackend", None)
    spy = _DirectSpy()
    sig = _sig_of()
    try:
        assert route_or_detect("EchoBackend", spy, sig, 16000.0) is None
        assert spy.calls == 0            # route_or_detect 不代调直连
        assert "EchoBackend" not in routing._proxy_registry  # 未 spawn

        # 生产接法同构：首行 routed 为 None → 继续直连
        routed = route_or_detect(
            "SwiftF0Backend", spy, sig, 16000.0, 55.0, 1500.0, None
        )
        assert routed is None
        track = spy.detect(sig, 16000.0)  # 直连兜底（接口稳定：同签名）
        assert spy.calls == 1
        assert np.allclose(track.f0_hz, 110.0)
        assert track.fmin == 40.0 and track.fmax == 2000.0
    finally:
        if saved is not None:
            routing._proxy_registry["EchoBackend"] = saved

    # 缺省 env（未设置）同样直连
    _set_worker_env(monkeypatch, None)
    assert route_or_detect("RMVPEBackend", spy, sig, 16000.0) is None


# ---------------------------------------------------------------------------
# B4: heartbeat 超时置 dead（BlackHole 无响应 server，注入缩短超时）
# ---------------------------------------------------------------------------

def test_heartbeat_timeout_marks_dead(monkeypatch):
    """伪造无响应 server（socket 收 BlackHole：accept 不处理 → PING 无
    PONG）→ heartbeat 超时（注入 0.5s，避免真实 5s 等待）置 dead。"""
    _set_worker_env(monkeypatch, "1")
    import socket

    proxy = WorkerProxy("EchoBackend")
    try:
        # BlackHole：监听但永不 accept/服务（send 进内核缓冲、recv 恒超时）
        bh = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        bh.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bh.bind(("127.0.0.1", 0))
        bh.listen(8)
        port = bh.getsockname()[1]

        # 注入假子进程句柄：poll() 恒 None（进程"活着"但不响应）
        class _FakeProc:
            def poll(self):
                return None

            def kill(self):
                pass

            def wait(self, timeout=None):
                pass

        conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        conn.settimeout(None)
        fobj = conn.makefile("rb")
        proxy._proc = _FakeProc()
        proxy._conn = conn
        proxy._reader = wproto.LineReader(fobj)

        # 缩短超时（契约 B.4：避免真实 5s 等待）
        proxy._wd(interval=0.2, timeout=0.5)
        proxy._start_heartbeat_locked()

        deadline = time.monotonic() + 4.0
        while not proxy._watchdog_marked_dead():
            assert time.monotonic() < deadline, (
                "heartbeat 超时判定未在 4s 内触发"
            )
            time.sleep(0.05)
        assert proxy._hb_dead is True
        assert proxy._last_pong_at is not None  # 曾初始化、再无 PONG 刷新
    finally:
        proxy._wd(interval=2.0, timeout=5.0)
        proxy.close()
    bh.close()


# ---------------------------------------------------------------------------
# 附加：route() 既有语义不回归（env 门）
# ---------------------------------------------------------------------------

def test_route_factory_semantics_unchanged(monkeypatch):
    """route(backend, factory) 纯函数语义保持（T-902a 既有行为）。"""
    _set_worker_env(monkeypatch, "0")
    spy = _DirectSpy()
    got = route("EchoBackend", lambda: spy)
    assert got is spy

    _set_worker_env(monkeypatch, "1")
    got2 = route("EchoBackend", lambda: _DirectSpy())
    assert isinstance(got2, WorkerProxy)
    assert got2.backend_name == "EchoBackend"


# ---------------------------------------------------------------------------
# T-1030：生产默认阈值 + 注入路径守卫（防"改默认时把注入也写死"）
# ---------------------------------------------------------------------------

def test_wd_default_timeout_is_15():
    """T-1030：生产默认 _wd_timeout 恰为 15.0（未经 _wd 注入）。"""
    proxy = WorkerProxy("EchoBackend")
    assert proxy._wd_timeout == 15.0


def test_wd_injection_still_overrides_default():
    """T-1030：_wd(timeout=...) 注入路径未被硬编码（改默认时仍可覆盖）。"""
    proxy = WorkerProxy("EchoBackend")
    proxy._wd(timeout=0.5)
    assert proxy._wd_timeout == 0.5


# ---------------------------------------------------------------------------
# T-1070 / IM-25 α：久 detect 不误判死 × 真 hang 照判死（双向守卫）
# 全部假 socket/脚本 reader 注入，不 spawn 真 ML worker（W5.1）。
# ---------------------------------------------------------------------------

# 注入档：interval 0.1s / timeout 0.5s；久 detect 持锁 0.8s（> 一整档）
_T1070_INTERVAL = 0.1
_T1070_TIMEOUT = 0.5
_T1070_HOLD = 0.8


class _ScriptedReader:
    """脚本化 LineReader（无 worker 进程）：

    首轮 read_message 先 sleep(hold) 模拟 detect 全程持锁，再吐 RESULT/
    ERROR；此后（heartbeat 探活 PING）恒抛 TimeoutError —— 等价 BlackHole
    （PING 无 PONG），判死仅取决于 _last_pong_at 新鲜度。
    """

    def __init__(self, hold, rid, *, error=False):
        self._hold = hold
        self._rid = rid
        self._error = error
        self._calls = 0

    def read_message(self):
        if self._calls == 0:
            self._calls += 1
            time.sleep(self._hold)
            if self._error:
                return {"type": wproto.MSG_ERROR, "rid": self._rid,
                        "message": "scripted failure"}
            payload = {
                "track": {"name": "acw_o_t1070", "shape": [1],
                          "dtype": "float64"},
                "counts": [1, 1, 1], "backend": "EchoBackend",
                "sr": 16000.0, "fmin": 40.0, "fmax": 2000.0,
            }
            return {"type": wproto.MSG_RESULT, "rid": self._rid,
                    "echo_amp": None, "payload": payload}
        raise TimeoutError("scripted blackhole: PING never answered")


def _inject_scripted_proxy(monkeypatch, reader):
    """BlackHole 假 server + 假 proc + 脚本 reader 注入（同 B4 法），
    _ensure_process 因 proc/conn 在场且未判死而短路 ⇒ 绝不 spawn。"""
    import socket

    _set_worker_env(monkeypatch, "1")
    proxy = WorkerProxy("EchoBackend")
    bh = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bh.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bh.bind(("127.0.0.1", 0))
    bh.listen(8)
    port = bh.getsockname()[1]

    class _FakeProc:
        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    conn.settimeout(None)
    proxy._proc = _FakeProc()
    proxy._conn = conn
    proxy._reader = reader
    proxy._wd(interval=_T1070_INTERVAL, timeout=_T1070_TIMEOUT)
    proxy._start_heartbeat_locked()
    # 收发全走脚本：不真写 socket、不 attach 结果 shm
    proxy._send_detect = lambda req, rid: None
    proxy._read_result_shm = lambda payload: _SENTINEL
    return proxy, bh


_SENTINEL = object()


def _wait_dead(proxy, deadline_s=3.0):
    deadline = time.monotonic() + deadline_s
    while not proxy._watchdog_marked_dead():
        assert time.monotonic() < deadline, "预期判死未在窗内触发"
        time.sleep(0.02)


def _close_proxy(proxy, bh):
    proxy._wd(interval=2.0, timeout=15.0)
    proxy.close()
    bh.close()


def test_im25_long_detect_success_not_marked_dead(monkeypatch):
    """正向（α）：久 detect 持锁 0.8s（> timeout 0.5s）成功返回后，
    _hb_dead 须 False；且 _last_pong_at 被刷到成功时刻（持锁·释锁前）。
    R-2 采样纪律：释锁即采，并仅在随后 <1 个 _wd_timeout 窗内短采样
    （reader 此后不答 PONG，越窗自然判死不污染本断言）。"""
    reader = _ScriptedReader(_T1070_HOLD, rid="r1")
    proxy, bh = _inject_scripted_proxy(monkeypatch, reader)
    try:
        t_before = time.monotonic()
        out = proxy.detect(_sig_of(), 16000.0)
        t_after = time.monotonic()
        assert out is _SENTINEL  # 走完整唯一成功路径（清零→α→return）
        # α 落点证据：pong 恰在本次 detect 窗口内被刷新
        assert proxy._last_pong_at is not None
        assert t_before <= proxy._last_pong_at <= t_after
        # 释锁即采（≤1 窗）：久 detect 未被误判死
        assert proxy._watchdog_marked_dead() is False
        # 窗内短采样（0.2s < 0.5s 档）：判死窗确被成功时刻后移一档
        observe_end = time.monotonic() + (_T1070_TIMEOUT - 0.3)
        while time.monotonic() < observe_end:
            assert proxy._watchdog_marked_dead() is False
            time.sleep(0.02)
    finally:
        _close_proxy(proxy, bh)


def test_im25_without_alpha_long_detect_still_marks_dead(monkeypatch):
    """负对照（仿 T-1069 R-6）：剥除 α（成功 return 前不刷
    _last_pong_at，逐字等价改前）⇒ 同一久 detect 成功后照判死，
    证明夹具可判别、正例非侥幸。"""
    orig_recv = WorkerProxy._recv_result

    def recv_no_alpha(self, req, in_shm, in_name, rid, progress_cb):
        # 本方法仅在 detect 的 with self._lock（:281）锁链上被调：
        # heartbeat 抢不到锁，无并发写，直接读/复旧值即可。
        before = self._last_pong_at
        try:
            return orig_recv(self, req, in_shm, in_name, rid, progress_cb)
        finally:
            self._last_pong_at = before  # α 效果归零，余路逐字不变

    monkeypatch.setattr(WorkerProxy, "_recv_result", recv_no_alpha)
    reader = _ScriptedReader(_T1070_HOLD, rid="r2")
    proxy, bh = _inject_scripted_proxy(monkeypatch, reader)
    try:
        out = proxy.detect(_sig_of(), 16000.0)
        assert out is _SENTINEL  # detect 本身成功——判死纯因成功未刷 pong
        _wait_dead(proxy)
        assert proxy._hb_dead is True
    finally:
        _close_proxy(proxy, bh)


def test_im25_failed_detect_does_not_refresh_pong(monkeypatch):
    """失败路径守卫：detect 收 ERROR（:372-375 raise）不刷
    _last_pong_at（α 行失败不可达）⇒ 不误延命；失败仍记账一次。
    （respawn 路径在 _ensure_process，不经 _recv_result，α 不可达。）"""
    reader = _ScriptedReader(0.05, rid="r3", error=True)
    proxy, bh = _inject_scripted_proxy(monkeypatch, reader)
    try:
        with proxy._lock:  # 预置陈旧 pong：已超一整档、本该判死
            proxy._last_pong_at = time.monotonic() - 10.0
        pong_before = proxy._last_pong_at
        with pytest.raises(RuntimeError, match="worker detect failed"):
            proxy.detect(_sig_of(), 16000.0)
        assert proxy._last_pong_at == pong_before  # 失败未续钟（逐字相等）
        assert proxy._consecutive_fails == 1
        _wait_dead(proxy)  # 未被误延命：释锁后照常判死
        assert proxy._hb_dead is True
    finally:
        _close_proxy(proxy, bh)
