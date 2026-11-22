# SPDX-License-Identifier: GPL-3.0-only
"""分母口径、低频标注与主档图件（W-8／W-9／W-10）测试。READOUT_W8_TEST_V1

只验契约与恒等，不作标定、不判阈值：

- W-8：四值分母＝可判段（``n_judgable``）；不可判段单列且不进四值；
  ``n_high_conf``／``n_low_conf``／``n_conf_missing`` 显式且和为 ``n_all``；
  三式恒等逐例成立；件内正名「往复窗不可判」并说明≠类型不可判；CSV 与 JSON 同步。
- W-9：低频不可靠段单列（清单＋计数，0 亦写 0）、``excluded_from_denominators``；
  候选面与输出面仍分列；正文分母 ``n_denominator_body`` 与 W-8 分母并陈。
- W-10：图分面入图＝``n_axis``、未入三型＝``n_composite``、``n_total``＝可判段；
  主档图与对照档图分件；闸件逐例给出 ``checks_named`` 三项。
"""

import json

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.readout import RecordingCase, run_batch  # noqa: E402

TAUS = [None, 10.0, 20.0, 30.0]


def _tone(path, sr=22050, dur=8.0, freq=220.0, depth_cents=40.0, rate_hz=1.5):
    import numpy as np

    from acouscope.audio import AudioIO

    t = np.arange(int(sr * dur)) / float(sr)
    cents = depth_cents * np.sin(2.0 * np.pi * rate_hz * t)
    sig = 0.4 * np.sin(2.0 * np.pi * freq * 2.0 ** (cents / 1200.0) * t)
    AudioIO().save(sig.astype(np.float32), sr, str(path))
    return path


def _run(tmp_path, *, fmin=80.0, fmax=1000.0, freq=220.0, name="out",
         figures=True):
    audio = _tone(tmp_path / "tone.wav", freq=freq)
    case = RecordingCase(recording_id="synth", audio_path=str(audio), label="合成例")
    out = tmp_path / name
    fig = tmp_path / f"fig_{name}"
    summary = run_batch(
        [case],
        out_dir=out,
        window_s=8.0,
        min_window_s=4.0,
        fmin=fmin,
        fmax=fmax,
        tonic_window_s=4.0,
        tau_values=TAUS,
        tau_analysis=10.0,
        tau_provenance="test:explicit",
        figure_out=(fig if figures else None),
        cases_source="<cases.json>",
    )
    return summary, out, fig


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("band_file", [
    "type_distribution.tau_analysis.absolute.json",
    "type_distribution.absolute.json",
])
def test_w8_counts_denominator_is_judgable(tmp_path, band_file):
    """W-8：四值之和＝n_judgable；不可判不进四值；三式恒等成立。"""
    _, out, _ = _run(tmp_path, figures=False)
    payload = _load(out / band_file)[0]
    counts = payload["counts_per_recording"]
    total = sum(counts[label] for label in ("上趋", "下趋", "平直", "未分类"))
    assert total == counts["合计"] == payload["n_judgable"]
    assert counts["合计"] != payload["n_all"] or payload["n_indeterminate"] == 0
    # 六分母量＋W-9 两量逐字在件
    for key in (
        "n_all", "n_judgable", "n_axis", "n_composite", "n_indeterminate",
        "n_high_conf", "n_low_conf", "n_conf_missing", "n_coexist",
        "n_low_freq_unreliable", "n_denominator_body",
    ):
        assert key in payload, key
    assert payload["n_high_conf"] + payload["n_low_conf"] + payload["n_conf_missing"] == payload["n_all"]
    assert payload["n_axis"] + payload["n_composite"] == payload["n_judgable"]
    assert payload["n_all"] == payload["n_judgable"] + payload["n_indeterminate"]
    checks = {item["expr"]: item["ok"] for item in payload["identity_checks"]}
    assert len(checks) == 4
    assert all(checks.values())
    assert payload["counts_denominator"] == "judgable_segments_v1"
    assert "往复窗不可判" in payload["indeterminate_name_zh"]
    assert "不等于" in payload["indeterminate_note_zh"]


def test_w8_indeterminate_segments_carry_no_type_label(tmp_path):
    """W-8：不可判段不再拿类型标签（原标签退到 ``label_if_type_applied``）。"""
    _, out, _ = _run(tmp_path, figures=False)
    block = _load(out / "three_column.synth.json")["by_ref_mode"]["absolute"]
    indeterminate = [item for item in block["segments"] if item["indeterminate"]]
    assert indeterminate, "本例应有往复窗不可判段（否则测不到）"
    for item in indeterminate:
        assert item["cavity_type"] is None
        assert item["label_if_type_applied"] in ("上趋", "下趋", "平直", "未分类")
        assert item["counts_in_type_distribution"] is False
        assert item["recurrence_window_insufficient"] is True
    judged = [item for item in block["segments"] if not item["indeterminate"]]
    for item in judged:
        assert item["cavity_type"] in ("上趋", "下趋", "平直", "未分类")
    buckets = {row["cavity_type"] for row in block["counts_cross"]}
    assert "往复窗不可判" in buckets


