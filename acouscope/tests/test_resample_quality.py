# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-B T06：重采样线性回退治理（纯 numpy，零 Qt）。

覆盖（设计约定 §判据-3 / §范围-6、7）：
  ① 注入 fake ``samplerate`` 模块 → ``sinc_best`` 分支标记
     ``anti_alias=True`` / ``uncertainty_cent=0.0``；
  ② 无 samplerate → ``pytest.warns(RuntimeWarning)`` 捕获、``anti_alias=False``、
     ``uncertainty_cent>0``（半 bin 公式可复算）；
  ③ ``last_resample_quality()`` 返回副本（改副本不污染记录）；
  ④ ``load()`` 发生重采样后 ``get_info()`` 的 ``AudioInfo.resample_quality`` 非空；
  ⑤ ``np.interp`` 回退本身保留（length / 谱峰 440，同 test_regression.py:199）；
  ⑥ T05↔T06 链路：``build_measurement_record(resample_quality=
     last_resample_quality())``，线性回退时记录里 ``anti_alias is False``。
"""

from __future__ import annotations

import math
import sys
import types
import warnings

import numpy as np
import pytest

from acouscope.analysis.measurement_record import (
    MEASUREMENT_FIELDS,
    build_measurement_record,
)
from acouscope.audio.io import (
    RESAMPLE_QUALITY,
    AudioIO,
    AudioInfo,
    last_resample_quality,
)

SR = 44100
TARGET_SR = 22050


@pytest.fixture(autouse=True)
def _clean_ledger():
    """每个用例前清空模块级记录，杜绝跨用例污染。"""
    RESAMPLE_QUALITY.clear()
    yield
    RESAMPLE_QUALITY.clear()


def _sine(freq: float = 440.0, duration: float = 0.5) -> np.ndarray:
    return np.sin(2.0 * np.pi * freq * np.arange(int(SR * duration)) / SR)


def _no_samplerate(monkeypatch):
    """确保 import samplerate 抛 ImportError（走 np.interp 回退）。"""
    monkeypatch.setitem(sys.modules, "samplerate", None)


# ----------------------------------------------------------------------
# ① fake samplerate → sinc_best 分支
# ----------------------------------------------------------------------
def test_sinc_best_branch_marks_anti_alias_true(monkeypatch):
    calls = {}

    def _fake_resample(data, ratio, method):
        calls["ratio"] = ratio
        calls["method"] = method
        # 用 numpy 线性插值模拟 sinc 输出（本用例只验质量标记，不验波形）
        n = max(1, int(round(len(data) * ratio)))
        return np.interp(
            np.linspace(0.0, len(data) - 1, n),
            np.arange(len(data)), np.asarray(data, dtype=float),
        )

    fake = types.ModuleType("samplerate")
    fake.resample = _fake_resample
    monkeypatch.setitem(sys.modules, "samplerate", fake)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = AudioIO._resample(_sine(), SR, TARGET_SR)
    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    q = last_resample_quality()
    print("SINC_BEST method=%s ratio=%s q=%s runtime_warnings=%d"
          % (calls.get("method"), calls.get("ratio"), q, len(runtime)))
    assert calls["method"] == "sinc_best"
    assert calls["ratio"] == pytest.approx(TARGET_SR / SR)
    assert len(out) == 11025
    assert not runtime  # sinc 分支不发回退 warning
    assert q == {"method": "sinc_best", "anti_alias": True,
                 "uncertainty_cent": 0.0}
    assert q["anti_alias"] is True


# ----------------------------------------------------------------------
# ② 无 samplerate → warning + anti_alias=False + 半 bin 公式
# ----------------------------------------------------------------------
def test_linear_fallback_warns_and_marks_anti_alias_false(monkeypatch):
    _no_samplerate(monkeypatch)
    with pytest.warns(RuntimeWarning, match="线性插值重采样无抗混叠"):
        out = AudioIO._resample(_sine(), SR, TARGET_SR)
    q = last_resample_quality()
    print("LINEAR_FALLBACK q=%s" % q)
    assert len(out) == 11025
    assert q["method"] == "linear_fallback"
    assert q["anti_alias"] is False
    # 半 bin → 音分公式复算（docstring 约定：n_fft=2048, A4=440）
    half_bin_hz = float(TARGET_SR) / (2.0 * 2048)
    expected = 1200.0 * math.log2((440.0 + half_bin_hz) / 440.0)
    assert q["uncertainty_cent"] == pytest.approx(expected)
    assert q["uncertainty_cent"] > 0.0


def test_warning_category_and_stacklevel(monkeypatch):
    """warning 类别为 RuntimeWarning、stacklevel=2（指向调用方）。"""
    _no_samplerate(monkeypatch)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        AudioIO._resample(_sine(duration=0.1), SR, TARGET_SR)
    assert len(caught) == 1
    w = caught[0]
    print("WARNING category=%s msg=%s filename=%s"
          % (w.category.__name__, w.message, w.filename.split("/")[-1]))
    assert w.category is RuntimeWarning
    assert "测量不确定度未评估" in str(w.message)
    # stacklevel=2 → filename 不是 io.py（而是调用本测试的帧）
    assert not w.filename.endswith("io.py")


# ----------------------------------------------------------------------
# ③ last_resample_quality() 返回副本
# ----------------------------------------------------------------------
def test_last_resample_quality_returns_copy(monkeypatch):
    _no_samplerate(monkeypatch)
    with pytest.warns(RuntimeWarning):
        AudioIO._resample(_sine(duration=0.1), SR, TARGET_SR)
    a = last_resample_quality()
    b = last_resample_quality()
    print("COPY a=%s a is b=%s" % (a, a is b))
    assert a == b and a is not b
    a["anti_alias"] = True  # 改副本
    assert RESAMPLE_QUALITY["anti_alias"] is False  # 记录不受影响
    assert last_resample_quality()["anti_alias"] is False
    # 空记录时返回空 dict（也是副本）
    RESAMPLE_QUALITY.clear()
    empty = last_resample_quality()
    assert empty == {} and empty is not RESAMPLE_QUALITY


# ----------------------------------------------------------------------
# ④ load() 重采样 → AudioInfo.resample_quality 非空
# ----------------------------------------------------------------------
def test_load_then_get_info_carries_resample_quality(tmp_path, monkeypatch):
    import soundfile as sf

    _no_samplerate(monkeypatch)
    wav = tmp_path / "tone.wav"
    sf.write(str(wav), 0.5 * _sine(duration=0.5), SR)
    io = AudioIO()
    with pytest.warns(RuntimeWarning):
        data, sr = io.load(str(wav), sample_rate=TARGET_SR)
    info = io.get_info(str(wav))
    print("LOAD sr=%d len=%d AudioInfo.resample_quality=%s"
          % (sr, len(data), info.resample_quality))
    assert sr == TARGET_SR
    assert isinstance(info, AudioInfo)
    assert info.resample_quality  # 非空
    assert info.resample_quality["anti_alias"] is False
    assert info.resample_quality["method"] == "linear_fallback"


def test_audio_info_default_field_is_optional_none():
    """既有 8 参构造零改动：新字段缺省 None。"""
    info = AudioInfo(
        filepath="x", duration=1.0, sample_rate=SR, channels=1,
        samples=SR, bit_depth=16, format="WAV", file_size=0,
    )
    print("AudioInfo default resample_quality=%r" % info.resample_quality)
    assert info.resample_quality is None
    assert info.duration_str == "0:01.00"


# ----------------------------------------------------------------------
# ⑤ np.interp 回退本身保留（同 test_regression.py::test_resample_numpy_fallback）
# ----------------------------------------------------------------------
def test_numpy_fallback_still_interpolates_correctly(monkeypatch):
    _no_samplerate(monkeypatch)
    with pytest.warns(RuntimeWarning):
        out = AudioIO._resample(_sine(), SR, TARGET_SR)
    spec = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(len(out), d=1.0 / TARGET_SR)
    peak = float(freqs[int(np.argmax(spec))])
    print("FALLBACK len=%d peak_freq=%.3f Hz" % (len(out), peak))
    assert len(out) == 11025
    assert abs(peak - 440.0) < 5.0


# ----------------------------------------------------------------------
# ⑥ T05↔T06 链路：记录里 anti_alias is False
# ----------------------------------------------------------------------
def test_t05_t06_link_record_anti_alias_false_on_fallback(monkeypatch):
    _no_samplerate(monkeypatch)
    with pytest.warns(RuntimeWarning):
        AudioIO._resample(_sine(duration=0.1), SR, TARGET_SR)
    record = build_measurement_record(
        resample_quality=last_resample_quality(),
    )
    print("LINK record.resample_quality=%s" % record["resample_quality"])
    assert tuple(record.keys()) == MEASUREMENT_FIELDS
    assert record["resample_quality"]["anti_alias"] is False
    assert record["resample_quality"]["method"] == "linear_fallback"


def test_t05_t06_link_sinc_best_record_anti_alias_true(monkeypatch):
    """sinc_best 分支链路：记录里 anti_alias is True。"""
    fake = types.ModuleType("samplerate")
    fake.resample = lambda data, ratio, method: np.interp(
        np.linspace(0.0, len(data) - 1, int(len(data) * ratio)),
        np.arange(len(data)), np.asarray(data, dtype=float),
    )
    monkeypatch.setitem(sys.modules, "samplerate", fake)
    AudioIO._resample(_sine(duration=0.1), SR, TARGET_SR)
    record = build_measurement_record(resample_quality=last_resample_quality())
    print("LINK(sinc) record.resample_quality=%s" % record["resample_quality"])
    assert record["resample_quality"]["anti_alias"] is True
