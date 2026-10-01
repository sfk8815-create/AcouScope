# SPDX-License-Identifier: GPL-3.0-only
"""T-1043 交互语义：开关 vs 命令（ARCH_ui_visual_language §五b / §五-6）。

判据（N1）：入口是否产生「持续态界面」（面板 / 抽屉 / 覆盖层 / 页签切换）
  → 是 = 开关（checkable + 状态与可见性双向同步 + 再点同入口 = 关闭，幂等）；
  → 否 = 命令（禁做成开关）。
持续态界面必须有**可见关闭出口**（面板头右侧；Esc / 点外部为额外路径）。

本文件覆盖放行令 RELEASE_T-1043 专项断言 ①~⑩：
  ① 全铺页入口（图表设计器，批4a）+ 两 ribbon 按钮 isCheckable 为真；
  ② 命令型入口 isCheckable 为假；③ 再点即关；④ 收回本页后入口取消勾选；
  ⑤ setChecked(True) 后全铺页 index4 为当前页；⑥ 页/开关组可见关闭出口（非空表，批4c）；
  ⑦ 覆盖层关闭路径（Esc / 点击外部）随抽屉退役失去主语（批4d）→ 反向断言在役宿主体制；⑧ set_content 切内容仍触发旧内容 closeEvent（批4d：改断 AI 宿主旧实例先 close）；
  ⑨ 无回环 / 无信号风暴；⑩ ribbon 折叠态与勾选态双向一致（含外部折叠路径）。
  ③ T-1054 批4c：录音入口口径 = 左栏 index3 页（非抽屉）。

fixture 参照 tests/test_sidebar_tabs.py：qapp（conftest）+ window（不 show）。
"""

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.app.controller import AppController
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.ai_interpret import AIInterpretDialog

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
# 批4d：抽屉实现整档删除（原 DrawerWidget / open_drawer 承载的所有断言改用反向断言）
_DRAWER_PY = _REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "drawer.py"

# 入口 → 所驱中央全铺页索引（N2；同一页的入口互斥勾选）
# T-1054 批3：action_room_modes / action_room_acoustics 已改走中央全铺页（非抽屉），
# 从抽屉宿主表移除（扩面②）；房间入口语义改由 workspace 开关组测试覆盖。
# T-1054 批4b：帮助族（action_quickstart / action_manual / ribbon_btn_help）已退役
# 改走左栏页。
# T-1054 批4a：图表设计器亦改走中央全铺页（index4）→ 全仓再无「抽屉型 action 入口」，
# 原 `_DRAWER_ATTR` 表已空 ⇒ 以**非空**主体表 _PAGE_ENTRY_INDEX 承接（禁空置写法：
# 仅删行会退化成 0 迭代空循环 = 守卫强度 0；反例 D 专抓此坑）。
_PAGE_ENTRY_INDEX = {
    "action_chart_designer": 4,
}

# 命令型入口（N6：一次性动作，禁做成开关）
_COMMAND_ACTIONS = (
    "action_about",         # 模态「关于」（CB-010 特批）
    "action_visit_site",    # 访问网站
    "action_save_project",
    "action_export",
    "action_undo",
    "action_redo",
)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（不 show()）；HOME 与数据目录隔离到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.2 * np.sin(2 * np.pi * 440.0 * t), sr)

    w = MainWindow(controller)
    yield w
    w.close()


# ----------------------------------------------------------------------
# ① / ② 开关化覆盖 + 命令型未被污染
# ----------------------------------------------------------------------


def test_switch_entries_are_checkable(window):
    """① 全铺页入口（图表设计器）+ 底部 ribbon 设置切页按钮 + 帮助? + 录音设置入口均可勾选。"""
    for name in _PAGE_ENTRY_INDEX:
        assert getattr(window, name).isCheckable() is True, name
    assert window.transport_bar.btn_record.isCheckable() is True   # 录音设置入口
    assert window.ribbon_btn_settings.isCheckable() is True
    assert window.ribbon_btn_help.isCheckable() is True            # 帮助族入口（走左栏页，开关）


