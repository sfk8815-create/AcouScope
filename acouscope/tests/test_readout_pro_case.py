# SPDX-License-Identifier: GPL-3.0-only
"""丙案出件补项（W-1—W-7）测试。READOUT_PRO_CASE_TEST_V1

覆盖（与设计约定逐项对位，**只验契约与判据自洽**，不作标定）：

- W-1：主档／对照档双档并陈，``tau_status`` 逐字、``run_id`` 同值；
- W-2：改判明细 ``type_flips`` 与逐方向计数、分母＝配对段数；
- W-3：各 τ 档四值计数（完整矩阵，各档合计恒等）；
- W-4：三栏并行＋``indeterminate`` 单列＋六分母量恒等式；
- W-5：两档音域差值件（只读落盘件）；
- W-6：候选面与输出面**分列**（钳位只由候选面成立）；
- W-7：口径面进 ``run_descriptor['config']`` ⇒ 进 ``run_id``。

音频为**合成信号**（正弦／低频正弦），只验链路与契约，不含任何真实录音。
"""

import json

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.readout import (  # noqa: E402
    RecordingCase,
    run_batch,
)
from acouscope.analysis.readout_extras import (  # noqa: E402
    CONFIG_KEYS,
    fminfmax_diff,
)

TAUS = [None, 10.0, 20.0, 30.0]


def _tone(path, sr=8000, dur=8.0, freq=220.0, depth_cents=25.0, rate_hz=5.0):
    """合成一段带起伏的稳态音（只验链路，不作标定）。"""
    import numpy as np

    from acouscope.audio import AudioIO

    t = np.arange(int(sr * dur)) / float(sr)
    cents = depth_cents * np.sin(2.0 * np.pi * rate_hz * t)
    sig = 0.4 * np.sin(2.0 * np.pi * freq * 2.0 ** (cents / 1200.0) * t)
    AudioIO().save(sig.astype(np.float32), sr, str(path))
    return path


def _run(tmp_path, *, fmin=60.0, fmax=1500.0, tau_analysis=10.0, name="out",
         freq=220.0):
    # 同一路径复用同一份合成音 ⇒ 同参两次跑的 run_id 才应当相同（含 audio_name 定址）
    audio = _tone(tmp_path / "tone.wav", freq=freq)
    case = RecordingCase(recording_id="synth", audio_path=str(audio), label="合成例")
    out = tmp_path / name
    summary = run_batch(
        [case],
        out_dir=out,
        window_s=8.0,
        min_window_s=4.0,
        fmin=fmin,
        fmax=fmax,
        tonic_window_s=4.0,
        tau_values=TAUS,
        tau_analysis=tau_analysis,
        tau_provenance="test:explicit",
        cases_source="<cases.json>",
    )
    return summary, out


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_w7_config_enters_run_id(tmp_path):
    """W-7：口径面进 ``config``；换口径维即换 ``run_id``（旧件只登 MANIFEST 的缺口）。"""
    base, out = _run(tmp_path, name="a")
    cfg = _load(out / "run_descriptor.json")["config"]
    for key in CONFIG_KEYS:
        assert key in cfg, key
    assert cfg["tonic_window_s"] == 4.0
    # grep -c '"tonic_window_s"' 须为 1（键只出现一次，机读面唯一）
    text = (out / "run_descriptor.json").read_text(encoding="utf-8")
    assert text.count('"tonic_window_s"') == 1
    other, _ = _run(tmp_path, tau_analysis=20.0, name="b")
    assert other["run_id"] != base["run_id"]
    same, _ = _run(tmp_path, name="c")
    assert same["run_id"] == base["run_id"]


def test_w1_dual_band_distributions(tmp_path):
    """W-1：主档与对照档并陈；状态逐字、run_id 同值、四值行和＝合计。"""
    summary, out = _run(tmp_path)
    main = _load(out / "type_distribution.tau_analysis.absolute.json")
    control = _load(out / "type_distribution.absolute.json")
    assert main and control
    m, c = main[0], control[0]
    assert m["tau_band"] == "main_declared"
    assert m["tau_cents"] == pytest.approx(10.0)
    assert m["tau_status"] == "run_config_declared_uncalibrated"
    assert m["tau_provenance"] == "test:explicit"
    assert m["calibration_note"] == "未经参考语料标定"
    assert c["tau_band"] == "control_sign_based"
    assert c["tau_cents"] is None
    assert c["tau_status"] == "unspecified_sign_based"
    assert m["run_id"] == c["run_id"] == summary["run_id"]
    assert m["tau_analysis"] == pytest.approx(10.0)
    for payload in (m, c):
        counts = payload["counts_per_recording"]
        assert sum(counts[label] for label in ("上趋", "下趋", "平直", "未分类")) == counts["合计"]
    # 主档不得写成已标定
    assert "calibrated" != m["tau_status"]


