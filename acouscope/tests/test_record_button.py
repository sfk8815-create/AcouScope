# SPDX-License-Identifier: GPL-3.0-only
"""录音按钮「变身停止」交互测试（T-505b 后录音按钮位于独立传输条）。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.i18n import tr
from acouscope.ui.widgets.transport_bar import TransportBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_record_button_morphs_to_stop(qapp):
    bar = TransportBar()
    bar.set_record_button_state(True)
    assert bar.btn_record.text() == "■"
    assert tr("transport.tip_stop_record") in bar.btn_record.toolTip()
    assert bar.btn_record.isChecked()
    bar.close()


def test_record_button_restores_to_record(qapp):
    bar = TransportBar()
    bar.set_record_button_state(True)
    bar.set_record_button_state(False)
    assert bar.btn_record.text() == "●"
    assert tr("transport.tip_record") in bar.btn_record.toolTip()
    assert not bar.btn_record.isChecked()
    bar.close()
