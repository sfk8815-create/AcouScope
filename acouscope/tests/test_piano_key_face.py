# SPDX-License-Identifier: GPL-3.0-only
"""T-1042b 钢琴键面 **v2 定形**守卫（单套物理色 + 黑键贴左 + 白键右端小圆角 + 明暗同款）。

语义源：`.pi/knowledge/ARCH_ui_visual_language.md §2.1-5/§五c(v1.5)/§六-10`
与 `.pi/tasks/T-1042b.txt`（v2 定形：单套物理色 + 几何硬指标 + 明暗同款 + 缩放不变形）。
覆盖：
① `TOKENS["keys"]` **单套物理色**四角色齐备、取值合法 hex、**明/暗骨架 `key_faces()` 逐字相等**（硬断言）；
② 白键亮度恒 > 黑键亮度且差值 ≥ 0.45；白键缝 `white_seam` 比白键暗（去「格子纸」）；
③ **去强描边**：白键间分隔只用 `keys.white_seam`（不出现 `border` 作键面描边），黑键无描边；
④ **去金色中央 C**：`freq_axis.py` / `spectrum.py` 内**不出现任何 `TOKENS["semantic"]`**；
⑤ **几何 v2**：黑键长/白键满宽 = 0.46 ∈ [0.45, 0.50]；黑键高 = 0.55 ∈ [0.54, 0.58]；`BLACK_X0 == 0.0` 贴左；
⑥ **圆角**：两键盘均使用 `QGraphicsPathItem` + 一端圆角路径 `rounded_end_rect`（禁四角 `addRoundedRect`）；
⑦ **色值唯一源**：键面色只在 `theme.py`，两文件内字面 hex = 0 / 字面 px = 0；
⑧ **主题往返**：dark→light→dark 后 `key_faces()` 仍逐字相等（单套物理色恒等）；
⑨ 实机建键（离屏）：竖排 `PianoKeyboardStrip` 与横排 `SpectrumWidget` 键面带底/圆角/中央C加粗均可实例化可读；
⑩ 键面内音名文字用 `keys.label`（freq_axis 中央 C 标签取色入口）。

★ T-1042b 非静默归因（相对 T-1042 旧守卫，本文件为 v2 版本）：
- `TOKENS["keys"]` 由「dark/light 两套（含 strip 角色）」改为「**单套 physical**（white/black/white_seam/label）」；
  旧 `strip` 角色废除 → 键带底/gutter 随骨架 `bg2`（ARCH §五c v1.5「非键面主角」，两 widget 经
  `theme.colors()["bg2"]` 取，不再经 keys 令牌）。
- 旧「黑键 vs strip 可分辨」断言随 strip 角色废除作废（v2 暗骨架 gutter=bg2 #1E2227 与黑键 #1E1E1E
  相近属设计内：黑键行间隙与黑键连成一片暗面）；以「white−black 明度差 ≥ 0.45 + 单套物理色恒等」
  承接其「键面可辨」强度。
- 黑键几何由「宽比 0.58–0.60 / 高 0.58–0.62 / X0 居中偏左」改为「**长比 0.46 / 高 0.55 / X0=0 贴左**」
  （任务书 §2 参考图量化硬指标，旧值作废）。
- 白键由「直角 QGraphicsRectItem」改为「**右端小圆角 QGraphicsPathItem**」（旧规「白键不加圆角」作废）；
- 黑键由「addRoundedRect 四角同圆角」改为「`rounded_end_rect` **仅右端圆角**（左端直角贴左）」。

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
_ROLES = ("white", "black", "white_seam", "label")
_KEYS_PHYSICAL = {"white": "#D4D4D6", "black": "#1E1E1E",
                  "white_seam": "#C6C6C8", "label": "#3A3A3A"}
_LITERAL_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_LITERAL_PX = re.compile(r"\b\d+(?:\.\d+)?px\b")
_HEX_VALID = re.compile(r"^#[0-9a-fA-F]{6}$")

# ★ 明度分层阈值（写入报告依据）：white−black 明度差 ≥ 0.45（ARCH §六-10 键面可辨评审口径）。
KEY_LUMINANCE_GAP_MIN = 0.45
# 黑键几何硬指标（任务书 §2 / 参考图量化）：长比 0.46（区间 0.45–0.50）；高 0.55（区间 0.54–0.58）。
BLACK_W_RATIO_TARGET = 0.46
BLACK_W_RATIO_MIN, BLACK_W_RATIO_MAX = 0.45, 0.50
BLACK_H_TARGET = 0.55
BLACK_H_MIN, BLACK_H_MAX = 0.54, 0.58
# 圆角硬指标：白键右端 r ≈ 半音高 6–10%（取 8%）；黑键右端 r ≈ 黑键高 15–20%（取 17%）。
WHITE_KEY_R_MIN, WHITE_KEY_R_MAX = 0.06, 0.10
BLACK_KEY_R_RATIO_MIN, BLACK_KEY_R_RATIO_MAX = 0.15, 0.20


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _src(name: str) -> str:
    return (_WIDGETS / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# ① TOKENS["keys"] 单套物理色齐备 / 合法 / 明暗同款（硬断言）
# ----------------------------------------------------------------------

def test_keys_roles_present_and_valid_hex():
    group = theme.TOKENS["keys"]
    assert tuple(group["roles"]) == tuple(_ROLES)
    pal = group["physical"]
    assert set(_ROLES) <= set(pal), "物理色缺键面角色"
    for role in _ROLES:
        assert _HEX_VALID.match(pal[role]), f"{role} 非法色值"
    # 单套物理色：不再有 dark/light 两套骨架索引
    assert "dark" not in group and "light" not in group
    assert "physical" in group


def test_key_faces_identical_across_skeletons(qapp):
    """★ 本笔硬断言：明/暗两骨架调用 key_faces() 必须返回**同一字典**（逐字相等）。"""
    theme.apply_theme("dark")
    dark_faces = theme.key_faces()
    theme.apply_theme("light")
    light_faces = theme.key_faces()
    theme.apply_theme("dark")
    assert dark_faces == light_faces, "明暗骨架 key_faces() 未返回同一字典"
    assert dark_faces == dict(_KEYS_PHYSICAL)


def test_white_black_luminance_gap():
    """white − black 明度差 ≥ 0.45，且 white 严格亮于 black（单套物理色恒成立）。"""
    pal = theme.TOKENS["keys"]["physical"]
    assert pal == _KEYS_PHYSICAL, "键面物理色与数据源不一致"
    white, black = _luminance(pal["white"]), _luminance(pal["black"])
    assert white > black, "白键未亮于黑键"
    gap = white - black
    assert gap >= KEY_LUMINANCE_GAP_MIN, f"白黑明度差 {gap:.3f} 不足"


def test_seam_darker_than_white():
    """白键缝 `white_seam` 必须比白键面暗（去「格子纸」前提）；勿用 border。"""
    pal = theme.TOKENS["keys"]["physical"]
    assert _luminance(pal["white_seam"]) < _luminance(pal["white"]), "white_seam 未暗于 white"
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
    pal = theme.TOKENS["keys"]["physical"]
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
# ⑤ 几何 v2（竖排 PianoKeyboardStrip 为准，横排按旋转同规 / 同一常量来源）
# ----------------------------------------------------------------------

def test_vertical_piano_geometry_v2():
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    ratio = PianoKeyboardStrip.BLACK_W / PianoKeyboardStrip.WHITE_W
    assert BLACK_W_RATIO_MIN <= ratio <= BLACK_W_RATIO_MAX, f"黑键长/白键满宽 = {ratio:.3f}"
    assert abs(ratio - BLACK_W_RATIO_TARGET) < 0.01, f"黑键长比未取 0.46（实测 {ratio:.3f}）"
    assert BLACK_H_MIN <= PianoKeyboardStrip.BLACK_H <= BLACK_H_MAX, \
        f"黑键高 = {PianoKeyboardStrip.BLACK_H:.3f}"
    assert abs(PianoKeyboardStrip.BLACK_H - BLACK_H_TARGET) < 0.01
    # 黑键贴左：X0 必须为 0（零内缩，参考图「自左缘起算」）
    assert PianoKeyboardStrip.BLACK_X0 == 0.0, \
        f"BLACK_X0 = {PianoKeyboardStrip.BLACK_X0} 未贴左（应为 0.0）"


def test_key_round_radii_v2():
    """圆角硬指标：白键右端 r ∈ 半音高 6–10%；黑键右端 r ∈ 黑键高 15–20%。"""
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    assert WHITE_KEY_R_MIN <= PianoKeyboardStrip.WHITE_KEY_R <= WHITE_KEY_R_MAX, \
        f"白键圆角 r = {PianoKeyboardStrip.WHITE_KEY_R:.3f}"
    r_ratio = PianoKeyboardStrip.BLACK_KEY_R / PianoKeyboardStrip.BLACK_H
    assert BLACK_KEY_R_RATIO_MIN <= r_ratio <= BLACK_KEY_R_RATIO_MAX, \
        f"黑键圆角 r/黑键高 = {r_ratio:.3f}"


# ----------------------------------------------------------------------
# ⑥ 圆角实现（源码级：一端圆角路径，禁四角 addRoundedRect）
# ----------------------------------------------------------------------

def test_black_keys_rounded_paths():
    """两键盘的圆角实现：使用 QPainterPath + 一端圆角路径 `rounded_end_rect` + QGraphicsPathItem。"""
    for name in _INK_FILES:
        text = _src(name)
        assert 'rounded_end_rect(' in text, f"{name} 未用一端圆角路径"
        assert 'QGraphicsPathItem(path)' in text, f"{name} 键面未用路径元素"
        # 禁四角同圆角（会掏空圆角端的对端，破坏贴左/贴缝）
        assert 'addRoundedRect(' not in text, f"{name} 仍用四角 addRoundedRect"


def test_rounded_end_rect_empirical():
    """圆角实证：包围盒角点（圆角端）在路径外、中心点在路径内（任务书自证 #6）。"""
    from acouscope.ui.widgets.freq_axis import rounded_end_rect

    x, y, w, h, r = 0.0, 0.0, 1.84, 0.55, 0.09
    path = rounded_end_rect(x, y, w, h, r, end="right")
    center = pg.QtCore.QPointF(x + w / 2, y + h / 2)
    assert path.contains(center), "黑键中心点应在路径内"
    # 右端（圆角端）包围盒角点在路径外
    assert not path.contains(pg.QtCore.QPointF(x + w, y)), "右上角点应在路径外（已圆角）"
    assert not path.contains(pg.QtCore.QPointF(x + w, y + h)), "右下角点应在路径外（已圆角）"
    # 左端（贴左直角端）内侧点在路径内
    assert path.contains(pg.QtCore.QPointF(x + r / 2, y + r / 2)), "贴左端内侧应在路径内"
    assert path.contains(pg.QtCore.QPointF(x + r / 2, y + h - r / 2)), "贴左端下内侧应在路径内"


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
    for role, color in theme.TOKENS["keys"]["physical"].items():
        assert color in theme_src, f"{color}（{role}）应唯一存在于 theme.py"
    for name in _INK_FILES:
        assert 'key_faces()' in _src(name), f"{name} 未经 key_faces() 取键面色"


