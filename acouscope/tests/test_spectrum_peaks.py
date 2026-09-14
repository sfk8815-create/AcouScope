# SPDX-License-Identifier: GPL-3.0-only
"""CB-001 #11 守卫测试：频谱「找峰值」去模态（内联 QDialog → toast）。

两层守卫：
① 源码扫描：spectrum.py 零 QDialog 字面量、零 dlg.exec（防回退）
② 行为用例：_on_find_peaks 走 show_toast(level="info")，不构造任何模态
"""

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPECTRUM_SRC = _REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "spectrum.py"


def _synthetic_spectrum(sr: int = 16000, n: int = 4096):
    """440 Hz + 880 Hz 合成频谱（保证能检出多个峰值）。"""
    t = np.arange(n) / sr
    sig = np.sin(2 * np.pi * 440 * t) + 0.6 * np.sin(2 * np.pi * 880 * t)
    spec = np.abs(np.fft.rfft(sig)) / n
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    return freqs, spec


class TestFindPeaksDeModalized:
    """① 源码层：去模态化防回退（无需 qapp）。"""

    def test_source_has_no_modal_construct(self):
        src = _SPECTRUM_SRC.read_text(encoding="utf-8")
        assert "QDialog" not in src, "spectrum.py 出现 QDialog 字面量（回退）"
        assert "dlg.exec" not in src, "spectrum.py 出现 dlg.exec（回退）"

    def test_source_uses_toast(self):
        src = _SPECTRUM_SRC.read_text(encoding="utf-8")
        assert "show_toast(" in src


class TestFindPeaksToastBehavior:
    """② 行为层：找峰值以非模态 toast 反馈（离屏，不 show()）。"""

    def test_find_peaks_emits_toast(self, qapp, monkeypatch):
        import acouscope.ui.widgets.spectrum as spectrum_mod
        from acouscope.ui.widgets.spectrum import SpectrumWidget

        calls = []
        monkeypatch.setattr(
            spectrum_mod,
            "show_toast",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        freqs, spec = _synthetic_spectrum()
        w = SpectrumWidget()
        try:
            w.set_data(freqs, spec, title="test", sample_rate=16000)
            w._on_find_peaks()
        finally:
            w.close()

        assert len(calls) == 1, f"期望 1 次 toast，实际 {len(calls)}"
        args, kwargs = calls[0]
        assert kwargs.get("level") == "info"
        # show_toast(parent, message, level="info")：消息为第 2 个位置参数
        msg = args[1] if len(args) > 1 else kwargs.get("message", "")
        assert "峰值" in msg


class TestPeakMarksPanel:
    """CB-002 F-3：峰值标记内嵌面板（非模态 QWidget）行为守卫。"""

    @staticmethod
    def _widget_with_peaks(qapp):
        from acouscope.ui.widgets.spectrum import SpectrumWidget

        freqs, spec = _synthetic_spectrum()
        w = SpectrumWidget()
        w.set_data(freqs, spec, title="test", sample_rate=16000)
        w._on_find_peaks()
        return w

    def test_panel_opens_with_detected_peaks(self, qapp):
        w = self._widget_with_peaks(qapp)
        try:
            assert len(w._last_peaks) >= 1
            # 勾选工具栏「标记面板」→ 内嵌面板可见且行数 = 检测数
            w.btn_peaks_panel.setChecked(True)
            assert w._peaks_panel.isVisible()
            assert w._peaks_panel.table.rowCount() == len(w._last_peaks)
        finally:
            w.close()

    def test_panel_mark_selected_increments(self, qapp):
        from PyQt6.QtWidgets import QTableWidgetSelectionRange

        w = self._widget_with_peaks(qapp)
        try:
            w.btn_peaks_panel.setChecked(True)
            w._clear_all_marks()  # set_data 默认标基频，先清空以隔离断言
            n = min(2, w._peaks_panel.table.rowCount())
            assert n >= 1
            rng = QTableWidgetSelectionRange(0, 0, n - 1, 4)
            w._peaks_panel.table.setRangeSelected(rng, True)
            before = len(w._manual_peaks)
            w._peaks_panel.btn_mark.click()
            assert len(w._manual_peaks) == before + n
            # 已标记态刷新
            assert w._peaks_panel.table.item(0, 4).text() == "✓"
        finally:
            w.close()

    def test_panel_unmark_selected_decrements(self, qapp):
        from PyQt6.QtWidgets import QTableWidgetSelectionRange

        w = self._widget_with_peaks(qapp)
        try:
            w.btn_peaks_panel.setChecked(True)
            w._clear_all_marks()
            n = min(2, w._peaks_panel.table.rowCount())
            assert n >= 1
            rng = QTableWidgetSelectionRange(0, 0, n - 1, 4)
            w._peaks_panel.table.setRangeSelected(rng, True)
            w._peaks_panel.btn_mark.click()
            assert len(w._manual_peaks) == n
            # 选中并取消
            w._peaks_panel.table.setRangeSelected(rng, True)
            w._peaks_panel.btn_unmark.click()
            assert len(w._manual_peaks) == 0
        finally:
            w.close()
