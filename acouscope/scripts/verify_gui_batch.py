# SPDX-License-Identifier: GPL-3.0-only
"""GUI 批量读数运行的端到端自证（任务件-20261026 · GUI 化）。

**要证什么**：GUI 对话框与命令行走的是同一条路 —— 载入同一份 ``cases.json``、
取数参数相同时，两条路跑出**同一个 run_id**、同一张图。

在 ``acouscope/`` 目录下执行（脚本内的清单路径是相对该目录的）::

    export TERM=xterm-256color LC_ALL=C.UTF-8 LANG=C.UTF-8 \\
           QT_QPA_PLATFORM=offscreen PYTHONPATH=src
    .venv/bin/python scripts/verify_gui_batch.py

    # 可选：指定另一份清单与输出目录
    .venv/bin/python scripts/verify_gui_batch.py --cases ../03_Docs_and_Assets/... \\
        --out /tmp/out --figure-out /tmp/fig --expect-run-id c121ba2e4cbd3c75

退出码 0 = 全部对上；2 = 有对不上的（不静默）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_CASES = "../03_Docs_and_Assets/platform_paper_run_20261026/cases.json"
DEFAULT_RUN_ID = "c121ba2e4cbd3c75"      # 命令行跑四例所得（内容定址，可复算）
DEFAULT_FIGURE_SHA = "7dbc844905a5bd219e47b5f05afbc3c9c00b0539be379b1f072af0f14bbaf24b"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GUI 批量读数运行端到端自证")
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--out", default="/tmp/gui_e2e_out")
    ap.add_argument("--figure-out", default="/tmp/gui_e2e_fig")
    ap.add_argument("--expect-run-id", default=DEFAULT_RUN_ID)
    ap.add_argument("--expect-figure-sha", default=DEFAULT_FIGURE_SHA)
    args = ap.parse_args(argv)

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841

    from acouscope.analysis.readout import run_batch_from_spec
    from acouscope.ui.widgets.batch_readout_dialog import BatchReadoutDialog

    dlg = BatchReadoutDialog()
    loaded = dlg.load_cases_json(args.cases)
    dlg.edit_dir.setText(args.out)
    dlg.edit_figure_dir.setText(args.figure_out)
    error = dlg.validate()
    if error:
        print(f"[FAIL] 对话框校验未过：{error}")
        return 2

    spec = dlg.spec()
    print(f"载入 {loaded} 条清单；取数参数：{json.dumps(spec['params'], ensure_ascii=False)}")
    print(f"τ 档位 {spec['tau_values']}；口径 {spec['ref_modes']}")

    result = run_batch_from_spec(spec)
    run_id = str(result.get("run_id", ""))
    print(f"run_id = {run_id}")

    failures = []
    if args.expect_run_id and run_id != args.expect_run_id:
        failures.append(f"run_id 不符：实得 {run_id} ≠ 期望 {args.expect_run_id}")

    figures = result.get("figures") or {}
    if "png" in figures:
        sha = hashlib.sha256(Path(figures["png"]).read_bytes()).hexdigest()
        print(f"figure_b.png sha256 = {sha}")
        if args.expect_figure_sha and sha != args.expect_figure_sha:
            failures.append(f"图件 sha 不符：实得 {sha} ≠ 期望 {args.expect_figure_sha}")

    out = Path(args.out)
    check = json.loads((out / "figure_table_check.json").read_text(encoding="utf-8"))
    print(f"figure_table_check.pass = {check['pass']}")
    if not check["pass"]:
        failures.append("图—表对账未通过")

    print("--- type_distribution.csv ---")
    for line in (out / "type_distribution.csv").read_text(encoding="utf-8").splitlines():
        print("  ", line)

    if failures:
        print("\n[FAIL]")
        for item in failures:
            print("  -", item)
        return 2
    print("\n[PASS] GUI 与命令行跑出同一个 run_id、同一张图，图—表对账通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
