# SPDX-License-Identifier: GPL-3.0-only
"""D 档参考音标定（W-11）测试。REFERENCE_CALIBRATION_TEST_V1

**测试内的合成音只验链路与状态机，不是标定件**（交付件的参考音为真实录音，
由指挥提供；本文件不生成任何交付件）。

覆盖：
① 440 Hz 稳态 → `calibrated`，bias 近 0，稳定段可取；
② 非标称音（500 Hz）→ `pending`，理由含「不是 A4」，bias 保留为诊断量；
③ 强揉弦 → 不得把整段当稳定段（回 pending 或取短稳定段，但不得 n＝全段）；
④ 过短音 → `pending: stable_segment_too_short`；
⑤ 字段面：reference_id／sha256／samplerate／duration_s／stable_segment_s／
  n_frames／std／p95／params_snapshot／provenance.run_id；
⑥ CSV 与 JSON 同值；
⑦ 无 `reference_id` 不得记 `calibrated`（ValueError）。
"""

import json

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.reference_calibration import (  # noqa: E402
    STATUS_CALIBRATED,
    STATUS_PENDING,
    analyze_reference_audio,
    build_reference_payload,
    calibration_csv_rows,
    export_reference_calibration_csv,
    export_reference_calibration_json,
)


def _write_tone(path, freq, *, sr=22050, dur=1.6, vibrato_cents=0.0,
                vibrato_hz=6.0, amp=0.35):
    import numpy as np

    from acouscope.audio import AudioIO

    t = np.arange(int(sr * dur)) / float(sr)
    cents = vibrato_cents * np.sin(2.0 * np.pi * vibrato_hz * t)
    sig = amp * np.sin(2.0 * np.pi * freq * 2.0 ** (cents / 1200.0) * t)
    AudioIO().save(sig.astype(np.float32), sr, str(path))
    return path


def _payload(path, *, reference_id="test_ref"):
    analysis = analyze_reference_audio(path, nominal_hz=440.0)
    return build_reference_payload(
        analysis,
        reference_id=reference_id,
        source="test-synthetic",
        command="pytest",
    )


def test_calibrated_when_tone_matches_nominal(tmp_path):
    """① 440 Hz 稳态 → calibrated；字段面齐全。"""
    path = _write_tone(tmp_path / "a4.wav", 440.0)
    payload = _payload(path)
    assert payload["reference_status"] == STATUS_CALIBRATED
    assert payload["bias_cents_is_diagnostic"] is False
    assert abs(payload["bias_cents"]) <= 50.0
    assert payload["n_frames"] > 20
    assert payload["n_segments"] >= 1
    seg = payload["stable_segment_s"]
    assert seg[0] < seg[1] and seg[1] <= payload["duration_s"]
    for key in (
        "reference_id", "source", "file_sha256", "samplerate", "duration_s",
        "reference_hz_nominal", "reference_hz_measured", "reference_status",
        "calibration_method", "bias_cents", "std_cents", "p95_cents",
        "n_frames", "n_segments", "params_snapshot", "provenance",
    ):
        assert key in payload, key
    assert len(payload["file_sha256"]) == 64
    assert payload["reference_hz_nominal"] == pytest.approx(440.0)
    assert payload["provenance"]["run_id"]
    assert payload["platform_reference_unchanged"]["reference_hz"] == pytest.approx(440.0)


def test_pending_when_tone_is_not_the_nominal_note(tmp_path):
    """② 500 Hz（≈B4+23 音分）→ pending，理由与诊断量并存，不冒充 A4。"""
    path = _write_tone(tmp_path / "b4.wav", 500.0)
    payload = _payload(path)
    assert payload["reference_status"] == STATUS_PENDING
    assert payload["bias_cents_is_diagnostic"] is True
    assert payload["bias_cents"] == pytest.approx(223.5, abs=6.0)
    assert "不是 A4" in payload["pending_reason"]
    assert "B4" in payload["measured_tone"]["classification"]["nearest_note"]
    # 离散量仍给出（与标称无关），且去趋势后不大于原值
    assert payload["std_cents"] is not None
    assert payload["std_cents_detrended"] <= payload["std_cents"] + 1e-6


def test_vibrato_tone_is_not_taken_whole(tmp_path):
    """③ 强揉弦（±120 音分）不得整段当稳定段。"""
    path = _write_tone(tmp_path / "vib.wav", 440.0, vibrato_cents=120.0)
    payload = _payload(path)
    dur = float(payload["duration_s"])
    if payload["reference_status"] == STATUS_CALIBRATED:
        seg = payload["stable_segment_s"]
        assert (seg[1] - seg[0]) < 0.9 * dur, "揉弦段不得整段入选"
    else:
        assert payload["reference_status"] == STATUS_PENDING
        assert payload["stable_segment_s"] is None


def test_too_short_tone_is_pending(tmp_path):
    """④ 0.15 s 短音 → pending，理由指明稳定段不足。"""
    path = _write_tone(tmp_path / "short.wav", 440.0, dur=0.15)
    payload = _payload(path)
    assert payload["reference_status"] == STATUS_PENDING
    assert "稳定段" in payload["pending_reason"]
    assert payload["measured_tone"] is None
    assert payload["n_frames"] == 0


def test_independent_check_agrees_with_pitch_track(tmp_path):
    """⑤b 独立法（FFT 主峰／自相关）与逐帧中位同指一个基频（排除八度误判）。"""
    path = _write_tone(tmp_path / "b4c.wav", 500.0)
    payload = _payload(path)
    indep = payload["independent_check"]
    assert indep["fft_peak_hz"] == pytest.approx(500.0, abs=6.0)
    assert indep["autocorr_f0_hz"] == pytest.approx(500.0, abs=6.0)
    assert indep["agreement_hz"] < 5.0
    assert abs(indep["fft_peak_hz"] - payload["reference_hz_measured"]) < 6.0
    # 谐波列：k=1 为 0 dB 参考，k=2 不应高于 k=1
    assert indep["harmonic_peaks_rel_db"]["k=1"] == pytest.approx(0.0, abs=0.6)


def test_calibrated_requires_reference_id(tmp_path):
    """⑦ 无 reference_id 不得记 calibrated（与 dsp.reference_status 同规）。"""
    path = _write_tone(tmp_path / "a4b.wav", 440.0)
    with pytest.raises(ValueError):
        _payload(path, reference_id="")


def test_csv_matches_json(tmp_path):
    """⑥ CSV 单行与 JSON 同值（pending 的 bias 留空而非 0）。"""
    path = _write_tone(tmp_path / "b4b.wav", 500.0)
    payload = _payload(path)
    export_reference_calibration_json(tmp_path / "c.json", payload)
    export_reference_calibration_csv(tmp_path / "c.csv", payload)
    loaded = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    import csv

    with open(tmp_path / "c.csv", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    row = rows[0]
    assert row["reference_id"] == loaded["reference_id"]
    assert row["file_sha256"] == loaded["file_sha256"]
    assert int(row["n_frames"]) == loaded["n_frames"]
    assert float(row["bias_cents"]) == pytest.approx(loaded["bias_cents"])
    assert row["reference_status"] == "pending"
    assert calibration_csv_rows(payload)[0]["reference_status"] == "pending"