def test_w2_type_flips_detail_and_rate(tmp_path):
    """W-2：明细×方向计数自洽；分母＝配对段数；未配对段按档重出。"""
    _, out = _run(tmp_path)
    for name in ("dual_calibre_flips.synth.json", "dual_calibre_pairing.json",
                 "dual_calibre_pairing.tau_analysis.json"):
        assert (out / name).is_file(), name
    bands = _load(out / "dual_calibre_flips.synth.json")["bands"]
    assert set(bands) == {"main_declared", "control_sign_based"}
    for band, block in bands.items():
        assert sum(block["type_flip_counts"].values()) == len(block["type_flips"])
        for flip in block["type_flips"]:
            assert flip["label_from"] != flip["label_to"]
            assert flip["label_from"] in ("上趋", "下趋", "平直", "未分类")
        rate = block["flip_rate_dual"]
        assert rate is None or 0.0 <= rate <= 1.0
        assert block["flip_denominator"] == "matched_pairs"
        assert block["unpaired_segments"] == block["unmatched_a"], band
    rows = _load(out / "dual_calibre_pairing.tau_analysis.json")
    assert rows[0]["tau_band"] == "main_declared"
    assert rows[0]["tau_cents"] == pytest.approx(10.0)
    assert rows[0]["配对段数"] == bands["main_declared"]["matched_pairs"]
    assert rows[0]["未配对段"] == bands["main_declared"]["unpaired_segments"]


def test_w3_counts_by_tau_matrix(tmp_path):
    """W-3：完整矩阵（例×口径×档×四值）＋逐档翻转数；各档合计恒等。"""
    _, out = _run(tmp_path)
    case_file = _load(out / "counts_by_tau.synth.json")
    for mode in ("absolute", "main_tone"):
        block = case_file["by_ref_mode"][mode]
        assert set(block["counts_by_tau"]) == {"None", "10.0", "20.0", "30.0"}
        totals = {key: row["合计"] for key, row in block["counts_by_tau"].items()}
        assert len(set(totals.values())) == 1, "各档分母漂移"
        for row in block["counts_by_tau"].values():
            assert sum(row[label] for label in ("上趋", "下趋", "平直", "未分类")) == row["合计"]
        assert set(block["flip_counts_by_tau"]) == {"None→10.0", "10.0→20.0", "20.0→30.0"}
    summary = _load(out / "counts_by_tau_summary.json")
    assert len(summary["matrix"]) == 8  # 2 口径 × 4 档
    assert len(summary["flips_matrix"]) == 6
    assert summary["no_recommendation"]


def test_w4_three_column_identity_and_single_listed_indeterminate(tmp_path):
    """W-4：三栏并行＋不可判单列；六分母量恒等式成立；并见不是互斥类。"""
    _, out = _run(tmp_path)
    block = _load(out / "three_column.synth.json")["by_ref_mode"]["absolute"]
    den = block["denominators"]
    # W-8 起另含 n_high_conf／n_low_conf／n_conf_missing／n_low_freq_unreliable／
    # n_denominator_body，故此处断言「包含」而非「等于」（旧六量仍在）
    assert set(den) >= {
        "n_all", "n_judgable", "n_axis", "n_composite", "n_indeterminate", "n_coexist",
    }
    assert den["n_axis"] + den["n_composite"] + den["n_indeterminate"] == den["n_all"]
    assert block["identity_check"]["ok"] is True
    assert den["n_judgable"] == den["n_all"] - den["n_indeterminate"]
    for item in block["segments"]:
        for key in ("cavity_type", "low_confidence", "coexist_netflat_segturn",
                    "indeterminate"):
            assert key in item
        if item["indeterminate"]:
            assert item["indeterminate_reason"] in (
                "edge_deviation_missing", "insufficient_valid_frames",
            )
    assert block["priority_note"]
    assert "threshold_sources" in block["criteria"]
    summary = _load(out / "three_column_summary.json")
    assert summary["tau_status"] == "run_config_declared_uncalibrated"
    per = summary["per_recording"][0]["by_ref_mode"]["absolute"]
    assert per["identity_check"]["ok"] is True
    assert "n_coexist" in per["denominators"]


def test_w6_grid_boundary_faces_are_separate(tmp_path):
    """W-6：候选面与输出面分列；钳位由候选面成立（低频例必触发）。"""
    _, out = _run(tmp_path, fmin=40.0, fmax=2000.0, name="low", freq=55.0)
    payload = _load(out / "grid_boundary.synth.json")
    cand = payload["candidate_face"]
    outp = payload["output_face"]
    assert "candidate_range_hz" in cand
    assert "hmm_output_range_hz" in outp
    assert cand["grid_clamp_below_frames"] >= 0
    # 55 Hz 级低频：候选必低于 61.735 Hz（钳位由候选面给出）
    assert cand["candidate_range_hz"][0] is not None
    assert cand["grid_clamp_below_frames"] > 0
    assert payload["paths"] and all("applies" in item for item in payload["paths"])
    summary = _load(out / "grid_boundary_summary.json")
    assert summary["grid_min_hz"] == pytest.approx(61.735)


def test_w5_fminfmax_diff_reads_artifacts(tmp_path):
    """W-5：两档各一套件，差值件只读落盘件；除音域外无参数漂移。"""
    base, base_dir = _run(tmp_path, name="base")
    var, var_dir = _run(tmp_path, fmin=40.0, fmax=2000.0, name="variant")
    diff = fminfmax_diff(base_dir, var_dir)
    assert diff["fminfmax_variant"]["base"] == "fmin60_fmax1500"
    assert diff["fminfmax_variant"]["variant"] == "fmin40_fmax2000"
    assert diff["params_identical_except_audio_range"] is True, diff["param_drift"]
    assert diff["run_ids"] == {"base": base["run_id"], "variant": var["run_id"]}
    case = diff["per_recording"][0]
    assert case["recording_id"] == "synth"
    assert len(case["cells"]) == 8  # 2 口径 × 4 档
    assert set(case["low_confidence"]) == {"base", "variant"}
    assert set(case["coexist"]) == {"base", "variant"}
