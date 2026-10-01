# SPDX-License-Identifier: GPL-3.0-only
"""单实例守卫（T-1029）：仅首实例加载 AcouScope。

判据（2026-09-16 冻结，基于真实实测，PyQt6 6.11）：

- 判据必须看 ``QLockFile.error()``, 不看 ``tryLock()`` 的布尔值。
  只有 ``LockFailedError`` = 另一个活实例持有锁（在此方才 exit(0) 拦住）。
- ``PermissionError`` / ``UnknownError`` / 任何其它非 ``NoError`` =
  机制失败（沙箱/只读目录等）⇒ ``None`` ⇒ fail-open（照常启动）。
- 陈旧锁（死 pid) 自动回收：``setStaleLockTime`` 语义，只收锁文件 mtime 较旧者；
  被 kill -9 遗留的锁随第一次调用自动吞掉。
- 进程退出释放锁（``atexit``），``kill -9`` 以外的正常退出均无残留。
- 接口与入口解耦：``try_acquire()`` / ``release()`` 可独立调用，
  ``main()`` 只判断返回值，零与 Qt GUI 的耦合；不构造任何 QWidget，
  可在无 QApplication 的入口前段调用。
"""

from __future__ import annotations

import atexit
from pathlib import Path

from PyQt6.QtCore import QLockFile

from acouscope.utils.config import get_config_dir
from acouscope.utils.log import get_logger

_log = get_logger("single_instance")

# 陈旧锁判定：文件 mtime 超过该久远即视为过期。
# 约 10 年，足以覆盖被 kill -9 遗留的锁，也绝不触碰任何本机存活的锁。
_STALE_LOCK_SECONDS = 315_360_000

_LOCK_FILENAME = "acouscope_single_instance"

_HELD_LOCK: "QLockFile | None" = None  # 取得锁的那个实例（release 必须用它）


def _lock_path(path: Path | None = None) -> Path:
    """锁文件路径：默认复用 ``get_config_dir()``（禁自造路径）。

    供测试注入临时目录；主流程不调用此参数。
    """
    base = Path(path) if path is not None else get_config_dir()
    return base / _LOCK_FILENAME


def try_acquire(path: Path | None = None) -> bool | None:
    """尝试取得单实例锁。

    Args:
        path: 可选锁文件父目录；不传时走 ``get_config_dir()``.

    Returns:
        ``True``: 本实例是首实例（拿到了锁）
        ``False``: 另一个活实例持有锁（``LockFailedError`` 判据）
        ``None``: 机制失败/fail-open（落 warning 日志，调用方照常启动）
    """
    try:
        lock_file = _lock_path(path)
        lock = QLockFile(str(lock_file))
        lock.setStaleLockTime(_STALE_LOCK_SECONDS)
        locked = lock.tryLock(100)
        error = lock.error()
        if error is None:  # PyQt6 未记录错误，视作无误
            error = QLockFile.LockError.NoError
    except Exception as e:
        # 任何机制异常（Qt 级 / 路径级 / 窗口级别）都 fail-open。
        _log.warning("单实例守卫获取锁机制失败（fail-open，照常启动）: %s", e)
        return None

    if error is QLockFile.LockError.LockFailedError:
        # 判据准：仅此情形才认为"另一个活实例持有"，方可设 exit(0)
        _log.info("AcouScope 已在运行，本次启动被拦（%s）", lock_file)
        return False

    if error is QLockFile.LockError.NoError:
        _log.info("AcouScope 单实例锁已获（%s）", lock_file)
        global _HELD_LOCK
        _HELD_LOCK = lock
        atexit.register(_release, lock_file)
        return True

    # PermissionError / UnknownError / 其它非 NoError / 非 LockFailedError
    # —— 本质是机制失败（沙箱/只读等），不可误判为"已有实例"，fail-open。
    _log.warning(
        "单实例守卫锁状态异常（非「锁＝另一个活实例」，不是真冲突 → fail-open）: %s",
        error,
    )
    return None


def release(path: Path | None = None) -> None:
    """释放单实例锁（幂等）。

    基于 Qt 单机语义：unlock 一个进程未持有的文件是 void 级无操作，
    对陈旧锁（kill -9) 不会误判/误释放其它实例，任何异常都不抛。
    """
    try:
        _release(_lock_path(path))
    except Exception:
        pass


def _release(lock_file: Path) -> None:
    """释放持有的锁（幂等；无持有时 no-op）。

    必须用【持有锁的那个 QLockFile 实例】unlock：unlock() 不接受路径参数，
    新构造的实例并不持有锁（实测 TypeError）。
    """
    global _HELD_LOCK
    lock, _HELD_LOCK = _HELD_LOCK, None
    if lock is None:
        return
    try:
        lock.unlock()
    except Exception:
        pass