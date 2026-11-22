# SPDX-License-Identifier: GPL-3.0-only
"""平台精度标定导出判据（任务-20261025-平台图导出 乙）。

三档状态的行为必须分得开：``pending``（无 D 档参考音，**不出标定数**）／
``chain_only``（合成只验链路，**不得称标定**）／``measured``（真测真算）。
"""

import csv
import json

import numpy as np
import pytest
import soundfile as sf

from acouscope.analysis.calibration_export import (
    CALIBRATION_COLUMNS,
    PRECISION_PRESETS,
    STATUS_CHAIN_ONLY,
    STATUS_MEASURED,
    STATUS_PENDING,
    build_calibration_payload,
    calibration_report,
    calibration_rows,
    calibration_table_rows,
    export_calibration_csv,
    export_calibration_json,
    reference_pairs_from_signal,
)

SR = 44100


def _tone(path, freq_hz=440.0, dur=1.5):
    t = np.arange(int(SR * dur)) / SR
    sf.write(str(path), 0.2 * np.sin(2 * np.pi * freq_hz * t), SR)
    return path


def test_pending_when_no_reference():
    """D 档未到 ⇒ pending，四项统计量一律 None（禁填 0 冒充）。"""
    payload = build_calibration_payload(dataset="D 档待提供")
    assert payload["status"] == STATUS_PENDING
    assert payload["is_calibration"] is False
    stats = payload["stats"]
    assert stats["n"] == 0
    assert stats["mean_bias_cents"] is None
    assert stats["dispersion_cents"] is None
    assert stats["p95_abs_cents"] is None
    assert "参考音" in payload["reason"]


def test_synth_is_chain_only_not_calibration():
    """合成信号只验链路：有读数但明确 is_calibration=False。"""
    payload = build_calibration_payload(synth=True)
    assert payload["status"] == STATUS_CHAIN_ONLY
    assert payload["is_calibration"] is False
    assert payload["stats"]["n"] > 0
    assert "不构成标定" in payload["reason"]


def test_measured_from_reference_tone(tmp_path):
    """真参考音：440 Hz 稳态长音对 440 参考 ⇒ 偏差近 0，标定成立。"""
    path = _tone(tmp_path / "a4.wav", 440.0)
    payload = build_calibration_payload(reference_path=path, ref_hz=440.0, dataset="合成参考音")
    assert payload["status"] == STATUS_MEASURED
    assert payload["is_calibration"] is True
    stats = payload["stats"]
    assert stats["n"] > 20, f"配对数过少：{stats['n']}"
    assert abs(stats["mean_bias_cents"]) < 5.0, stats
    assert stats["p95_abs_cents"] >= 0.0
    assert payload["params_snapshot"]["a4_reference_hz"] == 440.0


def test_reference_mismatch_sign_convention(tmp_path):
    """参考频率设 442 而音源 440 ⇒ 平均偏差应为负（测量低于参考），量级≈−7.85 音分。"""
    path = _tone(tmp_path / "a4.wav", 440.0)
    payload = build_calibration_payload(reference_path=path, ref_hz=442.0)
    bias = payload["stats"]["mean_bias_cents"]
    assert bias == pytest.approx(1200.0 * np.log2(440.0 / 442.0), abs=1.0)
    assert bias < 0


def test_reference_pairs_skip_silence():
    """静音帧不参与配对（不补零、不造样本）。"""
    sig = np.zeros(SR, dtype=float)
    sig[: SR // 2] = 0.2 * np.sin(2 * np.pi * 440.0 * np.arange(SR // 2) / SR)
    pairs = reference_pairs_from_signal(sig, SR)
    assert len(pairs) > 0
    assert len(pairs) < SR  # 静音半段未进入配对
    assert all(measured == pytest.approx(0.0, abs=5.0) for measured, _ref in pairs)


def test_export_json_and_csv(tmp_path):
    """导出 JSON／CSV：CSV 一行一档，数值与 payload 同源。"""
    path = _tone(tmp_path / "a4.wav", 440.0)
    payload = build_calibration_payload(reference_path=path, dataset="导出用例")
    json_path = tmp_path / "calib.json"
    csv_path = tmp_path / "calib.csv"
    export_calibration_json(json_path, payload)
    export_calibration_csv(csv_path, payload)

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["stats"]["n"] == payload["stats"]["n"]
    assert loaded["status"] == STATUS_MEASURED

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert int(rows[0]["n"]) == payload["stats"]["n"]
    assert rows[0]["status"] == STATUS_MEASURED
    assert rows[0]["is_calibration"] == "1"
    assert float(rows[0]["mean_bias_cents"]) == pytest.approx(
        payload["stats"]["mean_bias_cents"]
    )

    table = calibration_table_rows(payload)
    assert list(table[0]) == [
        "dataset", "status", "is_calibration", "ref_hz", "n",
        "mean_bias_cents", "dispersion_cents", "p95_abs_cents",
        "a4_reference_hz", "pitch_backend", "reason",
    ]


def test_precision_row_preset_and_alias(tmp_path):
    """呈现层预设：paper 列序只取七列；旧名 build_calibration_payload 等价新名。"""
    path = _tone(tmp_path / "a4.wav", 440.0)
    payload = calibration_report(reference_path=path, dataset="预设用例")
    assert payload == build_calibration_payload(reference_path=path, dataset="预设用例")

    paper = calibration_rows(payload, preset="paper")
    assert list(paper[0]) == list(PRECISION_PRESETS["paper"])
    assert paper[0]["status"] == STATUS_MEASURED
    assert "ref_hz" not in paper[0] and "is_calibration" not in paper[0]

    full = calibration_rows(payload)
    assert list(full[0]) == list(CALIBRATION_COLUMNS)
    assert full[0]["n"] == paper[0]["n"]

    csv_path = tmp_path / "paper.csv"
    export_calibration_csv(csv_path, payload, preset="paper")
    with open(csv_path, newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == list(PRECISION_PRESETS["paper"])


def test_unknown_preset_rejected():
    with pytest.raises(ValueError):
        calibration_rows({"stats": {}}, preset="nope")
