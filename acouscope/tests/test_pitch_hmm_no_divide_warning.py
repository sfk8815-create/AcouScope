# SPDX-License-Identifier: GPL-3.0-only
"""T-905：pitch_hmm divide-by-zero RuntimeWarning 根治回归测试。

真机日志 F3（2026-09-07 13:13）：
  RuntimeWarning: divide by zero encountered in log
    obs_log = np.where(obs > 0, np.log(obs), -np.inf).reshape(2, self.n_pitch)
根因：np.where 两分支全部先求值，log(0) 真实执行并发告警（结果被 where 覆盖）。
修复（方案 A）：np.errstate(divide='ignore') 包裹，数值语义逐位不变。
本测试：含零概率观测（空缺候选帧，有声 bin 概率全 0）的 decode，
simplefilter('error', RuntimeWarning) 下必须全程无 RuntimeWarning 抛出。
"""

import warnings

import numpy as np
import pytest

pytest.importorskip("numpy")

from acouscope.analysis.pitch_hmm import PitchHMM  # noqa: E402


class TestPitchHMMNoDivideWarning:
    def test_decode_gap_frames_no_runtime_warning_fixed_lag(self):
        """fixed_lag 路径：空缺帧触发 log(0)，修复后不得发 RuntimeWarning。"""
        h = PitchHMM()
        # 输入须长于 lag（100），否则前段帧回溯窗口不足（fixed-lag 正常行为，见 test_fixed_lag 语义）
        cands = [[(220.0, 0.9)] for _ in range(100)] \
            + [[] for _ in range(10)] \
            + [[(330.0, 0.6)] for _ in range(100)]
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("error", RuntimeWarning)
            r = h.decode(cands, fixed_lag=100)
        divzero = [w for w in rec
                   if issubclass(w.category, RuntimeWarning)
                   and "divide by zero" in str(w.message)]
        assert not divzero, f"仍发出 {len(divzero)} 条 divide-by-zero 警告"
        # 语义抽检：空缺帧仍判清音 NaN（-inf 语义未被破坏）；稳态段全有声
        assert not r.voiced[100:110].any()
        assert np.all(np.isnan(r.f0_hz[100:110]))
        assert r.voiced[7:100].all()

    def test_decode_gap_frames_no_runtime_warning_full(self):
        """full（fixed_lag=None）路径：同样不得发 RuntimeWarning。"""
        h = PitchHMM()
        cands = [[(220.0, 0.9)] for _ in range(20)] \
            + [[] for _ in range(6)] \
            + [[(330.0, 0.6), (660.0, 0.1)] for _ in range(20)]
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("error", RuntimeWarning)
            h.decode(cands, fixed_lag=None)
        divzero = [w for w in rec
                   if issubclass(w.category, RuntimeWarning)
                   and "divide by zero" in str(w.message)]
        assert not divzero, f"仍发出 {len(divzero)} 条 divide-by-zero 警告"

    def test_decode_all_silence_no_runtime_warning(self):
        """全静默输入（首帧即零概率观测，覆盖 :135 首帧分支）不得发警告。"""
        h = PitchHMM()
        cands = [[] for _ in range(40)]
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("error", RuntimeWarning)
            r = h.decode(cands, fixed_lag=100)
        assert not [w for w in rec if issubclass(w.category, RuntimeWarning)]
        assert not r.voiced.any()
        assert np.all(np.isnan(r.f0_hz))