def test_command_entries_stay_uncheckable(window):
    """② 命令型入口（关于/访问网站/保存/导出/撤销/重做）不得被改成开关。"""
    for name in _COMMAND_ACTIONS:
        act = getattr(window, name)
        assert act.isCheckable() is False, name
        assert act.isChecked() is False, name


# ----------------------------------------------------------------------
# ③ 再点即关（幂等 toggle）
# ----------------------------------------------------------------------


def test_second_trigger_closes_entry(window):
    """③ 每个全铺页入口：开 → 再点同入口 → 收回（禁「再点只重新进页」）。

    录音入口（左栏 index3 页宿主）的「再点收回」口径见下方
    test_record_entry_second_toggle_retracts_left_page（批4c：非中央全铺页）。
    """
    stack = window.central_stack
    for name, index in _PAGE_ENTRY_INDEX.items():
        act = getattr(window, name)
        act.trigger()
        assert stack.currentIndex() == index, name
        assert act.isChecked() is True, name
        act.trigger()
        assert act.isChecked() is False, name
        assert stack.currentIndex() == 0, name


def test_record_entry_second_toggle_retracts_left_page(window):
    """③+② 录音设置入口（传输条 ●）：批4c 口径 = 左栏 index3 常驻页（非抽屉）。

    勾选 → 展开左栏 + index3 + 页内常驻面板在；再点 → 收回左栏 + ● 复位。
    （原 :131 抽屉口径等价改写：抽屉已退役，判据强度不变 = 再点即收回。）
    """
    btn = window.transport_bar.btn_record
    btn.setChecked(True)
    assert window.left_panel.is_collapsed() is False
    assert window.left_content.currentIndex() == 3
    assert window.record_settings_panel is not None
    btn.setChecked(False)
    assert window.left_panel.is_collapsed() is True
    assert btn.isChecked() is False


def test_shared_left_page_entries_mutually_exclusive(window):
    """③+⑨ 左栏页入口组：同 index 入口同勾选、异 index 互斥（唯一槽 _on_left_page_toggled）。

    T-1054 批4b：帮助族（快速入门/手册/帮助?）改走左栏页；批4d 等价改写——
    抽屉已整档删除 ⇒ 原「同抽屉实例多入口互斥」语义由**同左栏页索引**承接。
    """
    # 快速入门（菜单 action, index1）→ 展开左栏并切快速入门页
    window.action_quickstart.trigger()
    assert window.left_panel.is_collapsed() is False
    assert window.left_content.currentIndex() == 1
    assert window.action_quickstart.isChecked() is True
    # 同 index 入口同勾选（设计）：ribbon 帮助? + 面板头快速入门钮
    assert window.ribbon_btn_help.isChecked() is True
    assert window.btn_header_quickstart.isChecked() is True
    # 异 index 入口未勾选：用户手册
    assert window.action_manual.isChecked() is False
    assert window.btn_header_manual.isChecked() is False
    # 帮助族已退役：_info_drawer 属性不存在
    assert not hasattr(window, "_info_drawer")
    # 换入口切到「用户手册」（index2）→ 所有 index1 入口取消勾选
    window.action_manual.trigger()
    assert window.action_manual.isChecked() is True
    assert window.left_content.currentIndex() == 2
    assert window.action_quickstart.isChecked() is False
    assert window.ribbon_btn_help.isChecked() is False
    assert window.btn_header_quickstart.isChecked() is False
    # 从 index2 切回 index1（ribbon 帮助?）→ 同 index 同勾选、异 index 复位
    window.ribbon_btn_help.click()
    assert window.left_content.currentIndex() == 1
    assert window.ribbon_btn_help.isChecked() is True
    assert window.action_quickstart.isChecked() is True
    assert window.action_manual.isChecked() is False
    # 同 index=4（设置页）双入口：ribbon 置底 ⚙ 与菜单 action_settings 同勾选
    window.ribbon_btn_settings.setChecked(True)
    assert window.left_content.currentIndex() == 4
    assert window.ribbon_btn_settings.isChecked() is True
    assert window.action_settings.isChecked() is True
    # 异 index 入口（index0 文件钮）随之复位（同实例多入口互斥的批4d 等价口径）
    assert window.btn_header_files.isChecked() is False
    assert window.ribbon_btn_help.isChecked() is False
    # 批4d：抽屉实现整档删除（原 test_shared_drawer_entries 的主语 drawer.py 已不存在）
    assert not _DRAWER_PY.exists()


