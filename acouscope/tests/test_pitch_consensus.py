# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-C T08：多算法音高一致性判据。

覆盖：纯音 220/440/880 三算法一致（consistent/applicable）；双音 440+660
判 multi-pitch（并打印 pYIN 实测 ~220 Hz 次谐波证据）；静音 no-voiced；
零外部后端引入（源码零命中 + 正对照）。

后端只来自仓内 analysis.pitch（YIN / HPS / pYIN），无外部音高后端。
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from acouscope.analysis.pitch_consensus import multi_algorithm_f0
from acouscope.dsp.pitch_tone import synthesize_tone

SR = 44100
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope"


def _pure_tone(freq: float) -> np.ndarray:
    return synthesize_tone(freq, 1.0, SR, amplitude=0.8)


def _dual_tone() -> np.ndarray:
    t = np.arange(SR, dtype=np.float64) / float(SR)
    return 0.5 * np.sin(2 * np.pi * 440.0 * t) + 0.5 * np.sin(2 * np.pi * 660.0 * t)


# ----------------------------------------------------------------------
# ① 纯音三频点：三算法一致
# ----------------------------------------------------------------------

@pytest.mark.parametrize("freq", [220.0, 440.0, 880.0])
def test_pure_tones_consistent_and_applicable(freq):
    res = multi_algorithm_f0(_pure_tone(freq), SR)
    print(
        f"[T08] pure {freq:.0f}: pyin={res['pyin_hz']:.3f} "
        f"yin={res['yin_hz']:.3f} hps={res['hps_hz']:.3f} "
        f"diffs={[round(d, 2) for d in res['pairwise_cent_diffs']]} "
        f"consistent={res['consistent']} reason={res['reason']}"
    )
    assert res["consistent"] is True
    assert res["applicable"] is True
    assert res["reason"] == "ok"
    assert res["n_algorithms"] == 3
    assert len(res["pairwise_cent_diffs"]) == 3
    assert max(abs(d) for d in res["pairwise_cent_diffs"]) <= 50.0
    for algo in ("pyin_hz", "yin_hz", "hps_hz"):
        assert res[algo] == pytest.approx(freq, rel=0.02), algo


def test_pairwise_cent_diffs_pair_count_and_consistency_threshold():
    res = multi_algorithm_f0(_pure_tone(440.0), SR)
    diffs = res["pairwise_cent_diffs"]
    # 三算法两两组合 = 3 对
    assert len(diffs) == 3
    assert res["consistent"] == (max(abs(d) for d in diffs) <= 50.0)


# ----------------------------------------------------------------------
# ② 双音：multi-pitch + pYIN 次谐波证据
# ----------------------------------------------------------------------

def test_dual_tone_multi_pitch_with_subharmonic_evidence():
    res = multi_algorithm_f0(_dual_tone(), SR)
    print(
        f"[T08] dual 440+660: pyin_median={res['pyin_hz']:.6f} Hz "
        f"(≈220 Hz sub-harmonic of 440) reason={res['reason']}"
    )
    assert res["applicable"] is False
    assert "multi-pitch" in res["reason"]
    # pYIN 实测落在 440/2 = 220 Hz 的 ±5% 内（次谐波证据）
    assert res["pyin_hz"] == pytest.approx(220.0, rel=0.05)
    assert "sub-harmonic" in res["reason"]


def test_dual_tone_integer_ratio_660_over_440_is_3_to_2():
    # 谱峰 660/440=1.5 落在 [1.4,1.6] 且间距 220>100 → 判多声部
    res = multi_algorithm_f0(_dual_tone(), SR)
    assert res["applicable"] is False
    assert "multi-pitch" in res["reason"]


# ----------------------------------------------------------------------
# ③ 静音：no-voiced
# ----------------------------------------------------------------------

def test_silence_no_voiced():
    res = multi_algorithm_f0(np.zeros(SR, dtype=np.float64), SR)
    assert res["applicable"] is False
    assert res["reason"] == "no-voiced"
    assert res["consistent"] is False


def test_harmonic_single_tone_integer_multiples_not_multi_pitch():
    # 含谐波的单音：880/440=2.0、1320/440=3.0 为整数倍 → 单音谐波，不判多声部
    res = multi_algorithm_f0(
        synthesize_tone(440.0, 1.0, SR, amplitude=0.8, waveform="harmonic"), SR
    )
    assert res["applicable"] is True
    assert res["reason"] == "ok"


# ----------------------------------------------------------------------
# ④ 判据 2：零外部后端引入（源码零命中 + 正对照）
# ----------------------------------------------------------------------

def test_no_external_pitch_backend_imports():
    # 拼接构造后端名，避免本测试文件本身构成 import 字面命中
    backends = ("au" + "bio", "parse" + "lmouth", "cre" + "pe")
    pattern = re.compile(
        r"^\s*(?:import|from)\s+(" + "|".join(backends) + r")\b", re.M
    )
    for name in ("pitch_consensus.py", "clock_calibration.py"):
        src = (_SRC_ROOT / "analysis" / name).read_text(encoding="utf-8")
        assert pattern.search(src) is None, f"{name} 引入了外部音高后端"
    # 正对照：同一正则对已知含外部后端 import 的样例必须命中
    positive = "import " + backends[0] + "\nfrom " + backends[1] + " import Thing\n"
    assert pattern.search(positive) is not None
    assert pattern.search("import " + backends[2]) is not None
