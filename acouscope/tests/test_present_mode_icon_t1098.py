# SPDX-License-Identifier: GPL-3.0-only
"""T-1098 IM-10：呈现模式两枚图标（``mode_single`` / ``mode_grid``）扩容与接线守卫。

覆盖判据（离屏可判的部分·好不好看归真机 N5）：
① 逻辑名入表 + 计数随 ``_pin_baselines.ICONS_LOGICAL_NAME_COUNT`` 单源；
② 四套（generic/macos/win/mint）资源齐备非空；
③ 图元常量守 derive 前置约束（24×24 坐标空间 / 仅 none|currentColor / 无 px /
   无 ``#hex`` / 无 ``<svg>``·``width`` 包裹——包裹由 ``render_base`` 负责）；
④ ``get_icon`` 离屏渲染出有效非空 QIcon；
⑤ 活钮（``multitrack_view`` 自建工具栏两钮）图标已挂**且文字仍在**（图标与文字并存）。

纪律：全程离屏、零子进程、零网络；不 show 控件、不弹模态、不调 ``apply_theme``
（后者装 app 级全局 QSS 不可逆，会污染同进程后续 GUI 档度量）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QToolButton

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel
from tests._pin_baselines import ICONS_LOGICAL_NAME_COUNT

_PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ICON_ROOT = _PKG_ROOT / "src" / "acouscope" / "resources" / "icons"
_DERIVE_PY = _PKG_ROOT / "scripts" / "derive_icon_styles.py"
_STYLES = ("generic", "macos", "win", "mint")
_NAMES = ("mode_single", "mode_grid")


@pytest.fixture
def panel(qapp):
    """裸面板（session=None）——两枚模式钮在自建工具栏，与宿主无关。"""
    return MultitrackPanel(None)


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("t1098_derive", _DERIVE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# ① 逻辑名入表 + 计数单源
# ---------------------------------------------------------------------------

def test_two_new_logical_names_and_count_follows_pin():
    for name in _NAMES:
        assert name in theme.ICONS, f"ICONS 缺 {name}"
        assert theme.ICONS[name] == f"generic/{name}.svg"
    assert len(theme.ICONS) == ICONS_LOGICAL_NAME_COUNT


# ---------------------------------------------------------------------------
# ② 四套资源齐备非空
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _NAMES)
def test_assets_complete_four_styles(name):
    for style in _STYLES:
        svg = _ICON_ROOT / style / f"{name}.svg"
        assert svg.exists(), f"{style}/{name}.svg 缺失（未跑派生脚本？）"
        assert svg.stat().st_size > 0, f"{style}/{name}.svg 为空"


# ---------------------------------------------------------------------------
# ③ 图元常量守 derive 前置约束
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _NAMES)
def test_primitive_follows_derive_constraints(name):
    primitive = _load_script().MISSING_GENERIC_PRIMITIVES[name]
    assert "<svg" not in primitive and "xmlns" not in primitive, (
        "图元须为片段（根元素与 width/height 包裹由 render_base 负责）")
    assert "px" not in primitive, "图元禁带长度单位（画布为 24×24 坐标空间）"
    assert not re.search(r"#[0-9a-fA-F]{3,8}", primitive), "图元禁字面色值"
    for found in re.findall(r'(?:fill|stroke)="([^"]+)"', primitive):
        assert found in ("none", "currentColor"), f"图元残留色值 {found}"


# ---------------------------------------------------------------------------
# ④ 离屏渲染非空
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _NAMES)
def test_get_icon_renders_non_null_offscreen(qapp, name):
    prev = theme._icon_style
    theme._icon_style = "generic"
    theme._icon_cache.clear()
    try:
        icon = theme.get_icon(name)
        assert not icon.isNull(), f"{name} 渲染为空 QIcon"
        assert icon.availableSizes(), f"{name} 无有效尺寸"
    finally:
        theme._icon_style = prev
        theme._icon_cache.clear()


# ---------------------------------------------------------------------------
# ⑤ 活钮接线：图标 + 文字并存
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("object_name,logical_name,i18n_key", (
    ("trackPresentSingle", "mode_single", "multitrack.compare.mode_single"),
    ("trackPresentGrid", "mode_grid", "multitrack.compare.mode_grid"),
))
def test_live_mode_buttons_carry_icon_and_keep_text(
        panel, object_name, logical_name, i18n_key):
    btn = panel.findChild(QToolButton, object_name)
    assert btn is not None, f"面板缺 {object_name}"
    assert not btn.icon().isNull(), f"{object_name} 未挂图标"
    assert btn.text() == tr(i18n_key) and btn.text(), f"{object_name} 文字标签丢失"
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon, (
        f"{object_name} 非 TextBesideIcon ⇒ QToolButton 默认 IconOnly 会吞文字")