# ----------------------------------------------------------------------
# ④ / ⑤ 双向同步
# ----------------------------------------------------------------------


def test_close_page_unchecks_entry(window):
    """④ 收回本页（_set_workspace_page(0)）→ 对应入口 isChecked() 为假（反同步，无回环）。"""
    # 主体 = 全铺页入口 action_chart_designer（T-1054 批4a：抽屉已退役，唯一状态源
    # _set_workspace_page 统管勾选态；语义与强度不变：收回 → 入口反勾选）
    window.action_chart_designer.trigger()
    assert window.central_stack.currentIndex() == 4
    assert window.action_chart_designer.isChecked() is True
    window._set_workspace_page(0)
    assert window.action_chart_designer.isChecked() is False


def test_explicit_set_checked_opens_page(window):
    """⑤ 入口 setChecked(True) → 中央全铺页 index4 为当前页（状态与可见性同向）。"""
    window.action_chart_designer.setChecked(True)
    assert window.central_stack.currentIndex() == 4
    assert window.central_stack.currentWidget() is window.chart_designer_page
    assert window.action_chart_designer.isChecked() is True


def test_no_signal_storm_and_no_reopen(window, qapp):
    """⑨ 唯一状态源用 blockSignals：无回环、无重复发信、收回路径不重进本页。"""
    # 主体 = 全铺页入口 action_chart_designer（T-1054 批4a）：同源回写勾选态
    # 不得额外发 toggled（否则回环）；收回路径不得把页重新点亮。
    act = window.action_chart_designer
    seen = []
    act.toggled.connect(lambda v: seen.append(v))
    act.trigger()
    assert window.central_stack.currentIndex() == 4
    act.trigger()
    assert window.central_stack.currentIndex() == 0
    qapp.processEvents()
    assert window.central_stack.currentIndex() == 0     # 关闭路径不得被延迟重开
    assert seen == [True, False]                        # 反同步不额外发 toggled（无信号风暴）


# ----------------------------------------------------------------------
# ⑥ 可见关闭出口（页 / 开关组口径，批4c 非空表）
# ----------------------------------------------------------------------

# 持续态界面入口 → 目标页/页索引（左栏 index3 / 中央全铺页 index4）
# 批4c（PI-T20 M9 + 处置 C-a）：在役抽屉归零 ⇒ 「在役抽屉有可见关闭按钮」失去主语；
# 改写为**非空表**逐条断言（禁空置写法：空表 = 0 迭代 = 守卫强度 0，教训 BB′），
# 与 §五b-10 原意等价（持续态界面必须有可见关闭出口，禁只靠 Esc）。
_CLOSE_EXIT_ENTRIES = (("btn_header_record", 3), ("action_chart_designer", 4))


def test_visible_close_exit_per_surface(window, qapp):
    """⑥ 每个持续态界面入口：可勾选 + 有 tooltip + 进入就位 + 再点收回。"""
    assert len(_CLOSE_EXIT_ENTRIES) >= 2          # 非空置（自证：空表 = 0 断言）
    for name, index in _CLOSE_EXIT_ENTRIES:
        ent = getattr(window, name)
        assert ent.isCheckable() is True, name
        assert ent.toolTip(), name
        ent.setChecked(True)
        qapp.processEvents()
        assert ent.isChecked() is True, name
        if index == 3:                            # 左栏页宿主（录音设置）
            assert window.left_panel.is_collapsed() is False, name
            assert window.left_content.currentIndex() == 3, name
        else:                                     # 中央全铺页宿主（图表设计器）
            assert window.central_stack.currentIndex() == index, name
        ent.setChecked(False)
        qapp.processEvents()
        assert ent.isChecked() is False, name
        if index == 3:
            assert window.left_panel.is_collapsed() is True, name
        else:
            assert window.central_stack.currentIndex() == 0, name
    # 附加（但不单独承担 ⑥）：抽屉归零口径
    assert not hasattr(window, "_rec_drawer")


