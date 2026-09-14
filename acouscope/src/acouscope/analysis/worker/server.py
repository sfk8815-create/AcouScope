# SPDX-License-Identifier: GPL-3.0-only
"""分析 Worker 子进程服务端（T-902a，纯新增零接线）。

WORKER_SERVER_V1 — 子进程入口，承载 onnxruntime 深度分析（SwiftF0/RMVPE），
主进程经本地 socket + SharedMemory 调用。onnxruntime 只在本进程内按需导入
（动态 import 后端模块时触发），主进程永不加载。

启动流程：
  1. stdin 读第一行 = auth token
  2. 127.0.0.1 绑定随机端口（port=0），listen
  3. stdout 打印 `WORKER_READY port=<p> token=<t>`（单行，flush）
  4. accept 单客户端，HELLO 鉴权（token + PROTOCOL_VERSION）
  5. JSON 行循环：DETECT / PING / BYE / 其他

DETECT 处理：
  signal@shm → attach → 拷贝 → close（只读侧，禁 unlink）
  → 构造后端（EchoBackend 内置；SwiftF0/RMVPE 动态 import，onnxruntime 在此
    进程内按需加载）
  → detect(signal, sr, fmin, fmax, progress_cb)，progress_cb 每值发一条
    PROGRESS 消息（rid 关联本次请求）
  → 结果 PitchTrack 数组（times/f0_hz/confidence 拼接 + 段长头）写新
    SharedMemory → RESULT{track@shm, counts, ...}（服务端仅 close 自身引用，
    不 unlink；结果段 unlink 责任在客户端——唯一消费者，防 attach 竞态）
  → 异常 → ERROR{rid, message}

EchoBackend 语义（协议内置，无模型依赖，供 roundtrip 测试）：
  - times:    arange(n)/sr（n = 输入信号长度）
  - f0_hz:    全 220.0 Hz 常值（恒定 f0 轨）
  - confidence: 全 1.0
  - 语义校验标记：另发 PROGRESS 不可行——signal×2 语义以 RESULT 附属字段
    echo_amp 回传（= mean(|input|)*2 的参照值：mean(|input*2|)），主进程
    测试据此校验 "输入信号×2" 数据路径未被破坏（幅度加倍一致性）。
"""

from __future__ import annotations

import sys
import uuid


def _emit(line: str) -> None:
    """向 stdout 输出单行并 flush（只用于启动期的 WORKER_READY）。"""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# EchoBackend（协议内置，无模型依赖）
# ---------------------------------------------------------------------------

class EchoBackend:
    """协议内置回显后端：无模型，供无模型 roundtrip 测试。

    语义（以本实现为准，测试注释同步）：
      f0_hz = 220.0 常值轨；times = arange(n)/sr；confidence = 1.0 常值；
      echo_amp = float(mean(|signal * 2|)) —— "输入信号×2" 路径的语义校验量。
    """

    name = "Echo"
    is_streaming = False

    def detect(
        self,
        signal,
        sr: float,
        fmin: float = 40.0,
        fmax: float = 2000.0,
        progress_cb=None,
    ):
        import numpy as np

        from acouscope.analysis.pitch import PitchTrack

        sig = np.asarray(signal, dtype=np.float64).ravel()
        doubled = sig * 2.0  # 输入信号×2（Echo 约定）
        n = sig.size
        times = np.arange(n, dtype=np.float64) / float(sr)
        f0 = np.full(n, 220.0, dtype=np.float64)
        conf = np.ones(n, dtype=np.float64)
        if progress_cb:
            for i in range(10):
                progress_cb((i + 1) / 10.0)
        return PitchTrack(
            times=times,
            f0_hz=f0,
            confidence=conf,
            fmin=fmin,
            fmax=fmax,
            cent_ref=440.0,
        ), float(np.mean(np.abs(doubled)))


def _build_backend(backend_name: str):
    """按名字构造后端实例。

    EchoBackend 内置（本模块）；SwiftF0Backend/RMVPEBackend 动态 import
    ——onnxruntime 的 import 只发生在本（子）进程内、按需触发。
    """
    if backend_name == "EchoBackend":
        return EchoBackend()
    if backend_name == "SwiftF0Backend":
        import importlib

        mod = importlib.import_module("acouscope.analysis.backends.swift_f0")
        return mod.SwiftF0Backend()
    if backend_name == "RMVPEBackend":
        import importlib

        mod = importlib.import_module("acouscope.analysis.backends.rmvpe")
        return mod.RMVPEBackend()
    raise ValueError(f"unknown backend: {backend_name!r}")


# ---------------------------------------------------------------------------
# 消息处理
# ---------------------------------------------------------------------------

