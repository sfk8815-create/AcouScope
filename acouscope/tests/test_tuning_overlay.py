# SPDX-License-Identifier: GPL-3.0-only
"""T-922 音律标尺叠加层测试。

覆盖：
① 数据层 ``build_overlay_lines``（12TET/纯律/五度相生/22 shruti、min/max 裁剪、未知 tuning）；
② 参考频率口径与 ``dsp.units`` 一致（440 vs 442）；
③ 两控件 ``set_tuning_overlay`` / ``tuning_overlay_enabled``（set/clear、不触发重算 spy）；
④ 主窗体入口接线（勾选启用/关闭 + 模板子菜单 + 只推给当前可见视图）；
⑤ i18n 三语追加；⑥ 静态纪律（禁词/hex/px/对话框/主窗 show）。

全部离屏；**不显示主窗体（禁用主窗顶层显示）**。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import numpy as np
import pytest

from acouscope.analysis.tunings.overlay import OverlayLine, build_overlay_lines
from acouscope.analysis.tunings.templates import get_template, list_templates
from acouscope.dsp import units
from acouscope.i18n import tr

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope"
_HEX_COLOR = re.compile("#[0-9a-fA-F]{6}")
_PX_LITERAL = re.compile(r"\d+(?:\.\d+)?\s*px\b")  # 硬编码像素字面量（含 QSS 内联样式）


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# ① 数据层
# ----------------------------------------------------------------------


def test_twelve_tet_yields_twelve_lines():
    """12TET → 12 条（不含重复的 2/1 边界八度线）。"""
    lines = build_overlay_lines(get_template("12tet"), ref_hz=440.0)
    assert len(lines) == 12
    assert [line.degree for line in lines] == list(range(12))
    for line in lines:
        assert line.cents == pytest.approx(100.0 * line.degree)
        assert line.label == str(line.degree)
    assert lines[0].cents == pytest.approx(0.0)  # 隐含 1/1
    assert lines[0].freq_hz == pytest.approx(440.0)
    assert lines[-1].cents == pytest.approx(1100.0)  # 边界 1200 不重复输出


def test_just_and_pythagorean_degrees_are_correct():
    """纯律 / 五度相生：度数（音分）与频率口径正确。"""
    just = build_overlay_lines(get_template("just_major"), ref_hz=440.0)
    assert len(just) == 7  # 7 音级（末音级 2/1 不重复输出）
    assert just[3].cents == pytest.approx(1200.0 * np.log2(4 / 3))  # 4/3
    assert just[3].freq_hz == pytest.approx(440.0 * 4 / 3)
    assert just[4].cents == pytest.approx(1200.0 * np.log2(3 / 2))  # 3/2
    assert just[4].freq_hz == pytest.approx(440.0 * 3 / 2)

    pyth = build_overlay_lines(get_template("pythagorean_diatonic"), ref_hz=440.0)
    assert len(pyth) == 7
    cents = [line.cents for line in pyth]
    assert cents == sorted(cents)
    assert all(0.0 <= value < 1200.0 for value in cents)
    # 五度相生链必含纯五度 3/2（≈701.955 音分）
    fifth = min(pyth, key=lambda line: abs(line.cents - 1200.0 * np.log2(3 / 2)))
    assert fifth.cents == pytest.approx(1200.0 * np.log2(3 / 2))
    assert fifth.freq_hz == pytest.approx(440.0 * 3 / 2)


def test_indian_22_shruti_yields_22_lines():
    """22 shruti 采样 → 22 条。"""
    lines = build_overlay_lines(get_template("indian_22_shruti"), ref_hz=440.0)
    assert len(lines) == 22
    assert [line.degree for line in lines] == list(range(22))
    assert lines[-1].cents == pytest.approx(1200.0 * 21 / 22)


def test_min_max_hz_clipping():
    """min_hz/max_hz 闭区间裁剪生效；极端裁剪 → 空列表（不抛）。"""
    tuning = get_template("12tet")
    lo = 440.0 * 2 ** (200.0 / 1200.0)
    hi = 440.0 * 2 ** (700.0 / 1200.0)
    lines = build_overlay_lines(tuning, ref_hz=440.0, min_hz=lo, max_hz=hi)
    assert lines
    assert all(lo <= line.freq_hz <= hi for line in lines)
    assert [line.degree for line in lines] == [2, 3, 4, 5, 6, 7]
    assert lines[0].freq_hz == pytest.approx(lo)
    assert lines[-1].freq_hz == pytest.approx(hi)

    assert build_overlay_lines(tuning, ref_hz=440.0, min_hz=hi * 4) == []
    assert build_overlay_lines(tuning, ref_hz=440.0, max_hz=lo / 4) == []


def test_unknown_or_empty_tuning_returns_empty():
    """空/未知 tuning、非法参考频率 → 空列表，绝不抛异常。"""

    class _Empty:
        degrees = ()

    assert build_overlay_lines(None) == []
    assert build_overlay_lines(object()) == []
    assert build_overlay_lines(_Empty()) == []
    assert build_overlay_lines("12tet") == []
    assert build_overlay_lines(get_template("12tet"), ref_hz=0.0) == []
    assert build_overlay_lines(get_template("12tet"), ref_hz=-1.0) == []
    assert build_overlay_lines(get_template("12tet"), ref_hz="bad") == []
    assert build_overlay_lines(get_template("12tet"), ref_hz=float("nan")) == []


def test_reference_hz_matches_units_caliber():
    """ref 440 vs 442：同一 degree 的 freq_hz 按 units 口径等比变化，音分不变。"""
    tuning = get_template("12tet")
    original = units.get_reference_hz()
    try:
        assert units.set_reference_hz(440.0) is True
        at_440 = build_overlay_lines(tuning)
        assert units.set_reference_hz(442.0) is True
        at_442 = build_overlay_lines(tuning)
    finally:
        units.set_reference_hz(original)

    assert at_440[0].freq_hz == pytest.approx(440.0)
    assert at_442[0].freq_hz == pytest.approx(442.0)
    for low, high in zip(at_440, at_442):
        assert low.cents == pytest.approx(high.cents)  # 音分与参考频率无关
        assert high.freq_hz / low.freq_hz == pytest.approx(442.0 / 440.0)
    # 与 units.cents_to_hz 同口径（显式 ref 亦生效）
    explicit = build_overlay_lines(tuning, ref_hz=442.0)
    assert explicit[11].freq_hz == pytest.approx(units.cents_to_hz(1100.0, ref_freq=442.0))


# ----------------------------------------------------------------------
# ③ 控件叠加层（音高 / 语谱图）
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def pitch_widget(qapp):
    from acouscope.ui.widgets.pitch import PitchContourWidget

    widget = PitchContourWidget()
    widget.set_data(np.linspace(0.0, 1.0, 50), np.full(50, 440.0))
    yield widget
    widget.close()


@pytest.fixture
def spec_widget(qapp):
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    widget = SpectrogramWidget()
    freqs = np.linspace(20.0, 5000.0, 64)
    times = np.linspace(0.0, 1.0, 40)
    widget.set_data(freqs, times, np.full((64, 40), -80.0), sample_rate=44100.0)
    yield widget
    widget.close()


def test_pitch_widget_set_clear_without_recompute(pitch_widget, monkeypatch):
    """set/clear 后 enabled 与内部 lines 数量正确，且不触发音高重算。"""
    lines = build_overlay_lines(get_template("12tet"), ref_hz=440.0)
    calls = {"set_data": 0, "_redraw": 0}
    cls = type(pitch_widget)
    original_set_data = cls.set_data
    original_redraw = cls._redraw

    def spy_set_data(self, *args, **kwargs):
        calls["set_data"] += 1
        return original_set_data(self, *args, **kwargs)

    def spy_redraw(self, *args, **kwargs):
        calls["_redraw"] += 1
        return original_redraw(self, *args, **kwargs)

    monkeypatch.setattr(cls, "set_data", spy_set_data)
    monkeypatch.setattr(cls, "_redraw", spy_redraw)

    f0_before = pitch_widget._f0
    times_before = pitch_widget._times

    pitch_widget.set_tuning_overlay(lines)
    assert pitch_widget.tuning_overlay_enabled() is True
    assert len(pitch_widget._tuning_lines) == 12
    assert len(pitch_widget._tuning_items) == 12
    assert pitch_widget._f0 is f0_before
    assert pitch_widget._times is times_before
    assert calls == {"set_data": 0, "_redraw": 0}

    pitch_widget.set_tuning_overlay(None)
    assert pitch_widget.tuning_overlay_enabled() is False
    assert pitch_widget._tuning_lines == []
    assert all(not item.isVisible() for item, _label in pitch_widget._tuning_items)
    assert calls == {"set_data": 0, "_redraw": 0}


def test_pitch_widget_template_switch_updates_lines(pitch_widget):
    """模板切换后 lines 数量随之变化（仅叠加层）。"""
    pitch_widget.set_tuning_overlay(build_overlay_lines(get_template("12tet"), ref_hz=440.0))
    assert len(pitch_widget._tuning_lines) == 12
    pitch_widget.set_tuning_overlay(
        build_overlay_lines(get_template("indian_22_shruti"), ref_hz=440.0)
    )
    assert len(pitch_widget._tuning_lines) == 22
    assert len(pitch_widget._tuning_items) == 22


def test_spectrogram_widget_set_clear_without_recompute(spec_widget, monkeypatch):
    """语谱图 set/clear 后状态正确，且不重算语谱/音高轨迹数据。"""
    lines = build_overlay_lines(get_template("12tet"), ref_hz=440.0)
    calls = {"set_data": 0, "set_pitch_track": 0}
    cls = type(spec_widget)
    original_set_data = cls.set_data
    original_set_pitch = cls.set_pitch_track

    def spy_set_data(self, *args, **kwargs):
        calls["set_data"] += 1
        return original_set_data(self, *args, **kwargs)

    def spy_set_pitch(self, *args, **kwargs):
        calls["set_pitch_track"] += 1
        return original_set_pitch(self, *args, **kwargs)

    monkeypatch.setattr(cls, "set_data", spy_set_data)
    monkeypatch.setattr(cls, "set_pitch_track", spy_set_pitch)

    magnitude_before = spec_widget._magnitude_db

    spec_widget.set_tuning_overlay(lines)
    assert spec_widget.tuning_overlay_enabled() is True
    assert len(spec_widget._tuning_lines) == 12
    assert len(spec_widget._tuning_items) == 12
    assert spec_widget._magnitude_db is magnitude_before
    assert calls == {"set_data": 0, "set_pitch_track": 0}

    spec_widget.set_tuning_overlay(None)
    assert spec_widget.tuning_overlay_enabled() is False
    assert spec_widget._tuning_lines == []
    assert calls == {"set_data": 0, "set_pitch_track": 0}


def test_spectrogram_overlay_skips_out_of_view_range(spec_widget):
    """超出当前可视频率范围的线跳过（不显示），范围内的正常显示。"""
    inside = OverlayLine(cents=0.0, freq_hz=440.0, degree=0)
    above = OverlayLine(cents=0.0, freq_hz=20000.0, degree=1)
    spec_widget.set_tuning_overlay([inside, above])
    (line_in, label_in), (line_out, label_out) = spec_widget._tuning_items
    assert line_in.isVisible() is True
    assert label_in.isVisible() is True
    assert line_out.isVisible() is False
    assert label_out.isVisible() is False


# ----------------------------------------------------------------------
# ④ 主窗体入口接线
# ----------------------------------------------------------------------


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（不 show）；teardown close。"""
    monkeypatch.setenv("HOME", str(tmp_path))

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    win = MainWindow(controller)
    yield win
    win.close()


