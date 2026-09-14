# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 多轨包：数据层（TrackModel/MultitrackSession）+ 轨道头 + 轨道区容器。"""

from acouscope.ui.widgets.multitrack.track_model import (
    MultitrackSession, TrackModel, format_seconds,
)

__all__ = ["MultitrackSession", "TrackModel", "format_seconds"]
