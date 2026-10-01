# SPDX-License-Identifier: GPL-3.0-only
"""A4 参考频率可注入校准单元测试（T-921）。A4_REFERENCE_TEST_V1

口径：硬门槛＝**默认 440.0 时全部既有换算函数输出与改动前逐位一致**（用独立复写的
旧公式做 np.array_equal 自证，多组输入）；注入 442/415 时与解析式一致（容差 1e-9）；
显式 ref_freq= 优先于全局参考；Settings 持久化往返 + 越界回退 440；
设置→通用 的数值项存在、clamp 400–480、可「恢复 440」；每例结束复原 440（全局隔离）。
本文件不构造 MainWindow.show()，不新建对话框类。
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from acouscope.dsp import units
from acouscope.utils.config import Settings

FREQS = np.array([27.5, 60.0, 110.0, 220.0, 440.0, 880.0, 2000.0])
MIDIS = np.array([21.0, 40.0, 69.0, 81.0, 108.0])
CENTS = np.array([-2400.0, -100.0, 0.0, 350.0, 1200.0, 5000.0])


@pytest.fixture(autouse=True)
def _isolate_reference():
    """全局状态隔离：每例前后均复原 440.0，防跨例污染。"""
    units.set_reference_hz(440.0)
    yield
    units.set_reference_hz(440.0)


# 改动前的旧公式（独立复写，用于逐位等价性自证）
def _legacy_hz_to_midi(freq):
    return 69 + 12 * np.log2(np.asarray(freq, dtype=float) / 440.0)


def _legacy_midi_to_hz(midi):
    return 440.0 * (2 ** ((np.asarray(midi, dtype=float) - 69) / 12))


def _legacy_hz_to_cents(freq, ref=440.0):
    return 1200.0 * np.log2(np.asarray(freq, dtype=float) / ref)


def _legacy_cents_to_hz(cents, ref=440.0):
    return ref * (2 ** (np.asarray(cents, dtype=float) / 1200.0))


# 1. 常量与默认参考


def test_a4_constant_preserved_and_default_reference():
    assert units.A4_FREQ == 440.0  # 兼容既有导入：常量保留
    assert units.get_reference_hz() == 440.0
    assert (units.REFERENCE_HZ_MIN, units.REFERENCE_HZ_MAX) == (400.0, 480.0)


def test_reference_parameters_are_optional():
    import inspect

    for func in (
        units.hz_to_midi,
        units.midi_to_hz,
        units.hz_to_cents,
        units.cents_to_hz,
        units.convert_freq_axis,
    ):
        assert inspect.signature(func).parameters["ref_freq"].default is None


# 2. 硬门槛：默认 440 逐位一致（bit-identical）


def test_bit_identical_at_default_440():
    assert np.array_equal(units.hz_to_midi(FREQS), _legacy_hz_to_midi(FREQS))
    assert np.array_equal(units.midi_to_hz(MIDIS), _legacy_midi_to_hz(MIDIS))
    assert np.array_equal(units.hz_to_cents(FREQS), _legacy_hz_to_cents(FREQS))
    assert np.array_equal(units.cents_to_hz(CENTS), _legacy_cents_to_hz(CENTS))
    # 标量输入同样逐位一致
    assert units.hz_to_midi(440.0) == _legacy_hz_to_midi(440.0)
    assert units.midi_to_hz(69.0) == _legacy_midi_to_hz(69.0)
    assert units.hz_to_cents(880.0) == _legacy_hz_to_cents(880.0)
    assert units.cents_to_hz(1200.0) == _legacy_cents_to_hz(1200.0)


def test_bit_identical_explicit_440_vs_default():
    assert np.array_equal(units.hz_to_midi(FREQS, 440.0), units.hz_to_midi(FREQS))
    assert np.array_equal(units.midi_to_hz(MIDIS, 440.0), units.midi_to_hz(MIDIS))
    assert np.array_equal(units.hz_to_cents(FREQS, 440.0), units.hz_to_cents(FREQS))
    assert np.array_equal(units.cents_to_hz(CENTS, 440.0), units.cents_to_hz(CENTS))


def test_bit_identical_convert_freq_axis():
    for unit in ("hz", "khz", "midi", "piano", "cents", "mel"):
        assert np.array_equal(
            units.convert_freq_axis(FREQS, unit),
            units.convert_freq_axis(FREQS, unit, 440.0),
        ), unit
    assert np.array_equal(units.convert_freq_axis(FREQS, "midi"), _legacy_hz_to_midi(FREQS))
    assert np.array_equal(units.convert_freq_axis(FREQS, "cents"), _legacy_hz_to_cents(FREQS))
    assert units.hz_to_note_name(440.0) == "A4"  # 音名路径未受影响（默认 440）


# 3. 注入非 440：与解析式一致


def test_injection_442_and_415_match_analytic_formulas():
    assert units.set_reference_hz(442.0) is True
    assert units.get_reference_hz() == 442.0
    assert np.allclose(units.hz_to_cents(FREQS), _legacy_hz_to_cents(FREQS, 442.0), atol=1e-9)
    assert np.allclose(units.cents_to_hz(CENTS), _legacy_cents_to_hz(CENTS, 442.0), atol=1e-9)
    assert units.midi_to_hz(69.0) == 442.0
    assert units.hz_to_midi(442.0) == 69.0
    assert units.hz_to_cents(442.0) == 0.0
    # 同一频率在两参考下的音分差 = 1200*log2(440/442)
    assert units.hz_to_cents(440.0) == pytest.approx(1200.0 * math.log2(440.0 / 442.0), abs=1e-9)
    assert np.allclose(
        units.midi_to_hz(MIDIS),
        _legacy_midi_to_hz(MIDIS) * (442.0 / 440.0),
        atol=1e-9,
    )

    assert units.set_reference_hz(415.0) is True
    assert units.midi_to_hz(69.0) == 415.0
    assert units.hz_to_cents(830.0) == pytest.approx(1200.0, abs=1e-9)
    assert units.cents_to_hz(1200.0) == pytest.approx(830.0, abs=1e-9)


def test_explicit_ref_freq_has_priority_over_global():
    units.set_reference_hz(442.0)
    assert units.hz_to_cents(440.0, ref_freq=440.0) == 0.0
    assert units.cents_to_hz(0.0, ref_freq=440.0) == 440.0
    assert units.midi_to_hz(69.0, ref_freq=440.0) == 440.0
    assert units.hz_to_midi(440.0, ref_freq=440.0) == 69.0
    assert units.convert_freq_axis(np.array([440.0]), "cents", ref_freq=440.0)[0] == 0.0
    assert units.convert_freq_axis(np.array([440.0]), "midi", ref_freq=440.0)[0] == 69.0
    assert units.get_reference_hz() == 442.0  # 显式传参不改写全局


@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, 399.9, 480.1, 1000.0, "abc", None, [440.0]],
)
def test_invalid_reference_rejected_without_raising(bad):
    units.set_reference_hz(442.0)
    assert units.set_reference_hz(bad) is False
    assert units.get_reference_hz() == 442.0


# 4. Settings 持久化往返与越界回退


def test_settings_default_and_round_trip(tmp_path):
    assert Settings().reference_hz == 440.0
    path = tmp_path / "settings.json"
    Settings(reference_hz=442.0).save(path)
    assert Settings.load(path).reference_hz == 442.0
    Settings(reference_hz=415.0).save(path)
    assert Settings.load(path).reference_hz == 415.0


@pytest.mark.parametrize("raw", [500.0, 399.0, 0.0, -5.0, "abc", None, []])
def test_settings_out_of_range_falls_back_to_440(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"reference_hz": raw}), encoding="utf-8")
    assert Settings.load(path).reference_hz == 440.0


def test_settings_missing_key_uses_default(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
    loaded = Settings.load(path)
    assert loaded.reference_hz == 440.0
    assert loaded.language == "zh_CN"  # 既有字段行为不变


# 5. 设置 → 通用 入口项（非模态常驻面板，不 show）


def test_general_tab_reference_item_clamps_and_restores(qapp):
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    dlg = SettingsDialog(language="zh_CN")
    spin = dlg.spin_reference_hz
    assert spin.minimum() == 400.0 and spin.maximum() == 480.0
    assert dlg.reference_hz() == 440.0
    assert spin.toolTip().strip()
    assert dlg.btn_reference_restore.text().strip()

    spin.setValue(300.0)  # 越界下钳
    assert dlg.reference_hz() == 400.0
    spin.setValue(9999.0)  # 越界上钳
    assert dlg.reference_hz() == 480.0
    spin.setValue(442.0)
    assert dlg.reference_hz() == 442.0
    dlg.btn_reference_restore.click()
    assert dlg.reference_hz() == 440.0


def test_dialog_initial_value_falls_back_when_out_of_range(qapp):
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    assert SettingsDialog(language="en_US", reference_hz=442.0).reference_hz() == 442.0
    assert SettingsDialog(language="en_US", reference_hz=999.0).reference_hz() == 440.0
    assert SettingsDialog(language="en_US", reference_hz="abc").reference_hz() == 440.0
    assert SettingsDialog(language="zh_TW").reference_hz() == 440.0


def test_i18n_keys_cover_three_languages():
    from acouscope.i18n import _STRINGS

    for key in (
        "settings.reference_hz",
        "settings.reference_hz_hint",
        "settings.reference_hz_restore",
    ):
        entry = _STRINGS[key]
        assert set(entry) == {"en_US", "zh_CN", "zh_TW"}, key
        for lang, text in entry.items():
            assert text.strip(), f"{key}/{lang}"


# 6. 接线面与纪律（静态）


def _src(relative: str) -> str:
    return (
        Path(__file__).resolve().parents[1] / "src" / "acouscope" / relative
    ).read_text(encoding="utf-8")


def test_set_reference_hz_callers_are_limited_to_allowed_files():
    root = Path(__file__).resolve().parents[1] / "src" / "acouscope"
    callers = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if not path.name.startswith("._")  # AppleDouble 旁车（外置卷非 UTF-8 元数据），非源码
        and "set_reference_hz(" in path.read_text(encoding="utf-8")
    )
    assert callers == ["dsp/units.py", "ui/main_window.py"]


def test_main_window_applies_reference_on_startup_and_apply():
    src = _src("ui/main_window.py")
    assert src.count("set_reference_hz(") == 2  # 启动 + 「应用」各一处
    apply_index = src.index("def _on_settings_applied")
    assert src.index("set_reference_hz(", apply_index) > apply_index
    assert "panel.reference_hz()" in src


def test_analysis_and_pitch_grid_untouched():
    """analysis/ 与 pitch_grid 只读消费：不出现 set_reference_hz 调用。"""
    for relative in ("analysis/pcp.py", "analysis/pitch_grid.py"):
        path = Path(__file__).resolve().parents[1] / "src" / "acouscope" / relative
        if not path.exists():
            continue
        assert "set_reference_hz" not in path.read_text(encoding="utf-8")
