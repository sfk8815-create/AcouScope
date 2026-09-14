# SPDX-License-Identifier: GPL-3.0-only
"""应用内模型商店后端（T-304b）：模型拉取管理器。MODEL_MANAGER_V1

V099_HTTP_PULL_V1：废弃 CLI 子进程路线，改内置 Ollama 实例的 HTTP 流式
拉取（POST /api/pull，NDJSON 逐行进度）；磁盘预检对准沙盒模型目录
（ollama_runtime.models_dir()）；错误文案零终端（AT-410：不含命令 /
URL / 安装指引）。进度按层 digest 聚合 completed/total；重发同一请求
即可由服务端按已完成层续传。

诚实边界（断点续传）：Ollama 服务端按层 digest 去重——同一实例上重发
POST /api/pull 即从已完成层续传，无需下载新层；客户端本身不做分片
断点。若模型沙盒目录被清空，则退化为全量重新下载。

用户可见文案铁律（零终端）：PullError 消息只描述状态与下一步动作，
绝不出现命令行、URL 或安装指引。
"""
# V099_HTTP_PULL_V1：应用内模型商店后端（AT-410，零终端；Ollama HTTP /api/pull）
from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

# 依赖 T-303b：内置 Ollama 运行时（get_runtime / models_dir）。
# import 失败即 [DEP_MISSING] T-303b——不允许 try 吞掉。
from acouscope.ai.ollama_runtime import get_runtime, models_dir
from acouscope.ai.backends.local_registry import OFFICIAL_MODELS, OLLAMA_BASE
from acouscope.ai.interpreter import CancelledError


class PullError(Exception):
    """拉取失败（用户可见中文文案，零终端：不含命令 / URL / 安装指引）。"""


def _default_base_url() -> str:
    """拉取目标地址：内置实例 ready 且端口非空 → 其动态端口；否则兜底默认地址。"""
    try:
        rt = get_runtime()
        if rt.state == "ready" and rt.base_url:
            return rt.base_url
    except Exception:
        pass
    return OLLAMA_BASE


def precheck_disk(model: str, path: str | Path | None = None) -> tuple[bool, str]:
    """磁盘空间预检：默认对准内置模型沙盒目录（models_dir()）。

    预估体积取 est_bytes * 1.2 余量；不足返回 (False, 中文文案)。
    """
    est = OFFICIAL_MODELS.get(model, {}).get("est_bytes", 2_000_000_000)
    target = Path(path) if path else models_dir()
    free = shutil.disk_usage(str(target)).free
    need = int(est * 1.2)
    if free < need:
        return False, (f"磁盘剩余 {free/1e9:.1f}GB 不足以容纳 {model}"
                       f"（预估需 {need/1e9:.1f}GB）")
    return True, "ok"


def pull_model(model: str, on_progress=None, is_cancelled=None,
               base_url: str | None = None) -> None:
    """阻塞式拉取官方模型（内置实例 HTTP /api/pull，NDJSON 流）。

    进度经 on_progress(0..1) 回调（按层 digest 聚合、单调不减）；
    取消抛 CancelledError；连接失败/服务端错误抛 PullError（零终端文案）。
    客户端不做分片断点：服务端按层 digest 去重，重发即续传。
    """
    ok, msg = precheck_disk(model)
    if not ok:
        raise PullError(msg)
    url = f"{(base_url or _default_base_url()).rstrip('/')}/api/pull"
    body = json.dumps({"name": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    layers: dict[str, tuple[int, int]] = {}
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                if is_cancelled is not None and is_cancelled():
                    resp.close()
                    raise CancelledError("pull cancelled")
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("error"):
                    raise PullError(str(obj["error"]))
                digest = obj.get("digest")
                total = obj.get("total")
                completed = obj.get("completed")
                if (digest
                        and isinstance(total, int) and total > 0
                        and isinstance(completed, int) and 0 <= completed <= total):
                    layers[digest] = (completed, total)
                    tot = sum(v[1] for v in layers.values())
                    done = sum(v[0] for v in layers.values())
                    if tot > 0 and on_progress is not None:
                        on_progress(max(0.0, min(1.0, done / tot)))
                if obj.get("status") == "success":
                    if on_progress is not None:
                        on_progress(1.0)
                    return
    except CancelledError:
        raise
    except PullError:
        raise  # 服务端错误行 / 预检失败：原样上抛，不再包装
    except urllib.error.URLError as e:
        # 连接失败类（拒绝/超时/DNS 等）→ 零终端文案
        raise PullError(
            "本地引擎未就绪。请在「设置-AI」启动内置引擎后重试，或切换远程模型。"
        ) from e
    except (ConnectionError, OSError) as e:
        raise PullError(
            "本地引擎未就绪。请在「设置-AI」启动内置引擎后重试，或切换远程模型。"
        ) from e
    except Exception as e:
        # 兜底包装：用户可见文案不泄露命令 / URL / 技术细节
        raise PullError(
            f"模型下载失败，请稍后重试：{type(e).__name__}"
        ) from e
