# SPDX-License-Identifier: GPL-3.0-only
"""模型推荐规则（T-1022，纯函数 / 表驱动）。

释图窗的本质是**释图**——图片必须先能被模型「看见」。因此本模块的第一条
硬约束是：**`vision=False` 的条目不出现在任何推荐结果里**（测试锁死）。
目录侧（`ai/llama_models.py`、`ai/backends/local_registry.py`）已把纯文本
模型下架，本模块再在推荐/列表出口做一次兜底过滤，双保险。

规则（最高指挥 2026-09-10 裁决）：
- 内存不足 = **软提示**（标 `insufficient_ram` 风险徽标，仍可被高级用户选择，
  故它只是「推荐位」的排除项，不是「列表」的排除项）；
- 视觉能力 = **硬门禁**（`vision=False` 一律不出现）；
- 磁盘不足（`est_bytes × 1.2 > 可用空间`）= `insufficient_disk`，优先于内存
  判定（磁盘是当下立刻失败，内存只是风险）；
- 探测到**可达的 OpenAI 兼容外部服务** → `prefer_remote`：优先提示「用现成
  服务」而非下载（省磁盘）。
"""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

#: 推荐档位（fit）取值。
FIT_RECOMMENDED = "recommended"
FIT_OK = "ok"
FIT_LOW_RAM = "insufficient_ram"
FIT_LOW_DISK = "insufficient_disk"

#: 磁盘余量系数（与 llama_models.precheck_disk / model_manager 同口径）。
DISK_MARGIN = 1.2

#: 内存分档阈值（GB）：≥32 可推 7B 档；16~32 推 3B 档；<16 推最小 VL 档。
RAM_TIER_7B = 32.0
RAM_TIER_3B = 16.0

#: 外部 OpenAI 兼容服务探测端点（局域网推理机在前，本机在后）。
#: 探测用短超时、失败静默；仅读 `/v1/models` 是否可达，不发送任何数据。
DEFAULT_REMOTE_ENDPOINTS: tuple[str, ...] = (
    "http://192.168.0.2:8000/v1/models",
    "http://127.0.0.1:8000/v1/models",
)

#: 展示排序权重（小者在前）。
_FIT_ORDER = {
    FIT_RECOMMENDED: 0,
    FIT_OK: 1,
    FIT_LOW_RAM: 2,
    FIT_LOW_DISK: 3,
}

_GB = 1024 ** 3

#: 未知视觉能力的提示（用户自填云端模型名 / 局域网自建端点：允许选择但标注）。
VISION_UNVERIFIED = "unverified"


@dataclass(frozen=True)
class CatalogEntry:
    """统一目录条目（GGUF 与 Ollama 两路归一，便于表驱动测试）。

    - vision：视觉能力（False = 硬门禁，任何列表/推荐都不出现）；
    - est_bytes：模型**全部文件**合计体积（GGUF 含 mmproj 视觉塔）；
    - min_ram_gb：跑该模型建议的最小内存（软提示阈值）；
    - tier_gb：参数量档位（用于按内存分档挑推荐位，如 1.8 / 3.0 / 7.0）。
    """

    model_id: str
    display_name: str
    vision: bool
    est_bytes: int
    min_ram_gb: float
    tier_gb: float
    source: str          # "gguf"（内置引擎直跑） / "ollama"（内置 Ollama 档）


@dataclass(frozen=True)
class Recommendation:
    """单条推荐结果：档位 + 人话理由（UI 直接展示，零终端）。"""

    model_id: str
    fit: str
    reason: str
    entry: CatalogEntry


def size_text(nbytes: int | float) -> str:
    """体积人话文案（GB / MB 自适应，零终端）。"""
    n = float(nbytes or 0)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    return f"{round(n / 1_000_000)} MB"


def vision_entries(catalog: Iterable[CatalogEntry]) -> tuple[CatalogEntry, ...]:
    """目录中**视觉**条目（硬门禁出口：任何列表/推荐都从这里取）。

    `vision` 非真（含 None / 缺失）一律过滤——保守侧不推荐无法读图的模型。
    """
    return tuple(e for e in catalog if bool(getattr(e, "vision", False)))


