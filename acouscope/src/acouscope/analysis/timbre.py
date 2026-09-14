# SPDX-License-Identifier: GPL-3.0-only
"""音色特征分析模块。"""

from __future__ import annotations

import numpy as np

from acouscope.utils.log import get_logger

_log = get_logger(__name__)


class TimbreAnalyzer:
    """音色特征分析器。

    提取 MFCC、频谱特征等音色描述符。
    """

    def __init__(self, sample_rate: float = 44100.0):
        self.sample_rate = sample_rate

    def mfcc(
        self,
        signal: np.ndarray,
        n_mfcc: int = 20,
        n_fft: int = 2048,
        hop_length: int = 512,
        n_mels: int = 128,
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算 MFCC 系数（纯 numpy）。

        Args:
            signal: 输入信号
            n_mfcc: MFCC 阶数
            n_fft: FFT 大小
            hop_length: 帧移
            n_mels: Mel 滤波器数量

        Returns:
            (时间轴, MFCC 矩阵 [n_frames, n_mfcc])
        """
        from acouscope.dsp.stft import STFTEngine

        # 1. 计算语谱图
        stft = STFTEngine(n_fft=n_fft, hop_length=hop_length, window="hann")
        freqs, times, mag = stft.magnitude(signal, self.sample_rate, db_scale=False)

        # 2. 构建 Mel 滤波器组
        mel_filters = self._mel_filterbank(n_mels, n_fft, self.sample_rate)

        # 3. 应用滤波器组
        mel_spec = np.dot(mel_filters, mag)  # [n_mels, n_frames]

        # 4. 取对数
        log_mel = np.log(np.maximum(mel_spec, 1e-10))

        # 5. DCT-II 变换得到 MFCC
        mfcc = self._dct2(log_mel, n_mfcc).T  # [n_frames, n_mfcc]

        return times, mfcc

    @staticmethod
    def _hz_to_mel(hz):
        """Hz 转 Mel（委托 dsp.units 公共函数）。"""
        from acouscope.dsp.units import hz_to_mel
        return hz_to_mel(hz)

    @staticmethod
    def _mel_to_hz(mel):
        """Mel 转 Hz（委托 dsp.units 公共函数）。"""
        from acouscope.dsp.units import mel_to_hz
        return mel_to_hz(mel)

    def _mel_filterbank(self, n_mels: int, n_fft: int, sr: float) -> np.ndarray:
        """构建 Mel 滤波器组。

        Returns:
            滤波器矩阵 [n_mels, n_freq]
        """
        n_freq = n_fft // 2 + 1
        freqs_hz = np.fft.rfftfreq(n_fft, d=1.0 / sr)

        # Mel 刻度上均匀分布的中心频率
        mel_min = self._hz_to_mel(0)
        mel_max = self._hz_to_mel(sr / 2)
        mel_centers = np.linspace(mel_min, mel_max, n_mels + 2)
        hz_centers = self._mel_to_hz(mel_centers)

        # 构建三角滤波器
        filters = np.zeros((n_mels, n_freq))
        for i in range(n_mels):
            left = hz_centers[i]
            center = hz_centers[i + 1]
            right = hz_centers[i + 2]

            # 左上升沿
            left_idx = freqs_hz >= left
            rise_idx = freqs_hz <= center
            left_slope = (freqs_hz - left) / (center - left + 1e-10)

            # 右下降沿
            right_idx = freqs_hz >= center
            fall_idx = freqs_hz <= right
            right_slope = (right - freqs_hz) / (right - center + 1e-10)

            filters[i, left_idx & rise_idx] = left_slope[left_idx & rise_idx]
            filters[i, right_idx & fall_idx] = right_slope[right_idx & fall_idx]

        return filters

    @staticmethod
    def _dct2(x: np.ndarray, n_out: int) -> np.ndarray:
        """DCT-II 变换（向量化实现）。

        Args:
            x: 输入 [n_in, n_frames]
            n_out: 输出维度

        Returns:
            DCT 结果 [n_out, n_frames]
        """
        n_in = x.shape[0]
        n = np.arange(n_in)
        k = np.arange(n_out)[:, None]
        dct_mat = np.cos(np.pi * k * (2 * n + 1) / (2 * n_in)) * np.sqrt(2.0 / n_in)
        dct_mat[0] *= 1.0 / np.sqrt(2)
        return dct_mat @ x

    def spectral_features(
        self,
        signal: np.ndarray,
        n_fft: int = 2048,
        hop_length: int = 512,
    ) -> dict:
        """计算一组频谱特征（对齐 TimbreToolbox 描述符集）。

        Args:
            signal: 输入信号
            n_fft: FFT 大小
            hop_length: 帧移

        Returns:
            包含各特征的字典（每帧一个值的时间序列）
        """
        from acouscope.analysis import SpectralAnalyzer

        sa = SpectralAnalyzer(self.sample_rate)
        features = {}

        # 一次 STFT，共享给所有特征
        freqs, times, mag = sa.spectrogram(signal, n_fft, hop_length, db_scale=False)
        features["times"] = times

        total = np.maximum(np.sum(mag, axis=0), 1e-10)
        centroid = np.sum(freqs[:, np.newaxis] * mag, axis=0) / total
        features["spectral_centroid"] = centroid

        spread = np.sqrt(np.sum(mag * (freqs[:, np.newaxis] - centroid) ** 2, axis=0) / total)
        features["spectral_bandwidth"] = spread

        cumulative = np.cumsum(mag, axis=0)
        rolloff_idx = np.argmax(cumulative >= total * 0.85, axis=0)
        features["spectral_rolloff"] = freqs[rolloff_idx]

        # 平坦度（几何均值 / 算术均值）
        log_mag = np.log(np.maximum(mag, 1e-10))
        flatness = np.exp(np.mean(log_mag, axis=0)) / np.maximum(np.mean(mag, axis=0), 1e-10)
        features["spectral_flatness"] = flatness

        # 频谱通量
        diff = np.diff(mag, axis=1, prepend=mag[:, :1])
        features["spectral_flux"] = np.sqrt(np.sum(np.maximum(diff, 0.0) ** 2, axis=0))

        # --- TimbreToolbox 补充特征 ---
        # 频谱峰值因子（spectral crest）：max / mean
        features["spectral_crest"] = np.max(mag, axis=0) / np.maximum(np.mean(mag, axis=0), 1e-10)

        # 频谱斜率（spectral slope）：对幅度谱做线性回归，回归斜率
        n_freq = mag.shape[0]
        x_freq = np.arange(n_freq)
        x_mean = x_freq - x_freq.mean()
        x_var = np.maximum(np.sum(x_mean ** 2), 1e-10)
        y_mean = mag.mean(axis=0, keepdims=True)
        slope = np.sum(x_mean[:, np.newaxis] * (mag - y_mean), axis=0) / x_var
        features["spectral_slope"] = slope

        # 频谱下降量（spectral decrease）：低频到高频的平均幅度衰减
        # = (1/(K-1)) * sum((mag[k] - mag[0]) / k), k=1..K-1
        mag_norm = mag / np.maximum(mag[0:1, :], 1e-10)
        k_idx = np.arange(1, n_freq)
        features["spectral_decrease"] = np.sum(mag_norm[1:, :] / k_idx[:, np.newaxis], axis=0) / (n_freq - 1)

        # 频谱变化量（spectral variation）：相邻帧谱的余弦距离
        mag_normed = mag / np.maximum(np.linalg.norm(mag, axis=0, keepdims=True), 1e-10)
        prev = mag_normed[:, :-1]
        curr = mag_normed[:, 1:]
        cos_sim = np.sum(prev * curr, axis=0)
        features["spectral_variation"] = 1.0 - np.pad(cos_sim, (1, 0), mode="constant", constant_values=0)

        return features

    def hnr(
        self,
        signal: np.ndarray,
        frame_size: int = 2048,
        hop_length: int = 512,
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算谐波噪声比（Harmonics-to-Noise Ratio，纯 numpy 向量化）。

        基于自相关法：HNR ≈ 10·log10(r_peak / (r_0 - r_peak))，
        其中 r_peak 为基音周期处的自相关峰值。
        自相关经 FFT 批量计算，长信号亦可在毫秒级完成。

        Args:
            signal: 输入信号
            frame_size: 帧长
            hop_length: 帧移

        Returns:
            (时间轴, HNR dB 值)
        """
        n_frames = 1 + (len(signal) - frame_size) // hop_length
        if n_frames <= 0:
            return np.array([]), np.array([])
        times = np.arange(n_frames) * hop_length / self.sample_rate

        # 帧矩阵 [n_frames, frame_size]
        idx = np.arange(frame_size)[None, :] + hop_length * np.arange(n_frames)[:, None]
        frames = signal[idx]

        # FFT 批量自相关（零填充 2 倍防循环混叠）
        n_fft = 2 * frame_size
        spec = np.fft.rfft(frames, n=n_fft, axis=1)
        autocorr = np.fft.irfft(spec * np.conj(spec), n=n_fft, axis=1)[:, :frame_size]

        r0 = autocorr[:, 0]

        # 基音周期搜索范围：50~2000 Hz
        min_lag = max(1, int(self.sample_rate / 2000))
        max_lag = min(int(self.sample_rate / 50), frame_size - 1)
        if max_lag <= min_lag:
            return times, np.zeros(n_frames)

        window = autocorr[:, min_lag : max_lag + 1]
        peak_val = np.max(window, axis=1)

        hnr = np.zeros(n_frames)
        voiced = r0 > 1e-10
        hnr[voiced] = 10 * np.log10(
            np.maximum(peak_val[voiced], 1e-10)
            / np.maximum(r0[voiced] - peak_val[voiced], 1e-10)
        )

        return times, hnr

    def _envelope_stats(
        self,
        signal: np.ndarray,
        frame_size: int = 2048,
        hop_length: int = 512,
    ) -> dict:
        """从 RMS 包络估计时间包络描述符（对齐 TimbreToolbox TEErep）。

        起振时间：包络从峰值 10% 升至 90% 的时间；
        衰减时间：包络从峰值降至峰值 10%（−20 dB）的时间；
        起振斜率：起振阶段包络的线性回归斜率；
        衰减斜率：衰减阶段包络的线性回归斜率；
        时间质心：能量分布的时间重心；
        有效持续时间：能量在峰值 40% 以上的持续时长。

        Returns:
            包含各时间包络特征的字典（无法估计的项不含）
        """
        result: dict = {}
        n = len(signal)
        if n < frame_size:
            return result
        n_frames = 1 + (n - frame_size) // hop_length
        if n_frames < 3:
            return result

        idx = np.arange(frame_size)[None, :] + hop_length * np.arange(n_frames)[:, None]
        frames = signal[idx]
        env = np.sqrt(np.mean(frames**2, axis=1))

        peak_i = int(np.argmax(env))
        peak_v = float(env[peak_i])
        if peak_v <= 0:
            return result

        # 起振：峰值前最后一次低于 10% → 其后首次达到 90%
        below = np.where(env[: peak_i + 1] < 0.1 * peak_v)[0]
        t10 = int(below[-1]) if len(below) else 0
        above = np.where(env[t10 : peak_i + 1] >= 0.9 * peak_v)[0]
        t90 = t10 + int(above[0]) if len(above) else peak_i
        attack = (t90 - t10) * hop_length / self.sample_rate
        result["attack_time"] = float(attack)

        # 起振斜率：t10 到 t90 段的线性回归斜率（env 值 / 帧序号）
        if t90 > t10:
            seg = env[t10 : t90 + 1]
            x = np.arange(len(seg))
            x_mean = x - x.mean()
            x_var = max(float(np.sum(x_mean ** 2)), 1e-10)
            result["attack_slope"] = float(np.sum(x_mean * (seg - seg.mean())) / x_var)

        # 衰减：峰值后首次跌破 10%
        after = np.where(env[peak_i:] < 0.1 * peak_v)[0]
        if len(after):
            decay_end = peak_i + int(after[0])
            result["decay_time"] = float(after[0]) * hop_length / self.sample_rate

            # 衰减斜率
            seg = env[peak_i : decay_end + 1]
            if len(seg) > 1:
                x = np.arange(len(seg))
                x_mean = x - x.mean()
                x_var = max(float(np.sum(x_mean ** 2)), 1e-10)
                result["decrease_slope"] = float(
                    np.sum(x_mean * (seg - seg.mean())) / x_var
                )

        # 时间质心：能量加权的时间重心
        total_e = np.sum(env ** 2)
        if total_e > 0:
            t_axis = np.arange(n_frames) * hop_length / self.sample_rate
            result["temporal_centroid"] = float(np.sum(t_axis * env ** 2) / total_e)

        # 有效持续时间：能量在峰值 40% 以上的帧跨度
        effective_frames = np.sum(env >= 0.4 * peak_v)
        result["effective_duration"] = float(
            effective_frames * hop_length / self.sample_rate
        )

        return result

    def harmonic_features(self, signal: np.ndarray, n_harmonics: int = 20) -> dict:
        """计算谐波描述符（对齐 TimbreToolbox HARMrep）。

        基于 YIN 基频检测结果，在频谱中提取谐波峰值，
        计算三刺激值、非谐性、奇偶比、谐波能量。

        Args:
            signal: 输入信号
            n_harmonics: 提取的谐波数

        Returns:
            谐波特征字典
        """
        result: dict = {}
        if len(signal) < 2048:
            return result

        # 基频检测
        try:
            from acouscope.analysis.pitch import PitchAnalyzer

            pa = PitchAnalyzer(self.sample_rate)
            _, f0 = pa.detect_yin(signal, frame_size=2048, hop_length=512)
            f0_median = float(np.median(f0[f0 > 0])) if np.any(f0 > 0) else 0.0
        except Exception as e:
            _log.warning("基频检测失败，跳过谐波特征: %s", e)
            return result

        if f0_median <= 0 or f0_median > self.sample_rate / 4:
            return result

        result["f0"] = f0_median

        # 中段 FFT 提取谐波峰值
        from acouscope.dsp import FFTEngine

        engine = FFTEngine(size=4096)
        mid = len(signal) // 2
        frame = signal[max(0, mid - 2048):mid + 2048]
        if len(frame) < 4096:
            frame = np.pad(frame, (0, 4096 - len(frame)))

        freqs, mag = engine.magnitude_spectrum(frame, db_scale=False)
        freqs_hz = freqs * self.sample_rate

        # 在每个谐波频率附近搜索局部峰值
        harmonic_amps = []
        for h in range(1, n_harmonics + 1):
            target_freq = f0_median * h
            if target_freq > self.sample_rate / 2:
                break
            # 搜索范围：±50 Hz 或 ±5%（取较大者）
            search_bw = max(50.0, target_freq * 0.05)
            mask = (freqs_hz >= target_freq - search_bw) & (freqs_hz <= target_freq + search_bw)
            if np.any(mask):
                peak_amp = float(np.max(mag[mask]))
            else:
                peak_amp = 0.0
            harmonic_amps.append(peak_amp)

        if not harmonic_amps or sum(harmonic_amps) < 1e-10:
            return result

        total_harmonic_energy = sum(harmonic_amps)
        result["harmonic_energy"] = total_harmonic_energy

        # 三刺激值（tristimulus）
        result["tristimulus_1"] = harmonic_amps[0] / total_harmonic_energy
        if len(harmonic_amps) >= 3:
            result["tristimulus_2"] = (
                (harmonic_amps[1] + harmonic_amps[2]) / total_harmonic_energy
            )
        if len(harmonic_amps) >= 6:
            result["tristimulus_3"] = (
                sum(harmonic_amps[3:6]) / total_harmonic_energy
            )

        # 奇偶比
        odd_energy = sum(harmonic_amps[0::2])
        even_energy = sum(harmonic_amps[1::2])
        if even_energy > 1e-10:
            result["harmonic_odd_even_ratio"] = odd_energy / even_energy

        # 非谐性（inharmonicity）：各谐波频率偏差的加权均值
        deviations = []
        for h, amp in enumerate(harmonic_amps, start=1):
            target_freq = f0_median * h
            if target_freq > self.sample_rate / 2:
                break
            search_bw = max(50.0, target_freq * 0.05)
            mask = (freqs_hz >= target_freq - search_bw) & (freqs_hz <= target_freq + search_bw)
            if np.any(mask):
                peak_freq = float(freqs_hz[np.argmax(mag[mask])])
                if target_freq > 0:
                    deviations.append(abs(peak_freq - target_freq) / target_freq * amp)

        if deviations and total_harmonic_energy > 0:
            result["inharmonicity"] = sum(deviations) / total_harmonic_energy

        return result

    def global_features(self, signal: np.ndarray) -> dict:
        """计算全局音色特征统计量（对齐 TimbreToolbox 描述符集）。

        覆盖时域电平类（峰值/RMS/波峰因数/DC/ZCR）、
        时间包络类（起振时间/衰减时间/起振斜率/衰减斜率/时间质心/有效持续）、
        频域形状类（质心/带宽/滚降/平坦度/偏度/峭度/峰值因子/斜率/下降量）、
        谐波类（三刺激值/非谐性/奇偶比/谐波能量）。

        Args:
            signal: 输入信号

        Returns:
            全局特征字典（无法可靠估计的项不含于字典中）
        """
        features = {}

        signal = np.asarray(signal, dtype=np.float64)

        # ---- 时域电平 ----
        rms = float(np.sqrt(np.mean(signal**2))) if len(signal) else 0.0
        features["rms"] = rms
        features["rms_db"] = 20 * np.log10(max(rms, 1e-10))

        peak = float(np.max(np.abs(signal))) if len(signal) else 0.0
        features["peak_dbfs"] = 20 * np.log10(max(peak, 1e-10))
        features["crest_factor"] = features["peak_dbfs"] - features["rms_db"]
        features["dc_offset"] = float(np.mean(signal)) * 100.0 if len(signal) else 0.0

        # 过零率
        zcr = np.sum(np.abs(np.diff(np.sign(signal)))) / (2 * len(signal))
        features["zcr"] = zcr * self.sample_rate

        # ---- 时间包络（对齐 TimbreToolbox TEErep）----
        features.update(self._envelope_stats(signal))

        # ---- 频域形状（信号中段 4096 点）----
        from acouscope.dsp import FFTEngine

        engine = FFTEngine(size=4096)
        mid = len(signal) // 2
        frame = signal[max(0, mid - 2048) : mid + 2048]
        if len(frame) < 4096:
            frame = np.pad(frame, (0, 4096 - len(frame)))

        freqs, mag = engine.magnitude_spectrum(frame, db_scale=False)
        freqs_hz = freqs * self.sample_rate

        total_energy = np.sum(mag)
        if total_energy > 0:
            centroid = np.sum(freqs_hz * mag) / total_energy
            features["spectral_centroid"] = float(centroid)

            spread = np.sqrt(
                np.sum((freqs_hz - centroid) ** 2 * mag) / total_energy
            )
            if spread > 1e-12:
                features["spectral_bandwidth"] = float(spread)
                features["spectral_skewness"] = float(
                    np.sum((freqs_hz - centroid) ** 3 * mag)
                    / (total_energy * spread**3)
                )
                features["spectral_kurtosis"] = float(
                    np.sum((freqs_hz - centroid) ** 4 * mag)
                    / (total_energy * spread**4)
                    - 3.0
                )

            # 平坦度
            features["spectral_flatness"] = float(
                np.exp(np.mean(np.log(np.maximum(mag, 1e-12))))
                / max(float(np.mean(mag)), 1e-12)
            )

            # 频谱滚降
            cumulative = np.cumsum(mag)
            rolloff_idx = np.searchsorted(cumulative, total_energy * 0.85)
            if rolloff_idx < len(freqs_hz):
                features["spectral_rolloff"] = float(freqs_hz[rolloff_idx])

            # --- TimbreToolbox 补充 ---
            # 频谱峰值因子
            features["spectral_crest"] = float(
                np.max(mag) / max(float(np.mean(mag)), 1e-10)
            )

            # 频谱斜率（线性回归）
            n_freq = len(mag)
            x = np.arange(n_freq, dtype=np.float64)
            x_mean = x - x.mean()
            x_var = max(float(np.sum(x_mean ** 2)), 1e-10)
            features["spectral_slope"] = float(
                np.sum(x_mean * (mag - mag.mean())) / x_var
            )

            # 频谱下降量
            mag_ratio = mag / max(float(mag[0]), 1e-10)
            k_idx = np.arange(1, n_freq)
            features["spectral_decrease"] = float(
                np.sum(mag_ratio[1:] / k_idx) / (n_freq - 1)
            )

        # ---- 谐波特征（对齐 TimbreToolbox HARMrep）----
        harmonic = self.harmonic_features(signal)
        features.update(harmonic)

        return features
