# SPDX-License-Identifier: GPL-3.0-only
"""T-1076：T-1076 三枚图元改后 get_icon 离屏冒烟（判据③）。

apply_theme 下 get_icon(name) 走 QSvgRenderer 染色渲染路径，返回有效非空
QIcon 且不抛异常；顺带核 hover/active/disabled 三态色路径同样不抛。
纪律：全程离屏（conftest 已设 QT_QPA_PLATFORM=offscreen）；不构造 MainWindow。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from acouscope.ui import theme  # noqa: E402

_NAMES = ("add_track", "room_acoustic", "room_modal", "chart_designer")


@pytest.fixture(autouse=True)
def _pin_generic_style():
    """钉 generic 风格进出复原（防跨文件污染，同 test_icon_styles 口径）。"""
    prev = theme._icon_style
    theme._icon_style = "generic"
    theme._icon_cache.clear()
    yield
    theme._icon_style = prev
    theme._icon_cache.clear()


@pytest.mark.parametrize("name", _NAMES)
def test_get_icon_valid_offscreen_under_dark_theme(qapp, name):
    theme.apply_theme("dark")
    icon = theme.get_icon(name)
    assert not icon.isNull(), f"{name} 渲染为空 QIcon"
    assert icon.availableSizes(), f"{name} 无有效尺寸"


@pytest.mark.parametrize("state", ("default", "hover", "active", "disabled"))
def test_get_icon_states_do_not_throw(qapp, state):
    theme.apply_theme("dark")
    for name in _NAMES:
        assert not theme.get_icon(name, state).isNull()
