# SPDX-License-Identifier: GPL-3.0-only
"""SwiftF0 ONNX 后端 — 轻量级 SOTA 音高检测。

SWIFT_F0_BACKEND_V1 — clean-room 封装，依据论文：
- Nieradzik 2025, "SwiftF0: Fast and Accurate Monophonic Pitch Detection", arXiv:2508.18440

模型架构：STFT → 2D CNN(5层) → 1D FreqConv → softmax 期望值 → 连续 Hz
模型内置期望值法反量化（f̂ = exp(Σ p_b · log(f_b))），输出已是连续 Hz。

设计约束：
- 16kHz 重采样：内部用 numpy 线性插值（不依赖 librosa/scipy）
- 离线分析：is_streaming=False（用户强制指令）
- ONNX 隔离：仅依赖 onnxruntime，不引入 PyTorch/TF
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


# SwiftF0 常量（论文 §3.2-3.3，core.py 实读）
_TARGET_SR = 16000
_HOP_LENGTH = 256
_FRAME_LENGTH = 1024
_STFT_PADDING = (_FRAME_LENGTH - _HOP_LENGTH) // 2  # 384
_CENTER_OFFSET = (_FRAME_LENGTH - 1) / 2 - _STFT_PADDING  # 127.5
_MODEL_FMIN = 46.875
_MODEL_FMAX = 2093.75


def _user_models_dir() -> str:
    """用户数据目录下的模型目录（可写；T-1051 运行时下载一律写这里）。

    沿用仓内既有用户数据目录约定 `get_data_dir()`；打包态可写、跨平台、升级不丢。
    """
    return os.path.join(str(get_data_dir()), "models")


def _resolve_model_path() -> str | None:
    """解析内置 SwiftF0 ONNX 模型路径。

    优先级（T-1051）：
    1. 用户数据目录（运行时下载目标，可写）
    2. PyInstaller `_MEIPASS`（只读，若将来重新随包）
    3. 开发模式 resources/models（只读回退）
    4. pip 包
    """
    # 1. 用户数据目录（运行时下载目标，见 _user_models_dir / download_model）
    user = os.path.join(_user_models_dir(), "swift_f0.onnx")
    if os.path.exists(user):
        return user
    # 2. PyInstaller 模式
    if hasattr(sys, "_MEIPASS"):
        p = os.path.join(sys._MEIPASS, "models", "swift_f0.onnx")
        if os.path.exists(p):
            return p
    # 3. 开发模式
    dev = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "models", "swift_f0.onnx")
    dev = os.path.normpath(dev)
    if os.path.exists(dev):
        return dev
    # 4. pip 包
    try:
        import swift_f0
        p = os.path.join(os.path.dirname(swift_f0.__file__), "model.onnx")
        if os.path.exists(p):
            return p
    except ImportError:
        pass
    return None


# SwiftF0 模型下载 URL（GitHub Release v0.1.0；域名正确，无需修改）
_SWIFTF0_URL = "https://github.com/mirkolotzek/swift-f0/releases/download/v0.1.0/swift_f0.onnx"
# 权重实际体积：390KB（399,114 字节实测）
# sha256：上游未公布官方校验值 → 取本仓首次下载实测值（仅防后续漂移，
# 不能防首次 MITM；性质见 THIRD-PARTY-NOTICES.md §3.6）
_SWIFTF0_SHA256 = "fa91bb45512b90339cf4b00a599ba8fe3a253c46419fcfe6b46df77a8a8336a5"


def _download_model(target_path: str, progress_cb=None) -> bool:
    """下载 SwiftF0 ONNX 模型到 target_path。

    使用 urllib（标准库），不依赖 requests。
    下载完成后做 sha256 完整性校验（供应链加固）；不符即失败并删除临时文件。
    progress_cb: 可选回调 callback(downloaded: int, total: int)。
    """
    import hashlib
    import urllib.request

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        req = urllib.request.Request(_SWIFTF0_URL, headers={"User-Agent": "AcouScope/0.99"})
        with urllib.request.urlopen(req, timeout=30) as resp:
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
            if sha.hexdigest() != _SWIFTF0_SHA256:
                os.remove(tmp_path)
                return False
            os.rename(tmp_path, target_path)
        return True
    except Exception:
        return False


def _resample_to_16k(signal: np.ndarray, sr: float) -> np.ndarray:
    """高质量线性插值重采样到 16kHz（不依赖 librosa/scipy）。

    重采样耗时计入总推理时间（用户强制指令）。
    """
    if sr == _TARGET_SR:
        return signal.astype(np.float32)
    # 计算新样本数
    n_out = int(round(len(signal) * _TARGET_SR / sr))
    # 原始时间位置
    t_old = np.arange(len(signal)) / sr
    t_new = np.arange(n_out) / _TARGET_SR
    # 线性插值
    return np.interp(t_new, t_old, signal).astype(np.float32)


class SwiftF0Backend:
    """SwiftF0 ONNX 音高检测后端（离线，CPU 推理）。

    实现 PitchBackend Protocol。输出连续 Hz（模型内置反量化）。
    """

    name = "SwiftF0"
    is_streaming = False  # 离线全局分析（用户强制指令）

    _session = None
    _input_name = None
    _lock = threading.Lock()

    def __init__(self):
        self._ensure_model()

    def _ensure_model(self):
        """懒加载 ONNX 模型（线程安全）。"""
        if SwiftF0Backend._session is not None:
            return
        with SwiftF0Backend._lock:
            if SwiftF0Backend._session is not None:
                return
            import onnxruntime as ort

            model_path = _resolve_model_path()
            if model_path is None:
                raise RuntimeError(
                    "SwiftF0 模型未找到。首次使用前需下载模型（约 390KB），"
                    "请通过界面执行「SwiftF0 模型下载」，或重新安装 AcouScope。"
                )

            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            SwiftF0Backend._session = ort.InferenceSession(
                model_path, opts, providers=["CPUExecutionProvider"]
            )
            SwiftF0Backend._input_name = SwiftF0Backend._session.get_inputs()[0].name

    def detect(
        self,
        signal: np.ndarray,
        sr: float,
        fmin: float = 40.0,
        fmax: float = 2000.0,
        progress_cb: "Callable[[float], None] | None" = None,
    ) -> PitchTrack:
        """SwiftF0 音高检测。

        Args:
            signal: 音频信号（float64/float32，任意采样率）
            sr: 采样率
            fmin/fmax: 频率范围（裁剪输出，不传给模型）
            progress_cb: 进度回调 (0.0→1.0)

        Returns:
            PitchTrack（连续 Hz，NaN=未检出/超量程）
        """
        routed = route_or_detect("SwiftF0Backend", self, signal, sr, fmin, fmax, progress_cb)
        if routed is not None:
            return routed
        # 16kHz 重采样
        audio_16k = _resample_to_16k(signal, sr)
        if audio_16k.ndim > 1:
            audio_16k = np.mean(audio_16k, axis=-1)
        audio_16k = np.asarray(audio_16k, dtype=np.float32).ravel()

        # 最小长度检查
        min_len = 256  # MIN_AUDIO_LENGTH
        if len(audio_16k) < min_len:
            audio_16k = np.pad(audio_16k, (0, max(0, min_len - len(audio_16k))))

        if progress_cb:
            progress_cb(0.3)

        # ONNX 推理
        inputs = {SwiftF0Backend._input_name: audio_16k[None, :]}
        outputs = SwiftF0Backend._session.run(None, inputs)

        if progress_cb:
            progress_cb(0.8)

        # 提取输出（模型已输出连续 Hz）
        pitch_hz = outputs[0][0].astype(np.float64)  # (T,)
        confidence = outputs[1][0].astype(np.float64)  # (T,)

        # 时间戳
        n_frames = len(pitch_hz)
        times = (np.arange(n_frames) * _HOP_LENGTH + _CENTER_OFFSET) / _TARGET_SR

        # 频率范围裁剪 + 置信度门控
        # 超量程帧 → NaN
        out_f0 = pitch_hz.copy()
        out_f0[(pitch_hz < fmin) | (pitch_hz > fmax)] = np.nan
        out_f0[confidence < 0.5] = np.nan

        if progress_cb:
            progress_cb(1.0)

        return PitchTrack(
            times=times,
            f0_hz=out_f0,
            confidence=confidence,
            fmin=fmin,
            fmax=fmax,
        )

    def is_available(self) -> bool:
        """检查模型和 onnxruntime 是否可用。"""
        try:
            self._ensure_model()
            return True
        except Exception:
            return False

    @staticmethod
    def download_model(progress_cb=None) -> bool:
        """下载 SwiftF0 ONNX 模型到用户数据目录（T-1051 运行时下载目标）。

        打包态可写、跨平台、升级不丢；已存在（含随包/开发副本）则直接成功。
        progress_cb: callback(downloaded: int, total: int)
        """
        if _resolve_model_path():
            return True  # 已存在
        target = os.path.join(_user_models_dir(), "swift_f0.onnx")
        return _download_model(target, progress_cb)


SWIFT_F0_BACKEND_V1 = "1"
