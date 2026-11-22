# SPDX-License-Identifier: GPL-3.0-only
"""T-1035b：`_export_field_metadata` 三格式导出的守卫测试。

修复前（实测四层，三个格式 100% 失败、零落盘）：
  ⓪ 守卫 `hasattr(self, "_current_audio_path")` 恒真 —— 该属性全仓无任何赋值点
     → 即使已加载音频也只弹「请先加载音频文件」warning，三格式全不可达；
  ① 从 `acouscope.analysis.annotation` 导入（该模块不存在 → ModuleNotFoundError）；
  ② `SessionMetadata` 以 7 个不存在的关键字构造（真实为单字段 `values`）；
  ③ 三个分支调用 `to_dict()` / `to_imdi_xml()` / `to_csv()` —— 三者皆不存在。

修复后落点（审计定案）：文件写手统一在 `annotation/export.py`
（新增 `export_session_json` / `export_session_csv` + 复用既有 `export_session_xml`），
`SessionMetadata` 只加 `to_dict()`，UI 仅改 `_export_field_metadata` 方法体。
"""

import csv
import json

from acouscope.annotation import export
from acouscope.annotation.metadata import FIELD_TERMS, SessionMetadata

FIELD_KEYS = [t.key for t in FIELD_TERMS]


def _meta() -> SessionMetadata:
    """标准字段样例（不含自定义键）→ CSV 表头应 == FIELD_KEYS 逐字逐序。"""
    m = SessionMetadata()
    m.set("Identifier", "/field/AC-2026-001.wav")
    m.set("Title", "AcouScope 田野录音")
    m.set("SamplingRate", 44100)
    m.set("BitDepth", 16)
    m.set("Format", "WAV")
    m.set("Channels", 1)
    m.set("Duration", 12.5)
    return m


