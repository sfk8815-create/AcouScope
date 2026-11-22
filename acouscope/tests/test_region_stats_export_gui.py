# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-B T05：区间统计测量记录 GUI 导出（离屏 Qt，禁 show 主窗）。

覆盖（设计约定 §判据-2 / §范围-3、4、5、8）：
  ① ``btn_export_stats`` 存在（objectName="btn_export_stats"）、初始禁用；
  ② ``set_export_stats_callback`` / ``_export_stats`` 回调接线；
  ③ ``_on_region_stats`` 末尾构建 17 字段 ``_last_measurement_record``，
     既有 rows 文本（"440.0"/"+0.0"/"41/41"/"0.400"）逐字保留；
  ④ monkeypatch ``QFileDialog.getSaveFileName`` 后**点击按钮真写出** JSON/CSV；
  ⑤ ``resample_quality.anti_alias`` 链路可查（线性回退时记录里为 False）；
  ⑥ i18n 两键三语齐；取消对话框 / 无记录零落盘。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QFileDialog, QWidget  # noqa: E402

from acouscope.analysis.measurement_record import (  # noqa: E402
    MEASUREMENT_FIELDS,
    read_measurement_json,
)
from acouscope.i18n import _STRINGS, get_language, set_language  # noqa: E402


class _FakePitchView(QWidget):
    """区间统计只读源：仅暴露 result_arrays（同既有 test_region_stats.py 桩）。"""

    def __init__(self, times, f0):
        super().__init__()
        self._times, self._f0 = times, f0

    def result_arrays(self):
        return (self._times, self._f0)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频 + 波形数据的 MainWindow（离屏构建，不 show）。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    x = 0.5 * np.sin(2.0 * np.pi * 440.0 * t)
    controller.load_from_array(x, sr)
    playing = {"v": False}
    monkeypatch.setattr(controller, "is_playing", lambda: playing["v"])
    monkeypatch.setattr(controller, "play", lambda: None)
    monkeypatch.setattr(controller, "pause", lambda: None)
    monkeypatch.setattr(controller, "set_position", lambda *_: None)
    monkeypatch.setattr(controller, "get_position", lambda: 0.0)
    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    yield w
    w.close()


def _arm_region_stats(window, monkeypatch, sel=(0.5, 0.9)):
    """注入音高结果 + 选区 → 触发 _on_region_stats，返回只读文本。"""
    monkeypatch.setattr(
        window.waveform_widget, "get_selection", lambda: sel
    )
    times = np.arange(0.0, 2.0, 0.01)
    f0 = np.zeros_like(times)
    f0[(times >= sel[0]) & (times <= sel[1])] = 440.0
    window._pitch_widget = _FakePitchView(times, f0)
    window._on_region_stats()
    return window.inspector_panel.lbl_region_stats.text()


def _toasts(monkeypatch):
    """拦截 show_toast（轻提示）收集 (level, message)。"""
    import acouscope.ui.main_window as mw_mod

    out = []
    monkeypatch.setattr(
        mw_mod, "show_toast",
        lambda parent, message, level="info", **kw: out.append(
            (level, str(message))
        ),
    )
    return out


# ----------------------------------------------------------------------
# ① 按钮存在 / 初始禁用
# ----------------------------------------------------------------------
def test_export_stats_button_exists_with_object_name(window):
    panel = window.inspector_panel
    btn = panel.btn_export_stats
    print("btn_export_stats objectName=%s enabled=%s text=%s"
          % (btn.objectName(), btn.isEnabled(), btn.text()))
    assert btn.objectName() == "btn_export_stats"
    assert btn.isEnabled() is False          # 未注入回调前禁用
    assert panel.btn_copy_stats is not None  # 既有复制按钮仍在
    # 既有复制按钮初始禁用（行为逐字不变）
    assert panel.btn_copy_stats.isEnabled() is False


# ----------------------------------------------------------------------
# ② 回调接线
# ----------------------------------------------------------------------
def test_set_export_stats_callback_enables_and_invokes(window):
    panel = window.inspector_panel
    fired = []
    panel.set_export_stats_callback(lambda: fired.append(1))
    assert panel.btn_export_stats.isEnabled() is True
    panel.btn_export_stats.click()
    # 不做 processEvents，clicked.connect 为直连（同线程）应已同步触发
    print("callback fired=%s" % fired)
    assert fired == [1]
    panel.set_export_stats_callback(None)
    assert panel.btn_export_stats.isEnabled() is False
    panel._export_stats()  # 未注入时零副作用、不抛
    assert fired == [1]


# ----------------------------------------------------------------------
# ③ _on_region_stats 构建 17 字段记录 + 既有 rows 文本保留
# ----------------------------------------------------------------------
def test_on_region_stats_builds_17_field_record_keeps_legacy_rows(window, monkeypatch):
    text = _arm_region_stats(window, monkeypatch)
    print("region_stats text=%r" % text)
    for legacy in ("0.400", "41/41", "440.0", "+0.0"):
        assert legacy in text, (legacy, text)
    rec = window._last_measurement_record
    print("_last_measurement_record keys=%d sample_rate=%s n_eff=%s"
          % (len(rec), rec["sample_rate"], rec["n_eff"]))
    assert tuple(rec.keys()) == MEASUREMENT_FIELDS
    assert rec["format_version"] == 1
    assert rec["sample_rate"] == 8000
    assert rec["a4_reference_hz"] == 440.0
    assert rec["calibration_status"] in ("pending", "default-nominal",
                                         "user-set", "calibrated")
    # 统计后导出按钮已接线并启用
    assert window.inspector_panel.btn_export_stats.isEnabled() is True


