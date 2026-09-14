# SPDX-License-Identifier: GPL-3.0-only
"""RMVPE ONNX 后端 — 复音人声音高提取。

RMVPE_BACKEND_V1 — clean-room 封装，依据论文：
- "RMVPE: A Robust Model for Vocal Pitch Estimation in Polyphonic Music", ISMIR 2023

模型架构：MelSpec(128, 16kHz) → DeepUNet → 360-class salience → local average cents → 连续 Hz
反量化：local average cents（9-bin 加权平均），禁止直接取 argmax bin。

设计约束：
- 纯 numpy mel 前端（不依赖 scipy/librosa，避开依赖冲突）
- 16kHz 重采样：numpy 线性插值
- 离线分析：is_streaming=False
- ONNX 隔离：仅依赖 onnxruntime
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable

import numpy as np

from acouscope.analysis.pitch import PitchTrack
from acouscope.analysis.worker.routing import route_or_detect
from acouscope.utils.config import get_data_dir


# === 常量（源码 model.py 实读） ===
_MEL_CHANNELS = 128
_SAMPLE_RATE = 16_000
_WIN_LENGTH = 1024
_HOP_LENGTH = 160
_N_FFT = 1024
_MEL_FMIN = 30.0
_MEL_FMAX = 8_000.0
_CLAMP = 1e-5
_N_CLASS = 360
_CENTS_OFFSET = 1997.3794084376191


def _hann_window(n: int) -> np.ndarray:
    """纯 numpy Hann 窗（替代 scipy.signal.get_window）。"""
    if n == 1:
        return np.ones(1, dtype=np.float32)
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))).astype(np.float32)


def _hz_to_mel(hz: float) -> float:
    """Hz → Mel（htk 公式）。"""
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    """Mel → Hz（htk 公式）。"""
    return 700.0 * (10 ** (mel / 2595.0) - 1.0)


def _mel_filterbank(
    n_mels: int = _MEL_CHANNELS,
    n_fft: int = _N_FFT,
    sr: int = _SAMPLE_RATE,
    fmin: float = _MEL_FMIN,
    fmax: float = _MEL_FMAX,
) -> np.ndarray:
    """纯 numpy mel 滤波器组（替代 librosa.filters.mel）。

    返回 (n_mels, n_fft//2+1) 的三角滤波器矩阵。
    """
    n_freqs = n_fft // 2 + 1
    fft_freqs = np.linspace(0, sr / 2, n_freqs)

    mel_min = _hz_to_mel(fmin)
    mel_max = _hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = np.array([_mel_to_hz(m) for m in mel_points])

    weights = np.zeros((n_mels, n_freqs), dtype=np.float32)
    for i in range(n_mels):
        left = hz_points[i]
        center = hz_points[i + 1]
        right = hz_points[i + 2]
        # 上升段
        idx_rise = (fft_freqs >= left) & (fft_freqs <= center)
        if center > left:
            weights[i, idx_rise] = (fft_freqs[idx_rise] - left) / (center - left)
        # 下降段
        idx_fall = (fft_freqs >= center) & (fft_freqs <= right)
        if right > center:
            weights[i, idx_fall] = (right - fft_freqs[idx_fall]) / (right - center)
    return weights


class _MelSpectrogram:
    """纯 numpy mel 频谱图提取器（不依赖 scipy/librosa）。"""

    def __init__(self):
        self.hop_length = _HOP_LENGTH
        self.n_fft = _N_FFT
        self.window = _hann_window(_WIN_LENGTH)
        self.mel_basis = _mel_filterbank()

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        """计算 log-mel 频谱图。

        Args:
            audio: (N,) float32, 16kHz mono

        Returns:
            (n_mels, T) float32, log-mel 频谱图
        """
        # Reflect padding（center=True）
        audio = np.pad(audio, self.n_fft // 2, mode="reflect")

        # Strided STFT（as_strided 避免逐帧循环）
        n_frames = (len(audio) - self.n_fft) // self.hop_length + 1
        shape = (n_frames, self.n_fft)
        strides = (audio.strides[0] * self.hop_length, audio.strides[0])
        frames = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)

        # FFT
        fft_out = np.fft.rfft(frames * self.window, n=self.n_fft)  # (frames, n_fft//2+1)
        magnitude = np.abs(fft_out).T.astype(np.float32)  # (n_fft//2+1, frames)

        # Mel 滤波器组
        mel_out = self.mel_basis @ magnitude  # (n_mels, frames)

        # Log 压缩
        return np.log(np.clip(mel_out, _CLAMP, None))


def _resample_to_16k(signal: np.ndarray, sr: float) -> np.ndarray:
    """numpy 线性插值重采样到 16kHz。"""
    if sr == _SAMPLE_RATE:
        return signal.astype(np.float32)
    n_out = int(round(len(signal) * _SAMPLE_RATE / sr))
    t_old = np.arange(len(signal)) / sr
    t_new = np.arange(n_out) / _SAMPLE_RATE
    return np.interp(t_new, t_old, signal).astype(np.float32)


def _to_local_average_cents(salience: np.ndarray) -> np.ndarray:
    """RMVPE 反量化：local average cents（9-bin 加权平均）。

    将 360-bin salience 概率转为连续 cents 值。
    禁止直接取 argmax bin 频率（反量化铁律）。

    Args:
        salience: (T, 360) 概率矩阵

    Returns:
        (T,) 连续 cents 值
    """
    cents_grid = 20 * np.arange(_N_CLASS) + _CENTS_OFFSET
    cents_mapping = np.pad(cents_grid, (4, 4))  # 368

    center = np.argmax(salience, axis=1)  # (T,)
    salience_padded = np.pad(salience, ((0, 0), (4, 4)))  # (T, 368)
    center += 4

    frame_idx = np.arange(salience_padded.shape[0])[:, None]
    bin_offsets = np.arange(9)[None, :]
    bin_idx = (center[:, None] - 4) + bin_offsets  # (T, 9)

    window_sal = salience_padded[frame_idx, bin_idx]  # (T, 9)
    window_cent = cents_mapping[bin_idx]  # (T, 9)

    # 加权平均（避免除零）
    denom = window_sal.sum(1, keepdims=True)
    denom = np.where(denom > 0, denom, 1.0)
    return (window_sal * window_cent).sum(1) / denom[:, 0]


def _user_models_dir() -> str:
    """用户数据目录下的模型目录（可写；T-1051 运行时下载一律写这里）。

    沿用仓内既有用户数据目录约定 `get_data_dir()`（macOS =
    ~/Library/Application Support/AcouScope，含 `_local` 回退链）；
    打包态可写、跨平台、升级不丢。
    """
    return os.path.join(str(get_data_dir()), "models")


def _resolve_model_path() -> str | None:
    """解析内置 RMVPE ONNX 模型路径。

    优先级（T-1051）：
    1. 用户数据目录（运行时下载目标，可写）
    2. PyInstaller `_MEIPASS`（只读，若将来重新随包）
    3. 开发模式 resources/models（只读回退）
    """
    # 1. 用户数据目录（运行时下载目标，见 _user_models_dir / download_model）
    user = os.path.join(_user_models_dir(), "rmvpe.onnx")
    if os.path.exists(user):
        return user
    # 2. PyInstaller 模式（只读）
    if hasattr(sys, "_MEIPASS"):
        p = os.path.join(sys._MEIPASS, "models", "rmvpe.onnx")
        if os.path.exists(p):
            return p
    dev = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "models", "rmvpe.onnx")
    dev = os.path.normpath(dev)
    if os.path.exists(dev):
        return dev
    return None


# RMVPE 模型下载 URL（HuggingFace.co；无需浏览器鉴权，可直接 resolve）
_RMVPE_URL = "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.onnx"
# 权重实际体积：345MB（361,688,443 字节实测）
# sha256：上游未公布官方校验值 → 取本仓首次下载实测值（仅防后续漂移，
# 不能防首次 MITM；性质见 THIRD-PARTY-NOTICES.md §3.6）
_RMVPE_SHA256 = "5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd"


def _download_model(target_path: str, progress_cb=None) -> bool:
    """下载 RMVPE ONNX 模型到 target_path。

    使用 urllib（标准库），不依赖 requests/huggingface_hub。
    下载完成后做 sha256 完整性校验（供应链加固）；不符即失败并删除临时文件。
    progress_cb: 可选回调 callback(downloaded: int, total: int)。
    """
    import hashlib
    import urllib.request

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        req = urllib.request.Request(_RMVPE_URL, headers={"User-Agent": "AcouScope/0.99"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            tmp_path = target_path + ".tmp"
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total:
                        progress_cb(downloaded, total)
            # sha256 完整性校验：不符 → 删临时文件并失败
            sha = hashlib.sha256()
            with open(tmp_path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    sha.update(chunk)
            if sha.hexdigest() != _RMVPE_SHA256:
                os.remove(tmp_path)
                return False
            os.rename(tmp_path, target_path)
        return True
    except Exception:
        return False


class RMVPEBackend:
    """RMVPE ONNX 音高检测后端（离线，CPU 推理，复音人声优化）。

    实现 PitchBackend Protocol。
    纯 numpy mel 前端 + ONNX 推理 + local average cents 反量化。
    """

    name = "RMVPE"
    is_streaming = False  # 离线全局分析

    _session = None
    _input_name = None
    _output_name = None
    _mel_extractor = None
    _lock = threading.Lock()

    def __init__(self):
        self._ensure_model()

    def _ensure_model(self):
        """懒加载 ONNX 模型（线程安全）。"""
        if RMVPEBackend._session is not None:
            return
        with RMVPEBackend._lock:
            if RMVPEBackend._session is not None:
                return
            import onnxruntime as ort

            model_path = _resolve_model_path()
            if model_path is None:
                raise RuntimeError(
                    "RMVPE 模型未找到。首次使用前需下载模型（约 345MB），"
                    "请通过界面执行「RMVPE 模型下载」，或重新安装 AcouScope。"
                )

            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            RMVPEBackend._session = ort.InferenceSession(
                model_path, sess_options=opts, providers=["CPUExecutionProvider"]
            )
            RMVPEBackend._input_name = RMVPEBackend._session.get_inputs()[0].name
            RMVPEBackend._output_name = RMVPEBackend._session.get_outputs()[0].name
            RMVPEBackend._mel_extractor = _MelSpectrogram()

    def detect(
        self,
        signal: np.ndarray,
        sr: float,
        fmin: float = 40.0,
        fmax: float = 2000.0,
        progress_cb: "Callable[[float], None] | None" = None,
    ) -> PitchTrack:
        """RMVPE 音高检测。

        Args:
            signal: 音频信号（任意采样率）
            sr: 采样率
            fmin/fmax: 频率范围（裁剪输出）

        Returns:
            PitchTrack（连续 Hz，NaN=未检出）
        """
        routed = route_or_detect("RMVPEBackend", self, signal, sr, fmin, fmax, progress_cb)
        if routed is not None:
            return routed
        # 16kHz 重采样
        audio = _resample_to_16k(signal, sr)
        if audio.ndim > 1:
            audio = np.mean(audio, axis=-1)
        audio = audio.astype(np.float32).ravel()

        if progress_cb:
            progress_cb(0.2)

        # Mel 频谱图
        mel = RMVPEBackend._mel_extractor(audio)  # (n_mels, T)
        mel = mel[np.newaxis]  # (1, n_mels, T) — batch 维

        if progress_cb:
            progress_cb(0.4)

        # Pad T 到 32 的倍数
        n_frames = mel.shape[-1]
        n_pad = 32 * ((n_frames - 1) // 32 + 1) - n_frames
        if n_pad:
            mel = np.pad(mel, ((0, 0), (0, 0), (0, n_pad)))

        # ONNX 推理
        hidden = RMVPEBackend._session.run(
            [RMVPEBackend._output_name], {RMVPEBackend._input_name: mel}
        )[0]  # (1, T_padded, 360)
        activation = hidden[0, :n_frames].astype(np.float32)  # (T, 360)

        if progress_cb:
            progress_cb(0.8)

        # 反量化：local average cents
        cents = _to_local_average_cents(activation)  # (T,)
        frequency = 10 * 2 ** (cents / 1200)  # (T,) 连续 Hz

        # 置信度 = max salience
        confidence = activation.max(axis=1).astype(np.float64)  # (T,)

        # 时间戳
        hop_seconds = _HOP_LENGTH / _SAMPLE_RATE  # 0.01s
        times = np.arange(len(frequency)) * hop_seconds

        # 频率范围裁剪
        out_f0 = frequency.astype(np.float64)
        out_f0[(out_f0 < fmin) | (out_f0 > fmax)] = np.nan
        out_f0[confidence < 0.03] = np.nan

        if progress_cb:
            progress_cb(1.0)

        return PitchTrack(
            times=times,
            f0_hz=out_f0,
            confidence=confidence,
            fmin=fmin,
            fmax=fmax,
            cent_ref=440.0,
        )

    def is_available(self) -> bool:
        try:
            self._ensure_model()
            return True
        except Exception:
            return False

    @staticmethod
    def download_model(progress_cb=None) -> bool:
        """下载 RMVPE ONNX 模型到用户数据目录（T-1051 运行时下载目标）。

        打包态可写、跨平台、升级不丢；已存在（含随包/开发副本）则直接成功。
        progress_cb: callback(downloaded: int, total: int)
        """
        if _resolve_model_path():
            return True  # 已存在
        target = os.path.join(_user_models_dir(), "rmvpe.onnx")
        return _download_model(target, progress_cb)


RMVPE_BACKEND_V1 = "1"
