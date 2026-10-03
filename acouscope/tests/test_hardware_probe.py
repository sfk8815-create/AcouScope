# SPDX-License-Identifier: GPL-3.0-only
"""T-1022 §1：硬件探测（离屏；全部打桩，禁真实 sysctl / system_profiler / 网络）。

覆盖需求说明 Step 6 对该文件的要求：
- 多平台分支（macOS sysctl / Windows GlobalMemoryStatusEx / Linux /proc/meminfo）；
- 字段缺失 → None（**绝不抛**）；
- 【隐私红线】字段白名单（无任何设备唯一标识）+ 源码级禁词断言；
- 会话内缓存与 refresh 语义；
- 探测失败返回部分 profile，不得阻断 UI。
"""

import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from acouscope.ai import hardware  # noqa: E402

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "src" / "acouscope" / "ai" / "hardware.py")

#: 唯一标识类**探测 API / 字段名**（隐私红线：源码里一个都不许出现）。
#: 只列真实探测会用到标识符（如序列号查询属性名 / 机器码函数），
#: 避免与文档里「不采集序列号」这句声明文字本身冲突。
_UNIQUE_ID_MARKERS = (
    "IOPlatformSerialNumber", "IOPlatformUUID", "IOPlatformExpertDevice",
    "serial_number", "SerialNumber", "uuid.getnode", "getnode(",
    "machine_id", "machine-id", "idfv", "idfa",
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前后清空会话缓存（避免跨用例串味）。"""
    hardware._cache.clear()
    yield
    hardware._cache.clear()


# ----------------------------------------------------------------------
# 隐私红线：字段白名单 + 源码禁词
# ----------------------------------------------------------------------

def test_profile_field_whitelist_exact():
    """HardwareProfile 的字段集合**恰等于**白名单（不许悄悄加字段）。"""
    from dataclasses import fields
    names = {f.name for f in fields(hardware.HardwareProfile)}
    assert names == set(hardware.PRIVACY_FIELDS)


def test_profile_dict_only_whitelisted_keys():
    prof = hardware.HardwareProfile(ram_gb=16.0, chip="Apple M4")
    assert set(prof.as_dict()) == set(hardware.PRIVACY_FIELDS)


def test_source_has_no_unique_identifier_probe():
    """源码级：绝不采集任何设备唯一标识（序列号 / UUID / 机器码）。"""
    src = _SRC.read_text(encoding="utf-8")
    for marker in _UNIQUE_ID_MARKERS:
        assert marker not in src, f"硬件探测源码出现唯一标识关键词：{marker}"


# ----------------------------------------------------------------------
# 平台分支
# ----------------------------------------------------------------------

def _patch_disk(monkeypatch, free_bytes: int):
    monkeypatch.setattr(
        hardware.shutil, "disk_usage",
        lambda p: type("U", (), {"free": free_bytes, "total": 0, "used": 0})())


def test_macos_branch_full(monkeypatch):
    """macOS：sysctl 取值 → 字段齐全；Apple Silicon → 统一内存。"""
    values = {
        "hw.memsize": "17179869184",          # 16GB
        "hw.model": "Mac16,10",
        "machdep.cpu.brand_string": "Apple M4",
        "hw.ncpu": "10",
        "hw.optional.arm64": "1",
    }
    monkeypatch.setattr(hardware, "_platform", lambda: "darwin")
    monkeypatch.setattr(hardware, "_sysctl", lambda name: values.get(name))
    monkeypatch.setattr(hardware, "_macos_gpu_cores", lambda: 10)
    _patch_disk(monkeypatch, 67 * 1024 ** 3)

    prof = hardware.probe(with_gpu=True)
    assert prof.ram_gb == 16.0
    assert prof.chip == "Apple M4"
    assert prof.model_id == "Mac16,10"
    assert prof.is_apple_silicon is True
    assert prof.cpu_cores == 10
    assert prof.gpu_cores == 10
    assert prof.unified_memory is True
    assert prof.disk_free_gb == 67.0


def test_macos_without_gpu_skips_system_profiler(monkeypatch):
    """with_gpu=False → 不调用 GPU 探测（system_profiler 实测约 4 秒）。"""
    called = []
    monkeypatch.setattr(hardware, "_platform", lambda: "darwin")
    monkeypatch.setattr(hardware, "_sysctl", lambda name: "1")
    monkeypatch.setattr(hardware, "_macos_gpu_cores",
                        lambda: called.append(1) or 10)
    _patch_disk(monkeypatch, 10 ** 9)
    prof = hardware.probe(with_gpu=False)
    assert prof.gpu_cores is None and called == []


def test_macos_apple_flag_by_chip_when_arm_unknown(monkeypatch):
    """hw.optional.arm64 取不到时按芯片名回退判定 Apple Silicon。"""
    values = {"machdep.cpu.brand_string": "Apple M2 Pro"}
    monkeypatch.setattr(hardware, "_platform", lambda: "darwin")
    monkeypatch.setattr(hardware, "_sysctl", lambda name: values.get(name))
    monkeypatch.setattr(hardware, "_macos_gpu_cores", lambda: None)
    _patch_disk(monkeypatch, 10 ** 9)
    prof = hardware.probe()
    assert prof.is_apple_silicon is True and prof.unified_memory is True


def test_linux_branch(monkeypatch):
    """Linux：/proc/meminfo + /proc/cpuinfo（机型文件缺失 → model_id None）。"""
    files = {
        "/proc/meminfo": "MemTotal:       32768000 kB\nMemFree: 1 kB\n",
        "/proc/cpuinfo": "processor\t: 0\nmodel name\t: AMD Ryzen 9\n",
    }
    monkeypatch.setattr(hardware, "_platform", lambda: "linux")
    monkeypatch.setattr(hardware, "_read_text", lambda p: files.get(str(p)))
    _patch_disk(monkeypatch, 20 * 1024 ** 3)

    prof = hardware.probe()
    assert prof.ram_gb == pytest.approx(31.2, abs=0.2)   # 32768000 kB ≈ 31.25GB
    assert prof.chip == "AMD Ryzen 9"
    assert prof.model_id is None
    assert prof.is_apple_silicon is False
    assert prof.gpu_cores is None
    assert prof.disk_free_gb == 20.0


def test_windows_branch(monkeypatch):
    """Windows：GlobalMemoryStatusEx + PROCESSOR_IDENTIFIER。"""
    monkeypatch.setattr(hardware, "_platform", lambda: "win32")
    monkeypatch.setattr(hardware, "_windows_ram_bytes",
                        lambda: 32 * 1024 ** 3)
    monkeypatch.setenv("PROCESSOR_IDENTIFIER", "Intel64 Family 6 Model 154")
    _patch_disk(monkeypatch, 100 * 1024 ** 3)

    prof = hardware.probe()
    assert prof.ram_gb == 32.0
    assert prof.chip and "Intel64" in prof.chip
    assert prof.is_apple_silicon is False
    assert prof.unified_memory is False
    assert prof.disk_free_gb == 100.0


def test_unknown_platform_only_disk(monkeypatch):
    """未知平台：仅尽力填磁盘字段，其余 None（绝不抛）。"""
    monkeypatch.setattr(hardware, "_platform", lambda: "plan9")
    _patch_disk(monkeypatch, 5 * 1024 ** 3)
    prof = hardware.probe()
    assert prof.disk_free_gb == 5.0
    assert prof.ram_gb is None and prof.chip is None


# ----------------------------------------------------------------------
# 失败降级（绝不抛）
# ----------------------------------------------------------------------

def test_all_probes_failing_returns_partial_profile(monkeypatch):
    """命令缺失 / 读文件失败 → 字段 None，探测**绝不抛**。"""
    monkeypatch.setattr(hardware, "_platform", lambda: "darwin")
    monkeypatch.setattr(hardware, "_sysctl", lambda name: None)
    monkeypatch.setattr(hardware, "_macos_gpu_cores", lambda: None)

    def _boom(_p):
        raise OSError("no such disk")

    monkeypatch.setattr(hardware.shutil, "disk_usage", _boom)
    prof = hardware.probe()
    assert prof.ram_gb is None and prof.chip is None and prof.disk_free_gb is None
    assert prof.summary() == ""


def test_branch_exception_degrades_not_raises(monkeypatch):
    """平台分支函数自身抛异常 → 退化为部分 profile（仅磁盘），不向上抛。"""
    def _boom(target, with_gpu=True):
        raise RuntimeError("sysctl exploded")

    monkeypatch.setattr(hardware, "_platform", lambda: "darwin")
    monkeypatch.setitem(hardware._PROBES, "darwin", _boom)
    _patch_disk(monkeypatch, 8 * 1024 ** 3)
    prof = hardware.probe()
    assert prof.ram_gb is None and prof.disk_free_gb == 8.0


def test_gpu_probe_failure_is_none(monkeypatch):
    """system_profiler 输出异常/缺失 → gpu_cores=None（其余字段不受影响）。"""
    output = "Graphics/Displays:\n  Chipset Model: Apple M4\n"
    monkeypatch.setattr(hardware, "_platform", lambda: "darwin")
    monkeypatch.setattr(hardware, "_sysctl", lambda name: {
        "hw.memsize": "8589934592", "hw.optional.arm64": "1",
    }.get(name))
    monkeypatch.setattr(hardware, "_run", lambda argv: output)
    _patch_disk(monkeypatch, 10 ** 9)
    prof = hardware.probe(with_gpu=True)
    assert prof.gpu_cores is None and prof.ram_gb == 8.0


def test_gpu_cores_parsed_from_system_profiler(monkeypatch):
    output = ("Graphics/Displays:\n\n    Apple M4:\n\n"
              "      Total Number of Cores: 10\n")
    monkeypatch.setattr(hardware, "_run", lambda argv: output)
    assert hardware._macos_gpu_cores() == 10


# ----------------------------------------------------------------------
# 缓存语义 / summary
# ----------------------------------------------------------------------

def test_probe_cached_and_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(hardware, "_platform", lambda: "darwin")
    monkeypatch.setattr(hardware, "_sysctl", lambda name: None)

    def _branch(target, with_gpu=True):
        calls.append(1)
        return hardware.HardwareProfile(ram_gb=1.0)

    monkeypatch.setitem(hardware._PROBES, "darwin", _branch)
    first = hardware.probe()
    second = hardware.probe()
    assert first is second and len(calls) == 1     # 会话内缓存
    hardware.probe(refresh=True)
    assert len(calls) == 2                          # refresh 强制重探


def test_summary_composition_and_unknown():
    prof = hardware.HardwareProfile(chip="Apple M4", ram_gb=16.0,
                                    disk_free_gb=67.3)
    assert prof.summary() == "Apple M4 · 16GB · 67GB"
    assert hardware.HardwareProfile().summary() == ""
    assert hardware.HardwareProfile().summary("未知") == "未知"


def test_models_target_dir_under_data_dir(monkeypatch, tmp_path):
    """磁盘统计目标 = 数据目录下的模型沙盒（调用期解析，随数据目录重定向）。"""
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    assert hardware.models_target_dir() == tmp_path / "llama_models"
