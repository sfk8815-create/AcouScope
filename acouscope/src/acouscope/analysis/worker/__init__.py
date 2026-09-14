# SPDX-License-Identifier: GPL-3.0-only
"""analysis.worker — 推理 worker 隔离子包（T-902a，纯新增零接线）。

内容：
  protocol — 消息常量 / 请求响应 dataclass / SharedMemory 句柄 / JSON 线格式
  server   — 子进程入口（python -m acouscope.analysis.worker.server）
  proxy    — WorkerProxy（PitchBackend 同签名代理，env=1 才 spawn）
  routing  — route(backend_name, factory) 纯函数路由（env=0 直连）

本包 import 不触发 onnxruntime；onnxruntime 只在子进程内按需导入。
env 默认 OFF（ACOUSECOPE_ANALYSIS_WORKER 未设置 → 直连，零行为变化）。
"""

from . import protocol
from .proxy import WorkerProxy
from .routing import route

PROTOCOL_VERSION = protocol.PROTOCOL_VERSION
ENV_WORKER = protocol.ENV_WORKER

__all__ = ["route", "WorkerProxy", "PROTOCOL_VERSION", "ENV_WORKER", "protocol"]