def _handle_detect(conn, msg: dict) -> None:
    """处理 DETECT：读 shm 信号 → 后端 detect → 结果写 shm → RESULT/ERROR。"""
    from multiprocessing import shared_memory

    import numpy as np

    from . import protocol as proto

    rid = msg.get("rid", "")
    req = proto.DetectRequest.from_dict(msg.get("payload", {}))

    # 1) 输入信号：attach → 拷贝 → close（只读侧，禁 unlink）
    input_shm = None
    try:
        input_shm = shared_memory.SharedMemory(name=req.signal.name)
        # 按 shape 取数（一维信号；shape 为空时按段容量全长）
        n = int(np.prod(req.signal.shape)) if req.signal.shape else 0
        if n == 0:
            n = input_shm.size // np.dtype(req.signal.dtype).itemsize
        buf = np.ndarray((n,), dtype=req.signal.dtype, buffer=input_shm.buf)
        signal = np.ascontiguousarray(buf, dtype=np.float64).ravel()
    except Exception as e:
        proto.write_message(conn, {
            "type": proto.MSG_ERROR, "rid": rid,
            "message": f"signal shm attach failed: {e!r}",
        })
        return
    finally:
        if input_shm is not None:
            input_shm.close()

    # 2) 后端 detect（onnxruntime 仅在本进程内按需加载）
    echo_amp = None
    try:
        backend = _build_backend(req.backend)

        def _progress_cb(value: float) -> None:
            # 进度经协议回传（PROGRESS 消息，rid 关联请求）
            proto.write_message(conn, {
                "type": proto.MSG_PROGRESS, "rid": rid, "value": float(value),
            })

        out = backend.detect(
            signal, req.sr, fmin=req.fmin, fmax=req.fmax, progress_cb=_progress_cb
        )
        if req.backend == "EchoBackend":
            track, echo_amp = out
        else:
            track = out
    except Exception as e:
        proto.write_message(conn, {
            "type": proto.MSG_ERROR, "rid": rid,
            "message": f"{type(e).__name__}: {e}",
        })
        return

    # 3) 结果数组 → 新 SharedMemory（owner=服务端）
    times = np.asarray(track.times, dtype=np.float64)
    f0 = np.asarray(track.f0_hz, dtype=np.float64)
    conf = np.asarray(track.confidence, dtype=np.float64)
    counts = (times.size, f0.size, conf.size)
    header = proto.track_header(*counts)
    body = np.concatenate([times, f0, conf]).astype(np.float64)
    total = proto.TRACK_HEADER.size + body.size * 8

    res_shm = None
    try:
        name = proto.shm_name("acw_r_", uuid.uuid4().hex)
        res_shm = shared_memory.SharedMemory(name=name, create=True, size=total)
        np.ndarray(
            (proto.TRACK_HEADER.size,), dtype="uint8", buffer=res_shm.buf
        )[:] = np.frombuffer(header, dtype=np.uint8)
        np.ndarray(
            (body.size,), dtype="float64",
            buffer=res_shm.buf[proto.TRACK_HEADER.size:],
        )[:] = body
    except Exception as e:
        if res_shm is not None:
            res_shm.close()
            try:
                res_shm.unlink()
            except FileNotFoundError:
                pass
        proto.write_message(conn, {
            "type": proto.MSG_ERROR, "rid": rid,
            "message": f"result shm write failed: {e!r}",
        })
        return

    # 4) RESULT（先发消息，随后仅 close 自身引用；unlink 由客户端执行）
    result_payload = proto.ResultPayload(
        track=proto.ShmHandle(name=name, shape=counts, dtype="float64"),
        counts=counts,
        backend=req.backend,
        sr=req.sr,
        fmin=req.fmin,
        fmax=req.fmax,
    )
    out_msg = {
        "type": proto.MSG_RESULT, "rid": rid,
        "payload": result_payload.to_dict(),
    }
    if echo_amp is not None:
        out_msg["echo_amp"] = echo_amp
    proto.write_message(conn, out_msg)
    # 服务端侧收尾：只 close 自己的引用，【不 unlink】。
    # 结果段 unlink 责任在客户端（唯一消费者）——消除 unlink/attach 竞态：
    # 若服务端先 unlink，客户端 attach 可能 FileNotFoundError（实测触发）。
    res_shm.close()


def _serve_client(conn, addr, token: str) -> None:
    """单客户端 socket 服务循环。"""
    from . import protocol as proto

    conn.settimeout(None)
    fobj = conn.makefile("rb")
    try:
        hello = proto.LineReader(fobj).read_message()
    except Exception:
        hello = None
    if not isinstance(hello, dict) or hello.get("type") != proto.MSG_HELLO:
        conn.close()
        return
    if hello.get("token") != token or str(hello.get("protocol")) != proto.PROTOCOL_VERSION:
        proto.write_message(conn, {"type": proto.MSG_ERROR, "message": "auth failed"})
        conn.close()
        return
    proto.write_message(conn, {"type": proto.MSG_HELLO_ACK, "protocol": proto.PROTOCOL_VERSION})

    reader = proto.LineReader(fobj)
    while True:
        try:
            msg = reader.read_message()
        except Exception:
            break
        if msg is None:
            break
        mtype = msg.get("type")
        if mtype == proto.MSG_DETECT:
            try:
                _handle_detect(conn, msg)
            except Exception as e:  # 兜底：任何未预期异常 → ERROR 而非断链
                proto.write_message(conn, {
                    "type": proto.MSG_ERROR, "rid": msg.get("rid", ""),
                    "message": f"internal: {type(e).__name__}: {e}",
                })
        elif mtype == proto.MSG_PING:
            proto.write_message(conn, {"type": proto.MSG_PONG, "rid": msg.get("rid", "")})
        elif mtype == proto.MSG_BYE:
            break
        else:
            proto.write_message(conn, {
                "type": proto.MSG_ERROR, "rid": msg.get("rid", ""),
                "message": f"unknown message type: {mtype!r}",
            })
    conn.close()


def main() -> int:
    """子进程入口：stdin token → 随机端口 → WORKER_READY → 服务循环。"""
    from . import protocol as proto

    # 1) stdin 读 auth token
    token = sys.stdin.readline().strip()
    if not token:
        sys.stderr.write("worker: empty auth token\n")
        return 2

    # 2) 127.0.0.1 随机端口
    import socket as _socket

    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    # 3) stdout 就绪行
    _emit(f"{proto.READY_PREFIX} port={port} token={token}")

    # 4/5) accept 单客户端 + 协议循环
    try:
        while True:
            conn, addr = srv.accept()
            _serve_client(conn, addr, token)
            if conn is None:
                break
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
