# SPDX-License-Identifier: GPL-3.0-only
"""`acouscope.utils.log` 统一日志模块专项测试（补测·纯测试面，不改产品码）。

覆盖：命名空间/前缀剥离 · 根 logger 配置（级别·propagate·双 handler）·
`_configure_root` 幂等 · `reset_logging` 重置 · 双路落地（滚动文件 + stderr）·
子 logger 冒泡进根 handler · 日志格式与 INFO 阈值挡下 DEBUG ·
数据目录不可写 / StreamHandler 构造失败时的降级不崩。

依赖 conftest autouse `_isolate_app_data_dir`：每个测试已把 `get_data_dir` 重定向到
`tmp_path` 并 `reset_logging()` + 触发一次 configure，故 `acouscope.log` 落 `tmp_path`，
测试互不污染、绝不写真实用户目录。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from acouscope.utils import log as logmod
from acouscope.utils.log import get_logger, reset_logging

ROOT = logging.getLogger("acouscope")


def _file_handler() -> RotatingFileHandler | None:
    return next((h for h in ROOT.handlers if isinstance(h, RotatingFileHandler)), None)


def _stream_handlers() -> list[logging.StreamHandler]:
    # 精确类型匹配：RotatingFileHandler 亦是 StreamHandler 子类，故不用 isinstance。
    return [h for h in ROOT.handlers if type(h) is logging.StreamHandler]


# --- 命名空间 / 前缀剥离 ---------------------------------------------------

def test_get_logger_returns_child_in_namespace():
    lg = get_logger("audio.player")
    assert isinstance(lg, logging.Logger)
    assert lg.name == "acouscope.audio.player"


def test_get_logger_strips_existing_prefix_no_double():
    # 传入已带 `acouscope.` 前缀的 __name__ → 先剥后加，结果等价、不出现双前缀
    lg = get_logger("acouscope.analysis.worker.proxy")
    assert lg.name == "acouscope.analysis.worker.proxy"


def test_get_logger_is_cached_singleton_per_name():
    # logging 层级下同名返回同一对象（标准库缓存语义）
    assert get_logger("main") is logging.getLogger("acouscope.main")


# --- 根 logger 配置 --------------------------------------------------------

def test_root_level_is_info_and_no_propagate():
    # conftest 已触发 configure
    assert ROOT.level == logging.INFO
    assert ROOT.propagate is False


def test_configure_from_scratch_binds_dual_handlers():
    reset_logging()
    get_logger("x")  # 触发 _configure_root（从零）
    assert len(_stream_handlers()) == 1, "应恰有一个 stderr StreamHandler"
    assert _file_handler() is not None, "应有一个滚动文件 handler"


def test_rotating_file_handler_params(tmp_path):
    reset_logging()
    get_logger("x")
    fh = _file_handler()
    assert fh is not None
    assert fh.maxBytes == 512 * 1024
    assert fh.backupCount == 3
    assert str(fh.baseFilename) == str(tmp_path / "acouscope.log")


# --- 幂等 / reset ----------------------------------------------------------

def test_configure_root_idempotent_no_duplicate_handlers():
    reset_logging()
    for n in ("a", "b", "c"):
        get_logger(n)
    assert len(ROOT.handlers) == 2, "多次 get_logger 不应叠加 handler（幂等）"


def test_reset_logging_clears_handlers_and_flag():
    get_logger("x")  # 确保已配置
    reset_logging()
    assert ROOT.handlers == []
    assert logmod._CONFIGURED is False
    # reset 后再取应重建完整双 handler
    get_logger("y")
    assert logmod._CONFIGURED is True
    assert len(ROOT.handlers) == 2


# --- 双路落地 / 冒泡 / 格式 / 阈值 ----------------------------------------

def test_warning_from_child_bubbles_to_file(tmp_path):
    reset_logging()
    get_logger("worker.proxy").warning("hello-%s", "world")
    fh = _file_handler()
    fh.flush()
    content = (tmp_path / "acouscope.log").read_text(encoding="utf-8")
    assert "hello-world" in content
    assert "WARNING" in content and "acouscope.worker.proxy" in content
    fh.close()


def test_format_contains_level_name_and_message(tmp_path):
    reset_logging()
    get_logger("f").error("boom")
    fh = _file_handler()
    fh.flush()
    line = (tmp_path / "acouscope.log").read_text(encoding="utf-8")
    # "%(asctime)s %(levelname)s %(name)s: %(message)s"
    assert "ERROR acouscope.f: boom" in line
    fh.close()


def test_debug_suppressed_by_info_threshold(tmp_path):
    reset_logging()
    lg = get_logger("d")
    lg.debug("hidden-debug")
    lg.info("shown-info")
    fh = _file_handler()
    fh.flush()
    content = (tmp_path / "acouscope.log").read_text(encoding="utf-8")
    assert "shown-info" in content
    assert "hidden-debug" not in content, "DEBUG 应被 INFO 阈值挡下"
    fh.close()


# --- 降级不崩 --------------------------------------------------------------

def test_degrades_to_stderr_only_when_data_dir_unwritable(monkeypatch):
    import acouscope.utils.config as _cfg

    reset_logging()

    def boom() -> None:
        raise OSError("read-only data dir")

    monkeypatch.setattr(_cfg, "get_data_dir", boom)
    lg = get_logger("deg")  # 不应抛
    assert isinstance(lg, logging.Logger)
    assert _file_handler() is None, "数据目录不可写时不应建文件 handler"
    assert len(_stream_handlers()) == 1, "仍应保留 stderr handler"
    lg.warning("still fine")  # 记录一条也不崩


def test_degrades_when_stream_handler_fails(monkeypatch):
    reset_logging()
    orig = logging.StreamHandler

    class _BadStream(orig):
        def __init__(self, *a, **k):
            raise RuntimeError("no stderr available")

    monkeypatch.setattr(logging, "StreamHandler", _BadStream)
    lg = get_logger("deg2")  # stderr 分支失败应被吞、文件分支仍建立
    assert isinstance(lg, logging.Logger)
    assert _file_handler() is not None, "文件 handler 仍应建立"
    assert _stream_handlers() == [], "失败构造不应留下 StreamHandler"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
