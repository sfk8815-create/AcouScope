# SPDX-License-Identifier: GPL-3.0-only
"""频谱分析模块。"""

from __future__ import annotations

import numpy as np

from acouscope.dsp import FFTEngine, STFTEngine


def refine_peak_frequency(magnitude: np.ndarray, freqs: np.ndarray, idx: int) -> float:
    """三点抛物线插值细化谱峰频率（T01 共享纯函数，线性幅度口径）。

    把 ``SpectralAnalyzer.detect_pitch_peaks`` 原有的抛物线公式原样抽出，
    供语谱图 ``freq_at`` 复用，消除「整 bin 量化读数」的虚假精度。公式与
    旧实现逐位一致：取 ``a=magnitude[idx-1]``、``b=magnitude[idx]``、
    ``c=magnitude[idx+1]``，``denom=a-2*b+c``，``delta=(a-c)/(2*denom)``，
    ``true_idx=idx+delta``，``peak_freq=true_idx*(freqs[1]-freqs[0])``。

    边界（``idx<=0`` / ``idx>=len(magnitude)-1`` / 频率轴过短）或
    ``abs(denom)<=1e-20``（三点共线、无峰值曲率）时回退到
    ``float(freqs[idx])``，即未插值的 bin 频率。
    """
    n = len(magnitude)
    if idx <= 0 or idx >= n - 1 or idx >= len(freqs) or len(freqs) < 2:
        return float(freqs[idx])
    a = magnitude[idx - 1]
    b = magnitude[idx]
    c = magnitude[idx + 1]
    denom = a - 2 * b + c
    if abs(denom) <= 1e-20:
        return float(freqs[idx])
    delta = (a - c) / (2 * denom)
    true_idx = idx + delta
    return float(true_idx * (freqs[1] - freqs[0]))


