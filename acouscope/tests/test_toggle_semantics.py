# SPDX-License-Identifier: GPL-3.0-only
"""T-1043 交互语义：开关 vs 命令（ARCH_ui_visual_language §五b / §五-6）。

判据（N1）：入口是否产生「持续态界面」（面板 / 抽屉 / 覆盖层 / 页签切换）
  → 是 = 开关（checkable + 状态与可见性双向同步 + 再点同入口 = 关闭，幂等）；
  → 否 = 命令（禁做成开关）。
持续态界面必须有**可见关闭出口**（面板头右侧；Esc / 点外部为额外路径）。

本文件覆盖放行令 RELEASE_T-1043 专项断言 ①~⑩：
  ① 六抽屉入口 + 两 ribbon 按钮 isCheckable 为真；
  ② 命令型入口 isCheckable 为假；③ 再点即关；④ close_drawer 后入口取消勾选；
  ⑤ setChecked(True) 后抽屉为开；⑥ 抽屉有可见关闭按钮且点击即关；
  ⑦ Esc / 点击外部仍可用（不回归）；⑧ set_content 切内容仍触发旧内容 closeEvent；
  ⑨ 无回环 / 无信号风暴；⑩ ribbon 折叠态与勾选态双向一致（含外部折叠路径）。

fixture 参照 tests/test_sidebar_tabs.py：qapp（conftest）+ window（不 show）。
"""

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QFrame, QPushButton, QWidget

