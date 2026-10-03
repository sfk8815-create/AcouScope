# SPDX-License-Identifier: GPL-3.0-only
"""T-1036 轨身份色「内容色板」守卫（UI 视觉语言 · 阶段四配套）。

语义源：`内部记录/knowledge/RELEASE_T-1036.md`（定案 L1~L6）+ `内部记录/knowledge/ARCH_ui_visual_language.md §2.1-3`。
覆盖：
① 色板规模与唯一性（明/暗骨架各 12 色）；② 与 `TOKENS["semantic"]` 反馈色**零交集**（身份色 ≠ 反馈色）；
③ 逐色 vs 同骨架 `bg1` 对比度 ≥3:1（明/暗各一遍）；④ 相邻色色相间隔 ≥ `theme.TRACK_HUE_GAP_MIN`；
⑤ 索引映射与末位回绕；⑥ 两处硬编码（`track_header` 语义色表 / `track_model` `% 4`）消除（源码断言）；
⑦ 三个消费点取值仍为合法色串；⑧ 骨架判定与接口稳定 + 静态纪律（`theme.py` 外零 hex/px）。

口径：全离屏；不构造主窗口、不 show、不弹模态。
"""

import inspect
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

import numpy as np  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402

from acouscope.ui import theme  # noqa: E402
from acouscope.ui.widgets.multitrack import track_header, track_model  # noqa: E402
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession  # noqa: E402

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_MT = _SRC / "ui" / "widgets" / "multitrack"
_SKELETONS = ("dark", "light")
# 身份色板规模（L1：12 色；下限 10 由放行令「≥10–12」修正给出）
PALETTE_SIZE = 12
_LITERAL_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_LITERAL_PX = re.compile(r"\b\d+(?:\.\d+)?px\b")
_HEX_VALID = re.compile(r"^#[0-9a-fA-F]{6}$")
# 禁词（三类，拼接构造，守卫文件自身零完整字面量）
_BANNED = ("Mel" + "odyne", "Rea" + "per", "Sonic " + "Visualis")


# ----------------------------------------------------------------------
# WCAG 相对亮度 / 对比度 / HSV 色相（纯函数，不依赖 Qt）
# ----------------------------------------------------------------------

