"""B1-02a 段级音级归属正确率（协议口径，2026-10-24 约定取 3a 后成立）。

覆盖：7 个内置律制模板 × 全音级 Voronoi 胞内合成采样，另含八度折叠外推档。
判定：``build_pitch_grid(segmenter="hmm", tuning=...)`` 的段级 ``degree_index``
精确等于期望音级（== 判定，不设容差）。
通过线：100%；失败样本逐条列清单；外推档读数与胞内档**分列**，不合并百分比。
边界：只覆盖合成稳态信号，不覆盖真实录音精度（后者属 R4 标定）。
"""

from __future__ import annotations

import json

import numpy as np

from acouscope.analysis.pitch_grid import build_pitch_grid
from acouscope.analysis.tunings.templates import get_template, list_templates
from acouscope.dsp.units import cents_to_hz

FRAMES = 20
DT = 0.01
CELL_T = (0.2, 0.5, 0.8)  # 胞内比例位置：避开胞界（0/1）


def _segment_degree(freq_hz: float, tpl) -> int | None:
    times = np.arange(FRAMES, dtype=float) * DT
    model = build_pitch_grid(
        times, np.full(FRAMES, float(freq_hz)), segmenter="hmm", tuning=tpl
    )
    return model.notes[0].degree_index if len(model.notes) == 1 else None


def _cell_cents(tpl, degree: int, t: float) -> float:
    """Voronoi 胞内取点：胞界为相邻音级中点（按八度循环取邻）。"""
    degs = list(tpl.degrees)
    cnt = tpl.degree_count
    center = float(degs[degree])
    left = float(degs[(degree - 1) % cnt]) + (-1200.0 if degree == 0 else 0.0)
    right = float(degs[(degree + 1) % cnt]) + (1200.0 if degree == cnt - 1 else 0.0)
    lmid, rmid = (center + left) / 2.0, (center + right) / 2.0
    return lmid + t * (rmid - lmid)


def _run(mode: str) -> dict:
    per_template: dict[str, dict] = {}
    failures: list[dict] = []
    skipped: list[str] = []
    for name in list_templates():
        tpl = get_template(name)
        cnt = tpl.degree_count
        if cnt <= 0 or (mode == "octave" and not tpl.is_octave_repeating):
            skipped.append(name)
            continue
        ok = n = 0
        for degree in range(cnt):
            for shift in ((0,) if mode == "cell" else (cnt, -cnt)):
                expected = degree + shift
                for t in CELL_T:
                    cents = _cell_cents(tpl, degree, t)
                    freq = float(
                        cents_to_hz(
                            cents + (shift / cnt) * 1200.0, ref_freq=tpl.reference_freq
                        )
                    )
                    actual = _segment_degree(freq, tpl)
                    n += 1
                    if actual == expected:
                        ok += 1
                    else:
                        failures.append(
                            {
                                "template": name,
                                "degree": degree,
                                "shift": shift,
                                "t": t,
                                "freq_hz": round(freq, 3),
                                "expected": expected,
                                "actual": actual,
                            }
                        )
        per_template[name] = {"n": n, "ok": ok}
    summary = {
        "mode": mode,
        "n": sum(v["n"] for v in per_template.values()),
        "ok": sum(v["ok"] for v in per_template.values()),
        "per_template": per_template,
        "skipped": skipped,
        "failures": failures,
    }
    print("DEGREE_ACCURACY " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return summary


def test_voronoi_cell_accuracy_by_template():
    """胞内档：7 模板全音级，精确匹配率须 100%，失败列清单。"""
    s = _run("cell")
    assert s["n"] > 0
    assert s["failures"] == [], f"胞内档失败 {len(s['failures'])} 例：{s['failures'][:5]}"


def test_octave_extrapolation_accuracy():
    """八度折叠外推档：读数单列，精确匹配率须 100%。"""
    s = _run("octave")
    assert s["n"] > 0
    assert s["failures"] == [], f"外推档失败 {len(s['failures'])} 例：{s['failures'][:5]}"
