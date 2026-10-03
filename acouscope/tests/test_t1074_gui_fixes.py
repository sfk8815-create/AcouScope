# SPDX-License-Identifier: GPL-3.0-only
"""T-1074 开发守卫测试（承 PI-T72 审计确认项 G1~G5）。

断言纪律：offscreen 全程（conftest 已 setdefault QT_QPA_PLATFORM）；构造
MainWindow 但不 .show()、无 QDialog/.exec()；G2/G5 用假 worker/假设备与
monkeypatch，绝不 spawn 真播放线程/真 ML 后端（对齐 W5.1）。

覆盖：
  G1  多轨播放错误回调经 pyqtSignal 跨线程 QueuedConnection 派发 → show_toast
      恒在主线程执行（消 T72-01 非 GUI 线程建 QWidget 的 UB）。
  G2  _shutdown_qthread：cancel→wait 超时→terminate 兜底（消 T72-04
      「QThread: Destroyed while running」）。
  G3  main_window 无裸 print（承 T72-05/06）；project._deserialize_analysis_results
      pitch_grid 损坏时保留原 dict 语义不变（承 T72-09）。
  G4  timbre.harmonic_features 以 fmin=40 实例化 PitchAnalyzer（承 T72-10）。
  G5  player._write_chunk_full：设备 isValid 预检失败 → 致命收尾返回 False
      （承 T72-03，消写死设备 ERROR 噪音）。
"""

import threading
import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

import acouscope.audio.player as player_mod
import acouscope.ui.main_window as mw
from acouscope.audio.player import AudioPlayer
from acouscope.ui.widgets.ai_interpret import _shutdown_qthread


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏主窗口（不 show()；参照 test_cb008_main_window_icons.py）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    from acouscope.app.controller import AppController

    controller = AppController()
    sr = 8000
    controller.load_from_array(np.zeros(sr, dtype=np.float64), sr)

    w = mw.MainWindow(controller)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# G1：跨线程错误回调经信号 QueuedConnection 派发 → 主线程建 toast
# ---------------------------------------------------------------------------


def test_g1_error_callback_is_signal_emit(window):
    """多轨 player 的 error_callback 应为 _mt_player_error.emit（非裸 lambda）。"""
    player = window._multitrack_player_instance()
    cb = player._error_callback
    assert cb is not None
    # emit 绑定方法：其 __self__ 即信号对象；不再是直调 show_toast 的 lambda
    assert not callable(getattr(cb, "__wrapped__", None))
    bound = getattr(cb, "__self__", None)
    assert bound is not None, "error_callback 非绑定信号 emit"


def test_g1_slot_connected_to_signal(window):
    """_mt_player_error 已连接到 _on_mt_player_error（getter 内建立，仅一次）。"""
    window._multitrack_player_instance()
    # 再次调用不应重复连接（is None 守卫）；disconnect 应成功证明连接存在
    ok = window._mt_player_error.disconnect(window._on_mt_player_error)
    assert ok is not False


def test_g1_cross_thread_emit_delivered_on_main_thread(qapp, window, monkeypatch):
    """子线程触发 error_callback → show_toast 在主线程执行（QueuedConnection）。"""
    captured = {}
    main_ident = threading.get_ident()

    def fake_toast(parent, message, level="info", duration=3500):
        captured["ident"] = threading.get_ident()
        captured["message"] = message
        captured["level"] = level

    monkeypatch.setattr(mw, "show_toast", fake_toast)

    player = window._multitrack_player_instance()
    err_cb = player._error_callback

    def emit_from_child():
        # 模拟播放 daemon 线程内 _fatal_stream_error 直调回调
        captured["emit_ident"] = threading.get_ident()
        err_cb("boom from play thread")

    t = threading.Thread(target=emit_from_child)
    t.start()
    t.join()

    # 队列投递：须在主线程事件循环里 processEvents 才送达
    deadline = time.time() + 3.0
    while "ident" not in captured and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert "ident" in captured, "主线程未收到派发的错误（连接非 queued？）"
    assert captured["emit_ident"] != main_ident, "发射确应来自子线程"
    assert captured["ident"] == main_ident, "show_toast 未在主线程执行=UB 未消除"
    assert captured["message"] == "boom from play thread"
    assert captured["level"] == "error"


