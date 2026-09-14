# SPDX-License-Identifier: GPL-3.0-only
"""3D 频谱图 / 瀑布图控件的数值与渲染测试。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.spectrogram3d import (
    DEFAULT_AZIM,
    MAX_FREQ_BINS,
    MAX_SURFACE_FRAMES,
    MAX_WATERFALL_LINES,
    Spectrogram3DWidget,
)

SR = 44100


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _harmonic_tone(dur=3.0, f0=440.0):
    """含 4 次谐波的稳定乐音。"""
    t = np.arange(int(SR * dur)) / SR
    sig = np.zeros_like(t)
    for k in (1, 2, 3, 4):
        sig += 0.5 / k * np.sin(2 * np.pi * f0 * k * t)
    return sig


def _chirp(dur=2.0, f0=300.0, f1=2500.0):
    """线性扫频（验证时间-频率结构保留）。"""
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * (f0 * t + (f1 - f0) / (2 * dur) * t**2)
    return np.sin(phase)


@pytest.fixture
def widget(qapp):
    w = Spectrogram3DWidget()
    w.resize(1000, 600)
    yield w
    w.close()


class TestSTFTSegment:
    def test_chirp_freq_rises_over_time(self, widget):
        """扫频信号：帧主峰频率随时间上升。"""
        widget.set_audio(_chirp(), SR)
        freqs = widget._stft_freqs
        times = widget._stft_times
        mags = widget._stft_mag
        assert len(times) >= 10

        # 前段 vs 后段主峰
        def peak_freq(mag_row):
            return float(freqs[np.argmax(mag_row)])

        f_early = peak_freq(mags[len(mags) // 8])
        f_late = peak_freq(mags[len(mags) - len(mags) // 8])
        assert f_late > f_early + 500, f"扫频结构丢失: {f_early} → {f_late}"

    def test_harmonic_peaks_at_expected_freqs(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        avg_mag = np.mean(widget._stft_mag, axis=0)
        freqs = widget._stft_freqs
        for k in (1, 2, 3, 4):
            expected = 440 * k
            idx = np.argmin(np.abs(freqs - expected))
            window = avg_mag[max(0, idx - 3) : idx + 4]
            assert np.max(window) > 0.1 * np.max(avg_mag), f"{expected} Hz 谐波缺失"

    def test_cache_avoids_recompute(self, widget):
        """纯显示参数变化不重算 STFT。"""
        widget.set_audio(_harmonic_tone(dur=1.5), SR)
        key_before = widget._cache_key
        mags_before = widget._stft_mag.copy()

        # 只切换显示模式
        widget.cmb_mode.setCurrentIndex(1)
        widget.render()

        assert widget._cache_key == key_before
        np.testing.assert_array_equal(widget._stft_mag, mags_before)

    def test_short_segment_rejected(self, widget):
        """过短乐段（< n_fft）不崩溃，显示提示。"""
        widget.set_audio(_harmonic_tone(dur=0.02), SR)
        assert len(widget._stft_times) == 0
        assert "过短" in widget.ax_3d.get_title()

    def test_time_range_change_recomputes(self, widget):
        sig = _harmonic_tone(dur=6.0)
        widget.set_audio(sig, SR)
        key0 = widget._cache_key
        widget.set_time_range(3.0, 5.0)
        assert widget._cache_key != key0
        assert widget.segment == (3.0, 5.0)


class TestDisplayDownsampling:
    def test_freq_bins_capped(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget.cmb_fmax.setCurrentIndex(6)  # 全频段
        freqs, _, _ = widget._display_arrays()
        assert len(freqs) <= MAX_FREQ_BINS

    def test_surface_frames_capped(self, widget):
        widget.set_audio(_harmonic_tone(dur=30.0), SR)
        widget.cmb_mode.setCurrentIndex(0)
        _, times, mags = widget._display_arrays()
        assert len(times) <= MAX_SURFACE_FRAMES
        assert mags.shape[0] == len(times)


class TestScaling:
    def test_db_floor_clipped(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget.cmb_scale.setCurrentIndex(1)  # dB
        _, _, mags = widget._display_arrays()
        z, zmin, zmax, label = widget._scaled_mags(mags)
        assert "dB" in label
        assert zmax - zmin == pytest.approx(widget.spn_dr.value())
        assert float(np.min(z)) >= zmin - 1e-9

    def test_linear_scale_passthrough(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        _, _, mags = widget._display_arrays()
        z, zmin, zmax, label = widget._scaled_mags(mags)
        assert "线性" in label
        assert zmin == 0.0
        np.testing.assert_array_equal(z, mags)


class TestRenderModes:
    @pytest.mark.parametrize("mode_idx", [0, 1, 2])
    def test_all_modes_render(self, widget, mode_idx):
        widget.set_audio(_harmonic_tone(), SR)
        widget.cmb_mode.setCurrentIndex(mode_idx)
        widget.render()

        ax = widget.ax_3d
        assert ax.get_xlabel() == "频率 (Hz)"
        # 时间轴用自定义格式（<1s 毫秒、≥60s 分秒），不再带 (s) 单位后缀
        assert ax.get_ylabel() == "时间"
        # 轴范围已设置
        assert ax.get_xlim()[1] > 0

    def test_waterfall_line_count_capped(self, widget):
        widget.set_audio(_harmonic_tone(dur=20.0), SR)
        widget.cmb_mode.setCurrentIndex(1)
        widget.render()
        lines = [
            a for a in widget.ax_3d.get_lines()
            if len(a.get_xdata()) > 2
        ]
        assert 0 < len(lines) <= MAX_WATERFALL_LINES

    def test_hidden_mode_has_fill_collections(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget.cmb_mode.setCurrentIndex(2)
        widget.render()
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        polys = [
            a for a in widget.ax_3d.collections
            if isinstance(a, Poly3DCollection)
        ]
        assert len(polys) > 0, "消隐模式应有白色填充面"

    def test_colorbar_removed_when_switching_to_waterfall(self, widget):
        """曲面→瀑布切换后旧色条不残留。"""
        widget.set_audio(_harmonic_tone(), SR)
        widget.cmb_mode.setCurrentIndex(0)  # 曲面
        widget.render()
        assert widget._colorbar is not None

        widget.cmb_mode.setCurrentIndex(1)  # 瀑布
        widget.render()
        assert widget._colorbar is None
        # 图形中无残留的色条轴
        cb_axes = [
            ax for ax in widget.figure.axes
            if ax.get_label() == "<colorbar>"
        ]
        assert len(cb_axes) == 0, f"残留色条 {len(cb_axes)} 个"



class TestPointerCentered:
    def test_pointer_range(self, widget):
        sig = _harmonic_tone(dur=10.0)
        widget.set_audio(sig, SR)
        widget.pointer_getter = lambda: 5.0
        widget._on_pointer_centered()
        t0, t1 = widget.segment
        assert t0 == pytest.approx(3.0)
        assert t1 == pytest.approx(7.0)

    def test_pointer_near_start_clamped(self, widget):
        widget.set_audio(_harmonic_tone(dur=10.0), SR)
        widget.pointer_getter = lambda: 0.5
        widget._on_pointer_centered()
        t0, t1 = widget.segment
        assert t0 == pytest.approx(0.0)
        assert t1 == pytest.approx(4.0)


class TestEmbeddedFontScale:
    """嵌入画布字号与 dpi（原缺陷：rcParams 300dpi 导致字号约为界面 4 倍）。"""

    def test_figure_dpi_is_embed_scale(self, widget):
        assert widget.figure.dpi == 100

    def test_axis_label_sizes(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget.canvas.draw()
        ax = widget.ax_3d
        assert ax.xaxis.label.get_fontsize() == pytest.approx(8.5)
        assert ax.zaxis.label.get_fontsize() == pytest.approx(8.5)
        assert ax.title.get_fontsize() == pytest.approx(9.5)

    def test_tick_label_sizes(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget.canvas.draw()
        labels = widget.ax_3d.xaxis.get_ticklabels()
        assert labels and labels[0].get_fontsize() == pytest.approx(7)


class TestSidePanel:
    """右侧参数面板（视角 / 边距 / 保存，替代原左下角导航工具列）。"""

    def test_no_bottom_toolbar(self, widget):
        """左下角导航工具列已移除。"""
        assert not hasattr(widget, "nav_toolbar")
        # 右侧参数面板存在
        assert hasattr(widget, "spn_elev") and hasattr(widget, "spn_azim")
        assert hasattr(widget, "_margin_spins") and hasattr(widget, "btn_save")

    def test_view_spins_rotate_axes(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget.spn_elev.setValue(45.0)
        widget.spn_azim.setValue(-120.0)
        assert widget.ax_3d.elev == pytest.approx(45.0)
        assert widget.ax_3d.azim == pytest.approx(-120.0)

    def test_view_reset(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget.spn_elev.setValue(60.0)
        widget._reset_view()
        assert widget.ax_3d.elev == pytest.approx(28.0)
        assert widget.ax_3d.azim == pytest.approx(DEFAULT_AZIM)
        assert widget.spn_elev.value() == pytest.approx(28.0)

    def test_margin_spins_adjust_axes(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget._margin_spins["left"].setValue(0.30)
        assert widget.ax_3d.get_position().x0 == pytest.approx(0.30, abs=1e-3)
        # 色条跟随主轴右缘平移
        cax_x = widget.cax.get_position().x0
        assert cax_x == pytest.approx(0.30 + widget._ax_rect[2] - 0.085, abs=1e-3)

    def test_margin_reset(self, widget):
        widget.set_audio(_harmonic_tone(), SR)
        widget._margin_spins["top"].setValue(0.50)
        widget._reset_margins()
        assert widget._ax_rect == pytest.approx([0.02, 0.10, 0.72, 0.80])
        assert widget._margin_spins["top"].value() == pytest.approx(0.90)

    def test_render_keeps_custom_view(self, widget):
        """改参数重绘时保持用户视角，不强制复位。"""
        widget.set_audio(_harmonic_tone(), SR)
        widget.spn_elev.setValue(50.0)
        widget.cmb_scale.setCurrentIndex(1)  # 触发重绘
        assert widget.ax_3d.elev == pytest.approx(50.0)

    def test_colormaps_extended(self, widget):
        """色板下拉 ≥ 14 组（原 6 + 新增 ≥ 8），全部为 matplotlib 有效色板。"""
        import matplotlib

        names = [key for _, key in Spectrogram3DWidget.COLORMAPS]
        assert len(names) >= 14
        for name in names:
            assert name in matplotlib.colormaps, f"无效色板: {name}"


class TestWaterfallColormap:
    """色板下拉在瀑布/消隐模式必须生效（原缺陷：谱线固定蓝色被忽略）。"""

    def _grab_array(self, widget):
        img = widget.grab().toImage()
        xs = list(range(0, img.width(), 9))
        ys = list(range(0, img.height(), 9))
        a = np.zeros((len(ys), len(xs), 3), dtype=np.int64)
        for yi, y in enumerate(ys):
            for xi, x in enumerate(xs):
                c = img.pixelColor(x, y)
                a[yi, xi] = (c.red(), c.green(), c.blue())
        return a

    @pytest.mark.parametrize("mode_idx,threshold", [(1, 50000), (2, 5000)])
    def test_cmap_changes_waterfall_render(self, widget, mode_idx, threshold):
        widget.set_audio(_harmonic_tone(), SR)
        widget.cmb_mode.setCurrentIndex(mode_idx)
        widget.cmb_cmap.setCurrentIndex(0)  # viridis
        widget.canvas.draw()
        a0 = self._grab_array(widget)
        widget.cmb_cmap.setCurrentIndex(4)  # jet
        widget.canvas.draw()
        a1 = self._grab_array(widget)
        diff = np.abs(a0 - a1).sum()
        assert diff > threshold, f"模式{mode_idx} 色板切换差异过小: {diff}"


class TestCanvasExport:
    """3D 视图画布直接导出（Ctrl+E 模式 6 路径）。"""

    @pytest.mark.parametrize("fmt", ["svg", "png", "pdf"])
    def test_print_figure_formats(self, widget, tmp_path, fmt):
        widget.set_audio(_harmonic_tone(dur=1.5), SR)
        out = tmp_path / f"export_3d.{fmt}"
        widget.canvas.print_figure(
            str(out), format=fmt, dpi=150, bbox_inches="tight",
            facecolor="white",
        )
        assert out.exists() and out.stat().st_size > 1000

    def test_print_figure_waterfall_mode(self, widget, tmp_path):
        widget.set_audio(_harmonic_tone(dur=1.5), SR)
        widget.cmb_mode.setCurrentIndex(2)  # 消隐瀑布
        out = tmp_path / "export_waterfall.png"
        widget.canvas.print_figure(
            str(out), format="png", dpi=150, bbox_inches="tight",
            facecolor="white",
        )
        assert out.exists() and out.stat().st_size > 1000
