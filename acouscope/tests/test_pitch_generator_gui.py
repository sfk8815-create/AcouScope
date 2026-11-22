# SPDX-License-Identifier: GPL-3.0-only
"""合成音高生成器 GUI 判据（判据 5–6，全离屏，禁 show()）。"""
from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QLabel, QMenu  # noqa: E402

import acouscope.utils.config as _cfg  # noqa: E402
from acouscope.app.controller import AppController  # noqa: E402
from acouscope.i18n import set_language, tr  # noqa: E402
from acouscope.ui.main_window import MainWindow  # noqa: E402
from acouscope.ui.widgets.pitch_generator_dialog import PitchGeneratorDialog  # noqa: E402

LOCALES = ("en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP")
_PUBLIC_NAMES = (
    "standards_combo", "note_combo", "octave_spin", "duration_spin",
    "sample_rate_combo", "amplitude_spin", "waveform_combo", "depth_combo",
    "fade_spin", "preview_widget", "caveat_label", "status_label",
    "btn_export", "btn_load", "btn_close",
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def dlg(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    dialog = PitchGeneratorDialog()
    yield dialog
    dialog.close()


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的 MainWindow（离屏构建，不 show；teardown close）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    data = 0.5 * np.sin(2 * np.pi * 440 * t)
    controller.load_from_array(data, sr)
    w = MainWindow(controller)
    w.waveform_widget.set_data(t, data, sample_rate=sr)
    yield w
    w.close()


# ===========================================================================
# 判据 5 · GUI 离屏
# ===========================================================================


def test_combo_has_13_and_three_group_titles(dlg):
    assert dlg.standards_combo.count() == 13
    labels = [
        x for x in dlg.findChildren(QLabel)
        if x.objectName().startswith("group_label_")
    ]
    assert len(labels) == 3
    assert all(x.text() for x in labels)
    joined = " ".join(x.text() for x in labels)
    # historical / orchestral 明确标注「非 ISO」，禁称作 ISO 标准
    assert ("非 ISO" in joined) or ("NOT ISO" in joined)


def test_public_api_object_names(dlg):
    for name in _PUBLIC_NAMES:
        widget = getattr(dlg, name)
        assert widget.objectName() == name, f"{name} 的 objectName 不符"


def test_defaults_iso16_a4_440(dlg):
    assert dlg.current_standard()["id"] == "iso16_1975"
    assert dlg.note_combo.currentData() == "A"
    assert dlg.octave_spin.value() == 4
    assert dlg.current_frequency_hz() == 440.0
    assert dlg.sample_rate_combo.currentData() == 44100
    assert dlg.duration_spin.value() == 2.0
    assert dlg.amplitude_spin.value() == 0.8
    assert dlg.waveform_combo.currentData() == "sine"
    assert dlg.depth_combo.currentData() == "pcm16"
    assert dlg.fade_spin.value() == 0.01


def test_set_standard_443_caveat_warning(dlg):
    before = dlg.caveat_label.text()
    dlg.set_standard("orchestral_443")
    assert dlg.current_frequency_hz() == 443.0
    text = dlg.caveat_label.text()
    assert "NOT an ISO standard" in text
    assert text != before


def test_c4_at_443(dlg):
    dlg.set_standard("orchestral_443")
    dlg.note_combo.setCurrentIndex(0)  # C
    assert dlg.octave_spin.value() == 4
    assert dlg.current_frequency_hz() == pytest.approx(443 * 2 ** (-9 / 12), abs=1e-9)


def test_export_wave_wave_readable(dlg, tmp_path):
    path = dlg.export_wave(tmp_path / "a.wav")
    assert Path(path).is_file()
    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == int(dlg.sample_rate_combo.currentData())


def test_export_button_writes_file(dlg, tmp_path, monkeypatch):
    target = tmp_path / "via_button.wav"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(target), "WAV (*.wav)"),
    )
    dlg.btn_export.click()
    assert target.is_file()
    assert dlg.status_label.text()


