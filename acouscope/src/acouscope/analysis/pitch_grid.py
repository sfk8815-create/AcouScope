# SPDX-License-Identifier: GPL-3.0-only
"""音高网格模型与吸附（T-801，T-8xx 首任务）。

与音高后端（pYIN / SwiftF0 / RMVPE）解耦的音符块数据模型，及可配置吸附
（12 平均律 / 自定义 cents 网格 / 关闭）。设计约束：
- 吸附只作用于表示层（snapped_f0_hz），原始连续 f0_hz 永不修改；
  任何离散网格值禁止直接充当最终输出，偏差量（deviation_cents）恒随行保存。
- 音符分段为简易口径（PLACEHOLDER 参数），后续由音符分段 HMM 任务替换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from ..dsp.units import cents_to_hz, hz_to_cents

if TYPE_CHECKING:  # 仅类型标注用，避免运行时导入 tunings 子包
    from .tunings.tuning_system import TuningSystem

__all__ = [
    "SNAP_12TET",
    "SNAP_OFF",
    "PitchGridModel",
    "PitchNote",
    "build_pitch_grid",
    "grid_cents_for_tuning",
    "snap_cents_12tet",
    "snap_cents_grid",
]

SNAP_OFF = "off"
SNAP_12TET = "12tet"


def snap_cents_12tet(cents):
    """12 平均律吸附：最近半音（100 cents 栅格，±50 cent 回折）。

    返回 (snapped_cents, deviation_cents)。纯数学运算。
    """
    c = np.asarray(cents, dtype=float)
    snapped = np.round(c / 100.0) * 100.0
    return snapped, c - snapped


def snap_cents_grid(cents, grid_cents):
    """自定义网格最近邻吸附（grid_cents 为升序一维 cents 数组）。

    等距时取较低网格点；空网格 = 关闭吸附（恒等返回，偏差 0）。
    非等距网格（如三分损益十二律）下「最近邻 = 最近律位」，
    deviation_cents 为到最近律位的音分差（可正可负）——正负号**不表示**
    高于/低于十二平均律，不得暗示 12tet 参照。
    返回 (snapped_cents, deviation_cents)。
    """
    c = np.asarray(cents, dtype=float)
    grid = np.asarray(grid_cents, dtype=float)
    if grid.size == 0:
        return c.copy(), np.zeros_like(c)
    if grid.size == 1:
        snapped = np.full_like(c, grid[0])
        return snapped, c - snapped
    idx = np.clip(np.searchsorted(grid, c), 1, grid.size - 1)
    left = grid[idx - 1]
    right = grid[idx]
    take_left = np.abs(c - left) <= np.abs(right - c)
    snapped = np.where(take_left, left, right)
    return snapped, c - snapped


def grid_cents_for_tuning(
    tuning: "TuningSystem", *, span_cents: float = 1200.0, include_octave: bool = True
) -> np.ndarray:
    """由 TuningSystem.degrees 生成相对 1/1 的音级吸附网格（音分，升序去重）。

    取 [0, span_cents) 内的 degrees 音分值，升序去重；include_octave 时补入
    span_cents 末值（等八度音律的 2/1 = 1200.0 音分）。span_cents 仅作防御
    过滤（内置模板 degrees 均以 1200.0 收尾，无截断场景）。纯函数：不改
    tuning、不读全局参考频率。B1-02：律制模板相对音级网格。
    """
    degrees = np.asarray(getattr(tuning, "degrees", ()), dtype=float).reshape(-1)
    span = float(span_cents)
    if degrees.size == 0:
        return np.zeros(0, dtype=float)
    grid = np.unique(degrees[(degrees >= 0.0) & (degrees < span)])
    if include_octave and (grid.size == 0 or grid[-1] < span - 1e-9):
        grid = np.append(grid, span)
    return grid


@dataclass
class PitchNote:
    """音符块：时间区间 + 连续 f0 中位数 + 置信度 + 吸附表示层值 + 段型标签。

    state_runs（B1-01a）：段内状态压茬运行清单（形制同 NoteSegment.state_runs），
    仅 hmm 分段透传；默认空 tuple = 向后兼容。
    degree_index / degree_deviation_cents（B1-02a）：段级音级归属（音级序号）
    与到最近律位的音分差，仅在 build_pitch_grid 传入 tuning 时填充；
    None = 未传律制/不归属（禁回退 12TET）。
    head_deviation_cents / tail_deviation_cents（B3-01 a 案）：段内首/末 stable
    运行对段 f0 中位的音分差，仅 hmm 分段从 NoteSegment 透传；simple 分段无
    state_runs ⇒ 两字段恒 None。
    """

    start_s: float
    end_s: float
    f0_hz: float
    conf: float = 0.0
    snapped_f0_hz: float | None = None
    deviation_cents: float = 0.0
    state: str = ""
    state_runs: tuple[tuple[int, int, float, float, str], ...] = ()
    degree_index: int | None = None
    degree_deviation_cents: float | None = None
    head_deviation_cents: float | None = None
    tail_deviation_cents: float | None = None


#: PitchNote 序列化白名单（from_dict 逐字段构造，未知键一律忽略——向后兼容）
_PITCH_NOTE_FIELDS = (
    "start_s",
    "end_s",
    "f0_hz",
    "conf",
    "snapped_f0_hz",
    "deviation_cents",
    "state",
    "state_runs",
    "degree_index",
    "degree_deviation_cents",
    "head_deviation_cents",
    "tail_deviation_cents",
)


def _pitch_note_from_dict(nt: object) -> PitchNote:
    """逐字段白名单构造 PitchNote（B1-01：未知键忽略，旧项目文件零崩溃）。"""
    if not isinstance(nt, dict):
        raise TypeError(f"notes 条目须为 dict，得到 {type(nt).__name__}")
    return PitchNote(**{k: nt[k] for k in _PITCH_NOTE_FIELDS if k in nt})


@dataclass
class PitchGridModel:
    """音高网格模型：音符块列表 + 吸附配置（可序列化入工程文件）。"""

    notes: list[PitchNote] = field(default_factory=list)
    snap_mode: str = SNAP_OFF
    grid_cents: np.ndarray | None = None

    @classmethod
    def from_contour(
        cls,
        times,
        f0_hz,
        conf=None,
        min_dur: float = 0.08,
        gap_max: float = 0.06,
        conf_thresh: float = 0.5,
    ) -> "PitchGridModel":
        """由连续音高轮廓构建音符块。

        分段口径（PLACEHOLDER，待音符分段 HMM 任务替换）：
        voiced = (f0 > 0) 且 (conf >= conf_thresh)；失声间隙或有声样本时间间隔 <= gap_max 合并，超限切分；
        时长 < min_dur 丢弃；f0/conf 取段内中位数。
        """
        t = np.asarray(times, dtype=float)
        f0 = np.asarray(f0_hz, dtype=float)
        cv = np.ones_like(f0) if conf is None else np.asarray(conf, dtype=float)
        voiced = (f0 > 0) & (cv >= conf_thresh)
        n = voiced.size
        notes: list[PitchNote] = []
        i = 0
        while i < n:
            if not voiced[i]:
                i += 1
                continue
            j = i
            while j + 1 < n:
                if voiced[j + 1]:
                    if (t[j + 1] - t[j]) > gap_max:
                        break
                    j += 1
                    continue
                k = j + 1
                while k < n and not voiced[k]:
                    k += 1
                if k < n and (t[k] - t[j]) <= gap_max:
                    j = k
                else:
                    break
            if (t[j] - t[i]) >= min_dur:
                seg = slice(i, j + 1)
                notes.append(
                    PitchNote(
                        start_s=float(t[i]),
                        end_s=float(t[j]),
                        f0_hz=float(np.median(f0[seg])),
                        conf=float(np.median(cv[seg])),
                    )
                )
            i = j + 1
        return cls(notes=notes)

    def apply_snap(self, snap_mode: str | None = None) -> "PitchGridModel":
        """对全部音符块应用吸附，写回 snapped_f0_hz / deviation_cents。

        SNAP_OFF = 恒等；SNAP_12TET = 最近半音；其余模式须先设 grid_cents。
        原始 f0_hz 永不修改。
        """
        mode = self.snap_mode if snap_mode is None else snap_mode
        for note in self.notes:
            if mode == SNAP_OFF:
                note.snapped_f0_hz = note.f0_hz
                note.deviation_cents = 0.0
                continue
            cents = float(hz_to_cents(note.f0_hz))
            if mode == SNAP_12TET:
                snapped, dev = snap_cents_12tet(np.array([cents]))
            elif self.grid_cents is not None:
                snapped, dev = snap_cents_grid(np.array([cents]), self.grid_cents)
            else:
                raise ValueError(f"unknown snap mode or grid not set: {mode!r}")
            note.snapped_f0_hz = float(cents_to_hz(float(snapped[0])))
            note.deviation_cents = float(dev[0])
        return self

    def to_dict(self) -> dict:
        """工程序列化（project.py 集成为后续任务）。"""
        return {
            "snap_mode": self.snap_mode,
            "grid_cents": None
            if self.grid_cents is None
            else [float(x) for x in self.grid_cents],
            "notes": [
                {
                    "start_s": nt.start_s,
                    "end_s": nt.end_s,
                    "f0_hz": nt.f0_hz,
                    "conf": nt.conf,
                    "snapped_f0_hz": nt.snapped_f0_hz,
                    "deviation_cents": nt.deviation_cents,
                    "state": nt.state,
                    "state_runs": [list(run) for run in nt.state_runs],
                    "degree_index": nt.degree_index,
                    "degree_deviation_cents": nt.degree_deviation_cents,
                    "head_deviation_cents": nt.head_deviation_cents,
                    "tail_deviation_cents": nt.tail_deviation_cents,
                }
                for nt in self.notes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PitchGridModel":
        notes = [_pitch_note_from_dict(nt) for nt in data.get("notes", [])]
        grid = data.get("grid_cents")
        return cls(
            notes=notes,
            snap_mode=data.get("snap_mode", SNAP_OFF),
            grid_cents=None if grid is None else np.asarray(grid, dtype=float),
        )


def _segment_degree(f0_hz: float, tuning: object) -> tuple[int | None, float | None]:
    """段级音级归属（B1-02a）：段 f0（Hz）→ (音级序号, 到最近律位的音分差)。

    与 PCP 帧级口径同式（pcp.py：先按 tuning.reference_freq 把 f0 换成音分，
    再取最近音级）：degree 走公共 API ``tuning.freq_to_degree``（默认 ref =
    ``tuning.reference_freq``），与帧级 ``_degree_index_for`` 逐位一致。
    f0_hz 非正或非有限（无声/异常段）⇒ (None, None)（不归属）。
    degree_deviation_cents 为到最近律位的音分差（可正可负）——正负号
    **不表示**高于/低于十二平均律，不得暗示 12tet 参照（口径同
    snap_cents_grid 的 deviation_cents）。
    """
    f0 = float(f0_hz)
    if not np.isfinite(f0) or f0 <= 0.0:
        return None, None
    cents = float(hz_to_cents(f0, ref_freq=tuning.reference_freq))  # type: ignore[attr-defined]
    degree = tuning.freq_to_degree(f0)  # type: ignore[attr-defined]
    deviation = cents - float(tuning.degree_to_cents(degree))  # type: ignore[attr-defined]
    return degree, deviation


def build_pitch_grid(
    times,
    f0_hz,
    conf=None,
    snap_mode: str = SNAP_OFF,
    segmenter: str = "simple",
    tuning: object | None = None,
) -> PitchGridModel:
    """分析管线接线用纯函数（T-802/T-803）：由音高轨迹构建网格模型并按 snap_mode 吸附。

    NaN/非正 f0 帧视为无声；snap_mode 仅接受 SNAP_OFF / SNAP_12TET 白名单，
    其余值一律回落 SNAP_OFF（确定性，不抛异常）。
    segmenter："simple" = from_contour 简易分段（默认，零行为变更）；"hmm" =
    NoteHMM 三态分段（T-803）；未知值回落 "simple"。
    tuning：会话律制（TuningSystem）；传入时在模型构建 + apply_snap() 之后
    对全部 notes 填段级音级归属（hmm/simple 同一后处理路径，B1-02a）；
    默认 None = 零行为变更（两字段全 None）。
    原始连续 f0_hz 永不修改（反量化铁律）；音符段 f0 恒取段内原始中位数。
    """
    if segmenter == "hmm":
        from .note_hmm import NoteHMM
        segs = NoteHMM().segment(times, f0_hz, conf)
        model = PitchGridModel(
            notes=[
                PitchNote(
                    start_s=s.start_s,
                    end_s=s.end_s,
                    f0_hz=s.f0_hz,
                    conf=s.conf,
                    state=s.state,
                    state_runs=s.state_runs,
                    head_deviation_cents=s.head_deviation_cents,
                    tail_deviation_cents=s.tail_deviation_cents,
                )
                for s in segs
            ]
        )
    else:
        model = PitchGridModel.from_contour(times, f0_hz, conf)
    model.snap_mode = snap_mode if snap_mode in (SNAP_OFF, SNAP_12TET) else SNAP_OFF
    model.apply_snap()
    if tuning is not None:
        # B1-02a：段级音级归属后处理（吸附之后同一路径，不碰分段逻辑）
        for note in model.notes:
            degree, deviation = _segment_degree(note.f0_hz, tuning)
            note.degree_index = degree
            note.degree_deviation_cents = deviation
    return model
