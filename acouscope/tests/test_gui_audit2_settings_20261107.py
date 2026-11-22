# SPDX-License-Identifier: GPL-3.0-only
"""真机 GUI 审计第二轮守卫（M4 窄栏设置页 / L4 字族链安装过滤）。

M4（tmp/gui_audit_20261107/N3_settings.png）：窄左栏下通用页最小宽顶宽视口 →
横向滚动条 + 滑杆右端「480」/ 刻度行被裁。守卫：320/340 与真机窄栏读数
（194/186，1000px 主窗离屏复现值）下无横向滚动需求、max 标签带全文 tooltip、
刻度行实宽不越视口。
L4（launch.log）：ui_font_families()/ui_mono_families() 按 QFontDatabase 已安装
族过滤（保序 + 泛型剔除语义不变），缺失族不得进 setFamilies。
平台条件覆盖：test_font_stack.py「链须含三平台族名」为环境无关旧判据；安装过滤
后与本平台事实（macOS 未装 Segoe UI/Consolas 等）冲突。旧文件不在本轮白名单、
不得改亦不得删断言放水，故在此以平台条件覆盖：已安装平台目标仍须覆盖，未安装
平台目标不得入链（缺失族入链正是 launch.log 告警根因）。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QFont, QFontDatabase  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QComboBox,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from acouscope.i18n import get_language, set_language, tr  # noqa: E402
from acouscope.ui import theme  # noqa: E402
from acouscope.ui.widgets.settings_dialog import SettingsDialog  # noqa: E402

MAC_FAMILIES = {"PingFang SC", "Helvetica Neue", "SF Mono", "Menlo"}
WIN_FAMILIES = {"Segoe UI", "Consolas", "Microsoft YaHei UI", "Microsoft YaHei"}
LINUX_FAMILIES = {
    "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans",
    "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono CJK SC",
}
GENERIC_KEYWORDS = {"sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui"}


@pytest.fixture(scope="module")
def base_app(qapp):
    """生产基座同口径（__main__：Fusion + 整链 + body 字号 + 暗主题 + 中文）。"""
    prev_style = qapp.style().name()
    prev_font = qapp.font()
    prev_theme = theme._theme_id
    prev_lang = get_language()
    qapp.setStyle("Fusion")
    font = QFont(prev_font)
    font.setFamilies(theme.ui_font_families())
    font.setPointSize(theme.TOKENS["typography"]["body"])
    qapp.setFont(font)
    theme.apply_theme("dark")
    set_language("zh_CN")
    yield qapp
    qapp.setStyle(prev_style)
    qapp.setFont(prev_font)
    theme.apply_theme(prev_theme)
    set_language(prev_lang)


def _make_selector():
    # 镜像 main_window._create_backend_selector 的尺寸契约（min 180 / combo min 140）
    sel = QWidget()
    sel.setMinimumWidth(180)
    lay = QHBoxLayout(sel)
    lay.setContentsMargins(6, 0, 6, 0)
    lay.setSpacing(4)
    lay.addWidget(QLabel(tr("pitch.backend_label")))
    combo = QComboBox()
    combo.setMinimumWidth(140)
    for key in ("pitch.backend_pyin", "pitch.backend_swiftf0", "pitch.backend_rmvpe"):
        combo.addItem(tr(key), key)
    lay.addWidget(combo)
    return sel


def _general_area(dlg):
    return dlg.stack.widget(0)


def test_m4_guard_widths_no_hscroll_and_max_label_tooltip(base_app):
    dlg = SettingsDialog(language="zh_CN", ai_config={},
                         backend_selector=_make_selector())
    dlg.show()
    for width in (320, 340):
        # 离屏顶层首帧 resize 会被 show 期布局事件弹回，补发一次同尺寸
        dlg.resize(width, 800)
        base_app.processEvents()
        dlg.resize(width, 800)
        base_app.processEvents()
        area = _general_area(dlg)
        page = area.widget()
        assert (area.horizontalScrollBar().maximum() == 0
                or page.minimumSizeHint().width() <= area.viewport().width()), (
            f"M4 {width}px 视口 {area.viewport().width()} 仍需横向滚动"
            f"（页最小宽 {page.minimumSizeHint().width()}）")
        lbl = dlg.lbl_reference_max
        assert "480" in lbl.toolTip(), "M4 max 标签缺全文 tooltip（裁切/缩略后不可读）"
        assert lbl.text() == "480" or lbl.text().endswith("…"), (
            f"M4 max 标签既非完整亦非 elide：{lbl.text()!r}")
        chips = dlg.chips_a4.chips
        assert all(c.width() > 0 for c in chips), "M4 chip 布局失效（宽 0）"
        assert len({c.y() for c in chips}) == 1, "M4 够宽时 chip 应单行"
    dlg.close()


def test_m4_real_narrow_column_no_hscroll(base_app):
    dlg = SettingsDialog(language="zh_CN", ai_config={},
                         backend_selector=_make_selector())
    dlg.show()
    for width in (194, 186):
        # 离屏顶层首帧 resize 会被 show 期布局事件弹回，补发一次同尺寸
        dlg.resize(width, 800)
        base_app.processEvents()
        dlg.resize(width, 800)
        base_app.processEvents()
        area = _general_area(dlg)
        page = area.widget()
        assert area.horizontalScrollBar().maximum() == 0, (
            f"M4 真机窄栏 {width}px 出横向滚动条：hsb="
            f"{area.horizontalScrollBar().maximum()} 页最小宽 "
            f"{page.minimumSizeHint().width()} 视口 {area.viewport().width()}")
        hint = dlg.param_group_general.fields[0]["range"]
        assert hint.width() <= area.viewport().width(), (
            f"M4 刻度行实宽 {hint.width()} 越视口 {area.viewport().width()}（右端被裁）")
        lbl = dlg.lbl_reference_max
        right = lbl.mapTo(area.viewport(), lbl.rect().topRight()).x()
        assert right <= area.viewport().width(), (
            f"M4 max 标签右缘 {right} 越视口 {area.viewport().width()}（被裁）")
        assert lbl.width() >= lbl.fontMetrics().horizontalAdvance(lbl.text())
        chips = dlg.chips_a4.chips
        assert all(c.width() > 0 for c in chips), "M4 chip 布局失效（宽 0）"
        assert len({c.y() for c in chips}) >= 2, (
            "M4 窄栏 chip 应换行（整行单排是顶宽根因）")
    dlg.close()


def test_l4_chain_filters_uninstalled_preserves_order(base_app, monkeypatch):
    installed = ("PingFang SC", "Helvetica Neue", "DejaVu Sans",
                 "SF Mono", "Menlo", "DejaVu Sans Mono")
    monkeypatch.setattr(theme, "_installed_family_names", lambda: installed,
                        raising=False)
    assert theme.ui_font_families() == [
        "PingFang SC", "Helvetica Neue", "DejaVu Sans"]
    assert theme.ui_mono_families() == ["SF Mono", "Menlo", "DejaVu Sans Mono"]
    monkeypatch.setattr(theme, "_installed_family_names",
                        lambda: installed + ("Segoe UI", "Consolas"), raising=False)
    assert theme.ui_font_families() == [
        "PingFang SC", "Helvetica Neue", "Segoe UI", "DejaVu Sans"]
    assert theme.ui_mono_families() == [
        "SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono"]


def test_l4_real_call_returns_installed_only(base_app):
    installed = {name.casefold() for name in QFontDatabase.families()}
    for chain in (theme.ui_font_families(), theme.ui_mono_families()):
        assert chain, "过滤后链不得为空兜底失败"
        assert all(name.casefold() in installed for name in chain), (
            f"L4 链含未安装族（setFamilies 告警根因）：{chain}")
        assert not any(name.lower() in GENERIC_KEYWORDS for name in chain)
    raw = theme._parse_family_chain(theme.TOKENS["typography"]["family"])
    assert theme.ui_font_families() == [
        name for name in raw if name.casefold() in installed], "已安装族顺序被改动"
    raw_mono = theme._parse_family_chain(theme.TOKENS["typography"]["mono"])
    assert theme.ui_mono_families() == [
        name for name in raw_mono if name.casefold() in installed]


def test_l4_platform_coverage_override(base_app):
    installed = {name.casefold() for name in QFontDatabase.families()}
    chains = (
        ("family", theme.ui_font_families(),
         (("macOS", MAC_FAMILIES), ("Windows", WIN_FAMILIES), ("Linux", LINUX_FAMILIES))),
        ("mono", theme.ui_mono_families(),
         (("macOS", MAC_FAMILIES), ("Windows", WIN_FAMILIES), ("Linux", LINUX_FAMILIES))),
    )
    for _name, chain, groups in chains:
        for label, group in groups:
            if {g.casefold() for g in group} & installed:
                assert group & set(chain), f"{label} 已安装目标族失去覆盖：{chain}"
            else:
                # 平台条件覆盖旧环境无关判据：未安装族入链 = launch.log 告警根因
                assert not (group & set(chain)), (
                    f"{label} 目标族本机未安装却仍在链中：{group & set(chain)}")