def _disk_ok(entry: CatalogEntry, disk_free_gb: float | None) -> bool:
    if disk_free_gb is None:
        return True
    return entry.est_bytes * DISK_MARGIN <= disk_free_gb * _GB


def _ram_ok(entry: CatalogEntry, ram_gb: float | None) -> bool:
    if ram_gb is None:
        return True
    return entry.min_ram_gb <= ram_gb


def _target_tier(ram_gb: float | None, entries: Sequence[CatalogEntry]) -> float | None:
    """按内存定「推荐档位」目标（tier_gb）；内存未知 → None（不给推荐位）。"""
    if not entries or ram_gb is None:
        return None
    tiers = sorted({e.tier_gb for e in entries})
    if ram_gb >= RAM_TIER_7B:
        return tiers[-1]
    if ram_gb >= RAM_TIER_3B:
        # 3B 档：不超过 3.0 的最大档位；目录只有 7B 时退化为最小档
        candidates = [t for t in tiers if t <= 3.0]
        return candidates[-1] if candidates else tiers[0]
    return tiers[0]


def recommend_models(
    profile,
    catalog: Iterable[CatalogEntry],
    remote_reachable: bool = False,
) -> tuple[Recommendation, ...]:
    """按硬件探测结论给出推荐列表（纯函数；vision=False 永不出现）。

    Args:
        profile: `ai.hardware.HardwareProfile`（或任何含 ram_gb / disk_free_gb
                 属性的对象；缺失字段按 None = 不设限处理）
        catalog: 候选条目（vision 非真者被硬过滤）
        remote_reachable: 是否已探到可用外部服务（True 时理由里提示免下载）

    Returns:
        推荐结果元组，按（档位权重，tier_gb 降序）排序；推荐位至多一条。
    """
    ram = getattr(profile, "ram_gb", None)
    disk = getattr(profile, "disk_free_gb", None)
    entries = vision_entries(catalog)

    fits: list[tuple[CatalogEntry, str]] = []
    for entry in entries:
        if not _disk_ok(entry, disk):
            fits.append((entry, FIT_LOW_DISK))
        elif not _ram_ok(entry, ram):
            fits.append((entry, FIT_LOW_RAM))
        else:
            fits.append((entry, FIT_OK))

    target = _target_tier(ram, [e for e, f in fits if f == FIT_OK])
    chosen: str | None = None
    if target is not None:
        usable = [(e, f) for e, f in fits if f == FIT_OK]
        below = [(e, f) for e, f in usable if e.tier_gb <= target]
        pool = below or usable
        if pool:
            chosen = max(pool, key=lambda p: p[0].tier_gb)[0].model_id

    out: list[Recommendation] = []
    for entry, fit in fits:
        if entry.model_id == chosen:
            fit = FIT_RECOMMENDED
        out.append(Recommendation(
            model_id=entry.model_id,
            fit=fit,
            reason=_reason(entry, fit, ram, disk, remote_reachable),
            entry=entry,
        ))
    out.sort(key=lambda r: (_FIT_ORDER.get(r.fit, 9), -r.entry.tier_gb))
    return tuple(out)


def _reason(entry: CatalogEntry, fit: str, ram: float | None,
            disk: float | None, remote_reachable: bool) -> str:
    """人话理由（零终端：不含命令 / URL / 版本号等工程细节）。"""
    if fit == FIT_LOW_DISK:
        return (f"磁盘可用空间不足：该模型需约 {size_text(entry.est_bytes * DISK_MARGIN)}，"
                f"当前可用约 {size_text((disk or 0) * _GB)}")
    if fit == FIT_LOW_RAM:
        return (f"内存可能不足：建议至少 {entry.min_ram_gb:.0f}GB，"
                f"当前约 {0 if ram is None else ram:.0f}GB（仍可下载试用）")
    if fit == FIT_RECOMMENDED:
        base = "与本机配置匹配；模型可读图，可直接下载使用"
        if remote_reachable:
            base += "；已检测到现成服务，也可先直接使用它，无需下载"
        return base
    if ram is None:
        return "硬件信息不可用：未做内存匹配，可读图"
    return "可读图，与当前内存匹配（非首选档位）"


