# SPDX-License-Identifier: GPL-3.0-only
"""T-929 内存防护与防崩（memguard）。

分层防护（静默优先，永不阻塞用户操作）：
  §1 可用内存检测 —— `available_memory_mb()`：可选依赖 `psutil` 优先，未安装则走
     免依赖原生分支（macOS `host_statistics64` / Linux `/proc/meminfo` /
     Windows `GlobalMemoryStatusEx`）；全部失败 → `None`（调用方静默跳过防护）。
  §2 长任务预检 —— `preflight(settings)`：可用内存低于低阈值 → 返回低内存裁决，
     由 UI 走**非模态**提示（本模块不触 Qt）。
  §3 模型闲置卸载 —— `ModelIdleUnloader` 按白名单把 SOTA 后端 ONNX session 及其
     派生对象置 `None` + `gc.collect()`（**不改 `analysis/**` 任何文件**）。
  §4 多轨协同 —— `relieve_pressure(session)` 只读复用既有 LRU 接口
     （`MultitrackSession.unload_inactive`）。
  §5 压力兜底 —— `MemoryPressureMonitor`：低于危急阈值持续 > `MEMGUARD_SUSTAIN_S`
     → 触发一次兜底回调；频率上限 `MEMGUARD_AUTOSAVE_MIN_INTERVAL_S`。

铁律：零硬依赖（`pyproject.toml` / `requirements.txt` 零改动）、零 Qt、零终端输出；
检测仅"读"，异常一律 `None` / 空结果（静默跳过，永不阻塞）。
"""

from __future__ import annotations

import ctypes
import gc
import importlib
import os
import sys
import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# K2 权威常量（`utils/config.py:Settings` 默认值须与本处逐值一致；测试断言两处口径）
# ---------------------------------------------------------------------------

MEMGUARD_LOW_THRESHOLD_MB = 512
MEMGUARD_CRITICAL_THRESHOLD_MB = 200
MEMGUARD_MODEL_IDLE_MINUTES = 10

# 兜底时序（§5）
MEMGUARD_SUSTAIN_S = 5.0
MEMGUARD_AUTOSAVE_MIN_INTERVAL_S = 300.0

# 设置钳位范围（非法/越界一律回退默认，照 `utils/config.py:_clamp_int_setting` 范式）
LOW_THRESHOLD_RANGE = (64, 8192)
CRITICAL_THRESHOLD_RANGE = (64, 8192)
MODEL_IDLE_MINUTES_RANGE = (1, 240)

STATUS_OK = "ok"
STATUS_LOW = "low"
STATUS_CRITICAL = "critical"

_MB = 1024.0 * 1024.0
_HOST_VM_INFO64 = 4  # mach host_statistics64 flavor


# ---------------------------------------------------------------------------
# §1 可用内存检测（仅"读"；异常 → None）
# ---------------------------------------------------------------------------

