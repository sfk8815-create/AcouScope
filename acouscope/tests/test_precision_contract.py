# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-B T04：精度合同（纯 numpy，零 Qt／零第三方依赖）。

金标准信号集 6 类（设计约定 §范围-1）：
  pure_tone / harmonic / inharmonic_piano / noise(SNR 30·20·10) /
  vibrato / two_tone(440+660)。

自研口径函数 :func:`to_cent_voicing` / :func:`cent_tolerance` /
:func:`classify_applicability`，docstring 声明「口径参考 mir_eval.melody
（MIT），未复制代码、未引入依赖」——**不 import mir_eval**、不引入任何
第三方包，纯 numpy + 标准库自研。

硬阈值（逐条 print 实测数值）：
  - 纯音 f0 误差 P95 ≤ 0.02 cent、max ≤ 0.05 cent（16× 零填充插值口径）；
  - SNR20 逐帧 |Δcent| 的 p95 ≤ 3 cent；
  - ``refine_peak_frequency`` 插值后 n_fft=2048 最大误差 ≤ 5 cent；
  - 非谐钢琴样与双音标 ``not_applicable`` 且**不计入**精度统计。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest

from acouscope.analysis.spectral import refine_peak_frequency

# ----------------------------------------------------------------------
# 常量 / 金标准口径
# ----------------------------------------------------------------------
SR = 44100.0
A4 = 440.0
N_FFT_PURE = 4096          # 纯音高精度测量窗
ZERO_PAD_PURE = 16         # 16× 零填充（呼应记录里的 zero_pad 字段）
N_FRAME = 2048             # SNR 逐帧窗
FRAME_ZERO_PAD = 4
N_FRAMES = 60
SEED = 20                  # 固定 seed（噪声可复现）
PURE_HZ = (110.0, 220.0, 440.0, 880.0)
PURE_OFFSETS_CENT = (-10.0, 0.0, 10.0)
SNR_LEVELS_DB = (30, 20, 10)
FAMILIES = (
    "pure_tone", "harmonic", "inharmonic_piano", "noise", "vibrato", "two_tone",
)
APPLICABLE = "applicable"
NOT_APPLICABLE = "not_applicable"
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope"


