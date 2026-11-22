# SPDX-License-Identifier: GPL-3.0-only
"""丙案出件缺口的交付驱动脚本。PRO_CASE_DELIVERY_V2（W-1—W-7；W-8—W-10）

**做什么**（一次跑完，不掺人工改数）：

1. 把交付目录里的**旧件（含子目录产物）改名存档**（``archive_<旧 run_id>/``），不删不覆盖；
2. 跑**基线档**（``fmin=60``／``fmax=1500``，``--tau-analysis 10``）进交付目录，
   同时渲出**主档图**（``figure_b``，正文用）与**对照档图**（``figure_b_control``）；
3. 跑**第二档音域**（``fmin=40``／``fmax=2000``）进子目录（W-5）；
4. 写 ``fminfmax_diff.json``（只读两档落盘件，逐例列差值）；
5. 可选 ``--verify-determinism``：同参再跑一趟到临时目录，比对 ``run_id``
   （W-1 验收③：内容定址须含主档这一维）。

自 W-8 起四值分母为**可判段**（``judgable_segments_v1``），低频不可靠段单列
（``low_frequency_unreliable``），故本脚本产出的件与旧 ``run_id`` 不同属正常。

**不做什么**：不改 ``TAU_CENTS_PLACEHOLDER``、不扩 HMM 网格、不代写作侧算改判率、
不写论文文字。

用法（在 ``acouscope/`` 目录下）::

    export LC_ALL=C.UTF-8 PYTHONPATH=src
    .venv/bin/python scripts/run_paper_run_pro_case.py \\
        --run-dir ../03_Docs_and_Assets/platform_paper_run_20261026 \\
        --figure-out ../03_Docs_and_Assets/platform_figures_20261027 \\
        --tau-analysis 10 --verify-determinism

退出码 0 = 全部产物齐备且两档参数除音域外一致；2 = 有缺项（不静默）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_RUN_DIR = "../03_Docs_and_Assets/platform_paper_run_20261026"
DEFAULT_FIGURE_OUT = "../03_Docs_and_Assets/platform_figures_20261028"
DEFAULT_CASES = "../03_Docs_and_Assets/platform_paper_run_20261026/cases.json"
DEFAULT_OLD_RUN_ID = "ffa3de9ba823d582"
DEFAULT_VARIANT_DIR = "fminfmax_40_2000"

TAUS = [None, 10.0, 20.0, 30.0]
BASE_RANGE = (60.0, 1500.0)
VARIANT_RANGE = (40.0, 2000.0)


def _archive_old(run_dir: Path, old_run_id: str,
                 keep: tuple[str, ...] = ("cases.json",)) -> Path | None:
    """旧件改名存档：顶层**产物件**与**子目录产物**移入 ``archive_<旧 run_id>/``。

    不删、不覆盖；``keep`` 为**输入件**名单（如 ``cases.json``），留在原地，
    否则下一趟跑不出同一份清单。已存在的 ``archive_*`` 子目录不再搬（避免自吞）。
    """
    target = run_dir / f"archive_{old_run_id}"
    files = [
        p for p in sorted(run_dir.iterdir())
        if p.is_file() and p.name not in set(keep)
    ]
    dirs = [
        p for p in sorted(run_dir.iterdir())
        if p.is_dir() and not p.name.startswith("archive_")
    ]
    if not files and not dirs:
        print(f"[skip] 交付目录顶层已无产物件，无需存档：{run_dir}")
        return None
    if target.exists() and any(target.iterdir()):
        raise SystemExit(
            f"[abort] 存档目录已存在且非空，拒绝二次存档：{target}"
        )
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for path in files + dirs:
        shutil.move(str(path), str(target / path.name))
        moved.append(path.name + ("/" if path.is_dir() else ""))
    (target / "ARCHIVE_NOTE.md").write_text(
        "\n".join(
            [
                f"# 旧件存档（run_id = `{old_run_id}`）",
                "",
                "丙案补项（W-1—W-7）重跑前，按设计约定 §三.5「新增件不得覆盖旧件："
                "交付目录只追加与改名存档」将上一轮顶层**产物件**整体移入本目录"
                f"（输入清单 `{'`、`'.join(keep)}` 留在原地，不属产物）。",
                "",
                "原件名与内容均未改动，可逐件回看（内容定址的旧 `run_id` 仍写在原件的",
                "`run_id` 字段内）。",
                "",
                "## 存档文件",
                "",
                *[f"- `{name}`" for name in moved],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"[ok] 旧件存档 {len(moved)} 件 → {target}")
    return target


def _append_late_manifest(run_dir: Path) -> None:
    """把**收尾追加件**（差值件／自检件，晚于 MANIFEST 生成）补登进 MANIFEST。

    只追加一节并记字节与 sha256；已登件不重复登记（逐行比对表内文件名）。
    """
    import hashlib

    manifest = run_dir / "MANIFEST.md"
    if not manifest.is_file():
        return
    text = manifest.read_text(encoding="utf-8")
    missing = [
        p for p in sorted(run_dir.iterdir())
        if p.is_file() and p.name != "MANIFEST.md" and f"`{p.name}`" not in text
    ]
    if not missing:
        return
    lines = ["", "## 五、收尾追加件（差值件／自检件；与上表同 run_id）", "",
             "| 文件 | 字节 | sha256 |", "|---|---:|---|"]
    for path in missing:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"| `{path.name}` | {path.stat().st_size} | `{digest}` |")
    lines.append("")
    manifest.write_text(text.rstrip("\n") + "\n" + "\n".join(lines), encoding="utf-8")
    print(f"[ok] MANIFEST 补登 {len(missing)} 件："
          + "、".join(p.name for p in missing))


def _run(run_dir, cases, *, fmin, fmax, figure_out, tau_analysis, cases_path,
         label):
    from acouscope.analysis.readout import run_batch, cases_from_json

    print(f"[run] {label}：fmin={fmin:g} fmax={fmax:g} τ_analysis={tau_analysis}")
    summary = run_batch(
        cases_from_json(cases_path),
        out_dir=run_dir,
        fmin=float(fmin),
        fmax=float(fmax),
        tau_analysis=None if tau_analysis is None else float(tau_analysis),
        tau_provenance=(
            f"cli:--tau-analysis {float(tau_analysis):g}"
            if tau_analysis is not None
            else ""
        ),
        tau_values=TAUS,
        figure_out=figure_out,
        figure_stem="figure_b",
        cases_source=str(cases_path),
    )
    print(f"[ok] {label} run_id={summary['run_id']}")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="丙案出件缺口交付（W-1—W-7）")
    ap.add_argument("--run-dir", default=DEFAULT_RUN_DIR)
    ap.add_argument("--figure-out", default=DEFAULT_FIGURE_OUT)
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--old-run-id", default=DEFAULT_OLD_RUN_ID)
    ap.add_argument("--tau-analysis", type=float, default=10.0)
    ap.add_argument("--variant-dir", default=DEFAULT_VARIANT_DIR)
    ap.add_argument("--skip-archive", action="store_true")
    ap.add_argument("--verify-determinism", action="store_true")
    ap.add_argument(
        "--stage", choices=("all", "base", "variant", "finish"), default="all",
        help="分段执行（长任务用）：base=存档＋基线档；variant=第二档音域；"
             "finish=差值件＋确定性复核；all=一次跑完",
    )
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    figure_out = Path(args.figure_out).resolve()
    variant_dir = run_dir / args.variant_dir
    if not Path(args.cases).is_file():
        raise SystemExit(f"[abort] 输入清单不存在：{args.cases}")

    if args.stage in ("all", "base"):
        if not args.skip_archive:
            _archive_old(run_dir, args.old_run_id)
        base = _run(
            run_dir, args.cases, fmin=BASE_RANGE[0], fmax=BASE_RANGE[1],
            figure_out=figure_out, tau_analysis=args.tau_analysis,
            cases_path=args.cases, label="基线档",
        )
    else:
        base = None
    if args.stage in ("all", "variant"):
        variant = _run(
            variant_dir, args.cases, fmin=VARIANT_RANGE[0], fmax=VARIANT_RANGE[1],
            figure_out=None, tau_analysis=args.tau_analysis,
            cases_path=args.cases, label="第二档音域",
        )
    else:
        variant = None

    if args.stage in ("base", "variant"):
        return 0

    if base is None or variant is None:
        # 分段执行的收尾：从落盘件读回 run_id／config（不重算）
        base_desc = json.loads((run_dir / "run_descriptor.json").read_text(encoding="utf-8"))
        variant_desc = json.loads(
            (variant_dir / "run_descriptor.json").read_text(encoding="utf-8")
        )
        base = {"run_id": base_desc.get("run_id"), "config": dict(base_desc.get("config") or {})}
        variant = {"run_id": variant_desc.get("run_id"),
                   "config": dict(variant_desc.get("config") or {})}

    from acouscope.analysis.readout_extras import fminfmax_diff, provenance_block
    from acouscope.analysis.type_distribution import export_json

    diff = fminfmax_diff(run_dir, variant_dir)
    diff["provenance"] = provenance_block(
        run_id_=base["run_id"],
        run_config=base["config"],
        command="python acouscope/scripts/run_paper_run_pro_case.py "
                f"--run-dir {run_dir} --figure-out {figure_out} "
                f"--tau-analysis {args.tau_analysis:g} --verify-determinism",
        extra={"variant": {"dir": str(variant_dir), "run_id": variant["run_id"]}},
    )
    export_json(run_dir / "fminfmax_diff.json", diff)
    print(
        "[ok] fminfmax_diff.json：除音域外参数"
        f"{'一致' if diff['params_identical_except_audio_range'] else '有漂移'}"
    )

    status = 0
    if args.verify_determinism:
        with tempfile.TemporaryDirectory() as tmp:
            rerun = _run(
                Path(tmp) / "rerun", args.cases, fmin=BASE_RANGE[0], fmax=BASE_RANGE[1],
                figure_out=None, tau_analysis=args.tau_analysis,
                cases_path=args.cases, label="确定性复核（同参第二趟）",
            )
        text = (run_dir / "PRO_CASE_SELFCHECK.json")
        payload = {
            "format": "acouscope-pro-case-selfcheck",
            "version": 1,
            "run_id": base["run_id"],
            "run_ids": {"first": base["run_id"], "second": rerun["run_id"]},
            "same_run_id": bool(base["run_id"] == rerun["run_id"]),
            "tau_analysis": args.tau_analysis,
            "note": "同参独立两趟：内容定址含主档 τ／音域／窗参数等口径维，故同值即证该维入哈希面。",
            "provenance": provenance_block(
                run_id_=base["run_id"],
                run_config=base["config"],
                command="python acouscope/scripts/run_paper_run_pro_case.py --stage finish --verify-determinism",
                extra={"second_run_out_dir": "<temporary dir, deleted after check>"},
            ),
        }
        export_json(text, payload)
        print(f"[{'ok' if payload['same_run_id'] else 'FAIL'}] run_id 复算："
              f"{base['run_id']} vs {rerun['run_id']}")
        if not payload["same_run_id"]:
            status = 2

    if not diff["params_identical_except_audio_range"]:
        print(f"[FAIL] 两档参数漂移：{json.dumps(diff['param_drift'], ensure_ascii=False)}")
        status = 2

    _append_late_manifest(run_dir)
    print(f"[done] 交付目录 {run_dir}")
    return status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