from acouscope.app.controller import AppController
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from acouscope.ui.theme import TOKENS
from acouscope.ui.widgets.drawer import DrawerWidget, open_drawer

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# 入口 → 所驱抽屉的实例属性名（N2；同一抽屉实例的入口互斥勾选）
# T-1054 批3：action_room_modes / action_room_acoustics 已改走中央全铺页（非抽屉），
# 从抽屉宿主表移除（扩面②）；房间入口语义改由 workspace 开关组测试覆盖。
_DRAWER_ATTR = {
    "action_quickstart": "_info_drawer",
    "action_manual": "_info_drawer",
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


class _Probe(QWidget):
    """记录 closeEvent 次数的探针部件（抽屉内容清理语义证据）。"""

    def __init__(self):
        super().__init__()
        self.close_events = 0

    def closeEvent(self, event):  # noqa: N802 (Qt 命名)
        self.close_events += 1
        super().closeEvent(event)


# ----------------------------------------------------------------------
# ① / ② 开关化覆盖 + 命令型未被污染
# ----------------------------------------------------------------------


def test_switch_entries_are_checkable(window):
    """① 六个抽屉入口 + 底部 ribbon 设置切页按钮 + 帮助? + 录音设置入口均可勾选。"""
    for name in _DRAWER_ATTR:
        assert getattr(window, name).isCheckable() is True, name
    assert window.transport_bar.btn_record.isCheckable() is True   # 录音设置入口
    assert window.ribbon_btn_settings.isCheckable() is True
    assert window.ribbon_btn_help.isCheckable() is True            # 走抽屉 → 按 N2


def test_command_entries_stay_uncheckable(window):
    """② 命令型入口（关于/访问网站/保存/导出/撤销/重做）不得被改成开关。"""
    for name in _COMMAND_ACTIONS:
        act = getattr(window, name)
        assert act.isCheckable() is False, name
        assert act.isChecked() is False, name


# ----------------------------------------------------------------------
# ③ 再点即关（幂等 toggle）
# ----------------------------------------------------------------------


def test_second_trigger_closes_drawer(window):
    """③ 每个抽屉入口：开 → 再点同入口 → 抽屉关闭（禁「再点只重新 open()」）。"""
    for name, attr in _DRAWER_ATTR.items():
        act = getattr(window, name)
        act.trigger()
        drawer = getattr(window, attr)
        assert drawer is not None and drawer.is_open() is True, name
        assert act.isChecked() is True, name
        act.trigger()
        assert act.isChecked() is False, name
        assert drawer.is_open() is False, name


def test_record_entry_second_toggle_closes_settings_drawer(window):
    """③ 录音设置入口（传输条 ●）：抽屉开着时再点 = 关闭抽屉。"""
    btn = window.transport_bar.btn_record
    btn.setChecked(True)
    drawer = window._rec_drawer
    assert drawer is not None and drawer.is_open() is True
    btn.setChecked(False)
    assert drawer.is_open() is False
    assert btn.isChecked() is False


def test_shared_drawer_entries_mutually_exclusive(window):
    """③+⑨ 共用同一抽屉的两个入口（菜单快速入门 / ribbon ?）互斥勾选。"""
    window.action_quickstart.trigger()
    assert window.action_quickstart.isChecked() is True
    window.ribbon_btn_help.click()
    assert window.ribbon_btn_help.isChecked() is True
    assert window.action_quickstart.isChecked() is False
    assert window._info_drawer.is_open() is True
    # 换入口切到「用户手册」→ 两个快速入门入口均取消勾选
    window.action_manual.trigger()
    assert window.action_manual.isChecked() is True
    assert window.action_quickstart.isChecked() is False
    assert window.ribbon_btn_help.isChecked() is False
    assert window._info_drawer.is_open() is True


# ----------------------------------------------------------------------
# ④ / ⑤ 双向同步
# ----------------------------------------------------------------------


def test_close_drawer_unchecks_entry(window):
    """④ 抽屉 close_drawer() → 对应入口 isChecked() 为假（反同步，无回环）。"""
    # 宿主 = 抽屉型入口 action_manual + _info_drawer（T-1054 批3 扩面③：
    # 房间入口已改走全铺页，语义由 workspace 开关组测试覆盖；抽屉语义以本宿主保持）
    window.action_manual.trigger()
    drawer = window._info_drawer
    assert window.action_manual.isChecked() is True
    drawer.close_drawer()
    assert window.action_manual.isChecked() is False


def test_explicit_set_checked_opens_drawer(window):
    """⑤ 入口 setChecked(True) → 抽屉为开（状态与可见性同向）。"""
    window.action_manual.setChecked(True)
    drawer = window._info_drawer
    assert drawer is not None and drawer.is_open() is True
    assert window.action_manual.isChecked() is True


def test_no_signal_storm_and_no_reopen(window):
    """⑨ 反同步用 blockSignals：无回环、无重复发信、关闭路径不重开。"""
    # 宿主 = 抽屉型入口 action_manual + _info_drawer（T-1054 批3 扩面③：
    # 房间入口已改走全铺页，抽屉反同步语义以本宿主保持，强度不变）
    act = window.action_manual
    seen = []
    act.toggled.connect(lambda v: seen.append(v))
    act.trigger()
    drawer = window._info_drawer
    assert drawer is not None and drawer.is_open() is True
    opens, closes = [], []
    drawer.opened.connect(lambda: opens.append(1))
    drawer.closed.connect(lambda: closes.append(1))
    act.trigger()
    assert drawer.is_open() is False
    assert closes == [1]
    assert opens == []                 # 关闭路径不得重开
    assert seen == [True, False]       # 反同步不额外发 toggled（无信号风暴）


# ----------------------------------------------------------------------
# ⑥ 可见关闭出口（面板头 + ✕）
# ----------------------------------------------------------------------


def test_drawer_has_visible_close_button(window):
    """⑥ 抽屉面板头存在可见关闭按钮（objectName=drawerCloseBtn），点击即关。"""
    window.action_manual.trigger()
    drawer = window._info_drawer
    header = drawer.findChild(QFrame, "drawerHeader")
    assert header is not None
    assert header.height() == TOKENS["control"]["h_lg"]
    assert drawer.title_label.text() == ""          # 标题可空（内容面板自带标题）
    btn = drawer.findChild(QPushButton, "drawerCloseBtn")
    assert btn is not None and not btn.isHidden()
    assert btn.toolTip()
    btn.click()
    assert drawer.is_open() is False
    assert window.action_manual.isChecked() is False


# ----------------------------------------------------------------------
# ⑦ Esc / 点击外部仍可用（不回归）
# ----------------------------------------------------------------------


def test_escape_and_outside_click_still_close(qapp):
    """⑦ 面板头关闭为**新增**出口，Esc 与点击外部为**额外**路径（多路径不互斥）。"""
    host = QWidget()
    host.resize(900, 700)
    host.show()
    d = DrawerWidget(host, width=360, duration=0)
    d.open()
    assert d.is_open() is True
    esc = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    assert d.eventFilter(host, esc) is True
    assert d.is_open() is False

    d.open()
    assert d.is_open() is True
    press = QMouseEvent(                       # 抽屉几何之外的外部点击
        QEvent.Type.MouseButtonPress,
        QPointF(QPoint(10, 10)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert d.eventFilter(host, press) is True
    assert d.is_open() is False
    host.close()


# ----------------------------------------------------------------------
# ⑧ 内容清理语义不破（set_content / toggle 关闭路径）
# ----------------------------------------------------------------------


def test_set_content_still_triggers_old_content_close_event(qapp):
    """⑧ 切内容 → 旧内容 closeEvent 仍被触发（AI 释图面板 cancel worker 依赖此路径）。"""
    host = QWidget()
    host.resize(900, 700)
    host.show()
    a, b = _Probe(), _Probe()
    open_drawer(host, a, width=360)
    open_drawer(host, b, width=360)
    assert a.close_events >= 1
    host.close()


def test_toggle_close_same_content_does_not_bypass_cleanup(qapp):
    """⑧ N4：同内容再请求 = 关闭；关闭路径先触发内容 closeEvent（不绕过清理）。"""
    host = QWidget()
    host.resize(900, 700)
    host.show()
    probe = _Probe()
    d = open_drawer(host, probe, width=360)
    assert d.is_open() is True
    d2 = open_drawer(host, probe, width=360)
    assert d2 is d
    assert d.is_open() is False
    assert probe.close_events >= 1
    host.close()


# ----------------------------------------------------------------------
# ⑩ ribbon 切页入口：激活态 + 再点收回 + 反向同步
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
    """关闭按钮复用既有逻辑名 close（ICONS 未新增）；无新增模态；仓内无 brand 词。"""
    assert "close" in theme.ICONS
    drawer_src = (
        _REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "drawer.py"
    ).read_text(encoding="utf-8")
    assert 'get_icon("close")' in drawer_src
    assert "QDialog" not in drawer_src
    assert "setWindowModality" not in drawer_src
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert ("MainWindow" + ".show()") not in src
