# SPDX-License-Identifier: GPL-3.0-only
"""T-1083 守卫测：右簇两钮复用现成图标 + 后端选择器溢出解 + 零新增 ICONS 键。

断言纪律：全离屏；构造 MainWindow 但不 show()、不弹模态。
"""

import inspect
import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QSizePolicy

from acouscope.app.controller import AppController
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from tests._pin_baselines import ICONS_LOGICAL_NAME_COUNT

_MAIN_PY = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "acouscope" / "ui" / "main_window.py"
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 300 * t), sr)

    w = MainWindow(controller)
    yield w
    w.close()


def test_ai_and_chart_designer_icons_not_null(window):
    assert not window.btn_ai_interpret.icon().isNull()
    assert not window.action_chart_designer.icon().isNull()


def test_no_new_icns_key():
    assert len(theme.ICONS) == ICONS_LOGICAL_NAME_COUNT


def test_backend_selector_combo_elastic():
    src = inspect.getsource(MainWindow._create_backend_selector)
    combo_lines = [ln for ln in src.splitlines() if "combo." in ln]
    assert not any("setFixedWidth" in ln for ln in combo_lines)
    assert "QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed" not in src
    assert "QSizePolicy.Policy.Preferred" in src


def test_backend_selector_runtime_size_policy(window):
    widget = window._create_backend_selector()
    combo = window._backend_combo
    assert combo.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred
    assert widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred
    assert combo.minimumWidth() >= 140
    assert widget.minimumWidth() < 240
