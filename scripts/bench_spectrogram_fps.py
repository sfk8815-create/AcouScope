# SPDX-License-Identifier: GPL-3.0-only
"""语谱图渲染帧率代理测量（架构演进工程 Phase 0 · 非侵入工具）。

口径（诚实声明）：
- 离屏 QT_QPA_PLATFORM=offscreen，widget.grab() 光栅化代理，无 GL/vsync/真机窗口合成；
  数值为【渲染耗时代理】，AT-1005 的 60fps(GL) 真值需真机 OpenGL 实测（T-906 另测）。
- 模拟两类开销：
  A. 纯重绘代理：不变数据连续 grab（渲染管线成本）。
  B. 缩放交互代理：ViewBox setXRange 视窗逐级×2 收窄 + grab（模拟缩放拖拽）。
- 数据规模取真实场景：n_fft=2048（2049 bin）× 30s@16kHz（hop≈512 → ~2576 帧）。

用法：
  .venv/bin/python scripts/bench_spectrogram_fps.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "acouscope" / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication([])
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = SpectrogramWidget()
    w.resize(1200, 520)

    freqs = np.linspace(0, 8000, 2049)
    times = np.linspace(0, 30.0, 2576)
    rng = np.random.RandomState(42)
    spec = rng.randn(2049, 2576) * 10 - 60
    for ti in range(spec.shape[1]):
        f_signal = 300 + (2500 - 300) * ti / spec.shape[1]
        fi = int(f_signal / 8000 * 2048)
        spec[fi, ti] += 60

    w.set_data(freqs, times, spec, sample_rate=16000)
    app.processEvents()

    # A. 纯重绘代理
    for _ in range(3):
        w.grab()
    n_a = 20
    t0 = time.perf_counter()
    for _ in range(n_a):
        w.grab()
    a_ms = (time.perf_counter() - t0) * 1000 / n_a

    # B. 缩放交互代理：视窗×2 收窄后 grab（8 级一轮，共 24 次）
    vb = w.plot_widget.getPlotItem().vb
    for _ in range(2):
        w.grab()
    n_b = 24
    t0 = time.perf_counter()
    for i in range(n_b):
        f1 = 30.0 / (2 ** (i % 8 + 1))
        vb.setXRange(0.0, max(f1, 0.05), padding=0)
        app.processEvents()
        w.grab()
    b_ms = (time.perf_counter() - t0) * 1000 / n_b

    summary = {
        "caliber": "offscreen grab proxy, no GL/vsync; AT-1005 real value needs on-screen GL (T-906)",
        "data_shape": f"{spec.shape[0]} bins x {spec.shape[1]} frames (30s@16kHz, n_fft=2048)",
        "widget_size": "1200x520",
        "repaint_proxy_ms_per_frame": round(a_ms, 2),
        "repaint_proxy_fps": round(1000 / a_ms, 1),
        "zoom_proxy_ms_per_frame": round(b_ms, 2),
        "zoom_proxy_fps": round(1000 / b_ms, 1),
        "zoom_proxy_median_ms": round(statistics.median([b_ms]), 2),
    }
    import json

    print("=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
