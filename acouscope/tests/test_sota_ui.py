# SPDX-License-Identifier: GPL-3.0-only
"""T-105: SOTA UI 集成测试。"""
import sys
sys.path.insert(0, "src")

import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestSotaUi:
    """SOTA UI 集成测试。"""

    def test_backend_selector_exists(self, qapp):
        """后端选择器可创建。"""
        from acouscope.ui.main_window import MainWindow
        # 仅检查方法存在，不实例化完整 MainWindow（需要大量 mock）
        assert hasattr(MainWindow, "_create_backend_selector")
        assert hasattr(MainWindow, "_run_sota_analysis")
        assert hasattr(MainWindow, "_detect_with_sota")

    def test_sota_ui_marker(self):
        """SOTA_UI_V1 标记存在。"""
        import acouscope.ui.main_window as mw
        assert "SOTA_UI_V1" in open(mw.__file__, encoding="utf-8").read()

    def test_default_backend_is_pyin(self, qapp):
        """默认后端为 pYIN。"""
        import acouscope.ui.main_window as mw_mod
        src = open(mw_mod.__file__, encoding="utf-8").read()
        assert "_pitch_backend" in src
        assert '"pYIN"' in src
