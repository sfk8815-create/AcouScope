# SPDX-License-Identifier: GPL-3.0-only
"""M-5b 导出接线测试：WAV 导出即自动嵌 bext/INFO/iXML（裁 A）。

范式照 F-1035b（qapp + monkeypatch `QFileDialog.getSaveFileName` + 真 wav）：
① test_wav_export_embeds_bwf —— 导出 wav → 嵌三块（CodingHistory/ISFT），
   wave 读回帧数 == 控制器音频长度。
② test_stored_metadata_lands —— 已存 Title(ASCII)/Creator(中文) →
   bext.Description 落、Originator 空（中文拒）、iXML vendor 树 Creator 全值。
③ test_unregistered_file_fallback —— 未注册文件导出 → 仍嵌三块（兜底 PROJECT）。
"""
from __future__ import annotations

import wave
import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("PyQt6")


def _write_wav(path, sample_rate: int = 8000, seconds: float = 0.25) -> None:
    """写 PCM_16 单声道 wav（soundfile；同 F-1035b 范式）。"""
    import numpy as np
    import soundfile as sf

    t = np.arange(int(sample_rate * seconds)) / float(sample_rate)
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype("float32"),
             sample_rate)


def _export_wav(win, out, monkeypatch) -> None:
    """mock 保存框指向 out（WAV / BWF 过滤器）后直调音频导出。"""
    from PyQt6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, __out=out, **kw:
                     (str(__out), "WAV / BWF 音频 (*.wav)")),
    )
    win._on_export_audio()


class TestBwfWiring:
    """WAV 导出自动嵌 BWF（裁 A）。"""

    def test_wav_export_embeds_bwf(self, qapp, tmp_path, monkeypatch):
        from acouscope.app.controller import AppController
        from acouscope.audio import bwf
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "take.wav"
        _write_wav(wav)
        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            out = tmp_path / "out.wav"
            _export_wav(win, out, monkeypatch)
            r = bwf.read_bwf(out)
            assert r["bext"] is not None
            assert "A=PCM" in r["bext"]["CodingHistory"]
            assert r["info"]["ISFT"] == "AcouScope"
            with wave.open(str(out), "rb") as wf:
                assert wf.getnframes() == len(win.controller.audio_data)
        finally:
            win.close()

    def test_stored_metadata_lands(self, qapp, tmp_path, monkeypatch):
        from acouscope.app.controller import AppController
        from acouscope.audio import bwf
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "take.wav"
        _write_wav(wav)
        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            pf = win.controller.project.add_file(str(wav), label=wav.name)
            pf.metadata["Title"] = "Field Take 02"
            pf.metadata["Creator"] = "李四"
            out = tmp_path / "out.wav"
            _export_wav(win, out, monkeypatch)
            r = bwf.read_bwf(out)
            assert r["bext"]["Description"] == "Field Take 02"
            assert r["bext"]["Originator"] == ""      # 中文被拒
            assert bwf.parse_vendor_tree(r["ixml_raw"])["Creator"] == "李四"
        finally:
            win.close()

    def test_unregistered_file_fallback(self, qapp, tmp_path, monkeypatch):
        from acouscope.app.controller import AppController
        from acouscope.audio import bwf
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "take.wav"
        _write_wav(wav)
        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))       # 未 add_file（未注册）
            out = tmp_path / "out.wav"
            _export_wav(win, out, monkeypatch)
            r = bwf.read_bwf(out)
            assert "A=PCM" in r["bext"]["CodingHistory"]
            assert r["info"]["ISFT"] == "AcouScope"
            assert ET.fromstring(r["ixml_raw"]).findtext("PROJECT") \
                == "AcouScope 田野录音"
        finally:
            win.close()