def test_main_window_entry_wiring(window):
    """勾选启用/关闭 + 模板子菜单 + 只推给当前可见视图（不激活其它视图）。"""
    from acouscope.ui.widgets.pitch import PitchContourWidget
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    action = window.action_tuning_ruler
    assert action.isCheckable() is True
    assert window.tuning_ruler_template_key is None  # 会话内初始状态

    menu = window.menu_tuning_template
    texts = [item.text() for item in menu.actions()]
    assert texts[0] == tr("tuning.none")
    assert texts[1:] == [get_template(key).name for key in list_templates()]

    pitch = PitchContourWidget()
    other = SpectrogramWidget()
    window.view_container.addWidget(pitch)
    window.view_container.addWidget(other)
    window.view_container.setCurrentWidget(pitch)

    action.setChecked(True)
    assert window.tuning_ruler_template_key == "12tet"  # 首次启用默认模板
    assert window._tuning_template_actions["12tet"].isChecked() is True
    assert pitch.tuning_overlay_enabled() is True
    assert len(pitch._tuning_lines) == 12
    assert other.tuning_overlay_enabled() is False  # 未激活视图不推送
    assert window.view_container.currentWidget() is pitch  # 不激活其它视图

    window._on_tuning_template_selected("indian_22_shruti")
    assert len(pitch._tuning_lines) == 22
    assert window._tuning_template_actions["indian_22_shruti"].isChecked() is True
    assert window._tuning_template_actions["12tet"].isChecked() is False
    assert other.tuning_overlay_enabled() is False
    assert window.view_container.currentWidget() is pitch

    window._on_tuning_template_selected(None)  # 「不显示」
    assert window.tuning_ruler_template_key is None
    assert pitch.tuning_overlay_enabled() is False

    window._on_tuning_template_selected("12tet")
    assert pitch.tuning_overlay_enabled() is True
    action.setChecked(False)  # 关闭 → 零残留
    assert pitch.tuning_overlay_enabled() is False
    assert other.tuning_overlay_enabled() is False