# ----------------------------------------------------------------------
# 自研口径函数（口径参考 mir_eval.melody（MIT），未复制代码、未引入依赖）
# ----------------------------------------------------------------------
def to_cent_voicing(f0_hz, ref_hz: float = A4):
    """把 f0(Hz) 序列换算为 (相对 A4 的 cent 序列, voicing 布尔序列)。

    口径参考 ``mir_eval.melody``（MIT，``hz2cents`` 与 voicing 判定），
    未复制上游代码、未引入依赖（自研口径函数）：

    - voiced 帧 = ``f0 > 0`` 且有限（非正／NaN 视为 unvoiced）；
    - ``cent = 1200 * log2(f0 / ref_hz)``，与 ``hz2cents`` 同式；
    - unvoiced 帧 cent 记为 NaN，不参与统计（同 ``evaluate`` 只在 ref/est
      均 voiced 的帧上计误差的口径）。
    """
    f0 = np.asarray(f0_hz, dtype=float)
    voiced = np.isfinite(f0) & (f0 > 0.0)
    cent = np.full(f0.shape, np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        cent[voiced] = 1200.0 * np.log2(f0[voiced] / float(ref_hz))
    return cent, voiced


def cent_tolerance(ref_f0_hz, est_f0_hz, ref_hz: float = A4) -> np.ndarray:
    """逐帧音分误差 ``|Δcent|``（仅双方均 voiced 的帧），返回一维 float 数组。

    口径参考 ``mir_eval.melody``（MIT，``evaluate`` 把 ref/est 均换算到 cent
    后逐帧求差），未复制上游代码、未引入依赖（自研口径函数）。调用方据此
    计算 P95 / max 等精度合同统计量。
    """
    ref_cent, ref_v = to_cent_voicing(ref_f0_hz, ref_hz)
    est_cent, est_v = to_cent_voicing(est_f0_hz, ref_hz)
    both = ref_v & est_v
    return np.abs(ref_cent[both] - est_cent[both])


def classify_applicability(case: dict) -> str:
    """判定某金标准信号是否适用「单声部基频精度合同」。

    口径参考 ``mir_eval.melody``（MIT，单声部 monophonic f0 评估前提），
    未复制上游代码、未引入依赖（自研口径函数）：

    - ``polyphonic``（双音／多声部）→ ``not_applicable``；
    - ``inharmonic``（非谐衰减钢琴样，分音非整数倍、无稳定单一 f0）
      → ``not_applicable``；
    - 其余单基频／近似谐波信号 → ``applicable``。

    标为 ``not_applicable`` 的信号**不计入任何精度统计**（禁把它们当精度
    失败、禁为此放宽阈值）。
    """
    meta = case.get("meta", {})
    if meta.get("polyphonic") or meta.get("inharmonic"):
        return NOT_APPLICABLE
    return APPLICABLE


def _estimate_f0(x, *, n_fft: int, zero_pad: int = 1,
                 fmin: float = 80.0, fmax: float = 1200.0) -> float:
    """零填充 FFT + 三点抛物线插值（调用批 A 共享纯函数）估单频 f0。"""
    seg = np.asarray(x, dtype=float)[:n_fft]
    if seg.size < n_fft:
        seg = np.pad(seg, (0, n_fft - seg.size))
    n = n_fft * zero_pad
    mag = np.abs(np.fft.rfft(seg * np.hanning(n_fft), n=n))
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    band = (freqs >= fmin) & (freqs <= fmax)
    idxs = np.flatnonzero(band)
    if idxs.size == 0:
        return float("nan")
    k = int(idxs[int(np.argmax(mag[band]))])
    return float(refine_peak_frequency(mag, freqs, k))


def _pure_tone(f_hz: float, off_cent: float, n: int = N_FFT_PURE) -> np.ndarray:
    """精确频率 f_true = f_hz * 2^(off_cent/1200) 的纯音（金标准真值）。"""
    f_true = f_hz * 2.0 ** (off_cent / 1200.0)
    return np.sin(2.0 * np.pi * f_true * np.arange(n) / SR)


def _tone_with_noise(snr_db: int, seed: int, n_frames: int = N_FRAMES):
    """SNR=snr_db dB 的含噪 440 Hz 逐帧信号（固定 seed，真值 440 Hz）。"""
    rng = np.random.RandomState(seed)
    total = n_frames * N_FRAME
    nn = np.arange(total)
    sig = np.sin(2.0 * np.pi * A4 * nn / SR)
    noise = rng.normal(0.0, 1.0, total)
    sig_rms = math.sqrt(float(np.mean(sig ** 2)))
    noise = noise / math.sqrt(float(np.mean(noise ** 2))) * sig_rms / (10.0 ** (snr_db / 20.0))
    return (sig + noise).reshape(n_frames, N_FRAME), A4


def _build_golden_set() -> list[dict]:
    """构建金标准信号集（6 类；含 12 纯音 + 3 档噪声 + 其余各 1）。"""
    cases: list[dict] = []
    for f in PURE_HZ:
        for off in PURE_OFFSETS_CENT:
            f_true = f * 2.0 ** (off / 1200.0)
            cases.append(dict(
                family="pure_tone", name=f"pure_{f:.0f}Hz_{off:+.0f}cent",
                x=_pure_tone(f, off), f0_hz=f_true, meta={"harmonic": True},
            ))
    # 谐波：基频 220，1..5 次谐波，幅度 1/k
    t = np.arange(N_FFT_PURE) / SR
    harm = sum((1.0 / k) * np.sin(2.0 * np.pi * 220.0 * k * t) for k in range(1, 6))
    cases.append(dict(family="harmonic", name="harmonic_220Hz",
                      x=harm, f0_hz=220.0, meta={"harmonic": True}))
    # 非谐衰减钢琴样：分音 f_k = k*f0*sqrt(1+B*k^2)（弦刚度非谐）+ 指数衰减
    inharm = np.zeros_like(t)
    for k in range(1, 6):
        f_k = k * 220.0 * math.sqrt(1.0 + 0.0004 * k * k)
        inharm += (1.0 / k) * np.sin(2.0 * np.pi * f_k * t) * math.exp(-3.0 * k * t[-1] * 0.0)
    inharm *= np.exp(-4.0 * t / t[-1])
    cases.append(dict(family="inharmonic_piano", name="inharmonic_piano_decay",
                      x=inharm, f0_hz=None,
                      meta={"inharmonic": True, "decay": True}))
    # 噪声 SNR 30/20/10 dB（固定 seed）
    for snr in SNR_LEVELS_DB:
        frames, f_true = _tone_with_noise(snr, SEED + snr)
        cases.append(dict(family="noise", name=f"noise_SNR{snr}dB",
                          x=frames, f0_hz=f_true,
                          meta={"snr_db": snr, "seed": SEED + snr}))
    # 颤音：440 Hz 中心、5 Hz 调制、峰值频偏对应 ±30 cent 的 FM 信号
    # （相位调制：瞬时频偏 = depth_hz * cos(2π·5·t)，峰值频偏 depth_hz）
    depth_hz = A4 * (2.0 ** (30.0 / 1200.0) - 1.0)
    vib = np.sin(2.0 * np.pi * A4 * t + (depth_hz / 5.0) * np.sin(2.0 * np.pi * 5.0 * t))
    cases.append(dict(family="vibrato", name="vibrato_440Hz_5Hz_pm30cent",
                      x=vib, f0_hz=A4, meta={"vibrato": True}))
    # 双音 440 + 660（多声部）
    two = np.sin(2.0 * np.pi * 440.0 * t) + 0.8 * np.sin(2.0 * np.pi * 660.0 * t)
    cases.append(dict(family="two_tone", name="two_tone_440_660",
                      x=two, f0_hz=None, meta={"polyphonic": True}))
    for c in cases:
        c["applicability"] = classify_applicability(c)
    return cases


GOLDEN_SET = _build_golden_set()


def _pure_tone_errors() -> np.ndarray:
    """12 个纯音（16× 零填充）逐条 |Δcent| 误差数组。"""
    errs = []
    for c in GOLDEN_SET:
        if c["family"] != "pure_tone":
            continue
        f_est = _estimate_f0(c["x"], n_fft=N_FFT_PURE, zero_pad=ZERO_PAD_PURE)
        e = cent_tolerance(np.array([c["f0_hz"]]), np.array([f_est]))
        errs.append(float(e[0]))
    return np.asarray(errs, dtype=float)


# ----------------------------------------------------------------------
# ① 金标准信号集 / 口径函数
# ----------------------------------------------------------------------
def test_golden_set_has_at_least_six_families():
    fams = {c["family"] for c in GOLDEN_SET}
    print("GOLDEN_SET families=%d names=%s" % (len(fams), sorted(fams)))
    assert len(fams) >= 6
    assert set(FAMILIES) <= fams
    assert len(GOLDEN_SET) >= 18
    print("GOLDEN_SET total_cases=%d" % len(GOLDEN_SET))


def test_golden_set_covers_required_signal_families():
    pure = [c for c in GOLDEN_SET if c["family"] == "pure_tone"]
    noise = [c for c in GOLDEN_SET if c["family"] == "noise"]
    print("PURE count=%d Hz=%s offsets=%s"
          % (len(pure), PURE_HZ, PURE_OFFSETS_CENT))
    print("NOISE count=%d snr_levels=%s seed_base=%d"
          % (len(noise), SNR_LEVELS_DB, SEED))
    assert len(pure) == len(PURE_HZ) * len(PURE_OFFSETS_CENT) == 12
    assert {c["meta"]["snr_db"] for c in noise} == set(SNR_LEVELS_DB)
    assert any(c["family"] == "harmonic" for c in GOLDEN_SET)
    assert any(c["family"] == "inharmonic_piano" for c in GOLDEN_SET)
    assert any(c["family"] == "vibrato" for c in GOLDEN_SET)
    assert any(c["family"] == "two_tone" for c in GOLDEN_SET)


def test_to_cent_voicing_formula_and_unvoiced():
    cent, voiced = to_cent_voicing(np.array([440.0, 880.0, 0.0, -1.0, np.nan]))
    print("to_cent_voicing cent=%s voiced=%s"
          % (np.round(cent, 6).tolist(), voiced.tolist()))
    assert cent[0] == pytest.approx(0.0)
    assert cent[1] == pytest.approx(1200.0)
    assert voiced.tolist() == [True, True, False, False, False]
    assert np.isnan(cent[2]) and np.isnan(cent[3]) and np.isnan(cent[4])


def test_cent_tolerance_only_counts_both_voiced_frames():
    # frame0 双方 voiced(440/440) / frame1 双方 voiced(440/880) → 计入 2 帧；
    # frame2 est unvoiced(0) / frame3 ref unvoiced(0) → 单侧 voiced 一律排除。
    ref = np.array([440.0, 440.0, 440.0, 0.0])
    est = np.array([440.0, 880.0, 0.0, 440.0])
    err = cent_tolerance(ref, est)
    print("cent_tolerance err=%s (frames 0,1 both-voiced; 2,3 excluded)"
          % err.tolist())
    assert err.size == 2
    assert err[0] == pytest.approx(0.0)
    assert err[1] == pytest.approx(1200.0)


def test_classify_applicability_flags_inharmonic_and_two_tone():
    marks = {c["family"]: c["applicability"] for c in GOLDEN_SET}
    na = sorted(c["name"] for c in GOLDEN_SET
                if c["applicability"] == NOT_APPLICABLE)
    print("not_applicable cases=%s" % na)
    assert marks["inharmonic_piano"] == NOT_APPLICABLE
    assert marks["two_tone"] == NOT_APPLICABLE
    for fam in ("pure_tone", "harmonic", "noise", "vibrato"):
        assert marks[fam] == APPLICABLE
    assert classify_applicability({"meta": {"polyphonic": True}}) == NOT_APPLICABLE
    assert classify_applicability({"meta": {"inharmonic": True}}) == NOT_APPLICABLE


def test_not_applicable_excluded_from_precision_stats():
    counted = [c for c in GOLDEN_SET if c["applicability"] == APPLICABLE]
    excluded = [c for c in GOLDEN_SET if c["applicability"] == NOT_APPLICABLE]
    print("precision_stat counted=%d excluded=%d (excluded families=%s)"
          % (len(counted), len(excluded), sorted({c["family"] for c in excluded})))
    assert not any(c["family"] in ("inharmonic_piano", "two_tone") for c in counted)
    assert {c["family"] for c in excluded} == {"inharmonic_piano", "two_tone"}
    assert len(counted) + len(excluded) == len(GOLDEN_SET)


# ----------------------------------------------------------------------
# ② 纯音精度合同（打印 P95 / max）
# ----------------------------------------------------------------------
def test_pure_tone_p95_le_0p02_and_max_le_0p05_cent():
    errs = _pure_tone_errors()
    p95 = float(np.percentile(errs, 95))
    mx = float(np.max(errs))
    print("PURE_TONE n=%d P95=%.6f cent max=%.6f cent mean=%.6f cent"
          % (errs.size, p95, mx, float(np.mean(errs))))
    for name, e in zip([c["name"] for c in GOLDEN_SET
                        if c["family"] == "pure_tone"], errs):
        print("  %-24s |Δ|=%.6f cent" % (name, e))
    assert errs.size == 12
    assert p95 <= 0.02, (p95, mx)
    assert mx <= 0.05, (p95, mx)


def test_pure_tone_all_offsets_traceable():
    for f in PURE_HZ:
        for off in PURE_OFFSETS_CENT:
            f_true = f * 2.0 ** (off / 1200.0)
            x = _pure_tone(f, off)
            f_est = _estimate_f0(x, n_fft=N_FFT_PURE, zero_pad=ZERO_PAD_PURE)
            e = float(cent_tolerance([f_true], [f_est])[0])
            print("TRACE %6.0f Hz %+4.0f cent f_true=%.6f f_est=%.6f |Δ|=%.6f cent"
                  % (f, off, f_true, f_est, e))
            assert e <= 0.05


# ----------------------------------------------------------------------
# ③ SNR20 逐帧 p95 ≤ 3 cent
# ----------------------------------------------------------------------
def test_snr20_framewise_p95_le_3_cent():
    frames, f_true = _tone_with_noise(20, SEED + 20)
    errs = []
    for fr in frames:
        f_est = _estimate_f0(fr, n_fft=N_FRAME, zero_pad=FRAME_ZERO_PAD,
                             fmin=300.0, fmax=600.0)
        errs.append(float(cent_tolerance([f_true], [f_est])[0]))
    errs = np.asarray(errs)
    p95 = float(np.percentile(errs, 95))
    mx = float(np.max(errs))
    print("SNR20 frames=%d framewise_p95=%.6f cent max=%.6f cent mean=%.6f cent"
          % (errs.size, p95, mx, float(np.mean(errs))))
    assert errs.size == N_FRAMES
    assert p95 <= 3.0, (p95, mx)


def test_noise_three_snr_levels_seed_reproducible():
    """固定 seed 可复现 + 三档 SNR 逐帧 p95 单调不减（噪声越大误差越大）。"""
    p95s = []
    for snr in SNR_LEVELS_DB:
        frames, f_true = _tone_with_noise(snr, SEED + snr)
        frames2, _ = _tone_with_noise(snr, SEED + snr)
        assert np.array_equal(frames, frames2)  # 固定 seed
        errs = [float(cent_tolerance([f_true], [_estimate_f0(
            fr, n_fft=N_FRAME, zero_pad=FRAME_ZERO_PAD,
            fmin=300.0, fmax=600.0)])[0]) for fr in frames]
        p95s.append(float(np.percentile(errs, 95)))
    print("NOISE SNR30/20/10 framewise_p95=%s cent"
          % ["%.6f" % p for p in p95s])
    assert p95s[0] <= p95s[1] <= p95s[2]
    assert p95s[1] <= 3.0  # SNR20 硬阈值


# ----------------------------------------------------------------------
# ④ refine_peak_frequency 插值精度（n_fft=2048 ≤ 5 cent）
# ----------------------------------------------------------------------
def _interp_errors(n_fft: int, offsets):
    interp, bins = [], []
    for off in offsets:
        f_true = A4 * 2.0 ** (off / 1200.0)
        x = np.sin(2.0 * np.pi * f_true * np.arange(n_fft) / SR)
        win = np.hanning(n_fft)
        mag = np.abs(np.fft.rfft(x * win))
        freqs = np.fft.rfftfreq(n_fft, 1.0 / SR)
        k = int(np.argmax(mag))
        f_interp = float(refine_peak_frequency(mag, freqs, k))
        interp.append(abs(1200.0 * math.log2(f_interp / f_true)))
        bins.append(abs(1200.0 * math.log2(float(freqs[k]) / f_true)))
    return np.asarray(interp), np.asarray(bins)


def test_interp_nfft_2048_max_error_le_5_cent():
    offsets = np.linspace(-50.0, 50.0, 7)
    interp, bins = _interp_errors(2048, offsets)
    print("INTERP n_fft=2048 offsets=%s" % np.round(offsets, 1).tolist())
    print("  interp_err_cent=%s" % np.round(interp, 4).tolist())
    print("  bin_err_cent=%s" % np.round(bins, 4).tolist())
    print("  interp_max=%.4f cent interp_p95=%.4f cent bin_max=%.4f cent"
          % (float(interp.max()), float(np.percentile(interp, 95)),
             float(bins.max())))
    assert float(interp.max()) <= 5.0, interp
    assert float(interp.max()) < float(bins.max())


def test_interp_reduces_error_at_least_80pct_vs_bin():
    for n_fft in (2048, 8192):
        interp, bins = _interp_errors(n_fft, np.linspace(-50.0, 50.0, 7))
        drop = 1.0 - float(interp.sum()) / float(bins.sum())
        print("INTERP n_fft=%d drop=%.4f interp_max=%.4f bin_max=%.4f"
              % (n_fft, drop, float(interp.max()), float(bins.max())))
        assert drop >= 0.80, (n_fft, drop)
    assert float(_interp_errors(8192, np.linspace(-50.0, 50.0, 7))[0].max()) <= 1.1


# ----------------------------------------------------------------------
# ⑤ 零新增依赖（import mir_eval 零命中，配正对照）
# ----------------------------------------------------------------------
def test_zero_new_dependency_no_mir_eval_import():
    # 只扫生产源码目录（tests/ 不是运行时源码；且测试文件本身含检索串字面量，
    # 若纳入会自命中）。检索口径 = 真实 import 语句（行首 `import mir_eval` /
    # `from mir_eval`），而非任意子串出现（docstring 里声明口径的串不算依赖）。
    srcs = list(_SRC_ROOT.rglob("*.py"))
    mir_re = re.compile(r"^\s*(?:import\s+mir_eval\b|from\s+mir_eval\b)", re.M)
    np_re = re.compile(r"^\s*(?:import\s+numpy\b|from\s+numpy\b)", re.M)
    hits = [str(p) for p in srcs
            if mir_re.search(p.read_text(encoding="utf-8", errors="replace"))]
    # 正对照：同一正则口径能命中真实存在的 numpy import（证明零命中非检索失效）
    np_hits = [str(p) for p in srcs
               if np_re.search(p.read_text(encoding="utf-8", errors="replace"))]
    print("DEPENDENCY scanned=%d real 'import mir_eval' statements=%d / "
          "numpy import statements=%d (positive control)"
          % (len(srcs), len(hits), len(np_hits)))
    assert hits == [], hits
    assert len(np_hits) > 0  # 正对照：检索有效
    # 本测试文件也不得含真实 mir_eval import 语句
    assert mir_re.search(Path(__file__).read_text(encoding="utf-8")) is None
    # 口径 docstring 声明（未复制代码、未引入依赖）
    for fn in (to_cent_voicing, cent_tolerance, classify_applicability):
        assert "mir_eval.melody" in (fn.__doc__ or "")
        assert "MIT" in (fn.__doc__ or "")
        assert "未复制上游代码、未引入依赖" in (fn.__doc__ or "")
