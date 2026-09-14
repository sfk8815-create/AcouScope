# SPDX-License-Identifier: GPL-3.0-only
"""T-1033 信息架构（面板头 / 分组 / 空态 / 工具栏图标优先）回归测试。

覆盖（全离屏，禁 MainWindow.show()）：
① 三构件（PanelHeader / EmptyState / SectionHeader）为**共用类**且被落地点复用；
② 面板头高 == TOKENS.control.h_lg、底边取 elevation.border、标题走 tokens；
③ 空态含「说明 + 主操作按钮 + 拖放提示」三要素（findChildren 结构断言）；
④ 分析区 hint 页已换为 EmptyState，主操作按钮走既有「打开文件」入口；
⑤ settings_dialog.py 内 hex = 0 / 字面 px = 0 / 裸样式表调用 = 0；
⑥ main_window.py 的 px 集合 ⊆ 既有白名单（不新增）；
⑦ 工具栏：纯图标按钮必有非空 tooltip；命名入口保留文字（逐按钮判据）；
⑧ 纪律：禁词 0 / 无新增 QDialog 类 / 新构件源码零 hex·零 px。
"""

import ast
import pathlib
import re

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPushButton,
    QToolBar,
    QToolButton,
)

from acouscope.app.controller import AppController  # noqa: E402
from acouscope.i18n import tr  # noqa: E402
from acouscope.ui import theme  # noqa: E402
from acouscope.ui.main_window import MainWindow  # noqa: E402
from acouscope.ui.widgets.panels import (  # noqa: E402
    EmptyState,
    PanelContainer,
    PanelHeader,
    SectionHeader,
    attach_panel_header,
)
from acouscope.ui.widgets.panels.inspector_panel import InspectorPanel  # noqa: E402

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_MW_PY = _SRC / "ui" / "main_window.py"
_SETTINGS_PY = _SRC / "ui" / "widgets" / "settings_dialog.py"
_INSPECTOR_PY = _SRC / "ui" / "widgets" / "panels" / "inspector_panel.py"
_PANEL_HEADER_PY = _SRC / "ui" / "widgets" / "panels" / "panel_header.py"
_EMPTY_STATE_PY = _SRC / "ui" / "widgets" / "panels" / "empty_state.py"
_SECTION_HEADER_PY = _SRC / "ui" / "widgets" / "panels" / "section_header.py"
_NEW_COMPONENTS = (_PANEL_HEADER_PY, _EMPTY_STATE_PY, _SECTION_HEADER_PY)

# 既有硬编码像素白名单（同 test_menu_restructure；新增任一 px 即失败）
_PX_WHITELIST = frozenset({"1px", "14px", "20px", "28px", "44px", "700px"})
_BANNED = "Mel" + "odyne"

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_PX_RE = re.compile(r"\b\d+(?:\.\d+)?px\b")

# 逐按钮判据（T-1033 P5）：纯图标组（高频 + 图标语义无歧义）
_ICON_ONLY = ("action_open", "action_undo", "action_redo", "action_export")
# 保留文字组（命名入口 / 低频 / 语义可能歧义）
_KEEP_TEXT = (
    "action_new_project",
    "action_open_project",
    "action_save_project",
)  # T-1054 批0：action_batch 已从工具栏撤为开关组，移出保留文字列表


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（离屏构建，不 show()；teardown close）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440 * t), sr)

    w = MainWindow(controller)
    yield w
    w.close()


@pytest.fixture
def inspector():
    panel = InspectorPanel()
    yield panel
    panel.deleteLater()


# ---------------------------------------------------------------------------
# ① 三构件为共用类 + 落地点复用
# ---------------------------------------------------------------------------


def test_components_are_public_shared_classes():
    """三构件为 panels 包公开共用类（禁各处再写一套）。"""
    assert PanelHeader.__module__ == "acouscope.ui.widgets.panels.panel_header"
    assert EmptyState.__module__ == "acouscope.ui.widgets.panels.empty_state"
    assert SectionHeader.__module__ == "acouscope.ui.widgets.panels.section_header"


def test_panel_header_reused_at_three_landings(window):
    """面板头三处落地（左栏 / 右栏 / 分析区）且均为同一共用构件实例。"""
    for holder, panel, title_key in (
        ("left_panel_header", window.left_panel, "sidebar.tab.files"),
        ("right_panel_header", window.right_panel, "sidebar.tab.inspector"),
        ("analysis_panel_header", window.analysis_panel, "toolbar.analysis"),
    ):
        header = getattr(window, holder)
        assert isinstance(header, PanelHeader)
        assert panel.findChildren(PanelHeader) == [header]
        assert header.title() == tr(title_key)
        # 结构：挂在面板内容上方（面板布局首项）
        assert panel.layout().itemAt(0).widget() is header