class SpectralAnalyzer:
    """频谱分析器。

    提供 FFT 频谱、语谱图等频域分析功能。
    """

    def __init__(self, sample_rate: float = 44100.0):
        self.sample_rate = sample_rate

    # ------------------------------------------------------------------
    # FFT 频谱
    # ------------------------------------------------------------------

    def fft_spectrum(
        self,
        signal: np.ndarray,
        fft_size: int = 4096,
        window: str = "hann",
        db_scale: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算 FFT 幅度谱。

        Args:
            signal: 输入信号
            fft_size: FFT 大小
            window: 窗函数名称
            db_scale: 是否转换为 dB

        Returns:
            (频率轴 Hz, 幅度谱)
        """
        engine = FFTEngine(size=fft_size, window=window)
        freqs_norm, magnitude = engine.magnitude_spectrum(signal, db_scale=db_scale)
        freqs_hz = freqs_norm * self.sample_rate
        return freqs_hz, magnitude

    def power_spectrum(
        self,
        signal: np.ndarray,
        fft_size: int = 4096,
        window: str = "hann",
        db_scale: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算功率谱。

        Args:
            signal: 输入信号
            fft_size: FFT 大小
            window: 窗函数名称
            db_scale: 是否转换为 dB

        Returns:
            (频率轴 Hz, 功率谱)
        """
        engine = FFTEngine(size=fft_size, window=window)
        freqs_norm, power = engine.power_spectrum(signal, db_scale=db_scale)
        freqs_hz = freqs_norm * self.sample_rate
        return freqs_hz, power

    def phase_spectrum(
        self,
        signal: np.ndarray,
        fft_size: int = 4096,
        window: str = "hann",
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算相位谱。

        Args:
            signal: 输入信号
            fft_size: FFT 大小
            window: 窗函数名称

        Returns:
            (频率轴 Hz, 相位谱)
        """
        engine = FFTEngine(size=fft_size, window=window)
        freqs_norm, phase = engine.phase_spectrum(signal)
        freqs_hz = freqs_norm * self.sample_rate
        return freqs_hz, phase

    # ------------------------------------------------------------------
    # 语谱图
    # ------------------------------------------------------------------

    def spectrogram(
        self,
        signal: np.ndarray,
        n_fft: int = 2048,
        hop_length: int = 512,
        window: str = "hann",
        db_scale: bool = True,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算语谱图。

        Args:
            signal: 输入信号
            n_fft: FFT 大小
            hop_length: 帧移
            window: 窗函数
            db_scale: 是否转换为 dB

        Returns:
            (频率轴, 时间轴, 语谱图矩阵)
        """
        engine = STFTEngine(n_fft=n_fft, hop_length=hop_length, window=window)
        freqs, times, mag = engine.magnitude(signal, self.sample_rate, db_scale=db_scale)
        return freqs, times, mag

    # ------------------------------------------------------------------
    # 频谱特征
    # ------------------------------------------------------------------

    def spectral_centroid(self, signal: np.ndarray, n_fft: int = 2048, hop_length: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """计算频谱质心（纯 numpy）。

        Args:
            signal: 输入信号
            n_fft: FFT 大小
            hop_length: 帧移

        Returns:
            (时间轴, 频谱质心 Hz)
        """
        freqs, times, mag = self.spectrogram(signal, n_fft, hop_length, db_scale=False)
        total = np.maximum(np.sum(mag, axis=0), 1e-10)
        centroid = np.sum(freqs[:, np.newaxis] * mag, axis=0) / total
        return times, centroid

    def spectral_bandwidth(self, signal: np.ndarray, n_fft: int = 2048, hop_length: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """计算频谱带宽（纯 numpy）。

        质心两侧的幅度加权标准差。

        Args:
            signal: 输入信号
            n_fft: FFT 大小
            hop_length: 帧移

        Returns:
            (时间轴, 频谱带宽 Hz)
        """
        freqs, times, mag = self.spectrogram(signal, n_fft, hop_length, db_scale=False)
        total = np.maximum(np.sum(mag, axis=0), 1e-10)
        centroid = np.sum(freqs[:, np.newaxis] * mag, axis=0) / total
        spread = np.sum(mag * (freqs[:, np.newaxis] - centroid) ** 2, axis=0) / total
        return times, np.sqrt(spread)

    def spectral_rolloff(self, signal: np.ndarray, n_fft: int = 2048, hop_length: int = 512, roll_percent: float = 0.85) -> tuple[np.ndarray, np.ndarray]:
        """计算频谱滚降点（纯 numpy）。

        累积幅度首次达到总幅度 roll_percent 比例处的频率。

        Args:
            signal: 输入信号
            n_fft: FFT 大小
            hop_length: 帧移
            roll_percent: 滚降百分比

        Returns:
            (时间轴, 滚降频率 Hz)
        """
        freqs, times, mag = self.spectrogram(signal, n_fft, hop_length, db_scale=False)
        cumulative = np.cumsum(mag, axis=0)
        threshold = cumulative[-1] * roll_percent
        idx = np.argmax(cumulative >= threshold[np.newaxis, :], axis=0)
        return times, freqs[idx]

    # ------------------------------------------------------------------
    # 乐音峰值检测（12平均律优化）
    # ------------------------------------------------------------------

    def detect_pitch_peaks(
        self,
        magnitude: np.ndarray,
        freqs: np.ndarray,
        min_freq: float = 32.7,
        max_freq: float = 2000.0,
        max_peaks: int = 12,
        mag_threshold: float = 0.01,
        min_peak_spacing: int = 3,
        tuning_offset: float = 0.0,
    ) -> list[dict]:
        """乐音分音峰值检测。

        直接找所有局部最大值，按幅度排序取前 N 个。
        适用于钢琴、提琴等谐波丰富的乐器，能准确标记各次分音。

        Args:
            magnitude: 幅度谱（线性幅度）
            freqs: 频率轴 Hz
            min_freq: 最低分析频率 Hz
            max_freq: 最高分析频率 Hz
            max_peaks: 最大峰值数量
            mag_threshold: 幅度阈值，相对最大峰值的比例 (0-1)
            min_peak_spacing: 最小峰间距（bin 数），防止分裂峰
            tuning_offset: 调音偏移（音分）

        Returns:
            峰值列表，每个包含: freq, magnitude, note, cents, midi
        """
        if len(magnitude) < 3 or len(freqs) != len(magnitude):
            return []

        # 限制频率范围
        freq_mask = (freqs >= min_freq) & (freqs <= max_freq)
        if not np.any(freq_mask):
            return []

        start_idx = int(np.argmax(freq_mask))
        end_idx = len(freqs) - 1 - int(np.argmax(freq_mask[::-1]))

        mag_segment = magnitude[start_idx : end_idx + 1]
        freq_segment = freqs[start_idx : end_idx + 1]

        if len(mag_segment) < 3:
            return []

        # 频率分辨率
        freq_res = freqs[1] - freqs[0]
        if freq_res <= 0:
            return []

        # 计算阈值（相对于最大峰值）
        spect_max = float(np.max(mag_segment))
        if spect_max <= 0:
            return []
        threshold = spect_max * mag_threshold

        # 找所有局部最大值（比左右邻居都大）
        peaks_raw = []
        for i in range(1, len(mag_segment) - 1):
            if (
                mag_segment[i] > mag_segment[i - 1]
                and mag_segment[i] >= mag_segment[i + 1]
                and mag_segment[i] >= threshold
            ):
                peaks_raw.append((i, float(mag_segment[i])))

        if not peaks_raw:
            return []

        # 最小峰间距抑制（如果两个峰太近，保留幅度大的）
        # 使用半音间距：约 1/4 半音对应的 bin 数，防止分裂峰
        if min_peak_spacing > 0:
            peaks_raw.sort(key=lambda x: x[1], reverse=True)  # 按幅度降序
            kept = []
            for idx, mag in peaks_raw:
                # 计算当前频率下，约 1/4 半音对应的 bin 数
                freq_here = freq_segment[idx]
                quarter_semitone_hz = freq_here * (2 ** (1/48) - 1)  # 1/4 半音 = 25 音分
                quarter_semitone_bins = max(1, int(quarter_semitone_hz / freq_res))
                spacing = max(min_peak_spacing, quarter_semitone_bins)
                too_close = False
                for kept_idx, _ in kept:
                    if abs(idx - kept_idx) < spacing:
                        too_close = True
                        break
                if not too_close:
                    kept.append((idx, mag))
            peaks_raw = kept

        # 按幅度排序，取前 max_peaks 个
        peaks_raw.sort(key=lambda x: x[1], reverse=True)
        peaks_raw = peaks_raw[:max_peaks]

        # 音符名工具
        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        a4_freq = 440.0 * (2 ** (tuning_offset / 1200.0))

        peaks = []
        for local_idx, mag_val in peaks_raw:
            abs_idx = start_idx + local_idx

            # 抛物线插值提高精度：频率改由共享纯函数给出（T01），
            # 幅度仍按抛物顶点值计算（旧实现的 peak_mag 口径逐位不变）。
            if abs_idx > 0 and abs_idx < len(magnitude) - 1:
                a = magnitude[abs_idx - 1]
                b = magnitude[abs_idx]
                c = magnitude[abs_idx + 1]
                denom = a - 2 * b + c
                if abs(denom) > 1e-20:
                    delta = (a - c) / (2 * denom)
                    peak_mag = b - 0.25 * (a - c) * delta
                else:
                    peak_mag = mag_val
            else:
                peak_mag = mag_val
            peak_freq = refine_peak_frequency(magnitude, freqs, abs_idx)

            # 计算最近的音符和音分偏差
            midi_float = 69 + 12 * np.log2(peak_freq / a4_freq)
            midi = int(round(midi_float))
            cents = 100 * (midi_float - midi)

            # 限制在合理范围
            midi = max(0, min(127, midi))
            octave = midi // 12 - 1
            note_idx = midi % 12
            note_name = f"{note_names[note_idx]}{octave}"

            peaks.append({
                "freq": float(peak_freq),
                "magnitude": float(peak_mag),
                "note": note_name,
                "cents": float(cents),
                "midi": midi,
            })

        # 按频率排序
        peaks.sort(key=lambda x: x["freq"])

        return peaks

    # ------------------------------------------------------------------
    # 和弦识别
    # ------------------------------------------------------------------

    def detect_chord(
        self,
        peaks: list[dict],
        magnitude_threshold_ratio: float = 0.3,
        max_notes: int = 6,
    ) -> dict:
        """从峰值列表识别和弦。

        基于检测到的峰值音符，匹配常见和弦类型（大三、小三、属七、小七等）。
        只考虑最强的几个峰值（接近基频级别），避免高次谐波干扰。

        Args:
            peaks: 峰值列表（来自 detect_pitch_peaks）
            magnitude_threshold_ratio: 相对于最强峰的幅度阈值
            max_notes: 最多考虑的音符数

        Returns:
            和弦信息字典: name(和弦名), root(根音), quality(性质), notes(音符列表), confidence(置信度)
        """
        if len(peaks) < 2:
            return {"name": "--", "root": "--", "quality": "--", "notes": [], "confidence": 0.0}

        # 只保留足够强的峰
        max_mag = max(p["magnitude"] for p in peaks)
        threshold = max_mag * magnitude_threshold_ratio
        strong_peaks = [p for p in peaks if p["magnitude"] >= threshold]

        # 按幅度排序，取前 max_notes 个
        strong_peaks.sort(key=lambda x: x["magnitude"], reverse=True)
        strong_peaks = strong_peaks[:max_notes]

        if len(strong_peaks) < 2:
            return {"name": "--", "root": "--", "quality": "--", "notes": [], "confidence": 0.0}

        # 提取所有 MIDI 音高（归一化到同一个八度内做音程分析）
        midi_pcs = sorted(set(p["midi"] % 12 for p in strong_peaks))
        midi_all = sorted(set(p["midi"] for p in strong_peaks))

        if len(midi_pcs) < 2:
            note_name = "--"
            if midi_all:
                names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
                m = midi_all[0]
                note_name = f"{names[m % 12]}{m // 12 - 1}"
            return {"name": note_name, "root": note_name, "quality": "单音", "notes": [note_name], "confidence": 0.3}

        # 和弦模板（音程半音数）
        chord_templates = {
            "maj": [0, 4, 7],           # 大三和弦
            "min": [0, 3, 7],           # 小三和弦
            "dim": [0, 3, 6],           # 减三和弦
            "aug": [0, 4, 8],           # 增三和弦
            "7": [0, 4, 7, 10],         # 属七和弦
            "maj7": [0, 4, 7, 11],      # 大七和弦
            "min7": [0, 3, 7, 10],      # 小七和弦
            "dim7": [0, 3, 6, 9],       # 减七和弦
            "m7b5": [0, 3, 6, 10],      # 半减七和弦
            "sus4": [0, 5, 7],          # 挂四和弦
            "sus2": [0, 2, 7],          # 挂二和弦
            "6": [0, 4, 7, 9],          # 六和弦
            "min6": [0, 3, 7, 9],       # 小六和弦
            "5": [0, 7],                # 五和弦/强力和弦
        }

        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        quality_names = {
            "maj": "", "min": "m", "dim": "dim", "aug": "aug",
            "7": "7", "maj7": "maj7", "min7": "m7",
            "dim7": "dim7", "m7b5": "m7b5",
            "sus4": "sus4", "sus2": "sus2",
            "6": "6", "min6": "m6", "5": "5",
        }

        best_match = None
        best_score = 0.0
        best_root = 0

        # 尝试每个音作为根音
        for root_pc in range(12):
            # 把所有音移到以 root 为 0 的空间
            shifted = sorted([(pc - root_pc) % 12 for pc in midi_pcs])

            for quality, template in chord_templates.items():
                # 计算匹配分数：匹配的音数 / 模板音数
                match_count = sum(1 for t in template if t in shifted)
                extra_count = len(shifted) - match_count

                # 置信度：匹配度 - 额外音惩罚
                template_len = len(template)
                match_ratio = match_count / template_len
                extra_penalty = extra_count * 0.15

                # 三音和五音的匹配权重更高
                core_tones = {0, 4, 7} if "maj" in quality or quality in ("7", "6", "sus4", "sus2", "5") else {0, 3, 7}
                core_match = sum(1 for t in core_tones if t in shifted)
                core_bonus = core_match / len(core_tones) * 0.2

                score = match_ratio - extra_penalty + core_bonus

                if score > best_score:
                    best_score = score
                    best_match = quality
                    best_root = root_pc

        if best_score < 0.4:
            return {
                "name": "--",
                "root": "--",
                "quality": "不确定",
                "notes": midi_all,
                "confidence": best_score,
            }

        root_name = note_names[best_root]
        quality_label = quality_names.get(best_match, best_match)
        chord_name = f"{root_name}{quality_label}"

        # 找到实际的音符名（所有检测到的音符）
        note_list = []
        for midi in sorted(midi_all):
            octave = midi // 12 - 1
            note_idx = midi % 12
            note_list.append(f"{note_names[note_idx]}{octave}")

        return {
            "name": chord_name,
            "root": root_name,
            "quality": best_match,
            "notes": note_list,
            "confidence": float(best_score),
        }
