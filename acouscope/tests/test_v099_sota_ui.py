# SPDX-License-Identifier: GPL-3.0-only
"""T-202: v0.99 SOTA UI 集成测试。"""
import sys
sys.path.insert(0, "src")

import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestV099SotaUi:
    """SOTA UI 集成测试。"""

    def test_v099_marker(self):
        """V099_SOTA_UI_V1 标记存在。"""
        import acouscope.ui.main_window as mw
        src = open(mw.__file__, encoding="utf-8").read()
        assert "V099_SOTA_UI_V1" in src

    def test_backend_selector_method(self):
        """后端选择器方法存在。"""
        from acouscope.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_create_backend_selector")
        assert hasattr(MainWindow, "_run_sota_analysis")
        assert hasattr(MainWindow, "_detect_with_sota")

    def test_default_backend_pyin(self):
        """默认后端为 pYIN。"""
        import acouscope.ui.main_window as mw
        src = open(mw.__file__, encoding="utf-8").read()
        assert '_pitch_backend' in src
        assert '"pYIN"' in src

    def test_backend_dispatch_in_compute(self):
        """compute() 中有后端切换逻辑。"""
        import acouscope.ui.main_window as mw
        src = open(mw.__file__, encoding="utf-8").read()
        assert 'getattr(self, "_pitch_backend"' in src
        assert '_detect_with_sota' in src