def test_attach_panel_header_inserts_first():
    """attach_panel_header 共用挂载函数：面板布局首项，内容不被替换。"""
    panel = PanelContainer()
    inner = QLabel("content")
    panel.set_content(inner)
    header = attach_panel_header(panel, "T")
    assert isinstance(header, PanelHeader)
    assert panel.layout().itemAt(0).widget() is header
    assert panel.panelContent.findChildren(QLabel) == [inner]


# ---------------------------------------------------------------------------
# ② 面板头几何与取色（全令牌）
# ---------------------------------------------------------------------------


def test_panel_header_height_and_border_from_tokens(qapp):
    """面板头高 == TOKENS.control.h_lg；底边取 elevation.border。"""
    from acouscope.ui.widgets.panels.panel_header import _header_qss

    header = PanelHeader("T")
    assert header.height() == theme.TOKENS["control"]["h_lg"]
    assert header.height() == header.minimumHeight() == header.maximumHeight()

    c = theme.colors()
    qss = _header_qss(c)
    elev = theme.TOKENS["elevation"]["border"]
    assert f"border-bottom: {elev}px solid {c['border']}" in qss
    assert f"color: {c['text']}" in qss
    assert f"font-size: {theme.TOKENS['typography']['body_lg']}px" in qss
    header.deleteLater()


def test_panel_header_action_slot_is_reusable(qapp):
    """右操作区插槽：add_action 可注入控件（共用能力）。"""
    header = PanelHeader("T")
    assert header.action_count() == 0
    btn = QPushButton("x")
    header.add_action(btn)
    assert header.action_count() == 1
    assert btn.parent() is not None
    header.deleteLater()


# ---------------------------------------------------------------------------
# ③④ 空态三要素 + 分析区 hint 页落地
# ---------------------------------------------------------------------------


def test_empty_state_has_three_parts(qapp):
    """空态三要素：说明 + 主操作按钮 + 拖放提示（结构断言）。"""
    st = EmptyState(message="m", action_text="a", drop_hint="d")
    assert [w.text() for w in st.findChildren(QLabel, "emptyStateMessage")] == ["m"]
    assert [w.text() for w in st.findChildren(QPushButton, "emptyStateAction")] == ["a"]
    assert [w.text() for w in st.findChildren(QLabel, "emptyStateDropHint")] == ["d"]
    # 主操作按钮 → actionTriggered 信号（零第二套路径）
    seen = []
    st.actionTriggered.connect(lambda: seen.append(1))
    st.btn_action.click()
    assert seen == [1]
    st.deleteLater()


def test_analysis_hint_page_uses_empty_state(window):
    """分析区 hint 页已换为 EmptyState（三要素 + i18n 文案）。"""
    st = window.analysis_empty_state
    assert isinstance(st, EmptyState)
    hint_page = window.view_container.widget(0)
    assert hint_page.findChildren(EmptyState) == [st]
    assert st.message() == tr("status.open_audio")
    assert st.btn_action.text() == tr("action.open")
    assert st.lbl_drop_hint.text() == tr("empty.drop_hint")


def test_analysis_empty_state_action_uses_existing_open_entry(window, monkeypatch):
    """空态主操作按钮接线到既有「打开文件」入口（不新增第二套打开路径）。

    口径：打桩 action_open.trigger（triggered 连接持原绑方法，改属性无效），
    避免落进真实 QFileDialog。
    """
    seen = []
    monkeypatch.setattr(window.action_open, "trigger", lambda: seen.append(1))
    window.analysis_empty_state.btn_action.click()
    assert seen == [1]


def test_inspector_empty_state_uses_component(inspector):
    """右栏检查器空态改用共用构件 EmptyState（三要素齐备）。"""
    assert inspector.findChildren(EmptyState) == [inspector.empty_meta]
    assert inspector.empty_meta.btn_action.text() == tr("action.open")
    assert inspector.empty_meta.lbl_drop_hint.text() == tr("empty.drop_hint")
    # 空态 / 编辑区互斥
    inspector.clear_metadata()
    assert inspector.empty_meta.isHidden() is False
    assert inspector.meta_box.isHidden() is True


