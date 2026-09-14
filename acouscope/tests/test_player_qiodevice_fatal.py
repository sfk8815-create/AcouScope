# SPDX-License-Identifier: GPL-3.0-only
"""T-p002：播放器写已销毁 QIODevice 时立即停止（消除持续爆音回归）。

病征背景：波形窗口左键点按 seek 触发 stop()→_close_stream() 销毁 QIODevice，
若播放线程正卡在满缓冲 sleep 循环，join 超时后苏醒再 write 悬垂设备 →
RuntimeError("wrapped C/C++ object of type QIODevice has been deleted")。
旧代码只 log+break 不置停止标志，_write_next_chunk 仍返回 True →
_play_loop 每块重试写死设备 = 持续「呲呲呲」爆音 + 终端报错成簇。

修复契约（audio/player.py）：
- _write_chunk_full 返回 bool（False=致命流错误，已置 _stop_flag/_is_playing=False
  并调 _error_callback）；
- _write_next_chunk 感知 False → 返回 False 让播放循环退出。

测试方式：mock 替换 _output_device（PyQt6 sip 限制下不必真 QIODevice），
离屏可跑，不构造 MainWindow。
"""

import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest


def _make_player(seconds: float = 1.0, sample_rate: int = 44100) -> "object":
    from acouscope.audio.player import AudioPlayer

    p = AudioPlayer()
    p.load(np.zeros(int(seconds * sample_rate), dtype=np.float32), sample_rate)
    p._backend = "qt"
    # load() 内部调 stop() 会置 _stop_flag/_is_playing=False，
    # 使 _write_chunk_full 的 while 首行直接 break（write 不发生）；
    # 此处恢复"可播放"态，模拟 _play_loop 运行中的上下文。
    p._stop_flag.clear()
    p._is_playing = True
    return p


def _dead_device(exc: Exception) -> MagicMock:
    """构造 write() 恒抛指定异常的 mock 输出设备。"""
    dev = MagicMock(name="QIODevice")
    dev.write.side_effect = exc
    return dev


class TestWriteNextChunkFatal:
    """_write_next_chunk 对致命写入失败的感知。"""

    def test_runtime_error_returns_false_and_stops(self):
        """① 写入抛 RuntimeError（QIODevice 已销毁）→ 返回 False + 停止标志。"""
        p = _make_player()
        dev = _dead_device(RuntimeError(
            "wrapped C/C++ object of type QIODevice has been deleted"))
        p._output_device = dev

        assert p._write_next_chunk(2048, 1.0) is False
        assert p._is_playing is False
        assert p._stop_flag.is_set()

    def test_no_retry_after_fatal_error(self):
        """② 致命错误后连续调用不产生第二次写入尝试（write 计数恒为 1）。

        真实 _play_loop 中 _stop_flag set 后 while 条件先退出、不会二次调用；
        此处直接连调验证"即使被再调也不写死设备"。
        """
        p = _make_player()
        dev = _dead_device(RuntimeError("QIODevice has been deleted"))
        p._output_device = dev

        assert p._write_next_chunk(2048, 1.0) is False
        for _ in range(2):
            p._write_next_chunk(2048, 1.0)
        assert dev.write.call_count == 1

    def test_attribute_error_object_deleted_stops(self):
        """对象已销毁（AttributeError，_close_stream 置 None 竞态）同样停止。"""
        p = _make_player()
        dev = _dead_device(AttributeError(
            "wrapped C/C++ object of type QIODevice has been deleted"))
        p._output_device = dev

        assert p._write_next_chunk(2048, 1.0) is False
        assert p._is_playing is False
        assert p._stop_flag.is_set()
        assert dev.write.call_count == 1

    def test_error_callback_invoked_on_fatal(self):
        """致命错误须调 _error_callback 上报（参照 _play_loop 既有回调用法）。"""
        p = _make_player()
        errors: list[str] = []
        p.set_error_callback(errors.append)
        dev = _dead_device(RuntimeError("QIODevice has been deleted"))
        p._output_device = dev

        p._write_next_chunk(2048, 1.0)
        assert len(errors) == 1
        assert "deleted" in errors[0]

    def test_normal_write_returns_true(self):
        """回归护栏：写入成功时语义不变（返回 True、不置停止标志）。"""
        p = _make_player()
        dev = MagicMock(name="QIODevice")
        dev.write.side_effect = lambda b: len(b)  # 全量写入
        p._output_device = dev

        assert p._write_next_chunk(2048, 1.0) is True
        assert p._stop_flag.is_set() is False
        assert dev.write.call_count == 1


class TestPlayLoopStopsOnDeadDevice:
    """整链路：_play_loop 遇死设备退出，不再反复重试。"""

    def test_play_loop_exits_without_retry(self):
        p = _make_player()
        dev = _dead_device(RuntimeError("QIODevice has been deleted"))
        p._output_device = dev
        p._open_stream = lambda: True  # 影子方法：跳过真实 QAudioSink 打开
        p._stop_flag.clear()
        p._is_playing = True

        t = threading.Thread(target=p._play_loop, daemon=True)
        t.start()
        t.join(timeout=5.0)

        assert not t.is_alive(), "播放线程未退出"
        assert p._is_playing is False
        # 预充首次写入失败即停（旧代码会继续循环重试写死设备）
        assert dev.write.call_count == 1
        time.sleep(0.2)  # 观察窗口：确认无迟到的重试写入
        assert dev.write.call_count == 1
