# SPDX-License-Identifier: GPL-3.0-only
"""T-504c 录音设置去模态化 + T-1054 批4c 左栏页内嵌常驻（页口径）测试。

模式照抄 tests/test_settings_drawer.py（sys.path.insert 指向 src）；
批4c G1：抽屉退役 → 页内常驻面板（`record_settings_panel` 构建期置位，
其后不得被清成 None，否则 accepted 启动录音失效 = PI-T20 M4）。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QDialog, QWidget  # noqa: E402

from acouscope.ui.widgets.record_settings_dialog import RecordSettingsDialog  # noqa: E402

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"
from tests._pin_baselines import MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT


class _FakeRecorder:
    """录音器替身：只记 start 次数与运行态（判据 2「录音真启动」探针）。"""

    def __init__(self):
        self._is_recording = False
        self.sr = 44100
        self.started = 0

    def set_device(self, _device):
        pass

    def set_sample_rate(self, rate):
        self.sr = rate

    def set_channels(self, _channels):
        pass

    def start(self):
        self.started += 1
        self._is_recording = True
        return True

    def stop(self):
        self._is_recording = False
        return None

    def get_sample_rate(self):
        return self.sr

    def get_duration(self):
        return 0.0


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（不 show()）；HOME 隔离到 tmp_path（照 test_toggle_semantics）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    w = MainWindow(AppController())
    yield w
    w.close()


def _arm(window, monkeypatch, tmp_path, name="t1054c_take"):
    """进入录音页 + 装替身录音器 + 填合法路径；返回（替身, 面板）。"""
    fake = _FakeRecorder()
    monkeypatch.setattr(window, "_recorder", fake)
    window.transport_bar.btn_record.setChecked(True)
    panel = window.record_settings_panel
    panel.edit_dir.setText(str(tmp_path))
    panel.edit_filename.setText(name)     # 路径不存在 → 无覆盖确认弹窗
    return fake, panel


# ----------------------------------------------------------------------
# 面板本体（T-504c 既有口径，保持）
# ----------------------------------------------------------------------


def test_record_settings_is_widget_not_modal(qapp):
    d = RecordSettingsDialog()
    assert isinstance(d, QWidget)
    assert not isinstance(d, QDialog)


def test_accepted_on_valid_accept(qapp, tmp_path):
    d = RecordSettingsDialog()
    d.edit_dir.setText(str(tmp_path))
    d.edit_filename.setText("t")          # 自动补 .wav，路径不存在 → 无覆盖弹窗
    assert d.file_path() == str(tmp_path / "t.wav")
    seen = []
    d.accepted.connect(lambda: seen.append("a"))
    d.btn_start.click()
    assert seen == ["a"]
    assert d.was_accepted() is True


def test_cancelled_on_cancel_and_close(qapp):
    # 实例 1：点取消按钮 → cancelled（面板不自关，由宿主决定）
    d1 = RecordSettingsDialog()
    seen1 = []
    d1.cancelled.connect(lambda: seen1.append("c"))
    d1.btn_cancel.click()
    assert seen1 == ["c"]
    assert not d1.was_accepted()

    # 实例 2：未 accepted 直接 close() → closeEvent 兜底发 cancelled
    d2 = RecordSettingsDialog()
    seen2 = []
    d2.cancelled.connect(lambda: seen2.append("c"))
    d2.close()
    assert seen2 == ["c"]


def test_validation_failure_no_signal(qapp):
    d = RecordSettingsDialog()
    d.edit_filename.setText("")           # 空文件名 → 校验失败，面板保持打开
    acc, canc = [], []
    d.accepted.connect(lambda: acc.append("a"))
    d.cancelled.connect(lambda: canc.append("c"))
    d.btn_start.click()
    assert acc == []
    assert canc == []
    assert not d.was_accepted()
    assert "文件名" in d.lbl_note.text()


def test_was_accepted_flag(qapp, tmp_path):
    d = RecordSettingsDialog()
    assert d.was_accepted() is False
    d.edit_dir.setText(str(tmp_path))
    d.edit_filename.setText("t2")
    d.btn_start.click()
    assert d.was_accepted() is True


# ----------------------------------------------------------------------
# 批4c G1：页内常驻面板（R1）· 入口切页（R2）· 真启动（判据2）· 复位（判据3）
# ----------------------------------------------------------------------


def test_page_embeds_persistent_panel(window):
    """R1/M4：页内常驻面板存在（构建期置位，__init__ 后段不得清成 None）。"""
    panel = window.record_settings_panel
    assert panel is not None
    page = window._record_settings_page
    assert page.findChild(RecordSettingsDialog) is panel     # 面板确实挂在页内
    assert page.findChild(QWidget, "recordSettingsPageOpenBtn") is None  # 页承载按钮已退役


def test_entry_expands_left_page(window):
    """R2/判据 2：btn_record 勾选 → 展开左栏 + index3 + 面板非隐藏（不开抽屉）。"""
    window.transport_bar.btn_record.setChecked(True)
    assert window.left_panel.is_collapsed() is False
    assert window.left_content.currentIndex() == 3
    assert window.left_content.currentWidget() is window._record_settings_page
    assert window.record_settings_panel.isHidden() is False


def test_accepted_starts_recording_then_retracts_left(window, monkeypatch, tmp_path):
    """判据 2（M7）：accepted → **录音真启动**（探 _recorder/计时器，非只探槽被调）；
    R4-F：accepted 后经唯一槽收回左栏（= 原 close_drawer 等价）。"""
    fake, panel = _arm(window, monkeypatch, tmp_path)
    panel.btn_start.click()
    assert fake.started == 1
    assert fake._is_recording is True                       # 真在录
    assert window._record_timer.isActive() is True
    assert window.transport_bar.btn_record.isChecked() is True
    assert window.left_panel.is_collapsed() is True          # R4-F 收回左栏
    assert panel.was_accepted() is True


def test_cancelled_resets_button(window, monkeypatch, tmp_path):
    """cancelled（未录音）→ ● 复位。"""
    _arm(window, monkeypatch, tmp_path)
    window.record_settings_panel.btn_cancel.click()
    assert window.transport_bar.btn_record.isChecked() is False


def test_cancel_during_recording_stops_recorder(window, monkeypatch, tmp_path):
    """判据 3（M6）：录音中点「取消」→ btn=False **且** recorder 不在跑（禁分裂态）。"""
    fake, _panel = _arm(window, monkeypatch, tmp_path, name="t1054c_take_m6")
    window.record_settings_panel.btn_start.click()
    assert fake._is_recording is True
    # 录音中重新进入录音页（按钮态仍亮）→ 取消按钮可达
    window.btn_header_record.setChecked(True)
    assert window.left_content.currentIndex() == 3
    assert window.transport_bar.btn_record.isChecked() is True
    window.record_settings_panel.btn_cancel.click()
    assert window.transport_bar.btn_record.isChecked() is False   # 按钮灭
    assert fake._is_recording is False                            # 且录音已停
    assert window._record_timer.isActive() is False


def test_retract_paths_reset_button(window, monkeypatch, tmp_path):
    """判据 3（M5）：4 条离开 index3 路径 → ● 均复位（原抽屉 closed 兜底退役后）。"""
    paths = {
        # ① 面板头录音钮再点（入口自带收回）
        "header_record_toggle": lambda w: w.btn_header_record.setChecked(False),
        # ② 切到其它左栏页（用户手册）
        "switch_page": lambda w: w.btn_header_manual.setChecked(True),
        # ③ 工具栏左栏开关折叠
        "toolbar_collapse": lambda w: w.btn_toggle_left_panel.setChecked(False),
        # ④ left_content.setCurrentIndex(0)（直接切页）
        "set_current_index": lambda w: w.left_content.setCurrentIndex(0),
    }
    for name, act in paths.items():
        w = window
        w.transport_bar.btn_record.setChecked(True)
        assert w.left_panel.is_collapsed() is False, name
        assert w.transport_bar.btn_record.isChecked() is True, name
        act(w)
        assert w.transport_bar.btn_record.isChecked() is False, name  # 复位
        assert w._record_timer.isActive() is False, name
        # 收尾：回到初始态（下一轮从干净态进入）
        w.btn_toggle_left_panel.setChecked(True)
        w.btn_header_files.setChecked(True)
        w.btn_toggle_left_panel.setChecked(False)


def test_left_page_is_record_page_group(window):
    """R2（M8）：入口「再点收回」用**当前态**判据，不依赖粘滞 was_accepted()。

    一次完整 accepted 循环后再点 ● → 仍须收回（was_accepted 恒 True 不得妨碍）。
    """
    w = window
    w.transport_bar.btn_record.setChecked(True)
    assert w.left_content.currentIndex() == 3
    w.transport_bar.btn_record.setChecked(False)      # 再点 → 收回
    assert w.left_panel.is_collapsed() is True
    assert w.transport_bar.btn_record.isChecked() is False


def test_main_window_de_modalized():
    """源码口径：面板非模态 + 批4c 后 main_window 无抽屉在役调用（open_drawer=0）。

    批4d：抽屉机制整体退役（`ui/widgets/drawer.py` 整档删除）⇒ 上述反向断言
    仍成立并加强为「实现档亦不存在」。
    """
    mw = (UI / "main_window.py").read_text(encoding="utf-8")
    assert "RecordSettingsDialog.DialogCode" not in mw
    assert "open_drawer" not in mw            # 批4c：抽屉通路已拆；批4d 实现档亦删
    assert "from acouscope.ui.widgets.drawer import open_drawer" not in mw
    assert "_rec_drawer" not in mw
    assert not (UI / "widgets" / "drawer.py").exists()   # 批4d：抽屉实现整档删除
    assert "record_settings_panel" in mw
    assert "audio_data is None" in mw
    # 常量 MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT 集中把守·迁移每减一处改该常量一处
    assert mw.count("QMessageBox.question(") == MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT   # 录音完成白名单 + 模型未安装

    sd = (UI / "widgets" / "record_settings_dialog.py").read_text(encoding="utf-8")
    assert "class RecordSettingsDialog(QWidget)" in sd
    assert "QDialogButtonBox" not in sd
    assert ".exec(" not in sd