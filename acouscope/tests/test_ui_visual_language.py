# SPDX-License-Identifier: GPL-3.0-only
"""T-1031 视觉语言守卫（阶段二：主题层收敛 + App 基座）。

语义源：`.pi/knowledge/ARCH_ui_visual_language.md`（§六 可验证验收口径）。
覆盖：
① 令牌唯一源：`theme._qss` 源码内散落 px / 字面 hex = 0；TOKENS 含 control/neutral；
② 对比度实测：正文 ≥4.5:1 / 次级 ≥3:1 / 禁用 text_faint ≥3:1 / accent 前景 ≥4.5:1 /
   accent_text/accent ≥4.5:1（9 套 × bg0..bg3 全量）；
③ 单强调色：每套仅 1 个 accent，sel_bg 同族低饱和（色相差 ≤25°）；
④ 语义色不变：4 个功能色逐字一致；
⑤ 主题集不降：THEME_ORDER ⊇ 原 9 + system（条目零删除）；
⑥ 中性阶 + 旧键别名：12 角色齐备、别名映射值恒等（colors() 旧键继续可用）；
⑦ 裁定 F′：App 基座（Fusion + 全局字体）只入 `__main__.py`，不进 apply_theme；
⑧ 裁定 E′：theme.ICONS 30 名（T-1025 授权 +9 图标补齐）、图标状态色角色表不变；
⑨ 主题下拉分组：主区 3 项在前 + 「更多配色」次级区，分组标题不可选、条目零丢失。

口径：全离屏；不构造主窗口、不 show、不弹模态。
"""

import inspect
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from acouscope.ui import theme  # noqa: E402

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_THEME_PY = _SRC / "ui" / "theme.py"
_MAIN_PY = _SRC / "__main__.py"

# 主区 3 项（跟随系统 / 深色 / 浅色）——其余全部入「更多配色」
_PRIMARY = ("system", "dark", "light")
_ROLES = ("bg0", "bg1", "bg2", "bg3", "border", "border_strong",
          "text", "text_sub", "text_faint", "accent", "accent_text", "sel_bg")
_SEMANTIC = {
    "warning": "#f59e0b", "error": "#ef4444",
    "success": "#10b981", "info": "#3b82f6",
}

_LITERAL_PX = re.compile(r"\b\d+(?:\.\d+)?px\b")
_LITERAL_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


# ----------------------------------------------------------------------
# WCAG 对比度（纯函数，不依赖 Qt）
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
    """HSV 色相（0~360）。"""
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


# ----------------------------------------------------------------------
# ① 令牌唯一源
# ----------------------------------------------------------------------

def test_qss_has_zero_literal_px_and_hex():
    """`_qss` 源码内散落 px / 字面 hex = 0（全部经 TOKENS 插值）。"""
    src = inspect.getsource(theme._qss)
    assert _LITERAL_PX.findall(src) == [], f"散落像素: {_LITERAL_PX.findall(src)}"
    assert _LITERAL_HEX.findall(src) == [], f"字面颜色: {_LITERAL_HEX.findall(src)}"


def test_qss_applies_token_values():
    """QSS 实际输出取自 TOKENS（抽样：描边宽度 / 控件内距 / 圆角 / 节拍高度）。"""
    qss = theme._qss(theme.THEMES["dark"])
    el = theme.TOKENS["elevation"]
    ctl = theme.TOKENS["control"]
    rad = theme.TOKENS["radius"]
    assert f"border-bottom: {el['border']}px" in qss
    assert f"padding: {ctl['pad_y']}px {ctl['pad_x']}px" in qss
    assert f"border-radius: {rad['sm']}px" in qss
    assert f"width: {ctl['pad_x']}px" in qss and f"min-height: {ctl['h_lg']}px" in qss
    # 语义色 + 电平属性仍在（既有硬断言同源）
    for hexcolor in _SEMANTIC.values():
        assert hexcolor in qss


def test_tokens_extended_control_and_neutral():
    t = theme.TOKENS
    assert t["control"] == {"h_sm": 24, "h_md": 28, "h_lg": 32,
                            "pad_x": 10, "pad_y": 4, "gap": 6}
    assert tuple(t["neutral"]["roles"]) == _ROLES
    assert t["neutral"]["alias"] == theme.NEUTRAL_ALIAS
    assert t["control"]["h_sm"] < t["control"]["h_md"] < t["control"]["h_lg"]
    # 既有令牌未被改动
    assert t["spacing"]["sm"] == 8 and t["radius"]["md"] == 8
    assert t["elevation"]["mid"] == 4


# ----------------------------------------------------------------------
# ② 对比度 / ④ 语义色
# ----------------------------------------------------------------------

