# SPDX-License-Identifier: GPL-3.0-only
"""3D 默认视角微调测试：新 AZIM 生效且 ELEV 不变。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from acouscope.ui.widgets import spectrogram3d as m3d


def test_default_view_updated():
    assert m3d.DEFAULT_AZIM == -75.0
    assert m3d.DEFAULT_ELEV == 28.0
