# SPDX-License-Identifier: GPL-3.0-only
"""冷启动/内存基线测量（架构演进工程 Phase 0 · 非侵入工具）。

口径：
- 子进程复刻 acouscope/__main__.py main() 启动序列（QApplication→apply_theme→
  AppController→MainWindow），但按 tests/test_view_stack.py 已验证的门控配方
  隔离 HOME/get_data_dir/licensing（规避 backlog #6 音频初始化挂起坑）。
- 冷启动 = 父进程 Popen 到子进程就绪标记的墙钟（含解释器启动与全部 import）。
- 排除首启预热：第 1 次运行视为首启单独报告，取第 2..N 次中位数。
- 内存 = 子进程就绪时刻自报 RSS（ps -o rss=，macOS 单位 KB）。

用法：
  .venv/bin/python scripts/bench_startup.py            # 默认 4 轮（1 首启 + 3 计入）
  .venv/bin/python scripts/bench_startup.py --with-audio   # 就绪态额外加载 20s 合成音频（内存参考）
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD_CODE = r'''
import os, sys, tempfile, time
T0 = time.perf_counter()
tmp = tempfile.mkdtemp(prefix="acouscope_bench_")
os.environ["HOME"] = tmp
SRC = r"{src}"
sys.path.insert(0, SRC)

import acouscope.ai.licensing as licensing
licensing.is_unlocked = lambda feature=None: True
import acouscope.utils.config as _cfg
_cfg.get_data_dir = lambda: tmp

from PyQt6.QtWidgets import QApplication
from acouscope.ui.main_window import MainWindow
MainWindow._check_feature_unlocked = lambda self, feature: True
from acouscope.app.controller import AppController
from acouscope.ui.theme import apply_theme
from acouscope.utils.config import Settings

app = QApplication(sys.argv)
app.setApplicationName("AcouScope")
app.setOrganizationName("AcouScope")
apply_theme(Settings.load().theme)

controller = AppController()
if "--with-audio" in sys.argv:
    import numpy as np
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t), sr)

w = MainWindow(controller)
for _ in range(5):
    app.processEvents()
import resource  # macOS: ru_maxrss 单位为字节
_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576.0
print("CHILD_READY_MS=%.1f|RSS_MB=%.1f" % ((time.perf_counter()-T0)*1000, _rss_mb), flush=True)
w.close()
sys.exit(0)
'''.replace("{src}", str(ROOT / "acouscope" / "src"))


def run_once(with_audio: bool, importtime: bool) -> dict:
    tmp = tempfile.mkdtemp(prefix="acouscope_bench_parent_")
    script = Path(tmp) / "child.py"
    script.write_text(CHILD_CODE)
    argv = [sys.executable]
    if importtime:
        argv += ["-X", "importtime"]
    argv += [str(script)] + (["--with-audio"] if with_audio else [])
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    try:
        out, stderr_data = proc.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"fail": "timeout 180s"}
    wall_ms = (time.perf_counter() - t0) * 1000
    last = out.strip().splitlines()[-1] if out.strip() else ""
    if proc.returncode != 0 or "CHILD_READY_MS" not in last:
        return {"fail": f"rc={proc.returncode}", "stderr_tail": stderr_data[-800:]}
    child_ms = float(last.split("|")[0].split("=")[1])
    rss_mb = None
    if "RSS_MB=" in last:
        try:
            rss_mb = float(last.split("RSS_MB=")[1])
        except ValueError:
            pass
    result = {
        "wall_ms": round(wall_ms, 1),
        "child_ms": child_ms,
        "rss_mb": rss_mb,
    }
    if importtime:
        rows = []
        # importtime 行: "import time: self us | cumulative us | module"
        for line in stderr_data.splitlines():
            if not line.startswith("import time:"):
                continue
            parts = line[len("import time:"):].split("|")
            if len(parts) >= 2:
                try:
                    rows.append((float(parts[1]), parts[-1].strip()))
                except ValueError:
                    pass
        rows.sort(reverse=True)
        result["import_top10_cum_ms"] = [
            {"cum_ms": round(c / 1000, 1), "module": m} for c, m in rows[:10]
        ]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-audio", action="store_true")
    ap.add_argument("--rounds", type=int, default=4)
    args = ap.parse_args()

    runs = []
    import_top = None
    for i in range(args.rounds):
        r = run_once(args.with_audio, importtime=(i == 0))
        if i == 0 and "import_top10_cum_ms" in r:
            import_top = r.pop("import_top10_cum_ms")
        r["round"] = i + 1
        runs.append(r)
        print(f"[round {i+1}] {r}", flush=True)

    ok = [r for r in runs[1:] if "wall_ms" in r]
    first = runs[0] if "wall_ms" in runs[0] else None
    summary = {
        "caliber": "parent-wall-cold-start, HOME/get_data_dir/licensing gated, offscreen, no app.exec",
        "first_launch": first,
        "steady_runs": [r.get("wall_ms") for r in ok],
        "median_wall_ms": round(statistics.median([r["wall_ms"] for r in ok]), 1) if ok else None,
        "median_child_ms": round(statistics.median([r["child_ms"] for r in ok]), 1) if ok else None,
        "median_rss_mb": round(statistics.median([r["rss_mb"] for r in ok]), 1)
        if ok and all(r["rss_mb"] for r in ok) else None,
        "with_audio": args.with_audio,
        "import_top10_cum_ms": import_top,
    }
    print("=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