def test_contrast_thresholds_all_themes():
    """9 套全量 × bg0..bg3：正文 ≥4.5、次级 ≥3、禁用 ≥3、accent 前景 ≥4.5、accent_text/accent ≥4.5。"""
    for tid, c in theme.THEMES.items():
        for bgk in ("bg0", "bg1", "bg2", "bg3"):
            body = _contrast(c["text"], c[bgk])
            sub = _contrast(c["text_sub"], c[bgk])
            faint = _contrast(c["text_faint"], c[bgk])
            acl = _contrast(c["accent"], c[bgk])
            assert body >= 4.5, f"{tid}/{bgk} 正文对比度 {body:.2f} < 4.5"
            assert sub >= 3.0, f"{tid}/{bgk} 次级对比度 {sub:.2f} < 3.0"
            assert faint >= 3.0, f"{tid}/{bgk} 禁用 text_faint 对比度 {faint:.2f} < 3.0"
            assert acl >= 4.5, f"{tid}/{bgk} accent 前景对比度 {acl:.2f} < 4.5"
        accent = _contrast(c["accent_text"], c["accent"])
        assert accent >= 4.5, f"{tid} accent_text/accent 对比度 {accent:.2f} < 4.5"


def test_semantic_colors_frozen():
    sem = theme.TOKENS["semantic"]
    for key, hexcolor in _SEMANTIC.items():
        assert sem[key] == hexcolor


# ----------------------------------------------------------------------
# ③ 单强调色
# ----------------------------------------------------------------------

def test_single_accent_and_sel_bg_same_family():
    for tid, c in theme.THEMES.items():
        assert _hue_gap(c["accent"], c["sel_bg"]) <= 25.0, \
            f"{tid}: sel_bg 与 accent 非同一色族（差 {_hue_gap(c['accent'], c['sel_bg']):.1f}°）"
        assert c["sel_bg"] != c["accent"]
        # 每套仅 1 个 accent 值（键唯一）
        assert list(c).count("accent") == 1


def test_neutral_ladder_monotonic():
    """明度阶梯：同骨架 9 套一致（暗：bg0<bg1<bg2<bg3；明：bg3<bg0<bg1≤bg2）；
    文字三阶按对比度严格递减（正文 > 次级 > 禁用）。"""
    for tid, c in theme.THEMES.items():
        lum = {k: _luminance(c[k]) for k in ("bg0", "bg1", "bg2", "bg3")}
        if _luminance(c["bg0"]) < 0.5:  # 暗骨架
            assert lum["bg0"] < lum["bg1"] < lum["bg2"] < lum["bg3"], f"{tid} 暗骨架阶梯: {lum}"
        else:                            # 明骨架
            assert lum["bg3"] < lum["bg0"] < lum["bg1"] <= lum["bg2"], f"{tid} 明骨架阶梯: {lum}"
        c_text = _contrast(c["text"], c["bg0"])
        c_sub = _contrast(c["text_sub"], c["bg0"])
        c_faint = _contrast(c["text_faint"], c["bg0"])
        assert c_text > c_sub > c_faint, f"{tid} 文字三阶对比度未递减"


# ----------------------------------------------------------------------
# ⑤ 主题集不降 / ⑥ 中性阶 + 旧键别名
# ----------------------------------------------------------------------

def test_theme_order_preserved():
    for tid in ("default", "light", "dark", "ocean", "forest",
                "sunset", "lavender", "graphite", "sepia", "system"):
        assert tid in theme.THEME_ORDER
    assert len(theme.THEMES) == 9
    assert theme.THEME_ORDER[0] == "system"


def test_neutral_roles_and_alias_mapping():
    for tid, c in theme.THEMES.items():
        for role in _ROLES:
            assert c.get(role), f"{tid} 缺中性阶角色 {role}"
        for alias, src in theme.NEUTRAL_ALIAS.items():
            assert c[alias] == c[src], f"{tid}: 别名 {alias} != {src}"


def test_legacy_color_keys_still_available():
    """colors() 旧键继续可用（防连锁改动）。"""
    theme.apply_theme("dark")
    try:
        c = theme.colors()
        for key in ("window", "panel", "input", "btn", "btn_hover", "sub", "text",
                    "border", "accent", "accent_text", "sel_bg", "id"):
            assert key in c
        assert c["window"] == c["bg0"] and c["panel"] == c["bg1"]
        assert c["input"] == c["bg2"] and c["btn"] == c["bg2"]
        assert c["btn_hover"] == c["bg3"] and c["sub"] == c["text_sub"]
        assert theme.icon_state_color("default") == c["text"]
        assert theme.icon_state_color("disabled") == c["sub"]
    finally:
        theme.apply_theme("dark")


def test_all_theme_ids_apply_without_error(qapp):
    for tid in theme.THEME_ORDER:
        theme.apply_theme(tid)  # 不抛即可（含 system 跟随）
        assert theme.colors()["id"] in theme.THEMES
    theme.apply_theme("dark")


# ----------------------------------------------------------------------
# ⑦ 裁定 F′：App 基座只入生产入口
# ----------------------------------------------------------------------