# ----------------------------------------------------------------------
# ④ 点击真写 JSON / CSV
# ----------------------------------------------------------------------
def test_click_export_writes_json_file(window, monkeypatch, tmp_path):
    _arm_region_stats(window, monkeypatch)
    toasts = _toasts(monkeypatch)
    out = tmp_path / "measurement.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, __out=out, **kw: (str(__out), "")),
    )
    window.inspector_panel.btn_export_stats.click()
    print("JSON exists=%s size=%d toasts=%s"
          % (out.exists(), out.stat().st_size if out.exists() else -1, toasts))
    assert out.exists() and out.stat().st_size > 0
    back = read_measurement_json(out)
    assert back == window._last_measurement_record
    assert tuple(back.keys()) == MEASUREMENT_FIELDS
    assert [lv for lv, _ in toasts] == ["success"]


def test_click_export_writes_csv_file(window, monkeypatch, tmp_path):
    import csv

    _arm_region_stats(window, monkeypatch)
    toasts = _toasts(monkeypatch)
    out = tmp_path / "measurement.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, __out=out, **kw: (str(__out), "")),
    )
    window.inspector_panel.btn_export_stats.click()
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    print("CSV exists=%s rows=%d cols=%d toasts=%s"
          % (out.exists(), len(rows), len(rows[0]), toasts))
    assert out.exists() and out.stat().st_size > 0
    assert len(rows) == 1 and len(rows[0]) == 17
    assert [lv for lv, _ in toasts] == ["success"]


def test_save_dialog_filter_is_json_csv(window, monkeypatch, tmp_path):
    """点击时传入的 filter 必须是 `JSON (*.json);;CSV (*.csv)`。"""
    _arm_region_stats(window, monkeypatch)
    _toasts(monkeypatch)
    seen = {}
    out = tmp_path / "f.json"

    def _fake_dialog(*args, **kwargs):
        seen["args"] = args
        return (str(out), "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(_fake_dialog))
    window.inspector_panel.btn_export_stats.click()
    print("dialog args=%s" % (seen["args"],))
    assert "JSON (*.json);;CSV (*.csv)" in seen["args"]


def test_cancel_save_dialog_writes_nothing(window, monkeypatch, tmp_path):
    _arm_region_stats(window, monkeypatch)
    _toasts(monkeypatch)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **kw: ("", "")),
    )
    window.inspector_panel.btn_export_stats.click()
    # 未产生任何新文件（除 fixture 的配置件）
    produced = [p for p in tmp_path.glob("*.json")
                if p.name in ("measurement.json", "measurement.csv")]
    print("cancel produced=%s" % produced)
    assert produced == []


def test_export_without_record_shows_info_toast(window, monkeypatch):
    """未触发统计（无记录）时直接调导出槽 → info 轻提示、零落盘。"""
    toasts = _toasts(monkeypatch)
    called = {}
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **kw: called.setdefault("opened", True)),
    )
    window._export_measurement_record()
    print("no-record toasts=%s dialog_opened=%s"
          % (toasts, "opened" in called))
    assert [lv for lv, _ in toasts] == ["info"]
    assert "opened" not in called


# ----------------------------------------------------------------------
# ⑤ resample_quality.anti_alias 链路
# ----------------------------------------------------------------------
def test_resample_quality_anti_alias_link_in_record(window, monkeypatch):
    import acouscope.audio.io as io_mod

    from acouscope.audio.io import AudioIO, last_resample_quality

    # 触发线性回退（无 samplerate）→ 记录 anti_alias=False
    io_mod.RESAMPLE_QUALITY.clear()
    monkeypatch.setitem(__import__("sys").modules, "samplerate", None)
    with pytest.warns(RuntimeWarning):
        AudioIO._resample(np.sin(2 * np.pi * 440 * np.arange(8000) / 8000),
                          8000, 4000)
    q = last_resample_quality()
    text = _arm_region_stats(window, monkeypatch)
    rec = window._last_measurement_record
    print("LINK ledger=%s record.resample_quality=%s legacy_text_ok=%s"
          % (q, rec["resample_quality"], "440.0" in text))
    assert q["anti_alias"] is False
    assert rec["resample_quality"]["anti_alias"] is False
    assert rec["resample_quality"]["method"] == "linear_fallback"
    assert "440.0" in text  # 既有 rows 未被破坏
    io_mod.RESAMPLE_QUALITY.clear()


# ----------------------------------------------------------------------
# ⑥ i18n 两键三语齐
# ----------------------------------------------------------------------
def test_i18n_export_keys_three_languages():
    for key in ("region_stats.export", "region_stats.exported"):
        entry = _STRINGS[key]
        for lang in ("en_US", "zh_CN", "zh_TW"):
            assert entry[lang].strip(), (key, lang)
        print("i18n %s en=%r zh=%r tw=%r"
              % (key, entry["en_US"], entry["zh_CN"], entry["zh_TW"]))
    original = get_language()
    try:
        set_language("en_US")
        from acouscope.i18n import tr
        assert "{" not in tr("region_stats.export")
        assert tr("region_stats.exported").format(name="m.json").endswith("m.json")
    finally:
        set_language(original)


def test_existing_copy_behavior_unchanged(window, monkeypatch):
    """既有 set_region_stats / _copy_stats / btn_copy_stats 行为逐字不变。"""
    panel = window.inspector_panel
    QApplication.clipboard().setText("")
    panel.set_region_stats("选区 0.500–0.900 s · 时长 0.400 s")
    assert panel.btn_copy_stats.isEnabled() is True
    panel._copy_stats()
    assert "0.400" in QApplication.clipboard().text()
    panel.set_region_stats(None)
    assert panel.btn_copy_stats.isEnabled() is False
    assert panel.lbl_region_stats.text() == "—"
    print("legacy copy/reset behavior intact")