def _read_rows(path) -> list[list[str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


class TestThreeFormats:
    """① 三格式各自生成非空文件。"""

    def test_all_three_formats_write_nonempty_files(self, tmp_path):
        meta = _meta()
        for name, writer in (
            ("out.json", export.export_session_json),
            ("out.xml", export.export_session_xml),
            ("out.csv", export.export_session_csv),
        ):
            p = tmp_path / name
            writer(p, meta)
            assert p.exists(), name
            assert p.stat().st_size > 0, name


class TestCsvHeader:
    """② CSV 表头 == FIELD_TERMS 的 key 列表（逐字逐序）。"""

    def test_header_equals_field_terms_keys_in_order(self, tmp_path):
        p = tmp_path / "header.csv"
        export.export_session_csv(p, _meta())
        rows = _read_rows(p)
        assert rows[0] == FIELD_KEYS
        assert len(FIELD_KEYS) == 16  # FIELD_TERMS 标准键数（M-8a 起含 DA/T 四项自动/预设，12→16）

    def test_custom_keys_appended_after_standard_keys(self, tmp_path):
        """未入 FIELD_TERMS 的自定义键追加在标准键之后（插入序，稳定）。"""
        meta = _meta()
        meta.set("Note", "村口老槐树下")
        meta.set("TapeNo", "A-07")
        p = tmp_path / "custom.csv"
        export.export_session_csv(p, meta)
        rows = _read_rows(p)
        assert rows[0] == FIELD_KEYS + ["Note", "TapeNo"]
        assert dict(zip(rows[0], rows[1]))["Note"] == "村口老槐树下"
        assert dict(zip(rows[0], rows[1]))["Identifier"] == "/field/AC-2026-001.wav"


class TestBareMetadata:
    """③ 空/缺字段元数据（裸对象）三格式均不崩。"""

    def test_bare_metadata_all_three_formats(self, tmp_path):
        meta = SessionMetadata()
        j, x, c = tmp_path / "bare.json", tmp_path / "bare.xml", tmp_path / "bare.csv"
        export.export_session_json(j, meta)
        export.export_session_xml(x, meta)
        export.export_session_csv(c, meta)
        for p in (j, x, c):
            assert p.exists() and p.stat().st_size > 0, p.name
        assert _read_rows(c)[0] == FIELD_KEYS
        assert _read_rows(c)[1] == [""] * len(FIELD_KEYS)
        assert json.loads(j.read_text(encoding="utf-8")) == {k: "" for k in FIELD_KEYS}


class TestRoundTrip:
    """④⑤ 回读口径与 to_dict() / to_imdi_session() 一致。"""

    @staticmethod
    def _flatten(obj: dict, prefix: str = "") -> dict:
        """与既有 test_export_formats.TestXmlExport._flatten 同口径（含 Keys/Key 列表）。"""
        out = {}
        for k, v in obj.items():
            if k.startswith("@") or k == "#text":
                continue
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict) and "@Name" in item:
                        q = f"{p}.{item['@Name']}"
                        if "#text" in item:
                            out[q] = str(item["#text"])
                    elif isinstance(item, dict):
                        out.update(TestRoundTrip._flatten(item, p))
            elif isinstance(v, dict):
                out.update(TestRoundTrip._flatten(v, p))
            else:
                out[p] = str(v)
        return out

    def test_json_content_equals_to_dict(self, tmp_path):
        meta = _meta()
        meta.set("Note", "自定义字段应无损保留")
        p = tmp_path / "meta.json"
        export.export_session_json(p, meta)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data == meta.to_dict()
        assert list(data.keys()) == FIELD_KEYS + ["Note"]
        assert data["Note"] == "自定义字段应无损保留"

    def test_xml_readback_matches_to_imdi(self, tmp_path):
        meta = _meta()
        meta.set("Note", "自定义字段应无损保留")  # → Session/MDGroup/Keys/Key（保证非空）
        p = tmp_path / "session.xml"
        export.export_session_xml(p, meta)
        leaves = export.load_session_xml(p)
        assert leaves == self._flatten(meta.to_imdi_session())
        assert leaves["Session.Name"] == "/field/AC-2026-001.wav"  # Identifier〔XSD:771〕
        assert leaves["Session.Resources.MediaFile.Keys.Key.SamplingRate"] == "44100"
        assert leaves["Session.MDGroup.Keys.Key.Note"] == "自定义字段应无损保留"


class TestMainWindowEndToEnd:
    """⑥ 端到端：直调 `MainWindow._export_field_metadata`（mock 保存框 + toast）。"""

    @staticmethod
    def _write_wav(path, sample_rate: int = 8000, seconds: float = 0.25) -> None:
        import numpy as np
        import soundfile as sf

        t = np.arange(int(sample_rate * seconds)) / float(sample_rate)
        sf.write(
            str(path),
            (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype("float32"),
            sample_rate,
        )

    @staticmethod
    def _toasts(monkeypatch) -> list:
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

    def test_three_formats_export_through_main_window(self, qapp, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog

        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        wav = tmp_path / "field_take.wav"
        self._write_wav(wav)
        toasts = self._toasts(monkeypatch)

        win = MainWindow(AppController())
        try:
            win.controller.open_file(str(wav))
            for ext in ("json", "xml", "csv"):
                out = tmp_path / f"field_metadata.{ext}"
                monkeypatch.setattr(
                    QFileDialog,
                    "getSaveFileName",
                    staticmethod(lambda *a, __out=out, **kw: (str(__out), "")),
                )
                win._export_field_metadata()
                assert out.exists() and out.stat().st_size > 0, (ext, toasts)
            assert [lv for lv, _ in toasts] == ["success", "success", "success"], toasts
        finally:
            win.close()

    def test_export_without_audio_warns_and_writes_nothing(
        self, qapp, tmp_path, monkeypatch
    ):
        """更正后的守卫：无音频 → warning 且零落盘（原守卫恒触发，属断链层 ⓪）。"""
        from PyQt6.QtWidgets import QFileDialog

        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        toasts = self._toasts(monkeypatch)
        out = tmp_path / "should_not_exist.json"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **kw: (str(out), "")),
        )
        win = MainWindow(AppController())
        try:
            win._export_field_metadata()
            assert [lv for lv, _ in toasts] == ["warning"], toasts
            assert not out.exists()
        finally:
            win.close()