# ---------------------------------------------------------------------------
# 外部服务探测（prefer_remote）
# ---------------------------------------------------------------------------

def _http_ok(url: str, timeout: float) -> bool:
    """端点是否可达（HTTP 状态 < 500 即视为有服务在监听）；失败静默 False。"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
        return 200 <= int(code) < 500
    except Exception:
        return False


def _service_root(url: str) -> str:
    """把 `/v1/models` 探测地址归一为服务根地址（供 UI 展示）。"""
    text = (url or "").strip().rstrip("/")
    for suffix in ("/v1/models", "/models", "/v1"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def detect_remote_service(
    timeout: float = 0.6,
    endpoints: Sequence[str] | None = None,
    probe_fn: Callable[[str, float], bool] | None = None,
) -> str | None:
    """探测可达的 OpenAI 兼容外部服务，返回服务根地址；均不可达 → None。

    短超时、失败静默（绝不抛、绝不阻塞 UI）；探测只读 `/v1/models`，
    不发送任何用户数据。
    """
    probe = probe_fn or _http_ok
    for url in (endpoints or DEFAULT_REMOTE_ENDPOINTS):
        try:
            if probe(url, timeout):
                return _service_root(url)
        except Exception:
            continue
    return None


def prefer_remote(
    remote: str | None = None,
    timeout: float = 0.6,
    endpoints: Sequence[str] | None = None,
    probe_fn: Callable[[str, float], bool] | None = None,
) -> bool:
    """是否应优先推荐「用现成服务」（省磁盘）；remote 为 None 时现场探测。"""
    if remote is not None:
        return bool(remote)
    return bool(detect_remote_service(timeout=timeout, endpoints=endpoints,
                                      probe_fn=probe_fn))


# ---------------------------------------------------------------------------
# 目录适配（GGUF 受管模型 / 内置 Ollama 官方档 → 统一条目）
# ---------------------------------------------------------------------------

def gguf_catalog() -> tuple[CatalogEntry, ...]:
    """受管 GGUF 目录（内置引擎直跑；含视觉塔体积）→ 统一条目。"""
    try:
        from acouscope.ai import llama_models
        models = tuple(llama_models.list_models())
    except Exception:
        return ()
    return tuple(
        CatalogEntry(
            model_id=m.model_id,
            display_name=m.display_name,
            vision=bool(getattr(m, "vision", False)),
            est_bytes=int(getattr(m, "est_bytes", 0) or 0),
            min_ram_gb=float(getattr(m, "min_ram_gb", 0.0) or 0.0),
            tier_gb=float(getattr(m, "tier_gb", 0.0) or 0.0),
            source="gguf",
        )
        for m in models
    )


def ollama_catalog() -> tuple[CatalogEntry, ...]:
    """内置 Ollama 官方档目录 → 统一条目。"""
    try:
        from acouscope.ai.backends.local_registry import OFFICIAL_MODELS
    except Exception:
        return ()
    return tuple(
        CatalogEntry(
            model_id=name,
            display_name=str(meta.get("display", name)),
            vision=bool(meta.get("vision", False)),
            est_bytes=int(meta.get("est_bytes", 0) or 0),
            min_ram_gb=float(meta.get("min_ram_gb", 0.0) or 0.0),
            tier_gb=float(meta.get("tier_gb", 0.0) or 0.0),
            source="ollama",
        )
        for name, meta in OFFICIAL_MODELS.items()
    )


def builtin_catalog() -> tuple[CatalogEntry, ...]:
    """内置档全部可选模型（受管 GGUF + 内置 Ollama 官方档；纯文本已过滤）。"""
    return vision_entries(gguf_catalog() + ollama_catalog())
