# SPDX-License-Identifier: GPL-3.0-only
"""音频录制模块。

基于 QtMultimedia 的 QAudioSource，支持：
- 录制、暂停、停止
- 实时电平监控（Audacity 风格录音电平表）
- 设备选择
- 采样率/通道配置
- 录音数据保存为 WAV
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from acouscope.utils.log import get_logger

_log = get_logger(__name__)


def save_audio_file(
    data: np.ndarray,
    sample_rate: int,
    path: str,
    fmt: str = "WAV",
    depth: str | None = "PCM_16",
) -> tuple[bool, str]:
    """保存录音数据到音频文件。

    Args:
        data: float 数组，[-1, 1]
        sample_rate: 采样率
        path: 输出路径（扩展名应与 fmt 匹配）
        fmt: WAV / FLAC / AIFF / MP3 / OGG
        depth: 采样深度 subtype（PCM_16/PCM_24/FLOAT）；
               MP3/OGG 传 None（压缩格式自动质量）

    Returns:
        (是否成功, 错误信息)
    """
    if data is None or len(data) == 0:
        return False, "没有音频数据"

    # 保证扩展名与格式匹配
    ext_map = {"WAV": ".wav", "FLAC": ".flac", "AIFF": ".aiff", "MP3": ".mp3", "OGG": ".ogg"}
    ext = ext_map.get(fmt.upper(), ".wav")
    p = Path(path)
    if p.suffix.lower() != ext:
        p = p.with_suffix(ext)

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        import soundfile as sf

        subtype = depth if fmt.upper() in ("WAV", "FLAC", "AIFF") and depth else None
        if fmt.upper() == "MP3":
            subtype = "MPEG_LAYER_III"
        elif fmt.upper() == "OGG":
            subtype = "VORBIS"

        sf.write(str(p), np.asarray(data, dtype=np.float64), sample_rate, subtype=subtype)
        return True, str(p)
    except ImportError:
        # soundfile 不可用：仅 WAV 16-bit 回退
        if fmt.upper() != "WAV":
            return False, f"未安装 soundfile，无法保存 {fmt} 格式"
        try:
            pcm = (np.clip(np.asarray(data), -1.0, 1.0) * 32767.0).astype(np.int16)
            with wave.open(str(p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm.tobytes())
            return True, str(p)
        except Exception as e:
            return False, str(e)
    except Exception as e:
        return False, str(e)


class AudioRecorder:
    """音频录制器。

    使用 QAudioSource 从麦克风录音，支持实时电平回调和数据累积。
    """

    def __init__(self):
        self._source = None  # QAudioSource
        self._input_device = None  # QAudioDevice
        self._io_device = None  # QIODevice

        # 录音参数
        self._sample_rate: int = 44100
        self._channels: int = 1

        # 状态
        self._is_recording = False
        self._is_paused = False

        # 录音数据累积（list 暂存 O(1) 追加，避免 O(n²) 反复拼接）
        self._recorded_data: list[np.ndarray] = []
        self._total_samples: int = 0
        # 合并缓存：仅当 _recorded_data 有新增时才重新 concatenate 一次
        self._merged_cache: Optional[np.ndarray] = None
        self._merged_count: int = 0

        # 采集有界环形缓冲（start 时创建）与累计丢样计数
        self._ring = None
        self._dropped_samples: int = 0

        # 回调
        self._level_callback: Optional[Callable[[float], None]] = None
        self._data_callback: Optional[Callable[[np.ndarray], None]] = None

        # 定时器轮询（读取音频数据）
        self._poll_timer = None

    # ------------------------------------------------------------------
    # 设备管理
    # ------------------------------------------------------------------

    @staticmethod
    def list_devices() -> list[tuple[str, object]]:
        """列出可用的音频输入设备。

        Returns:
            [(设备描述, QAudioDevice), ...]
        """
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            devices = QMediaDevices.audioInputs()
            return [(d.description(), d) for d in devices]
        except Exception:
            return []

    def set_device(self, device) -> bool:
        """设置录音设备。"""
        if self._is_recording:
            self.stop()
        self._input_device = device
        return True

    def set_sample_rate(self, rate: int):
        self._sample_rate = max(8000, min(rate, 192000))

    def set_channels(self, channels: int):
        self._channels = max(1, min(channels, 2))

    def get_sample_rate(self) -> int:
        return self._sample_rate

    # ------------------------------------------------------------------
    # 回调设置
    # ------------------------------------------------------------------

    def set_level_callback(self, callback: Callable[[float], None]):
        """设置实时电平回调（参数为 0.0 ~ 1.0 的峰值）。"""
        self._level_callback = callback

    def set_data_callback(self, callback: Callable[[np.ndarray], None]):
        """设置实时数据回调（每块录音数据）。"""
        self._data_callback = callback

    # ------------------------------------------------------------------
    # 录制控制
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """开始录音。

        Returns:
            是否成功启动
        """
        if self._is_recording:
            return True

        try:
            from PyQt6.QtMultimedia import QAudioSource, QAudioFormat, QMediaDevices
            from PyQt6.QtCore import QTimer
        except ImportError:
            return False

        # 构造格式
        fmt = QAudioFormat()
        fmt.setSampleRate(self._sample_rate)
        fmt.setChannelCount(self._channels)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)

        # 选择设备
        if self._input_device is None:
            devices = QMediaDevices.audioInputs()
            if not devices:
                return False
            self._input_device = devices[0]

        # 创建音频源（bufferSize≈120ms：到达粒度细，且 UI 线程偶发卡顿
        # 时不溢出丢样）
        buffer_bytes = max(4096, int(self._sample_rate * 0.12) * self._channels * 4)
        self._source = QAudioSource(self._input_device, fmt)
        try:
            self._source.setBufferSize(buffer_bytes)
        except Exception:
            pass  # 旧 Qt 版本无此方法时用系统默认缓冲

        # 启动
        self._io_device = self._source.start()
        if self._io_device is None:
            self._source = None
            return False

        # 重置数据（含合并缓存）
        self._recorded_data = []
        self._total_samples = 0
        self._merged_cache = None
        self._merged_count = 0

        # 采集有界环形缓冲（2s 容量）：采集块异常超大/消费积压超容量时丢样可计数
        from acouscope.audio.ring_buffer import FixedRingBuffer
        self._ring = FixedRingBuffer(2.0, self._sample_rate)
        self._dropped_samples = 0

        self._is_recording = True
        self._is_paused = False

        # 用定时器轮询读取数据（16ms ≈ 60Hz：小块高频到达，
        # 波形/电平表每帧推进量小且均匀，不顿挫）
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_audio)
        self._poll_timer.start(16)

        return True

    def pause(self):
        """暂停录音。"""
        if self._is_recording and not self._is_paused:
            self._is_paused = True
            if self._source:
                self._source.suspend()

    def resume(self):
        """恢复录音。"""
        if self._is_recording and self._is_paused:
            self._is_paused = False
            if self._source:
                self._source.resume()

    def stop(self) -> Optional[np.ndarray]:
        """停止录音，返回完整录音数据。

        Returns:
            单声道 float64 numpy 数组（多声道时取平均混缩）
        """
        if not self._is_recording:
            if self._recorded_data:
                merged = self._get_merged_data()
                self._recorded_data = []
                self._merged_cache = None
                self._merged_count = 0
                return merged
            return None

        # 先读掉剩余数据
        self._poll_audio()

        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

        if self._source:
            self._source.stop()
            self._source = None

        self._io_device = None
        self._ring = None
        self._is_recording = False
        self._is_paused = False

        if not self._recorded_data:
            return np.array([], dtype=np.float64)

        merged = self._get_merged_data()
        self._recorded_data = []  # 释放分块列表（merged 已含全部数据）
        self._merged_cache = None
        self._merged_count = 0
        return merged

    def is_recording(self) -> bool:
        return self._is_recording and not self._is_paused

    def is_paused(self) -> bool:
        return self._is_paused

    def get_duration(self) -> float:
        """已录制时长（秒）。"""
        if self._sample_rate == 0:
            return 0.0
        return self._total_samples / self._sample_rate

    def get_recorded_data(self) -> tuple[Optional[np.ndarray], int]:
        """获取已录制的音频数据（带合并缓存，重复调用零拷贝）。

        录音过程中 _recorded_data 只做 O(1) 的 list.append；
        仅当有新 chunk 加入时才执行一次 np.concatenate 并更新缓存，
        避免每次调用都全量拼接（长录音下为 O(n²) 陷阱）。

        Returns:
            (float32 数组, 采样率)；未录音时返回 (None, sample_rate)
        """
        if not self._recorded_data:
            return None, self._sample_rate

        if self._merged_cache is None or len(self._recorded_data) != self._merged_count:
            raw = np.concatenate(self._recorded_data)
            if self._channels > 1:
                raw = raw.reshape(-1, self._channels).mean(axis=1)
            self._merged_cache = raw.astype(np.float32)
            self._merged_count = len(self._recorded_data)

        return self._merged_cache, self._sample_rate

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _poll_audio(self):
        """定时器回调：读取可用音频数据并入库。"""
        if not self._is_recording or self._is_paused:
            return
        if self._io_device is None:
            return

        try:
            data_bytes = self._io_device.readAll()
            if data_bytes is None or data_bytes.size() == 0:
                return

            # 转为 numpy float32
            raw = np.frombuffer(data_bytes.data(), dtype=np.float32)

            # 多声道时混音为单声道
            if self._channels > 1:
                raw = raw.reshape(-1, self._channels).mean(axis=1).astype(np.float32)

            # 入有界环形缓冲并累积（异常大块的溢出部分计入丢样）
            self._ingest_chunk(raw)
            self._error_count = 0

        except Exception as e:
            self._error_count = getattr(self, "_error_count", 0) + 1
            _log.error("录音读取失败(连续第%d次): %s", self._error_count, e)
            if self._error_count >= 10:
                self._is_recording = False
                try:
                    self.stop()
                except Exception as stop_err:
                    _log.error("录音自动停止失败: %s", stop_err)

    def _ingest_chunk(self, raw: np.ndarray) -> int:
        """一块采集采样入库（无音频设备可单测）。

        放入有界环形缓冲 → 取出被接受部分 → 累积并触发电平/数据回调。
        缓冲满溢（单次块超过可用容量）时多余采样计入丢样。

        Returns:
            本块丢弃的采样数。
        """
        x = np.asarray(raw, dtype=np.float32).ravel()
        if self._ring is not None:
            _accepted, dropped = self._ring.put(x)
            self._dropped_samples += int(dropped)
            accepted = self._ring.drain_all()
        else:
            # 未走 start() 的兜底：直接累积（向后兼容 / 单元测试）
            accepted = x
            dropped = 0

        if len(accepted) > 0:
            self._recorded_data.append(accepted)
            self._total_samples += len(accepted)

            if self._level_callback:
                try:
                    self._level_callback(float(np.max(np.abs(accepted))))
                except Exception as e:
                    _log.warning("电平回调失败: %s", e)

            if self._data_callback:
                try:
                    self._data_callback(accepted)
                except Exception as e:
                    _log.warning("数据回调失败: %s", e)

        return int(dropped)

    def get_dropout_seconds(self) -> float:
        """累计采集丢样时长（秒）。

        环形缓冲满溢（采集块超过 2s 可用容量）时计数；正常 16ms 轮询下
        块远小于容量，恒为 0。该护栏为异步消费/写盘预留。
        """
        sr = self._sample_rate if self._sample_rate > 0 else 44100
        return self._dropped_samples / float(sr)

    def _get_merged_data(self) -> np.ndarray:
        """合并所有录音块为一个数组。"""
        if not self._recorded_data:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._recorded_data).astype(np.float32, copy=False)
