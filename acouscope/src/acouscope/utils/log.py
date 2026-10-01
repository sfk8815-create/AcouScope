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


def reset_logging() -> None:
    """移除并关闭 acouscope 根 logger 的既有 handler，回到「未配置」状态。

    测试隔离（GUI_backlog #13）：模块级 ``_log = get_logger(__name__)`` 会在
    测试收集（import）阶段就把 RotatingFileHandler 绑定到**真实**
    ``get_data_dir()``；此后 autouse 夹具再 monkeypatch 数据目录也无效——
    ``_configure_root`` 的 ``_CONFIGURED`` 幂等标志会直接早退，旧 handler
    继续写真实用户目录。

    故测试的隔离夹具须先调用本函数，再触发一次 ``get_logger()``，使日志
    handler 重新绑定到重定向后的临时目录（生产路径不调用本函数，语义不变）。
    """
    global _CONFIGURED
    root = logging.getLogger("acouscope")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
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
            log_path,
            maxBytes=512 * 1024,
            backupCount=3,
            encoding="utf-8",
            delay=True,  # 首次写入才打开/创建文件，避免 import 期即触碰数据目录
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
