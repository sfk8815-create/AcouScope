# SPDX-License-Identifier: GPL-3.0-only
"""T-904: 孤儿 worker 进程根治测试（L1 conftest autouse 兜底 + L2 __del__ 析构兜底）。

铁律（任务书）：
- offscreen 全程；禁 MainWindow.show()/QDialog
- env=1 + EchoBackend（无模型依赖）触发真实 spawn
- 有界等待（deadline 轮询），禁 sleep 裸等长循环
"""
import gc
import sys
import time

sys.path.insert(0, "src")

import numpy as np
import pytest

from acouscope.analysis.worker import protocol as wproto
from acouscope.analysis.worker.proxy import WorkerProxy


def _set_worker_env(monkeypatch, value):
    """设置/移除 worker 开关 env。"""
    if value is None:
        monkeypatch.delenv(wproto.ENV_WORKER, raising=False)
    else:
        monkeypatch.setenv(wproto.ENV_WORKER, value)


def _wait_until_exit(proc, timeout_s):
    """有界等待子进程退出（deadline 轮询，步长 50ms）；返回 True=已退出。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return proc.poll() is not None


# ---------------------------------------------------------------------------
# ① L2 析构兜底：未 close 的 proxy 被 GC → __del__ 补 close → 子进程退出
# ---------------------------------------------------------------------------

def test_del_reclaims_spawned_worker(monkeypatch):
    """构造 WorkerProxy("EchoBackend") 并走最小公开路径（env=1 下 detect 触发
    _ensure_process spawn）→ 不 close → del + gc.collect() → 子进程退出
    （proc.poll() 非 None，有界等待 ≤5s；CI/offscreen 下允许放宽至 10s）。

    依赖链（T-904 实测 2026-09-07）：
      a) L2' hb 线程弱引用化（proxy.py）：废弃 proxy 引用计数可归零；
      b) conftest L1 登记为 weakref（不托住引用计数）；
      c) del proxy → finalize 回调（先）/ __del__（后）兜底 close()。
    任一环节缺失本例即失败（历史根因：hb 线程强持 proxy 成 GC 根）。"""
    _set_worker_env(monkeypatch, "1")
    proxy = WorkerProxy("EchoBackend")
    sig = np.zeros(1600, dtype=np.float64)
    proxy.detect(sig, 16000.0)  # 公开路径：spawn + Echo roundtrip
    assert proxy._proc is not None and proxy._proc.poll() is None
    proc = proxy._proc
    pid = proc.pid
    assert pid > 0

    del proxy  # 不 close，触发 CPython 引用计数 GC → __del__
    gc.collect()  # 兜底（确保无循环引用残留场景下也触发）

    assert _wait_until_exit(proc, 5.0), f"析构兜底未在 5s 内使子进程 {pid} 退出"


def test_del_idempotent_after_explicit_close(monkeypatch):
    """已 close 的 proxy 被 GC → __del__ 无存活 _proc → no-op 不抛。"""
    _set_worker_env(monkeypatch, "1")
    proxy = WorkerProxy("EchoBackend")
    sig = np.zeros(1600, dtype=np.float64)
    proxy.detect(sig, 16000.0)
    assert proxy._proc is not None
    proxy.close()
    assert proxy._proc is None
    del proxy  # __del__ 应 no-op（_proc 已 None），不抛
    gc.collect()


# ---------------------------------------------------------------------------
# ② L1 conftest 兜底：registry 捕获 + teardown 后 _proc 归 None
# ---------------------------------------------------------------------------

def _count_worker_subprocesses():
    """psutil 不在铁律依赖内 → 用 pgrep 统计 worker.server 子进程数（本机同树）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["pgrep", "-fl", "worker.server"],
            capture_output=True, text=True, timeout=5.0,
        )
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        return len(lines)
    except Exception:
        return -1


def test_conftest_registry_captures_and_teardown_closes(monkeypatch, request):
    """模拟 conftest autouse 兜底链路（测试体内自模拟，因下一测试的 fixture
    无法感知本测试内的实例）：
      1) 创建 proxy 走公开路径 spawn（不 close）；
      2) 断言 registry（本 fixture 的 _tracked 等价物）已捕获该实例；
      3) 执行 fixture teardown 等价的回收动作；
      4) 断言 _proc 归 None（子进程已收尾）+ worker 子进程计数回落。
    注：真实 conftest autouse 兜底对【本测试自身未 close 的实例】同样生效——
    本例显式回收后 teardown 为 no-op（_proc 已 None），双层互不冲突。
    """
    _set_worker_env(monkeypatch, "1")
    from acouscope.analysis.worker.proxy import WorkerProxy as _WP

    # —— 自模拟 conftest registry（tracked 列表 + 包装 __init__）——
    _tracked: list = []
    _orig_init = _WP.__init__

    def _tracked_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        _tracked.append(self)

    monkeypatch.setattr(_WP, "__init__", _tracked_init)

    before_children = _count_worker_subprocesses()
    proxy = _WP("EchoBackend")
    sig = np.zeros(1600, dtype=np.float64)
    proxy.detect(sig, 16000.0)  # spawn，不 close
    assert proxy._proc is not None and proxy._proc.poll() is None

    # ②-1 registry 已捕获该实例
    assert proxy in _tracked, "registry 未捕获本测试内创建的 WorkerProxy 实例"
    assert len(_tracked) == 1  # 禁跨测试泄漏：本测试内仅新建 1 个

    # ②-2 fixture teardown 等价回收（吞异常 + 计数，与 conftest 实现同语义）
    reclaimed = 0
    for p in _tracked:
        try:
            if getattr(p, "_proc", None) is not None:
                p.close()
                reclaimed += 1
        except Exception:
            pass
    assert reclaimed == 1

    # ②-3 teardown 后 _proc 归 None（子进程已收尾）
    assert proxy._proc is None

    # ②-4 进程计数回落（有界等待子进程退出）
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        after = _count_worker_subprocesses()
        if before_children < 0:  # pgrep 不可用：跳过计数断言
            break
        if after <= before_children:
            break
        time.sleep(0.1)
    else:
        pytest.fail(
            f"worker 子进程计数未回落: before={before_children} after={after}"
        )
    del proxy
    gc.collect()


# ---------------------------------------------------------------------------
# ③ 正常 close 幂等：close 后 teardown 再 close 不抛
# ---------------------------------------------------------------------------

def test_close_then_teardown_close_no_raise(monkeypatch):
    """显式 close 后，conftest teardown 路径（_proc is None → 跳过；
    以及强制二次 close()）均安全不抛（close 幂等）。"""
    _set_worker_env(monkeypatch, "1")
    proxy = WorkerProxy("EchoBackend")
    sig = np.zeros(1600, dtype=np.float64)
    proxy.detect(sig, 16000.0)
    proc = proxy._proc
    assert proc is not None

    proxy.close()
    assert proxy._proc is None
    # teardown 路径①：_proc 已 None → 跳过 close（conftest 语义）
    if getattr(proxy, "_proc", None) is not None:
        proxy.close()
    # teardown 路径②：强制二次 close()（_shutdown_locked 幂等 no-op）
    proxy.close()
    # 从未 spawn 的 proxy close 亦安全（无子进程场景）
    bare = WorkerProxy("EchoBackend")
    bare.close()
    bare.close()
    assert _wait_until_exit(proc, 10.0)  # 显式 close 后子进程最终退出
    del proxy, bare
    gc.collect()
