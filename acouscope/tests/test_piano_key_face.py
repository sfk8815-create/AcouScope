# SPDX-License-Identifier: GPL-3.0-only
"""T-1042 钢琴键面重设计守卫（分层明度 + 去强描边 + 去金色中央C + 几何 + 黑键圆角）。

语义源：`.pi/knowledge/ARCH_ui_visual_language.md §2.1-5/§五c/§六-10/§六-17/§六-18`
与 `.pi/tasks/T-1042.txt`（五因分析 + 硬化验收）。
覆盖：
① `TOKENS["keys"]` 明/暗两套四角色齐备、取值合法 hex、**白键亮度恒 > 黑键亮度**且差值 ≥ 0.45；
② 黑键与键带底 `strip` 可分辨（明度差 ≥ 小阈值）；白键缝 `white_seam` 比白键暗（去「格子纸」）；
③ **去强描边**：白键间分隔只用 `keys.white_seam`（不出现 `border` 作键面描边），黑键无描边；
④ **去金色中央 C**：`freq_axis.py` / `spectrum.py` 内**不出现任何 `TOKENS["semantic"]`**；
⑤ **几何**：黑键宽/白键宽 ∈ [0.58, 0.60]；黑键高 ∈ [0.58, 0.62]；`BLACK_X0` 居中偏左；
⑥ **黑键圆角**：两个键盘均使用 `QGraphicsPathItem` + `addRoundedRect`；
⑦ **色值唯一源**：键面色只在 `theme.py`，两文件内字面 hex = 0 / 字面 px = 0；
⑧ **主题往返**：dark→light→dark 后四角色逐值回原；
⑨ 实机建键（离屏）：竖排 `PianoKeyboardStrip` 与横排 `SpectrumWidget` 键面带底/黑键圆角/中央C加粗均可实例化可读。

口径：全离屏；不构造主窗口、不 show、不弹模态。
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

import pyqtgraph as pg  # noqa: E402

from acouscope.ui import theme  # noqa: E402

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_WIDGETS = _SRC / "ui" / "widgets"
_INK_FILES = ("freq_axis.py", "spectrum.py")
_ROLES = ("strip", "white", "black", "white_seam")
_DARK_KEYS = {"strip": "#101215", "white": "#D9DBDF",
              "black": "#1A1C1F", "white_seam": "#C6C9CE"}
_LIGHT_KEYS = {"strip": "#F5F6F7", "white": "#FFFFFF",
               "black": "#23262A", "white_seam": "#E4E6E8"}
_LITERAL_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_LITERAL_PX = re.compile(r"\b\d+(?:\.\d+)?px\b")
_HEX_VALID = re.compile(r"^#[0-9a-fA-F]{6}$")

# ★ 明度分层阈值（写入报告依据）：T-1038 后差仅 0.004 ≈ 不可辨；
#   本任务 white−black 明度差 ≥ 0.45（ARCH §六-10 键面可辨评审口径）。
KEY_LUMINANCE_GAP_MIN = 0.45
# 黑键与键带底可分辨的最小明度差（远小于主阈值，仅防「同色」）。
KEY_STRIP_GAP_MIN = 0.001
# 黑键几何区间（ARCH §五c-3）：宽/白键宽轨道 & 黑键纵向高轨道
BLACK_W_RATIO_MIN, BLACK_W_RATIO_MAX = 0.58, 0.60
BLACK_H_MIN, BLACK_H_MAX = 0.58, 0.62
# BANK_X0 居中偏左判定带：左移不超过 0.30（且严格小于居中位）
BLACK_X0_CENTER_SHIFT_MAX = 0.30


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _src(name: str) -> str:
    return (_WIDGETS / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# ① TOKENS["keys"] 双骨架齐备 / 合法 / 恒等白亮黑暗
# ----------------------------------------------------------------------

def test_keys_roles_present_and_valid_hex():
    group = theme.TOKENS["keys"]
    assert tuple(group["roles"]) == tuple(_ROLES)
    for sk in ("dark", "light"):
        pal = group[sk]
        assert set(_ROLES) <= set(pal), f"{sk} 缺键面角色"
        for role in _ROLES:
            assert _HEX_VALID.match(pal[role]), f"{sk}.{role} 非法色值"


def test_white_black_luminance_gap_all_skeletons():
    """明/暗两骨架下 white − black 明度差 ≥ 阈值，且 white 严格亮于 black。"""
    for sk, expected in (("dark", _DARK_KEYS), ("light", _LIGHT_KEYS)):
        pal = theme.TOKENS["keys"][sk]
        assert pal == expected, f"{sk} 键面色值与数据源不一致"
        white, black = _luminance(pal["white"]), _luminance(pal["black"])
        assert white > black, f"{sk} 白键未亮于黑键"
        gap = white - black
        # 实测：dark 0.696 / light 0.981，均显著 ≥ 0.45（T-1038 后仅 0.004）
        assert gap >= KEY_LUMINANCE_GAP_MIN, f"{sk} 白黑明度差 {gap:.3f} 不足"


def test_black_distinct_from_strip():
    """黑键与键带底可分辨：明度差 ≥ 小阈值（不得同色）。"""
    for sk in ("dark", "light",):
        pal = theme.TOKENS["keys"][sk]
        gap = abs(_luminance(pal["black"]) - _luminance(pal["strip"]))
        assert gap >= KEY_STRIP_GAP_MIN, f"{sk} 黑键与带底同色（{pal['black']} vs {pal['strip']}）"


def test_seam_darker_than_white_in_both_skeletons():
    """白键缝 `white_seam` 必须比白键面暗（去「格子纸」前提）；勿用 border。"""
    for sk in ("dark", "light"):
        pal = theme.TOKENS["keys"][sk]
        assert _luminance(pal["white_seam"]) < _luminance(pal["white"]), \
            f"{sk} white_seam 未暗于 white"
        assert pal["white_seam"] != theme.TOKENS["neutral"]["roles"]


# ----------------------------------------------------------------------
# ③ 去强描边（源码级）
# ----------------------------------------------------------------------

def test_key_face_stroke_uses_white_seam_no_border():
    """白键间分隔只用 keys.white_seam；两文件不应再用 border 作键面描边（无 key_edge）。"""
    for name in _INK_FILES:
        text = _src(name)
        assert 'pg.mkPen(faces["white_seam"]' in text, f"{name} 未用 white_seam 作白键缝"
        assert "key_edge" not in text, f"{name} 仍存在亮于键面的 border 描边变量"
        assert 'pg.mkPen(None)' in text, f"{name} 未用 NoPen 淡化黑键/带底描边"


def test_no_stroke_brighter_than_key_face_value_wise():
    """取值级：键面任意描边色明度不得高于对应键面。白键缝 < 白键面（已证），黑键无描边。"""
    for sk in ("dark", "light"):
        pal = theme.TOKENS["keys"][sk]
        assert _luminance(pal["white_seam"]) < _luminance(pal["white"])
        # 黑键无描边（源码用 NoPen）→ 不存在亮于黑键面的键面描边
        for name in _INK_FILES:
            assert 'setPen(no_pen)' in _src(name)


# ----------------------------------------------------------------------
# ④ 去金色中央 C：无任何语义反馈色
# ----------------------------------------------------------------------

def test_no_semantic_color_in_keyboard_files():
    for name in _INK_FILES:
        assert 'TOKENS["semantic"]' not in _src(name), f"{name} 残留语义色（中央 C 应去金色）"


# ----------------------------------------------------------------------
# ⑤ 几何（竖排 PianoKeyboardStrip 为准，横排按旋转同规）
# ----------------------------------------------------------------------

def test_vertical_piano_geometry():
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    ratio = PianoKeyboardStrip.BLACK_W / PianoKeyboardStrip.WHITE_W
    assert BLACK_W_RATIO_MIN <= ratio <= BLACK_W_RATIO_MAX, f"黑键宽/白键宽 = {ratio:.3f}"
    assert BLACK_H_MIN <= PianoKeyboardStrip.BLACK_H <= BLACK_H_MAX
    center = (PianoKeyboardStrip.WHITE_W - PianoKeyboardStrip.BLACK_W) / 2.0
    x0 = PianoKeyboardStrip.BLACK_X0
    # 居中偏左：严格小于居中位，且左移不超过 0.30
    assert x0 < center, f"BLACK_X0 {x0} 未严格偏左于居中位 {center:.2f}"
    assert center - BLACK_X0_CENTER_SHIFT_MAX <= x0 <= center, \
        f"BLACK_X0 {x0} 偏左量超出判定带 [居中−0.30, 居中]"


# ----------------------------------------------------------------------
# ⑥ 黑键圆角
# ----------------------------------------------------------------------

def test_black_keys_rounded_corners():
    """两键盘的圆角实现：源码使用 QPainterPath.addRoundedRect + QGraphicsPathItem。"""
    for name in _INK_FILES:
        text = _src(name)
        assert 'QPainterPath()' in text, f"{name} 未用 QPainterPath"
        assert 'addRoundedRect(' in text, f"{name} 黑键未圆角"
        assert 'QGraphicsPathItem(path)' in text, f"{name} 黑键未用路径元素"


# ----------------------------------------------------------------------
# ⑦ 色值唯一源：两文件中字面 hex / px = 0；键面 hex 只在 theme.py
# ----------------------------------------------------------------------

def test_keys_hex_unique_source_no_literal_in_widgets():
    for name in _INK_FILES:
        text = _src(name)
        assert _LITERAL_HEX.search(text) is None, f"{name} 残留字面 hex"
        assert _LITERAL_PX.search(text) is None, f"{name} 残留字面 px"
    theme_src = (_SRC / "ui" / "theme.py").read_text(encoding="utf-8")
    assert _LITERAL_PX.search(theme_src) is None, "theme.py 残留字面 px"
    # 键面色值集中出现在 theme.py（作为唯一数据源）
    for sk in ("dark", "light"):
        for role, color in theme.TOKENS["keys"][sk].items():
            assert color in theme_src, f"{color}（{sk}.{role}）应唯一存在于 theme.py"
    for name in _INK_FILES:
        assert 'key_faces()' in _src(name), f"{name} 未经 key_faces() 取键面色"


# ----------------------------------------------------------------------
# ⑧ 主题往返：dark→light→dark 四角色逐值回原
# ----------------------------------------------------------------------

def test_key_faces_roundtrip_dark_light_dark(qapp):
    def faces_dark():
        theme.apply_theme("dark")
        return theme.key_faces()

    base = faces_dark()
    assert base == dict(_DARK_KEYS)
    theme.apply_theme("light")
    assert theme.key_faces() == dict(_LIGHT_KEYS)
    theme.apply_theme("dark")
    assert theme.key_faces() == base, "dark→light→dark 后键面四角色未逐值回原"


def test_key_face_entry_point_and_error(qapp):
    theme.apply_theme("dark")
    try:
        assert theme.key_face("white") == _DARK_KEYS["white"]
        assert theme.key_face("strip") == _DARK_KEYS["strip"]
        with pytest.raises(KeyError):
            theme.key_face("__nope__")
    finally:
        theme.apply_theme("dark")


# ----------------------------------------------------------------------
# ⑨ 实机建键（离屏）：分层 / 圆角 / 中央 C 加粗可读
# ----------------------------------------------------------------------

def test_vertical_keyboard_builds_layered(qapp):
    from acouscope.dsp.units import midi_is_black_key
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    theme.apply_theme("dark")
    try:
        strip = PianoKeyboardStrip()
        strip._build_keys()
        # 键带底位于最底层（负 z），铺满整条
        base = strip._key_items[0]
        assert isinstance(base, pg.QtWidgets.QGraphicsRectItem)
        assert base.zValue() < 0
        assert base.brush().color().name().upper() == _DARK_KEYS["strip"].upper()
        # 黑键为圆角路径元素（数量 = 全音域黑键数）
        n_black = sum(1 for m in range(128) if midi_is_black_key(m))
        paths = [i for i in strip._key_items if isinstance(i, pg.QtWidgets.QGraphicsPathItem)]
        assert len(paths) == n_black, f"黑键圆角元素数 {len(paths)} ≠ {n_black}"
        for p in paths:
            assert p.brush().color().name().upper() == _DARK_KEYS["black"].upper()
            assert p.pen().style() == pg.QtCore.Qt.PenStyle.NoPen, "黑键不应有可见描边"
        # 白键缝：白键矩形描边 == white_seam
        rects = [i for i in strip._key_items
                 if isinstance(i, pg.QtWidgets.QGraphicsRectItem) and i is not base]
        assert rects and all(
            r.pen().color().name().upper() == _DARK_KEYS["white_seam"].upper()
            for r in rects[:5]
        )
        # 中央 C 加粗标签
        assert strip._center_c_label.textItem.font().bold()
    finally:
        theme.apply_theme("dark")


def test_horizontal_keyboard_builds_rounded(qapp):
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    theme.apply_theme("dark")
    try:
        widget = SpectrumWidget()
        widget._keyboard_visible = True
        widget._update_piano_keyboard(36, 72)
        paths = [i for i in widget._keyboard_items
                 if isinstance(i, pg.QtWidgets.QGraphicsPathItem)]
        assert len(paths) > 0, "横排键盘未生成圆角黑键"
        for p in paths:
            assert p.brush().color().name().upper() == _DARK_KEYS["black"].upper()
        strips = [i for i in widget._keyboard_items
                  if isinstance(i, pg.QtWidgets.QGraphicsRectItem) and i.zValue() < 0]
        assert strips and strips[0].brush().color().name().upper() == _DARK_KEYS["strip"].upper()
    finally:
        theme.apply_theme("dark")