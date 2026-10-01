# SPDX-License-Identifier: GPL-3.0-only
"""T-504g-migration 设置面板去模态化 + 栏位 tab 接入测试（T-1010 设置归左栏 tab）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QListWidget, QStackedWidget, QWidget, QDialog
from acouscope.ui.widgets.settings_dialog import SettingsDialog

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"


def test_settings_dialog_is_widget_not_modal(qapp):
    d = SettingsDialog()
    assert isinstance(d, QWidget)
    assert not isinstance(d, QDialog)


def test_applied_signal_on_apply(qapp):
    d = SettingsDialog()
    seen = []
    d.applied.connect(lambda: seen.append(1))
    d.btn_apply.click()
    assert seen == [1]


def test_cancelled_only_when_unapplied(qapp):
    d = SettingsDialog()
    seen = []
    d.cancelled.connect(lambda: seen.append("c"))
    d.close()                      # 未应用即关 → cancelled
    assert seen == ["c"]
    d2 = SettingsDialog()
    seen2 = []
    d2.cancelled.connect(lambda: seen2.append("c"))
    d2.btn_apply.click()           # 应用后关闭 → 不发 cancelled
    d2.close()
    assert seen2 == []


def test_switch_to_tab_still_works(qapp):
    d = SettingsDialog()
    d.switch_to_tab("ai")          # 不抛异常即可


def test_embedded_in_page_host(qapp):
    """非模态嵌入：设置面板可装入右栏内容页宿主容器且非模态。

    抽屉（open_drawer）已整体退役，等价断言改为普通 QWidget 子件装入宿主。
    """
    from PyQt6.QtWidgets import QVBoxLayout

    host = QWidget()
    host.resize(1200, 800)
    host.show()
    panel = SettingsDialog()
    layout = QVBoxLayout(host)
    layout.addWidget(panel)
    qapp.processEvents()
    assert not isinstance(panel, QDialog)     # 非模态面板（非对话框）
    assert panel.parent() is host             # 装入宿主容器
    assert panel.isModal() is False           # 非模态语义保留
    assert panel.isVisibleTo(host)            # 宿主显示时面板随之可见


def test_sources_de_modalized():
    sd = (UI / "widgets" / "settings_dialog.py").read_text(encoding="utf-8")
    assert ".exec(" not in sd and "QDialogButtonBox" not in sd
    ai = (UI / "widgets" / "ai_interpret.py").read_text(encoding="utf-8")
    assert ".exec(" not in ai
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    # 批4c：录音设置抽屉退役 → main_window 无 open_drawer 调用/import；
    # 批4d：抽屉基础设施本体（drawer.py）亦整体删除 → 反向断言文件不存在
    assert "open_drawer" not in mw
    assert not (UI / "widgets" / "drawer.py").exists()


# ----------------------------------------------------------------------
# T-1013：设置两栏（左导航列表 + 右内容栈；替代顶部 QTabWidget）
# ----------------------------------------------------------------------


def test_settings_two_column_nav_and_stack(qapp):
    """两栏结构：左导航 QListWidget 与右 QStackedWidget 各 6 项，顺序即原 tab 序。"""
    from acouscope.i18n import tr

    d = SettingsDialog()
    try:
        assert isinstance(d.nav_list, QListWidget)
        assert isinstance(d.stack, QStackedWidget)
        assert d.nav_list.count() == 6
        assert d.stack.count() == 6
        assert [d.nav_list.item(i).text() for i in range(6)] == [
            tr("settings.tab.general"),
            "音频设备",
            tr("settings.tab.ai"),
            tr("settings.tab.interface"),
            "快捷键",
            tr("settings.tab.export"),
        ]
    finally:
        d.deleteLater()


def test_settings_switch_to_tab_syncs_both_columns(qapp):
    """switch_to_tab / 点左导航 → 左右两栏索引同步，6 页均可达。"""
    d = SettingsDialog()
    try:
        for name, idx in (
            ("general", 0), ("audio", 1), ("ai", 2), ("interface", 3),
            ("shortcuts", 4), ("export", 5),
        ):
            d.switch_to_tab(name)
            assert d.nav_list.currentRow() == idx
            assert d.stack.currentIndex() == idx
            assert d.stack.currentWidget() is d.stack.widget(idx)
        d.nav_list.setCurrentRow(4)  # 反向：左导航 → 右内容
        assert d.stack.currentIndex() == 4
    finally:
        d.deleteLater()


def test_settings_two_column_no_clip_at_sidebar_width(qapp):
    """左栏展开宽度内完整显示：左列窄、无省略；6 页最小宽 ≤ 内容栈宽。"""
    d = SettingsDialog()
    d.resize(560, 640)
    d.show()
    try:
        qapp.processEvents()
        # 布局遵从最小宽约束：若任一页 min 超宿主宽则窗口会自行撑宽 → 判失败
        assert d.width() <= 560
        nav_vp = d.nav_list.viewport().width()
        stack_w = d.stack.width()  # QStackedWidget 非 QAbstractScrollArea，无 viewport
        assert nav_vp > 0 and stack_w > 0
        assert nav_vp < stack_w, "左标签栏应显著窄于右内容区"
        assert d.nav_list.sizeHintForColumn(0) <= nav_vp, "左导航文本被省略"
        for i in range(d.stack.count()):
            d.stack.setCurrentIndex(i)
            qapp.processEvents()
            page = d.stack.widget(i)
            assert page.minimumSizeHint().width() <= stack_w, (
                f"page{i} 最小宽 {page.minimumSizeHint().width()} > 内容区宽 {stack_w}"
            )
    finally:
        d.close()
        d.deleteLater()
