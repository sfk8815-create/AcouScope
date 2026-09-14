# SPDX-License-Identifier: GPL-3.0-only
"""回归测试：依赖陷阱修复、短信号防护、后端模块。

覆盖 2026-08-28 全面审计后修复的问题：
- 频谱特征（质心/带宽/滚降）纯 numpy 实现
- FilterBank 纯 numpy 重写
- STFT 时间轴对齐
- 短信号防护
- ProjectManager / FigureExporter / Preferences 后端
"""

import numpy as np
import pytest


SR = 44100


def _sine(freq: float, duration: float = 1.0, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * duration)) / sr
    return np.sin(2 * np.pi * freq * t)


# ----------------------------------------------------------------------
# 频谱特征（原 librosa 路径在此环境崩溃，现为纯 numpy）
# ----------------------------------------------------------------------


class TestSpectralFeatures:
    @pytest.fixture
    def analyzer(self):
        from acouscope.analysis.spectral import SpectralAnalyzer
        return SpectralAnalyzer(SR)

    def test_centroid_single_tone(self, analyzer):
        times, centroid = analyzer.spectral_centroid(_sine(440))
        # FFT bin 分辨率 21.5Hz，容差放宽
        assert abs(np.mean(centroid) - 440) < 30

    def test_centroid_two_tones(self, analyzer):
        sig = _sine(440) + _sine(5000)
        _, centroid = analyzer.spectral_centroid(sig)
        assert abs(np.mean(centroid) - 2720) < 100

    def test_bandwidth_two_tones(self, analyzer):
        sig = _sine(440) + _sine(5000)
        _, bw = analyzer.spectral_bandwidth(sig)
        # 等幅双音的加权标准差 ≈ 2280
        assert abs(np.mean(bw) - 2280) < 150

    def test_rolloff_two_tones(self, analyzer):
        sig = _sine(440) + _sine(5000)
        _, ro = analyzer.spectral_rolloff(sig)
        assert abs(np.mean(ro) - 5000) < 100

    def test_rolloff_silence(self, analyzer):
        _, ro = analyzer.spectral_rolloff(np.zeros(SR))
        assert np.all(np.isfinite(ro))


# ----------------------------------------------------------------------
# 音色特征（原 librosa 路径已移除）
# ----------------------------------------------------------------------


class TestTimbreFeatures:
    @pytest.fixture
    def analyzer(self):
        from acouscope.analysis.timbre import TimbreAnalyzer
        return TimbreAnalyzer(SR)

    def test_mfcc_shape(self, analyzer):
        times, mfcc = analyzer.mfcc(_sine(440), n_mfcc=13)
        assert mfcc.shape[1] == 13
        assert mfcc.shape[0] == len(times)
        assert np.all(np.isfinite(mfcc))

    def test_hnr_tone_vs_noise(self, analyzer):
        rng = np.random.default_rng(42)
        noise = rng.normal(0, 0.5, SR)
        _, hnr_tone = analyzer.hnr(_sine(440))
        _, hnr_noise = analyzer.hnr(noise)
        # 纯音 HNR 显著高于白噪声
        assert np.mean(hnr_tone) - np.mean(hnr_noise) > 10

    def test_spectral_features_complete(self, analyzer):
        features = analyzer.spectral_features(_sine(440))
        for key in ("spectral_centroid", "spectral_bandwidth",
                    "spectral_rolloff", "spectral_flatness"):
            assert key in features, f"缺少特征: {key}"
            assert np.all(np.isfinite(features[key]))


# ----------------------------------------------------------------------
# STFT 时间轴（修复了 -n_fft/2 偏移 bug）
# ----------------------------------------------------------------------


class TestSTFTTimeAxis:
    def test_impulse_position(self):
        from acouscope.dsp.stft import STFTEngine
        sr = SR
        sig = np.zeros(sr * 2)
        sig[sr] = 1.0  # t=1.0s 处脉冲
        eng = STFTEngine(n_fft=2048, hop_length=512, center=True)
        freqs, times, S = eng.compute(sig, sr)
        peak_frame = int(np.argmax(np.abs(S).sum(axis=0)))
        assert abs(times[peak_frame] - 1.0) < 2 * 512 / sr

    def test_time_axis_starts_at_zero(self):
        from acouscope.dsp.stft import STFTEngine
        eng = STFTEngine(n_fft=2048, hop_length=512, center=True)
        _, times, _ = eng.compute(np.zeros(SR), SR)
        assert times[0] == pytest.approx(0.0)

    def test_frame_count_librosa_convention(self):
        from acouscope.dsp.stft import STFTEngine
        eng = STFTEngine(n_fft=2048, hop_length=512, center=True)
        _, _, S = eng.compute(np.zeros(SR), SR)
        assert S.shape[1] == 1 + SR // 512