# ----------------------------------------------------------------------
# ⑧ 主题往返：dark→light→dark 后 key_faces() 仍逐字相等（单套物理色恒等）
# ----------------------------------------------------------------------

def test_key_faces_roundtrip_dark_light_dark(qapp):
    def faces_dark():
        theme.apply_theme("dark")
        return theme.key_faces()

    base = faces_dark()
    assert base == dict(_KEYS_PHYSICAL)
    theme.apply_theme("light")
    assert theme.key_faces() == base
    theme.apply_theme("dark")
    assert theme.key_faces() == base, "dark→light→dark 后键面物理色未逐值回原"


def test_key_face_entry_point_and_error(qapp):
    theme.apply_theme("dark")
    try:
        assert theme.key_face("white") == _KEYS_PHYSICAL["white"]
        assert theme.key_face("label") == _KEYS_PHYSICAL["label"]
        with pytest.raises(KeyError):
            theme.key_face("__nope__")
    finally:
        theme.apply_theme("dark")


# ----------------------------------------------------------------------
# ⑨ 实机建键（离屏）：分层 / 圆角 / 中央 C 加粗可读
# ----------------------------------------------------------------------

def test_vertical_keyboard_builds_layered(qapp):
    from acouscope.dsp.units import midi_is_black_key, midi_is_white_key
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    theme.apply_theme("dark")
    try:
        strip = PianoKeyboardStrip()
        strip._build_keys()
        # 键带底位于最底层（负 z），铺满整条；v2 起随骨架 bg2（strip 角色废除）
        base = strip._key_items[0]
        assert isinstance(base, pg.QtWidgets.QGraphicsRectItem)
        assert base.zValue() < 0
        assert base.brush().color().name().upper() == theme.colors()["bg2"].upper()
        # 黑白键均为一端圆角路径（白键在前、黑键在后，总路径数 = 白键数 + 黑键数）
        n_black = sum(1 for m in range(128) if midi_is_black_key(m))
        n_white = sum(1 for m in range(128) if midi_is_white_key(m))
        paths = [i for i in strip._key_items if isinstance(i, pg.QtWidgets.QGraphicsPathItem)]
        assert len(paths) == n_black + n_white, \
            f"键路径数 {len(paths)} ≠ 白{n_white}+黑{n_black}"
        whites, blacks = paths[:n_white], paths[n_white:]
        for p in whites[:5]:
            assert p.brush().color().name().upper() == _KEYS_PHYSICAL["white"].upper()
            assert p.pen().color().name().upper() == _KEYS_PHYSICAL["white_seam"].upper()
        for p in blacks[:5]:
            assert p.brush().color().name().upper() == _KEYS_PHYSICAL["black"].upper()
            assert p.pen().style() == pg.QtCore.Qt.PenStyle.NoPen, "黑键不应有可见描边"
            assert p.zValue() == 20
        # 黑键贴左：黑键路径包围盒左缘 == BLACK_X0 == 0.0
        bbox = blacks[0].boundingRect()
        assert abs(bbox.x()) < 1e-6, f"黑键包围盒左缘 {bbox.x()} 未贴左"
        # 中央 C 加粗标签 + 音名文字用 keys.label
        assert strip._center_c_label.textItem.font().bold()
        assert strip._center_c_label.color.name().upper() == _KEYS_PHYSICAL["label"].upper()
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
        assert len(paths) > 0, "横排键盘未生成圆角键"
        for p in paths:
            if p.brush().color().name().upper() == _KEYS_PHYSICAL["black"].upper():
                assert p.pen().style() == pg.QtCore.Qt.PenStyle.NoPen, "黑键不应有描边"
        strips = [i for i in widget._keyboard_items
                  if isinstance(i, pg.QtWidgets.QGraphicsRectItem) and i.zValue() < 0]
        assert strips and strips[0].brush().color().name().upper() == theme.colors()["bg2"].upper()
    finally:
        theme.apply_theme("dark")
