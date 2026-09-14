# SPDX-License-Identifier: GPL-3.0-only
"""Worker 通信协议（T-902a，纯新增零接线）。

WORKER_PROTOCOL_V1 — SwiftF0/RMVPE 深度分析子进程隔离的协议层。

设计：
- 主进程（Proxy）与子进程（Server）经 127.0.0.1 本地 socket 通信，
  每条消息为一行 JSON（UTF-8），\n 分隔。
- 大数组（输入信号 / 结果 PitchTrack 数组）禁 pickle 走 socket，
  一律经 multiprocessing.shared_memory.SharedMemory 传递：
  消息内只传 ShmHandle（name/shape/dtype），数据本体走共享内存。
  30min@16kHz float32 ≈115MB 场景下 socket 仅传元数据。
- 鉴权：Server 启动时从 stdin 读 auth token，socket HELLO 必须携带
  同一 token，否则断开。
- 仅标准库 + numpy（numpy 仅用于 server 侧数组经 SharedMemory 的
  语义约定 dtype/shape 序列化；protocol 层本身不 import numpy）。
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import IO, Optional

PROTOCOL_VERSION = "1"

# 环境变量开关（HARD-RULE 4：默认 OFF）
ENV_WORKER = "ACOUSECOPE_ANALYSIS_WORKER"
WORKER_ON = "1"
WORKER_OFF = "0"  # 缺省/任何非 "1" 值一律按 OFF 处理

# ---------------------------------------------------------------------------
# 消息类型常量（JSON 行字段 "type" 的取值）
# ---------------------------------------------------------------------------
MSG_HELLO = "HELLO"        # 客户端 → 服务端：握手（token + protocol 版本）
MSG_HELLO_ACK = "HELLO_ACK"  # 服务端 → 客户端：握手确认
MSG_DETECT = "DETECT"      # 客户端 → 服务端：检测请求（信号经 SharedMemory）
MSG_RESULT = "RESULT"      # 服务端 → 客户端：检测成功（结果数组经 SharedMemory）
MSG_ERROR = "ERROR"        # 服务端 → 客户端：检测失败（异常文本回传）
MSG_PROGRESS = "PROGRESS"  # 服务端 → 客户端：进度回调中继（0.0→1.0）
MSG_PING = "PING"          # 客户端 → 服务端：探活
MSG_PONG = "PONG"          # 服务端 → 客户端：探活应答
MSG_BYE = "BYE"            # 客户端 → 服务端：请求优雅退出（服务端可忽略）


def is_worker_enabled(env: Optional[dict] = None) -> bool:
    """ACOUSECOPE_ANALYSIS_WORKER 开关判定：仅 "1" 为 ON（HARD-RULE 4）。"""
    import os

    mapping = os.environ if env is None else env
    return str(mapping.get(ENV_WORKER, WORKER_OFF)) == WORKER_ON


# ---------------------------------------------------------------------------
# SharedMemory 句柄结构（大数组只传句柄，不传数据）
# ---------------------------------------------------------------------------

def shm_name(prefix: str, rid: str) -> str:
    """跨平台安全 SharedMemory 名：总长 ≤ 30。

    Linux shm 名上限 251 字符；macOS 将名映射为 /name 文件，本机实测上限
    30（31 即 Errno 63）。此处统一取严口径 30，rid 截断补足。
    """
    if len(prefix) > 24:
        raise ValueError(f"shm prefix too long: {prefix!r}")
    return (prefix + rid)[:30]


@dataclass
class ShmHandle:
    """SharedMemory 句柄（跨进程 attach 用）。

    name:  SharedMemory 名称（主进程创建、子进程 attach 的同一名字）
    shape: 数组形状（tuple[int, ...]）
    dtype: numpy dtype 字符串（如 "float32"/"float64"）

    生命周期约定（双侧，T-902a 实测后定稿）：
      输入段（proxy owner）: proxy create → 写数据 → 发 DETECT → 等服务端消费
            → 收 RESULT/ERROR 后 close → unlink
      结果段（proxy 为最终 owner，唯一消费者）:
            server create → 写数据 → 发 RESULT → 仅 close 自身引用（禁 unlink，
            防 attach 竞态）→ proxy attach → 拷贝 → close → unlink
    所有权原则：谁最终消费谁负责 unlink；非 owner 侧只 close 自己 attach 的引用。
    """

    name: str
    shape: tuple = field(default_factory=tuple)
    dtype: str = "float64"

    def to_dict(self) -> dict:
        return {"name": self.name, "shape": list(self.shape), "dtype": self.dtype}

    @classmethod
    def from_dict(cls, d: dict) -> "ShmHandle":
        return cls(name=d["name"], shape=tuple(d.get("shape", ())), dtype=d.get("dtype", "float64"))


# ---------------------------------------------------------------------------
# 请求/响应 dataclass
# ---------------------------------------------------------------------------

@dataclass
class DetectRequest:
    """DETECT 请求：signal 走 SharedMemory（ShmHandle），其余为标量元数据。"""

    backend: str          # "EchoBackend" | "SwiftF0Backend" | "RMVPEBackend"
    signal: ShmHandle     # 输入信号句柄（一维 float 数组）
    sr: float             # 采样率
    fmin: float = 40.0
    fmax: float = 2000.0

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "signal": self.signal.to_dict(),
            "sr": self.sr,
            "fmin": self.fmin,
            "fmax": self.fmax,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DetectRequest":
        return cls(
            backend=d["backend"],
            signal=ShmHandle.from_dict(d["signal"]),
            sr=float(d["sr"]),
            fmin=float(d.get("fmin", 40.0)),
            fmax=float(d.get("fmax", 2000.0)),
        )


@dataclass
class ResultPayload:
    """RESULT 载荷：PitchTrack 各数组走共享内存（一个 shm 打包多段）。

    打包约定（服务端写 / 主进程读，顺序固定）：
      [times | f0_hz | confidence] 一维拼接为 float64，
      段长依次 times.shape, f0_hz.shape, confidence.shape。
    元数据（fmin/fmax/sr/后端名）以标量随消息回传，不进 shm。
    """

    track: ShmHandle      # 打包后的 PitchTrack 数组句柄
    counts: tuple         # (n_times, n_f0, n_confidence)
    backend: str
    sr: float
    fmin: float
    fmax: float

    def to_dict(self) -> dict:
        return {
            "track": self.track.to_dict(),
            "counts": list(self.counts),
            "backend": self.backend,
            "sr": self.sr,
            "fmin": self.fmin,
            "fmax": self.fmax,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResultPayload":
        return cls(
            track=ShmHandle.from_dict(d["track"]),
            counts=tuple(d.get("counts", ())),
            backend=d.get("backend", ""),
            sr=float(d.get("sr", 0.0)),
            fmin=float(d.get("fmin", 40.0)),
            fmax=float(d.get("fmax", 2000.0)),
        )


# ---------------------------------------------------------------------------
# 线格式（JSON 行）收发
# ---------------------------------------------------------------------------

def encode_message(msg: dict) -> bytes:
    """dict → 单行 JSON 字节（UTF-8，\n 结尾）。"""
    return (json.dumps(msg, ensure_ascii=False, default=str) + "\n").encode("utf-8")


class LineReader:
    """socket 文件对象的按行 JSON 读取器（跨读边界缓冲）。

    底层一次读优先用 read1（BufferedReader，单次原始读、不等待回填），
    对纯 socket 对象退化为 recv。兼容 makefile("rb") 与原始 socket。
    """

    def __init__(self, fileobj: IO[bytes]):
        self._fileobj = fileobj
        self._buf = b""

    def _raw_read(self) -> bytes:
        """一次原始读：read1 优先（BufferedReader），recv 退路（socket）。"""
        if hasattr(self._fileobj, "read1"):
            return self._fileobj.read1(65536)
        return self._fileobj.recv(65536)

    def read_message(self) -> dict:
        """读一条 JSON 行消息；连接断开返回 None。"""
        while b"\n" not in self._buf:
            chunk = self._raw_read()
            if not chunk:
                if self._buf:
                    # 连接断开前残留的完整行也尽量收下
                    try:
                        return json.loads(self._buf.decode("utf-8"))
                    except Exception:
                        return None
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        line = line.strip()
        if not line:
            return self.read_message()
        return json.loads(line.decode("utf-8"))


def write_message(fileobj: IO[bytes], msg: dict) -> None:
    """向 socket 文件对象写一条 JSON 行消息（含 flush）。"""
    fileobj.sendall(encode_message(msg))


# ---------------------------------------------------------------------------
# Server stdout 就绪行解析（WORKER_READY port=<p> token=<t>）
# ---------------------------------------------------------------------------

READY_PREFIX = "WORKER_READY"


def parse_ready_line(line: str) -> Optional[tuple]:
    """解析 `WORKER_READY port=<p> token=<t>` → (port:int, token:str)；失败 None。"""
    parts = line.strip().split()
    if len(parts) < 3 or parts[0] != READY_PREFIX:
        return None
    kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
    if "port" not in kv or "token" not in kv:
        return None
    return int(kv["port"]), kv["token"]


# ---------------------------------------------------------------------------
# SharedMemory 打包/解包（PitchTrack 数组，仅服务端/代理侧使用 numpy）
# ---------------------------------------------------------------------------

#: struct 头格式：8 字节 = 4 x uint32（n_times, n_f0, n_conf, _unused）
TRACK_HEADER = struct.Struct("<IIII")


def track_header(n_times: int, n_f0: int, n_conf: int) -> bytes:
    return TRACK_HEADER.pack(n_times, n_f0, n_conf, 0)


def parse_track_header(header: bytes) -> tuple:
    n_times, n_f0, n_conf, _ = TRACK_HEADER.unpack(header)
    return n_times, n_f0, n_conf
