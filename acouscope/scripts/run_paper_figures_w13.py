# SPDX-License-Identifier: GPL-3.0-only
"""W-13 律制参照系整体修正：论文三图按**逐例主参照**重出（不出结论句）。

只读平台公开 API（``acouscope.visualization.figures``），不复制任何平台取数逻辑：

- 图 4-1（paper_A）：管平湖 26.140–27.150 s 段曲线，HMM 取数网格按**本例主参照**重建；
- 图 4-2（paper_C）：古琴两例首窗音级归属对照，**模板集＝论文模板集**（含琴律与
  纯律，无印度／阿拉伯），锚照 cases.json（空弦实测，平台不猜）；
- 图 4-3（paper_B）：取自 W-13 运行件 ``figure_b_panels.tau_analysis.json``（不自行重算）。

用法：

    cd acouscope && export LC_ALL=C.UTF-8 PYTHONPATH=src QT_QPA_PLATFORM=offscreen
    .venv/bin/python scripts/run_paper_figures_w13.py
    .venv/bin/python scripts/run_paper_figures_w13.py --skip-curve --skip-comparison
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "03_Docs_and_Assets"
RUN_DIR = DOCS / "platform_paper_run_20261031_qinlu"
FIG_OUT = DOCS / "platform_figures_20261031_qinlu"
AUDIO_DIR = ROOT / "Essay_writing" / "audio_files"
CASES = RUN_DIR / "cases.json"

#: 图 4-1：管平湖《良宵引》正文所引段（沿用 2026-10-25 裁切约定）
CURVE_SEGMENT = (26.140, 27.150)
PAD_LEFT, PAD_RIGHT = 0.05, 0.04

JSON_OUT = FIG_OUT / "figure_export_w13.json"


def _cases():
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    return payload["cases"]


def _main_template(item: dict) -> str:
    """本例主参照（缺省 12tet，只作对照索引）。"""
    return str(item.get("template") or "12tet")


def export_curve(records: list[dict]) -> dict:
    from acouscope.visualization.figures import segment_curve, segment_curve_data
    from acouscope.visualization.presets import get_preset

    preset = get_preset("paper_A")
    audio = AUDIO_DIR / "管平湖-良宵引_古琴.wav"
    anchor = next(item for item in _cases() if "guanpinghu" in item["recording_id"])
    template = _main_template(anchor)
    data = segment_curve_data(
        str(audio),
        CURVE_SEGMENT[0],
        CURVE_SEGMENT[1],
        window_s=float(preset["window_s"]),
        template=template,
        segmenter=preset["segmenter"],
    )
    result = segment_curve(
        data,
        FIG_OUT,
        stem="figure_a",
        dpi=int(preset["dpi"]),
        formats=preset["formats"],
        pad_left=PAD_LEFT,
        pad_right=PAD_RIGHT,
        labels=preset["labels"],
        title="管平湖《良宵引》",
        annotate_segment=bool(preset.get("annotate_segment", True)),
    )
    record = {
        "kind": "segment_curve",
        "template": template,
        "audio": audio.name,
        "segment_s": list(CURVE_SEGMENT),
        "paths": {k: Path(v).name for k, v in result["paths"].items()},
    }
    records.append(record)
    return record


def export_comparison(records: list[dict]) -> list[dict]:
    from acouscope.analysis.tunings.templates import list_paper_templates
    from acouscope.visualization.figures import reference_comparison_from_audio
    from acouscope.visualization.presets import get_preset

    preset = get_preset("paper_C")
    papers = list_paper_templates()
    out: list[dict] = []
    for item in _cases():
        rid = str(item["recording_id"])
        audio = AUDIO_DIR / Path(item["audio_path"]).name
        result = reference_comparison_from_audio(
            str(audio),
            FIG_OUT,
            window_start_s=0.0,
            window_s=float(preset["window_s"]),
            anchor_offset_cents=float(item["anchor_offset_cents"]),
            anchor_source=str(item["anchor_source"]),
            templates=papers,
            limit=int(preset["limit"]),
            require_anchor=bool(preset["require_anchor"]),
            tuning_template=_main_template(item),
            dpi=int(preset["dpi"]),
            formats=preset["formats"],
            labels=preset["labels"],
            title=str(item.get("label") or rid),
            stem=f"figure_c_{rid}",
        )
        record = {
            "kind": "reference_comparison",
            "recording_id": rid,
            "tuning_template": result.get("tuning_template"),
            "templates": list(result["matrix"]["templates"]),
            "median_deviation_cents": result["matrix"]["median_deviation_cents"],
            "n_segments": result["matrix"]["n_segments"],
            "anchor": result["anchor"],
            "paths": {k: Path(v).name for k, v in result["paths"].items()},
        }
        out.append(record)
        records.append(record)
    return out


def export_type_oscillation(records: list[dict]) -> dict:
    from acouscope.visualization.figures import load_panels, type_oscillation, type_oscillation_data
    from acouscope.visualization.presets import get_preset

    preset = get_preset("paper_B")
    panels_path = RUN_DIR / "figure_b_panels.tau_analysis.json"
    if not panels_path.is_file():
        raise SystemExit(f"运行件未就绪：{panels_path}（先跑 W-13 readout 批次）")
    data = type_oscillation_data(load_panels(panels_path))
    result = type_oscillation(
        data,
        FIG_OUT,
        stem="figure_b",
        dpi=int(preset["dpi"]),
        formats=preset["formats"],
        labels=preset["labels"],
    )
    record = {
        "kind": "type_oscillation",
        "panels": panels_path.name,
        "run_id": json.loads((RUN_DIR / "run_descriptor.json").read_text(encoding="utf-8"))["run_id"],
        "paths": {k: Path(v).name for k, v in result["paths"].items()},
    }
    records.append(record)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W-13 论文三图按逐例主参照重出")
    parser.add_argument("--skip-curve", action="store_true", help="不出图 4-1")
    parser.add_argument("--skip-comparison", action="store_true", help="不出图 4-2")
    parser.add_argument("--skip-panels", action="store_true", help="不出图 4-3")
    args = parser.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    FIG_OUT.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    if not args.skip_curve:
        export_curve(records)
    if not args.skip_comparison:
        export_comparison(records)
    if not args.skip_panels:
        export_type_oscillation(records)

    JSON_OUT.write_text(
        json.dumps({"figures": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"count": len(records), "out": str(FIG_OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
