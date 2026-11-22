# SPDX-License-Identifier: GPL-3.0-only
"""音频文件读写模块。

Offline-First 设计：
- FFmpeg 二进制内置（resources/bin/ffmpeg），无需用户配置系统环境变量
- 直接调用 ffmpeg 解码非无损格式（mp3/m4a/aac/wma/opus），不依赖 pydub/ffprobe
- PyInstaller 打包后从包内 resources 位置解析（frozen 模式 __file__ 被合成为
  sys._MEIPASS/acouscope/audio/io.py，与开发模式同一相对布局；Windows 用 ffmpeg.exe）
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import numpy as np


# ---------------------------------------------------------------------------
# T06：重采样质量记录（最后一次重采样的质量标记）
# ---------------------------------------------------------------------------
# 模块级单例 dict：_resample() 每次重采样就地更新（clear + update），
# last_resample_quality() 返回副本，调用方拿到的 dict 与记录互不影响。
# 半 bin → 音分换算公式（线性回退无抗混叠时的保守不确定度上界）：
#   half_bin_hz      = target_sr / (2 * n_fft),  n_fft = 2048（分析默认帧长）
#   uncertainty_cent = 1200 * log2((ref + half_bin_hz) / ref)，ref 取 A4 单源
#   （dsp.units.get_reference_hz，随用户在设置里改基准）
# 线性插值不做带限，混叠误差以「半 bin」频率量化宽度折算为音分上界；
# 该值仅为未评估口径的占位量级，不是实测校准值（warning 明确标注未评估）。
RESAMPLE_QUALITY: dict = {}


def last_resample_quality() -> dict:
    """返回最近一次重采样的质量标记副本（``method`` / ``anti_alias`` /
    ``uncertainty_cent``）；未发生重采样时返回空 dict。

    返回的是副本：调用方改写返回值不会污染 :data:`RESAMPLE_QUALITY` 记录。
    """
    return dict(RESAMPLE_QUALITY)


def _get_ffmpeg_path() -> str | None:
    """解析内置 FFmpeg 二进制路径。

    优先级：
    1. 随包位置（开发模式与冻结模式共用同一相对布局）：
       acouscope/resources/bin/ffmpeg（Windows 为 ffmpeg.exe）
       ★ 候选名必须带平台后缀：Windows 可执行文件恒带 .exe，
         旧实现两档候选都写无后缀 "ffmpeg"，在 Windows 上 exists() 恒 False（WIN-1 根因）。
    2. 系统 PATH 中的 ffmpeg（最后回退）
    """
    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled = Path(__file__).resolve().parent.parent / "resources" / "bin" / ffmpeg_name
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    return shutil.which("ffmpeg")


@dataclass
class AudioInfo:
    """音频文件信息。"""

    filepath: str
    duration: float  # 秒
    sample_rate: int
    channels: int
    samples: int  # 总采样点数
    bit_depth: int  # 位深
    format: str  # 格式名称
    file_size: int  # 字节数
    md5: str = ""  # 文件 MD5
    # T06：最近一次重采样质量标记（可选，缺省 None；末尾带默认值，
    # 既有 8 参位置/关键字构造零改动）
    resample_quality: dict | None = None

    @property
    def duration_str(self) -> str:
        """格式化的时长字符串。"""
        minutes = int(self.duration // 60)
        seconds = self.duration - minutes * 60
        return f"{minutes}:{seconds:05.2f}"


class AudioIO:
    """音频文件输入输出。

    无损格式（WAV/FLAC/OGG/AIFF）使用 soundfile 原生解码。
    非无损格式（MP3/M4A/AAC/WMA/Opus）直接调用内置 FFmpeg 解码到 raw PCM。
    不依赖 pydub 或 ffprobe，仅需 ffmpeg 一个二进制。
    """

    # soundfile 原生支持的格式
    SOUNDFILE_FORMATS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}

    # 需要 FFmpeg 解码的格式
    FFMPEG_FORMATS = {".mp3", ".m4a", ".aac", ".wma", ".opus"}

    # 全部支持格式
    SUPPORTED_FORMATS = {
        ".wav": "WAV",
        ".aiff": "AIFF",
        ".aif": "AIFF",
        ".flac": "FLAC",
        ".ogg": "OGG",
        ".opus": "Opus",
        ".mp3": "MP3",
        ".m4a": "M4A",
        ".aac": "AAC",
        ".wma": "WMA",
    }

    def __init__(self):
        self._soundfile = None
        self._ffmpeg_path = None
        self._resample_quality_after_load = None  # T06：load 重采样后的质量标记

    def _info_resample_quality(self) -> dict | None:
        """T06：AudioInfo 用的重采样质量标记（load 记录优先，回落全局记录）。"""
        q = self._resample_quality_after_load or last_resample_quality()
        return dict(q) if q else None

    def _get_ffmpeg(self) -> str | None:
        """获取内置 FFmpeg 路径（首次调用时缓存）。"""
        if self._ffmpeg_path is None:
            self._ffmpeg_path = _get_ffmpeg_path()
        return self._ffmpeg_path

    def _import_soundfile(self):
        """延迟导入 soundfile。"""
        if self._soundfile is None:
            try:
                import soundfile as sf
                self._soundfile = sf
            except ImportError:
                raise ImportError("soundfile 未安装")
        return self._soundfile

    # ------------------------------------------------------------------
    # FFmpeg 辅助
    # ------------------------------------------------------------------

    def _probe_ffmpeg(self, filepath: Path) -> dict:
        """用 ffmpeg -i 从 stderr 解析音频元信息。

        不依赖 ffprobe，仅用 ffmpeg 一个二进制。
        返回: {sample_rate, channels, duration}
        """
        ff = self._get_ffmpeg()
        if not ff:
            raise RuntimeError("FFmpeg 未找到")

        proc = subprocess.run(
            [ff, "-hide_banner", "-i", str(filepath)],
            capture_output=True, text=True, timeout=30,
        )
        info = {"sample_rate": 44100, "channels": 1, "duration": None}
        for line in (proc.stderr or "").splitlines():
            if "Audio:" not in line:
                continue
            # 例: "  Stream #0:1: Audio: mp3, 44100 Hz, stereo, fltp, 128 kb/s"
            parts = [p.strip() for p in line.split(",")]
            for p in parts:
                if "Hz" in p:
                    m = re.search(r"(\d+)\s*Hz", p)
                    if m:
                        info["sample_rate"] = int(m.group(1))
                if "stereo" in p:
                    info["channels"] = 2
                elif "mono" in p:
                    info["channels"] = 1
            break

        # 从 Duration: 行提取时长
        for line in (proc.stderr or "").splitlines():
            if line.strip().startswith("Duration:"):
                m = re.search(
                    r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", line
                )
                if m:
                    h, mi, s = m.groups()
                    info["duration"] = int(h) * 3600 + int(mi) * 60 + float(s)
                break

        return info

    def _load_with_ffmpeg(
        self, filepath: Path, ext: str
    ) -> Tuple[np.ndarray, int]:
        """通过内置 FFmpeg 直接解码音频到 raw PCM。

        支持 mp3/m4a/aac/wma/opus 等非无损格式。
        直接调用 ffmpeg 二进制解码到 f32le PCM，不依赖 pydub/ffprobe。
        """
        ff = self._get_ffmpeg()
        if not ff:
            raise RuntimeError(
                f"FFmpeg 未找到，无法解码 {ext} 格式。"
                f"请重新安装 AcouScope 或将 ffmpeg 加入系统 PATH。"
            )

        # 解析原始采样率
        probe = self._probe_ffmpeg(filepath)
        sr = probe["sample_rate"]

        # 用 ffmpeg 解码到 raw f32le PCM，通过 stdout 输出
        cmd = [
            ff, "-hide_banner", "-loglevel", "error",
            "-i", str(filepath),
            "-f", "f32le",        # 32-bit float little-endian
            "-acodec", "pcm_f32le",
            "-ar", str(sr),
            "-ac", "1",           # 直接混缩为单声道
            "pipe:1",
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg 解码失败 ({ext}): "
                f"{proc.stderr.decode('utf-8', errors='replace')[:200]}"
            )

        # raw bytes → numpy float32 → float64
        data = np.frombuffer(proc.stdout, dtype=np.float32).astype(np.float64)
        return data, sr

    # ------------------------------------------------------------------
    # 加载音频
    # ------------------------------------------------------------------

    def load(
        self,
        filepath: str | Path,
        mono: bool = True,
        sample_rate: int | None = None,
    ) -> Tuple[np.ndarray, int]:
        """加载音频文件。

        Args:
            filepath: 音频文件路径
            mono: 是否转换为单声道
            sample_rate: 目标采样率，None 则保持原始采样率

        Returns:
            (音频数据, 采样率)
            音频数据为 float64 数组，范围 [-1.0, 1.0]
        """
        filepath = Path(filepath)
        ext = filepath.suffix.lower()

        sf = self._import_soundfile()

        if ext in self.SOUNDFILE_FORMATS:
            data, sr = sf.read(str(filepath), always_2d=False)
        elif ext in self.FFMPEG_FORMATS:
            data, sr = self._load_with_ffmpeg(filepath, ext)
        else:
            try:
                data, sr = sf.read(str(filepath), always_2d=False)
            except Exception as e:
                raise ValueError(f"不支持的音频格式: {ext} ({e})")

        # 转单声道
        if mono and data.ndim > 1 and data.shape[1] > 1:
            data = np.mean(data, axis=1)

        # 重采样
        if sample_rate is not None and sample_rate != sr:
            data = self._resample(data, sr, sample_rate)
            # T06：load() 发生重采样后，把 last_resample_quality() 记到实例，
            # 供随后 get_info() 写入 AudioInfo.resample_quality
            self._resample_quality_after_load = last_resample_quality()
            sr = sample_rate

        return data.astype(np.float64), sr

    # ------------------------------------------------------------------
    # 获取信息
    # ------------------------------------------------------------------

    def get_info(self, filepath: str | Path) -> AudioInfo:
        """获取音频文件信息（不加载音频数据）。"""
        filepath = Path(filepath)
        ext = filepath.suffix.lower()

        # 计算 MD5
        md5_hash = ""
        try:
            with open(filepath, "rb") as f:
                md5_hash = hashlib.md5(f.read()[:1024 * 1024]).hexdigest()
        except Exception:
            pass

        if ext in self.FFMPEG_FORMATS:
            # FFmpeg 格式：用 _probe_ffmpeg 获取信息
            probe = self._probe_ffmpeg(filepath)
            sr = probe["sample_rate"]
            channels = probe["channels"]
            duration = probe["duration"] or 0.0
            samples = int(duration * sr) if duration else 0
            fmt_name = self.SUPPORTED_FORMATS.get(ext, ext.lstrip("."))
            return AudioInfo(
                filepath=str(filepath),
                duration=duration,
                sample_rate=sr,
                channels=channels,
                samples=samples,
                bit_depth=16,  # 有损格式无固定位深，报告 16 作默认
                format=fmt_name,
                file_size=filepath.stat().st_size,
                md5=md5_hash,
                resample_quality=self._info_resample_quality(),
            )

        # soundfile 格式
        sf = self._import_soundfile()
        info = sf.info(str(filepath))

        bit_depth = 16
        subtype = info.subtype
        if subtype and subtype.startswith("PCM_"):
            try:
                bit_depth = int(subtype.split("_")[1])
            except (IndexError, ValueError):
                pass
        elif subtype == "FLOAT":
            bit_depth = 32

        return AudioInfo(
            filepath=str(filepath),
            duration=float(info.duration),
            sample_rate=info.samplerate,
            channels=info.channels,
            samples=info.frames,
            bit_depth=bit_depth,
            format=info.format,
            file_size=filepath.stat().st_size,
            md5=md5_hash,
            resample_quality=self._info_resample_quality(),
        )

    # ------------------------------------------------------------------
    # 保存音频
    # ------------------------------------------------------------------

    def save(
        self,
        data: np.ndarray,
        sample_rate: int,
        filepath: str | Path,
        format: str | None = None,
    ) -> None:
        """保存音频到文件。"""
        sf = self._import_soundfile()
        filepath = Path(filepath)

        if format is None:
            format = self.SUPPORTED_FORMATS.get(filepath.suffix.lower(), "WAV")

        sf.write(str(filepath), data, sample_rate, format=format)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resample(data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """重采样。

        优先使用 samplerate（高质量 sinc），失败时回退到 numpy 线性插值。
        T06：两条分支都把质量标记写入模块级 :data:`RESAMPLE_QUALITY`；
        线性回退显式发 ``RuntimeWarning`` 并标注 ``anti_alias=False`` +
        ``uncertainty_cent``（半 bin 音分，公式见模块顶部记录注释），
        **回退本身保留**（``test_regression.py::test_resample_numpy_fallback``
        依赖 ``np.interp`` 路径，禁改成抛错）。
        """
        try:
            import samplerate
            result = samplerate.resample(data, target_sr / orig_sr, "sinc_best")
        except Exception:
            pass  # 无 samplerate / sinc 失败 → 走下方线性回退
        else:
            RESAMPLE_QUALITY.clear()
            RESAMPLE_QUALITY.update({
                "method": "sinc_best",
                "anti_alias": True,
                "uncertainty_cent": 0.0,
            })
            return result

        # 纯 numpy 线性插值回退（保留，不抛错）
        warnings.warn(
            "线性插值重采样无抗混叠，测量不确定度未评估",
            RuntimeWarning, stacklevel=2,
        )
        # 半 bin → 音分：half_bin_hz = target_sr/(2*2048)；
        # uncertainty_cent = 1200*log2((ref + half_bin_hz)/ref)，ref 取 A4 单源
        from acouscope.dsp.units import get_reference_hz

        half_bin_hz = float(target_sr) / (2.0 * 2048)
        ref_hz = float(get_reference_hz())
        uncertainty_cent = 1200.0 * math.log2((ref_hz + half_bin_hz) / ref_hz)
        RESAMPLE_QUALITY.clear()
        RESAMPLE_QUALITY.update({
            "method": "linear_fallback",
            "anti_alias": False,
            "uncertainty_cent": float(uncertainty_cent),
        })
        duration = len(data) / orig_sr
        n_samples = max(1, int(round(duration * target_sr)))
        old_positions = np.arange(len(data)) / orig_sr
        new_positions = np.arange(n_samples) / target_sr
        return np.interp(new_positions, old_positions, data)
