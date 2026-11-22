# SPDX-License-Identifier: GPL-3.0-only
"""W-12 交付驱动：段长分布件（同运行复核）＋ 段集比对。SEG_LEN_W12_DELIVERY_V1

**做什么**：

1. 读四例输入清单，按主分析档口径（60–1500 Hz、HMM、30 s 窗、下限 0.08 s）逐例
   重算帧轨与分段；
2. 与交付运行 ``58ca9b6ebc5c5d35`` 的 ``three_column.<rid>.json``（绝对口径）
   **逐段比对段集**——段数、段 id 集合、中位段长三项都要对上，否则本件只算
   「同参重算」而不算「同运行复核」；
3. 在下限网格上扫描短段占比（<150 ms），给逐例漂移幅度；
4. 出 ``segment_length.58ca9b6ebc5c5d35.json``／``.csv``／``MANIFEST.md``。

**不做什么**：不改分段逻辑、不改已交付表图、不改 τ 主档、不碰标定。

用法::

    cd acouscope && export LC_ALL=C.UTF-8 PYTHONPATH=src
    .venv/bin/python scripts/run_segment_length_w12.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

RUN_ID = "58ca9b6ebc5c5d35"
DEFAULT_CASES = "../03_Docs_and_Assets/platform_paper_run_20261026/cases.json"
DEFAULT_RUN_DIR = "../03_Docs_and_Assets/platform_paper_run_20261026"
DEFAULT_OUT_DIR = "../03_Docs_and_Assets/platform_segment_length_20261031"
STEM = f"segment_length.{RUN_ID}"


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="W-12 段长分布同运行复核件")
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--run-dir", default=DEFAULT_RUN_DIR)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--stem", default=STEM)
    ap.add_argument("--scan", default="0.04,0.06,0.08,0.10,0.12")
    ap.add_argument("--scan-fine", default="0.02,0.04,0.06,0.08,0.10,0.12,0.14",
                    help="细网格（只出占比与区间检验，供判断用）")
    ap.add_argument("--base-min-dur", type=float, default=0.08)
    ap.add_argument("--short-s", type=float, default=0.150)
    ap.add_argument("--frame-cache", default="",
                    help="可选：帧轨缓存目录（npz），供二次扫描免重算 pYIN")
    ap.add_argument(
        "--expect-run-id",
        default=RUN_ID,
        help=("预期运行标识（缺省＝原 W-12 主档 %s）；" % RUN_ID
              + "指向另一次运行（如逐例换参照系后的新档）时显式给出其 run_id"),
    )
    args = ap.parse_args(argv)

    import numpy as np

    from acouscope.analysis.readout import cases_from_json
    from acouscope.analysis.segment_length import (
        build_segment_length_payload,
        export_segment_length_csv,
        export_segment_length_json,
        frame_tracks,
        length_stats,
        pairs_within_band,
        scan_lower_bound,
        segments_for,
    )

    cases_path = Path(args.cases).resolve()
    run_dir = Path(args.run_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    scan = [float(x) for x in str(args.scan).split(",") if x.strip()]
    fine = [float(x) for x in str(args.scan_fine).split(",") if x.strip()]

    descriptor = json.loads((run_dir / "run_descriptor.json").read_text(encoding="utf-8"))
    expect = str(args.expect_run_id).strip()
    if descriptor.get("run_id") != expect:
        raise SystemExit(
            f"[abort] 运行目录 run_id={descriptor.get('run_id')} ≠ 预期 {expect}；"
            "本单要求段长件与其对账的表件同运行"
        )
    cfg = dict(descriptor.get("config") or {})
    caliber = {
        "fmin": cfg.get("fmin"),
        "fmax": cfg.get("fmax"),
        "segmenter": cfg.get("segmenter"),
        "window_s": cfg.get("window_s"),
        "min_window_s": cfg.get("min_window_s"),
        "tonic_window_s": cfg.get("tonic_window_s"),
        "template": cfg.get("template"),
        # 逐例参照系（仅当该运行登记了 config.templates 时出现）
        "case_templates": cfg.get("templates"),
        "base_min_dur_s": float(args.base_min_dur),
        "short_s": float(args.short_s),
        "ref_mode": "absolute",
        "note": (
            "主分析档口径逐项取自该运行的 run_descriptor.config；"
            "段长分布只在该运行**绝对口径**的段集上核（表 4-2/4-3 的四例段数 183/223/687/577 即此口径）。"
        ),
    }

    per_case: list[dict] = []
    checks: list[dict] = []
    fine_by_case: dict[str, dict] = {}
    cache = Path(args.frame_cache).resolve() if args.frame_cache else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    for case in cases_from_json(cases_path):
        rid = str(case.recording_id)
        npz = (cache / f"{rid}.npz") if cache is not None else None
        if npz is not None and npz.is_file():
            blob = np.load(npz, allow_pickle=True)
            tracks = json.loads(str(blob["tracks"]))
            for w in tracks["windows"]:
                w["times"] = np.asarray(w["times"], dtype=float)
                w["f0"] = np.asarray(w["f0"], dtype=float)
                w["conf"] = np.asarray(w["conf"], dtype=float)
        else:
            tracks = frame_tracks(
                case.audio_path,
                window_s=float(cfg.get("window_s") or 30.0),
                min_window_s=float(cfg.get("min_window_s") or 5.0),
                fmin=float(cfg.get("fmin") or 60.0),
                fmax=float(cfg.get("fmax") or 1500.0),
            )
            if npz is not None:
                serialisable = {
                    **{k: v for k, v in tracks.items() if k != "windows"},
                    "windows": [
                        {**{k: v for k, v in w.items() if k not in ("times", "f0", "conf")},
                         "times": w["times"].tolist(), "f0": w["f0"].tolist(),
                         "conf": w["conf"].tolist()}
                        for w in tracks["windows"]
                    ],
                }
                np.savez(npz, tracks=json.dumps(serialisable))
        scan_block = scan_lower_bound(
            tracks, min_dur_values=scan,
            base_min_dur_s=float(args.base_min_dur), short_s=float(args.short_s),
        )
        fine_block = scan_lower_bound(
            tracks, min_dur_values=fine,
            base_min_dur_s=float(args.base_min_dur), short_s=float(args.short_s),
        )
        fine_by_case[rid] = {
            "ex": case.title(),
            "levels": fine_block["levels"],
        }
        base_segs = segments_for(tracks, min_dur_s=float(args.base_min_dur))
        base_ids = {item["segment_id"] for item in base_segs}
        run_file = run_dir / f"three_column.{rid}.json"
        run_ids: set[str] = set()
        run_n = 0
        if run_file.is_file():
            payload = json.loads(run_file.read_text(encoding="utf-8"))
            block = dict(payload.get("by_ref_mode") or {}).get("absolute") or {}
            run_ids = {str(s.get("segment_id")) for s in block.get("segments") or ()}
            run_n = len(run_ids)
        run_durations = sorted(
            float(i.split("-")[1]) - float(i.split("-")[0]) for i in run_ids
        )
        checks.append(
            {
                "recording_id": rid,
                "run_n": run_n,
                "replication_n": len(base_ids),
                "n_match": bool(run_n == len(base_ids)),
                "id_sets_equal": bool(run_ids == base_ids),
                "only_in_run": sorted(run_ids - base_ids)[:5],
                "only_in_replication": sorted(base_ids - run_ids)[:5],
                "median_run_s": (
                    round(float(np.median(run_durations)), 6) if run_durations else None
                ),
                "median_replication_s": scan_block["levels"][
                    f"{round(float(args.base_min_dur), 4):.2f}"
                ]["median_s"],
            }
        )
        per_case.append(
            {
                "recording_id": rid,
                "label": case.title(),
                "ref_mode": "absolute",
                "duration_s": round(
                    tracks["frames"] / float(tracks["samplerate"]), 6
                ),
                "scan": scan_block,
            }
        )
        print(
            f"[case] {rid:26s} n_run={run_n:4d} n_repl={len(base_ids):4d} "
            f"段集{'' if run_ids == base_ids else '不'}一致 "
            f"中位={scan_block['levels'][f'{round(float(args.base_min_dur),4):.2f}']['median_s']} "
            f"漂移={scan_block['drift_pp']}pp"
        )

    command = (
        "python scripts/run_segment_length_w12.py "
        f"--cases {args.cases} --run-dir {args.run_dir} --out-dir {args.out_dir} "
        f"--stem {args.stem} --scan {args.scan} "
        f"--base-min-dur {args.base_min_dur:g} --short-s {args.short_s:g}"
    )
    payload = build_segment_length_payload(
        per_case,
        run_id_=RUN_ID,
        caliber=caliber,
        command=command,
        scan_grid=scan,
        base_min_dur_s=float(args.base_min_dur),
        short_s=float(args.short_s),
    )
    payload["scan_fine"] = {
        "grid": fine,
        "short_share_by_case": {
            rid: {key: block["short_share"] for key, block in data["levels"].items()}
            for rid, data in fine_by_case.items()
        },
        "levels_by_case": fine_by_case,
        "band_check": pairs_within_band(
            {rid: data["levels"] for rid, data in fine_by_case.items()}
        ),
    }
    payload["segment_set_check"] = {
        "against": str(run_dir / "three_column.<recording_id>.json"),
        "ref_mode": "absolute",
        "per_recording": checks,
        "all_id_sets_equal": all(c["id_sets_equal"] for c in checks),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    export_segment_length_json(out_dir / f"{args.stem}.json", payload)
    export_segment_length_csv(out_dir / f"{args.stem}.csv", payload)
    print(f"[ok] {out_dir / (args.stem + '.json')}")
    print(f"[ok] {out_dir / (args.stem + '.csv')}")

    lines = [
        "# 段长分布 · 同运行复核件（W-12）",
        "",
        f"- **运行标识**：`{RUN_ID}`（段集逐条比对见 JSON 的 `segment_set_check`）",
        f"- **口径**：{caliber['fmin']:g}–{caliber['fmax']:g} Hz、"
        f"{caliber['segmenter']} 分段、窗 {caliber['window_s']:g} s／最小窗 "
        f"{caliber['min_window_s']:g} s、下限 {caliber['base_min_dur_s']:g} s、绝对口径",
        f"- **短段判据**：< {caliber['short_s']:g} s（边界计为不短）",
        f"- **扫描网格**：{scan}（漂移依网格而定，逐档占比见 CSV）",
        "",
        "## 一、逐例（基准档 0.08 s）",
        "",
        "| 例 | recording_id | 段数 | 中位段长 s | P25 | P75 | <150 ms 段数 | 占比 | 漂移 pp |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in payload["per_recording"]:
        lines.append(
            f"| {case['例']} | `{case['recording_id']}` | {case['n_segments']} | "
            f"{case['median_s']} | {case['p25_s']} | {case['p75_s']} | "
            f"{case['n_short']} | {case['short_share'] * 100:.1f}% | "
            f"{case['scan']['drift_pp']} |"
        )
    lines += [
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
        command,
        "```",
        "",
    ]
    (out_dir / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[ok] {out_dir / 'MANIFEST.md'}")

    ok = payload["segment_set_check"]["all_id_sets_equal"]
    print(f"[check] 四例段集逐条一致：{ok}")
    return 0 if ok else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