# ----------------------------------------------------------------------
# 短信号防护（返回空数组而非崩溃）
# ----------------------------------------------------------------------


class TestShortSignalGuards:
    def test_stft_short(self):
        from acouscope.dsp.stft import STFTEngine
        eng = STFTEngine(n_fft=2048, hop_length=512, center=False)
        freqs, times, S = eng.compute(np.zeros(100), SR)
        assert len(times) == 0 and S.shape[1] == 0

    def test_formants_short(self):
        from acouscope.analysis.formants import FormantAnalyzer
        analyzer = FormantAnalyzer()
        times, f, bw = analyzer.extract_lpc(np.zeros(100), SR)
        assert len(times) == 0

    def test_pitch_short(self):
        from acouscope.analysis.pitch import PitchAnalyzer
        analyzer = PitchAnalyzer()
        times, f0 = analyzer.detect_yin(np.zeros(100), SR)
        assert len(times) == 0

    def test_hnr_short(self):
        from acouscope.analysis.timbre import TimbreAnalyzer
        _, hnr = TimbreAnalyzer(SR).hnr(np.zeros(100))
        assert len(hnr) == 0

    def test_detect_pitch_peaks_mismatch(self):
        from acouscope.analysis.spectral import SpectralAnalyzer
        analyzer = SpectralAnalyzer(SR)
        # 长度不匹配的输入应返回空列表而非崩溃
        assert analyzer.detect_pitch_peaks(np.ones(5), np.arange(10)) == []


# ----------------------------------------------------------------------
# 后端模块（未接线但已验证可用，为下阶段开发保留）
# ----------------------------------------------------------------------