def test_inspector_open_requested_signal(inspector):
    """检查器空态主操作按钮 → openRequested 信号（由主窗接线）。"""
    seen = []
    inspector.openRequested.connect(lambda: seen.append(1))
    inspector.empty_meta.btn_action.click()
    assert seen == [1]


# ---------------------------------------------------------------------------
# P3 分组标题构件落地
# ---------------------------------------------------------------------------


def test_section_header_landed_in_inspector(inspector):
    """检查器档案元数据区标题走共用构件 SectionHeader。"""
    headers = inspector.findChildren(SectionHeader)
    assert len(headers) == 1
    assert headers[0].title() == tr("inspector.metadata")


def test_section_header_landed_in_settings(qapp, monkeypatch):
    """设置面板（AI 页）分组标题走共用构件 SectionHeader。"""
    import acouscope.ai.backends.local_registry as lr
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    monkeypatch.setattr(lr, "probe_ollama", lambda *a, **k: (False, []))
    dlg = SettingsDialog(ai_config={})
    titles = [h.title() for h in dlg.findChildren(SectionHeader)]
    assert tr("settings.ai_source") in titles
    assert tr("settings.ai_models_title") in titles
    dlg.deleteLater()


def test_section_header_uses_h3_and_top_spacing(qapp):
    """分组规范：h3 字号 + spacing.sm 上间距（禁 QGroupBox 描边）。"""
    from acouscope.ui.widgets.panels.section_header import _section_qss

    st = SectionHeader("T")
    assert st.layout().contentsMargins().top() == theme.TOKENS["spacing"]["sm"]
    assert f"font-size: {theme.TOKENS['typography']['h3']}px" in _section_qss(
        theme.colors()
    )
    assert st.findChildren(QLabel, "sectionHeaderTitle")
    st.deleteLater()


# ---------------------------------------------------------------------------
# ⑤⑥ P6 / 令牌唯一源（源码级）
# ---------------------------------------------------------------------------


def test_settings_dialog_has_zero_hex_px_and_style_sheet_call():
    """P6：settings_dialog.py 内 hex = 0 / 字面 px = 0 / 裸样式表调用 = 0。"""
    src = _SETTINGS_PY.read_text(encoding="utf-8")
    assert _HEX_RE.findall(src) == []
    assert _PX_RE.findall(src) == []
    assert ".setStyleSheet(" not in src


def test_main_window_px_set_within_whitelist():
    """main_window.py 的 px 集合 ⊆ 既有白名单（不新增硬编码像素）。"""
    src = _MW_PY.read_text(encoding="utf-8")
    px = set(_PX_RE.findall(src))
    assert px <= _PX_WHITELIST, f"新增硬编码像素: {px - _PX_WHITELIST}"
    assert _HEX_RE.findall(src) == []


def test_new_components_have_no_literal_hex_or_px():
    """三构件源码零 hex / 零字面 px（令牌唯一源）。"""
    for path in _NEW_COMPONENTS:
        src = path.read_text(encoding="utf-8")
        assert _HEX_RE.findall(src) == [], path.name
        assert _PX_RE.findall(src) == [], path.name


def test_no_qdialog_class_added_in_touched_files():
    """禁新建 QDialog 子类（外观改动不得引回模态）。"""
    for path in (_MW_PY, _SETTINGS_PY, _INSPECTOR_PY) + _NEW_COMPONENTS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = getattr(base, "id", getattr(base, "attr", ""))
                    assert name != "QDialog", f"{path.name}: {node.name} 继承 QDialog"


def test_banned_word_absent():
    for path in (_MW_PY, _SETTINGS_PY, _INSPECTOR_PY) + _NEW_COMPONENTS:
        assert _BANNED.lower() not in path.read_text(encoding="utf-8").lower()


def test_new_i18n_key_in_three_languages():
    """新增用户可见文案须三语齐备。"""
    from acouscope.i18n import _STRINGS

    entry = _STRINGS.get("empty.drop_hint")
    assert entry is not None
    for lang in ("en_US", "zh_CN", "zh_TW"):
        assert entry.get(lang), f"empty.drop_hint 缺 {lang}"


# ---------------------------------------------------------------------------
# ⑦ P5 工具栏图标优先（逐按钮判据）
# ---------------------------------------------------------------------------


def _tool_button(toolbar, action):
    btn = toolbar.widgetForAction(action)
    return btn if isinstance(btn, QToolButton) else None


def _file_toolbar(window) -> QToolBar:
    """主工具栏（既有口径：btn_toggle_right_panel 所在工具栏）。"""
    tb = window.btn_toggle_right_panel.parent()
    assert isinstance(tb, QToolBar)
    return tb