# ---------------------------------------------------------------------------
# G2：_shutdown_qthread terminate 兜底（假 QThread）
# ---------------------------------------------------------------------------


class _FakeWorkerTimeout:
    """假 worker：cancel 无效、wait 恒超时 → 应触发 terminate。"""

    def __init__(self):
        self.running = True
        self.cancel_called = False
        self.terminate_called = False
        self.deleted = False
        self.wait_calls = []

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_called = True  # 模拟「请求取消但线程不理会」

    def wait(self, ms):
        self.wait_calls.append(ms)
        return False  # 超时未退

    def terminate(self):
        self.terminate_called = True
        self.running = False
        return True

    def deleteLater(self):
        self.deleted = True


class _FakeWorkerClean:
    """假 worker：cancel 后 wait 成功退出 → 不应 terminate。"""

    def __init__(self):
        self.running = True
        self.terminate_called = False

    def isRunning(self):
        return self.running

    def cancel(self):
        pass

    def wait(self, ms):
        self.running = False
        return True  # 超时前已退

    def terminate(self):
        self.terminate_called = True

    def deleteLater(self):
        pass


def test_g2_terminate_on_wait_timeout():
    """wait 超时 → terminate 被调 + deleteLater + 返回 True（兜底生效）。"""
    w = _FakeWorkerTimeout()
    ret = _shutdown_qthread(w, timeout_ms=50)
    assert w.cancel_called is True
    assert w.terminate_called is True, "超时未触发 terminate 兜底"
    assert w.deleted is True
    assert ret is True


def test_g2_no_terminate_when_worker_exits():
    """wait 成功退出 → 不 terminate、返回 False（无过度终止）。"""
    w = _FakeWorkerClean()
    ret = _shutdown_qthread(w, timeout_ms=50)
    assert w.terminate_called is False
    assert ret is False


def test_g2_none_and_not_running_are_noops():
    """None / 未在跑 → 直接 False，不触碰 terminate。"""
    assert _shutdown_qthread(None) is False

    class _Stopped:
        def isRunning(self):
            return False

        def terminate(self):
            raise AssertionError("不应 terminate 已停线程")

    assert _shutdown_qthread(_Stopped()) is False


# ---------------------------------------------------------------------------
# G3：日志纳管反证（源码级守卫）+ project 反序列化语义不变
# ---------------------------------------------------------------------------


def test_g3_no_bare_print_in_main_window():
    """main_window.py 无裸 print(（承 T72-05/06；print_exc 不在此列）。"""
    import pathlib
    import re

    mod_file = pathlib.Path(mw.__file__).resolve()
    text = mod_file.read_text(encoding="utf-8")
    hits = [
        (i + 1, ln)
        for i, ln in enumerate(text.splitlines())
        if re.search(r"[^_a-z]print\(", ln)
        and "get_logger" not in ln
        and "_log." not in ln
        and not ln.strip().startswith("#")
    ]
    assert hits == [], f"main_window 残留裸 print: {hits}"


def test_g3_project_deserialize_keeps_dict_on_corrupt():
    """pitch_grid 损坏 → 保留原 dict、不抛（T72-09 语义不变），并留日志痕。"""
    from acouscope.app import project as project_mod

    # notes 内含 PitchNote 不接受的键 → from_dict 内 PitchNote(**nt) 抛 TypeError
    bad_pg = {"notes": [{"__bogus_key__": 1}], "snap_mode": "off"}
    corrupt = {"pitch_grid": bad_pg}
    out = project_mod._deserialize_analysis_results(corrupt, source="/x/y.acouproj")
    # 未抛 + 仍是原 dict（降级保留），未被替换为 PitchGridModel
    assert isinstance(out["pitch_grid"], dict)
    assert out["pitch_grid"] is bad_pg


