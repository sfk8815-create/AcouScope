# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 多轨包：数据层（TrackModel/MultitrackSession）+ 轨道头 + 轨道区容器。"""

from __future__ import annotations

import importlib

__all__ = ["MultitrackSession", "TrackModel", "format_seconds"]


def __getattr__(name: str):
    if name in ("MultitrackSession", "TrackModel", "format_seconds"):
        mod = importlib.import_module(".track_model", __name__)
        attr = getattr(mod, name)
        globals()[name] = attr
        return attr
    raise AttributeError(name)
