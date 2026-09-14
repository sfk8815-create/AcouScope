# SPDX-License-Identifier: GPL-3.0-only
"""硬件规格探测（T-1022）。

用途：为「设置 → AI」与释图窗模型选择器提供本机算力结论（芯片 / 内存 /
磁盘可用 / 是否 Apple Silicon），并驱动 `ai.model_recommend` 的模型推荐与
UI 上的「本机推荐 / 内存不足 / 磁盘不足」徽标。

【隐私红线】只读硬件**规格**（内存容量、芯片型号名、核数、磁盘可用空间、
是否 Apple Silicon），**禁采集任何设备唯一标识**——序列号 / 硬件 UUID /
机器码 / MAC 地址一律不读；允许的字段白名单见 `PRIVACY_FIELDS`，由
`tests/test_hardware_probe.py` 锁死（新增字段必须同步白名单，评审可见）。

【健壮性】全部探测走 stdlib（零新依赖），任一项失败（命令缺失 / 权限受限 /
输出格式变化）只把该字段置 `None` 并继续，**绝不抛异常、绝不阻断 UI**。
`probe()` 结果在会话内缓存（`refresh=True` 强制重探）。

平台分支：macOS 用 `sysctl`（必要时 `system_profiler` 取 GPU 核数）；
Windows 用 `GlobalMemoryStatusEx`；Linux 用 `/proc/meminfo` + `os.cpu_count()`。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

#: 允许出现在 HardwareProfile 上的字段白名单（隐私红线：不含任何唯一标识）。
PRIVACY_FIELDS: tuple[str, ...] = (
    "ram_gb",
    "chip",
    "model_id",
    "is_apple_silicon",
    "cpu_cores",
    "gpu_cores",
    "disk_free_gb",
    "unified_memory",
)

_GB = 1024 ** 3
#: 外部命令超时（system_profiler 较慢，给足余量；失败即放弃该字段）。
_CMD_TIMEOUT = 8.0


@dataclass(frozen=True)
class HardwareProfile:
    """本机硬件规格（字段不可得一律 None，绝不抛）。

    model_id 为**机型类名**（如 `Mac16,10`），非设备唯一标识。
    unified_memory：Apple Silicon 统一内存架构（GPU 与 CPU 共享内存）。
    """

    ram_gb: float | None = None
    chip: str | None = None
    model_id: str | None = None
    is_apple_silicon: bool | None = None
    cpu_cores: int | None = None
    gpu_cores: int | None = None
    disk_free_gb: float | None = None
    unified_memory: bool | None = None

    def as_dict(self) -> dict:
        """字段字典（仅白名单字段，供 UI / 报告序列化）。"""
        return asdict(self)

    def summary(self, unknown: str = "") -> str:
        """一行探测结论（缺失字段跳过；全缺 → unknown 文案）。"""
        parts: list[str] = []
        if self.chip:
            parts.append(str(self.chip))
        if self.ram_gb is not None:
            parts.append(f"{self.ram_gb:.0f}GB")
        if self.disk_free_gb is not None:
            parts.append(f"{self.disk_free_gb:.0f}GB")
        return " · ".join(parts) if parts else unknown


# ---------------------------------------------------------------------------
# 基础设施（全部包裹异常，单点失败不扩散）
# ---------------------------------------------------------------------------

def _platform() -> str:
    """当前平台标识（薄封装：测试可打桩遍历三分支）。"""
    return sys.platform


def _run(argv: list[str]) -> str | None:
    """执行外部命令并返回 stdout 文本；任何失败返回 None（绝不抛）。"""
    try:
        out = subprocess.run(
            argv, capture_output=True, timeout=_CMD_TIMEOUT, check=False)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        return out.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def _read_text(path: str | Path) -> str | None:
    """读取文本文件；失败返回 None（绝不抛）。"""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _sysctl(name: str) -> str | None:
    """`sysctl -n <name>` → 去空白文本；失败返回 None。"""
    out = _run(["sysctl", "-n", name])
    if out is None:
        return None
    text = out.strip()
    return text or None


def _to_int(text: str | None) -> int | None:
    try:
        return int(str(text).strip())
    except Exception:
        return None


def _to_gb(nbytes: int | None) -> float | None:
    if nbytes is None or nbytes <= 0:
        return None
    return round(nbytes / _GB, 1)


def models_target_dir() -> Path:
    """磁盘可用空间的统计目标（模型沙盒目录所在盘；不可得则退用户主目录）。

    数据目录**调用期解析**（`acouscope.utils.config.get_data_dir` 现场取），
    便于宿主/测试重定向数据目录后本函数随之生效。
    """
    try:
        from acouscope.utils.config import get_data_dir
        return get_data_dir() / "llama_models"
    except Exception:
        return Path.home()


def _disk_free_gb(target: str | Path) -> float | None:
    """目标路径所在卷的可用空间（GB）；失败返回 None。"""
    try:
        return _to_gb(shutil.disk_usage(str(target)).free)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 平台分支
# ---------------------------------------------------------------------------

def _macos_gpu_cores() -> int | None:
    """GPU 核数（`system_profiler SPDisplaysDataType` 的 "Total Number of Cores"）。

    输出形如 `Total Number of Cores: 10`；Apple Silicon 多显示器时取首条。
    命令不存在 / 输出格式变化 → None（绝不抛）。
    """
    out = _run(["system_profiler", "SPDisplaysDataType"])
    if not out:
        return None
    for line in out.splitlines():
        key, sep, value = line.partition(":")
        if sep and "total number of cores" in key.strip().lower():
            num = _to_int(value.strip().split()[0] if value.strip() else None)
            if num:
                return num
    return None


def _probe_macos(target: str | Path, with_gpu: bool = True) -> HardwareProfile:
    """macOS：sysctl（memsize / model / brand_string / ncpu / arm64）+ 磁盘。

    with_gpu=False 跳过 `system_profiler`（本机实测约 4 秒，不适合 UI 构造
    路径常显；GPU 核数按需探测）。
    """
    ram = _to_int(_sysctl("hw.memsize"))
    model_id = _sysctl("hw.model")
    chip = _sysctl("machdep.cpu.brand_string")
    cpu = _to_int(_sysctl("hw.ncpu")) or os.cpu_count()
    arm = _sysctl("hw.optional.arm64")
    if arm is not None:
        apple: bool | None = arm.strip() == "1"
    elif chip:
        apple = "apple" in chip.lower()
    else:
        apple = None
    return HardwareProfile(
        ram_gb=_to_gb(ram),
        chip=chip,
        model_id=model_id,
        is_apple_silicon=apple,
        cpu_cores=cpu,
        gpu_cores=_macos_gpu_cores() if (apple and with_gpu) else None,
        disk_free_gb=_disk_free_gb(target),
        unified_memory=apple,
    )


class _MemoryStatusEx(ctypes.Structure):
    """Win32 MEMORYSTATUSEX（仅取 ullTotalPhys；不涉及任何标识）。"""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_ram_bytes() -> int | None:
    """物理内存总量（GlobalMemoryStatusEx）；非 Windows / 失败 → None。"""
    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        if not ok:
            return None
        return int(status.ullTotalPhys)
    except Exception:
        return None


def _probe_windows(target: str | Path, with_gpu: bool = True) -> HardwareProfile:
    """Windows：GlobalMemoryStatusEx + 环境变量机型名 + 逻辑核数（无 GPU 探测）。"""
    chip = os.environ.get("PROCESSOR_IDENTIFIER", "").strip() or None
    return HardwareProfile(
        ram_gb=_to_gb(_windows_ram_bytes()),
        chip=chip,
        model_id=None,
        is_apple_silicon=False,
        cpu_cores=os.cpu_count(),
        gpu_cores=None,
        disk_free_gb=_disk_free_gb(target),
        unified_memory=False,
    )


def _linux_ram_bytes() -> int | None:
    """`/proc/meminfo` 的 MemTotal（kB → 字节）；失败 → None。"""
    text = _read_text("/proc/meminfo")
    if not text:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "MemTotal":
            kb = _to_int(value.strip().split()[0] if value.strip() else None)
            return kb * 1024 if kb else None
    return None


def _probe_linux(target: str | Path, with_gpu: bool = True) -> HardwareProfile:
    """Linux：/proc/meminfo + 机型文件（product_name，非唯一标识）。"""
    chip = None
    text = _read_text("/proc/cpuinfo")
    if text:
        for line in text.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() in ("model name", "hardware"):
                chip = value.strip() or None
                break
    model_id = None
    vendor = _read_text("/sys/devices/virtual/dmi/id/product_name")
    if vendor:
        model_id = vendor.strip() or None
    return HardwareProfile(
        ram_gb=_to_gb(_linux_ram_bytes()),
        chip=chip,
        model_id=model_id,
        is_apple_silicon=False,
        cpu_cores=os.cpu_count(),
        gpu_cores=None,
        disk_free_gb=_disk_free_gb(target),
        unified_memory=False,
    )


#: 平台分支表（键 = sys.platform 前缀；测试可打桩 `_platform()` 逐一走查）。
_PROBES: dict[str, Callable[..., HardwareProfile]] = {
    "darwin": _probe_macos,
    "win32": _probe_windows,
    "cygwin": _probe_windows,
    "linux": _probe_linux,
    "freebsd": _probe_linux,
}

#: 会话缓存（键 = with_gpu，两种粒度各自缓存；避免 UI 反复探测）。
_cache: dict[bool, HardwareProfile] = {}


def probe(refresh: bool = False, with_gpu: bool = True) -> HardwareProfile:
    """探测本机硬件规格（会话内缓存；任意失败只降级字段，绝不抛）。

    Args:
        refresh: True 时忽略缓存重新探测。
        with_gpu: 是否探测 GPU 核数（macOS 走 `system_profiler`，本机实测约
            4 秒——UI 常显路径传 False，需要时（诊断/报告）再按需探测）。

    Returns:
        HardwareProfile；探测整体失败时返回空 profile（仅尽力填充磁盘字段）。
    """
    key = bool(with_gpu)
    if not refresh and key in _cache:
        return _cache[key]
    target = models_target_dir()
    plat = _platform() or ""
    fn = _PROBES.get(plat)
    if fn is None:
        # 未知平台：仅磁盘可用（其余字段保持 None）
        profile = HardwareProfile(disk_free_gb=_disk_free_gb(target))
    else:
        try:
            profile = fn(target, with_gpu)
        except Exception:
            profile = HardwareProfile(disk_free_gb=_disk_free_gb(target))
    _cache[key] = profile
    return profile
