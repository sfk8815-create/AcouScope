# SPDX-License-Identifier: GPL-3.0-only
"""图表字体可选功能测试（西文/中文字体分开设置）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest

pytest.importorskip("matplotlib")


class TestFontDiscovery:
    def test_latin_cjk_lists_disjoint_and_typed(self):
        from acouscope.visualization.mpl_style import (
            _CJK_NAME_RE,
            list_cjk_fonts,
            list_latin_fonts,
        )

        latin = list_latin_fonts()
        cjk = list_cjk_fonts()
        assert latin and cjk
        # 西文列表不应混入 CJK 字体
        assert not any(_CJK_NAME_RE.search(f) for f in latin)
        # 中文列表全部为 CJK 特征字体或推荐中文字体
        from acouscope.visualization.mpl_style import RECOMMENDED_CJK_FONTS

        for f in cjk:
            assert _CJK_NAME_RE.search(f) or f in RECOMMENDED_CJK_FONTS


class TestFontChain:
    def test_auto_keeps_language_chain(self):
        from acouscope.visualization.mpl_style import get_academic_style

        s_auto = get_academic_style("default", "zh_CN",
                                    font_latin="auto", font_cjk="auto")
        s_default = get_academic_style("default", "zh_CN")
        assert s_auto["font_family"] == s_default["font_family"]

    def test_latin_leads_chain(self):
        from acouscope.visualization.mpl_style import get_academic_style

        style = get_academic_style("default", "zh_CN", font_latin="Times New Roman")
        assert style["font_family"][0] == "Times New Roman"
        # 链尾保留 sans-serif 兜底
        assert style["font_family"][-1] == "sans-serif"

    def test_latin_only_includes_cjk_fallback(self):
        from acouscope.visualization.mpl_style import get_academic_style

        chain = get_academic_style("default", "zh_CN",
                                   font_latin="Times New Roman")["font_family"]
        assert chain[0] == "Times New Roman"
        assert len(chain) >= 2

    def test_cjk_only_keeps_default_latin_first(self):
        from acouscope.visualization.mpl_style import font_chain

        chain = font_chain("auto", "Songti SC")
        assert chain[0] == "Times New Roman"  # 数字/英文仍用西文
        assert "Songti SC" in chain

    def test_both_specified(self):
        from acouscope.visualization.mpl_style import font_chain

        chain = font_chain("Arial", "PingFang SC")
        assert chain[0] == "Arial"
        assert chain[1] == "PingFang SC"
        assert chain[-1] == "sans-serif"
        # 无重复
        assert len(chain) == len(set(chain))


class TestExporterFont:
    def test_font_attributes(self):
        from acouscope.visualization.exporters import FigureExporter

        e = FigureExporter(font_latin="Arial", font_cjk="Songti SC")
        assert e.font_latin == "Arial"
        assert e.font_cjk == "Songti SC"
        assert FigureExporter().font_latin == "auto"
        assert FigureExporter(font_latin=None).font_latin == "auto"
        assert FigureExporter(font_cjk="").font_cjk == "auto"

    def test_export_with_font(self, tmp_path):
        from acouscope.visualization.exporters import FigureExporter

        times = np.linspace(0, 1, 500)
        sig = np.sin(2 * np.pi * 440 * times)
        out = tmp_path / "wave.svg"
        exporter = FigureExporter(font_latin="Times New Roman")
        saved = exporter.export_waveform(times, sig, out, fmt="svg")
        assert Path(saved).exists()

    def test_font_applied_to_artists(self):
        import matplotlib

        matplotlib.use("Agg")
        from acouscope.visualization.mpl_style import create_figure
        import matplotlib.pyplot as plt

        fig, ax = create_figure("default", "zh_CN", font_latin="Times New Roman")
        assert ax.title.get_fontfamily()[0] == "Times New Roman"
        assert ax.xaxis.label.get_fontfamily()[0] == "Times New Roman"
        plt.close(fig)

    def test_different_fonts_render_differently(self, tmp_path):
        from PIL import Image

        from acouscope.visualization.exporters import FigureExporter

        times = np.linspace(0, 1, 500)
        sig = np.sin(2 * np.pi * 440 * times)

        def size(latin, name):
            p = tmp_path / name
            FigureExporter(font_latin=latin).export_waveform(
                times, sig, p, fmt="png", dpi=100
            )
            return Image.open(p).size

        assert size("Times New Roman", "a.png") != size("Courier New", "b.png")


class TestSettingsFont:
    def test_default_chart_fonts(self):
        from acouscope.utils.config import Settings

        assert Settings().chart_font_latin == "auto"
        assert Settings().chart_font_cjk == "auto"

    def test_save_load_roundtrip(self, tmp_path):
        from acouscope.utils.config import Settings

        path = tmp_path / "settings.json"
        s = Settings()
        s.chart_font_latin = "Times New Roman"
        s.chart_font_cjk = "Songti SC"
        s.save(path)
        loaded = Settings.load(path)
        assert loaded.chart_font_latin == "Times New Roman"
        assert loaded.chart_font_cjk == "Songti SC"

    def test_legacy_chart_font_migrates_to_latin(self, tmp_path):
        import json

        from acouscope.utils.config import Settings

        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"chart_font": "Arial"}), encoding="utf-8")
        loaded = Settings.load(path)
        assert loaded.chart_font_latin == "Arial"


class TestChartFontDialog:
    @pytest.fixture(scope="class")
    def qapp(self):
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def test_dialog_two_combos(self, qapp):
        from acouscope.ui.widgets.chart_font_dialog import ChartFontDialog

        dlg = ChartFontDialog(latin="auto", cjk="auto")
        try:
            assert dlg.cmb_latin.count() >= 2
            assert dlg.cmb_cjk.count() >= 2
            assert dlg.latin() == "auto"
            assert dlg.cjk() == "auto"
        finally:
            dlg.close()

    def test_dialog_restores_values(self, qapp):
        from acouscope.ui.widgets.chart_font_dialog import ChartFontDialog

        dlg = ChartFontDialog(latin="Times New Roman", cjk="auto")
        try:
            assert dlg.latin() == "Times New Roman"
        finally:
            dlg.close()


class TestSpectrogram3DFont:
    @pytest.fixture(scope="class")
    def qapp(self):
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def test_font_button_exists(self, qapp):
        from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

        w = Spectrogram3DWidget()
        try:
            assert w.btn_font is not None
            assert w.btn_font.text().startswith("字体")
        finally:
            w.close()

    def test_set_chart_font_applies_chain(self, qapp):
        from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

        w = Spectrogram3DWidget()
        try:
            sr = 8000
            t = np.arange(sr * 2) / sr
            w.set_audio(np.sin(2 * np.pi * 220 * t), sr)
            w.set_chart_font("Times New Roman", "auto")
            assert w._chart_font_latin == "Times New Roman"
            chain = w.ax_3d.title.get_fontfamily()
            assert chain[0] == "Times New Roman"
            w.set_chart_font("auto", "auto")
            assert w._chart_font_latin == "auto"
            assert w._chart_font_cjk == "auto"
        finally:
            w.close()


class TestChartFontDrawer:
    """CB-001 #10：图表字体去模态——QWidget + 抽屉承载 + fontChanged 即时生效。"""

    _SRC_DIR = Path(__file__).parent.parent / "src" / "acouscope" / "ui"
    _PANEL_SRC = _SRC_DIR / "widgets" / "chart_font_dialog.py"
    _MW_SRC = _SRC_DIR / "main_window.py"
    _S3D_SRC = _SRC_DIR / "widgets" / "spectrogram3d.py"

    def test_is_qwidget_not_qdialog(self, qapp):
        from PyQt6.QtWidgets import QDialog, QWidget

        from acouscope.ui.widgets.chart_font_dialog import ChartFontDialog

        assert issubclass(ChartFontDialog, QWidget)
        assert not issubclass(ChartFontDialog, QDialog)

    def test_source_has_no_modal(self):
        src = self._PANEL_SRC.read_text(encoding="utf-8")
        assert "QDialog" not in src, "面板出现 QDialog 字面量（回退）"
        assert ".exec(" not in src, "面板出现 .exec(（回退）"

    def test_font_changed_signal_on_select(self, qapp):
        from acouscope.ui.widgets.chart_font_dialog import ChartFontDialog

        panel = ChartFontDialog(latin="auto", cjk="auto")
        try:
            got = []
            panel.fontChanged.connect(lambda latin, cjk: got.append((latin, cjk)))
            idx = panel.cmb_latin.findData("Times New Roman")
            if idx < 0:
                pytest.skip("当前环境无 Times New Roman 字体")
            panel.cmb_latin.setCurrentIndex(idx)
            assert got, "选择变化未发出 fontChanged"
            assert got[-1] == ("Times New Roman", "auto")
        finally:
            panel.close()

    def test_construction_does_not_emit(self, qapp):
        from acouscope.ui.widgets.chart_font_dialog import ChartFontDialog

        panel = ChartFontDialog(latin="auto", cjk="auto")
        try:
            got = []
            panel.fontChanged.connect(lambda latin, cjk: got.append((latin, cjk)))
            assert got == [], "初值装载期不应触发 fontChanged"
            assert panel.latin() == "auto"
            assert panel.cjk() == "auto"
        finally:
            panel.close()

    @staticmethod
    def _func_body(src: str, name: str) -> str:
        start = src.index(f"def {name}(")
        nxt = src.find("\n    def ", start + 1)
        return src[start: nxt if nxt > 0 else len(src)]

    def test_callers_route_to_non_modal_host_without_exec(self):
        """T-1054 批2 单宿主：图表字体入口走非模态宿主（右栏页 / 3D 信号），禁 exec。"""
        body = self._func_body(self._MW_SRC.read_text(encoding="utf-8"),
                               "_on_chart_font_settings")
        assert "_on_right_page_toggled" in body
        assert "exec()" not in body

        body3 = self._func_body(self._S3D_SRC.read_text(encoding="utf-8"),
                                "_on_font_button")
        assert "chartFontRequested" in body3
        assert ".exec(" not in body3
