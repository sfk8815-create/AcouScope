# SPDX-License-Identifier: GPL-3.0-only
"""Worker 同签名代理（T-902a，纯新增零接线）。

WORKER_PROXY_V1 — 主进程侧 WorkerProxy：

- isinstance(WorkerProxy(...), PitchBackend)（runtime_checkable Protocol，
  以 name/is_streaming 属性 + detect/is_available 方法满足结构检查）
- detect/is_available 与 analysis/backends/base.py 的 PitchBackend 同签名
  （参数名/默认值逐一对齐：signal, sr, fmin=40.0, fmax=2000.0, progress_cb=None）
- is_available() 走进程内真实类（不 spawn 子进程）：EchoBackend 内置恒真；
  SwiftF0/RMVPE 动态 import 真实类实例化探测（与 main_window 现有行为同语义。
  注意实读：两真实类 __init__ 即调 _ensure_model()，探测会触发本进程
  onnxruntime 加载——与现状一致，非代理引入）
- detect() 仅 env=1（ACOUSECOPE_ANALYSIS_WORKER=1）时 spawn/复用子进程；
  env=0（默认）raise RuntimeError("worker disabled")——T-902b 接线前不可达
- progress_cb 经 PROGRESS 消息回传，主进程侧调用
- 本模块 import 不触发 onnxruntime（动态 import 只在 is_available/detect
  实际调用时发生）

T-902b 新增 watchdog（AT-1006 主进程免疫 hang/OOM）：
- heartbeat 线程：按 interval 发 PING，超 _wd_timeout 无 PONG → 置 dead（锁内翻转）
- 死亡 → 下次 detect 自动 respawn 一次（_ensure_process 单重生，代次上限）
- 连续 2 次 worker 失败 → 本会话 fallback 直连（logging.warning 记
  backend 名与失败原因摘要；非模态、无 UI；fallback 后 env 语义不变，
  不自动改回）
- 所有 watchdog 状态翻转均在 _lock 内完成（线程安全）

T-904 孤儿 worker 根治（L2/L2'）：
- __del__ 析构兜底：_proc 仍存活则补一次 close()（全程 try、吞异常、
  绝不在解释器 shutdown 期外抛）
- L2' hb 线程弱引用化：_heartbeat_loop 改模块级函数、经 weakref 逐轮
  解析 proxy（线程帧不持 proxy 强引用）。实测（2026-09-07）：原 hb 以
  绑定方法为 target，线程帧/绑定方法均强持 proxy → 废弃 proxy 永不
  回收 → __del__ 永不触发 → 孤儿在“进程退出前”无法自愈。弱引用化后：
  del proxy → 引用计数归零 → __del__ 即时触发 close()（hb 线程下轮
  发现 weakref 已死自行退出，无 UAF：weakref 已死 ⇒ 无其他强引用 ⇒
  对象不可再被使用）。既有语义不变：hb 探活/判死/respawn/fallback
  状态机与 _lock 纪律照旧（唯 _wd 的动态 interval 注入自下次 hb
  重启生效——既有测试注入后均重起 hb，不受影响）。
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
import weakref
from typing import Callable, Optional

import numpy as np

from . import protocol as proto

logger = logging.getLogger(__name__)


def _backend_module(backend_name: str) -> Optional[tuple]:
    """backend 类名 → (模块名, 类名)；EchoBackend 无主进程模块（内置 server）。"""
    if backend_name == "EchoBackend":
        return None
    if backend_name == "SwiftF0Backend":
        return ("acouscope.analysis.backends.swift_f0", "SwiftF0Backend")
    if backend_name == "RMVPEBackend":
        return ("acouscope.analysis.backends.rmvpe", "RMVPEBackend")
    return None


def _pythonpath_for_worker() -> str:
    """spawn 子进程的 PYTHONPATH：保证 `python -m acouscope...` 可导入包。

    开发态（src 布局、pip 未安装）：注入本包所在 src 目录；
    已安装态：沿用现有 PYTHONPATH（若已有）。
    """
    import acouscope

    # acouscope.__file__ = <src>/acouscope/__init__.py → 两层 dirname = <src>
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(acouscope.__file__)))
    existing = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if src_dir not in parts:
        parts.insert(0, src_dir)
    return os.pathsep.join(parts)


def _heartbeat_loop(proxy_ref) -> None:
    """heartbeat 线程主体（模块级函数，T-904 L2'：线程帧不持 proxy 强引用）。

    弱引用纪律：
      - proxy 经 weakref 每轮解析（p）；weakref 死 → 线程自行退出
        （无 UAF：weakref 死 ⇒ 无其他强引用 ⇒ 对象不可再被使用）
      - 长等待 stop.wait(interval) 前/后均不持 p 强引用（p 每轮局部
        解析、本轮工作结束即释放；while 条件只接触 stop 与启动时缓存
        的 interval——两者均不反向引用 proxy；_wd 的动态 interval 注入
        自下次 hb 重启生效，既有测试 _wd 注入后均重起 hb，语义不变）

    状态机（AT-1006 ①：interval 间隔 / _wd_timeout 超时，可经 _wd 注入）与
    _lock 纪律与实装完全一致：
      - 抢到 _lock 才动 socket（一次一读者，防与 detect 竞争 LineReader）；
        detect 占用期跳过（该窗口内的死亡由 detect 失败路径记账）
      - 持锁动作：进程死亡/超时判定 → PING → 收 PONG（recv 超时
        取 interval，健康态毫秒级返回；持锁总时长有界，不阻塞
        detect 超过一个心跳周期）
      - 超过 p._wd_timeout 无 PONG → 置 p._hb_dead（锁内翻转）
    线程为 daemon：主进程退出自然带走；fallback/shutdown 时经
    _stop_hb 退出。
    """
    p0 = proxy_ref()
    if p0 is None:
        return  # 启动前即被回收（竞态窗口）：直接退出
    stop = p0._stop_hb            # Event 对象：不反向引用 proxy
    interval = p0._wd_interval    # 启动时缓存（见上弱引用纪律）
    del p0                        # 立即释放强引用（等待期不持 proxy）
    while not stop.wait(interval):
        p = proxy_ref()
        if p is None:
            return  # proxy 已回收（T-904 L2'）：线程自行退出
        if not p._lock.acquire(timeout=0.0):
            p = None  # 本轮结束：释放强引用后进入长等待
            continue  # detect 占用中：下轮再试
        try:
            if p._hb_dead or p._conn is None or p._proc is None:
                pass  # 无探活动作（判死/空闲）→ 直接收尾
            else:
                # 进程已死（poll 收尸）→ 判死
                if p._proc.poll() is not None:
                    p._hb_dead = True
                    logger.warning(
                        "worker process died: backend=%s exit=%s → dead",
                        p.backend_name, p._proc.poll(),
                    )
                # 距上次 PONG 超 _wd_timeout → 判死（hang 免疫）
                elif p._last_pong_at is not None \
                        and time.monotonic() - p._last_pong_at > p._wd_timeout:
                    p._hb_dead = True
                    logger.warning(
                        "worker heartbeat timeout: backend=%s timeout=%.1fs → dead",
                        p.backend_name, p._wd_timeout,
                    )
                else:
                    # 探活：PING → PONG（短超时；超时留待下轮 PING/超时判定）
                    msg = None
                    try:
                        p._conn.settimeout(max(interval, 0.05))
                        proto.write_message(p._conn, {
                            "type": proto.MSG_PING, "rid": "",
                        })
                        msg = p._reader.read_message()
                    except TimeoutError:
                        # 本轮 PONG 未回（worker 忙或慢）：不判死，
                        # 留给下轮超时判定（_last_pong_at 未刷新 → 累计超
                        # _wd_timeout 才置 dead，保证超时语义）
                        pass
                    except OSError:
                        p._hb_dead = True
                        logger.warning(
                            "worker heartbeat ping failed: backend=%s → dead",
                            p.backend_name,
                        )
                    else:
                        if msg is None:
                            p._hb_dead = True  # 连接断开
                        elif msg.get("type") == proto.MSG_PONG:
                            p._last_pong_at = time.monotonic()
                    finally:
                        p._conn.settimeout(None)
        finally:
            p._lock.release()
            p = None  # 持锁窗口结束：释放强引用后再进入长等待


class WorkerProxy:
    """PitchBackend 同签名子进程代理（一代理一后端，进程内可复用子进程）。"""

    name: str
    is_streaming = False  # 深度分析均为离线（与真实 SOTA 后端一致）

    def __init__(self, backend_name: str):
        if backend_name not in ("EchoBackend", "SwiftF0Backend", "RMVPEBackend"):
            raise ValueError(f"unknown backend: {backend_name!r}")
        self.backend_name = backend_name
        self.name = backend_name
        self._proc: Optional[subprocess.Popen] = None
        self._conn: Optional[socket.socket] = None
        self._reader = None
        self._lock = threading.Lock()
        # ---- watchdog 状态（T-902b / AT-1006，全部 _lock 保护）----
        self._wd_interval = 2.0          # heartbeat 间隔（s，可经 _wd 注入）
        self._wd_timeout = 15.0          # heartbeat 超时（s，可经 _wd 注入；T-1030：5.0→15.0，依据 PI-T25 实测 2.581s/档）
        self._hb_thread: Optional[threading.Thread] = None
        self._stop_hb = threading.Event()
        self._last_pong_at: Optional[float] = None
        self._hb_dead = False            # heartbeat 超时置 dead（锁内翻转）
        self._consecutive_fails = 0      # 连续 worker 失败计数
        self._fallback = False           # 本会话 fallback 直连标志（不自动改回）
        self._respawn_gen = -1           # 上次 respawn 前代次（-1=未发生）
        self._proc_gen = 0               # 子进程代次（每次成功 spawn +1）
        self._fail_reason: Optional[str] = None  # 最近一次失败原因摘要

    # ------------------------------------------------------------------
    # watchdog 控制/观测 API（线程安全）
    # ------------------------------------------------------------------

    def _wd(self, **kwargs) -> None:
        """watchdog 参数注入（测试可缩短超时，避免真实等待）。"""
        with self._lock:
            if "interval" in kwargs:
                self._wd_interval = float(kwargs["interval"])
            if "timeout" in kwargs:
                self._wd_timeout = float(kwargs["timeout"])

    def is_fallback_active(self) -> bool:
        """本会话是否已 fallback 直连（连续失败触发后恒真，不自动改回）。"""
        with self._lock:
            return self._fallback

    def failure_summary(self) -> Optional[str]:
        """最近一次 worker 失败原因摘要（fallback 日志/诊断用）。"""
        with self._lock:
            return self._fail_reason

    def _kill_for_test(self) -> None:
        """测试用：SIGKILL 当前子进程并清引用（模拟 worker 死亡）。

        幂等：子进程已不存在时 no-op（供 respawn 窗口内二次 kill 场景：
        首次 kill 后 detect 失败已把 _proc 置 None，二次调用直接返回，
        不会把旧连接复活）。
        """
        with self._lock:
            proc, self._proc = self._proc, None
            self._conn = None
            self._reader = None
        if proc is not None:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=5.0)
            except Exception:
                pass

    def _watchdog_marked_dead(self) -> bool:
        """heartbeat 是否已判定 worker 死亡（锁内读）。"""
        with self._lock:
            return self._hb_dead

    # ------------------------------------------------------------------
    # PitchBackend 接口（同签名）
    # ------------------------------------------------------------------

    def detect(
        self,
        signal: np.ndarray,
        sr: float,
        fmin: float = 40.0,
        fmax: float = 2000.0,
        progress_cb: "Callable[[float], None] | None" = None,
    ):
        """子进程 detect（env=1 才可达；env=0 → RuntimeError("worker disabled")）。

        SharedMemory 生命周期（双侧，如实）：
          输入：proxy create → 写 float32 → 发 DETECT → [等服务端消费]
                → 收 RESULT/ERROR 后 close → unlink（owner=proxy）
          输出：server create+写+发 RESULT（仅 close 自身引用，不 unlink）
                → proxy attach（重试 3 次兜底）→ 拷贝 → close → unlink
                （最终 owner=proxy，唯一消费者；消除服务端先 unlink 的竞态）
        """
        if not proto.is_worker_enabled():
            raise RuntimeError("worker disabled")

        sig = np.ascontiguousarray(signal, dtype=np.float32).ravel()
        n = sig.size
        if n == 0:
            raise ValueError("empty signal")

        with self._lock:
            # watchdog 防御：本会话已 fallback 直连后，本代理不再进 worker 路径
            #（主判定在 routing.route_or_detect 前置完成；此处为并发/直调双保险）
            if self._fallback:
                raise RuntimeError(
                    f"worker fallback active: backend={self.backend_name} "
                    f"({self._fail_reason})"
                )
            in_shm = None
            in_name = ""
            try:
                self._ensure_process()
                rid = uuid.uuid4().hex

                # 1) 输入信号 → SharedMemory（禁 pickle 大数组）
                from multiprocessing import shared_memory

                in_name = proto.shm_name("acw_i_", rid)
                in_shm = shared_memory.SharedMemory(
                    name=in_name, create=True, size=n * 4
                )
                in_view = np.ndarray(n, dtype="float32", buffer=in_shm.buf)
                in_view[:] = sig

                req = proto.DetectRequest(
                    backend=self.backend_name,
                    signal=proto.ShmHandle(name=in_name, shape=(n,), dtype="float32"),
                    sr=float(sr),
                    fmin=float(fmin),
                    fmax=float(fmax),
                )
                # 2) 发送 + 消息循环（PROGRESS 中继/RESULT/ERROR）+ 结果读取
                self._send_detect(req, rid)
                return self._recv_result(req, in_shm, in_name, rid, progress_cb)
            except Exception as e:
                if in_shm is not None:
                    in_shm.close()
                    self._cleanup_in_shm(in_name)
                # watchdog 失败记账（锁内，AT-1006 ②③：spawn/send/recv
                # 任一环节失败均计入连续失败）
                self._record_failure_locked(str(e))
                raise

    # ------------------------------------------------------------------
    # detect 收发拆分（watchdog：失败路径可注入）
    # ------------------------------------------------------------------

    def _send_detect(self, req: proto.DetectRequest, rid: str) -> None:
        """发送 DETECT 消息（失败由 detect 统一记账；调用方持 _lock）。"""
        try:
            proto.write_message(self._conn, {
                "type": proto.MSG_DETECT, "rid": rid, "payload": req.to_dict(),
            })
        except Exception as e:
            raise RuntimeError(
                f"worker detect failed: send lost: {e!r}"
            ) from e

    def _recv_result(self, req: proto.DetectRequest, in_shm, in_name: str,
                     rid: str, progress_cb):
        """消息循环（PROGRESS 中继/RESULT/ERROR）+ 结果 shm 读取。

        PONG 只可能出现在 DETECT 未发出前的空闲期（server 侧 PING→PONG）；
        本循环收到的 PONG 属协议外消息，按原语义忽略。watchdog 的 PING/
        PONG 探活走 heartbeat 线程，与本循环互斥于 _lock（一次只有一个读者）。
        调用方持 _lock。
        """
        # 2) 消息循环：PROGRESS 中继，直到 RESULT/ERROR
        echo_amp = None
        result_msg = None
        while True:
            try:
                msg = self._reader.read_message()
            except OSError as e:
                # 连接被对端重置/断开（worker 死亡竞态）→ 归一为 worker 失败
                raise RuntimeError(f"worker connection lost: {e!r}") from e
            if msg is None:
                raise RuntimeError("worker connection lost")
            mtype = msg.get("type")
            if mtype == proto.MSG_PROGRESS and msg.get("rid") == rid:
                if progress_cb is not None:
                    progress_cb(float(msg.get("value", 0.0)))
            elif mtype in (proto.MSG_RESULT, proto.MSG_ERROR):
                result_msg = msg
                break
            # 其他类型（PONG 等）忽略

        # 3) 输入 shm 收尾（服务端已消费完毕才走到这里）
        in_shm.close()
        self._cleanup_in_shm(in_name)

        if result_msg["type"] == proto.MSG_ERROR:
            raise RuntimeError(
                f"worker detect failed: {result_msg.get('message', 'unknown')}"
            )
        echo_amp = result_msg.get("echo_amp")
        payload = proto.ResultPayload.from_dict(result_msg["payload"])

        # 4) 结果 shm：attach（重试）→ 拷贝 → close → unlink（owner）
        track = self._read_result_shm(payload)
        # 挂 Echo 语义校验量（非 PitchTrack 字段，测试消费）
        try:
            track._worker_echo_amp = echo_amp  # type: ignore[attr-defined]
        except Exception:
            pass
        # 成功 → 失败计数清零（连续失败语义：成功即打断；调用方持 _lock）
        self._consecutive_fails = 0
        # IM-25 α（T-1070）：完整成功即活体证据。detect 全程持锁，期间
        # heartbeat 抢锁失败（:121 跳过）发不出 PING，server 串行处理
        # detect（返回循环后才写 PONG）⇒ 以成功时刻续 _last_pong_at，把
        # 判死窗后移一整档，免合法久 detect 被全额计入墙钟差而误判死。
        # 仅成功路径可达（:354-358/:372-375 失败 raise 在前行），判死式不动。
        self._last_pong_at = time.monotonic()
        return track

    @staticmethod
    def _cleanup_in_shm(in_name: str) -> None:
        """输入 shm unlink 兜底（owner=proxy；FileNotFoundError 容忍）。"""
        try:
            from multiprocessing import shared_memory

            shared_memory.SharedMemory(name=in_name, create=False).unlink()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # watchdog（T-902b / AT-1006）：heartbeat / respawn / fallback
    # ------------------------------------------------------------------

    def _record_failure_locked(self, reason: str) -> None:
        """记录一次 worker 失败并推进 fallback 状态机（调用方持 _lock）。

        状态机（锁内单点翻转）：
          _consecutive_fails += 1
          达到 2 → _fallback=True + logging.warning（含 backend 名与原因摘要）
          fallback 后 env 语义不变（不自动改回；本会话内恒直连）
        """
        self._consecutive_fails += 1
        self._fail_reason = (reason or "unknown")[:200]
        if self._consecutive_fails >= 2 and not self._fallback:
            self._fallback = True
            self._stop_hb.set()
            self._shutdown_locked()
            logger.warning(
                "worker fallback to in-process: backend=%s "
                "consecutive_fails=%d last_reason=%s",
                self.backend_name, self._consecutive_fails, self._fail_reason,
            )

    def _start_heartbeat_locked(self) -> None:
        """spawn/respawn 完成后启动 heartbeat 线程（调用方持 _lock）。

        T-904 L2'：target 为模块级 _heartbeat_loop（线程帧无 self、
        仅持 weakref），废弃 proxy 的引用计数可归零 → __del__ 即时
        触发（否则 hb 强持 proxy 成 GC 根，见模块 docstring T-904 段）。
        """
        self._stop_hb.clear()
        self._hb_dead = False
        self._last_pong_at = time.monotonic()
        t = threading.Thread(
            target=_heartbeat_loop, args=(weakref.ref(self),),
            name="worker-hb", daemon=True,
        )
        self._hb_thread = t
        t.start()

    def is_available(self) -> bool:
        """进程内真实类探测（不 spawn 子进程，与 base.py 同语义）。"""
        if self.backend_name == "EchoBackend":
            return True  # 协议内置，无模型依赖
        spec = _backend_module(self.backend_name)
        if spec is None:
            return False
        import importlib

        try:
            mod = importlib.import_module(spec[0])
            cls = getattr(mod, spec[1])
            return bool(cls().is_available())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def __del__(self) -> None:
        """析构兜底（T-904 L2）：_proc 仍存活（未 close）则补一次 close()。

        全程 try 包裹：解释器 shutdown 期属性可能已被回收为 None、或
        模块级 proto/子模块处于半销毁状态——任何异常一律吞掉，绝不外抛。
        close() 内部为 BYE→terminate→kill 有界链，天然有界。
        前置 best-effort 置 _stop_hb：加速 hb 线程退出（L2' 弱引用化后
        本方法在 proxy 回收时即被触发，hb 线程下轮自行退出）；失败无碍。
        """
        try:
            stop = getattr(self, "_stop_hb", None)
            if stop is not None:
                stop.set()
        except Exception:
            pass
        try:
            proc = getattr(self, "_proc", None)
            if proc is not None:
                self.close()
        except Exception:
            pass

    def close(self) -> None:
        """优雅关闭子进程（BYE → 超时 → terminate → kill）。"""
        with self._lock:
            self._shutdown_locked()

    def _shutdown_locked(self) -> None:
        # watchdog：停止 heartbeat 线程（stop 标志 + 有界 join；
        # join 超时则置 _hb_dead 使残留线程下轮空转直至退出，
        # 避免双 hb 线程竞争同一 socket 读者）
        self._stop_hb.set()
        hb, self._hb_thread = self._hb_thread, None
        if hb is not None:
            hb.join(timeout=self._wd_interval + 0.5)
            if hb.is_alive():
                self._hb_dead = True
        self._hb_dead = False
        self._last_pong_at = None
        proc, self._proc = self._proc, None
        conn, self._conn = self._conn, None
        self._reader = None
        if conn is not None:
            try:
                proto.write_message(conn, {"type": proto.MSG_BYE})
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
        if proc is not None:
            try:
                proc.wait(timeout=5.0)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=5.0)
                except Exception:
                    proc.kill()

    def _ensure_process(self) -> None:
        """spawn/复用子进程 + 连接 + HELLO 握手（watchdog respawn 路径）。

        状态机（调用方持 _lock，AT-1006 ②）：
        - 存活且未被 heartbeat 判死 → 直接复用
        - heartbeat 判死（_hb_dead）或进程已死（poll 非 None）→ 重建：
          单次调用至多 spawn 一次（无 call 内重试）——"下次 detect 自动
          respawn 一次" 即由此保证；spawn 失败抛出由 detect 计入失败
          计数，连续 2 次失败 → fallback 直连
        - 重建成功 → 重置 dead/失败计数 + 重启 heartbeat（新子进程
          重新进入探活周期）
        """
        if (self._proc is not None and self._proc.poll() is None
                and self._conn is not None and not self._hb_dead):
            return
        was_respawn = self._proc_gen > 0
        self._shutdown_locked()

        env = os.environ.copy()
        env["PYTHONPATH"] = _pythonpath_for_worker()
        token = uuid.uuid4().hex
        proc = subprocess.Popen(
            [sys.executable, "-m", "acouscope.analysis.worker.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        proc.stdin.write(token.encode("utf-8") + b"\n")
        proc.stdin.flush()

        line = proc.stdout.readline().decode("utf-8", errors="replace")
        ready = proto.parse_ready_line(line)
        if ready is None:
            err = proc.stderr.read(4096).decode("utf-8", errors="replace")
            proc.kill()
            raise RuntimeError(f"worker failed to start: {line.strip()!r} {err.strip()!r}")
        port, srv_token = ready

        conn = socket.create_connection(("127.0.0.1", port), timeout=10.0)
        conn.settimeout(None)
        fobj = conn.makefile("rb")
        proto.write_message(conn, {
            "type": proto.MSG_HELLO, "token": srv_token, "protocol": proto.PROTOCOL_VERSION,
        })
        ack = proto.LineReader(fobj).read_message()
        if not isinstance(ack, dict) or ack.get("type") != proto.MSG_HELLO_ACK:
            conn.close()
            proc.kill()
            raise RuntimeError(f"worker handshake failed: {ack!r}")

        self._proc = proc
        self._conn = conn
        self._reader = proto.LineReader(fobj)
        self._proc_gen += 1
        if was_respawn:
            logger.warning(
                "worker respawned: backend=%s gen=%d",
                self.backend_name, self._proc_gen,
            )
        # 重建成功：重置死亡标记 + 重启 heartbeat（失败计数不在此清零：
        # "连续失败" 语义计的是 detect 调用失败次数，respawn 后立即再死
        # 同样计入；仅在 _recv_result 完整成功后清零）
        self._respawn_gen = self._proc_gen
        self._hb_dead = False
        self._start_heartbeat_locked()

    def _read_result_shm(self, payload: proto.ResultPayload):
        """attach 结果 shm（重试 3 次兜底）→ 拷贝 → close → unlink（owner）。"""
        from multiprocessing import shared_memory

        handle: proto.ShmHandle = payload.track
        shm = None
        last_err: Optional[Exception] = None
        for _ in range(3):
            try:
                shm = shared_memory.SharedMemory(name=handle.name, create=False)
                break
            except FileNotFoundError as e:
                last_err = e
                time.sleep(0.05)
        if shm is None:
            raise RuntimeError(f"result shm attach failed: {last_err!r}")
        try:
            n_times, n_f0, n_conf = proto.parse_track_header(
                bytes(bytearray(shm.buf[: proto.TRACK_HEADER.size]))
            )
            n_body = n_times + n_f0 + n_conf
            # 头部后的 float64 视图（sliced memoryview，偏移 16 字节 8 对齐）
            body = np.ndarray(
                (n_body,), dtype="float64",
                buffer=shm.buf[proto.TRACK_HEADER.size:],
            )
            times = np.array(body[:n_times], dtype=np.float64)
            f0 = np.array(body[n_times:n_times + n_f0], dtype=np.float64)
            conf = np.array(body[n_times + n_f0:n_times + n_f0 + n_conf], dtype=np.float64)
        finally:
            # 结果段 owner=客户端（唯一消费者）：拷贝完成后 close → unlink，
            # 消除服务端先 unlink 导致 attach 失败（FileNotFoundError）的竞态。
            shm.close()
            try:
                shm.unlink()
            except FileNotFoundError:
                pass

        from acouscope.analysis.pitch import PitchTrack

        return PitchTrack(
            times=times,
            f0_hz=f0,
            confidence=conf,
            fmin=payload.fmin,
            fmax=payload.fmax,
        )