class _VmStatistics64(ctypes.Structure):
    """macOS `vm_statistics64_data_t`（natural_t 为 32 位，uint64 紧随其后）。"""

    _fields_ = [
        ("free_count", ctypes.c_uint32),
        ("active_count", ctypes.c_uint32),
        ("inactive_count", ctypes.c_uint32),
        ("wire_count", ctypes.c_uint32),
        ("zero_fill_count", ctypes.c_uint64),
        ("reactivations", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("pageouts", ctypes.c_uint64),
        ("faults", ctypes.c_uint64),
        ("cow_faults", ctypes.c_uint64),
        ("lookups", ctypes.c_uint64),
        ("hits", ctypes.c_uint64),
        ("purges", ctypes.c_uint64),
        ("purgeable_count", ctypes.c_uint32),
        ("speculative_count", ctypes.c_uint32),
        ("decompressions", ctypes.c_uint64),
        ("compressions", ctypes.c_uint64),
        ("swapins", ctypes.c_uint64),
        ("swapouts", ctypes.c_uint64),
        ("compressor_page_count", ctypes.c_uint32),
        ("throttled_count", ctypes.c_uint32),
        ("external_page_count", ctypes.c_uint32),
        ("internal_page_count", ctypes.c_uint32),
        ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
    ]


class _MemoryStatusEx(ctypes.Structure):
    """Windows `MEMORYSTATUSEX`。"""

    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def available_memory_mb() -> float | None:
    """当前可用内存（MB）；检测失败一律 `None`（调用方静默跳过防护）。"""
    for probe in (_available_via_psutil, _available_native):
        try:
            value = probe()
        except Exception:  # noqa: BLE001 — 检测失败不得阻塞任何用户操作
            value = None
        if value is not None:
            return float(value)
    return None


def _available_via_psutil() -> float | None:
    """psutil 分支（可选依赖；未安装 → None，不新增硬依赖）。"""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return None
    try:
        return float(psutil.virtual_memory().available) / _MB
    except Exception:  # noqa: BLE001
        return None


def _available_native() -> float | None:
    """免依赖分支：按平台分派（未知平台 → None）。"""
    if sys.platform == "darwin":
        return _available_macos()
    if sys.platform.startswith("linux"):
        return _available_linux()
    if sys.platform.startswith("win"):
        return _available_windows()
    return None


def _available_macos() -> float | None:
    """macOS：`host_statistics64` 的 free + inactive（可回收页）× 页大小。"""
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    stats = _VmStatistics64()
    count = ctypes.c_uint32(ctypes.sizeof(stats) // ctypes.sizeof(ctypes.c_uint32))
    rc = libc.host_statistics64(
        libc.mach_host_self(),
        ctypes.c_int(_HOST_VM_INFO64),
        ctypes.byref(stats),
        ctypes.byref(count),
    )
    if rc != 0:
        return None
    page_size = int(os.sysconf("SC_PAGE_SIZE"))
    pages = int(stats.free_count) + int(stats.inactive_count)
    return float(pages * page_size) / _MB


def _available_linux() -> float | None:
    """Linux：`/proc/meminfo` 的 `MemAvailable`。"""
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return float(line.split()[1]) / 1024.0
    return None


def _available_windows() -> float | None:
    """Windows：`GlobalMemoryStatusEx` 的 `ullAvailPhys`。"""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return float(status.ullAvailPhys) / _MB


# ---------------------------------------------------------------------------
# §2 阈值与预检（纯判定，不触 Qt）
# ---------------------------------------------------------------------------

def clamp_threshold(value, default: int, bounds: tuple[int, int]) -> int:
    """整数钳位：非法/越界一律回退 default（照 `_clamp_int_setting` 既有范式）。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    low, high = bounds
    if number < low or number > high:
        return default
    return number


def thresholds_from_settings(settings=None) -> tuple[int, int, int]:
    """(低阈值 MB, 危急阈值 MB, 模型闲置分钟)；缺失/非法 → K2 权威常量。

    与 `utils/config.py:Settings.load()` 同口径（默认值逐值一致）。
    """
    low = clamp_threshold(
        getattr(settings, "memguard_low_threshold_mb", None),
        MEMGUARD_LOW_THRESHOLD_MB, LOW_THRESHOLD_RANGE,
    )
    critical = clamp_threshold(
        getattr(settings, "memguard_critical_threshold_mb", None),
        MEMGUARD_CRITICAL_THRESHOLD_MB, CRITICAL_THRESHOLD_RANGE,
    )
    if critical > low:  # 危急阈值不得高于低阈值（否则两级语义倒置）→ 回退可比值
        critical = min(MEMGUARD_CRITICAL_THRESHOLD_MB, low)
    idle = clamp_threshold(
        getattr(settings, "memguard_model_idle_minutes", None),
        MEMGUARD_MODEL_IDLE_MINUTES, MODEL_IDLE_MINUTES_RANGE,
    )
    return low, critical, idle


def memory_status(available_mb, *, low_mb=None, critical_mb=None) -> str:
    """阈值判定；`None`（检测失败）视为 `STATUS_OK` = 静默跳过防护。"""
    if available_mb is None:
        return STATUS_OK
    low = MEMGUARD_LOW_THRESHOLD_MB if low_mb is None else int(low_mb)
    critical = MEMGUARD_CRITICAL_THRESHOLD_MB if critical_mb is None else int(critical_mb)
    if float(available_mb) < critical:
        return STATUS_CRITICAL
    if float(available_mb) < low:
        return STATUS_LOW
    return STATUS_OK


@dataclass(frozen=True)
class PreflightResult:
    """预检裁决（`is_low=True` → UI 走非模态提示「仍继续 / 取消」）。"""

    status: str
    available_mb: float | None
    low_mb: int
    critical_mb: int

    @property
    def is_low(self) -> bool:
        return self.status != STATUS_OK


def preflight(settings=None, *, available_mb=None) -> PreflightResult:
    """长任务启动前预检（§2）：采样 + 阈值判定，永不抛异常。"""
    low, critical, _idle = thresholds_from_settings(settings)
    if available_mb is None:
        try:
            available_mb = available_memory_mb()
        except Exception:  # noqa: BLE001
            available_mb = None
    return PreflightResult(
        status=memory_status(available_mb, low_mb=low, critical_mb=critical),
        available_mb=available_mb,
        low_mb=low,
        critical_mb=critical,
    )


# ---------------------------------------------------------------------------
# §3 模型闲置卸载（K3：只从外部置空类级属性，禁改 analysis/**）
# ---------------------------------------------------------------------------
# 实读依据（2026-09-12）：`analysis/backends/base.py:PitchBackend` Protocol 仅
# `detect` / `is_available`，后端**无** `unload()` / `reset()` 入口；session 为
# **类级全局**，在 `__init__ → _ensure_model()` 内以「双重检查 + threading.Lock」
# 懒建（`_session is not None` 即直接返回）→ 外部置空 `_session` 后再次构造/`detect`
# 会走同一加载路径重建，结果与首次等价（测试断言）。
# 白名单按类**逐名**声明：RMVPE 有 `_mel_extractor`，SwiftF0 无。

SESSION_WHITELIST: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "RMVPE",
        "acouscope.analysis.backends.rmvpe",
        "RMVPEBackend",
        ("_session", "_input_name", "_output_name", "_mel_extractor"),
    ),
    (
        "SwiftF0",
        "acouscope.analysis.backends.swift_f0",
        "SwiftF0Backend",
        ("_session", "_input_name"),
    ),
)


def _resolve_backend_class(module_path: str, class_name: str):
    """按白名单解析后端类；模块不可导入（缺 onnxruntime 等）→ None。"""
    try:
        module = importlib.import_module(module_path)
    except Exception:  # noqa: BLE001
        return None
    return getattr(module, class_name, None)


def loaded_model_names() -> list[str]:
    """已加载（`_session` 非 None）的 SOTA 后端名（只读判定）。"""
    names: list[str] = []
    for name, module_path, class_name, _attrs in SESSION_WHITELIST:
        cls = _resolve_backend_class(module_path, class_name)
        if cls is not None and getattr(cls, "_session", None) is not None:
            names.append(name)
    return names


def free_model_sessions(names=None) -> list[str]:
    """按白名单把 `names`（None = 全部已加载）的 session 与派生对象置 None + gc。

    仅从外部置空类级属性，**不改任何后端文件**；调用方须确保此刻无分析在跑
    （在跑推理中卸载会破坏该次结果 → 由 `ModelIdleUnloader(busy=True)` 守卫）。
    """
    target = None if names is None else set(names)
    freed: list[str] = []
    for name, module_path, class_name, attrs in SESSION_WHITELIST:
        if target is not None and name not in target:
            continue
        cls = _resolve_backend_class(module_path, class_name)
        if cls is None or getattr(cls, "_session", None) is None:
            continue
        for attr in attrs:
            setattr(cls, attr, None)
        freed.append(name)
    if freed:
        gc.collect()
    return freed


class ModelIdleUnloader:
    """§3 模型闲置卸载：闲置满 N 分钟 → 释放 session；分析在跑时一律跳过。"""

    def __init__(self, *, idle_minutes=None, sample_loaded=None, free_fn=None, now=None):
        minutes = MEMGUARD_MODEL_IDLE_MINUTES if idle_minutes is None else int(idle_minutes)
        self.idle_s = max(0.0, float(minutes) * 60.0)
        self._loaded = sample_loaded or loaded_model_names
        self._free = free_fn or free_model_sessions
        self._now = now or time.monotonic
        self._last_seen: dict[str, float] = {}

    def note(self, name: str, *, at=None) -> None:
        """标记该后端刚被使用（闲置计时起点）。"""
        self._last_seen[str(name)] = self._now() if at is None else float(at)

    def poll(self, *, busy: bool = False, at=None) -> list[str]:
        """返回本次卸载的后端名；`busy=True`（分析在跑）→ 不卸载（保结果不变）。"""
        if busy:
            return []
        moment = self._now() if at is None else float(at)
        try:
            loaded = list(self._loaded())
        except Exception:  # noqa: BLE001
            return []
        stale: list[str] = []
        for name in loaded:
            seen = self._last_seen.get(name)
            if seen is None:
                self._last_seen[name] = moment  # 首次发现即计时起点（不立即卸载）
                continue
            if moment - seen >= self.idle_s:
                stale.append(name)
        if not stale:
            return []
        try:
            freed = list(self._free(stale))
        except Exception:  # noqa: BLE001
            return []
        for name in freed:
            self._last_seen.pop(name, None)
        return freed


# ---------------------------------------------------------------------------
# §4 多轨协同（K4：只读复用既有 LRU 接口；禁改 ui/widgets/multitrack/**）
# ---------------------------------------------------------------------------

def release_inactive_tracks(session) -> list[str]:
    """释放非活跃轨样本（复用 `MultitrackSession.unload_inactive`，只读调用）。"""
    if session is None:
        return []
    try:
        return list(session.unload_inactive())
    except Exception:  # noqa: BLE001
        return []


def relieve_pressure(session=None, *, unload_models: bool = True) -> dict:
    """压力序列：**先**卸不活跃轨 buffer，**后**卸模型 session（K4 口径）。"""
    return {
        "tracks": release_inactive_tracks(session),
        "models": free_model_sessions() if unload_models else [],
    }


# ---------------------------------------------------------------------------
# §5 内存压力兜底（无可靠跨平台「压力事件」API → 绝对下限 + 持续 + 限频）
# ---------------------------------------------------------------------------

class MemoryPressureMonitor:
    """低于危急阈值持续 > `sustain_s` → `poll()` 返回一次 True；频率上限 `min_interval_s`。"""

    def __init__(self, *, critical_mb=None, sustain_s: float = MEMGUARD_SUSTAIN_S,
                 min_interval_s: float = MEMGUARD_AUTOSAVE_MIN_INTERVAL_S,
                 sample_fn=None, now=None):
        critical = MEMGUARD_CRITICAL_THRESHOLD_MB if critical_mb is None else int(critical_mb)
        self.critical_mb = critical
        self.sustain_s = float(sustain_s)
        self.min_interval_s = float(min_interval_s)
        self._sample = sample_fn or available_memory_mb
        self._now = now or time.monotonic
        self._below_since: float | None = None
        self._last_fire: float | None = None

    def poll(self, *, at=None) -> bool:
        """True = 本次应触发兜底（一次 autosave + 非模态警告）。"""
        moment = self._now() if at is None else float(at)
        try:
            available = self._sample()
        except Exception:  # noqa: BLE001
            available = None
        if available is None:  # 检测失败 → 静默跳过（并清持续计时）
            self._below_since = None
            return False
        if float(available) >= self.critical_mb:
            self._below_since = None
            return False
        if self._below_since is None:
            self._below_since = moment
            return False
        if moment - self._below_since < self.sustain_s:
            return False
        if self._last_fire is not None and (moment - self._last_fire) < self.min_interval_s:
            return False
        self._last_fire = moment
        return True