# ----------------------------------------------------------------------
# ⑦ 覆盖层关闭路径（批4d：抽屉退役 ⇒ 反向断言 + 在役宿主等价）
# ----------------------------------------------------------------------


def test_no_overlay_host_and_drawer_absent(window, qapp):
    """⑦ 覆盖层关闭路径（Esc / 点击外部）随抽屉退役失去主语 → 改断在役等价事实。

    批4d：`drawer.py` 整档删除、`DrawerWidget.eventFilter` 不复存在。持续态界面
    一律由 PanelContainer 宿主页承载（页/折叠，非覆盖层）；入口驱动后窗口零抽屉
    实例残留（原 `_v099_drawer_*` 注册族亦已清零）。
    """
    from acouscope.ui.widgets.panels.panel_container import PanelContainer

    assert isinstance(window.left_panel, PanelContainer)
    assert isinstance(window.right_panel, PanelContainer)
    window.action_ai_interpret.trigger()
    qapp.processEvents()
    window.action_settings.trigger()
    qapp.processEvents()
    drawers = [k for k in window.__dict__ if k.startswith("_v099_drawer_")]
    assert drawers == []
    assert not hasattr(window, "_info_drawer")
    assert not hasattr(window, "_rec_drawer")
    assert not _DRAWER_PY.exists()          # 批4d：覆盖层实现整档删除
    if window._ai_panel is not None:
        window._ai_panel.close()


# ----------------------------------------------------------------------
# ⑧ 内容清理语义不破（内容替换 / 收回路径）
# ----------------------------------------------------------------------


def test_content_swap_still_triggers_old_content_cleanup(window, qapp):
    """⑧ 内容替换 → 旧内容清理路径仍被触发（AI 释图面板 cancel worker 依赖此路径）。

    批4d 等价改写：原经 `DrawerWidget.set_content` 的旧内容 closeEvent 验证；抽屉
    删除后，在役等价路径 = 右栏 AI 宿主每次入口新建实例、**旧实例先 close()** 再
    移出宿主（main_window._activate_ai_tab）⇒ 以 close 调用探针断清理不得被绕过。
    """
    window.action_ai_interpret.trigger()
    qapp.processEvents()
    first = window._ai_panel
    assert isinstance(first, AIInterpretDialog)

    closed = []
    orig_close = first.close
    first.close = lambda *a, **k: (closed.append(True), orig_close(*a, **k))[0]

    window.action_ai_interpret.trigger()
    qapp.processEvents()
    assert closed == [True], "旧内容清理路径（close）未被触发"
    assert window._ai_panel is not first, "入口应新建实例"
    assert isinstance(window._ai_panel, AIInterpretDialog)
    window._ai_panel.close()


def test_same_page_reclick_retracts_without_rebuild(window, qapp):
    """ N4：同内容页再请求 = 收回（不重进、不重建实例）——不绕过清理。

    原以 `open_drawer(host, probe)` 两次（同内容 → 关闭 + closeEvent）验证；
    批4d 改以在役右栏 AI 页（index1）等价口径：同页入口再请求 → 折叠收回，
    实例不变（下次进入前旧实例仍先 close，见上一用例）。
    """
    window.btn_header_ai.setChecked(True)
    qapp.processEvents()
    first = window._ai_panel
    assert isinstance(first, AIInterpretDialog)
    assert window.right_content.currentWidget() is window._ai_host
    assert window.right_panel.is_collapsed() is False

    window.btn_header_ai.setChecked(False)     # 同内容页再请求 → 收回本页
    qapp.processEvents()
    assert window.right_panel.is_collapsed() is True
    assert window.btn_header_ai.isChecked() is False
    assert window._ai_panel is first           # 收回路径不得重建实例
    assert window.right_content.currentIndex() == 1
    assert not hasattr(window, "_v099_drawer_640")
    window._ai_panel.close()


# ----------------------------------------------------------------------
#   ribbon 切页入口：激活态 + 再点收回 + 反向同步
# ----------------------------------------------------------------------