class TestBackendModules:
    def test_project_roundtrip(self, tmp_path):
        from acouscope.app.project import ProjectManager

        pm = ProjectManager()
        pm.new("测试")
        pm.add_file("/tmp/a.wav", label="A")
        pm.current.files[0].analysis_results = {"pitch": 440.0}

        path = tmp_path / "t.acouproj"
        pm.save(path)
        loaded = pm.load(path)
        assert loaded.name == "测试"
        assert loaded.files[0].analysis_results["pitch"] == 440.0

    def test_figure_exporter_svg(self, tmp_path):
        from acouscope.visualization.exporters import FigureExporter

        t = np.arange(SR // 10) / SR
        sig = np.sin(2 * np.pi * 440 * t)
        out = FigureExporter().export_waveform(
            t, sig, tmp_path / "w.svg", fmt="svg", title="波形"
        )
        assert out.exists() and out.stat().st_size > 100

    def test_preferences_roundtrip(self, tmp_path):
        from acouscope.utils import Settings
        from acouscope.app.preferences import Preferences

        fp = tmp_path / "s.json"
        prefs = Preferences(Settings.load(fp))
        prefs.language = "en_US"
        prefs._settings.save(fp)
        assert Preferences(Settings.load(fp)).language == "en_US"

    def test_resample_numpy_fallback(self):
        from acouscope.audio.io import AudioIO

        sig = _sine(440, duration=0.5)
        out = AudioIO._resample(sig, SR, 22050)
        assert len(out) == 11025
        spec = np.abs(np.fft.rfft(out))
        freqs = np.fft.rfftfreq(len(out), d=1.0 / 22050)
        assert abs(freqs[np.argmax(spec)] - 440) < 5


# ----------------------------------------------------------------------
# 项目管理（controller 层接线）
# ----------------------------------------------------------------------


class TestProjectManagement:
    @pytest.fixture
    def controller(self):
        from acouscope.app.controller import AppController

        return AppController()

    @pytest.fixture
    def wav_file(self, tmp_path):
        from acouscope.audio import AudioIO

        path = tmp_path / "tone.wav"
        sr = 44100
        sig = 0.5 * _sine(440, duration=0.5)
        AudioIO().save(sig, sr, str(path))
        return path

    def test_save_load_roundtrip(self, controller, wav_file, tmp_path):
        controller.open_file(wav_file)
        marks = [{"freq": 440.0, "note": "A4", "cents": 0.0, "midi": 69.0}]
        proj_path = tmp_path / "t.acouproj"

        controller.save_project(proj_path, annotations=marks)

        assert proj_path.exists()
        assert controller.project.current.name == "tone"
        assert controller.project.current.files[0].path == str(wav_file)

        project, info = controller.load_project(proj_path)
        assert info is not None
        assert project.files[0].analysis_results["harmonic_marks"] == marks

    def test_get_saved_annotations(self, controller, wav_file, tmp_path):
        assert controller.get_saved_annotations() == []

        controller.open_file(wav_file)
        assert controller.get_saved_annotations() == []

        marks = [{"freq": 440.0, "note": "A4", "cents": 0.0, "midi": 69.0}]
        controller.save_project(tmp_path / "p.acouproj", annotations=marks)
        assert controller.get_saved_annotations() == marks

    def test_save_preserves_other_files(self, controller, wav_file, tmp_path):
        # 预置多文件项目
        controller.project.add_file("/other/existing.wav", label="其他文件")
        controller.open_file(wav_file)
        controller.save_project(tmp_path / "multi.acouproj")

        project, _ = controller.load_project(tmp_path / "multi.acouproj")
        paths = [f.path for f in project.files]
        assert str(wav_file) in paths
        assert "/other/existing.wav" in paths


# ----------------------------------------------------------------------
# 新增导出器方法
# ----------------------------------------------------------------------


class TestNewExporters:
    @pytest.fixture
    def exporter(self):
        from acouscope.visualization.exporters import FigureExporter
        return FigureExporter()

    def test_export_formants(self, exporter, tmp_path):
        times = np.linspace(0, 1, 50)
        freqs = np.zeros((50, 4))
        freqs[:, 0] = np.linspace(500, 600, 50)
        freqs[:, 1] = np.linspace(1500, 1600, 50)
        out = exporter.export_formants(
            times, freqs, tmp_path / "f.svg", fmt="svg", title="共振峰"
        )
        assert out.exists() and out.stat().st_size > 100

    def test_export_mfcc(self, exporter, tmp_path):
        times = np.linspace(0, 1, 40)
        mfcc = np.random.default_rng(1).normal(size=(40, 13))
        out = exporter.export_mfcc(times, mfcc, tmp_path / "m.png", fmt="png")
        assert out.exists() and out.stat().st_size > 100

    def test_export_spectrum_with_markers(self, exporter, tmp_path):
        freqs = np.linspace(0, 5000, 512)
        mag = np.exp(-((freqs - 440) ** 2) / 1000)
        out = exporter.export_spectrum(
            freqs, mag, tmp_path / "s.svg", fmt="svg",
            markers=[(440.0, "A4"), (880.0, "A5")],
        )
        assert out.exists() and out.stat().st_size > 100
        # SVG 中应包含两个标记竖线
        content = out.read_text(encoding="utf-8")
        assert content.count("stroke-dasharray") >= 2


# ----------------------------------------------------------------------
# 谐波标记恢复（SpectrumWidget）
# ----------------------------------------------------------------------


class TestRestoreMarks:
    def test_restore_marks(self, qapp):
        from acouscope.ui.widgets.spectrum import SpectrumWidget

        widget = SpectrumWidget()
        sr = 44100
        sig = (_sine(440) + 0.5 * _sine(880) + 0.25 * _sine(1320)) * 0.8

        from acouscope.analysis import SpectralAnalyzer
        analyzer = SpectralAnalyzer(sr)
        freqs, mag = analyzer.fft_spectrum(sig, fft_size=16384, db_scale=False)

        widget.set_data(freqs, mag, db_scale=False, sample_rate=sr, signal_data=sig)

        marks = [
            {"freq": 440.0, "note": "A4", "cents": 0.0, "midi": 69.0},
            {"freq": 880.0, "note": "A5", "cents": 0.0, "midi": 81.0},
        ]
        n = widget.restore_marks(marks)
        assert n == 2
        assert len(widget._manual_peaks) >= 2

        # 恢复的标记应吸附到实际峰值（440/880 Hz 附近）
        restored_freqs = sorted(p["freq"] for p in widget._manual_peaks)
        assert abs(restored_freqs[0] - 440) < 5
        assert abs(restored_freqs[1] - 880) < 5

    def test_restore_marks_invalid_input(self, qapp):
        from acouscope.ui.widgets.spectrum import SpectrumWidget

        widget = SpectrumWidget()
        widget.set_data(
            np.linspace(0, 1000, 256), np.abs(np.random.default_rng(2).normal(size=256)),
            db_scale=False, sample_rate=44100,
        )
        # 非法标记应被跳过而非崩溃
        n = widget.restore_marks([{"freq": "bad"}, {"freq": -1}, {"note": "x"}])
        assert n == 0


# ----------------------------------------------------------------------
# HNR 向量化（数值与旧实现一致）
# ----------------------------------------------------------------------


class TestHNRVectorized:
    def test_hnr_values_match_reference(self):
        from acouscope.analysis.timbre import TimbreAnalyzer

        ta = TimbreAnalyzer(SR)
        t = np.arange(SR) / SR
        tone = np.sin(2 * np.pi * 440 * t)
        _, hnr = ta.hnr(tone)
        # 纯音帧的 HNR 应稳定为正值
        assert np.mean(hnr) == pytest.approx(12.9, abs=1.5)

    def test_hnr_silence_all_zero(self):
        from acouscope.analysis.timbre import TimbreAnalyzer

        _, hnr = TimbreAnalyzer(SR).hnr(np.zeros(SR))
        assert np.all(hnr == 0)

    def test_hnr_long_signal_fast(self):
        import time

        from acouscope.analysis.timbre import TimbreAnalyzer

        rng = np.random.default_rng(42)
        sig = np.sin(2 * np.pi * 220 * np.arange(SR * 30) / SR) * 0.5
        sig += rng.normal(0, 0.01, SR * 30)

        t0 = time.time()
        _, hnr = TimbreAnalyzer(SR).hnr(sig)
        elapsed = time.time() - t0

        assert len(hnr) == 1 + (SR * 30 - 2048) // 512
        assert elapsed < 2.0, f"30 秒音频 HNR 耗时 {elapsed:.2f}s，应向量化"


# ----------------------------------------------------------------------
# 频谱导出跟随窗口视图（修复：导出永远全频段 dB、不随窗口设置变化）
# ----------------------------------------------------------------------


def _make_spectrum_widget(qapp):
    """构造带谐波数据的频谱控件。"""
    from acouscope.ui.widgets.spectrum import SpectrumWidget
    from acouscope.analysis import SpectralAnalyzer

    widget = SpectrumWidget()
    sig = (_sine(440) + 0.5 * _sine(880) + 0.25 * _sine(1320)
           + 0.12 * _sine(1760) + 0.08 * _sine(2200) + 0.05 * _sine(2640)) * 0.8
    analyzer = SpectralAnalyzer(SR)
    freqs, mag = analyzer.fft_spectrum(sig, fft_size=16384, db_scale=False)
    widget.set_data(freqs, mag, db_scale=False, sample_rate=SR, signal_data=sig)
    return widget


class TestSpectrumExportFollowsView:
    def test_export_respects_x_unit_khz(self, qapp):
        w = _make_spectrum_widget(qapp)
        w.cmb_x_unit.setCurrentIndex(1)  # kHz
        qapp.processEvents()
        view = w.get_view_export()
        assert view["xlabel"] == "频率 (kHz)"
        assert view["xlim"][1] < 3, "kHz 单位下视图上限应远小于 3"

    def test_export_respects_y_unit_db(self, qapp):
        w = _make_spectrum_widget(qapp)
        w.cmb_y_unit.setCurrentIndex(1)  # dB
        qapp.processEvents()
        view = w.get_view_export()
        assert view["ylabel"] == "幅度 (dB)"
        assert view["y"].max() < 10, "dB 单位下幅度应为负分贝值"

    def test_export_respects_zoom_range(self, qapp):
        w = _make_spectrum_widget(qapp)
        w.plot_widget.setXRange(0, 500, padding=0)
        qapp.processEvents()
        view = w.get_view_export()
        assert view["x"][-1] <= 501, "缩放后导出数据应只含可见段"
        # 500Hz 内只有 440Hz 一个标记
        assert len(view["markers"]) == 1

    def test_export_markers_converted_to_display_unit(self, qapp):
        w = _make_spectrum_widget(qapp)
        w.cmb_x_unit.setCurrentIndex(2)  # MIDI
        qapp.processEvents()
        view = w.get_view_export()
        assert view["xlabel"] == "MIDI 音高"
        # 440Hz 标记应为 MIDI 69
        assert any(abs(mx - 69) < 0.5 for mx, _ in view["markers"])

    def test_export_full_range_default(self, qapp):
        w = _make_spectrum_widget(qapp)
        view = w.get_view_export()
        # 默认钢琴卷帘视图（坐标为 MIDI，导出与显示一致）
        assert view["xlabel"] == "MIDI 音高"
        assert view["xlim"] is not None and len(view["xlim"]) == 2
        assert view["ylim"] is not None and len(view["ylim"]) == 2

    def test_default_marks_fundamental_only(self, qapp):
        """默认只自动标记基频（最强峰），其他谐波不标记。"""
        w = _make_spectrum_widget(qapp)
        assert w._freq_unit == "piano", "默认应为钢琴卷帘视图"
        assert len(w._manual_peaks) == 1
        assert abs(w._manual_peaks[0]["freq"] - 440.0) < 2.0


# ----------------------------------------------------------------------
# 标记表无滚动条（修复：固定 140px 上限导致 6 标记出现滚动条）
# ----------------------------------------------------------------------


class TestMarksTableNoScrollbar:
    def test_six_marks_no_vertical_scrollbar(self, qapp):
        w = _make_spectrum_widget(qapp)
        # 默认自动检测最多 6 个分音；此处显式置 6 个保证确定性
        w._manual_peaks = [
            {"freq": 440.0 * k, "magnitude": 0.9 / k, "note": f"H{k}",
             "cents": 0.0, "midi": 69 + 12 * (k - 1)}
            for k in range(1, 7)
        ]
        w._refresh_marks()
        w.show()
        qapp.processEvents()

        assert w.marks_table.rowCount() == 6
        assert not w.marks_table.verticalScrollBar().isVisible(), \
            "6 个标记时数值表不应出现垂直滚动条"

    def test_table_height_fits_rows(self, qapp):
        w = _make_spectrum_widget(qapp)
        w._manual_peaks = [
            {"freq": 440.0 * k, "magnitude": 0.9 / k, "note": f"H{k}",
             "cents": 0.0, "midi": 69}
            for k in range(1, 7)
        ]
        w._refresh_marks()
        qapp.processEvents()

        table = w.marks_table
        header_h = table.horizontalHeader().height()
        row_h = table.rowHeight(0)
        expected = header_h + row_h * 6 + 2 * table.frameWidth()
        assert abs(table.height() - expected) <= 2, \
            f"表格高度应自适应 6 行（期望≈{expected}，实际 {table.height()}）"


# ----------------------------------------------------------------------
# 设置菜单（新增：全局性设置统一收纳至"设置"菜单）
# ----------------------------------------------------------------------


class TestSettingsMenu:
    def _make_window(self):
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow
        from acouscope.i18n import set_language

        set_language("zh_CN")
        return MainWindow(AppController())

    def _menus(self, win):
        from PyQt6.QtWidgets import QMenu

        return {m.title(): m for m in win.menuBar().findChildren(QMenu) if m.title()}

    def test_settings_menu_exists_with_items(self, qapp):
        win = self._make_window()
        menus = self._menus(win)
        settings_key = [k for k in menus if "设置" in k]
        assert settings_key, f"缺少设置菜单，现有: {list(menus)}"
        texts = [a.text() for a in menus[settings_key[0]].actions()]
        assert any("设置" in t for t in texts), f"设置菜单缺少设置项: {texts}"
        assert any("图表字体" in t for t in texts), f"设置菜单缺少图表字体: {texts}"

    def test_chart_font_moved_out_of_analysis(self, qapp):
        win = self._make_window()
        menus = self._menus(win)
        analysis_key = [k for k in menus if "分析" in k]
        assert analysis_key, f"缺少分析菜单: {list(menus)}"
        analysis_texts = [a.text() for a in menus[analysis_key[0]].actions()]
        assert not any("图表字体" in t for t in analysis_texts), \
            "图表字体应已从分析菜单移入设置菜单"

    def test_preferences_dialog_values_and_fallback(self, qapp):
        from acouscope.ui.widgets.settings_dialog import SettingsDialog

        dlg = SettingsDialog(default_format="png", default_dpi=600)
        assert dlg.default_format() == "png"
        assert dlg.default_dpi() == 600

        dlg_bad = SettingsDialog(default_format="bmp", default_dpi=999)
        assert dlg_bad.default_format() == "svg"
        assert dlg_bad.default_dpi() == 300

    def test_settings_dialog_tabs(self, qapp):
        from acouscope.ui.widgets.settings_dialog import SettingsDialog

        dlg = SettingsDialog(language="zh_CN", default_format="pdf", default_dpi=600)
        assert dlg.language() == "zh_CN"
        assert dlg.default_format() == "pdf"
        assert dlg.default_dpi() == 600
        assert dlg.theme() == "default"
        ai = dlg.ai_config()
        assert "provider" in ai and "send_image" in ai

    def test_export_format_dpi_helpers(self, qapp):
        win = self._make_window()
        win.controller.settings.default_format = "pdf"
        win.controller.settings.default_dpi = 600
        assert win._export_format_default() == "pdf"
        assert win._export_dpi() == 600

        win.controller.settings.default_format = "tiff"
        win.controller.settings.default_dpi = 999
        assert win._export_format_default() == "svg"
        assert win._export_dpi() == 300

