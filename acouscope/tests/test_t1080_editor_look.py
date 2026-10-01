# SPDX-License-Identifier: GPL-3.0-only
"""T-1080 M-2：图表设计器编辑器观感微调（D 方案·只调节拍不改结构）守卫测。

断言面（判据①）：
- hint 走 `theme.colors()["text_faint"]`（弱化），层级 = 分区标题 > 字段标签 > hint；
- 分区/行/列间距一律取自 `theme.TOKENS["spacing"]` 现成刻度 —— **无新增硬编码 px**；
- 标签与控件左对齐统一；
- **结构守恒**：仍 6 列分区、每列首件仍 `SectionHeader`、字段仍三段式 `_ParamField`、
  控件类型未变。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from acouscope.ui import theme
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets import chart_designer as cd
from acouscope.ui.widgets.chart_designer import ChartDesignerPanel, _ParamField
from acouscope.ui.widgets.panels.section_header import SectionHeader, _section_qss

_SPACING = set(TOKENS["spacing"].values())
_TY = TOKENS["typography"]
_SRC = Path(cd.__file__)
_FONT_SIZE = re.compile(r"font-size:\s*(\d+)px")
_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_PARAM_FIELDS = 15  # 4 内容 + 3 版式 + 1 配色 + 2 字体 + 2 导出 + 3 参考线


@pytest.fixture
def panel(qapp):
    return ChartDesignerPanel(settings=None)


def _columns(panel):
    """编辑器 6 列的 QVBoxLayout（root 第 2 项 = `_build_params` 的 box）。"""
    box = panel.layout().itemAt(1).widget()
    row = box.layout()
    return box, [row.itemAt(i).layout() for i in range(row.count())]


# ---------------------------------------------------------------------------
# 结构守恒
# ---------------------------------------------------------------------------


def test_six_column_structure_preserved(panel):
    _box, cols = _columns(panel)
    assert len(cols) == 6, "②-D：编辑器仍为 6 列分区，不得重排"
    for col in cols:
        assert isinstance(col, QVBoxLayout)
        assert col.count() > 1 and isinstance(col.itemAt(0).widget(), SectionHeader)
    assert len(panel.findChildren(_ParamField)) == _PARAM_FIELDS


def test_widget_types_unchanged(panel):
    """不改控件类型（D 方案红线）。"""
    for cls in (QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton):
        assert panel.findChildren(cls), f"{cls.__name__} 应仍在编辑器内"


# ---------------------------------------------------------------------------
# 间距：一律取 TOKENS["spacing"]
# ---------------------------------------------------------------------------


def test_all_editor_gaps_come_from_spacing_tokens(panel):
    box, cols = _columns(panel)
    gaps = {box.layout().spacing(), panel.layout().spacing()}
    for col in cols:
        gaps.add(col.spacing())
    for field in panel.findChildren(_ParamField):
        gaps.add(field.layout().spacing())
    assert gaps <= _SPACING, f"列间/行间/区内间距非 spacing 刻度：{gaps}"
    assert box.layout().spacing() == TOKENS["spacing"]["md"]


def test_column_spacing_is_uniform(panel):
    """6 列列内间距一致（旧码走各布局默认值 → 节拍不齐的根因之一）。"""
    _box, cols = _columns(panel)
    assert len({col.spacing() for col in cols}) == 1
    assert cols[0].spacing() == TOKENS["spacing"]["sm"]


def test_no_new_hardcoded_pixel_literals_in_layout():
    """静态守卫：布局调用不得出现裸数字间距（外边距归零的 0 除外）。"""
    offenders = re.findall(
        r"set(?:Spacing|ContentsMargins)\((?:\s*-?[1-9]\d*)", _SRC.read_text(encoding="utf-8")
    )
    assert not offenders, f"布局中新增硬编码 px：{offenders}"


# ---------------------------------------------------------------------------
# 字号层级 + hint 弱化
# ---------------------------------------------------------------------------


def test_hint_uses_text_faint_across_themes():
    for tid, colors in theme.THEMES.items():
        assert colors["text_faint"] != colors["text_sub"], tid  # 前提：两角色有别
        unit_rule = cd._param_qss(colors).split("chartDesignerParamUnit")[1]
        assert colors["text_faint"] in unit_rule, f"{tid}: hint 未取 text_faint"
        assert colors["text_sub"] not in unit_rule, f"{tid}: hint 仍留 text_sub"


def test_font_hierarchy_title_gt_label_gt_hint():
    title = int(_FONT_SIZE.search(_section_qss(theme.colors())).group(1))
    sizes = _FONT_SIZE.findall(cd._param_qss(theme.colors()))
    name, hint = int(sizes[0]), int(sizes[1])
    assert (title, name, hint) == (_TY["h3"], _TY["body_sm"], _TY["caption_sm"])
    assert title > name > hint, "层级：分区标题 > 字段标签 > hint"


def test_param_labels_left_aligned(panel):
    fields = panel.findChildren(_ParamField)
    assert fields
    for field in fields:
        assert field.name_label.alignment() == _LEFT
        assert field.unit_label.alignment() == _LEFT


def test_editor_qss_builders_take_only_theme_colors():
    """取色只经 `theme.colors()` 传入的字典，构造器本体无本地色值。"""
    for builder in (cd._param_qss, cd._preview_qss):
        body = inspect.getsource(builder)
        assert not re.search(r"#[0-9a-fA-F]{3,8}", body), builder.__name__
        assert "c[" in body


# ---------------------------------------------------------------------------
# 离屏成图（供幕僚 render 目测）
# ---------------------------------------------------------------------------


def test_editor_offscreen_render_smoke(panel, tmp_path):
    panel.resize(1400, 900)
    box, _cols = _columns(panel)
    box.resize(1400, 460)
    pix = box.grab()
    assert pix.width() > 0 and pix.height() > 0
    assert pix.save(str(tmp_path / "t1080_editor_after.png"))