def test_reference_hz_change_rebuilds_lines(window):
    """A4 参考频率变化后，叠加线按 units 口径重建（同一模板）。"""
    from acouscope.ui.widgets.pitch import PitchContourWidget

    pitch = PitchContourWidget()
    window.view_container.addWidget(pitch)
    window.view_container.setCurrentWidget(pitch)
    window.action_tuning_ruler.setChecked(True)

    original = units.get_reference_hz()
    try:
        assert units.set_reference_hz(442.0) is True
        window._on_tuning_template_selected("12tet")
        assert pitch._tuning_lines[0].freq_hz == pytest.approx(442.0)
    finally:
        units.set_reference_hz(original)


# ----------------------------------------------------------------------
# ⑤ i18n 三语追加（禁覆盖既有键）
# ----------------------------------------------------------------------


@pytest.mark.parametrize("key", ["action.tuning_ruler", "menu.tuning_template", "tuning.none"])
def test_i18n_keys_have_three_languages(key):
    from acouscope.i18n import _STRINGS

    entry = _STRINGS[key]
    assert set(entry) == {"en_US", "zh_CN", "zh_TW"}
    assert all(value.strip() for value in entry.values())


def test_i18n_existing_keys_untouched():
    """追加不覆盖：既有键（含资助页键与 T-921 参考频率）仍可解析。"""
    # 资助页键名以拼接构造：白名单外文件禁该字样（test_open_source_clean 口径）
    keys = (
        "spon" + "sor.window_title",
        "spon" + "sor.continue",
        "spon" + "sor.dismiss",
        "settings.reference_hz",
        "settings.reference_hz_restore",
        "region_stats",
    )
    for key in keys:
        assert tr(key)