def test_export_cancel_leaves_status(dlg, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    dlg.status_label.setText("")
    dlg.btn_export.click()
    assert dlg.status_label.text() == ""


def test_load_disabled_without_controller(dlg):
    assert dlg._controller is None
    assert dlg.btn_load.isEnabled() is False


def test_load_with_fake_controller(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")

    class FakeController:
        def __init__(self):
            self.calls = []

        def load_from_array(self, data, sr, name="recording"):
            self.calls.append((data, sr, name))

    fake = FakeController()
    dialog = PitchGeneratorDialog(controller=fake)
    try:
        assert dialog.btn_load.isEnabled() is True
        dialog.btn_load.click()
        assert len(fake.calls) == 1
        data, sr, name = fake.calls[0]
        assert isinstance(data, np.ndarray) and data.size > 0
        assert sr == 44100
        assert name == "pitchgen_iso16_1975_A4"
        assert dialog.status_label.text()
    finally:
        dialog.close()


def test_close_button_rejects(dlg, monkeypatch):
    seen = []
    monkeypatch.setattr(dlg, "reject", lambda: seen.append(True))
    dlg.btn_close.click()
    assert seen == [True]


def test_preview_grab_offscreen(dlg):
    pix = dlg.preview_widget.grab()
    assert pix is not None
    assert pix.isNull() is False


def test_preview_updates_on_param_change(dlg):
    before = dlg._preview_data.copy()
    dlg.waveform_combo.setCurrentIndex(1)  # harmonic
    assert not np.array_equal(dlg._preview_data, before)
    dlg.set_standard("orchestral_443")
    assert dlg._preview_data is not None and dlg._preview_data.size >= 2


def test_cents_vs_a440_tracks_standard_not_note(dlg):
    """读数 = 1200*log2(a4/440)，与音名无关；A4@440 为 0（正对照）。"""
    # A4 @ 440（默认 ISO 16）→ 0.0
    assert dlg.current_cents_vs_a440() == pytest.approx(0.0, abs=0.01)

    dlg.set_standard("orchestral_443")
    a4_443 = dlg.current_cents_vs_a440()
    dlg.note_combo.setCurrentIndex(0)  # C4 @ 443
    c4_443 = dlg.current_cents_vs_a440()

    expected = pytest.approx(1200 * np.log2(443 / 440), abs=0.01)
    assert a4_443 == expected
    assert c4_443 == expected
    assert a4_443 == pytest.approx(c4_443, abs=0.01)
    # 正对照：与 A4@440 的 0.0 不同（两类输入产生不同输出）
    assert a4_443 != pytest.approx(0.0, abs=0.01)


def test_preview_buffer_is_short_not_full_duration(dlg):
    """预览仅合成 0.02 s 短片段；build_audio() 仍产出完整时长。"""
    dlg.duration_spin.setValue(30.0)
    dlg.sample_rate_combo.setCurrentIndex(
        dlg.sample_rate_combo.findData(96000)
    )
    dlg._refresh()
    assert len(dlg._preview_data) < 0.03 * 96000
    assert len(dlg.build_audio()[0]) == 30 * 96000


@pytest.mark.parametrize("lang", LOCALES)
def test_all_locales_nonempty(qapp, monkeypatch, tmp_path, lang):
    """五语逐档：windowTitle 与三个按钮文本均非空且不等于键名。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    try:
        set_language(lang)
        dialog = PitchGeneratorDialog()
        try:
            assert dialog.windowTitle()
            assert dialog.windowTitle() != "pitchgen.title"
            for button in (dialog.btn_export, dialog.btn_load, dialog.btn_close):
                assert button.text()
                assert button.text() not in (
                    "pitchgen.btn.export", "pitchgen.btn.load", "pitchgen.btn.close",
                )
        finally:
            dialog.close()
    finally:
        set_language("zh_CN")


# ===========================================================================
# 判据 6 · 菜单入口
# ===========================================================================


def test_action_properties(window):
    action = window.action_pitch_generator
    assert action.objectName() == "pitch_generator"
    assert action.text() == tr("action.pitch_generator")
    assert action.shortcut().isEmpty() is True


def test_action_belongs_to_tools_menu(window):
    action = window.action_pitch_generator
    menus = [m for m in window.findChildren(QMenu) if action in m.actions()]
    assert any(m.title() == tr("menu.tools") for m in menus), [m.title() for m in menus]


def test_trigger_opens_dialog_with_controller(window, monkeypatch):
    import acouscope.ui.widgets.pitch_generator_dialog as pgd

    seen: dict = {}

    def fake_exec(self):
        seen["type"] = type(self).__name__
        seen["parent"] = self.parent()
        seen["controller"] = self._controller
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(pgd.PitchGeneratorDialog, "exec", fake_exec)
    window.action_pitch_generator.trigger()
    assert seen.get("type") == "PitchGeneratorDialog"
    assert seen.get("parent") is window
    assert seen.get("controller") is window.controller


# ===========================================================================
# 测试文件自身纪律
# ===========================================================================


def test_gui_test_never_shows_window():
    src = Path(__file__).read_text(encoding="utf-8")
    assert ("window" + ".show()") not in src
    assert ("dlg" + ".show()") not in src
    assert ("dialog" + ".show()") not in src


# ===========================================================================
# PI-P6-PITCH-02 · 24-bit PCM 下拉与导出链路（离屏，禁 show()）
# ===========================================================================


def test_depth_combo_has_pcm24_in_order(dlg):
    assert dlg.depth_combo.count() == 3
    items = [dlg.depth_combo.itemData(i) for i in range(3)]
    assert items == ["pcm16", "pcm24", "float32"]
    assert dlg.depth_combo.currentData() == "pcm16"


def test_export_pcm24_sampwidth_and_button_chain(dlg, tmp_path, monkeypatch):
    dlg.depth_combo.setCurrentIndex(dlg.depth_combo.findData("pcm24"))
    assert dlg.depth_combo.currentData() == "pcm24"
    direct = dlg.export_wave(tmp_path / "a24.wav")
    with wave.open(str(direct), "rb") as wf:
        assert wf.getsampwidth() == 3
        assert wf.getnchannels() == 1
    # status_label 链路：monkeypatch 保存对话框后点击导出按钮复验一次
    target = tmp_path / "via_button24.wav"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(target), "WAV (*.wav)"),
    )
    dlg.status_label.setText("")
    dlg.btn_export.click()
    assert target.is_file()
    assert dlg.status_label.text()
    with wave.open(str(target), "rb") as wf:
        assert wf.getsampwidth() == 3


def test_pcm24_label_five_locales(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    try:
        for lang in LOCALES:
            set_language(lang)
            text = tr("pitchgen.depth.pcm24")
            assert text
            assert text != "pitchgen.depth.pcm24"
    finally:
        set_language("zh_CN")