def test_w8_csv_syncs_with_json(tmp_path):
    """W-8 验收：CSV 与 JSON 同步（四值＋分母量逐格相同）。"""
    _, out, _ = _run(tmp_path, figures=False)
    import csv

    with open(out / "type_distribution.tau_analysis.csv", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    payloads = _load(out / "type_distribution.tau_analysis.absolute.json") + _load(
        out / "type_distribution.tau_analysis.main_tone.json"
    )
    assert len(rows) == len(payloads)
    for row, payload in zip(rows, payloads):
        assert int(row["合计"]) == payload["n_judgable"]
        assert int(row["n_indeterminate"]) == payload["n_indeterminate"]
        assert int(row["n_denominator_body"]) == payload["n_denominator_body"]
        assert int(row["正文分母_合计"]) == payload["counts_per_recording_excluding_low_freq"]["合计"]


def test_w9_low_frequency_unreliable_is_listed(tmp_path):
    """W-9：低频不可靠段单列（含 0 例也给 0）；两面范围仍分列。"""
    _, out, _ = _run(tmp_path, fmin=40.0, fmax=2000.0, freq=55.0, figures=False)
    payload = _load(out / "grid_boundary.synth.json")
    assert payload["excluded_from_denominators"] is True
    listed = payload["low_frequency_unreliable_segments"]
    assert set(listed) == {"absolute", "main_tone"}
    for block in listed.values():
        assert "n" in block and "segment_ids" in block
        assert block["n"] == len(block["segment_ids"])
    counts = payload["n_low_frequency_unreliable_segments"]
    assert set(counts) == {"absolute", "main_tone"}
    assert payload["candidate_face"]["grid_clamp_below_frames"] > 0
    assert "candidate_range_hz" in payload["candidate_face"]
    assert "hmm_output_range_hz" in payload["output_face"]
    impact = payload["denominator_impact"]["absolute"]
    assert impact["n_denominator_body"] == (
        impact["n_judgable"] - impact["n_low_freq_unreliable"]
    )
    summary = _load(out / "grid_boundary_summary.json")
    for row in summary["per_recording"]:
        assert "low_frequency_unreliable_segments" in row
        assert row["excluded_from_denominators"] is True


def test_w10_figure_shares_denominator_with_main_table(tmp_path):
    """W-10：图／表同分母；主档图与对照档图分件；闸件三项逐例给结果。"""
    summary, out, fig = _run(tmp_path)
    # 主档图 = figure_b，对照档图 = figure_b_control
    assert (fig / "figure_b.png").is_file()
    assert (fig / "figure_b_control.png").is_file()
    assert set(summary["figures"]) == {"main_declared", "control"}
    panels = _load(out / "figure_b_panels.tau_analysis.json")
    table = _load(out / "type_distribution.tau_analysis.absolute.json")[0]
    panel = panels["panels"][0]
    assert panel["denominators"]["n_axis"] == table["n_axis"]
    assert panel["denominators"]["n_indeterminate"] == table["n_indeterminate"]
    assert len(panel["rows"]) == table["n_judgable"]
    assert set(panel["rows"][0]) >= {"cavity_type", "turns", "low_frequency_unreliable"}
    check = _load(out / "figure_table_check.tau_analysis.json")
    assert check["pass"] is True
    for entry in check["per_recording"]:
        assert all(entry["checks_named"].values()), entry
        assert entry["figure_plotted"] == entry["table_n_axis"]
        assert entry["figure_excluded"] == entry["table_n_composite"]
        assert entry["figure_total"] == entry["table_n_judgable"]
    control_check = _load(out / "figure_table_check.json")
    assert control_check["pass"] is True
    assert control_check["tau_band"] == "control_sign_based"
    assert check["tau_band"] == "main_declared"


def test_w8_w9_policy_enters_run_id(tmp_path):
    """口径进了 run_id：同参同输入两跑同 id（口径为常量），且 config 记了口径名。"""
    first, out_a, _ = _run(tmp_path, name="a", figures=False)
    second, _, _ = _run(tmp_path, name="b", figures=False)
    cfg = _load(out_a / "run_descriptor.json")["config"]
    assert cfg["denominator_policy"] == "judgable_segments_v1"
    assert cfg["low_frequency_excluded_from_body_denominator"] is True
    assert cfg["indeterminate_name"] == "往复窗不可判"
    assert first["run_id"] == second["run_id"]