def test_files_header_toggle_bidirectional(window):
    """⑩ 文件入口（面板头 btn_header_files）：勾选 → 展开 + 文件页；再点 → 折叠；外部折叠/展开双向一致。"""
    assert window.left_panel.is_collapsed() is True
    assert window.btn_header_files.isChecked() is False

    window.btn_header_files.click()
    assert window.left_panel.is_collapsed() is False
    assert window.left_content.currentWidget() is window.file_browser
    assert window.btn_header_files.isChecked() is True

    # 外部折叠（左栏自带折叠钮 / 恢复布局）→ 入口反同步为未勾选
    window.left_panel.set_collapsed(True)
    assert window.btn_header_files.isChecked() is False

    # 外部展开 → 勾选态反映「当前页 = 文件」
    window.left_panel.set_collapsed(False)
    assert window.btn_header_files.isChecked() is True

    window.btn_header_files.click()          # 再点同入口 → 取消勾选并收回（折叠左栏）
    assert window.left_panel.is_collapsed() is True
    assert window.btn_header_files.isChecked() is False


def test_ribbon_settings_toggle_and_action_sync(window):
    """⑩ 设置入口（ribbon ⚙ / 菜单 action）同页同步；再点收回。"""
    window.ribbon_btn_settings.click()
    assert window.left_panel.is_collapsed() is False
    assert window.left_content.currentWidget() is window._settings_panel
    assert window.ribbon_btn_settings.isChecked() is True
    assert window.btn_header_files.isChecked() is False
    assert window.action_settings.isChecked() is True   # 同一持续态界面 → 同勾选

    window.ribbon_btn_settings.click()
    assert window.left_panel.is_collapsed() is True
    assert window.ribbon_btn_settings.isChecked() is False
    assert window.action_settings.isChecked() is False

    # T-1054 批1b #8：面板头快速入门钮（index1）同槽语义一致 ——
    # 单击展开+切快速入门页；再点收回（折叠左栏）
    window.btn_header_quickstart.click()
    assert window.left_panel.is_collapsed() is False
    assert window.left_content.currentWidget() is window._quickstart_page
    assert window.btn_header_quickstart.isChecked() is True
    window.btn_header_quickstart.click()
    assert window.left_panel.is_collapsed() is True
    assert window.btn_header_quickstart.isChecked() is False


def test_settings_action_toggle_expands_and_collapses(window):
    """⑩ 菜单设置入口（Ctrl+,）为开关：勾选展开切页；再点（取消）折叠左栏。"""
    window.action_settings.trigger()
    assert window.left_panel.is_collapsed() is False
    assert window.left_content.currentWidget() is window._settings_panel
    window.action_settings.trigger()
    assert window.left_panel.is_collapsed() is True
    assert window.action_settings.isChecked() is False


# ----------------------------------------------------------------------
# 静态纪律
# ----------------------------------------------------------------------


def test_static_discipline():
    """关闭按钮复用既有逻辑名 close（ICONS 未新增）；无新增模态；仓内无 brand 词。

    批4d：原「读 drawer.py 源码断无 QDialog / 无 setWindowModality」三条断言随
    抽屉整档删除失去主语 ⇒ 改为**反向断言**：抽屉实现不存在 + main_window 抽屉
    族标识符零出现（防复活；与 tests/test_no_drawer_mechanism.py 同口径）。
    """
    assert "close" in theme.ICONS
    assert not _DRAWER_PY.exists()          # 批4d：抽屉实现整档删除
    mw = (
        _REPO_ROOT / "src" / "acouscope" / "ui" / "main_window.py"
    ).read_text(encoding="utf-8")
    for sym in (
        "open_drawer",
        "DrawerWidget",
        "btn_toggle_drawer",
        "_v099_drawer_",
        "_register_drawer_entry",
        "_drawer_entries_of",
        "_bind_drawer_sync",
        "_sync_drawer_entry",
        "_clear_drawer_entries",
        "_drawer_entries",
        "_drawer_sync_bound",
        "_room_drawer",
        "_on_room_drawer_cancelled",
    ):
        assert sym not in mw, sym
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert ("MainWindow" + ".show()") not in src
