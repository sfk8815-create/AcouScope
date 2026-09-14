# SPDX-License-Identifier: GPL-3.0-only
"""统一日志工具。

用于替代散落的 ``except Exception: pass`` 静默吞没：
- 日志同时输出到 stderr（终端 / 控制台模式可见）与数据目录下的
  滚动日志文件 ``acouscope.log``（GUI 模式下也可事后排查）
- 懒初始化；数据目录不可写等异常不影响主流程（降级为仅 stderr）
- 日志级别：INFO 及以上（DEBUG 默认关闭，避免刷屏）

用法::

    from acouscope.utils.log import get_logger

    _log = get_logger(__name__)
    try:
        ...
    except Exception as e:
        _log.warning("打开音频流失败: %s", e)
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

_CONFIGURED = False


def _configure_root() -> None:
    """初始化 acouscope 根 logger（幂等）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger("acouscope")
    root.setLevel(logging.INFO)
    root.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # stderr（终端 / PyInstaller 控制台模式可见）
    try:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        root.addHandler(stream)
    except Exception:
        pass  # 极端环境 stderr 不可用 → 仅保留文件 handler

    # 滚动文件（GUI 模式排查；512KB × 3 份）
    try:
        from acouscope.utils.config import get_data_dir

        log_path = get_data_dir() / "acouscope.log"
        file_handler = RotatingFileHandler(
            log_path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:
        pass  # 数据目录不可写 → 仅 stderr，不影响主流程


def get_logger(name: str) -> logging.Logger:
    """获取 acouscope 命名空间下的子 logger。

    Args:
        name: 模块名，如 ``"audio.player"`` 或完整 ``__name__``
              （自动去掉 ``acouscope.`` 前缀，日志更简洁）。
    """
    if not _CONFIGURED:
        _configure_root()
    if name.startswith("acouscope."):
        name = name[len("acouscope."):]
    return logging.getLogger(f"acouscope.{name}")