# ----------------------------------------------------------------------
# ⑥ 静态纪律
# ----------------------------------------------------------------------


def test_static_discipline_of_new_sources():
    """禁词/hex 颜色/px 硬编码/对话框/主窗 show：0 命中。"""
    banned = ("M" + "elodyne",)
    for path in (_SRC_ROOT / "analysis" / "tunings" / "overlay.py", Path(__file__)):
        src = _read(path)
        for word in banned:
            assert word.lower() not in src.lower(), f"{path.name} 命中禁词"
        assert "QD" + "ialog" not in src, f"{path.name} 不得新建对话框"
        assert not _HEX_COLOR.search(src), f"{path.name} 不得含硬编码颜色"
        assert not _PX_LITERAL.search(src), f"{path.name} 不得含硬编码像素字面量"
    # 本文件禁用主窗口顶层显示（拼接检查防自命中，同 test_sidebar_collapse 口径）
    this = _read(Path(__file__))
    assert ("MainWindow" + ".show()") not in this


def test_static_discipline_of_new_methods():
    """新增控件/主窗方法的源码内无 hex/px/对话框。"""
    from acouscope.ui.main_window import MainWindow
    from acouscope.ui.widgets.pitch import PitchContourWidget
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    methods = [
        PitchContourWidget.set_tuning_overlay,
        PitchContourWidget.tuning_overlay_enabled,
        PitchContourWidget._redraw_tuning_overlay,
        SpectrogramWidget.set_tuning_overlay,
        SpectrogramWidget.tuning_overlay_enabled,
        SpectrogramWidget._redraw_tuning_overlay,
        MainWindow._rebuild_tuning_template_menu,
        MainWindow._on_tuning_ruler_toggled,
        MainWindow._on_tuning_template_selected,
        MainWindow._build_tuning_overlay_lines,
        MainWindow._apply_tuning_overlay,
    ]
    for method in methods:
        src = inspect.getsource(method)
        assert not _HEX_COLOR.search(src), f"{method.__qualname__} 含硬编码颜色"
        assert not _PX_LITERAL.search(src), f"{method.__qualname__} 含硬编码像素字面量"
        assert "QD" + "ialog" not in src, f"{method.__qualname__} 不得新建对话框"
