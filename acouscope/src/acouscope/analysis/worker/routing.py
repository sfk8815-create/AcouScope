# SPDX-License-Identifier: GPL-3.0-only
"""Worker 路由（T-902a 纯函数 + T-902b detect 接线点）。

WORKER_ROUTING_V1 — 后端实例路由开关：

    route(backend_name, factory) -> PitchBackend

- env=0（默认）→ factory()（直连进程内真实后端，不 spawn）
- env=1 → WorkerProxy(backend_name)（子进程隔离）

T-902b 新增 route_or_detect(backend_name, direct_backend, *args)：
SwiftF0/RMVPE detect 首行的唯一合法接线点（接口稳定铁律）：
- env=0（默认，任意非 "1" 值）→ 返回 None（调用方继续直连，零行为变化）
- env=1 → 委托会话级 WorkerProxy(backend_name).detect(*args)（含 watchdog）
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from acouscope.analysis.backends.base import PitchBackend

from . import protocol as proto
from .proxy import WorkerProxy

logger = logging.getLogger(__name__)


def route(backend_name: str, factory: "Callable[[], PitchBackend]",
          env: Optional[dict] = None) -> PitchBackend:
    """按 ACOUSCOPE_ANALYSIS_WORKER 开关路由后端构造。

    Args:
        backend_name: "EchoBackend" | "SwiftF0Backend" | "RMVPEBackend"
        factory: 直连工厂（env=0 时调用，返回进程内真实后端实例）
        env: 测试注入用环境变量映射；缺省取 os.environ

    Returns:
        env=0 → factory()（直连）；env=1 → WorkerProxy(backend_name)
    """
    if proto.is_worker_enabled(env):
        return WorkerProxy(backend_name)
    return factory()


# ---------------------------------------------------------------------------
# T-902b：detect 级路由（两后端 detect 首行的唯一合法触点）
# ---------------------------------------------------------------------------

#: 会话级 WorkerProxy 注册表：同一 backend_name 全程复用同一代理实例，
#: watchdog 状态（失败计数/fallback 标志/已 respawn 代次）才能跨 detect 调用
#: 累积；若每次 detect 新建代理，"连续 2 次失败" 无法跨调用成立。
_proxy_registry: "dict[str, WorkerProxy]" = {}
_registry_lock = threading.Lock()


def _get_session_proxy(backend_name: str) -> WorkerProxy:
    """取（缺失则创建）指定后端的会话级 WorkerProxy（线程安全）。"""
    with _registry_lock:
        p = _proxy_registry.get(backend_name)
        if p is None:
            p = WorkerProxy(backend_name)
            _proxy_registry[backend_name] = p
        return p


def route_or_detect(backend_name: str, direct_backend, *args, **kwargs):
    """detect 路由点（SwiftF0/RMVPE detect 首行调用，接口稳定铁律唯一触点）。

    - env=0（默认，任意非 "1" 值）→ 返回 None：调用方继续进程内直连检测，
      行为逐字节不变（本路径不构造 WorkerProxy、不 spawn、不触碰任何
      watchdog 状态）
    - env=1 → 委托会话级 WorkerProxy(backend_name).detect(*args, **kwargs)
      （含 watchdog：heartbeat 探活 / 死亡自动 respawn 一次 / 连续 2 次
      失败本会话 fallback 直连），返回其结果

    Args:
        backend_name: "SwiftF0Backend" | "RMVPEBackend"
            （"EchoBackend" 仅测试可达，生产两后端不注入）
        direct_backend: 进程内真实后端实例（env=0 时由调用方直接使用；
            env=1 路径不使用该实例，仅签名占位——对调用方透明）
        *args/**kwargs: detect 参数原样透传
            （signal, sr, fmin=40.0, fmax=2000.0, progress_cb=None）

    Returns:
        env=0 → None；env=1 → PitchTrack（proxy 结果）
        env=1 但本会话已 fallback 直连 → None（调用方走直连，env 语义不变：
        不自动改回 worker，本会话内每次 detect 均经此判定）
    """
    if not proto.is_worker_enabled():
        return None
    proxy = _get_session_proxy(backend_name)
    if proxy.is_fallback_active():
        logger.warning(
            "worker fallback active, using in-process direct: backend=%s",
            backend_name,
        )
        return None
    try:
        return proxy.detect(*args, **kwargs)
    except Exception:
        # 本次失败恰好触发 fallback（连续第 2 次失败，proxy 内已置 _fallback
        # 并记日志）→ 本调用不再向调用方抛 worker 异常，改落直连（返回 None
        # 使调用方 detect 继续进程内推理）。这是 AT-1006 主进程免疫的关键：
        # 连续 worker 失败不击穿用户 detect 调用。
        if proxy.is_fallback_active():
            logger.warning(
                "worker fallback tripped on this call, falling to in-process "
                "direct: backend=%s",
                backend_name,
            )
            return None
        raise
