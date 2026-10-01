# SPDX-License-Identifier: GPL-3.0-only
"""T-1038 画布「数据墨色」令牌化 + 旁路 QSS 收口守卫。

语义源：`.pi/knowledge/RELEASE_T-1038.md`（裁定 M1~M6）+ `.pi/knowledge/DESIGN_inspiration_notes.md §9.3`。
覆盖：
① 改动面文件 `#hex` = 0 / 字面 px = 0（`theme.py` 仅数据源允许 hex，px 仍须 0）；
② `TOKENS["data"]` 六角色齐备且明/暗两套均备；③ `data` 与 `semantic`/`accent` 取值零交集；
④ 8 个画布文件均订阅 `theme.on_theme_change` 且含墨色重设（`_apply_ink`）；
⑤ M5 明度关系：明/暗两骨架下白键明度 > 黑键明度（黑键 `bg0` / 中央 C 保持 `bg3`）；
⑥ 主题往返后墨色随动（实测 QPen 颜色）；⑦ 多序列分类色复用 T-1036 内容色板（无第二套）。

口径：全离屏；不构造主窗口、不 show、不弹模态。
"""

import inspect
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from acouscope.ui import theme  # noqa: E402

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_W = _SRC / "ui" / "widgets"
# 改动面：8 画布文件 + freq_axis + room_acoustics_dialog（theme.py 数据源另判 hex）
_INK_FILES = (
    "spectrum.py", "spectrogram.py", "pitch.py", "formants.py", "timbre.py",
    "waveform.py", "room_modes.py", "realtime_features.py", "freq_axis.py",
    "room_acoustics_dialog.py",
)
# 8 个画布文件（M6 要求订阅主题变化并在回调内重设墨色）
_CANVAS_FILES = _INK_FILES[:8]
_DATA_ROLES = ("trace", "trace_alt", "cursor", "marker", "ref_line", "tint")
_LITERAL_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_LITERAL_PX = re.compile(r"\b\d+(?:\.\d+)?px\b")
_HEX_VALID = re.compile(r"^#[0-9a-fA-F]{6}$")
_BANNED = ("Mel" + "odyne", "Rea" + "per", "Sonic " + "Visualis")


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _src(name: str) -> str:
    return (_W / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# ② TOKENS["data"] 角色齐备 / 两套骨架
# ----------------------------------------------------------------------

def test_data_roles_and_skeletons_present():
    group = theme.TOKENS["data"]
    assert tuple(group["roles"]) == _DATA_ROLES
    for sk in ("dark", "light"):
        palette = group[sk]
        assert set(_DATA_ROLES) <= set(palette), f"{sk} 缺数据墨色角色"
        for role in _DATA_ROLES:
            assert _HEX_VALID.match(palette[role]), f"{sk}.{role} 非法色值"
    assert theme.data_ink("trace") in tuple(theme.TOKENS["data"]["dark"].values()) + \
        tuple(theme.TOKENS["data"]["light"].values())
    with pytest.raises(KeyError):
        theme.data_ink("__nope__")


# ----------------------------------------------------------------------
# ③ 三权分立：data ∩ semantic / accent = ∅
# ----------------------------------------------------------------------

def test_data_disjoint_from_semantic_and_accent(qapp):
    data_values = set()
    for sk in ("dark", "light"):
        data_values |= set(theme.TOKENS["data"][sk].values())
    assert data_values & set(theme.TOKENS["semantic"].values()) == set()
    accents = {c["accent"] for c in theme.THEMES.values()}
    assert data_values & accents == set()
    # accent 的单强调色地位不变：仍每套恰一个 accent 值
    for tid, c in theme.THEMES.items():
        assert list(c).count("accent") == 1, tid
    theme.apply_theme("dark")


def test_data_ink_follows_skeleton(qapp):
    theme.apply_theme("dark")
    try:
        assert theme.data_ink("trace") == theme.TOKENS["data"]["dark"]["trace"]
        assert theme.data_ink("tint") == theme.TOKENS["data"]["dark"]["tint"]
    finally:
        theme.apply_theme("dark")
    theme.apply_theme("light")
    try:
        assert theme.data_ink("trace") == theme.TOKENS["data"]["light"]["trace"]
        assert theme.data_ink("cursor") == theme.TOKENS["data"]["light"]["cursor"]
    finally:
        theme.apply_theme("dark")


# ----------------------------------------------------------------------
# ① 静态纪律：改动面无字面 hex / 字面 px
# ----------------------------------------------------------------------

def test_ink_files_have_zero_literal_hex_and_px():
    for name in _INK_FILES:
        text = _src(name)
        assert _LITERAL_HEX.search(text) is None, f"{name} 残留字面 hex"
        assert _LITERAL_PX.search(text) is None, f"{name} 残留字面 px"
    theme_src = (_SRC / "ui" / "theme.py").read_text(encoding="utf-8")
    assert _LITERAL_PX.search(theme_src) is None, "theme.py 残留字面 px"


# ----------------------------------------------------------------------
# ④ 8 画布文件订阅主题变化且有墨色重设
# ----------------------------------------------------------------------

def test_canvas_files_subscribe_and_reset_ink():
    for name in _CANVAS_FILES:
        text = _src(name)
        assert "on_theme_change(" in text, f"{name} 未订阅主题变化"
        assert "_apply_ink(" in text, f"{name} 未在回调内重设墨色"
        assert "data_ink(" in text, f"{name} 未取数据墨色令牌"


# ----------------------------------------------------------------------
# ⑥ 主题往返：墨色实测随动
# ----------------------------------------------------------------------

@pytest.fixture(scope="function")
def ink_probe(qapp):
    from acouscope.ui.widgets.pitch import PitchContourWidget
    from acouscope.ui.widgets.spectrum import SpectrumWidget
    from acouscope.ui.widgets.waveform import WaveformWidget

    widgets = (WaveformWidget(), SpectrumWidget(), PitchContourWidget())
    yield {
        "waveform": widgets[0],
        "spectrum": widgets[1],
        "pitch": widgets[2],
        "widgets": widgets,
    }
    theme.apply_theme("dark")


def _pen_hex(item) -> str:
    """取绘图项当前画笔色（PlotDataItem 走 opts，InfiniteLine 走 pen 属性）。"""
    pen = item.opts["pen"] if hasattr(item, "opts") else item.pen
    return pen.color().name().upper()


def test_ink_refresh_is_live_and_roundtrips(qapp, ink_probe):
    theme.apply_theme("dark")
    waveform = ink_probe["waveform"]
    spectrum = ink_probe["spectrum"]
    pitch = ink_probe["pitch"]
    assert _pen_hex(waveform.curve) == theme.TOKENS["data"]["dark"]["trace"].upper()
    assert _pen_hex(spectrum.curve) == theme.TOKENS["data"]["dark"]["trace"].upper()
    assert _pen_hex(pitch.v_line) == theme.TOKENS["data"]["dark"]["cursor"].upper()

    theme.apply_theme("light")
    assert _pen_hex(waveform.curve) == theme.TOKENS["data"]["light"]["trace"].upper()
    assert _pen_hex(spectrum.curve) == theme.TOKENS["data"]["light"]["trace"].upper()
    assert _pen_hex(pitch.v_line) == theme.TOKENS["data"]["light"]["cursor"].upper()

    theme.apply_theme("dark")
    assert _pen_hex(waveform.curve) == theme.TOKENS["data"]["dark"]["trace"].upper()
    assert _pen_hex(spectrum.curve) == theme.TOKENS["data"]["dark"]["trace"].upper()
    assert _pen_hex(pitch.v_line) == theme.TOKENS["data"]["dark"]["cursor"].upper()


# ----------------------------------------------------------------------
# ⑤ M5（d5 修正）：白键明度 > 黑键明度（明/暗两骨架）
# ----------------------------------------------------------------------

def test_m5_white_key_brighter_than_black_key_all_skeletons():
    # T-1042 归因：钢琴键盘改走 TOKENS["keys"] 后，本断言仍在验证「中性阶 bg1 恒亮于 bg0」
    # （中性骨架关系不变），键面自身的明度分层改由 test_piano_key_face.py 用 keys.token 覆盖。
    for tid, c in theme.THEMES.items():
        white, black = _luminance(c["bg1"]), _luminance(c["bg0"])
        assert white > black, f"{tid} 白键({c['bg1']}) 未亮于黑键({c['bg0']})"


def test_m5_key_source_uses_keys_token_no_semantic_center():
    """T-1042 归因：原断言「键面取 bg0 / 中央 C 取 bg3」随键面重设计作废。

    新键面取色改走 `theme.key_faces()` 的 `TOKENS["keys"]`（物理面色阶，白恒亮/黑恒暗），
    中央 C 用**文字加粗**强调（不再取 bg3 强调；`freq_axis` 已叠 `_center_c_label`）。
    T-1038 → T-1042 守卫强度只增不降：新增断言两文件内**不得出现任何 `TOKENS["semantic"]`**。

    ★ T-1042b 非静默归因：旧断言 `'faces["strip"]' in 两文件` 随 `TOKENS["keys"]` 改
    **单套物理色**（strip 角色废除，键带底/gutter 随骨架 `bg2`）作废；以更强的
    「键带底经 `theme.colors()["bg2"]` 取（源码无字面 hex）+ `faces["black"]/["white_seam"]`
    仍经 key_faces() 取」承接，取值来源唯一性强度不减。

    ★ T-1042c 非静默归因：中央 C 加粗标签与音名**落位键床内**后，字体构造收敛到
    `PianoKeyboardStrip._name_fonts()`（返回 base/bold 两字体），取色改经 `faces = key_faces()`
    后按角色索引 —— 故旧字面量断言 `'cfont.setBold(True)'` / `'theme.key_face("label")'`
    作废；改断「`bold.setBold(True)` 构造加粗字体 + `bold_font if is_center` 把加粗字体
    真正应用到中央 C 标签 + `faces["label"]` 取音名色」，**从「建了加粗字体」升级为
    「加粗字体确被中央 C 标签使用」**，且 `_center_c_label` 与运行时 `font().bold()`
    （test_piano_key_face.py ⑨）两道守卫均在 → 强度只增不减。
    """
    freq_axis = _src("freq_axis.py")
    spectrum = _src("spectrum.py")
    assert 'black_brush = pg.mkBrush(faces["black"])' in freq_axis
    assert 'key_black = pg.mkBrush(faces["black"])' in spectrum
    # 键带底/gutter 随骨架 bg2（ARCH §五c v1.5「非键面主角」，经 theme.colors() 取、无字面 hex）
    assert 'theme.colors()["bg2"]' in freq_axis and 'theme.colors()["bg2"]' in spectrum
    assert 'faces["white_seam"]' in freq_axis and 'faces["white_seam"]' in spectrum
    # 去金色：两文件内不再出现任何语义反馈色取值
    assert "TOKENS[\"semantic\"]" not in freq_axis, "freq_axis.py 残留语义色（中央 C 应去金色）"
    assert "TOKENS[\"semantic\"]" not in spectrum, "spectrum.py 残留语义色（中央 C 应去金色）"
    # 中央 C 文字强调（freq_axis 专用加粗标签；T-1042b：音名文字色取 keys.label）
    assert "_center_c_label" in freq_axis
    assert 'bold.setBold(True)' in freq_axis, "未构造加粗字体（中央 C 加粗强调）"
    assert 'bold_font if is_center' in freq_axis, "加粗字体未应用到中央 C 标签（仅构造不算）"
    assert 'faces["label"]' in freq_axis, "音名文字色未取 keys.label 角色"
    assert 'color=faces["label"]' in spectrum, "横排音名文字色未取 keys.label 角色"


# ----------------------------------------------------------------------
# ⑦ 多序列分类色复用 T-1036 内容色板（禁第二套）
# ----------------------------------------------------------------------

def test_formants_reuse_content_palette(qapp):
    from acouscope.ui.widgets.formants import FORMANT_COUNT, formant_colors

    theme.apply_theme("dark")
    try:
        assert formant_colors() == theme.track_palette()[:FORMANT_COUNT]
    finally:
        theme.apply_theme("dark")
    src = _src("formants.py")
    assert "FORMANT_COLORS" not in src                    # 旧四色常量已消除
    assert "track_palette()" in src


def test_timbre_and_room_modes_reuse_content_palette(qapp):
    from acouscope.ui.widgets.room_modes import mode_ink
    from acouscope.ui.widgets.timbre import feature_colors

    theme.apply_theme("dark")
    try:
        palette = theme.track_palette()
        assert set(feature_colors().values()) <= set(palette)
        kinds = ("axial", "tangential", "oblique")
        colors = [mode_ink(k) for k in kinds]
        assert len(set(colors)) == 3 and set(colors) <= set(palette)
    finally:
        theme.apply_theme("dark")
    assert "FEATURE_COLORS" not in _src("timbre.py")


def test_public_entry_signatures_stable():
    assert list(inspect.signature(theme.data_ink).parameters) == ["role", "colors_dict"]
    assert list(inspect.signature(theme.track_palette).parameters) == ["colors_dict"]


def test_no_banned_words_in_touched_artifacts():
    for name in _INK_FILES:
        text = _src(name).lower()
        for word in _BANNED:
            assert word.lower() not in text, f"{name} 命中禁词"
