# SPDX-License-Identifier: GPL-3.0-only
"""官方严选本地模型注册表 + Ollama 环境自检（T-303）。

LOCAL_REGISTRY_V1 — Ollama 优先路线（Phase 0 决策：放弃 llama.cpp fork）。

T-1022 目录替换（最高指挥 2026-09-10 裁决：**纯文本模型一律不推荐/不上架**）：
原 `spark-x2.5-1.7b`（text_only=True，且占 is_default 推荐位）与 `qwen2.5:3b`
（text_only=True）整体下架——释图窗的本质是释图，本地档必须能读图。现目录
只保留**视觉**模型：每条带 `vision=True`、`min_ram_gb`、`est_bytes`（实测，
查询日期见下）；`text_only` 键保留但恒为 False（向后兼容旧读点）。
下架模型名记入 `LEGACY_TEXT_ONLY`，供视觉门禁识别历史配置（禁静默降级）。
"""
from __future__ import annotations

import json
import urllib.request

OLLAMA_BASE = "http://127.0.0.1:11434"  # 外部 Ollama 兜底地址（高级设置；默认走内置实例）


def active_base_url() -> str:
    """V099_RUNTIME_V1：当前应使用的 Ollama 基址。

    内置运行时就绪 → 其动态端口（端口隔离，不与用户自装 Ollama 冲突）；
    否则回退外部默认地址。任何异常都静默回退，绝不向调用方抛。
    """
    try:
        from acouscope.ai.ollama_runtime import get_runtime
        rt = get_runtime()
        if rt.state == "ready" and rt.base_url:
            return rt.base_url
    except Exception:
        pass
    return OLLAMA_BASE

#: 官方推荐本地模型注册表（T-1022 定稿）。key 即 ollama 模型名。
#: est_bytes 取自 2026-09-11 对 ollama 模型仓库 manifest 的真实查询
#: （各层 size 求和），禁编造：
#:   library/moondream:latest  1738450635
#:   library/llava:latest      4733362813
OFFICIAL_MODELS: dict[str, dict] = {
    "moondream": {
        "display": "Moondream 2（轻量视觉·默认推荐）",
        "est_bytes": 1738450635,
        "text_only": False,
        "vision": True,
        "min_ram_gb": 8.0,
        "tier_gb": 1.8,
        "mem_note": "建议 8GB+ 内存",
        "is_default": True,
    },
    "llava": {
        "display": "LLaVA 7B（视觉问答）",
        "est_bytes": 4733362813,
        "text_only": False,
        "vision": True,
        "min_ram_gb": 16.0,
        "tier_gb": 7.0,
        "mem_note": "建议 16GB+ 内存",
        "is_default": False,
    },
}

#: T-1022 下架的纯文本模型（历史配置识别用；**不得**再进任何推荐/列表）。
LEGACY_TEXT_ONLY: frozenset[str] = frozenset({
    "spark-x2.5-1.7b",
    "qwen2.5:3b",
})


def probe_ollama(timeout: float = 0.8, base_url: str | None = None) -> tuple[bool, list[str]]:
    """探测 Ollama（GET /api/tags）。

    base_url 为 None 时走 active_base_url()（内置实例优先，V099_RUNTIME_V1）。
    返回 (可用, 已装模型名列表)；连接失败 / 超时 / 解析错误 → (False, [])，
    绝不向调用方抛异常。
    """
    try:
        req = urllib.request.Request(f"{(base_url or active_base_url()).rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return True, [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return False, []


def get_missing_official_models(available: list[str] | None = None) -> list[str]:
    """计算注册表中尚未拉取的模型。

    available 为 None 时现场探测；Ollama 不可用视为全部缺失。
    模型名带/不带 :tag 均能匹配（如 "qwen2.5:3b" 与 "qwen2.5" 互认）。
    """
    if available is None:
        ok, available = probe_ollama()
        if not ok:
            return list(OFFICIAL_MODELS)
    have = {a.split(":")[0] for a in available} | set(available)
    return [n for n in OFFICIAL_MODELS if n not in have and n.split(":")[0] not in have]


def guidance_text() -> str:
    """返回本地引擎状态文案（V099_RUNTIME_V1，AT-410 零终端铁律）。

    禁出现任何命令行/URL/安装指引；目标用户是田野研究者而非工程师。
    """
    ok, models = probe_ollama()
    if not ok:
        return ("本地引擎未就绪。首次释图时 AcouScope 会自动启动内置引擎；"
                "也可在「设置-AI」下载模型，或在高级设置中切换远程模型。")
    missing = get_missing_official_models(models)
    if missing:
        return ("模型尚未下载：" + "、".join(missing) +
                "。请在「设置-AI」点击「下载选中模型」，或切换远程模型。")
    return "本地引擎就绪，推荐模型已齐备。"
