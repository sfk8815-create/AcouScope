# SPDX-License-Identifier: GPL-3.0-only
"""MonoNote 三态音符分段 HMM（T-803，PITCH_analysis §1.5 净室口径）。

净室重写声明：本模块按 PITCH_analysis.md §1.5 公布的学术参数规格独立实现，
未逐行翻译任何第三方源码；参数取值以 NOTE_HMM_PARAMS 为准（§1.5 口径）。

反量化铁律：HMM 的半音/bin 网格仅作状态索引；音符段 f0_hz 一律取段内
原始 f0 中位数，midi 字段仅为参考，任何 bin/网格值禁止直接充当输出。

模型（每音高 3 状态 + 全局 silent）：
- 音高 bin = (midi - min_pitch) * bins_per_semitone + {0: attack, 1: stable,
  2: inter}；音高范围由输入有声音符裁剪至 [35, 35+n_semi)，n_semi 上限 64
  （PLACEHOLDER：上限取值待实测标定，超界音高帧按边界裁剪，不扩展状态空间）；
  silent 为单一全局态。
- 观测：voiced 帧按 f0→midi→bin 位置高斯打分（sigma = 0.8 半音），稳定态
  权重最高、起音/音间次之；有声总概率 = yin_trust * conf * prior_pitched_prob
  （截断至 [0,1]），其余归 silent；unvoiced/NaN/非正 f0 帧为 silent。
- 转移（log 域 numpy 构造）：帧内同音高 bin 邻域走高斯核（sigma 0.8 半音，
  稳定态自环 p_stable_selftrans = 0.99）；跨音高仅半音距 ∈ [min_semitone_distance,
  max_jump_semitones]（= [0.5, 13] 半音/帧上限）的 bin 可达，且 |Δbin| <=
  3 * max_jump_semitones；静音自环 p_silent_selftrans = 0.9999，静音⇄音高
  走 (1 - 0.9999) 质量加权。
- 解码：log 域 max-product Viterbi（全序列，转移/观测矩阵均向量化构造）+
  回溯取段：稳定/起音连续运行构段，音间/静音收束；时长 < min_dur_s 丢弃；
  f0_hz = 段内原始 f0 中位数、conf = 段内原始 conf 中位数、midi 由中位数
  f0 取整（仅参考）。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from ..dsp.units import hz_to_midi

__all__ = [
    "NOTE_HMM_PARAMS",
    "NoteHMM",
    "NoteSegment",
]

NOTE_HMM_PARAMS: dict = {
    # PITCH_analysis §1.5（净室口径，键值逐字）
    "p_stable_selftrans": 0.99,
    "p_silent_selftrans": 0.9999,
    "max_jump_semitones": 13,
    "min_semitone_distance": 0.5,
    "sigma_yin_pitch_stable": 0.8,
    "yin_trust": 0.1,
    "prior_pitched_prob": 0.7,
    "min_pitch_midi": 35,
    "bins_per_semitone": 3,
}

_N_SEMI_CAP = 64  # PLACEHOLDER：音高范围半音上限（§1.5 未定死，实测待标定）

# 帧内 3 状态观测偏好（0=attack, 1=stable, 2=inter，未归一）
_STATE_PREF = np.array([0.6, 1.0, 0.4], dtype=np.float64)


@dataclass
class NoteSegment:
    """音符段：时间区间 + 段内原始 f0 中位数 + 参考 MIDI + 置信度。"""

    start_s: float
    end_s: float
    f0_hz: float
    midi: int
    conf: float


class NoteHMM:
    """MonoNote 三态（attack/stable/inter）+ 全局 silent 的音符分段 HMM。"""

    def __init__(self, params: dict | None = None):
        self.p = copy.deepcopy(NOTE_HMM_PARAMS) if params is None else dict(params)

    # ------------------------------------------------------------------
    def _frame_inits(self, times, f0_hz, conf):
        """帧预处理：voiced 标记、音高范围裁剪、逐帧半音位置与观测质量。"""
        t = np.asarray(times, dtype=float)
        f0 = np.asarray(f0_hz, dtype=float)
        cv = np.ones_like(f0) if conf is None else np.asarray(conf, dtype=float)
        voiced = np.isfinite(f0) & (f0 > 0)
        n = f0.size
        min_midi = int(self.p["min_pitch_midi"])

        x = np.full(n, np.nan)
        lo, hi = min_midi, min_midi
        if voiced.any():
            midi_all = hz_to_midi(np.where(voiced, f0, 440.0))
            lo = max(min_midi, int(np.floor(midi_all[voiced].min())))
            hi = min(
                min_midi + _N_SEMI_CAP,
                int(np.ceil(midi_all[voiced].max())) + 1,
            )
            hi = max(hi, lo + 1)
            # 超界音高帧按边界裁剪（状态空间不扩展）
            x = np.clip(hz_to_midi(f0), float(lo), float(hi)) - float(lo)
        return t, f0, cv, voiced, lo, hi, x

    # ------------------------------------------------------------------
    def _obs_components(self):
        """观测常量（向量化）：帧内 3 状态 log 权重与有声基础概率。

        逐帧 log 概率 = log(p_voiced * conf_t) + log_g_bin + log_state_weight[s]
        （log_g_bin 在 _frame_log_obs 内按 d = |midi - bin中心| 向量化计算）；
        p_voiced = yin_trust * prior_pitched_prob（逐帧再乘 conf 截断）。
        """
        pref = _STATE_PREF / _STATE_PREF.sum()
        log_state_weight = np.log(pref)
        p_voiced = float(self.p["yin_trust"]) * float(self.p["prior_pitched_prob"])
        return log_state_weight, p_voiced

    # ------------------------------------------------------------------
    def _build_transition(self, n_semi):
        """log 域转移矩阵 (n_state, n_state)，numpy 向量化构造。"""
        bps = int(self.p["bins_per_semitone"])
        max_jump = int(self.p["max_jump_semitones"])
        min_dist = float(self.p["min_semitone_distance"])
        p_st = float(self.p["p_stable_selftrans"])
        p_si = float(self.p["p_silent_selftrans"])
        sigma = float(self.p["sigma_yin_pitch_stable"])
        n_state = n_semi * bps + 1
        sil = n_semi * bps

        states = np.arange(n_semi * bps)
        src_bin = states // bps
        src_st = states % bps

        # 帧内：目标 (bj, s2) 与源 (bi, s) 同 bin（bj == bi）的高斯核
        intra_states = np.arange(n_semi * bps)
        dst_bin = intra_states // bps
        dst_st = intra_states % bps
        same = (src_bin[:, None] == dst_bin[None, :])
        # 跨音高：半音距 ∈ [min_dist, max_jump]
        dist_semi = np.abs(src_bin[:, None] - dst_bin[None, :]).astype(float) / float(bps)
        jump_mask = (
            (src_bin[:, None] != dst_bin[None, :])
            & (dist_semi >= min_dist)
            & (dist_semi <= float(max_jump))
            & (np.abs(src_bin[:, None] - dst_bin[None, :]) <= max_jump * bps)
        )

        def gauss(d_semi):
            return np.exp(-(d_semi * d_semi) / (2.0 * sigma * sigma))

        intra_w = gauss((dst_st[None, :].astype(float) - src_st[:, None]) / float(bps))
        jump_w = (1.0 - dist_semi / (float(max_jump) + 1.0))
        jump_log_pref = np.log(np.clip(1.0 - p_st, 1e-300, None))
        intra_log_pref = np.log(np.clip(1.0 - p_st, 1e-300, None))

        m = np.zeros((n_semi * bps, n_semi * bps))
        m[same] = intra_log_pref + np.log(np.clip(intra_w[same], 1e-300, None))
        # 稳定态自环取 p_stable_selftrans（T-803c：缺此自环时长序列全量判 silent）
        for bi in range(n_semi):
            stable = bi * bps + 1
            m[stable, stable] = np.log(float(p_st))
        m[jump_mask] = jump_log_pref + np.log(np.clip(jump_w[jump_mask], 1e-300, None))

        trans = np.full((n_state, n_state), -np.inf)
        trans[:sil, :sil] = m
        trans[sil, sil] = np.log(p_si)
        # 静音→音高：起音/音间 bin 起步（每 bin 各 (1-p_si)/2 / 3 归一）
        onset = np.log((1.0 - p_si) / 2.0)
        for s in (0, 2):
            trans[sil, s::bps] = onset
        # 音高→静音：按帧内偏好加权
        end = np.log((1.0 - p_si) / 2.0)
        for s in range(bps):
            trans[s::bps, sil] = end + np.log(_STATE_PREF[s] / _STATE_PREF.sum())
        return trans

    # ------------------------------------------------------------------
    def _frame_log_obs(self, tt, voiced, x, cv, p_voiced, log_state_weight):
        """单帧 log 观测 (n_state,)（向量化）。

        有声总概率 p = min(yin_trust * conf_t * prior_pitched_prob, 1)；
        p 内部分配 = bin 高斯（d = |midi - bin中心|，σ 半音）× 帧内 3 态偏好；
        1 - p 归 silent。
        """
        n_semi = (self._n_state - 1) // int(self.p["bins_per_semitone"])
        bps = int(self.p["bins_per_semitone"])
        neg = -np.inf
        obs = np.full(self._n_state, neg)
        if not voiced[tt]:
            obs[-1] = 0.0  # log(1)
            return obs
        sigma = float(self.p["sigma_yin_pitch_stable"])
        bin_pos = np.arange(n_semi, dtype=float)
        d = np.abs(bin_pos - float(x[tt]))
        g = np.where(d <= 3.0, -0.5 * (d / sigma) ** 2, -np.inf)
        if np.all(np.isneginf(g)):
            # 截断外（范围已裁剪，数值上不会发生）：全量给 silent
            obs[-1] = 0.0
            return obs
        g -= np.max(g)  # log-sum-exp 稳定化
        lg = g - np.log(np.exp(g).sum())
        p = min(float(p_voiced * np.clip(cv[tt], 0.0, 1.0)), 1.0)
        log_prob = np.log(p) + lg[:, None] + log_state_weight[None, :]
        idx = np.arange(n_semi)[:, None] * bps + np.arange(bps)[None, :]
        obs[idx.ravel()] = log_prob.ravel()
        obs[-1] = np.log(max(1.0 - p, 1e-300))
        return obs

    # ------------------------------------------------------------------
    def segment(self, times, f0_hz, conf=None, min_dur_s: float = 0.08) -> list[NoteSegment]:
        """由连续音高轨迹 (times, f0_hz, conf) 解码音符段列表。

        段 f0_hz = 段内原始 f0 中位数（反量化铁律）；midi 仅参考；
        时长 < min_dur_s 的段丢弃。conf=None 视为全 1。
        """
        t, f0, cv, voiced, lo, hi, x = self._frame_inits(times, f0_hz, conf)
        n = f0.size
        segs: list[NoteSegment] = []
        if n == 0:
            return segs

        bps = int(self.p["bins_per_semitone"])
        n_semi = hi - lo
        if n_semi <= 0:  # 全无声：无音高状态
            return segs

        self._n_state = n_semi * bps + 1
        log_state_weight, p_voiced = self._obs_components()
        trans = self._build_transition(n_semi)

        # 逐帧 log 观测（逐帧循环为 Viterbi 热点之一；矩阵本身已向量化构造）
        log_obs = np.empty((n, self._n_state))
        for tt in range(n):
            log_obs[tt] = self._frame_log_obs(
                tt, voiced, x, cv, p_voiced, log_state_weight
            )

        # Viterbi（log 域）
        delta = log_obs[0].copy()
        bp = np.empty((n, self._n_state), dtype=np.int32)
        for tt in range(1, n):
            scores = delta[:, None] + trans  # (n_state, n_state)
            bp[tt] = np.argmax(scores, axis=0)
            delta = scores.max(axis=0) + log_obs[tt]
        path = np.empty(n, dtype=np.int32)
        cur = int(np.argmax(delta))
        for tt in range(n - 1, -1, -1):
            path[tt] = cur
            if tt > 0:
                cur = int(bp[tt, cur])

        # 取段：稳定/起音连续运行构段，音间/静音/音高 bin 变化收束（T-803b：
        # 相邻异音高无缝切换时 bin 变化即切段，防止混合中位数并段）
        i = 0
        while i < n:
            st = path[i]
            if st == self._n_state - 1 or st % bps == 2:
                i += 1
                continue
            j = i
            while (
                j + 1 < n
                and path[j + 1] != self._n_state - 1
                and path[j + 1] % bps != 2
                and path[j + 1] // bps == path[j] // bps
            ):
                j += 1
            f0v = f0[i : j + 1]
            f0v = f0v[np.isfinite(f0v) & (f0v > 0)]
            if f0v.size and (float(t[j]) - float(t[i])) >= min_dur_s:
                f0_med = float(np.median(f0v))
                segs.append(
                    NoteSegment(
                        start_s=float(t[i]),
                        end_s=float(t[j]),
                        f0_hz=f0_med,
                        midi=int(round(hz_to_midi(f0_med))),
                        conf=float(np.median(cv[i : j + 1])),
                    )
                )
            i = j + 1
        return segs
