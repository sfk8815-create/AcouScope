# SPDX-License-Identifier: GPL-3.0-only
"""T-1029: 单实例守卫测试（6 例）。

铁律：
- offscreen 全程；禁起 GUI / app
- 子进程用例必须自设期限 + kill -9 收尾（W5.2）
- 锁文件落在 tmp_path，不污染真实 config 目录
"""

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from acouscope.utils.single_instance import release, try_acquire  # noqa: E402

# 子进程脚本模板：只跑守卫逻辑，不起 GUI
_CHILD_SCRIPT = textwrap.dedent("""\
    import sys, time
    sys.path.insert(0, {src!r})
    from pathlib import Path
    from acouscope.utils.single_instance import try_acquire, release
    lock_dir = Path({lock_dir!r})
    result = try_acquire(lock_dir)
    print(result, flush=True)
    if result is True:
        time.sleep({hold_s!r})
    release(lock_dir)
""")


def _run_child(lock_dir: str, hold_s: float = 5.0) -> subprocess.Popen:
    """启动一个只跑守卫逻辑的子进程，返回 Popen。"""
    src = str(Path(__file__).resolve().parent.parent / "src")
    script = _CHILD_SCRIPT.format(src=src, lock_dir=lock_dir, hold_s=hold_s)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _kill(proc: subprocess.Popen) -> None:
    """强制 kill -9 收尾（W5.2）。"""
    if proc.poll() is None:
        os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)


# ─── 用例 1: 首实例拿到锁 ─────────────────────────────────────────────


def test_first_instance_acquires(tmp_path):
    """首实例 try_acquire() → True。"""
    result = try_acquire(tmp_path)
    assert result is True
    release(tmp_path)


# ─── 用例 2: ★ 第二实例被拦（真子进程持锁）────────────────────────────


def test_second_instance_blocked(tmp_path):
    """先起真子进程持锁，主进程 try_acquire() → False。"""
    lock_dir = str(tmp_path)
    child = _run_child(lock_dir, hold_s=5.0)
    try:
        # 等子进程拿到锁（读 stdout 第一行）
        line = child.stdout.readline().decode().strip()
        assert line == "True", f"子进程应拿到锁，实际: {line!r}"
        # 主进程尝试取同一把锁 → 必须 False
        result = try_acquire(tmp_path)
        assert result is False, f"第二实例应被拦（False），实际: {result!r}"
    finally:
        _kill(child)


# ─── 用例 3: 释放后可再取 ─────────────────────────────────────────────


def test_release_then_reacquire(tmp_path):
    """release() 后 try_acquire() → True。"""
    assert try_acquire(tmp_path) is True
    release(tmp_path)
    assert try_acquire(tmp_path) is True
    release(tmp_path)


# ─── 用例 4: 陈旧锁可回收 ─────────────────────────────────────────────


def test_stale_lock_reclaimed(tmp_path):
    """构造陈旧锁（死 pid）⇒ try_acquire() → True。"""
    # Qt 锁文件格式: "pid\\nappname\\nhostname"
    import socket

    dead_pid = 99999  # 一个极不可能存活的 pid
    hostname = socket.gethostname()
    lock_file = tmp_path / "acouscope_single_instance"
    lock_file.write_text(f"{dead_pid}\nAcouScope\n{hostname}\n")
    # 取锁应成功（Qt 检测到 pid 已死 ⇒ 回收）
    result = try_acquire(tmp_path)
    assert result is True, f"陈旧锁应可回收，实际: {result!r}"
    release(tmp_path)


# ─── 用例 5: ★★ fail-open 注入故障 ⇒ None 且不抛 ─────────────────────


def test_fail_open_on_injected_fault(tmp_path, monkeypatch):
    """注入故障（get_config_dir 抛异常）⇒ try_acquire() → None，不抛。"""
    from acouscope.utils import single_instance as si

    def _raise():
        raise PermissionError("模拟只读目录")

    monkeypatch.setattr(si, "get_config_dir", _raise)
    # 不传 path 参数 ⇒ 走 get_config_dir() ⇒ 抛异常 ⇒ fail-open
    result = si.try_acquire()
    assert result is None, f"故障注入应返回 None（fail-open），实际: {result!r}"


# ─── 用例 6: 入口集成（两个真子进程只跑守卫逻辑，禁起 GUI）────────────


def test_entry_integration_two_children(tmp_path):
    """两个真子进程：第一个持锁，第二个必须得到 False。"""
    lock_dir = str(tmp_path)

    # 第一个子进程：持锁 5s
    child1 = _run_child(lock_dir, hold_s=5.0)
    try:
        line1 = child1.stdout.readline().decode().strip()
        assert line1 == "True", f"第一子进程应拿到锁，实际: {line1!r}"

        # 第二个子进程：同一锁目录
        child2 = _run_child(lock_dir, hold_s=1.0)
        try:
            line2 = child2.stdout.readline().decode().strip()
            assert line2 == "False", f"第二子进程应被拦（False），实际: {line2!r}"
        finally:
            _kill(child2)

        # 断言第一个子进程仍存活（未被影响）
        assert child1.poll() is None, "第一子进程在持锁期间应仍存活"
    finally:
        _kill(child1)