def test_app_base_only_in_main_entry():
    main_src = _MAIN_PY.read_text(encoding="utf-8")
    theme_src = _THEME_PY.read_text(encoding="utf-8")
    assert 'setStyle("Fusion")' in main_src
    assert 'setStyle("Fusion")' not in theme_src
    assert "setFont(" not in theme_src
    # T-1037 归因：原断言锁定的是旧字面写法 ——
    #   `"app.setFont(QFont(family, TOKENS["` 与
    #   `'TOKENS["typography"]["family"].split(",")[0]'`（即「只取族链首项」）。
    # 本任务改为传整条跨平台回落链（`setFamilies(ui_font_families())`），故断言同步
    # 更新为语义断言；基座隔离的守卫强度不降（上方三条核心守卫逐字未动）。
    assert "app.setFont(" in main_src
    assert "setFamilies(" in main_src
    # 族链解析 helper 的调用点在唯一生产入口（链字面量唯一源在 theme.py）
    assert "ui_font_families()" in main_src
    # 反向断言：「只取首项」旧写法已被消除
    assert 'split(",")[0]' not in main_src
    assert "def ui_font_families(" in theme_src
    assert "def ui_mono_families(" in theme_src


def test_app_base_snippet_effective(qapp):
    """基座片段离屏实测（不真起 GUI 循环，也不改全局样式：用独立 QApplication 不可行，
    故此处只验证 API 可用性与取值口径，样式生效由验收命令单独实测）。"""
    from PyQt6.QtGui import QFont

    family = theme.TOKENS["typography"]["family"].split(",")[0].strip().strip("'\"")
    assert family == "PingFang SC"
    font = QFont(family, theme.TOKENS["typography"]["body"])
    assert font.pointSize() == theme.TOKENS["typography"]["body"] == 13
    assert hasattr(qapp, "setStyle") and hasattr(qapp, "setFont")


# ----------------------------------------------------------------------
# ⑧ 裁定 E′：图标层零改动
# ----------------------------------------------------------------------

def test_icon_layer_frozen():
    assert len(theme.ICONS) == 30
    assert theme._ICON_STATE_ROLE == {
        "default": "text", "hover": "accent",
        "active": "accent_text", "disabled": "sub",
    }
    assert theme.icon_path("__not_exist__") is None
    assert theme.get_icon("open") is not None


# ----------------------------------------------------------------------
# ⑨ 主题下拉分组
# ----------------------------------------------------------------------

@pytest.fixture
def settings_dialog(qapp, monkeypatch):
    import acouscope.ai.backends.local_registry as lr
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    monkeypatch.setattr(lr, "probe_ollama", lambda *a, **k: (False, []))
    dlg = SettingsDialog(ai_config={})
    yield dlg
    dlg.deleteLater()


def test_theme_combo_is_grouped(settings_dialog):
    model = settings_dialog.cmb_theme.model()
    rows = [model.item(r) for r in range(model.rowCount())]
    heads = [it for it in rows if not it.data(Qt.ItemDataRole.UserRole)]
    entries = [it for it in rows if it.data(Qt.ItemDataRole.UserRole)]
    assert len(heads) == 2, "应有「基础配色 / 更多配色」两个分组标题"
    assert all(it.flags() == Qt.ItemFlag.NoItemFlags for it in heads), "分组标题必须不可选"

    ids = [it.data(Qt.ItemDataRole.UserRole) for it in entries]
    assert ids[:3] == list(_PRIMARY), "主区 3 项（跟随系统/深色/浅色）必须在前"
    assert ids == list(_PRIMARY) + [t for t in theme.THEME_ORDER if t not in _PRIMARY]
    assert sorted(ids) == sorted(theme.THEME_ORDER), "条目一个不少（零删除）"

    # 更多配色分组标题出现在第 4 项之后（主区之后）
    assert rows[4] in heads


def test_theme_combo_selection_path_unchanged(settings_dialog):
    """选中行为 / 取值口径零变化：选中项 → apply_theme(该 id)；theme() 取 currentData。"""
    cmb = settings_dialog.cmb_theme
    model = cmb.model()
    target = next(r for r in range(model.rowCount())
                  if model.item(r).data(Qt.ItemDataRole.UserRole) == "light")
    try:
        cmb.setCurrentIndex(target)
        assert theme.colors()["id"] == "light"
        assert settings_dialog.theme() == "light"
        assert cmb.currentData() == "light"
    finally:
        theme.apply_theme("dark")


def test_theme_labels_neutralized():
    """曝光收敛：主题标签中性化（无轻佻命名），三语齐全。"""
    from acouscope.i18n import _STRINGS  # noqa: PLC0415

    for key in ("settings.theme.group.basic", "settings.theme.group.more"):
        assert key in _STRINGS
        assert set(_STRINGS[key]) == {"en_US", "zh_CN", "zh_TW"}
        assert all(_STRINGS[key].values())
    for tid in theme.THEME_ORDER:
        entry = _STRINGS[f"settings.theme.{tid}"]
        assert set(entry) == {"en_US", "zh_CN", "zh_TW"}
        for flowery in ("日落", "薰衣草", "书卷", "Sunset", "Lavender", "Sepia", "Ocean"):
            assert flowery.lower() not in entry["zh_CN"].lower()
            assert flowery.lower() not in entry["en_US"].lower()
