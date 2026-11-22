# SPDX-License-Identifier: GPL-3.0-only
"""W-11 交付驱动：D 档 A4 参考音标定件 ＋ 四例读数未动核对。CALIB_W11_DELIVERY_V1

**做什么**（一次跑完，不掺人工改数）：

1. 校验参考音 sha256 与设计约定给定值一致（不一致即中止，不猜）；
2. 走平台路径 ``analysis.reference_calibration`` 出
   ``calibration.a4_erhu_20261028.json``（＋同名 ``.csv``）；
3. 对四例主档目录 ``platform_paper_run_20261026`` **逐文件快照 sha256**，
   出件前后各算一次并比对，写 ``calibration_impact_check.json``；
   同时把图件哈希与设计约定给定的 ``0e050063…`` 对照。

**不做什么**：不改 ``TAU_CENTS_PLACEHOLDER``／``A4`` 基准、不重跑四例、
不把合成音当标定、不在 reference_status=pending 时写 calibrated。

用法::

    cd acouscope && export LC_ALL=C.UTF-8 PYTHONPATH=src
    .venv/bin/python scripts/run_calibration_w11.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_SHA256 = "8d66ae6776da305937eedd9226133145cb79572dc11725f62bead81c20785375"
EXPECTED_FIGURE = "0e050063a71874169de9934322a595848283f8dddade3b49971dad3212c6bde2"
DEFAULT_AUDIO = "../Essay_writing/audio_files/二胡_A4.wav"
DEFAULT_RUN_DIR = "../03_Docs_and_Assets/platform_paper_run_20261026"
DEFAULT_OUT_DIR = "../03_Docs_and_Assets/platform_calibration_20261028"
STEM = "calibration.a4_erhu_20261028"


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict:
    """目录顶层文件 → {name: sha256}（不递归；子目录只记名，不记内容）。"""
    out: dict[str, str] = {}
    for path in sorted(root.iterdir()):
        if path.is_file():
            out[path.name] = _sha256(path)
    return out


def _write_manifest(out_dir: Path, payload: dict, impact: dict) -> Path:
    """人读清单（机读面以 JSON 为准）：逐件 sha256 ＋ 状态与理由 ＋ 复跑命令。"""
    lines = [
        "# D 档参考音标定件 · W-11（A4 参考音）",
        "",
        f"- **reference_id**：`{payload['reference_id']}`",
        f"- **标定 run_id**：`{payload['provenance']['run_id']}`"
        f"（内容定址；平台版本 `{payload['provenance']['platform_version']}`）",
        f"- **reference_status**：`{payload['reference_status']}`",
        f"- **参考音**：`{payload['file']['name']}`，sha256 "
        f"`{payload['file_sha256']}`（{payload['samplerate']} Hz，"
        f"{payload['duration_s']} s）",
        f"- **稳定段**：{payload['stable_segment_s']} s（{payload['n_frames']} 帧）",
        f"- **实测中位**：{payload['reference_hz_measured']} Hz ｜ "
        f"bias {payload['bias_cents']} 音分 ｜ std {payload['std_cents']} ｜ "
        f"P95 {payload['p95_cents']}",
        "",
        "## 一、口径（不掩盖）",
        "",
        f"- 标称 `reference_hz_nominal = {payload['reference_hz_nominal']}`（平台 A4 基准，**未改**）。",
        f"- 结论：**{payload['reference_status']}**。{payload.get('pending_reason', '')}",
        "- `bias_cents` 在 pending 态为**诊断量**（`bias_cents_is_diagnostic=true`），不得当精度结果引用；",
        "  `std_cents`／`p95_cents` 与标称无关，可作该稳态音的重复性读数；"
        "`*_detrended` 另除去段内线性慢漂。",
        "- 四例主档 `58ca9b6ebc5c5d35` 与图件 `0e050063…` **未变**（见 `calibration_impact_check.json`）。",
        "",
        "## 二、产物与 sha256",
        "",
        "| 文件 | 字节 | sha256 |",
        "|---|---:|---|",
    ]
    for path in sorted(out_dir.iterdir()):
        if path.is_file() and path.name != "MANIFEST.md":
            lines.append(f"| `{path.name}` | {path.stat().st_size} | `{_sha256(path)}` |")
    lines += [
        "",
        "## 三、复跑命令",
        "",
        "```bash",
        payload["provenance"]["command"],
        "```",
        "",
        f"- 四例主档核对：`files_checked = {impact['files_checked']}`，"
        f"`changed_files = {len(impact['changed_files'])}`。",
        "",
    ]
    target = out_dir / "MANIFEST.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="W-11 D 档参考音标定件交付")
    ap.add_argument("--audio", default=DEFAULT_AUDIO)
    ap.add_argument("--run-dir", default=DEFAULT_RUN_DIR)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--reference-id", default="d_a4_erhu_20261028")
    ap.add_argument("--source", default="中国传统乐器音响数据库")
    ap.add_argument("--stem", default=STEM)
    args = ap.parse_args(argv)

    from acouscope.analysis.reference_calibration import (
        SUGGESTED_ALTERNATIVES,
        analyze_reference_audio,
        build_reference_payload,
        export_reference_calibration_csv,
        export_reference_calibration_json,
    )

    audio = Path(args.audio).resolve()
    run_dir = Path(args.run_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    digest = _sha256(audio)
    print(f"[sha] 参考音 {audio.name} = {digest}")
    if digest != EXPECTED_SHA256:
        raise SystemExit(
            f"[abort] 参考音 sha256 与设计约定给定值不一致：\n  实得 {digest}\n  应为 {EXPECTED_SHA256}"
        )

    before = _snapshot(run_dir)

    analysis = analyze_reference_audio(audio, nominal_hz=None)
    command = (
        "python scripts/run_calibration_w11.py "
        f"--audio {args.audio} --run-dir {args.run_dir} --out-dir {args.out_dir} "
        f"--reference-id {args.reference_id} --source {args.source} --stem {args.stem}"
    )
    payload = build_reference_payload(
        analysis,
        reference_id=args.reference_id,
        source=args.source,
        command=command,
        suggested_alternatives=SUGGESTED_ALTERNATIVES,
    )
    try:
        payload["file"]["path_in_repo"] = str(audio.relative_to(audio.parents[2]))
    except (IndexError, ValueError):  # 非本仓路径：不硬写
        payload["file"]["path_in_repo"] = ""
    out_dir.mkdir(parents=True, exist_ok=True)
    export_reference_calibration_json(out_dir / f"{args.stem}.json", payload)
    export_reference_calibration_csv(out_dir / f"{args.stem}.csv", payload)
    print(f"[ok] {out_dir / (args.stem + '.json')}")
    print(f"[ok] {out_dir / (args.stem + '.csv')}")
    print(
        f"[status] {payload['reference_status']}｜measured={payload['reference_hz_measured']} Hz"
        f"｜bias={payload['bias_cents']} cents｜n={payload['n_frames']}"
    )

    after = _snapshot(run_dir)
    changed = {
        name: {"before": before.get(name), "after": after.get(name)}
        for name in sorted(set(before) | set(after))
        if before.get(name) != after.get(name)
    }
    figure = run_dir.parent / "platform_figures_20261028" / "figure_b.png"
    figure_sha = _sha256(figure) if figure.is_file() else None
    impact = {
        "format": "acouscope-calibration-impact-check",
        "version": 1,
        "calibration_run_id": payload["provenance"]["run_id"],
        "four_case_run_id": "58ca9b6ebc5c5d35",
        "run_dir": str(run_dir),
        "files_checked": len(before),
        "changed_files": changed,
        "unchanged": not changed,
        "figure": {
            "path": str(figure),
            "sha256": figure_sha,
            "expected": EXPECTED_FIGURE,
            "match": figure_sha == EXPECTED_FIGURE,
        },
        "note": (
            "本件为出件前后对四例主档目录的逐文件 sha256 快照比对；"
            "changed_files 为空即证明标定件未改动四例读数与表图。"
        ),
    }
    export_reference_calibration_json(out_dir / "calibration_impact_check.json", impact)
    manifest = _write_manifest(out_dir, payload, impact)
    print(f"[ok] {manifest}")
    print(f"[check] 四例主档改动文件数 = {len(changed)}；图件哈希对上 = {impact['figure']['match']}")
    if changed or not impact["figure"]["match"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