def _analysis_toolbar(window) -> QToolBar:
    """分析工具栏（含音律标尺对应 QToolButton 的工具栏）。

    注：QAction.parent() 是主窗而非工具栏 → 不能据 parent 反查。
    """
    for tb in window.findChildren(QToolBar):
        if isinstance(tb.widgetForAction(window.action_tuning_ruler), QToolButton):
            return tb
    raise AssertionError("未找到分析工具栏（音律标尺所在）")


def test_toolbar_icon_only_group_and_tooltips(window):
    """纯图标组：高频 + 图标语义无歧义 → IconOnly，且 tooltip 非空。"""
    toolbar = _file_toolbar(window)
    for name in _ICON_ONLY:
        act = getattr(window, name)
        btn = _tool_button(toolbar, act)
        assert btn is not None, f"{name} 无对应 QToolButton"
        assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        assert btn.toolTip().strip(), f"{name} 纯图标但 tooltip 为空"


def test_toolbar_naming_entries_keep_text(window):
    """命名入口 / 歧义入口保留文字（禁一刀切图标化）。"""
    toolbar = _file_toolbar(window)
    for name in _KEEP_TEXT:
        act = getattr(window, name)
        btn = _tool_button(toolbar, act)
        assert btn is not None
        assert btn.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly
        assert act.text().strip(), f"{name} 保留文字但文本为空"


def test_every_icon_only_toolbar_button_has_tooltip(window):
    """⑦ 结构断言：工具栏内任何 IconOnly 按钮都必须有非空 tooltip。"""
    for tb in window.findChildren(QToolBar):
        for act in tb.actions():
            btn = tb.widgetForAction(act)
            if isinstance(btn, QToolButton) and (
                btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
            ):
                assert btn.toolTip().strip(), f"{act.text()} 纯图标但无 tooltip"


def test_toolbar_level_style_unified_guard_intact(window):
    """既有守卫口径未变：两工具栏 toolbar 级 style 仍为统一值（未静默改写）。"""
    style = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert _file_toolbar(window).toolButtonStyle() == style
    assert _analysis_toolbar(window).toolButtonStyle() == style


def test_analysis_toolbar_tuning_ruler_keeps_text(window):
    """音律标尺为低频/语义可能歧义入口 → 保留文字（逐按钮判据）。"""
    btn = _tool_button(_analysis_toolbar(window), window.action_tuning_ruler)
    assert btn is not None
    assert btn.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly


# ---------------------------------------------------------------------------
# 面板头标题随页签同步（P2）
# ---------------------------------------------------------------------------


def test_panel_header_titles_follow_pages(window):
    """左右栏面板头标题随页签（文件/快速入门/手册/录音设置/设置、检查器/AI 释图）切换。"""
    assert window.left_panel_header.title() == tr("sidebar.tab.files")
    # T-1054 批1b 扩面⑧：5 页标题逐一验证（用 i18n 键，禁写死字串）
    title_map = {
        1: "sidebar.tab.quickstart",
        2: "sidebar.tab.manual",
        3: "sidebar.tab.record",
        4: "sidebar.tab.settings",
    }
    for idx, key in title_map.items():
        window.left_content.setCurrentIndex(idx)
        assert window.left_panel_header.title() == tr(key)
    window.left_content.setCurrentIndex(0)
    assert window.left_panel_header.title() == tr("sidebar.tab.files")

    assert window.right_panel_header.title() == tr("sidebar.tab.inspector")
    window.right_content.setCurrentIndex(1)
    assert window.right_panel_header.title() == tr("sidebar.tab.ai")
    window.right_content.setCurrentIndex(0)
    assert window.right_panel_header.title() == tr("sidebar.tab.inspector")


def test_panel_header_and_empty_state_follow_theme(window):
    """面板头/空态随主题刷新（dark→light→dark 逐值回原，禁固定色）。"""
    header = window.left_panel_header
    empty = window.analysis_empty_state
    dark = theme.colors()
    assert dark["text"] in header.styleSheet()
    assert dark["sub"] in empty.styleSheet()

    theme.apply_theme("light")
    try:
        light = theme.colors()
        assert light["border"] != dark["border"]
        assert light["border"] in header.styleSheet()
        assert light["sub"] in empty.styleSheet()
    finally:
        theme.apply_theme("dark")

    assert theme.colors()["text"] in header.styleSheet()
    assert theme.colors()["border"] in header.styleSheet()
