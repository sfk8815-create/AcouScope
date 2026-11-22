# SPDX-License-Identifier: GPL-3.0-only
"""T-1047 参数控件规范守卫（三段式 / 范围可见性 / 读数内嵌框 / 状态点 LED / chip 激活态）。

设计真源 `ARCH_ui_visual_language.md`：
- **§五-7 参数控件三段式**：名称（上）+ 控件（中）+ 单位（下）；同组内三列左边界一致；
- **§五-8 / §六-13 参数范围可见性**：端点数值标签或稀疏刻度（禁裸数字框，禁逐刻度标注）；
- **§四 字阶与排版**：数值一律等宽（`typography.mono`）；数值 `text` 亮于说明 `text_sub`；
- **§五-4 状态点**：小圆点 + 令牌色，禁拟物（发光/渐变/动画）；
- **§六-11 状态 chip**：激活态靠**底色存在**（`accent` 低 alpha 底 + `accent` 字），禁描边/纯色文字。

判据层级：结构（几何/对象）→ 取值（令牌取色/字体/色值）→ **像素级**（chip 两态底色像素占比差 > 0）。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QWidget

from acouscope.i18n import _STRINGS
from acouscope.ui import theme
from acouscope.ui.widgets.panels import InspectorPanel
from acouscope.ui.widgets.settings_dialog import (
    ChipButton,
    LedDot,
    ParamGroup,
    RangeHint,
    ReadoutBox,
    SettingsDialog,
)

# 改动面（令牌唯一源判据：本两文件内 hex / 字面 px = 0）
_SRC = Path(__file__).resolve().parents[1] / "src" / "acouscope"
_PARAM_SOURCES = (
    _SRC / "ui" / "widgets" / "settings_dialog.py",
    _SRC / "ui" / "widgets" / "panels" / "inspector_panel.py",
)

# 本单新增 i18n 键（五语齐：en/简/繁/韩/日）
_NEW_KEYS = (
    "param.unit.hz", "param.unit.px", "param.unit.dpi", "param.unit.channels",
    "param.unit.bit", "param.name.a4_preset", "param.readout.a4",
    "param.name.font_size", "param.opt.font_small", "param.opt.font_default",
    "param.opt.font_large", "param.opt.font_xlarge",
    "param.name.play_channels", "param.name.record_channels",
    "param.name.sample_rate", "param.name.sample_format",
    "param.audio.output_device", "param.audio.input_device",
    "param.audio.title", "param.audio.refresh",
    "param.opt.mono", "param.opt.stereo", "param.opt.recommended",
    "param.led.ready", "param.led.off",
)
_FIVE_LANGS = ("en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP")

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_LITERAL_PX_RE = re.compile(r"(?<![\w.])\d+px")

_EVIDENCE_DIR = Path("/tmp/t1047_evidence")


# ---------------------------------------------------------------------------
# 夹具 / 工具
# ---------------------------------------------------------------------------

@pytest.fixture
def dlg(qapp):
    """设置对话框（离屏显示一次以完成布局；teardown 关闭）。"""
    d = SettingsDialog(ai_config={})
    d.resize(1000, 700)
    d.show()
    qapp.processEvents()
    yield d
    d.hide()
    d.deleteLater()
    qapp.processEvents()


def _contrast(fg: str, bg: str) -> float:
    """WCAG 对比度（明暗两骨架通用口径：数值应比说明更「亮」= 对比更高）。"""
    a, b = theme._relative_luminance(fg), theme._relative_luminance(bg)  # noqa: SLF001
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _hist(widget: QWidget, background: str):
    """离屏渲染单控件 → (像素色直方图, 像素总数)。"""
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(background))
    widget.render(img)
    hist: Counter = Counter()
    for y in range(img.height()):
        for x in range(img.width()):
            hist[img.pixelColor(x, y).name().lower()] += 1
    return hist, img.width() * img.height()


def _combo_range(combo: QComboBox) -> tuple[float, float]:
    """下拉项的可用范围端点（itemData 极值）。"""
    values = [float(combo.itemData(i)) for i in range(combo.count())]
    return min(values), max(values)


def _sample_groups(dlg: SettingsDialog) -> list[ParamGroup]:
    """本单改造的全部参数组。"""
    return [
        dlg.param_group_general,
        dlg.param_group_audio,
        dlg.param_group_interface,
        dlg.param_group_export,
    ]


# ---------------------------------------------------------------------------
# 1. 三段式（名称上 / 控件中 / 单位下 + 列对齐）
# ---------------------------------------------------------------------------

def test_three_tier_columns_aligned(dlg):
    """抽查 ≥3 个参数控件：同组内「名称列 / 控件列 / 单位列」左边界各自一致（几何实测）。"""
    groups = [g for g in dlg.findChildren(ParamGroup) if len(g.fields) >= 3]
    assert groups, "未找到 ≥3 个参数的参数组（三段式列对齐无从抽查）"
    group = groups[0]
    group.resize(900, 200)
    group.layout().activate()          # 该页非当前页：显式激活本组布局
    assert len(group.fields) >= 3
    blocks: dict[int, list] = {}
    for field in group.fields:
        name, control, unit = field["name"], field["control"], field["unit"]
        assert control.width() > 0, "控件未被布局（几何为 0，判据无效）"
        assert name.x() == control.x() == unit.x(), (
            f"三段左边界不一致（name/control/unit x="
            f"{name.x()}/{control.x()}/{unit.x()}）")
        if field["range"] is not None:
            assert field["range"].x() == control.x(), "范围线索未与所在列对齐"
        assert name.y() < control.y() < unit.y(), "三段顺序不是 名称（上）/控件（中）/单位（下）"
        blocks.setdefault(name.y(), []).append(field)
    # 每个行块：三行各自水平对齐（同 y）；列宽跨行块共享 → 各列左边界一致
    col_xs = None
    for fields in blocks.values():
        assert len({(f["name"].y(), f["control"].y(), f["unit"].y())
                    for f in fields}) == 1, "同块三行未水平对齐"
        xs = [f["control"].x() for f in fields]
        assert xs == sorted(xs) and len(set(xs)) == len(xs), f"列边界异常：{xs}"
        col_xs = xs if col_xs is None else col_xs
        assert xs == col_xs, f"行块之间列左边界不一致：{xs} vs {col_xs}"
    assert len(blocks) >= 1


def test_three_tier_name_unit_copy_i18n(dlg):
    """名称/单位文案走 i18n（非字面量）：切换语言后取值随之变化。"""
    from acouscope import i18n

    prev = i18n.get_language()
    try:
        i18n.set_language("zh_CN")
        zh = SettingsDialog(ai_config={})
        zh_name = zh.param_group_audio.fields[0]["name"].text()
        zh_unit = zh.param_group_audio.fields[0]["unit"].text()
        i18n.set_language("en_US")
        en = SettingsDialog(ai_config={})
        en_name = en.param_group_audio.fields[0]["name"].text()
        en_unit = en.param_group_audio.fields[0]["unit"].text()
        assert zh_name and en_name and zh_name != en_name
        assert zh_unit and en_unit
        zh.deleteLater()
        en.deleteLater()
    finally:
        i18n.set_language(prev)


# ---------------------------------------------------------------------------
# 2. 参数范围可见性（端点 / 稀疏刻度）
# ---------------------------------------------------------------------------

def test_range_hint_endpoints_match_control_range(dlg):
    """每个抽查参数控件必有范围线索，且端点 = 控件可用范围端点（取值断言）。"""
    groups = _sample_groups(dlg)
    sampled = 0
    for group in groups:
        for field in group.fields:
            hint = field["range"]
            assert isinstance(hint, RangeHint), "参数控件缺范围线索（禁裸数字框）"
            lo, hi = hint.endpoints()
            labels = hint.labels()
            assert labels[0] and labels[-1], "范围端点未标注数值"
            control = field["control"]
            if isinstance(control, QComboBox):
                assert (lo, hi) == _combo_range(control), (
                    f"范围端点与控件可用范围不一致：{lo}-{hi} vs {_combo_range(control)}")
            sampled += 1
    assert sampled >= 3, f"抽查参数控件数不足：{sampled}"
    # A4 参考频率（数值框）：端点 = spin 的 clamp 区间
    spin = dlg.spin_reference_hz
    a4_hint = dlg.param_group_general.fields[0]["range"]
    assert a4_hint.endpoints() == (float(spin.minimum()), float(spin.maximum()))


def test_range_hint_labels_sparse(dlg):
    """刻度稀疏化：只标端点 + 少数关键点（存在未标注刻度，非逐刻度标注）。"""
    all_labels, all_values = [], []
    for group in _sample_groups(dlg):
        for field in group.fields:
            hint = field["range"]
            assert len(hint.values()) >= 2
            all_labels.extend(hint.labels())
            all_values.extend(hint.values())
    assert len(all_values) > len([lab for lab in all_labels if lab]), (
        "刻度未稀疏化（每个刻度都写了数值）")


# ---------------------------------------------------------------------------
# 3. 读数内嵌框（等宽 + 数值层级）
# ---------------------------------------------------------------------------

def test_readout_box_mono_and_value_hierarchy(dlg):
    """读数等宽（typography.mono）；数值色 = text、说明色 = text_sub，且数值对比更高。"""
    box = dlg.readout_reference
    assert isinstance(box, ReadoutBox)
    assert box.value().strip(), "读数框为空"
    # 等宽：过滤后的字链进 QSS（单一来源 theme.ui_mono_family_qss）
    assert theme.ui_mono_family_qss() in box.styleSheet()
    families = list(box.lbl_value.font().families()) or [box.lbl_value.font().family()]
    assert theme.ui_mono_families()[0] in families, f"读数未等宽：{families}"
    c = theme.colors()
    assert box.value_color == c["text"]
    assert box.name_color == c["sub"]
    bg = c["bg1"]
    assert _contrast(box.value_color, bg) > _contrast(box.name_color, bg), (
        "数值未比说明更亮（对比度不足）")


def test_inspector_readout_box_and_values_mono(qapp):
    """检视器同套规范：读数内嵌框（底色 + 描边走令牌）+ 键值网格数值等宽。"""
    panel = InspectorPanel()
    qss = InspectorPanel._build_qss(theme.colors())  # noqa: SLF001
    c = theme.colors()
    ty = theme.TOKENS["typography"]
    assert theme.ui_mono_family_qss() in qss, "检视器读数未走等宽字链"
    assert f"background: {c['bg2']}" in qss, "检视器读数未内嵌框（缺底色）"
    rule = re.search(r"QLineEdit#metaLineEdit \{([^}]*)\}", qss)
    assert rule and theme.ui_mono_family_qss() in rule.group(1), "键值网格的「值」未等宽"
    panel.deleteLater()


# ---------------------------------------------------------------------------
# 4. 状态点（LED 式）
# ---------------------------------------------------------------------------

def test_led_dot_size_and_token_colors(dlg):
    """状态点尺寸/色值均取自令牌；禁拟物（无渐变/动画）。"""
    led = dlg.led_ai_builtin
    assert isinstance(led, LedDot)
    dot = theme.TOKENS["param"]["led_dot"]
    assert (led.width(), led.height()) == (dot, dot)
    assert led.role() in ("success", "text_faint")
    led.set_state("ready")
    assert led.color() == theme.TOKENS["semantic"]["success"]
    led.set_state("off")
    assert led.color() == theme.colors()["text_faint"]


def test_inspector_led_follows_active_state(qapp):
    """检视器状态点与元数据激活态同源（就绪 / 不可用）。"""
    panel = InspectorPanel()
    assert isinstance(panel.led_meta, LedDot)
    assert panel.led_meta.role() == "text_faint"
    panel._set_meta_active(True)  # noqa: SLF001
    assert panel.led_meta.state() == "ready"
    assert panel.led_meta.color() == theme.TOKENS["semantic"]["success"]
    panel._set_meta_active(False)  # noqa: SLF001
    assert panel.led_meta.role() == "text_faint"
    panel.deleteLater()


# ---------------------------------------------------------------------------
# 5. 状态 chip 激活态（像素级：底色存在）
# ---------------------------------------------------------------------------

def test_chip_active_state_background_pixels(qapp):
    """激活/未激活两态渲染后**底色像素占比差 > 0**，且激活态底色大面积存在（非仅描边）。"""
    c = theme.colors()
    host = QWidget()
    host.setStyleSheet(f"background: {c['bg1']};")
    row = QHBoxLayout(host)
    row.setContentsMargins(theme.TOKENS["spacing"]["xs"],
                           theme.TOKENS["spacing"]["xs"],
                           theme.TOKENS["spacing"]["xs"],
                           theme.TOKENS["spacing"]["xs"])
    row.setSpacing(theme.TOKENS["spacing"]["xs"])
    idle, active = ChipButton("440", host), ChipButton("442", host)
    row.addWidget(idle)
    row.addWidget(active)
    row.addStretch(1)
    active.setChecked(True)
    host.resize(240, 44)
    host.show()
    qapp.processEvents()

    base = idle.idle_bg().lower()
    assert base and active.active_bg() and base != active.active_bg().lower()

    hist_idle, area_idle = _hist(idle, c["bg1"])
    hist_active, area_active = _hist(active, c["bg1"])
    ratio_idle = hist_idle.get(base, 0) / area_idle
    ratio_active = hist_active.get(base, 0) / area_active

    assert ratio_idle > 0.4, f"未激活态底色占比异常：{ratio_idle:.3f}"
    assert ratio_idle - ratio_active > 0.2, (
        f"两态底色像素占比差不足（差={ratio_idle - ratio_active:.3f}）")
    # 禁「仅描边」：激活态被另一种底色覆盖的面积必须过半（描边级差异远小于此）
    top_hex, top_n = hist_active.most_common(1)[0]
    assert top_hex != base, "激活态底色与未激活同色（激活态不可见）"
    assert top_n / area_active > 0.4, (
        f"激活态底色面积过小（{top_n / area_active:.3f}），疑为描边式表达")
    host.hide()
    host.deleteLater()


def test_chip_qss_active_uses_accent_alpha_no_border(dlg):
    """chip 激活态 = accent 低 alpha 底；禁描边表达（QSS 取值断言）。"""
    chip = dlg.chips_a4.chips[0]
    css = chip.styleSheet()
    accent = QColor(theme.colors()["accent"])
    alpha = int(theme.TOKENS["param"]["chip_alpha"])
    assert f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {alpha})" in css
    assert "#paramChip:checked" in css
    assert "border: none" in css, "chip 仍在用描边表达状态"
    # 激活态唯一（互斥）
    group = dlg.chips_a4
    group.chips[1].click()
    assert group.chips[1].isChecked() and not group.chips[0].isChecked()
    assert sum(chip.isChecked() for chip in group.chips) == 1
    assert group.current() == group.payload_of(group.chips[1])


# ---------------------------------------------------------------------------
# 6. 令牌唯一源 + i18n 五语
# ---------------------------------------------------------------------------

def test_token_source_zero_hex_zero_literal_px():
    """改动面内字面 hex = 0、字面 px = 0（色/尺寸一律走令牌）。"""
    for path in _PARAM_SOURCES:
        text = path.read_text(encoding="utf-8")
        assert not _HEX_RE.search(text), f"{path.name} 含字面 hex 色值"
        assert not _LITERAL_PX_RE.search(text), f"{path.name} 含字面 px 尺寸"


def test_new_i18n_keys_five_languages():
    """新增文案五语齐（en/简/繁/韩/日），禁硬编码中文。"""
    for key in _NEW_KEYS:
        entry = _STRINGS.get(key)
        assert entry is not None, f"i18n 缺 key：{key}"
        for lang in _FIVE_LANGS:
            assert entry.get(lang), f"{key} 缺 {lang}"


# ---------------------------------------------------------------------------
# 7. 观感证据（4 张离屏截图落 /tmp/t1047_evidence/）
# ---------------------------------------------------------------------------

def test_evidence_screenshots_four(qapp):
    """settings 页 + 检视器，明/暗各一张（共 4 张）落 /tmp/t1047_evidence/。"""
    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    prev_id = theme.colors().get("id", "dark")
    written: list[Path] = []
    try:
        for skeleton in ("dark", "light"):
            theme.apply_theme(skeleton)
            qapp.processEvents()

            d = SettingsDialog(ai_config={})
            d.resize(1000, 700)
            d.show()
            qapp.processEvents()
            shot = _EVIDENCE_DIR / f"settings_{skeleton}.png"
            img = QImage(d.size(), QImage.Format.Format_ARGB32)
            img.fill(QColor(theme.colors()["bg1"]))
            d.render(img)
            assert img.save(str(shot))
            d.hide()
            d.deleteLater()
            written.append(shot)

            panel = InspectorPanel()
            panel.resize(340, 680)
            panel.show()
            qapp.processEvents()
            shot_p = _EVIDENCE_DIR / f"inspector_{skeleton}.png"
            img_p = QImage(panel.size(), QImage.Format.Format_ARGB32)
            img_p.fill(QColor(theme.colors()["bg1"]))
            panel.render(img_p)
            assert img_p.save(str(shot_p))
            panel.hide()
            panel.deleteLater()
            written.append(shot_p)
            qapp.processEvents()
    finally:
        theme.apply_theme(prev_id if prev_id in theme.THEME_ORDER else "dark")
    assert len(written) == 4
    for path in written:
        assert path.exists() and path.stat().st_size > 0, f"证据缺失：{path}"
