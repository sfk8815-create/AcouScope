# SPDX-License-Identifier: GPL-3.0-only
"""W-13 参照系切换前后**同一 audio、同一 τ 主档**的对账件（只读，不重算）。

对照两份已交付的运行件，逐例逐口径报：

- 段数基准是否同一段集（逐条比对 segment_id）；
- 三型计数（判型取音分容差、不取网格值）是否改变、改变多少段；
- 逐段 cavity_type 改动清单（逐段 countable，不是只在总数上差）；
- 两口径配对翻转数是否改变。

旧件＝`platform_paper_run_20261026`（run_id `58ca9b6ebc5c5d35`，旧参照 12tet）；
新件＝`platform_paper_run_20261031_qinlu`（逐例主参照，古琴＝qin_lu、二胡＝三分损益）。

用法：

    cd acouscope && export LC_ALL=C.UTF-8 PYTHONPATH=src
    .venv/bin/python scripts/reconcile_w13_reference_shift.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "03_Docs_and_Assets"
OLD = DOCS / "platform_paper_run_20261026"
NEW = DOCS / "platform_paper_run_20261031_qinlu"
OUT = NEW / "reference_shift_check.json"

RECORDINGS = (
    "gq_liangxiaoyin_puxuezhai",
    "gq_liangxiaoyin_guanpinghu",
    "eh_erquan_abing",
    "eh_erquan_minhuifen",
)
LABEL = {
    "gq_liangxiaoyin_puxuezhai": "溥雪斋《良宵引》",
    "gq_liangxiaoyin_guanpinghu": "管平湖《良宵引》",
    "eh_erquan_abing": "阿炳《二泉映月》",
    "eh_erquan_minhuifen": "闵惠芬《二泉映月》",
}
MODES = ("absolute", "main_tone")
TYPES = ("上趋", "下趋", "平直", "未分类")


def _three(run_dir: Path, rid: str) -> dict:
    return json.loads((run_dir / f"three_column.{rid}.json").read_text(encoding="utf-8"))


def _mode_block(payload: dict, mode: str) -> dict:
    return payload["by_ref_mode"][mode]


def _type_counts(block: dict) -> dict:
    return dict(block["counts_per_recording"])


def _segments(block: dict) -> dict:
    return {row["segment_id"]: row["cavity_type"] for row in block["segments"]}


#: 两口径对照件的取数字段（与表 4-3 同源）
PAIRING_FIELDS = ("配对段数", "未配对段", "type_flips", "flip_numerator", "flip_denominator", "flip_rate_dual")


def compare_pairing() -> dict:
    out: dict[str, dict] = {}
    for name, path in (
        ("old", OLD / "dual_calibre_pairing.tau_analysis.json"),
        ("new", NEW / "dual_calibre_pairing.tau_analysis.json"),
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("rows", [])
        out[name] = {
            row["recording_id"]: {field: row.get(field) for field in PAIRING_FIELDS}
            for row in rows
        }
    return out


def main() -> int:
    old_run = json.loads((OLD / "run_descriptor.json").read_text(encoding="utf-8"))["run_id"]
    new_run = json.loads((NEW / "run_descriptor.json").read_text(encoding="utf-8"))["run_id"]
    pairing = compare_pairing()

    per_recording = []
    for rid in RECORDINGS:
        old = _three(OLD, rid)
        new = _three(NEW, rid)
        entry = {
            "recording_id": rid,
            "例": LABEL[rid],
            "old_template": "12tet",
            "new_template": next(
                item["template"]
                for item in json.loads((NEW / "cases.json").read_text(encoding="utf-8"))["cases"]
                if item["recording_id"] == rid
            ),
            "by_ref_mode": {},
        }
        for mode in MODES:
            old_block = _mode_block(old, mode)
            new_block = _mode_block(new, mode)
            old_seg = _segments(old_block)
            new_seg = _segments(new_block)
            common = set(old_seg) & set(new_seg)
            changed_ids = sorted(sid for sid in common if old_seg[sid] != new_seg[sid])
            flips = sorted(
                f"{old_seg[sid]}→{new_seg[sid]}" for sid in changed_ids
            )
            entry["by_ref_mode"][mode] = {
                "tau_cents": new_block["tau_cents"],
                "n_segments_old": len(old_seg),
                "n_segments_new": len(new_seg),
                "only_in_old": sorted(set(old_seg) - set(new_seg)),
                "only_in_new": sorted(set(new_seg) - set(old_seg)),
                "same_segment_set": set(old_seg) == set(new_seg),
                "counts_old": _type_counts(old_block),
                "counts_new": _type_counts(new_block),
                "counts_delta": {
                    t: int(_type_counts(new_block).get(t, 0)) - int(_type_counts(old_block).get(t, 0))
                    for t in TYPES
                },
                "n_common": len(common),
                "changed_segments": len(changed_ids),
                "changed_share": round(len(changed_ids) / len(common), 6) if common else 0.0,
                "changed_pairs_first10": flips[:10],
            }
        entry["pairing"] = {
            "old": pairing["old"].get(rid),
            "new": pairing["new"].get(rid),
        }
        per_recording.append(entry)

    total_changed = {
        mode: sum(e["by_ref_mode"][mode]["changed_segments"] for e in per_recording)
        for mode in MODES
    }
    payload = {
        "kind": "reference_shift_check",
        "old_run_id": old_run,
        "new_run_id": new_run,
        "note": "同一 audio、同一 τ 主档（τ=10）；只切音级归属参照系。判型取音分容差、不取网格值。",
        "total_changed_segments": total_changed,
        "per_recording": per_recording,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"run_id {old_run} → {new_run}")
    for e in per_recording:
        for mode in MODES:
            b = e["by_ref_mode"][mode]
            print(
                f"{e['例']} [{mode}] {e['old_template']}→{e['new_template']} "
                f"段数 {b['n_segments_old']}→{b['n_segments_new']} "
                f"段集同={b['same_segment_set']} 变动 {b['changed_segments']}/{b['n_common']} "
                f"({b['changed_share']:.4f}) 计数差 {b['counts_delta']}"
            )
        print(f"    两口径 {e['pairing']['old']} → {e['pairing']['new']}")
    print(f"合计变动段数 {total_changed}")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
