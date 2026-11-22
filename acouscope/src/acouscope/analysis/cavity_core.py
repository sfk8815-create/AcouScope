# SPDX-License-Identifier: GPL-3.0-only
"""腔核段级候选（B2-01 / PI-P5 批次 2）。

口径更正（2026-10-25 确定）：本模块产出为**段级候选**——每个 stable run
一个，区间即该 run 的起讫；它不是段内更窄的「核心窗」。核心窗若另行给出，
只作辅助列，且**不得用固定比例切头尾**（固定比例＝另一个自设阈值）。

边界口径（写作侧已锁定，本模块重申，勿自行放宽）：
- **腔核只给候选，不给判定**：本模块只输出候选区间（起讫秒）+ 音级归属 +
  不确定度三项，供写作侧验证与后续批次消费；人工/专家判定留痕不在本模块
  职责内（p.9；孙毅 pp.126-127）。
- 候选 = 音符段内 ``state_runs`` 中 ``state_name == "stable"`` 的运行
  （B1-01a 段内同态压茬结果）；非 stable 运行与无 ``state_runs`` 的 note
  （旧数据 / simple 分段）**不产候选**——无段型信息即无候选，禁启发式回退。
- 候选区间 ⊆ 单一 note 的单一 run，**不得跨段**。
- 三态（attack/stable/inter）与「腔头—腔腹—腔尾」为功能类比、非等同；本模块
  不做该映射，只消费 HMM 段内状态名。

表述纪律（metadata.py:23-24 同规）：本模块只陈述「按 state_runs 的 stable 运行
建立候选区间」，不作「符合/覆盖标准」级宣称。

纯函数、无 UI、不入项目文件（最小面）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .pitch_grid import PitchGridModel

__all__ = [
    "CoreCandidate",
    "core_candidates",
]

#: 段内状态名（note_hmm._STATE_LABELS 口径）；仅 stable 运行产候选
_STABLE_RUN_STATE = "stable"

#: state_runs 元素形制：(起帧, 讫帧, 起秒, 讫秒, 态名)
_RUN_ARITY = 5


@dataclass(frozen=True)
class CoreCandidate:
    """腔核候选区间：起讫秒 + 音级归属 + 不确定度（三项，定死禁增删）。

    - ``start_s`` / ``end_s``：候选区间起讫秒，取来源 stable run 的第 3/4 位
      （与 run 逐位相等，不再做任何数值加工）；
    - ``degree_index`` / ``deviation_cents``：继承来源 note 的段级归属
      （PitchNote.degree_index / degree_deviation_cents，B1-02a）；note 未传
      律制时为 None（禁回退 12TET）；
    - ``conf``：来源 note 的段级置信度（PitchNote.conf）。
    """

    start_s: float
    end_s: float
    degree_index: int | None
    deviation_cents: float | None
    conf: float


def core_candidates(model: PitchGridModel) -> list[CoreCandidate]:
    """由音高网格模型提取腔核候选区间（确定性规则，禁启发式阈值）。

    规则（定死）：
    1. 遍历 ``model.notes``；
    2. 对每 note 的 ``state_runs`` 中每个 ``state_name == "stable"`` 的 run
       产出一个候选：起讫秒取该 run 的第 3/4 位（逐位相等），音级归属与
       不确定度继承该 note 的段级字段，``conf`` 取该 note 的段级 conf；
    3. 非 stable run、无 ``state_runs`` 的 note（旧数据 / simple 分段）不产
       候选；
    4. 候选区间不得跨段（⊆ 单一 note 的单一 run）。

    返回按 (note 序, run 序) 的遍历序；空列表 = 无候选（诚实可判据）。

    只给候选不给判定：本函数不做任何腔核/非腔核裁决。
    """
    candidates: list[CoreCandidate] = []
    for note in model.notes:
        for run in note.state_runs:
            if len(run) != _RUN_ARITY:
                continue  # 防御：非五元组条目（旧数据/损坏条目）不产候选
            _, _, start_s, end_s, state_name = run
            if state_name != _STABLE_RUN_STATE:
                continue
            candidates.append(
                CoreCandidate(
                    start_s=start_s,
                    end_s=end_s,
                    degree_index=note.degree_index,
                    deviation_cents=note.degree_deviation_cents,
                    conf=note.conf,
                )
            )
    return candidates
