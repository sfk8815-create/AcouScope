# SPDX-License-Identifier: GPL-3.0-only
"""传输条 TransportBar 守卫测试（T-505b）。

qapp + 直接实例化 TransportBar（不构造 MainWindow），window 不 show()。
"""

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


@pytest.fixture
def bar(qapp):
    b = TransportBar()
    yield b
    b.close()


def test_transport_bar_has_expected_signals(bar):
    """9 个传输信号齐全（与 main_window 槽函数签名对应）。"""
    for name in (
        "playToggled", "playStop", "skipToStart", "skipToEnd",
        "recordToggled", "loopToggled", "speedChanged",
        "seekPreview", "seekCommit",
    ):
        assert hasattr(bar, name), f"缺少信号: {name}"


def test_buttons_emit_signals(bar):
    """按钮/滑条 → 同名信号发射。"""
    captured = []
    bar.playToggled.connect(lambda v: captured.append(("play", v)))
    bar.playStop.connect(lambda: captured.append(("stop",)))
    bar.seekCommit.connect(lambda: captured.append(("commit",)))

    bar.btn_play.toggle()
    assert ("play", True) in captured

    bar.btn_stop.click()
    assert ("stop",) in captured

    bar.slider_position.setValue(500)
    bar.slider_position.sliderReleased.emit()
    assert ("commit",) in captured


def test_setters_update_ui_without_signal(bar):
    """setter 同步 UI 且 blockSignals 不触发信号。"""
    fired = []
    bar.playToggled.connect(lambda v: fired.append(("play", v)))
    bar.recordToggled.connect(lambda v: fired.append(("rec", v)))
    bar.loopToggled.connect(lambda v: fired.append(("loop", v)))

    bar.set_play_button_state(True)
    assert bar.btn_play.isChecked()
    assert bar.btn_play.text() == "⏸"

    bar.set_record_button_state(True)
    assert bar.btn_record.text() == "■"
    assert tr("transport.tip_stop_record") in bar.btn_record.toolTip()

    bar.set_loop_state(True)
    assert bar.btn_loop.isChecked()

    assert fired == [], f"setter 不应触发信号，实际: {fired}"


def test_set_seek_and_time_label(bar):
    """set_seek_percent / set_time_label（format_seconds 格式，宽松子串断言）。"""
    from acouscope.ui.widgets.time_axis import format_seconds

    bar.set_seek_percent(300)
    assert bar.slider_position.value() == 300

    bar.set_time_label(1.5, 10.0)
    text = bar.lbl_current_time.text()
    assert format_seconds(1.5) in text
    assert format_seconds(10.0) in text
    assert text.count("/") == 1


def test_cmb_speed_emits_speed(bar):
    """速率下拉切换 → speedChanged(float)。"""
    captured = []
    bar.speedChanged.connect(lambda v: captured.append(v))

    bar.cmb_speed.setCurrentIndex(0)  # 0.5x
    assert 0.5 in captured
