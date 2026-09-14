# SPDX-License-Identifier: GPL-3.0-only
"""音律标尺基座子包（T-918）：.scl 解析 + TuningSystem 模型 + 内置代表模板。

导入一律走完整路径（analysis/__init__.py 不引用本子包，T-918 任务书口径）：
``acouscope.analysis.tunings.scl`` / ``.tuning_system`` / ``.templates``。
"""

from __future__ import annotations

from .scl import SclScale, SclValue, parse_scl, parse_scl_file
from .templates import TEMPLATE_KEYS, TEMPLATES, get_template, list_templates, load_scl
from .tuning_system import TuningSystem

__all__ = [
    "SclScale",
    "SclValue",
    "TEMPLATE_KEYS",
    "TEMPLATES",
    "TuningSystem",
    "get_template",
    "list_templates",
    "load_scl",
    "parse_scl",
    "parse_scl_file",
]
