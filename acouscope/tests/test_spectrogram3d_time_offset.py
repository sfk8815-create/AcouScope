# SPDX-License-Identifier: GPL-3.0-only
"""T-917 3D 频谱图时间轴绝对化回归测试。

离屏环境：独立构造 Spectrogram3DWidget（禁 MainWindow、禁 show()），
验证乐段起点偏移回加后 _stft_times / 标题 / y 轴视图区间均为绝对时间，
且乐段切换缓存不串档。
"""

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

_SR = 8000
_TOL = 1.0 / _SR  # i0/sr 与 t0 的整数截断误差 ≤ 1 个采样点

_S3D_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "widgets" / "spectrogram3d.py"
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）。
_BANNED = "Mel" + "odyne"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _tone(dur=6.0, f0=440.0):
    """含 4 次谐波的稳定乐音（6 s，覆盖 5.0–6.0 乐段）。"""
    t = np.arange(int(_SR * dur)) / _SR
    sig = np.zeros_like(t)
    for k in (1, 2, 3, 4):
        sig += 0.5 / k * np.sin(2 * np.pi * f0 * k * t)
    return sig


@pytest.fixture
def widget(qapp):
    w = Spectrogram3DWidget()
    w.resize(1000, 600)
    w.set_audio(_tone(), _SR)
    yield w
    w.close()


class TestAbsoluteTimeAxis:
    def test_range_2_to_4_starts_at_2(self, widget):
        """乐段 2.0–4.0s → _stft_times 起点 ≈ 2.0（绝对时间）。"""
        widget.set_time_range(2.0, 4.0)
        times = widget._stft_times
        assert len(times) >= 10
        assert float(times[0]) == pytest.approx(2.0, abs=_TOL)

    def test_range_0_to_1_starts_at_0(self, widget):
        """乐段 0.0–1.0s → 起点 ≈ 0.0（零偏移，与旧口径一致）。"""
        widget.set_time_range(0.0, 1.0)
        times = widget._stft_times
        assert len(times) >= 1
        assert float(times[0]) == pytest.approx(0.0, abs=_TOL)

    def test_times_monotonic_and_bounded(self, widget):
        """_stft_times 严格单调递增且不越过乐段终点。"""
        widget.set_time_range(2.0, 4.0)
        times = widget._stft_times
        assert np.all(np.diff(times) > 0), "时间轴必须严格单调递增"
        assert float(times[-1]) <= 4.0 + _TOL

    def test_cache_no_crosstalk_between_segments(self, widget):
        """连续两次不同乐段（2.0–4.0 → 5.0–6.0）缓存不串档。"""
        widget.set_time_range(2.0, 4.0)
        key_a = widget._cache_key
        t_a = float(widget._stft_times[0])
        assert t_a == pytest.approx(2.0, abs=_TOL)

        widget.set_time_range(5.0, 6.0)
        assert widget._cache_key != key_a, "不同乐段缓存键必须不同"
        t_b = float(widget._stft_times[0])
        assert t_b == pytest.approx(5.0, abs=_TOL), "第二次乐段起点未绝对化"

    def test_title_shows_absolute_range(self, widget):
        """标题时间范围显示绝对时间（起点 2.00）。"""
        widget.set_time_range(2.0, 4.0)
        title = widget.ax_3d.get_title()
        assert "2.00–" in title, f"标题应含绝对起点 2.00: {title}"

    def test_yaxis_view_interval_absolute(self, widget):
        """曲面模式：y 轴视图区间起点为绝对时间 2.0。"""
        widget.cmb_mode.setCurrentIndex(0)  # 曲面
        widget.set_time_range(2.0, 4.0)
        lo, hi = widget.ax_3d.yaxis.get_view_interval()
        assert lo == pytest.approx(2.0, abs=_TOL)
        assert hi <= 4.0 + _TOL and hi > lo


class TestStatic:
    def test_banned_word_zero_hits(self):
        """禁词 0 命中（spectrogram3d.py + 本测试文件）。"""
        for f in (_S3D_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hex_px_in_added_lines(self):
        """T-917 标记行无硬编码 hex/px。"""
        src = _S3D_PY.read_text(encoding="utf-8")
        added = [ln for ln in src.splitlines() if "T-917" in ln]
        assert added, "应存在 T-917 标记行"
        for ln in added:
            assert not re.search(r"#[0-9a-fA-F]{6}\b", ln), f"hex 硬编码: {ln}"
            assert "px" not in ln, f"px 硬编码: {ln}"

    def test_no_new_qdialog(self):
        """无新建 QDialog（T-917 标记行不得出现 QDialog）。"""
        src = _S3D_PY.read_text(encoding="utf-8")
        for ln in src.splitlines():
            if "T-917" in ln:
                assert "QDialog" not in ln, f"禁新建 QDialog: {ln}"
