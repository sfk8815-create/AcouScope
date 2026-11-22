# SPDX-License-Identifier: GPL-3.0-only
"""三型分布一站式入口测试（任务件-20261026 · T-1／T-2／T-3）。READOUT_TEST_V1

覆盖：
① ``cases_from_json``：输入清单由调用方给（平台不内建具体录音）；
② ``analyze_case``：段行／分布／扫描同源同 τ，``run_id`` 贯通；
③ ``reconcile``：图件入图段数 ＋ 未入三型 ＝ 表合计，差值逐例列明；
④ ``run_batch``：落盘件齐备且 MANIFEST 含图件哈希（T-3 交付惯例）。

音频夹具为**合成信号**（正弦＋轻微起伏），只验链路与契约，不含任何真实录音，
也不构成精度标定。
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.cavity_type import LABELS  # noqa: E402
from acouscope.analysis.readout import (  # noqa: E402
    RecordingCase,
    analyze_case,
    cases_from_json,
    reconcile,
    run_batch,
)
from acouscope.analysis.tonic_ref import REF_ABSOLUTE, REF_MAIN_TONE  # noqa: E402


def _tone(path, sr=44100, dur=6.0, freq=440.0, depth_cents=12.0, rate_hz=5.0):
    """合成一段带轻微起伏的稳态音（只验链路，不作标定）。"""
    import numpy as np

    from acouscope.audio import AudioIO

    t = np.arange(int(sr * dur)) / float(sr)
    cents = depth_cents * np.sin(2.0 * np.pi * rate_hz * t)
    sig = 0.4 * np.sin(2.0 * np.pi * freq * 2.0 ** (cents / 1200.0) * t)
    AudioIO().save(sig.astype(np.float32), sr, str(path))
    return path


def test_cases_from_json_is_caller_supplied(tmp_path):
    """① 输入清单来自调用方 JSON（平台不内建任何具体录音）。"""
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {"recording_id": "r1", "audio_path": "/tmp/a.wav", "label": "甲组",
                     "anchor_offset_cents": 12.0, "anchor_source": "空弦"},
                    {"recording_id": "r2", "audio_path": "/tmp/b.wav"},
                ]
            }
        ),
        encoding="utf-8",
    )
    cases = cases_from_json(path)
    assert [case.recording_id for case in cases] == ["r1", "r2"]
    assert cases[0].anchor_offset_cents == pytest.approx(12.0)
    assert cases[0].title() == "甲组"
    assert cases[1].title() == "r2"  # 无呈现名 ⇒ 退回录音 id


def test_cases_from_json_reads_per_case_template(tmp_path):
    """逐例参照系：JSON 键白名单新增 ``template``，缺省 None（退回批次级）。

    2026-10-31《律制参照系整体修正》要求古琴／二胡诸例用不同律制作参照系，
    故模板须能逐例指定；缺省语义不变（仍走批次级 ``--template``）。
    """
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {"recording_id": "r1", "audio_path": "/tmp/a.wav", "template": "qin_lu"},
                    {"recording_id": "r2", "audio_path": "/tmp/b.wav"},
                ]
            }
        ),
        encoding="utf-8",
    )
    cases = cases_from_json(path)
    assert cases[0].template == "qin_lu"
    assert cases[1].template is None  # 未给 ⇒ 退回批次级


def test_run_batch_registers_per_case_template_in_run_id(tmp_path):
    """逐例换参照系 ⇒ run_id 必变，并在 config.templates 留证（内容定址）。

    若只换 case.template 而不登记进描述符，就会出现「同一运行标识、两种参照系」，
    直接违反平台的内容定址约定。本测试即该约定的守卫。
    """
    audio = _tone(tmp_path / "tone_case_template.wav")
    case_spec = {"recording_id": "synth", "audio_path": str(audio), "label": "合成例"}

    def _run(template_key: str | None, out: Path) -> dict:
        spec = dict(case_spec)
        if template_key is not None:
            spec["template"] = template_key
        path = tmp_path / f"cases_{template_key}.json"
        path.write_text(json.dumps({"cases": [spec]}), encoding="utf-8")
        summary = run_batch(cases_from_json(path), out_dir=out)
        return json.loads((out / "run_descriptor.json").read_text(encoding="utf-8"))

    baseline = _run(None, tmp_path / "out_base")
    switched = _run("qin_lu", tmp_path / "out_qin")
    # 缺省不在配置块内出现 ⇒ 历史运行的 run_id 不受影响
    assert "templates" not in baseline["config"]
    assert baseline["config"]["template"] == "12tet"
    # 逐例登记：写进 run_id 哈希面 ⇒ 换参照系即换运行标识
    assert switched["config"]["templates"] == [
        {"recording_id": "synth", "template": "qin_lu"}
    ]
    assert switched["run_id"] != baseline["run_id"]


def test_analyze_case_shares_one_tau_across_artifacts(tmp_path):
    """② 段行／分布／扫描同源同 τ，run_id 贯通三件（T-3）。"""
    case = RecordingCase(
        recording_id="synth",
        audio_path=str(_tone(tmp_path / "tone.wav")),
        label="合成例",
    )
    result = analyze_case(case, run_id_="run-deadbeef")
    assert result["label"] == "合成例"
    assert len(result["windows"]) >= 1
    for mode in (REF_ABSOLUTE, REF_MAIN_TONE):
        dist = result["distributions"][mode]
        sweep = result["sweeps"][mode]
        assert dist["run_id"] == "run-deadbeef"
        assert sweep["run_id"] == "run-deadbeef"
        assert sweep["tau_declaration"]["tau_status"] == dist["tau_status"]
        # 扫描件与被扫段行同源：逐 τ 的标签数 ＝ 段数
        for labels in sweep["labels_by_tau"].values():
            assert len(labels) == len(result["rows"][mode])
        # 计数自洽：四值之和 ＝ 合计
        counts = dist["counts_per_recording"]
        assert sum(counts[label] for label in LABELS) == counts["合计"]


def test_reconcile_identity_holds_per_recording(tmp_path):
    """③ 入图段数 ＋ 未入三型 ＝ 表合计（差＝无往复度读数段，逐例列明）。"""
    case = RecordingCase(
        recording_id="synth",
        audio_path=str(_tone(tmp_path / "tone2.wav")),
        label="合成例",
    )
    report = reconcile([analyze_case(case, run_id_="run-0000ffff")])
    assert report["per_recording"], report
    for entry in report["per_recording"]:
        assert entry["入图段数+未入三型=合计"] is True, entry
        assert entry["图_未入三型"] == entry["表_未分类"] + entry["差_无往复度读数段"]
        assert entry["图_入图段数"] + entry["图_未入三型"] == entry["n_segments"]
        assert entry["run_id"] == "run-0000ffff"


def test_run_batch_writes_artifacts_and_manifest(tmp_path):
    """④ 批量运行落盘：分布／扫描／汇总／分面数据／MANIFEST 齐备。"""
    audio = _tone(tmp_path / "tone3.wav")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {"cases": [{"recording_id": "synth", "audio_path": str(audio), "label": "合成例"}]}
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    figures = tmp_path / "fig"
    summary = run_batch(cases_from_json(cases_path), out_dir=out, figure_out=figures,
                        figure_stem="figure_b")
    assert summary["run_id"]
    for name in ("run_descriptor.json", "type_distribution.absolute.json",
                 "type_distribution.main_tone.json", "type_distribution.csv",
                 "dual_calibre_pairing.csv", "tau_sweep_summary.absolute.json",
                 "tau_sweep_summary.main_tone.json",
                 "tau_sweep.synth.absolute.json", "figure_b_panels.json",
                 "MANIFEST.md"):
        assert (out / name).is_file(), name
    assert (figures / "figure_b.png").is_file()
    assert (figures / "figure_b.pdf").is_file()
    # T-3：MANIFEST 记图件哈希，图件与表件同 run_id
    text = (out / "MANIFEST.md").read_text(encoding="utf-8")
    assert summary["run_id"] in text
    assert "figure_b.png" in text
    panels = json.loads((out / "figure_b_panels.json").read_text(encoding="utf-8"))
    assert panels["run_id"] == summary["run_id"]
    assert panels["tau_status"] == "unspecified_sign_based"
