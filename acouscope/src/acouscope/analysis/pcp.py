# SPDX-License-Identifier: GPL-3.0-only
"""音级分布（PCP / chroma）计算（T-919，音律标尺链第 2 项）。

以 f0 轨迹（Hz）为输入，按 ``dsp/units.hz_to_cents`` 的音分口径把每帧折算到
一个音级分箱，得到 120 bin（10 音分/bin，跨 0..1200 音分）的音级权重分布，
供 T-920 的调式/音律模板推断消费。

口径约定：
- 权重已归一化（``weights.sum() ≈ 1``）；**无有效帧时为全零（不抛异常）**。
- 有效帧判定：``isfinite(f0) & (f0 > 0) & (confidence >= min_confidence)``。
- 音分折叠：``cent_min + mod(cents - cent_min, cent_max - cent_min)``，
  默认折入一个八度 ``[0, 1200)``。
- 传入 ``TuningSystem`` 时额外记录每帧的音级归属（``degree_index``），并原样
  带出该音律模型的 ``name`` / ``source``；来源文本出自音律模型自身，本模块
  不另作任何断言。
- 全程 numpy 向量化，无逐帧 Python 循环。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..dsp.units import hz_to_cents

__all__ = ["PCP", "PCPParams", "build_pcp"]

#: 常用分箱数（10 音分/bin 的 120 bin 为默认口径）。
COMMON_BIN_COUNTS: tuple[int, ...] = (12, 24, 120)

_OCTAVE_CENTS = 1200.0

#: 音级归属的向量化分块长度（限制峰值内存）。
_DEGREE_CHUNK = 65536


@dataclass(frozen=True)
class PCPParams:
    """PCP 计算参数。

    ``bins``：分箱数（常用 12/24/120，默认 120 = 10 音分/bin）；
    ``cent_min`` / ``cent_max``：折叠区间（默认一个八度 ``[0, 1200)``）；
    ``weight_by_confidence``：是否按 confidence 加权（否则每有效帧计 1）；
    ``min_confidence``：confidence 低于该阈值的帧直接丢弃。
    """

    bins: int = 120
    cent_min: float = 0.0
    cent_max: float = 1200.0
    weight_by_confidence: bool = True
    min_confidence: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.bins, bool) or int(self.bins) != self.bins or int(self.bins) < 1:
            raise ValueError("PCPParams.bins 需为 >= 1 的整数")
        object.__setattr__(self, "bins", int(self.bins))
        cent_min = float(self.cent_min)
        cent_max = float(self.cent_max)
        if not (np.isfinite(cent_min) and np.isfinite(cent_max)):
            raise ValueError("PCPParams.cent_min/cent_max 需为有限值")
        if cent_max <= cent_min:
            raise ValueError("PCPParams.cent_max 必须大于 cent_min")
        object.__setattr__(self, "cent_min", cent_min)
        object.__setattr__(self, "cent_max", cent_max)
        min_conf = float(self.min_confidence)
        if not np.isfinite(min_conf):
            raise ValueError("PCPParams.min_confidence 需为有限值")
        object.__setattr__(self, "min_confidence", min_conf)

    @property
    def span_cents(self) -> float:
        """折叠区间宽度（音分）。"""
        return self.cent_max - self.cent_min

    @property
    def bin_cents(self) -> float:
        """单个分箱宽度（音分）。"""
        return self.span_cents / self.bins


@dataclass
class PCP:
    """音级分布（pitch class profile）。

    ``weights``：``shape == (n_bins,)`` 的归一化权重（全无效输入时全零）；
    ``bin_cents``：分箱宽度（音分）；``ref_hz``：音分参考频率（Hz）；
    ``tuning_name`` / ``tuning_source``：传入音律模型的名称与来源（未传时为空串）；
    ``n_frames_used``：参与统计的有效帧数；
    ``cent_min``：分箱区间起点（音分），用于 ``bin_center`` 反算；
    ``degree_index``：每有效帧的音级归属（仅在传入 ``TuningSystem`` 时非 None）。
    """

    weights: np.ndarray
    bin_cents: float
    ref_hz: float
    tuning_name: str = ""
    tuning_source: str = ""
    n_frames_used: int = 0
    cent_min: float = 0.0
    degree_index: np.ndarray | None = None

    def __post_init__(self) -> None:
        weights = np.asarray(self.weights, dtype=float).reshape(-1)
        if weights.size == 0:
            raise ValueError("PCP.weights 不可为空数组（无有效帧时也应为全零定长数组）")
        if not np.all(np.isfinite(weights)):
            raise ValueError("PCP.weights 含非有限值")
        if not np.any(weights < 0.0):
            object.__setattr__(self, "weights", weights)
        else:
            raise ValueError("PCP.weights 不可含负值")
        bin_cents = float(self.bin_cents)
        if not np.isfinite(bin_cents) or bin_cents <= 0.0:
            raise ValueError("PCP.bin_cents 需为正有限值")
        object.__setattr__(self, "bin_cents", bin_cents)
        ref_hz = float(self.ref_hz)
        if not np.isfinite(ref_hz) or ref_hz <= 0.0:
            raise ValueError("PCP.ref_hz 需为正有限值")
        object.__setattr__(self, "ref_hz", ref_hz)
        object.__setattr__(self, "cent_min", float(self.cent_min))
        if self.degree_index is not None:
            degrees = np.asarray(self.degree_index, dtype=np.int64).reshape(-1)
            object.__setattr__(self, "degree_index", degrees)
        object.__setattr__(self, "n_frames_used", int(self.n_frames_used))

    @property
    def n_bins(self) -> int:
        """分箱数。"""
        return int(self.weights.size)

    @property
    def span_cents(self) -> float:
        """分箱区间宽度（音分）。"""
        return self.n_bins * self.bin_cents

    @property
    def total_weight(self) -> float:
        """权重总和（归一化 PCP 约为 1；全零 PCP 为 0）。"""
        return float(self.weights.sum())

    @property
    def is_empty(self) -> bool:
        """是否为空 PCP（无任何有效权重）。"""
        return self.total_weight <= 0.0

    def bin_center(self, index: int) -> float:
        """分箱中心音分。"""
        return self.cent_min + (int(index) + 0.5) * self.bin_cents

    def peak_bins(self, top_k: int = 6) -> list[tuple[int, float]]:
        """按权重降序返回前 ``top_k`` 个分箱：``[(bin 索引, 分箱中心音分), ...]``。

        权重为 0 的分箱也可能入选（当 ``top_k`` 大于非零箱数时），便于调用方
        自行判断置信度；``top_k <= 0`` 返回空列表。
        """
        if top_k <= 0 or self.weights.size == 0:
            return []
        k = min(int(top_k), self.weights.size)
        order = np.argsort(-self.weights, kind="stable")[:k]
        return [(int(index), self.bin_center(int(index))) for index in order]

    def to_classes(self, n: int = 12) -> "PCP":
        """按等分合并为 ``n`` 个音级类，返回新的 :class:`PCP`（权重重新归一化）。"""
        if isinstance(n, bool) or int(n) != n or int(n) < 1:
            raise ValueError("to_classes 的 n 需为 >= 1 的整数")
        n = int(n)
        bins = self.n_bins
        class_of_bin = (np.arange(bins, dtype=np.int64) * n) // bins
        merged = np.bincount(class_of_bin, weights=self.weights, minlength=n)[:n]
        total = float(merged.sum())
        if total > 0.0:
            merged = merged / total
        return PCP(
            weights=merged,
            bin_cents=self.span_cents / n,
            ref_hz=self.ref_hz,
            tuning_name=self.tuning_name,
            tuning_source=self.tuning_source,
            n_frames_used=self.n_frames_used,
            cent_min=self.cent_min,
            degree_index=None,
        )


def _degree_index_for(tuning: object, cents: np.ndarray) -> np.ndarray:
    """音级归属（向量化）：语义同 :meth:`TuningSystem.cents_to_degree`。

    实现要点：把音律音级网格按八度周期平铺三份后做一次 ``searchsorted`` 定位，
    再在左右候选里取更近者；平局取较低音级号，与 ``cents_to_degree`` 的
    "首个更优者胜出" 口径一致（抽样逐帧核对见 tests/test_pcp.py）。
    """
    grid = np.asarray(tuning.degrees, dtype=float)  # type: ignore[attr-defined]
    if grid.size == 0:
        raise ValueError("TuningSystem.degrees 不可为空")
    count = grid.size - 1
    if count <= 0:
        return np.round(cents / _OCTAVE_CENTS).astype(np.int64)
    tiled = np.concatenate((grid - _OCTAVE_CENTS, grid, grid + _OCTAVE_CENTS))
    tile_degree = np.concatenate(
        (
            np.arange(grid.size, dtype=np.int64) - count,
            np.arange(grid.size, dtype=np.int64),
            np.arange(grid.size, dtype=np.int64) + count,
        )
    )
    out = np.empty(cents.shape, dtype=np.int64)
    for start in range(0, cents.size, _DEGREE_CHUNK):
        chunk = cents[start : start + _DEGREE_CHUNK]
        with np.errstate(invalid="ignore"):
            octave = np.floor(chunk / _OCTAVE_CENTS)
            residual = chunk - _OCTAVE_CENTS * octave
        octave = np.where(np.isfinite(octave), octave, 0.0)
        residual = np.where(np.isfinite(residual), residual, 0.0)
        position = np.searchsorted(tiled, residual)
        left = np.clip(position - 1, 0, tiled.size - 1)
        right = np.clip(position, 0, tiled.size - 1)
        take_right = (tiled[right] - residual) < (residual - tiled[left])
        chosen = np.where(take_right, right, left)
        out[start : start + _DEGREE_CHUNK] = tile_degree[chosen] + count * octave.astype(
            np.int64
        )
    return out


def _zero_pcp(params: PCPParams, ref_hz: float, tuning: object | None) -> PCP:
    """全零 PCP（无效输入的安全返回值）。"""
    name = "" if tuning is None else str(tuning.name)  # type: ignore[attr-defined]
    source = "" if tuning is None else str(tuning.source)  # type: ignore[attr-defined]
    return PCP(
        weights=np.zeros(params.bins, dtype=float),
        bin_cents=params.bin_cents,
        ref_hz=ref_hz,
        tuning_name=name,
        tuning_source=source,
        n_frames_used=0,
        cent_min=params.cent_min,
        degree_index=None,
    )


def build_pcp(
    freq_hz,
    confidence=None,
    *,
    params: PCPParams | None = None,
    ref_hz: float = 440.0,
    tuning=None,
) -> PCP:
    """由 f0 轨迹构建音级分布（numpy 向量化）。

    参数
    ----
    freq_hz : 一维可迭代/数组，f0（Hz）；NaN 或 <= 0 视为无效帧。
    confidence : 可选，同 shape 的有声概率；``None`` 时全部有效帧权重为 1。
    params : :class:`PCPParams`，省略时用默认（120 bin，0..1200 音分）。
    ref_hz : 音分参考频率（Hz），经 ``dsp/units.hz_to_cents(..., ref_freq=)`` 折算。
    tuning : 可选 :class:`~acouscope.analysis.tunings.tuning_system.TuningSystem`；
        传入时额外记录每帧的 ``degree_index`` 音级归属，并原样带出其 name/source。

    返回
    ----
    :class:`PCP`。空输入 / 全 NaN / 全 0 / 全被 ``min_confidence`` 滤除时，
    返回全零 PCP（``is_empty`` 为 True），**不抛异常**。
    """
    p = PCPParams() if params is None else params
    reference = float(ref_hz)
    if not np.isfinite(reference) or reference <= 0.0:
        raise ValueError("ref_hz 需为正有限值")

    freq = np.asarray(freq_hz, dtype=float).reshape(-1)
    if freq.size == 0:
        return _zero_pcp(p, reference, tuning)

    if confidence is None:
        conf = np.ones(freq.shape, dtype=float)
    else:
        conf = np.asarray(confidence, dtype=float).reshape(-1)
        if conf.size != freq.size:
            raise ValueError(
                f"confidence 长度（{conf.size}）与 freq_hz 长度（{freq.size}）不一致"
            )

    valid = np.isfinite(freq) & (freq > 0.0) & np.isfinite(conf) & (conf >= p.min_confidence)
    n_valid = int(np.count_nonzero(valid))
    if n_valid == 0:
        return _zero_pcp(p, reference, tuning)

    frame_weight = conf[valid] if p.weight_by_confidence else np.ones(n_valid, dtype=float)
    cents = np.asarray(hz_to_cents(freq[valid], ref_freq=reference), dtype=float)

    span = p.span_cents
    folded = p.cent_min + np.mod(cents - p.cent_min, span)
    index = np.floor((folded - p.cent_min) / p.bin_cents).astype(np.int64)
    index = np.clip(index, 0, p.bins - 1)
    histogram = np.bincount(index, weights=frame_weight, minlength=p.bins)[: p.bins]
    total = float(histogram.sum())
    weights = histogram / total if total > 0.0 else np.zeros(p.bins, dtype=float)

    degrees = None
    if tuning is not None:
        tuning_cents = np.asarray(
            hz_to_cents(freq[valid], ref_freq=float(tuning.reference_freq)), dtype=float
        )
        degrees = _degree_index_for(tuning, tuning_cents)

    return PCP(
        weights=weights,
        bin_cents=p.bin_cents,
        ref_hz=reference,
        tuning_name="" if tuning is None else str(tuning.name),
        tuning_source="" if tuning is None else str(tuning.source),
        n_frames_used=n_valid,
        cent_min=p.cent_min,
        degree_index=degrees,
    )
