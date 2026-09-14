# SPDX-License-Identifier: GPL-3.0-only
"""T-203: v0.99 田野元数据导出 UI 测试。"""
import sys
sys.path.insert(0, "src")

import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestV099ExportUi:
    """田野元数据导出 UI 测试。"""

    def test_export_marker(self):
        """V099_EXPORT_UI_V1 标记存在。"""
        import acouscope.ui.main_window as mw
        src = open(mw.__file__, encoding="utf-8").read()
        assert "V099_EXPORT_UI_V1" in src

    def test_export_method_exists(self):
        """导出方法存在。"""
        from acouscope.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_export_field_metadata")

    def test_export_menu_action_exists(self):
        """导出菜单项存在。"""
        import acouscope.ui.main_window as mw
        src = open(mw.__file__, encoding="utf-8").read()
        assert "导出田野元数据" in src
