# SPDX-License-Identifier: GPL-3.0-only
"""调式/音律模板推断（T-920，音律标尺链第 3 项）。

输入 T-919 产出的 :class:`~acouscope.analysis.pcp.PCP` 音级分布，输出"更像哪种
内置音律模板、主音落在何处"的候选列表；为后续 A4 校准（T-921）与音律标尺叠加层
（T-922）提供依据。

匹配算法（自定口径，公式如下，纯 numpy）::

    # 对每个候选模板 T（内置模板，degrees 含隐含 1/1，去重后 n_deg 个音级）
    # 对每个主音旋转 r（主音候选 t = degrees[r]）：
    pattern_i = (degrees[i] + t) mod span        # span = n_bins * bin_cents
    window_i  = { bin b : circdist(center_b, pattern_i) <= tol_cents }
    peak_i    = max(weights[b] for b in window_i)          # 邻域峰值权重
    recall    = sum_i peak_i / sum(weights)                # 被模板音级解释的能量占比
    chance    = sum_i |window_i| / n_bins                  # 均匀分布下的期望占比
    recall_adj= clip((recall - chance) / (1 - chance), 0, 1)
    precision = #{i : peak_i > 0} / n_deg                  # 命中音级占比
    score     = recall_adj * precision

    # 模板得分 = max over 主音旋转 r；再对全部候选模板按 score 降序取 top_k

选用该口径的理由（详见 .pi/reports/T-920_report.json）：
1. ``recall`` 单独使用无法区分"音级集合的超集模板"（音级更多者会把 PCP 能量
   全部解释掉），故乘 ``precision`` 惩罚未被解释的音级；
2. ``chance`` 校正按均匀分布基线扣除，使均匀分布（白噪）PCP 的得分趋近 0、
   且各模板得分接近（margin 小），避免给出虚假结论；
3. 主音只在模板自身音级上旋转（"哪个音级当主音"），与 T-919 的音级归属口径一致。

学术诚信：每个 :class:`TuningMatch` 均携带 ``template_source``（出自内置模板
自身的来源标注），本模块不另作任何断言。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .tunings.templates import TEMPLATE_KEYS, get_template

__all__ = ["TOL_CENTS", "TuningMatch", "infer_tuning"]

#: 音级邻域容差（音分）：模板音级在 PCP 分箱上的命中半径。
TOL_CENTS: float = 15.0

_OCTAVE_CENTS = 1200.0


@dataclass(frozen=True)
class TuningMatch:
    """单个模板匹配结果（主音 + 得分）。

    ``tonic_cents``：主音相对 PCP 参考频率的音分（``0..1200``）；
    ``tonic_degree``：主音对应模板音级序号（去重后 ``degrees`` 的下标）；
    ``score``：匹配得分（``0..1``，口径见模块 docstring）；
    ``runner_up_score``：全局候选中紧随其后者的得分（末位为 ``0.0``）；
    ``margin``：``score - runner_up_score``，反映与次优候选的可区分度。
    """

    template_key: str
    template_name: str
    template_source: str
    tonic_cents: float
    tonic_degree: int
    score: float
    runner_up_score: float
    margin: float


def _dedup_degrees(degrees: tuple[float, ...], span: float) -> np.ndarray:
    """音级去重（按 ``mod span``，如末值 1200 与隐含 1/1 的 0 归一），升序返回。"""
    values: list[float] = []
    for item in degrees:
        folded = math.fmod(float(item), span)
        if folded < 0.0:
            folded += span
        if not values or abs(folded - values[-1]) > 1e-9:
            if not any(abs(folded - existing) < 1e-9 for existing in values):
                values.append(folded)
    values.sort()
    return np.asarray(values, dtype=float)


def _score_template(
    weights: np.ndarray,
    centers: np.ndarray,
    span: float,
    degrees: np.ndarray,
    tol_cents: float,
    total_weight: float,
) -> tuple[float, int, float]:
    """对单个模板求最佳主音旋转的得分。

    返回 ``(score, tonic_degree, tonic_cents)``。
    """
    n_bins = weights.size
    n_deg = degrees.size
    best_score = 0.0
    best_degree = 0
    best_tonic = float(degrees[0])
    for rotation in range(n_deg):
        tonic = float(degrees[rotation])
        pattern = np.mod(degrees + tonic, span)
        peaks = np.empty(n_deg, dtype=float)
        window_bins = 0
        for i, target in enumerate(pattern):
            distance = np.abs(centers - target)
            distance = np.minimum(distance, span - distance)
            hit = distance <= tol_cents
            window_bins += int(np.count_nonzero(hit))
            peaks[i] = float(weights[hit].max()) if np.any(hit) else 0.0
        recall = float(peaks.sum()) / total_weight
        chance = window_bins / float(n_bins)
        if chance >= 1.0:
            recall_adjusted = 0.0
        else:
            recall_adjusted = (recall - chance) / (1.0 - chance)
            recall_adjusted = min(1.0, max(0.0, recall_adjusted))
        precision = float(np.count_nonzero(peaks > 0.0)) / float(n_deg)
        score = recall_adjusted * precision
        if score > best_score + 1e-12:
            best_score = score
            best_degree = rotation
            best_tonic = tonic
    return best_score, best_degree, best_tonic


def infer_tuning(
    pcp,
    *,
    template_keys: tuple[str, ...] | list[str] | None = None,
    top_k: int = 3,
    ref_hz: float | None = None,
) -> list[TuningMatch]:
    """由音级分布推断最相近的音律模板与主音。

    参数
    ----
    pcp : :class:`~acouscope.analysis.pcp.PCP`（只读消费其 ``weights`` / ``bin_cents``
        / ``cent_min`` / ``ref_hz``）。
    template_keys : 候选模板键名子集，省略时取内置全部模板（``TEMPLATE_KEYS``）。
    top_k : 返回条数（按 ``score`` 降序）；``top_k <= 0`` 返回空列表。
    ref_hz : 可选参考频率口径校验；显式传入且与 ``pcp.ref_hz`` 不一致时抛
        ``ValueError``（本算法在音分域比较，参考频率只在 PCP 构建时起作用）。

    返回
    ----
    按得分降序的 :class:`TuningMatch` 列表；**空 / 全零 PCP 返回空列表**
    （不抛异常、不臆造结论）。
    """
    if top_k <= 0:
        return []
    weights = np.asarray(pcp.weights, dtype=float)
    if weights.size == 0:
        return []
    total_weight = float(weights.sum())
    if not np.isfinite(total_weight) or total_weight <= 0.0:
        return []
    if ref_hz is not None:
        given = float(ref_hz)
        if not math.isfinite(given) or given <= 0.0:
            raise ValueError("ref_hz 需为正有限值")
        if abs(given - float(pcp.ref_hz)) > 1e-9:
            raise ValueError(
                f"ref_hz（{given}）与 pcp.ref_hz（{pcp.ref_hz}）不一致：PCP 音分口径"
                "在构建时已固定，推断不再重算音分"
            )

    bin_cents = float(pcp.bin_cents)
    cent_min = float(pcp.cent_min)
    n_bins = weights.size
    span = n_bins * bin_cents
    centers = cent_min + (np.arange(n_bins, dtype=float) + 0.5) * bin_cents

    keys = tuple(TEMPLATE_KEYS if template_keys is None else template_keys)
    scored: list[tuple[str, float, int, float]] = []
    for key in keys:
        tuning = get_template(key)
        degrees = _dedup_degrees(tuning.degrees, span)
        score, degree, tonic = _score_template(
            weights, centers, span, degrees, TOL_CENTS, total_weight
        )
        scored.append((key, score, degree, tonic))

    order = sorted(range(len(scored)), key=lambda i: (-scored[i][1], i))
    matches: list[TuningMatch] = []
    for rank, position in enumerate(order[:top_k]):
        key, score, degree, tonic = scored[position]
        next_score = scored[order[rank + 1]][1] if rank + 1 < len(order) else 0.0
        tuning = get_template(key)
        matches.append(
            TuningMatch(
                template_key=key,
                template_name=tuning.name,
                template_source=tuning.source,
                tonic_cents=float(tonic) % _OCTAVE_CENTS,
                tonic_degree=int(degree),
                score=float(score),
                runner_up_score=float(next_score),
                margin=float(score - next_score),
            )
        )
    return matches
