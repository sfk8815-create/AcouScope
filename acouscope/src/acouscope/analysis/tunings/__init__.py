# SPDX-License-Identifier: GPL-3.0-only
"""音律标尺基座子包（T-918）：.scl 解析 + TuningSystem 模型 + 内置代表模板。

导入一律走完整路径（analysis/__init__.py 不引用本子包，T-918 需求说明口径）：
``acouscope.analysis.tunings.scl`` / ``.tuning_system`` / ``.templates``。

W-14-06 起增补写出与统一取用入口：:func:`save_scl`／:func:`format_scl`
（``.scl`` 写出）与 :func:`get_tuning`（内置 key 或用户 ``.scl`` 的统一入口，
未知 spec 显式报错、不回退 12TET）。
"""

from __future__ import annotations

from .scl import SclScale, SclValue, format_scl, parse_scl, parse_scl_file, save_scl
from .templates import (
    CUSTOM_PREFIX,
    PAPER_TEMPLATE_KEYS,
    TEMPLATE_KEYS,
    TEMPLATES,
    get_template,
    get_tuning,
    is_custom_spec,
    list_paper_templates,
    list_templates,
    load_scl,
    template_fingerprint,
    template_metadata,
)
from .tuning_system import TuningSystem

__all__ = [
    "CUSTOM_PREFIX",
    "PAPER_TEMPLATE_KEYS",
    "SclScale",
    "SclValue",
    "TEMPLATE_KEYS",
    "TEMPLATES",
    "TuningSystem",
    "format_scl",
    "get_template",
    "get_tuning",
    "is_custom_spec",
    "list_paper_templates",
    "list_templates",
    "load_scl",
    "parse_scl",
    "parse_scl_file",
    "save_scl",
    "template_fingerprint",
    "template_metadata",
]
