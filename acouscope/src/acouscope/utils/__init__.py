# SPDX-License-Identifier: GPL-3.0-only
"""工具函数模块。"""

from .config import get_config_dir, get_data_dir, Settings
from .log import get_logger

__all__ = ["get_config_dir", "get_data_dir", "Settings", "get_logger"]
