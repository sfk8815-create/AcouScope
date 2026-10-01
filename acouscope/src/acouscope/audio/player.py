# SPDX-License-Identifier: GPL-3.0-only
"""音频播放控制模块。

双后端设计：
- 优先使用 QtMultimedia 的 QAudioSink（PyQt6 内置，无需额外依赖）
- 回退到 pyaudio（如果已安装）

修复要点：
- QAudioSink 使用默认设备显式构造
- 正确处理部分写入（QIODevice.write 可能返回少于请求的字节数）
- 使用 bytesFree() 检查缓冲区空间，避免丢样
- 播放线程使用精确计时控制写入速度
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from acouscope.utils.log import get_logger

_log = get_logger("audio.player")

# T-1074 G5（承 T72-03）：写 QIODevice 前用 shiboken6.isValid 预检 C++ 对象是否
# 仍存活，把已知「关窗竞态→写已删设备」从反复 ERROR 降级为一次性 debug；缺
# shiboken6 时优雅降级 None（跳过预检，仍由既有 except 兜底，语义不回退）。
try:
    from shiboken6 import isValid as _qt_isValid
except ImportError:  # pragma: no cover - 环境无 shiboken6 时的降级
    _qt_isValid = None


class AudioPlayer:
    """音频播放器。

    支持播放、暂停、停止、定位、变速播放、循环区域。
    优先使用 QAudioSink（Qt 内置），pyaudio 作为后备。
    """

    def __init__(self):
        self._backend = None  # "qt" / "pyaudio" / None
        self._audio_sink = None  # QAudioSink
        self._output_device = None  # QIODevice
        self._pyaudio = None
        self._stream = None

        # 音频数据
        self._data: Optional[np.ndarray] = None
        self._sample_rate: int = 44100

        # 播放状态
        self._is_playing = False
        self._is_paused = False
        self._position: int = 0  # 当前位置（采样点）
        self._lock = threading.Lock()

        # 循环播放区域（采样点，None 表示不循环）
        self._loop_start: Optional[int] = None
        self._loop_end: Optional[int] = None
        self._loop_enabled: bool = False

        # 播放速率
        self._playback_rate: float = 1.0

        # 回调线程
        self._play_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

        # 音量 (0.0 - 1.0)
        self._volume: float = 1.0

        # 电平回调（用于 VU 表）
        self._level_callback: Optional[callable] = None

        # 错误回调（用于 UI 提示）
        self._error_callback: Optional[callable] = None

    def set_level_callback(self, callback):
        """设置实时电平回调。"""
        self._level_callback = callback

    def set_error_callback(self, callback):
        """设置播放错误回调（用于 UI 提示）。"""
        self._error_callback = callback

    def _init_backend(self) -> bool:
        """初始化音频后端。优先 Qt，回退 pyaudio。"""
        if self._backend is not None:
            return self._backend != "none"

        # 尝试 QtMultimedia
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            # 验证有可用设备
            devices = QMediaDevices.audioOutputs()
            if devices:
                self._backend = "qt"
                return True
        except ImportError:
            pass

        # 尝试 pyaudio
        try:
            import pyaudio
            self._pyaudio = pyaudio.PyAudio()
            self._backend = "pyaudio"
            return True
        except ImportError:
            pass

        self._backend = "none"
        return False

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def load(self, data: np.ndarray, sample_rate: int) -> None:
        """加载音频数据。

        Args:
            data: 音频数据（单声道 float64）
            sample_rate: 采样率
        """
        self.stop()

        with self._lock:
            # 已是 float32 时零复制
            self._data = np.asarray(data, dtype=np.float32)
            self._sample_rate = sample_rate
            self._position = 0

    # ------------------------------------------------------------------
    # 播放控制
    # ------------------------------------------------------------------

    def play(self) -> None:
        """开始播放。"""
        if self._data is None:
            return

        if not self._init_backend():
            return

        if self._is_paused:
            self._is_paused = False
            self._is_playing = True
            return

        if self._is_playing:
            return

        self._is_playing = True
        self._is_paused = False
        self._stop_flag.clear()
        self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self._play_thread.start()

    def pause(self) -> None:
        """暂停播放。"""
        if self._is_playing and not self._is_paused:
            self._is_paused = True

    def stop(self) -> None:
        """停止播放。"""
        self._stop_flag.set()
        self._is_playing = False
        self._is_paused = False

        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=2.0)

        self._position = 0
        self._close_stream()

        # 回调电平归零
        if self._level_callback:
            try:
                self._level_callback(0.0)
            except Exception as e:
                _log.warning("stop: 电平回调失败: %s", e)

    def toggle(self) -> bool:
        """切换播放/暂停。返回是否正在播放。"""
        if self._is_playing and not self._is_paused:
            self.pause()
            return False
        else:
            self.play()
            return True

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def is_playing(self) -> bool:
        return self._is_playing and not self._is_paused

    def is_paused(self) -> bool:
        return self._is_paused

    def get_position(self) -> float:
        if self._sample_rate == 0 or self._data is None:
            return 0.0
        return self._position / self._sample_rate

    def set_position(self, seconds: float) -> None:
        if self._data is None:
            return
        pos = int(seconds * self._sample_rate)
        pos = max(0, min(pos, len(self._data) - 1))
        with self._lock:
            self._position = pos

    def get_duration(self) -> float:
        if self._data is None or self._sample_rate == 0:
            return 0.0
        return len(self._data) / self._sample_rate

    # ------------------------------------------------------------------
    # 循环播放
    # ------------------------------------------------------------------

    def set_loop(self, start_sec: Optional[float], end_sec: Optional[float]) -> None:
        with self._lock:
            if start_sec is None or end_sec is None or end_sec <= start_sec:
                self._loop_start = None
                self._loop_end = None
                self._loop_enabled = False
                return
            self._loop_start = int(start_sec * self._sample_rate)
            self._loop_end = int(end_sec * self._sample_rate)
            if self._data is not None:
                self._loop_start = max(0, min(self._loop_start, len(self._data)))
                self._loop_end = max(0, min(self._loop_end, len(self._data)))

    def set_loop_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._loop_enabled = enabled and self._loop_start is not None

    def is_loop_enabled(self) -> bool:
        return self._loop_enabled and self._loop_start is not None

    def get_loop_region(self) -> tuple[Optional[float], Optional[float]]:
        if self._loop_start is None:
            return None, None
        return self._loop_start / self._sample_rate, self._loop_end / self._sample_rate

    # ------------------------------------------------------------------
    # 播放速率
    # ------------------------------------------------------------------

    def set_rate(self, rate: float) -> None:
        rate = max(0.25, min(rate, 4.0))
        with self._lock:
            self._playback_rate = rate

    def get_rate(self) -> float:
        return self._playback_rate

    def _resample_chunk(self, data: np.ndarray, target_length: int) -> np.ndarray:
        """用线性插值重采样音频块。"""
        import os as _os
        if _os.environ.get("ACOUSCOPE_NATIVE", "0") == "1":
            try:
                import acouscope_core as _core

                return _core.resample_chunk_native(
                    data.astype(np.float64), target_length
                ).astype(data.dtype)
            except ImportError:
                pass  # 缺 .so：静默降级下方 numpy 插值（只吞 ImportError）
        if len(data) == target_length:
            return data
        if len(data) == 0 or target_length == 0:
            return np.zeros(target_length, dtype=data.dtype)
        x_orig = np.arange(len(data))
        x_new = np.linspace(0, len(data) - 1, target_length)
        return np.interp(x_new, x_orig, data).astype(data.dtype)

    # ------------------------------------------------------------------
    # 内部播放循环
    # ------------------------------------------------------------------

    def _play_loop(self) -> None:
        """播放线程主循环。"""
        if not self._open_stream():
            self._is_playing = False
            return

        # 大块写入（46ms @44.1kHz）+ 预充缓冲：给 UI 线程留出 GIL 竞争
        # 余量，避免缓冲欠载产生爆音
        chunk_size = 2048
        chunk_duration = chunk_size / self._sample_rate

        try:
            # 预充 ~140ms 缓冲（不节流）
            for _ in range(3):
                if self._stop_flag.is_set() or not self._is_playing or self._is_paused:
                    break
                if not self._write_next_chunk(chunk_size, 1.0):
                    break

            while not self._stop_flag.is_set() and self._is_playing:
                if self._is_paused:
                    time.sleep(0.02)
                    continue

                if not self._write_next_chunk(chunk_size, self._playback_rate):
                    break

                # 节流：略小于块时长，write() 满时自然阻塞
                time.sleep(chunk_duration * 0.85)

        except Exception as e:
            _log.error("播放线程异常退出: %s", e, exc_info=True)
            if self._error_callback:
                try:
                    self._error_callback(str(e))
                except Exception as cb_err:
                    _log.error("播放错误回调执行失败: %s", cb_err)
        finally:
            # 自然播完：等缓冲排空再关流，避免截断尾部产生爆音
            if not self._stop_flag.is_set():
                time.sleep(min(0.35, 3 * chunk_duration + 0.05))
            self._close_stream()
            self._is_playing = False
            self._is_paused = False

    def _write_next_chunk(self, chunk_size: int, rate: float) -> bool:
        """读取并写入下一音频块。返回 False 表示数据耗尽或致命写入错误。"""
        with self._lock:
            pos = self._position
            data = self._data

        if data is None:
            return False

        # 消耗方向：rate>1（快放）每输出块消耗更多源样本，rate<1（慢放）更少。
        # 曾误写 chunk_size / rate 导致速率倒挂（0.5x 反而 2x 快放），真机发现后修正。
        n_read = max(1, int(chunk_size * rate)) if rate > 0 else chunk_size
        end = min(pos + n_read, len(data))
        chunk = data[pos:end]

        if len(chunk) == 0:
            return False

        if rate != 1.0:
            output_chunk = self._resample_chunk(chunk, chunk_size)
        else:
            output_chunk = chunk
            if len(output_chunk) < chunk_size:
                output_chunk = np.pad(
                    output_chunk, (0, chunk_size - len(output_chunk))
                )

        if self._backend == "pyaudio" and self._volume != 1.0:
            output_chunk = output_chunk * self._volume

        if self._level_callback:
            try:
                peak = float(np.max(np.abs(output_chunk)))
                self._level_callback(peak)
            except Exception as e:
                _log.warning("电平回调失败: %s", e)

        if not self._write_chunk_full(output_chunk):
            # 致命流错误（输出设备已销毁）：立即返回 False，让播放循环退出
            return False

        with self._lock:
            self._position = end

        if self._loop_enabled and self._loop_start is not None and self._loop_end is not None:
            if end >= self._loop_end:
                with self._lock:
                    self._position = self._loop_start
                return True

        return end < len(data)

    # ------------------------------------------------------------------
    # 后端：流操作
    # ------------------------------------------------------------------

    def _open_stream(self) -> bool:
        """打开音频输出流。"""
        if self._backend == "qt":
            return self._open_qt_stream()
        elif self._backend == "pyaudio":
            return self._open_pyaudio_stream()
        return False

    def _open_qt_stream(self) -> bool:
        try:
            from PyQt6.QtMultimedia import QAudioSink, QAudioFormat, QMediaDevices

            fmt = QAudioFormat()
            fmt.setSampleRate(self._sample_rate)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)

            # 使用默认输出设备
            devices = QMediaDevices.audioOutputs()
            if not devices:
                return False

            default_device = QMediaDevices.defaultAudioOutput()
            self._audio_sink = QAudioSink(default_device, fmt)
            # 显式 300ms 缓冲：抗 UI 线程 GIL 竞争导致的欠载爆音
            self._audio_sink.setBufferSize(int(self._sample_rate * 0.3 * 4))
            self._audio_sink.setVolume(self._volume)
            self._output_device = self._audio_sink.start()
            return self._output_device is not None
        except Exception as e:
            _log.error("Qt 音频输出流打开失败: %s", e, exc_info=True)
            return False

    def _open_pyaudio_stream(self) -> bool:
        try:
            stream = self._pyaudio.open(
                format=self._pyaudio.paFloat32,
                channels=1,
                rate=self._sample_rate,
                output=True,
                frames_per_buffer=512,
            )
            self._stream = stream
            return True
        except Exception as e:
            # 设备打开失败是关键错误（设备被占用/拔出/驱动异常），必须上报
            _log.error("pyaudio 输出流打开失败: %s", e, exc_info=True)
            return False

    def _write_chunk_full(self, chunk: np.ndarray) -> bool:
        """写入完整音频块（确保所有数据都写入设备）。

        返回 True=写入成功；False=致命流错误（Qt 输出设备已销毁/断开），
        此时已置停止标志，调用方必须让播放循环退出。
        """
        if self._backend == "qt" and self._output_device is not None:
            audio_bytes = chunk.astype(np.float32).tobytes()
            total_written = 0
            data_len = len(audio_bytes)

            while total_written < data_len:
                if self._stop_flag.is_set() or not self._is_playing:
                    break

                # T-1074 G5（承 T72-03）：写前预检 QIODevice C++ 对象是否仍存活。
                # 关窗/stop 竞态下设备可能已被 deleteLater 回收；直接写会抛
                # RuntimeError 记 ERROR（09-08 曾同源刷屏 14 条）。预检命中即走
                # 致命收尾、记一次性 debug，消噪；既有 except 仍作 TOCTOU 兜底。
                dev = self._output_device
                if dev is None or (_qt_isValid is not None and not _qt_isValid(dev)):
                    _log.debug("Qt 输出设备已回收，播放线程收尾（关窗竞态，非故障）")
                    self._fatal_stream_error("Qt output device deleted")
                    return False

                try:
                    written = self._output_device.write(audio_bytes[total_written:])
                    if written <= 0:
                        # 缓冲区满，等待一小段时间
                        time.sleep(0.005)
                        continue
                    total_written += written
                except (OSError, RuntimeError) as e:
                    # 致命流错误（QIODevice 已被 stop/_close_stream 销毁）：
                    # 立即停止播放线程并上报，避免反复写死设备产生持续爆音
                    _log.error("Qt 设备写入失败: %s", e)
                    self._fatal_stream_error(str(e))
                    return False
                except AttributeError as e:
                    # 对象已销毁（关窗竞态）：同样视为流已死，停止播放线程
                    _log.warning("Qt 设备写入时对象不可用: %s", e)
                    self._fatal_stream_error(str(e))
                    return False

            return True

        elif self._backend == "pyaudio" and self._stream is not None:
            try:
                self._stream.write(chunk.astype(np.float32).tobytes())
            except (OSError, RuntimeError) as e:
                # 设备级错误（断开/驱动异常）：上报（保持既有语义，不中断播放线程）
                _log.error("pyaudio 写入失败: %s", e)
            except Exception as e:
                # 其他异常（如流已关闭）：降级处理
                _log.warning("pyaudio 写入异常: %s", e)

        return True

    def _fatal_stream_error(self, message: str) -> None:
        """致命流错误统一收尾：置停止标志 + 上报错误回调。"""
        self._stop_flag.set()
        self._is_playing = False
        if self._error_callback:
            try:
                self._error_callback(message)
            except Exception as cb_err:
                _log.error("播放错误回调执行失败: %s", cb_err)

    def _close_stream(self):
        """关闭音频流。"""
        if self._backend == "qt":
            try:
                if self._audio_sink is not None:
                    self._audio_sink.stop()
                    self._audio_sink = None
                self._output_device = None
            except Exception as e:
                _log.warning("Qt 音频流关闭失败: %s", e)
        elif self._backend == "pyaudio":
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception as e:
                    _log.warning("pyaudio 流关闭失败: %s", e)
                self._stream = None

    def __del__(self):
        # 解释器关闭阶段禁止 join：只发停止信号并关流，避免死锁
        self._stop_flag.set()
        try:
            self._close_stream()
        except Exception as e:
            _log.warning("__del__ 清理失败: %s", e)
        if self._pyaudio is not None and self._pyaudio is not False:
            try:
                self._pyaudio.terminate()
            except Exception as e:
                _log.warning("pyaudio 终止失败: %s", e)