def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _hue(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    span = mx - mn
    if mx == r:
        deg = 60 * (((g - b) / span) % 6)
    elif mx == g:
        deg = 60 * ((b - r) / span + 2)
    else:
        deg = 60 * ((r - g) / span + 4)
    return deg % 360


def _hue_gap(a: str, b: str) -> float:
    d = abs(_hue(a) - _hue(b)) % 360
    return min(d, 360 - d)


def _palette(skeleton: str) -> list:
    return list(theme.TOKENS["track_palette"][skeleton])


# ----------------------------------------------------------------------
# ① 色板规模 / 唯一性
# ----------------------------------------------------------------------

def test_palette_size_unique_and_valid_hex():
    for sk in _SKELETONS:
        pal = _palette(sk)
        assert len(pal) == PALETTE_SIZE >= 10, f"{sk} 色板规模 {len(pal)}"
        assert len(set(pal)) == len(pal), f"{sk} 色板存在重复色"
        for col in pal:
            assert _HEX_VALID.match(col), f"{sk} 非法色值 {col}"


# ----------------------------------------------------------------------
# ② 身份色 ≠ 反馈色（与 semantic 零交集）
# ----------------------------------------------------------------------

def test_palette_disjoint_from_semantic_and_frozen():
    sem = theme.TOKENS["semantic"]
    for key, val in {
        "warning": "#f59e0b", "error": "#ef4444",
        "success": "#10b981", "info": "#3b82f6",
    }.items():
        assert sem[key] == val, f"语义色 {key} 被改动"
    sem_values = set(sem.values())
    for sk in _SKELETONS:
        assert set(_palette(sk)) & sem_values == set(), f"{sk} 身份色与语义反馈色重叠"


# ----------------------------------------------------------------------
# ③ 逐色对比度（对同骨架 bg1）
# ----------------------------------------------------------------------

def test_palette_contrast_vs_own_skeleton_bg1(qapp):
    theme.apply_theme("dark")
    try:
        for tid in theme.THEMES:
            theme.apply_theme(tid)
            c = theme.colors()
            bg1 = c["bg1"]
            sk = theme.skeleton_of(c)
            for col in theme.track_palette():
                ratio = _contrast(col, bg1)
                assert ratio >= 3.0, f"{tid}({sk}) 身份色 {col} vs bg1 {bg1} = {ratio:.2f} < 3.0"
    finally:
        theme.apply_theme("dark")


# ----------------------------------------------------------------------
# ④ 相邻色可辨（色相间隔）
# ----------------------------------------------------------------------

def test_palette_adjacent_hue_gap_meets_threshold():
    assert theme.TRACK_HUE_GAP_MIN > 0
    for sk in _SKELETONS:
        pal = _palette(sk)
        gaps = [_hue_gap(pal[i], pal[(i + 1) % len(pal)]) for i in range(len(pal))]
        assert min(gaps) >= theme.TRACK_HUE_GAP_MIN, \
            f"{sk} 最小相邻色相间隔 {min(gaps):.1f}° < {theme.TRACK_HUE_GAP_MIN}°"


# ----------------------------------------------------------------------
# ⑤ 索引映射 / 末位回绕
# ----------------------------------------------------------------------

def test_track_color_covers_palette_and_wraps(qapp):
    theme.apply_theme("dark")
    try:
        pal = theme.track_palette()
        assert [theme.track_color(i) for i in range(len(pal))] == pal
        assert len({theme.track_color(i) for i in range(len(pal))}) == len(pal)
        assert theme.track_color(len(pal)) == pal[0]       # 末位回绕
        assert theme.track_color(-1) == pal[-1]            # 负索引取末位
    finally:
        theme.apply_theme("dark")


def test_track_color_follows_skeleton(qapp):
    theme.apply_theme("dark")
    try:
        dark_pal = theme.track_palette()
        assert dark_pal == _palette("dark")
    finally:
        theme.apply_theme("dark")
    theme.apply_theme("light")
    try:
        light_pal = theme.track_palette()
        assert light_pal == _palette("light")
    finally:
        theme.apply_theme("dark")
    assert set(dark_pal) != set(light_pal)                 # 两骨架各自一套
    assert dark_pal[0] != light_pal[0]


def test_skeleton_flag_matches_bg0_luminance():
    for tid, c in theme.THEMES.items():
        expected = "dark" if _luminance(c["bg0"]) < 0.5 else "light"
        assert c["skeleton"] == expected, f"{tid} skeleton 标记与 bg0 亮度不符"
    for sk in _SKELETONS:
        assert theme.skeleton_of(theme.THEMES["dark" if sk == "dark" else "light"]) == sk


# ----------------------------------------------------------------------
# ⑥ 两处硬编码消除（源码断言）
# ----------------------------------------------------------------------

def test_header_track_color_uses_palette_not_semantic():
    sig = inspect.signature(track_header.track_color)
    assert list(sig.parameters) == ["index"]               # 签名不变
    assert sig.parameters["index"].annotation in (int, "int")
    assert sig.return_annotation in (str, "str")
    text = (_MT / "track_header.py").read_text(encoding="utf-8")
    assert "TOKENS[\"semantic\"]" not in text.split("def track_color")[1].split("def ")[0]
    assert theme.track_color(0) == theme.track_palette()[0]


def test_track_model_has_no_hardcoded_four():
    text = (_MT / "track_model.py").read_text(encoding="utf-8")
    assert re.search(r"%\s*4\b", text) is None, "track_model.py 仍存在硬编码 % 4"


def test_session_color_index_cycles_over_palette(qapp):
    theme.apply_theme("dark")
    try:
        session = MultitrackSession(
            metadata_reader=lambda p: {"sample_rate": 8000, "channels": 1, "duration": 0.1},
            envelope_reader=lambda p, points: (
                np.linspace(0.0, 0.1, points), np.zeros(points, dtype=np.float32)
            ),
            loader=lambda p: (np.zeros(8), 8000),
        )
        n = len(theme.track_palette())
        tracks = [session.add_path(f"/tmp/t1036_{i}.wav") for i in range(n + 1)]
        assert [t.color_index for t in tracks] == [i % n for i in range(n + 1)]
        assert tracks[n].color_index == 0                  # 回绕
        colors = [theme.track_color(t.color_index) for t in tracks[:n]]
        assert len(set(colors)) == n                       # ≥12 轨各色互异
    finally:
        theme.apply_theme("dark")


# ----------------------------------------------------------------------
# ⑦ 三个消费点（预期零改动）取值仍合法
# ----------------------------------------------------------------------

def test_consumers_still_render_valid_colors(qapp):
    theme.apply_theme("dark")
    try:
        from acouscope.ui.widgets.multitrack.compare_present import TrackSeries

        for i in range(len(theme.track_palette())):
            series = TrackSeries(track_id=f"t{i}", label=f"t{i}", color_index=i)
            assert series.color == theme.track_color(i)
            assert QColor(series.color).isValid()
            assert QColor(track_header.track_color(i)).isValid()
        # 消费点仍经同一入口取色（源码级确认「无需改动」）
        view_src = (_MT / "multitrack_view.py").read_text(encoding="utf-8")
        present_src = (_MT / "compare_present.py").read_text(encoding="utf-8")
        assert "QColor(track_color(track.color_index))" in view_src
        assert "return track_color(self.color_index)" in present_src
    finally:
        theme.apply_theme("dark")


# ----------------------------------------------------------------------
# ⑧ 静态纪律
# ----------------------------------------------------------------------

def test_changed_files_have_zero_literal_hex_and_px():
    for name in ("track_header.py", "track_model.py"):
        text = (_MT / name).read_text(encoding="utf-8")
        assert _LITERAL_HEX.search(text) is None, f"{name} 出现字面 hex"
        assert _LITERAL_PX.search(text) is None, f"{name} 出现字面 px"


def test_no_banned_words_in_touched_artifacts():
    paths = [(_MT / "track_header.py"), (_MT / "track_model.py"), _SRC / "ui" / "theme.py"]
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        for word in _BANNED:
            assert word.lower() not in text, f"{path.name} 命中禁词"
    assert track_model.__name__ and theme.__name__        # 导入面完好（防误删模块级名）
