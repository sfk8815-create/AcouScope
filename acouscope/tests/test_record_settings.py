# SPDX-License-Identifier: GPL-3.0-only
"""录音设置对话框与多格式保存的单元测试。"""

import numpy as np
import pytest

pytest.importorskip("soundfile")

from PyQt6.QtWidgets import QApplication

from acouscope.audio.recorder import save_audio_file
from acouscope.ui.widgets.record_settings_dialog import (
    RECORD_FORMATS,
    RecordSettingsDialog,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def tone():
    sr = 44100
    t = np.arange(sr) / sr
    return 0.5 * np.sin(2 * np.pi * 440 * t), sr


# ------------------------------------------------------------------
# save_audio_file
# ------------------------------------------------------------------

class TestSaveAudioFile:
    @pytest.mark.parametrize("depth", ["PCM_16", "PCM_24", "FLOAT"])
    def test_wav_depths(self, tmp_path, tone, depth):
        data, sr = tone
        ok, path = save_audio_file(data, sr, str(tmp_path / f"t.wav"), "WAV", depth)
        assert ok
        import soundfile as sf
        info = sf.info(path)
        assert info.samplerate == sr
        assert info.subtype == depth

    @pytest.mark.parametrize("fmt,ext", [
        ("FLAC", ".flac"), ("AIFF", ".aiff"), ("MP3", ".mp3"), ("OGG", ".ogg"),
    ])
    def test_formats_roundtrip(self, tmp_path, tone, fmt, ext):
        data, sr = tone
        ok, path = save_audio_file(data, sr, str(tmp_path / f"t{ext}"), fmt, None)
        assert ok, path
        import soundfile as sf
        back, sr2 = sf.read(path)
        assert sr2 == sr
        assert len(back) == len(data) or fmt in ("MP3", "OGG")  # 有损可有帧差

    def test_extension_autofix(self, tmp_path, tone):
        """格式与扩展名不匹配时自动纠正。"""
        data, sr = tone
        ok, path = save_audio_file(data, sr, str(tmp_path / "t.mp3"), "OGG", None)
        assert ok
        assert path.endswith(".ogg")

    def test_creates_missing_dir(self, tmp_path, tone):
        data, sr = tone
        ok, path = save_audio_file(
            data, sr, str(tmp_path / "new" / "sub" / "t.wav"), "WAV", "PCM_16"
        )
        assert ok

    def test_empty_data(self, tmp_path):
        ok, msg = save_audio_file(np.array([]), 44100, str(tmp_path / "t.wav"))
        assert not ok

    def test_mp3_default_depth_ignored(self, tmp_path, tone):
        """MP3 忽略 depth 参数。"""
        data, sr = tone
        ok, _ = save_audio_file(data, sr, str(tmp_path / "t.mp3"), "MP3", "PCM_16")
        assert ok


# ------------------------------------------------------------------
# RecordSettingsDialog
# ------------------------------------------------------------------

class TestRecordSettingsDialog:
    def test_defaults(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "acouscope.ui.widgets.record_settings_dialog._last_dir",
            str(tmp_path),
        )
        # T-1054 批4c（PI-T20 M1）：`_last_rate` 为模块级会话内粘滞全局，任何
        # accept 过的面板都会写它 ⇒ 档序敏感（drawer 档先跑会污染本档的 48000 断言）。
        # 本处显式归零（粘滞全局本体属禁碰面，登记不修），使本档与档序无关。
        monkeypatch.setattr(
            "acouscope.ui.widgets.record_settings_dialog._last_rate",
            None,
        )
        dlg = RecordSettingsDialog(current_rate=48000)
        assert dlg.format_name() == "WAV"
        assert dlg.depth() == "PCM_16"
        assert dlg.sample_rate() == 48000  # 工具栏当前采样率预填
        assert dlg.channels() == 1
        assert dlg.file_path().endswith(".wav")
        assert dlg.file_path().startswith(str(tmp_path))

    def test_format_depth_linkage(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "acouscope.ui.widgets.record_settings_dialog._last_dir",
            str(tmp_path),
        )
        dlg = RecordSettingsDialog()

        # WAV：3 种深度
        assert [dlg.cmb_depth.itemText(i) for i in range(dlg.cmb_depth.count())] == [
            "16-bit PCM", "24-bit PCM", "32-bit 浮点",
        ]

        # MP3：深度禁用 + 提示
        dlg.cmb_format.setCurrentText("MP3")
        assert not dlg.cmb_depth.isEnabled()
        assert "有损" in dlg.lbl_note.text()
        assert dlg.file_path().endswith(".mp3")

        # FLAC：16/24
        dlg.cmb_format.setCurrentText("FLAC")
        assert dlg.cmb_depth.isEnabled()
        assert dlg.cmb_depth.count() == 2

    def test_filename_timestamp(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "acouscope.ui.widgets.record_settings_dialog._last_dir",
            str(tmp_path),
        )
        dlg = RecordSettingsDialog()
        assert "recording_" in dlg.edit_filename.text()

    def test_depth_memory_across_dialogs(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "acouscope.ui.widgets.record_settings_dialog._last_dir",
            str(tmp_path),
        )
        import acouscope.ui.widgets.record_settings_dialog as mod

        mod._last_fmt = "WAV"
        mod._last_depth = "PCM_24"
        dlg = RecordSettingsDialog()
        assert dlg.depth() == "PCM_24"

    def test_formats_table_consistency(self):
        """所有格式条目结构完整。"""
        for fmt, (ext, depths, default) in RECORD_FORMATS.items():
            assert ext.startswith(".")
            if depths:
                assert default in depths
            else:
                assert default is None
