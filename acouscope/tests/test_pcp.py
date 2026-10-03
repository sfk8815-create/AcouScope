# SPDX-License-Identifier: GPL-3.0-only
"""音级分布 PCP 单元测试（T-919）。PCP_TEST_V1

口径：纯 numpy 计算、无 Qt、无文件 IO；合成信号自包含可复现；
无效输入（空/全 NaN/全 0/全低于阈值）安全归零且不抛异常。
"""

import time

import numpy as np
import pytest

from acouscope.analysis.pcp import COMMON_BIN_COUNTS, PCP, PCPParams, build_pcp
from acouscope.analysis.tunings.templates import get_template
from acouscope.dsp.units import cents_to_hz

REF_HZ = 440.0
BIN_CENTS = 10.0


def _freqs_from_cents(cents, ref_hz: float = REF_HZ) -> np.ndarray:
    """音分（相对 ref_hz）→ 频率（Hz）。"""
    return np.asarray(cents_to_hz(np.asarray(cents, dtype=float), ref_freq=ref_hz), dtype=float)


def _repeat(values, times: int) -> np.ndarray:
    return np.repeat(np.asarray(values, dtype=float), times)


def test_params_defaults_and_validation():
    params = PCPParams()
    assert (params.bins, params.cent_min, params.cent_max) == (120, 0.0, 1200.0)
    assert params.weight_by_confidence is True
    assert params.min_confidence == 0.0
    assert params.span_cents == pytest.approx(1200.0)
    assert params.bin_cents == pytest.approx(BIN_CENTS)
    with pytest.raises(ValueError):
        PCPParams(bins=0)
    with pytest.raises(ValueError):
        PCPParams(cent_min=1200.0, cent_max=1200.0)
    with pytest.raises(ValueError):
        PCPParams(min_confidence=float("nan"))


def test_12tet_scale_peaks_and_classes():
    # 落在 bin 中心（+5 音分）以避免 Hz↔音分往返的浮点尾差跨越分箱边界
    cents = np.arange(5.0, 1200.0, 100.0)
    pcp = build_pcp(_repeat(_freqs_from_cents(cents), 5), np.ones(60))

    assert isinstance(pcp, PCP)
    assert pcp.n_frames_used == 60
    assert pcp.n_bins == 120
    assert pcp.ref_hz == pytest.approx(REF_HZ)
    assert pcp.weights.sum() == pytest.approx(1.0)
    assert not pcp.is_empty

    peaks = pcp.peak_bins(12)
    indices = sorted(index for index, _ in peaks)
    # 合成频率经 Hz→音分往返存在浮点尾差，允许 ±1 bin（需求说明口径）
    assert all(
        abs(index - expected) <= 1 for index, expected in zip(indices, range(0, 120, 10))
    )
    assert len(set(indices)) == 12
    for index, cents_at in peaks:
        assert cents_at == pytest.approx(pcp.bin_center(index))
        assert abs(cents_at - index * BIN_CENTS) <= 2 * BIN_CENTS

    classes = pcp.to_classes(12)
    assert classes.n_bins == 12
    assert classes.bin_cents == pytest.approx(100.0)
    assert classes.weights.sum() == pytest.approx(1.0)
    assert classes.ref_hz == pytest.approx(pcp.ref_hz)
    assert classes.n_frames_used == pcp.n_frames_used
    assert int(np.argmax(classes.weights)) == 0
    assert np.allclose(classes.weights, 1.0 / 12.0)
    assert classes.degree_index is None
    with pytest.raises(ValueError):
        pcp.to_classes(0)


def test_octave_folding_and_reference_frequency():
    folded = build_pcp(np.array([220.0, 440.0, 880.0]))
    assert folded.n_frames_used == 3
    assert int(np.argmax(folded.weights)) == 0
    assert folded.weights[0] == pytest.approx(1.0)

    ref_shifted = build_pcp(np.array([440.0, 880.0]), ref_hz=220.0)
    assert int(np.argmax(ref_shifted.weights)) == 0
    assert ref_shifted.weights[0] == pytest.approx(1.0)

    sixth = build_pcp(_freqs_from_cents([605.0]))
    assert int(np.argmax(sixth.weights)) == 60

    with pytest.raises(ValueError):
        build_pcp(np.array([440.0]), ref_hz=0.0)


def test_common_bin_counts_supported():
    assert COMMON_BIN_COUNTS == (12, 24, 120)
    freqs = _freqs_from_cents([0.0, 100.0, 350.0])
    for bins in COMMON_BIN_COUNTS:
        pcp = build_pcp(freqs, params=PCPParams(bins=bins))
        assert pcp.n_bins == bins
        assert pcp.bin_cents == pytest.approx(1200.0 / bins)
        assert pcp.weights.sum() == pytest.approx(1.0)
        assert int(np.argmax(pcp.weights)) >= 0


def test_custom_cent_window():
    freqs = _freqs_from_cents([5.0, 605.0, 1205.0])
    pcp = build_pcp(freqs, params=PCPParams(bins=12, cent_min=0.0, cent_max=600.0))
    assert pcp.n_bins == 12
    assert pcp.bin_cents == pytest.approx(50.0)
    # 5 / 605 / 1205 音分折入 [0, 600) 后都落在第 0 箱
    assert pcp.weights[0] == pytest.approx(1.0)