# ---------------------------------------------------------------------------
# G4：timbre 以 fmin=40 实例化 PitchAnalyzer（口径对齐 worker 链路）
# ---------------------------------------------------------------------------


def test_g4_timbre_harmonic_uses_fmin40(monkeypatch):
    """harmonic_features 内 PitchAnalyzer(..., fmin=40.0)，对齐 protocol fmin=40。"""
    captured = {}

    class _StubPA:
        def __init__(self, sample_rate, fmin=50.0, fmax=2000.0):
            captured["fmin"] = fmin
            captured["sample_rate"] = sample_rate

        def detect_yin(self, signal, frame_size=2048, hop_length=512):
            # 返回全零 f0 → f0_median=0 → harmonic_features 早退，避免重计算
            return np.array([0.0]), np.array([0.0])

    import acouscope.analysis.pitch as pitch_mod

    monkeypatch.setattr(pitch_mod, "PitchAnalyzer", _StubPA)

    from acouscope.analysis.timbre import TimbreAnalyzer

    ta = TimbreAnalyzer(sample_rate=44100.0)
    ta.harmonic_features(np.zeros(4096, dtype=np.float64))

    assert captured.get("fmin") == 40.0, "timbre 未显式对齐 fmin=40"


def test_g4_protocol_default_is_40():
    """口径基准：worker protocol DetectRequest 默认 fmin=40.0（G4 对齐目标）。"""
    from acouscope.analysis.worker.protocol import DetectRequest

    assert DetectRequest.__dataclass_fields__["fmin"].default == 40.0


# ---------------------------------------------------------------------------
# G5：player._write_chunk_full isValid 预检守卫
# ---------------------------------------------------------------------------


class _FakeDevice:
    """假 QIODevice：write 全部接受，返回写入字节数。"""

    def __init__(self):
        self.written = 0

    def write(self, data):
        n = len(data)
        self.written += n
        return n


def test_g5_invalid_device_triggers_fatal(monkeypatch):
    """isValid 预检失败 → 致命收尾、返回 False、不实际写（消 ERROR 噪音）。"""
    monkeypatch.setattr(player_mod, "_qt_isValid", lambda obj: False)

    p = AudioPlayer()
    p._backend = "qt"
    p._output_device = object()  # 非 None，但 isValid→False
    p._is_playing = True
    errs = []
    p.set_error_callback(errs.append)

    ret = p._write_chunk_full(np.zeros(16, dtype=np.float32))
    assert ret is False
    assert p._stop_flag.is_set(), "预检失败未置停止标志"
    assert errs == ["Qt output device deleted"]


def test_g5_valid_device_writes_and_returns_true(monkeypatch):
    """isValid→True 且设备正常 → 写满返回 True（守卫不误伤正常路径）。"""
    monkeypatch.setattr(player_mod, "_qt_isValid", lambda obj: True)

    p = AudioPlayer()
    p._backend = "qt"
    dev = _FakeDevice()
    p._output_device = dev
    p._is_playing = True

    chunk = np.zeros(16, dtype=np.float32)
    ret = p._write_chunk_full(chunk)
    assert ret is True
    assert dev.written == chunk.nbytes


def test_g5_guard_skipped_when_shiboken_absent(monkeypatch):
    """无 shiboken6（_qt_isValid=None）→ 跳过预检、走既有写路径（降级不回退）。"""
    monkeypatch.setattr(player_mod, "_qt_isValid", None)

    p = AudioPlayer()
    p._backend = "qt"
    dev = _FakeDevice()
    p._output_device = dev
    p._is_playing = True

    ret = p._write_chunk_full(np.zeros(16, dtype=np.float32))
    assert ret is True
    assert dev.written > 0
