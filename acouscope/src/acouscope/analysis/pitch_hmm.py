# SPDX-License-Identifier: GPL-3.0-only
"""音高网格 HMM 与 Viterbi 平滑（pYIN 的平滑层）。

PITCH_HMM_CLEANROOM_V1 — clean-room 重写，算法依据 Mauch & Dixon (2014, ICASSP)：
- 状态：音高网格 f_k = MIN_FREQ * 2^(k/60)（k=0..344，即每半音 5 bin / 20 cent），
  每个音高 bin 同时挂有声/清音两个状态，共 2*345=690 态。
- 观测：候选 (f0,p) 装入最近 bin（四舍五入 60*log2(f/MIN_FREQ)）；有声部分总概率
  按 yin_trust 缩放，清音状态均分剩余概率。
- 转移：带内三角权重 w(d) = R+1-|d|（d = 目标bin-源bin ∈ [-R,R]，R=6 即
  ±120 cent/帧），有声→有声与清音→清音乘 self_trans，跨态乘 (1-self_trans)。
- 解码：log 域 max-product Viterbi；支持固定滞后（fixed_lag）在线平滑与全序列。
- 输出映射：有声状态 f0 = 该帧候选中距网格频率最近者（候选已抛物线插值），
  保证输出为连续插值值而非 20 cent 网格原值；清音输出 NaN。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PITCH_HMM_CLEANROOM_V1 = "1"
MIN_FREQ = 61.735  # MIDI 35，网格基频
N_BPS = 5          # bins per semitone（20 cent 分辨率）
N_SEMITONES = 69


@dataclass
class PitchHMMResult:
    """Viterbi 解码结果。

    f0_hz：有声帧为插值候选频率（Hz），清音帧为 NaN；
    voiced：每帧是否有声（来自状态路径）；
    states：原始状态索引（<N = 有声，>=N = 清音，N = n_pitch）。
    """

    f0_hz: np.ndarray
    voiced: np.ndarray
    states: np.ndarray


class PitchHMM:
    """20 cent 音高网格 HMM（690 态，带状转移，log 域 Viterbi）。"""

    def __init__(
        self,
        min_freq: float = MIN_FREQ,
        n_bps: int = N_BPS,
        n_semitones: int = N_SEMITONES,
        self_trans: float = 0.99,
        transition_width: int = 13,
        yin_trust: float = 0.5,
    ):
        self.min_freq = float(min_freq)
        self.n_bps = int(n_bps)
        self.n_pitch = int(n_semitones) * int(n_bps)  # 345
        self.n_state = 2 * self.n_pitch
        self.self_trans = float(self_trans)
        self.width = int(transition_width)
        self.yin_trust = float(yin_trust)
        self.grid_freqs = self.min_freq * 2.0 ** (
            np.arange(self.n_pitch) / (12.0 * self.n_bps)
        )
        # 带内三角权重（w(d)=R+1-|d|），log 域，形状 (width,)
        self._radius = self.width // 2
        offsets = np.arange(-self._radius, self._radius + 1)
        w = (self._radius + 1 - np.abs(offsets)).astype(np.float64)
        w /= w.sum()
        self._log_w = np.log(w)
        self._log_self = np.log(self.self_trans)
        self._log_cross = np.log(1.0 - self.self_trans)

    # ------------------------------------------------------------------
    def observation(self, cands: list[tuple[float, float]]) -> np.ndarray:
        """单帧观测概率 (n_state,)：前 n_pitch 有声、后 n_pitch 清音。"""
        obs = np.zeros(self.n_state, dtype=np.float64)
        s = float(sum(p for _, p in cands))
        if s > 0 and cands:
            prob_really = self.yin_trust * s
            for f0, p in cands:
                k = int(round(60.0 * np.log2(max(f0, 1e-9) / self.min_freq)))
                k = min(max(k, 0), self.n_pitch - 1)
                obs[k] += p * (prob_really / s)
            obs[self.n_pitch :] = (1.0 - prob_really) / self.n_pitch
        else:
            obs[self.n_pitch :] = 1.0 / self.n_pitch
        return obs

    # ------------------------------------------------------------------
    def _viterbi_step(self, delta_log: np.ndarray, obs_log: np.ndarray):
        """单帧 Viterbi 递推（带状切片向量化）。

        delta_log: (2, n_pitch)（行 0 有声、行 1 清音）
        返回 (new_delta_log, bp_d, bp_v)：bp_d/bp_v 为回溯所需
        （源音高偏移 d 与源有声行号，形状 (2, n_pitch)）。
        """
        n = self.n_pitch
        r = self._radius
        neg_inf = -np.inf
        best = np.full((2, n), neg_inf)
        bp_d = np.zeros((2, n), dtype=np.int8)
        bp_v = np.zeros((2, n), dtype=np.int8)
        padded = np.full((2, n + 2 * r), neg_inf)
        padded[:, r : r + n] = delta_log
        # 源音高 = 目标音高 + d
        for k, d in enumerate(range(-r, r + 1)):
            shifted = padded[:, r + d : r + d + n] + self._log_w[k]
            upd = shifted > best
            bp_d[upd] = d
            bp_v[upd] = 0  # 占位：真实源行号在下方 voicing 组合中确定
            best = np.where(upd, shifted, best)
        # voicing 组合：源有声→目标有声 * self；源清音→目标有声 * cross
        cand_v = np.maximum(best[0] + self._log_self, best[1] + self._log_cross)
        bp_v[0, :] = np.where(best[0] + self._log_self >= best[1] + self._log_cross, 0, 1)
        cand_u = np.maximum(best[0] + self._log_cross, best[1] + self._log_self)
        bp_v[1, :] = np.where(best[0] + self._log_cross >= best[1] + self._log_self, 0, 1)
        new = np.stack([cand_v, cand_u]) + obs_log
        return new, bp_d, bp_v

    # ------------------------------------------------------------------
    def decode(self, cand_lists: list, fixed_lag: int | None = 100) -> PitchHMMResult:
        """Viterbi 解码。

        fixed_lag=int：固定滞后在线平滑（滞后 fixed_lag 帧，尾帧收尾补齐）；
        fixed_lag=None：全序列 Viterbi（需存储全部回溯指针，O(帧数) 内存）。
        """
        n_frames = len(cand_lists)
        f0_out = np.full(n_frames, np.nan)
        voiced_out = np.zeros(n_frames, dtype=bool)
        state_out = np.full(n_frames, -1, dtype=int)
        if n_frames == 0:
            return PitchHMMResult(f0_out, voiced_out, state_out)

        obs0 = self.observation(cand_lists[0])
        with np.errstate(divide="ignore"):  # T-905: 静音 log(0) 除零告警，数值语义不变
            obs0_log = np.where(obs0 > 0, np.log(obs0), -np.inf)
        delta = np.stack([
            obs0_log[: self.n_pitch].copy(),
            obs0_log[self.n_pitch :].copy(),
        ])
        if fixed_lag is None:
            all_bp_d = np.zeros((n_frames, 2, self.n_pitch), dtype=np.int8)
            all_bp_v = np.zeros((n_frames, 2, self.n_pitch), dtype=np.int8)
            ring = None
        else:
            ring = []  # (bp_d, bp_v) 环形缓冲，容量 fixed_lag

        lag = fixed_lag if fixed_lag is not None else 0

        def backtrack(t_target: int, start_state: tuple[int, int], bp_window) -> int:
            """从 (t_target 之后) 的 start_state 回溯到 t_target 帧的状态。"""
            v, p = start_state
            # bp_window[i] 对应帧 (t_emit_end - len + i)
            for i in range(len(bp_window) - 1, -1, -1):
                if (t_target - (i + 1)) < 0:
                    continue
                d = int(bp_window[i][0][v, p])
                src_v = int(bp_window[i][1][v, p])
                p = p + d
                v = src_v
            return v * self.n_pitch + p

        def emit(t: int, end_state: tuple[int, int], bp_window) -> None:
            st = backtrack(t, end_state, bp_window)
            state_out[t] = st
            if st < self.n_pitch:
                voiced_out[t] = True
                grid = self.grid_freqs[st]
                cands = cand_lists[t]
                if cands:
                    best_f = min(cands, key=lambda c: abs(c[0] - grid))[0]
                    f0_out[t] = best_f

        for t in range(1, n_frames):
            obs = self.observation(cand_lists[t])
            with np.errstate(divide="ignore"):  # T-905: 同上，log(0) 分支被 where 覆盖
                obs_log = np.where(obs > 0, np.log(obs), -np.inf).reshape(2, self.n_pitch)
            delta, bp_d, bp_v = self._viterbi_step(delta, obs_log)
            if ring is not None:
                ring.append((bp_d, bp_v))
                if len(ring) > lag:
                    ring.pop(0)
                if t >= lag:
                    v_row = int(np.argmax(delta.max(axis=1)))
                    p_idx = int(np.argmax(delta[v_row]))
                    emit(t - lag, (v_row, p_idx), ring)
            else:
                all_bp_d[t] = bp_d
                all_bp_v[t] = bp_v

        # 收尾：剩余帧（fixed_lag）或全路径（full）
        if ring is not None:
            v_row = int(np.argmax(delta.max(axis=1)))
            p_idx = int(np.argmax(delta[v_row]))
            for t in range(max(0, n_frames - lag), n_frames):
                # 回溯窗口 = 进入帧 (t+1 .. n-1) 的指针，即 ring[t:]
                # （ring[i] 为进入帧 i+1 的转移；起点状态属于帧 n-1）
                emit(t, (v_row, p_idx), ring[t:])
        else:
            # 全序列回溯
            path = np.zeros(n_frames, dtype=int)
            v_row = int(np.argmax(delta.max(axis=1)))
            p_idx = int(np.argmax(delta[v_row]))
            cur = v_row * self.n_pitch + p_idx
            for t in range(n_frames - 1, -1, -1):
                path[t] = cur
                if t > 0:
                    v, p = divmod(cur, self.n_pitch)
                    d = int(all_bp_d[t][v, p])
                    sv = int(all_bp_v[t][v, p])
                    cur = sv * self.n_pitch + (p + d)
            for t in range(n_frames):
                st = path[t]
                state_out[t] = st
                if st < self.n_pitch:
                    voiced_out[t] = True
                    grid = self.grid_freqs[st]
                    cands = cand_lists[t]
                    if cands:
                        f0_out[t] = min(cands, key=lambda c: abs(c[0] - grid))[0]
        return PitchHMMResult(f0_out, voiced_out, state_out)