def test_confidence_weighting_and_min_confidence():
    freqs = np.array([440.0, float(_freqs_from_cents([605.0])[0])])
    confidence = np.array([1.0, 0.25])

    weighted = build_pcp(freqs, confidence)
    assert weighted.weights[0] == pytest.approx(0.8)
    assert weighted.weights[60] == pytest.approx(0.2)

    flat = build_pcp(freqs, confidence, params=PCPParams(weight_by_confidence=False))
    assert flat.weights[0] == pytest.approx(0.5)
    assert flat.weights[60] == pytest.approx(0.5)

    filtered = build_pcp(freqs, confidence, params=PCPParams(min_confidence=0.5))
    assert filtered.n_frames_used == 1
    assert filtered.weights[0] == pytest.approx(1.0)

    dropped = build_pcp(
        freqs, np.array([0.4, 0.2]), params=PCPParams(min_confidence=0.5)
    )
    assert dropped.is_empty
    assert dropped.n_frames_used == 0


@pytest.mark.parametrize(
    "freqs",
    [
        np.array([]),
        np.array([np.nan] * 8),
        np.zeros(8),
        np.array([-440.0, 0.0, np.inf]),
    ],
)
def test_invalid_inputs_return_zero_pcp_without_raising(freqs):
    pcp = build_pcp(freqs)
    assert pcp.is_empty
    assert pcp.weights.shape == (120,)
    assert pcp.weights.sum() == 0.0
    assert pcp.n_frames_used == 0
    assert pcp.peak_bins(3)[0][1] == pytest.approx(pcp.bin_center(0))


def test_confidence_length_mismatch_raises():
    with pytest.raises(ValueError):
        build_pcp(np.array([440.0, 441.0]), np.array([1.0]))


def test_tuning_degree_attribution_just_major_vs_12tet():
    just = get_template("just_major")
    tet = get_template("12tet")
    freqs = _freqs_from_cents(just.degrees)

    pcp_just = build_pcp(freqs, tuning=just)
    assert pcp_just.tuning_name == just.name
    assert pcp_just.tuning_source == just.source
    assert pcp_just.tuning_source
    expected_just = [just.freq_to_degree(float(freq)) for freq in freqs]
    assert list(pcp_just.degree_index) == expected_just
    assert expected_just == list(range(len(just.degrees)))
    # 纯律大三度（386.31c，帧序号 2）落在模板第 2 音级
    assert pcp_just.degree_index[2] == 2
    assert just.degrees[2] == pytest.approx(386.31, abs=0.01)

    pcp_tet = build_pcp(freqs, tuning=tet)
    expected_tet = [tet.freq_to_degree(float(freq)) for freq in freqs]
    assert list(pcp_tet.degree_index) == expected_tet
    # 同一频率在 12TET 下归到第 4 音级（400c），与纯律口径不同
    assert pcp_tet.degree_index[2] == 4
    assert pcp_tet.tuning_name == tet.name

    default = build_pcp(freqs)
    assert default.degree_index is None
    assert default.tuning_name == ""
    assert default.tuning_source == ""


def test_degree_attribution_matches_tuning_api_on_sample():
    tuning = get_template("chinese_sanfen_sunyi_12")
    rng = np.random.default_rng(11)
    cents = rng.uniform(-900.0, 2100.0, size=200)
    freqs = _freqs_from_cents(cents)
    pcp = build_pcp(freqs, tuning=tuning)
    expected = np.array([tuning.freq_to_degree(float(freq)) for freq in freqs])
    assert np.array_equal(pcp.degree_index, expected)


def test_peak_bins_ordering_and_limit():
    freqs = np.concatenate(
        [
            _repeat(_freqs_from_cents([300.0]), 6),
            _repeat(_freqs_from_cents([700.0]), 3),
            _repeat(_freqs_from_cents([1100.0]), 1),
        ]
    )
    pcp = build_pcp(freqs)
    peaks = pcp.peak_bins(2)
    assert abs(peaks[0][0] - 30) <= 1
    assert abs(peaks[1][0] - 70) <= 1
    assert pcp.weights[peaks[0][0]] > pcp.weights[peaks[1][0]] > 0.0
    assert peaks[0][1] == pytest.approx(pcp.bin_center(peaks[0][0]))
    assert pcp.peak_bins(0) == []
    assert len(pcp.peak_bins(500)) == 120


def test_vectorized_performance_smoke():
    rng = np.random.default_rng(3)
    n_frames = 100_000
    freqs = rng.uniform(60.0, 1000.0, size=n_frames)
    confidence = rng.uniform(0.3, 1.0, size=n_frames)

    start = time.perf_counter()
    pcp = build_pcp(freqs, confidence)
    elapsed = time.perf_counter() - start

    assert pcp.n_frames_used == n_frames
    assert pcp.weights.sum() == pytest.approx(1.0)
    # 宽阈值：仅用于发现退化为逐帧 Python 循环的实现
    assert elapsed < 1.0, f"10^5 帧耗时 {elapsed:.4f}s，疑似未向量化"
    print(f"[PCP 性能] 10^5 帧 build_pcp 实测 {elapsed * 1000:.2f} ms")
