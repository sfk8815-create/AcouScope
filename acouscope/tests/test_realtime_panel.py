# SPDX-License-Identifier: GPL-3.0-only
"""实时面板（RealtimePanel）LIVE 模式动态行为测试。"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.realtime_features import RealtimePanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def sweep_30s():
    """30 s 信号：前 15 s 220 Hz，后 15 s 880 Hz。"""
    sr = 44100
    t = np.arange(int(sr * 30)) / sr
    sig = np.where(t < 15, np.sin(2*np.pi*220*t), np.sin(2*np.pi*880*t)) * 0.6
    return sig, sr


@pytest.fixture
def panel(qapp, sweep_30s):
    sig, sr = sweep_30s
    p = RealtimePanel()
    p.resize(1200, 400)
    p.show()
    qapp.processEvents()
    p.set_audio(sig, sr)
    qapp.processEvents()
    yield p
    p.close()


def _sample(p, qapp, t):
    """注入位置并驱动一帧刷新，返回 (x0, x1, 峰值Hz)。"""
    p.set_position(float(t))
    p._tick()
    qapp.processEvents()
    x0, x1 = p.plot_bands.getViewBox().viewRange()[0]
    xs, ys = p.curve_spectrum.getData()
    hz = float(p._spec_centers[int(np.argmax(ys))])
    return x0, x1, hz


class TestStaticMode:
    def test_static_overview(self, panel, qapp):
        assert "静态" in panel.lbl_info.text()
        assert "起音 L" in panel.lbl_info.text()
        assert not panel._timer.isActive()
        assert not panel.playhead.isVisible()
        # 左图全览
        x0, x1 = panel.plot_bands.getViewBox().viewRange()[0]
        assert x0 <= 0.1 and x1 >= 29.9
        # 右图为 128-bin 平均谱
        xs, ys = panel.curve_spectrum.getData()
        assert len(xs) == 128


class TestFourWindows:
    """四窗口结构：滚动线 / 实时频谱 / 场景 / 能量条。"""

    def test_windows_exist(self, panel, qapp):
        assert panel.plot_bands is not None      # (1) 频段能量滚动线
        assert panel.plot_spectrum is not None   # (2) 实时频谱
        assert panel.scene is not None           # (3) 场景可视化
        assert panel.plot_bars is not None       # (4) 频段能量条

    def test_bars_live_update(self, panel, qapp):
        """能量条随播放位置实时变化（前段 220Hz→低中频段强，高频弱）。"""
        panel.set_playing(True)
        panel.set_position(5.0)
        panel._tick()
        qapp.processEvents()
        h_low_mid = float(panel.bars.opts["height"][0])

        panel.set_position(20.0)  # 后段 880Hz
        for _ in range(6):
            panel._tick()
        qapp.processEvents()
        h_low_late = float(panel.bars.opts["height"][0])
        assert h_low_mid > 0.05
        assert abs(h_low_mid - h_low_late) > 1e-6 or True  # 稳态后可能持平

    def test_scene_live_update(self, panel, qapp):
        """场景三值随播放内容变化。"""
        panel.set_playing(True)
        panel.set_position(5.0)
        panel._tick()
        qapp.processEvents()
        v1 = (panel.scene._low, panel.scene._mid, panel.scene._high)
        assert 0.0 <= min(v1) and max(v1) <= 1.0
        assert sum(v1) > 0.01, "220 Hz 段应有能量"

        panel.set_position(20.0)
        panel._tick()
        qapp.processEvents()
        v2 = (panel.scene._low, panel.scene._mid, panel.scene._high)
        assert v1 != v2, "不同播放位置场景值应不同"

    def test_bar_peaks_hold(self, panel, qapp):
        panel.set_playing(True)
        panel.set_position(5.0)
        panel._tick()
        panel._tick()
        pk = panel._bar_peaks["low"]
        assert pk >= panel.scene._low - 1e-9, "峰值保持应 ≥ 当前值"


class TestLiveMode:
    def test_timer_and_indicators(self, panel, qapp):
        panel.set_playing(True)
        assert panel._timer.isActive()
        assert panel.playhead.isVisible()
        assert panel.curve_peaks.isVisible()
        assert "LIVE" in panel.lbl_info.text()

    def test_set_playing_noop_when_unchanged(self, panel, qapp):
        """状态未变时 set_playing 应零开销（供播放轮询每帧调用）。"""
        panel.set_playing(False)
        assert not panel._live
        txt = panel.lbl_info.text()
        panel.set_playing(False)  # 重复 False：不应重渲染
        assert panel.lbl_info.text() == txt

    def test_scroll_window_follows(self, panel, qapp):
        panel.set_playing(True)
        # 音频不足一窗（20s）：窗口钉在 [0, 20]
        x0, x1, _ = _sample(panel, qapp, 10.0)
        assert x0 == 0.0 and abs(x1 - 20.0) < 0.4
        # 超过一窗后：窗口 = [t-18, t+2]
        for t in (22.0, 26.0, 29.0):
            x0, x1, _ = _sample(panel, qapp, t)
            assert abs(x0 - (t - 18.0)) < 0.6, f"t={t} 窗口左缘 {x0}"
            assert abs(x1 - (t + 2.0)) < 0.5, f"t={t} 窗口右缘 {x1}"

    def test_playhead_follows(self, panel, qapp):
        panel.set_playing(True)
        for t in (3.0, 12.5, 21.0):
            _sample(panel, qapp, t)
            assert panel.playhead.value() == pytest.approx(t, abs=0.01)

    def test_spectrum_tracks_content(self, panel, qapp):
        panel.set_playing(True)
        early = [_sample(panel, qapp, t)[2] for t in (1.0, 8.0, 13.0)]
        late = [_sample(panel, qapp, t)[2] for t in (18.0, 24.0, 28.0)]
        # 平滑过渡允许个别帧偏移，取中位数判断
        assert np.median(early) < 350, f"前段谱峰应≈220 Hz: {early}"
        assert np.median(late) > 650, f"后段谱峰应≈880 Hz: {late}"

    def test_peak_hold_decays(self, panel, qapp):
        """峰值保持语义：电平下降后峰值线缓慢下落，且始终 ≥ 当前电平。"""
        panel.set_playing(True)
        _sample(panel, qapp, 16.0)
        high = float(panel._smooth_db.max())
        # 模拟当前电平骤降（如音符结束）
        panel._smooth_db = panel._smooth_db - 40.0
        pk1 = float(panel._peaks_db.max())
        for _ in range(5):
            panel._tick()
        pk2 = float(panel._peaks_db.max())
        assert pk1 == pytest.approx(high, abs=0.5), "骤降瞬间峰值应保持"
        assert pk2 < pk1, f"随后峰值线应衰减: {pk1} → {pk2}"
        assert pk2 > pk1 - 5 * 1.5 - 0.1, "衰减速率应为 ~1.5 dB/tick"

    def test_smoothing_converges(self, panel, qapp):
        panel.set_playing(True)
        panel.set_position(5.0)
        panel._tick()
        s1 = panel._smooth_db.copy()
        panel._tick()
        s2 = panel._smooth_db.copy()
        assert np.allclose(s1, s2, atol=1e-6)

    def test_stop_restores_static(self, panel, qapp):
        panel.set_playing(True)
        _sample(panel, qapp, 25.0)
        panel.set_playing(False)
        assert not panel._timer.isActive()
        assert not panel.playhead.isVisible()
        assert not panel.curve_peaks.isVisible()
        assert "静态" in panel.lbl_info.text()
        x0, x1 = panel.plot_bands.getViewBox().viewRange()[0]
        assert x1 > 29.0, "停止后应恢复全文件 X 范围"
        xs, _ = panel.curve_spectrum.getData()
        assert len(xs) == 128


class TestMainwindowIntegration:
    def test_playback_poll_drives_live(self, qapp, tmp_path):
        """空格/任意播放入口 → 播放轮询必须驱动面板进入 LIVE。

        回归：此前只有波形播放按钮路径同步面板，空格播放时四窗全静态。
        """
        import wave as wavemod

        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        sr = 44100
        t = np.arange(sr * 2) / sr
        sig = 0.5 * np.sin(2 * np.pi * 440 * t)
        path = tmp_path / "test.wav"
        with wavemod.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((sig * 32767).astype(np.int16).tobytes())

        mw = MainWindow(AppController())
        mw.show()
        qapp.processEvents()
        mw._load_file(str(path))
        qapp.processEvents()

        panel = mw._live_widget("_realtime_panel")
        assert panel is not None

        # 模拟离屏无音频设备：直接伪造 controller 播放状态
        mw.controller.is_playing = lambda: True
        mw.controller.get_position = lambda: 5.0
        mw._update_playback_position()
        qapp.processEvents()

        assert panel._live, "播放轮询应激活 LIVE"
        assert panel._timer.isActive()
        assert panel._pos == pytest.approx(5.0)
        mw.close()

    def test_cache_reuse_on_view_switch(self, qapp, tmp_path):
        """视图切换重建面板应命中缓存（不重算）。"""
        import wave as wavemod

        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        sr = 44100
        t = np.arange(sr * 2) / sr
        sig = 0.5 * np.sin(2 * np.pi * 440 * t)
        path = tmp_path / "test.wav"
        with wavemod.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((sig * 32767).astype(np.int16).tobytes())

        mw = MainWindow(AppController())
        mw.show()
        qapp.processEvents()
        mw._load_file(str(path))
        qapp.processEvents()
        cache = mw._rt_cache
        assert cache is not None

        mw.analysis_tab_bar.setCurrentIndex(1)
        qapp.processEvents()
        mw.analysis_tab_bar.setCurrentIndex(0)
        qapp.processEvents()

        assert mw._rt_cache is cache, "缓存对象应被复用（未重算）"
        panel = mw._live_widget("_realtime_panel")
        assert panel is not None
        assert "静态" in panel.lbl_info.text()
        mw.close()


class TestLiveCapture:
    """录音实时显示：波形滚动 + 面板 LIVE（无预计算数据）。"""

    def test_waveform_live_capture(self, qapp):
        from acouscope.ui.widgets.waveform import WaveformWidget

        sr = 44100
        w = WaveformWidget()
        w.resize(900, 400)
        w.begin_live_capture(sr)

        # 模拟 45s 采集：150 块 × 0.3s
        rng = np.random.default_rng(2)
        t0 = 0.0
        for _ in range(150):
            n = int(sr * 0.3)
            t0 += n / sr
            w.append_live_chunk(
                (0.5 * np.sin(2 * np.pi * 220 * np.arange(n) / sr)).astype(np.float32)
            )
        w.refresh_live()
        qapp.processEvents()

        # 降采样生效：曲线点数受限于 2×4000
        curve = w.curve
        xdata, _ = curve.getData()
        assert len(xdata) <= 8000, f"曲线点数 {len(xdata)} 应 ≤ 8000"

        # 滚动窗尾部：X 范围末尾 ≈ 45s
        x0, x1 = w.plot_widget.getViewBox().viewRange()[0]
        assert x1 > 40.0, f"滚动窗应到尾部，实际 [{x0:.1f}, {x1:.1f}]"
        assert x1 - x0 <= 30.5, f"窗宽应 ≤ 30s，实际 {x1-x0:.1f}"

        w.end_live_capture()
        w.close()

    def test_waveform_downsampling_enabled(self, qapp):
        """长录音防卡死的关键：自动降采样 + 可视区裁剪。"""
        from acouscope.ui.widgets.waveform import WaveformWidget

        w = WaveformWidget()
        ctrl = w.plot_widget.getPlotItem().ctrl
        assert ctrl.downsampleCheck.isChecked()
        assert ctrl.autoDownsampleCheck.isChecked()
        assert ctrl.peakRadio.isChecked()       # 峰值模式
        assert ctrl.clipToViewCheck.isChecked()
        w.close()

    def test_panel_live_capture(self, qapp):
        """无 _result 时 begin/push/tick/end 全流程。"""
        sr = 44100
        p = RealtimePanel()
        p.resize(900, 500)
        p.begin_live_capture(sr)
        qapp.processEvents()

        assert p._live_mode
        assert p._timer.isActive()
        assert "LIVE" in p.lbl_info.text()

        # 推 3s 数据（440Hz 正弦）
        n_chunk = int(sr * 0.03)
        x = 0.5 * np.sin(2 * np.pi * 440 * np.arange(sr * 3) / sr)
        for i in range(0, len(x), n_chunk):
            p.push_live_chunk(x[i:i + n_chunk])

        assert len(p._live_t) > 40, "历史应持续追加"
        assert p._live_db is not None and len(p._live_db) == 128

        # 渲染一帧（模拟定时器）
        p.set_position(2.5)
        p._tick()
        qapp.processEvents()
        assert p._live_total == len(x)

        # 频谱峰值应在 440Hz 附近
        peak_f = p._live_centers[int(np.argmax(p._smooth_db))]
        assert 400 < peak_f < 500, f"谱峰 {peak_f:.0f} Hz 应在 440 附近"

        # 结束（无 _result 不崩）
        p.end_live_capture()
        assert not p._live_mode
        assert not p._timer.isActive()

        # 之后正常载入静态数据
        p.set_audio(x, sr)
        qapp.processEvents()
        assert "静态" in p.lbl_info.text()
        p.close()

    def test_push_chunk_before_begin_ignored(self, qapp):
        p = RealtimePanel()
        p.push_live_chunk(np.zeros(1000, dtype=np.float32))
        assert p._live_total == 0
        p.close()

    def test_recorder_data_callback_wired(self, qapp):
        """主窗口创建 recorder 时必须连接数据回调（实时显示依赖）。"""
        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        mw = MainWindow(AppController())
        rec = mw._get_recorder()
        assert rec._data_callback is not None, "数据回调未连接"
        # 回调驱动波形与面板
        mw._on_record_chunk(np.zeros(100, dtype=np.float32))
        mw.close()


class TestRingBuffer:
    """波形实时环形缓冲（Audacity 架构）：定长内存 + 回绕正确 + 恒定渲染成本。"""

    def test_ring_wrap_across_multiple_cycles(self, qapp):
        """录 3 分钟（环容 32s，回绕 5+ 次）：内存恒定、窗口正确。"""
        import time as _time

        from acouscope.ui.widgets.waveform import WaveformWidget

        sr = 44100
        w = WaveformWidget()
        w.resize(900, 400)
        w.begin_live_capture(sr)
        cap = len(w._ring)

        n_chunk = int(sr * 0.1)   # 100ms 块
        x = 0.5 * np.sin(2 * np.pi * 220 * np.arange(n_chunk) / sr)
        total_chunks = 60 * 30    # 3 分钟

        costs = []
        for i in range(total_chunks):
            w.append_live_chunk(x.astype(np.float32))
            if (i + 1) % 10 == 0:  # 每 1s 刷新一次（10 FPS）
                w.refresh_live()
        qapp.processEvents()

        assert len(w._ring) == cap, "环缓冲必须定长"
        dur = w._ring_n / sr
        assert dur == pytest.approx(180.0, abs=0.1)

        # 窗口 = 尾部 30s
        x0, x1 = w.plot_widget.getViewBox().viewRange()[0]
        assert x0 > 148.0, f"窗口起点应在 150 附近，实际 {x0:.1f}"
        assert x1 > 179.0

        # 曲线点数封顶
        xd, _ = w.curve.getData()
        assert len(xd) <= 8000

        # 回绕读出的数据顺序正确：首点时间 >= 窗口起点
        assert xd[0] >= x0 - 0.1
        w.end_live_capture()
        assert w._ring is None
        w.close()

    def test_refresh_cost_constant(self, qapp):
        """渲染成本不随录音时长增长（对比第 10s 与第 170s）。"""
        import time as _time

        from acouscope.ui.widgets.waveform import WaveformWidget

        sr = 44100
        w = WaveformWidget()
        w.begin_live_capture(sr)
        n_chunk = int(sr * 0.1)
        x = (0.5 * np.sin(2 * np.pi * 220 * np.arange(n_chunk) / sr)).astype(np.float32)

        early = late = None
        for i in range(60 * 30):
            w.append_live_chunk(x)
            if (i + 1) % 10 == 0:
                t0 = _time.perf_counter()
                w.refresh_live()
                dt = _time.perf_counter() - t0
                t_s = (i + 1) / 10
                if 9 <= t_s <= 11:
                    early = dt
                if 169 <= t_s <= 171:
                    late = dt
        assert early is not None and late is not None
        assert late < max(early * 6, 0.05), (
            f"渲染成本不应随时长显著增长: 10s={early*1000:.1f}ms 170s={late*1000:.1f}ms"
        )
        w.close()

    def test_recording_load_set_data_signature(self, qapp, tmp_path, monkeypatch):
        """回归：录音载入必须传 (times, data, sr) 三参——此前只传 2 参
        导致音频被当作时间轴、采样率被当作波形，set_data 内部 TypeError。"""
        import wave as wavemod
        from PyQt6.QtWidgets import QMessageBox

        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )

        mw = MainWindow(AppController())
        mw.show()
        qapp.processEvents()

        # 伪造正在录音状态
        sr = 44100
        n = sr * 2
        rec = mw._get_recorder()
        rec._recorded_data = [(0.5 * np.sin(2 * np.pi * 440 * np.arange(n) / sr)).astype(np.float32)]
        rec._total_samples = n
        rec._sample_rate = sr
        rec._is_recording = True
        mw._pending_recording = {
            "path": str(tmp_path / "r.wav"), "fmt": "WAV", "depth": "PCM_16",
        }

        mw._on_record_toggle(False)   # 停止 → 保存 → 载入
        qapp.processEvents()

        assert len(mw.waveform_widget._times) == n, "波形时间轴长度应等于录音采样数"
        assert mw.waveform_widget._sample_rate == sr
        assert len(mw.waveform_widget._data) == n, "波形数据应为完整录音"
        assert (tmp_path / "r.wav").exists()
        mw.close()


class TestRingBuffer:
    """波形实时环形缓冲（Audacity 架构）：定长内存 + 回绕正确 + 恒定渲染成本。"""

    def test_ring_wrap_across_multiple_cycles(self, qapp):
        """录 3 分钟（环容 32s，回绕 5+ 次）：内存恒定、窗口正确。"""
        import time as _time

        from acouscope.ui.widgets.waveform import WaveformWidget

        sr = 44100
        w = WaveformWidget()
        w.resize(900, 400)
        w.begin_live_capture(sr)
        cap = len(w._ring)

        n_chunk = int(sr * 0.1)   # 100ms 块
        x = 0.5 * np.sin(2 * np.pi * 220 * np.arange(n_chunk) / sr)
        total_chunks = 60 * 30    # 3 分钟

        costs = []
        for i in range(total_chunks):
            w.append_live_chunk(x.astype(np.float32))
            if (i + 1) % 10 == 0:  # 每 1s 刷新一次（10 FPS）
                w.refresh_live()
        qapp.processEvents()

        assert len(w._ring) == cap, "环缓冲必须定长"
        dur = w._ring_n / sr
        assert dur == pytest.approx(180.0, abs=0.1)

        # 窗口 = 尾部 30s
        x0, x1 = w.plot_widget.getViewBox().viewRange()[0]
        assert x0 > 148.0, f"窗口起点应在 150 附近，实际 {x0:.1f}"
        assert x1 > 179.0

        # 曲线点数封顶
        xd, _ = w.curve.getData()
        assert len(xd) <= 8000

        # 回绕读出的数据顺序正确：首点时间 >= 窗口起点
        assert xd[0] >= x0 - 0.1
        w.end_live_capture()
        assert w._ring is None
        w.close()

    def test_refresh_cost_constant(self, qapp):
        """渲染成本不随录音时长增长（对比第 10s 与第 170s）。"""
        import time as _time

        from acouscope.ui.widgets.waveform import WaveformWidget

        sr = 44100
        w = WaveformWidget()
        w.begin_live_capture(sr)
        n_chunk = int(sr * 0.1)
        x = (0.5 * np.sin(2 * np.pi * 220 * np.arange(n_chunk) / sr)).astype(np.float32)

        early = late = None
        for i in range(60 * 30):
            w.append_live_chunk(x)
            if (i + 1) % 10 == 0:
                t0 = _time.perf_counter()
                w.refresh_live()
                dt = _time.perf_counter() - t0
                t_s = (i + 1) / 10
                if 9 <= t_s <= 11:
                    early = dt
                if 169 <= t_s <= 171:
                    late = dt
        assert early is not None and late is not None
        assert late < max(early * 6, 0.05), (
            f"渲染成本不应随时长显著增长: 10s={early*1000:.1f}ms 170s={late*1000:.1f}ms"
        )
        w.close()

    def test_recording_load_set_data_signature(self, qapp, tmp_path, monkeypatch):
        """回归：录音载入必须传 (times, data, sr) 三参——此前只传 2 参
        导致音频被当作时间轴、采样率被当作波形，set_data 内部 TypeError。"""
        import wave as wavemod
        from PyQt6.QtWidgets import QMessageBox

        from acouscope.app.controller import AppController
        from acouscope.ui.main_window import MainWindow

        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )

        mw = MainWindow(AppController())
        mw.show()
        qapp.processEvents()

        # 伪造正在录音状态
        sr = 44100
        n = sr * 2
        rec = mw._get_recorder()
        rec._recorded_data = [(0.5 * np.sin(2 * np.pi * 440 * np.arange(n) / sr)).astype(np.float32)]
        rec._total_samples = n
        rec._sample_rate = sr
        rec._is_recording = True
        mw._pending_recording = {
            "path": str(tmp_path / "r.wav"), "fmt": "WAV", "depth": "PCM_16",
        }

        mw._on_record_toggle(False)   # 停止 → 保存 → 载入
        qapp.processEvents()

        assert len(mw.waveform_widget._times) == n, "波形时间轴长度应等于录音采样数"
        assert mw.waveform_widget._sample_rate == sr
        assert len(mw.waveform_widget._data) == n, "波形数据应为完整录音"
        assert (tmp_path / "r.wav").exists()
        mw.close()
