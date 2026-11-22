# SPDX-License-Identifier: GPL-3.0-only
"""M-4c 导出接线测试：`MainWindow._export_field_metadata` 按该文件已存
`_standard` 传 profile，并以已存元数据为底（修「硬编码 Title 忽略已存字段」）。

范式照 F-1035b（qapp + monkeypatch `QFileDialog.getSaveFileName` + 真 wav）：
① 无 `_standard`（open_file 后条目无该键）→ 导出 JSON == 扁平（无 "profile" 键）
② 条目 `metadata["_standard"] = "DAT63"` → JSON profile=DAT63；XML 根标签 DA_T63
③ 条目 `metadata["_standard"] = "IMDI"` → JSON profile=IMDI
④ 已存 Title/Creator → 导出值 == 已存（「已存为底」首证）；无存 → Title 兜底
"""

from __future__ import annotations

import csv
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")


def _write_wav(path, sample_rate: int = 8000, seconds: float = 0.25) -> None:
    """写 PCM_16 单声道 wav（soundfile；合成可复现，同 F-1035b 范式）。"""
    import numpy as np
    import soundfile as sf

    t = np.arange(int(sample_rate * seconds)) / float(sample_rate)
    sf.write(
        str(path),
        (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype("float32"),
        sample_rate,
    )


def _toasts(monkeypatch) -> list:
    """截获 show_toast（不弹真 toast），返回 [(level, message), ...]。"""
    import acouscope.ui.main_window as mw_mod

    toasts: list = []
    monkeypatch.setattr(
        mw_mod,
        "show_toast",
        lambda parent, message, level="info", **kw: toasts.append(
            (level, str(message))
        ),
    )
    return toasts


def _export_to(win, out, monkeypatch) -> None:
    """mock 保存框指向 out 后直调导出方法。"""
    from PyQt6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, __out=out, **kw: (str(__out), "")),
    )
    win._export_field_metadata()


class TestExportProfileWiring:
    """profile 按已存 _standard 传 + 已存元数据为底（M-4c）。"""

    def test_no_standard_flat_json(self, qapp, tmp_path, monkeypatch):
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "take.wav"
        _write_wav(wav)
        toasts = _toasts(monkeypatch)

        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            out = tmp_path / "field_metadata.json"
            _export_to(win, out, monkeypatch)
            assert [lv for lv, _ in toasts] == ["success"], toasts
            data = json.loads(out.read_text(encoding="utf-8"))
            # open_file 不入档 → 无 _standard → custom 扁平 JSON（无 profile 键）
            assert "profile" not in data
            # 无已存 → Title 兜底保留
            assert data["Title"] == "AcouScope 田野录音"
        finally:
            win.close()

    def test_dat63_standard_lands(self, qapp, tmp_path, monkeypatch):
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "take.wav"
        _write_wav(wav)
        toasts = _toasts(monkeypatch)

        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            pf = win.controller.project.add_file(str(wav), label=wav.name)
            pf.metadata["_standard"] = "DAT63"
            out = tmp_path / "field_metadata.json"
            _export_to(win, out, monkeypatch)
            data = json.loads(out.read_text(encoding="utf-8"))
            assert data["profile"] == "DAT63"

            out_xml = tmp_path / "field_metadata.xml"
            _export_to(win, out_xml, monkeypatch)
            assert ET.parse(out_xml).getroot().tag == "DA_T63"
        finally:
            win.close()

    def test_imdi_standard_lands(self, qapp, tmp_path, monkeypatch):
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "take.wav"
        _write_wav(wav)
        toasts = _toasts(monkeypatch)

        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            pf = win.controller.project.add_file(str(wav), label=wav.name)
            pf.metadata["_standard"] = "IMDI"
            out = tmp_path / "field_metadata.json"
            _export_to(win, out, monkeypatch)
            data = json.loads(out.read_text(encoding="utf-8"))
            assert data["profile"] == "IMDI"
        finally:
            win.close()

    def test_stored_values_are_base(self, qapp, tmp_path, monkeypatch):
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "take.wav"
        _write_wav(wav)
        toasts = _toasts(monkeypatch)

        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            pf = win.controller.project.add_file(str(wav), label=wav.name)
            pf.metadata["Title"] = "已存题名"
            pf.metadata["Creator"] = "已存责任者"
            out = tmp_path / "field_metadata.json"
            _export_to(win, out, monkeypatch)
            data = json.loads(out.read_text(encoding="utf-8"))
            # 已存为底：导出值 == 已存（不再被硬编码 Title 覆盖）
            assert data["Title"] == "已存题名"
            assert data["Creator"] == "已存责任者"
        finally:
            win.close()

    def test_dat63_profile_carries_m8a_autofour(self, qapp, tmp_path, monkeypatch):
        """M-8a 例⑤：真 wav 走 DAT63 profile，四自动值逐项在案（code/value 双真身）。"""
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "m8a_take.wav"
        _write_wav(wav)
        toasts = _toasts(monkeypatch)

        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            pf = win.controller.project.add_file(str(wav), label=wav.name)
            pf.metadata["_standard"] = "DAT63"
            out = tmp_path / "field_metadata.csv"
            _export_to(win, out, monkeypatch)
            assert [lv for lv, _ in toasts] == ["success"], toasts

            with open(out, encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            by_field = {r[0]: r for r in rows[1:]}
            assert by_field["FileName"][1] == "M46"          # code 真身
            assert by_field["FileName"][4] == wav.name       # value == 名.扩展名
            assert by_field["FileSize"][1] == "M47"
            assert by_field["FileSize"][4] == str(os.path.getsize(str(wav)))  # 十进制串
            assert by_field["AggregationLevel"][4] == "件"
            assert by_field["RetentionPeriod"][4] == "永久"
        finally:
            win.close()

    def test_imdi_profile_m8a_size_and_filename_pass_xsd(self, qapp, tmp_path, monkeypatch):
        """M-8a 例⑥：同件走 IMDI profile——MediaFile/Size 真身、FileName 落 Keys，过官方 XSD。"""
        pytest.importorskip("lxml")
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "m8a_imdi.wav"
        _write_wav(wav)
        toasts = _toasts(monkeypatch)

        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            pf = win.controller.project.add_file(str(wav), label=wav.name)
            pf.metadata["_standard"] = "IMDI"
            out_xml = tmp_path / "field_metadata.xml"
            _export_to(win, out_xml, monkeypatch)
            assert [lv for lv, _ in toasts] == ["success"], toasts

            lxml = pytest.importorskip("lxml")
            from lxml import etree
            tree = etree.parse(str(out_xml))
            ns = {"i": "http://www.mpi.nl/IMDI/Schema/IMDI"}
            sizes = tree.findall(".//i:Size", ns)
            assert sizes and sizes[0].text == str(os.path.getsize(str(wav)))
            fname = [
                k for k in tree.findall(".//i:Key", ns)
                if k.get("Name") == "FileName"
            ]
            assert fname and fname[0].text == wav.name
            schema = etree.XMLSchema(etree.parse(
                str(Path(__file__).resolve().parents[2]
                    / "02_References" / "IMDI_3.0.22_schema.xsd")))
            assert schema.validate(tree) is True, schema.error_log
        finally:
            win.close()
