# SPDX-License-Identifier: GPL-3.0-only
"""T-1008 M3 分析源抽象 + 逐轨分析调度回归（离屏，无主窗口显示调用）。

覆盖：
- `AnalysisSource` 持引用不复制（`id()` 断言）、多声道形状不降混、偏移时间映射；
- `resolve_source` 默认源与 controller 逐字等价（同对象/同采样率/偏移 0）、
  多轨源取轨数据引用 + T-1006 对齐偏移 + 回落语义；
- 逐轨调度：默认并发 1、完成序、取消中断、缓存命中免算、未知 kind / 单轨异常隔离、
  参数指纹分档；
- 缓存**两域隔离**：多轨键 `(track_id, kind, 参数指纹)` 与单轨键
  `(kind, fp[, t0, t1])` 形态与容器均不共用，单轨键形态零改动；
- **等价性硬门槛**：默认源下 pitch / spectrogram（另加共振峰 / 音色）结果与
  改造前取数路径 **BIT-IDENTICAL**（双路径逐位对比）；
- 六个分析入口取数**全部经 resolver**（运行时计数证明，非源码字面）；
- 静态纪律（禁词 / hex-px / QDialog / 无主窗口显示调用）。
"""

import inspect
import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QComboBox, QWidget

from acouscope.analysis import FormantAnalyzer, TimbreAnalyzer
from acouscope.analysis.pitch import detect_pyin
from acouscope.app.controller import AppController
from acouscope.dsp.stft import STFTEngine
from acouscope.i18n import set_language
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.multitrack.analysis_source import (
    CACHE_DOMAIN, DEFAULT_MAX_CONCURRENCY, AnalysisSource, TrackResultCache,
    params_fingerprint, resolve_source, run_analysis_on_tracks,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession, TrackModel

_MODULE = (
    Path(__file__).resolve().parents[1]
    / "src" / "acouscope" / "ui" / "widgets" / "multitrack" / "analysis_source.py"
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


class _FakeController:
    """最小 controller 替身（resolve_source 只读三字段）。"""

    def __init__(self, data, sr, path=None):
        self.audio_data = data
        self.sample_rate = sr
        self.current_file = path


def _tone(sr: int = 8000, seconds: float = 1.0, freq: float = 440.0):
    t = np.arange(int(sr * seconds)) / sr
    return (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _source(track_id, data=None, sr: int = 8000, offset_ms: float = 0.0):
    return AnalysisSource(
        track_id or "current", data if data is not None else _tone(sr),
        sr, align_offset_ms=offset_ms, track_id=track_id,
    )


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏 MainWindow（不 show）；一条 1s / 8kHz 单声道正弦。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    sr = 8000
    controller.load_from_array(_tone(sr, 1.0, 440.0), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def _sync_analysis(window):
    """把异步执行器替换为同步执行（不建 QThread），返回调用记录。"""
    log = []

    def _run(status_text, compute_fn, on_done, error_prefix):
        log.append(status_text)
        on_done(compute_fn())

    window._run_analysis_async = _run
    return log


def _spy_source(window):
    """给 `_analysis_source` 挂钩，返回调用计数（运行时证明取数经 resolver）。"""
    calls = []
    original = window._analysis_source

    def _spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    window._analysis_source = _spy
    return calls


def _cached(window, kind):
    for key, value in window._result_cache.items():
        if key[0] == kind:
            return value
    return None


# ---------------------------------------------------------------------------
# ① AnalysisSource：持引用 / 时间映射
# ---------------------------------------------------------------------------


def test_source_holds_reference_without_copy():
    arr = np.zeros(64, dtype=np.float32)
    src = AnalysisSource("a", arr, 8000)
    assert src.data is arr                      # 不复制 buffer
    assert src.fingerprint()[1] == 64
    assert len(src) == 64


def test_source_keeps_multichannel_shape_unchanged():
    """多声道原样透传（不降混）——与既有取数口径逐字一致，避免语义漂移。"""
    stereo = np.zeros((32, 2), dtype=np.float32)
    src = AnalysisSource("a", stereo, 8000)
    assert src.data.shape == (32, 2)
    assert src.data is stereo


def test_zero_offset_returns_times_object_unchanged():
    src = AnalysisSource("a", _tone(), 8000, align_offset_ms=0.0)
    times = np.arange(4, dtype=np.float32)
    assert src.offset_seconds == 0.0
    assert src.to_timeline(times) is times      # 单轨主态零扰动（保 dtype/身份）


def test_offset_maps_to_aligned_timeline():
    src = AnalysisSource("a", _tone(), 8000, align_offset_ms=250.0)
    times = np.arange(4, dtype=np.float32)
    mapped = src.to_timeline(times)
    assert src.offset_seconds == pytest.approx(0.25)
    assert np.array_equal(mapped, times + 0.25)
    assert mapped is not times


def test_params_fingerprint_order_insensitive():
    assert params_fingerprint({"a": 1, "b": [1, 2]}) == params_fingerprint(
        {"b": [1, 2], "a": 1}
    )
    assert params_fingerprint({"a": 1}) != params_fingerprint({"a": 2})
    assert params_fingerprint(None) == ()
    assert params_fingerprint({}) == ()


# ---------------------------------------------------------------------------
# ② resolve_source：默认源等价 / 多轨源
# ---------------------------------------------------------------------------


def test_default_source_matches_controller_object(tmp_path):
    data = _tone()
    controller = _FakeController(data, 8000, tmp_path / "sample.wav")
    src = resolve_source(controller)
    assert src.data is controller.audio_data     # 同一对象（等价性根基）
    assert src.sample_rate == controller.sample_rate
    assert src.align_offset_ms == 0.0
    assert src.track_id is None
    assert src.name == "sample"


def test_default_source_without_audio_mirrors_controller():
    controller = _FakeController(None, 8000, None)
    src = resolve_source(controller)
    assert src.data is None                      # 与 controller.audio_data 同语义
    assert src.fingerprint() == (8000, 0, 0.0)


def test_resolve_source_uses_track_reference_and_offset():
    data = _tone(8000, 0.5, 330.0)
    track = TrackModel("/tmp/track.wav", label="轨A")
    track.set_data(data, sample_rate=8000)
    session = MultitrackSession()
    session.add_track(track)
    session.set_offset_ms(track.track_id, 120.0)

    controller = _FakeController(_tone(), 8000, None)
    src = resolve_source(controller, session=session, track_id=track.track_id)
    assert src.data is data                      # 轨数据引用，不复制
    assert src.track_id == track.track_id
    assert src.align_offset_ms == 120.0
    assert src.name == "轨A"
    assert src.sample_rate == 8000


def test_resolve_source_falls_back_when_track_missing():
    controller = _FakeController(_tone(), 8000, None)
    session = MultitrackSession()
    src = resolve_source(controller, session=session, track_id="absent")
    assert src.data is controller.audio_data     # 回落默认源
    assert src.track_id is None
    assert src.align_offset_ms == 0.0


# ---------------------------------------------------------------------------
# ③ 逐轨调度
# ---------------------------------------------------------------------------


def test_serial_scheduler_completion_order_and_references():
    sources = [_source(tid) for tid in ("a", "b", "c")]
    seen = []

    def runner(src, params):
        seen.append(src.track_id)
        return src.data                          # 结果按引用返回

    handles = run_analysis_on_tracks(sources, "k", {"n": 1}, runner=runner)
    assert [h.track_id for h in handles] == ["a", "b", "c"]   # 输入序
    assert [h.seq for h in handles] == [0, 1, 2]              # 完成序
    assert seen == ["a", "b", "c"]
    assert [h.status for h in handles] == ["done"] * 3
    for handle, src in zip(handles, sources):
        assert handle.result is src.data                       # 无大数组复制


def test_scheduler_default_concurrency_is_one():
    assert DEFAULT_MAX_CONCURRENCY == 1
    default = inspect.signature(run_analysis_on_tracks).parameters["max_concurrency"]
    assert default.default == 1


def test_cancel_stops_remaining_tracks():
    sources = [_source(tid) for tid in ("a", "b", "c")]
    state = {"cancel": False}

    def runner(src, params):
        state["cancel"] = True                   # 首轨完成后请求取消
        return src.data

    handles = run_analysis_on_tracks(
        sources, "k", None, runner=runner, cancel=lambda: state["cancel"]
    )
    assert handles[0].status == "done" and handles[0].seq == 0
    assert [h.status for h in handles[1:]] == ["cancelled", "cancelled"]
    assert [h.seq for h in handles[1:]] == [-1, -1]


def test_cache_hit_marks_handle_cached_without_runner():
    src = _source("a")
    cache = TrackResultCache()
    key = TrackResultCache.key("a", "pitch", {"x": 1})
    holder = object()
    cache.put(key, holder)

    def boom(source, params):                    # 命中即免算：runner 不得被调用
        raise AssertionError("runner 不应被调用")

    handles = run_analysis_on_tracks(
        [src], "pitch", {"x": 1}, runner=boom, cache=cache
    )
    assert handles[0].status == "cached"
    assert handles[0].result is holder
    assert handles[0].seq == 0


def test_unknown_kind_yields_error_handle():
    handles = run_analysis_on_tracks([_source("a")], "no_such_kind")
    assert handles[0].status == "error"
    assert handles[0].error and "no_such_kind" in handles[0].error
    assert handles[0].ok is False


def test_runner_failure_isolated_per_track():
    sources = [_source("a"), _source("b")]

    def runner(src, params):
        if src.track_id == "b":
            raise ValueError("boom")
        return src.data

    handles = run_analysis_on_tracks(sources, "k", None, runner=runner)
    assert handles[0].status == "done" and handles[0].ok is True
    assert handles[1].status == "error"
    assert "ValueError" in handles[1].error


def test_params_change_produces_separate_cache_entries():
    src = _source("a")
    cache = TrackResultCache()
    run_analysis_on_tracks([src], "k", {"n": 1}, runner=lambda s, p: p, cache=cache)
    run_analysis_on_tracks([src], "k", {"n": 2}, runner=lambda s, p: p, cache=cache)
    assert len(cache) == 2
    assert cache.get(TrackResultCache.key("a", "k", {"n": 1})) == {"n": 1}


def test_cache_key_does_not_cross_tracks():
    cache = TrackResultCache()
    cache.put(TrackResultCache.key("a", "k", None), (1,))
    assert cache.get(TrackResultCache.key("b", "k", None)) is None
    assert cache.get(TrackResultCache.key("a", "other", None)) is None


def test_cache_domain_isolated_from_single_track_keys():
    """两域隔离禁串：多轨键 `(track_id, kind, 指纹)`；单轨键形态零改动。"""
    assert TrackResultCache.DOMAIN == CACHE_DOMAIN == "multitrack"

    mt_key = TrackResultCache.key("trk1", "pitch", None)
    assert mt_key == ("trk1", "pitch", ())

    # 单轨既有键形态（T-321/T-916）：全文件 (kind, fp) / 区间 (kind, fp, t0, t1)
    single_full = MainWindow._cache_key(object(), "pitch", (8000, 100, 1.0))
    single_region = MainWindow._cache_key(
        object(), "pitch", (8000, 100, 1.0), (0.5, 1.5)
    )
    assert single_full == ("pitch", (8000, 100, 1.0))
    assert single_region == ("pitch", (8000, 100, 1.0), 0.5, 1.5)

    cache = TrackResultCache()
    cache.put(mt_key, (1,))
    assert cache.get(single_full) is None        # 单轨键不会命中多轨域
    assert cache.get(single_region) is None
    assert cache.get(mt_key) == (1,)


def test_builtin_spectrogram_runner_returns_stft_triple():
    src = _source("a")
    handles = run_analysis_on_tracks(
        [src], "spectrogram", {"n_fft": 256, "hop_length": 64}
    )
    assert handles[0].ok is True
    freqs, times, mag_db = handles[0].result
    assert freqs.shape[0] == 129 and mag_db.shape == (129, times.size)


def test_builtin_pitch_runner_returns_continuous_f0():
    src = _source("a")
    handles = run_analysis_on_tracks([src], "pitch")
    assert handles[0].ok is True
    f0 = np.asarray(handles[0].result.f0_hz, dtype=np.float64)
    voiced = f0[f0 > 0]
    assert voiced.size > 0
    assert np.allclose(np.median(voiced), 440.0, rtol=0.02)   # 连续 Hz 值（非网格索引）


# ---------------------------------------------------------------------------
# ④ 默认源等价性（BIT-IDENTICAL 硬门槛）
# ---------------------------------------------------------------------------


def test_window_default_source_identity(window):
    src = window._analysis_source()
    assert src.data is window.controller.audio_data
    assert src.sample_rate == window.controller.sample_rate
    assert src.align_offset_ms == 0.0 and src.track_id is None


def test_pitch_entry_bit_identical(window):
    _sync_analysis(window)
    calls = _spy_source(window)
    window._on_pitch_analysis()
    assert len(calls) == 1                       # 取数经 resolver

    times, f0, _grid = _cached(window, "pitch")
    data = window.controller.audio_data
    sr = window.controller.sample_rate
    tr = detect_pyin(data, sr)
    assert times.dtype == tr.times.dtype and f0.dtype == tr.f0_hz.dtype
    assert np.array_equal(times, tr.times)       # 逐位一致
    assert np.array_equal(f0, tr.f0_hz)


def test_spectrogram_entry_bit_identical(window):
    calls = _spy_source(window)
    window._on_spectrogram_analysis()
    assert len(calls) == 1

    freqs, times, mag_db = _cached(window, "spectrogram")
    data = window.controller.audio_data
    sr = window.controller.sample_rate
    engine = STFTEngine(n_fft=2048, hop_length=512, window="hann")
    d_freqs, d_times, d_mag = engine.magnitude(data, sr, db_scale=True)
    assert freqs.dtype == d_freqs.dtype and mag_db.dtype == d_mag.dtype
    assert np.array_equal(freqs, d_freqs)
    assert np.array_equal(times, d_times)
    assert np.array_equal(mag_db, d_mag)


def test_formant_entry_bit_identical(window):
    _sync_analysis(window)
    calls = _spy_source(window)
    window._on_formant_analysis()
    assert len(calls) == 1

    times, freqs, bws = _cached(window, "formant")
    data = window.controller.audio_data
    sr = window.controller.sample_rate
    d_times, d_freqs, d_bws = FormantAnalyzer(sr).extract_lpc(
        data, frame_size=1024, hop_length=512
    )
    assert np.array_equal(times, d_times)
    assert np.array_equal(freqs, d_freqs)
    assert np.array_equal(bws, d_bws)


def test_timbre_entry_bit_identical(window):
    _sync_analysis(window)
    calls = _spy_source(window)
    window._on_timbre_analysis()
    assert len(calls) == 1

    times, mfcc, hnr_times, hnr, _features, _global = _cached(window, "timbre")
    data = window.controller.audio_data
    sr = window.controller.sample_rate
    analyzer = TimbreAnalyzer(sr)
    d_times, d_mfcc = analyzer.mfcc(data, n_mfcc=13, n_fft=2048, hop_length=512)
    d_hnr_times, d_hnr = analyzer.hnr(data, frame_size=2048, hop_length=512)
    assert np.array_equal(times, d_times) and np.array_equal(mfcc, d_mfcc)
    assert np.array_equal(hnr_times, d_hnr_times) and np.array_equal(hnr, d_hnr)


def test_fft_entry_routes_through_resolver(window):
    calls = _spy_source(window)
    window._on_fft_analysis()
    assert len(calls) == 1
    assert window._spectrum_widget is not None


class _Dummy3D(QWidget):
    """3D 画布替身（免 matplotlib 渲染；只验取数与接线）。"""

    def __init__(self):
        super().__init__()
        self.segment = (0.0, 0.0)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("dummy")
        self.audio = None

    def set_audio(self, data, sr):
        self.audio = (data, sr)

    def set_time_range(self, t0, t1):
        self.segment = (t0, t1)


def test_spectrogram3d_builder_routes_through_resolver(window, monkeypatch):
    import acouscope.ui.widgets.spectrogram3d as s3d_mod

    monkeypatch.setattr(s3d_mod, "Spectrogram3DWidget", _Dummy3D)
    calls = _spy_source(window)
    window._set_analysis_view(6)
    window._build_spectrogram3d(window._analysis_gen)
    assert len(calls) == 1
    dummy = window._spectrogram3d_widget
    assert dummy.audio[0] is window.controller.audio_data
    assert dummy.audio[1] == window.controller.sample_rate


# ---------------------------------------------------------------------------
# ⑤ 静态纪律
# ---------------------------------------------------------------------------

# 禁词：拼接构造（守卫文件自身不得含完整字面量）
_BANNED = ("M" + "elodyne", "Rea" + "per", "Sonic " + "Visualiser")


def test_new_module_has_no_banned_words():
    src = _MODULE.read_text(encoding="utf-8").lower()
    for word in _BANNED:
        assert word.lower() not in src, f"analysis_source.py 命中禁词（{word}）"


def test_new_module_has_no_hex_or_px():
    src = _MODULE.read_text(encoding="utf-8")
    assert re.search(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b", src) is None
    assert re.search(r"\b\d+\s*px\b", src) is None


def test_new_module_has_no_qdialog():
    src = _MODULE.read_text(encoding="utf-8")
    assert "QDialog" not in src


def test_guard_has_no_banned_literal_and_no_window_show():
    this = Path(__file__).read_text(encoding="utf-8").lower()
    for word in _BANNED:
        assert word.lower() not in this
    # 禁主窗口显示调用：字面量拼接构造，避免守卫文件自伤
    assert ("." + "show()") not in this
