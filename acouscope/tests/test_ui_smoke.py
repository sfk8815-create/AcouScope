# SPDX-License-Identifier: GPL-3.0-only
"""T-508 UI 结构冒烟测试：V099 三栏架构守卫（黑名单铁律）。

两层守卫：
① 结构用例（window fixture，离屏、不 show()）：三栏/堆叠/传输条/导航器
   删除守卫（T-1013）/检查器各就各位 + 无抽屉注册族（T-1054d 抽屉退役） +
   close 清理路径
② 模态清单用例（纯源码扫描，无需 qapp）：6 文件去模态化防回退 +
   QDialog 白名单清单

白名单（架构师核实，冒烟测试按白名单放行）：
- 弹窗演进：QDialog 已批量转 QWidget/toast（_CONVERTED_DIALOGS + support_dialog 已随开源化
  移除），其余见 AboutDialog 模态例外。
- about_dialog.py：AboutDialog(QDialog)+setModal(True)，CB-010 用户特批
  「关于」回归模态例外（main_window._on_about exec 调用点登记，见
  test_modal_whitelist_inventory 白名单 3）
- chart_font_dialog.py：ChartFontDialog 已转 QWidget（CB-001 #10，入 _CONVERTED_DIALOGS）
- sponsor_dialog.py：SponsorDialog(QDialog)+setModal(False) —— 非模态赞助致谢框
  （T-1017 白名单 4；无 exec、无倒计时、无赞助码，启动段与恢复确认错峰触发）
- QMenu.exec( 右键菜单（合法非对话框）：waveform / spectrum / plot_menu
"""

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import pyqtBoundSignal, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QStackedWidget,
)

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.panels import InspectorPanel

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_WIDGETS_DIR = _REPO_ROOT / "src" / "acouscope" / "ui" / "widgets"

# 已转 QWidget 的 6 文件（零 QDialog、零 .exec( 字面量）
# chart_font_dialog 于 CB-001 #10 转入（抽屉承载，fontChanged 即时生效）
# about_dialog 于 CB-010 移出（用户特批「关于」回归模态 QDialog，见白名单注释）
_CONVERTED_DIALOGS = [
    "ai_interpret",
    "settings_dialog",
    "room_modes",
    "record_settings_dialog",
    "help_dialogs",
    "chart_font_dialog",
]
# QMenu 右键菜单合法 .exec( 的 3 文件（.exec( 出现行均须含 "menu.exec"）
_QMENU_EXEC_FILES = ["waveform", "spectrum", "plot_menu"]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控；不 show()，参照 test_view_stack.py）。"""


    # 设置写入指向临时目录，避免污染用户配置
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    sweep = 0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t)
    controller.load_from_array(sweep, sr)

    w = MainWindow(controller)
    yield w
    w.close()


class TestV099Structure:
    """① 三栏结构冒烟（window fixture，离屏构建，不 show()）。"""

    def test_three_panels_wired(self, window):
        assert isinstance(window.inspector_panel, InspectorPanel)
        assert isinstance(window.view_container, QStackedWidget)
        assert window.transport_bar is not None
        assert window.waveform_widget is not None
        # 右面板父子链：内容必须是容器子孙（结构特征，非像素值）
        assert window.inspector_panel in window.right_panel.findChildren(
            InspectorPanel
        )

    def test_navigator_removed(self, window):
        # T-1013：AnalysisNavigator 删除守卫（覆盖 GUI_backlog #18 裁决 A）
        assert not hasattr(window, "analysis_navigator")
        import importlib

        with pytest.raises(ImportError):
            importlib.import_module(
                "acouscope.ui.widgets.panels.analysis_navigator"
            )
        import acouscope.ui.widgets.panels as _panels

        assert not hasattr(_panels, "AnalysisNavigator")
        # 懒构建语义保留：hint 页常驻，页数随交互增长，不硬断言 8
        assert window.view_container.count() >= 1

    def test_inspector_has_ai_entry(self, window):
        assert window.inspector_panel.btn_ai is not None
        assert window.inspector_panel.btn_ai.isEnabled()
        # PyQt6：实例访问得 pyqtBoundSignal，类访问得 pyqtSignal 描述符
        assert isinstance(window.inspector_panel.aiRequested, pyqtBoundSignal)
        assert isinstance(InspectorPanel.aiRequested, pyqtSignal)

    def test_close_cleanup_no_crash(self, window):
        # T-1054d：抽屉退役 → 改触发一个在役右栏页（图表字体页，无 worker）再 close
        window.action_chart_font.trigger()
        assert window.right_content.currentWidget() is window._chart_font_page
        window.close()  # closeEvent 走退出收尾路径，不得抛异常
        # 幂等：close 后再次 close 不报错
        window.close()

    def test_no_drawer_width_registry(self, window):
        # T-1054d：抽屉机制整体退役 → 实例上不得再残留 _v099_drawer_* 注册族
        assert [k for k in window.__dict__ if k.startswith("_v099_drawer_")] == []
        # 反向断言：抽屉组件源文件已整档删除（防能力回退）
        assert (_WIDGETS_DIR / "drawer.py").exists() is False


class TestModalInventory:
    """② 模态清单：源码扫描断言（无需 qapp，防去模态化回退）。"""

    def test_converted_dialogs_stay_qwidget(self):
        for name in _CONVERTED_DIALOGS:
            src = (_WIDGETS_DIR / f"{name}.py").read_text(encoding="utf-8")
            assert "QDialog" not in src, f"{name}.py 出现 QDialog 字面量（回退）"
            assert ".exec(" not in src, f"{name}.py 出现 .exec( 字面量（回退）"

    def test_modal_whitelist_inventory(self):
        # 白名单 2 已销账：ChartFontDialog 于 CB-001 #10 转 QWidget（见 _CONVERTED_DIALOGS）
        # 白名单 3（CB-010 用户特批）：AboutDialog 模态 QDialog 例外
        #   ——「关于」回归模态，仅结构断言文件级锚点（setModal + exec 调用点）。
        about_src = (_WIDGETS_DIR / "about_dialog.py").read_text(encoding="utf-8")
        assert "class AboutDialog(QDialog)" in about_src
        assert "setModal(True)" in about_src
        assert ".exec(" not in about_src  # exec 在 main_window 调用点，非对话框文件
        mw_src = (_WIDGETS_DIR.parent / "main_window.py").read_text(encoding="utf-8")
        assert "AboutDialog(self).exec()" in mw_src
        # 白名单 4（T-1017）：SponsorDialog 赞助致谢框——QDialog 但**非模态**
        #   （setModal(False) + show()，禁 exec；启动段与恢复确认错峰触发）。
        sponsor_src = (_WIDGETS_DIR / "sponsor_dialog.py").read_text(encoding="utf-8")
        assert "class SponsorDialog(QDialog)" in sponsor_src
        assert "setModal(False)" in sponsor_src
        assert ".exec(" not in sponsor_src
        # QMenu 右键菜单合法 .exec(：出现行均须含 "menu.exec"；
        # spectrum.py 的 _on_find_peaks 内联 QDialog 亦于 CB-001 #11 转 toast，
        # 故此处不再保留任何例外分支。
        for name in _QMENU_EXEC_FILES:
            lines = (_WIDGETS_DIR / f"{name}.py").read_text(
                encoding="utf-8"
            ).splitlines()
            for i, line in enumerate(lines, 1):
                if ".exec(" in line:
                    assert "menu.exec" in line, (
                        f"{name}.py L{i} 的 .exec( 不属于白名单: {line.strip()}"
                    )
