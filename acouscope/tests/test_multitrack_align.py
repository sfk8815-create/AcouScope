# SPDX-License-Identifier: GPL-3.0-only
"""T-1006 M2 多轨开头对齐回归：起点检测引擎 + 偏移合成 + 微调交互（全离屏）。

覆盖：合成信号起点（300ms 容差）、门限边界、min_speech 防瞬态、全静默/空输入防御、
检测只读（输入逐位不变）、多轨偏移表（默认最早发声轨 / 显式参考轨 / 未检出跳过）、
**音频数据零改动（前后逐位一致 + 同一对象）**、自动对齐幂等重跑、
轨道头 ±1ms/±10ms 微调与对齐状态、微调即时驱动共享时间轴、i18n 三语键、静态纪律。

★ T-1087 M6（项目负责人裁·扩授权改测）：``auto_align`` 由同步执行改经任务中心
fire-and-forget，返回值随之从 ``AlignResult`` 变投递句柄 ⇒ 本档对返回值的
两处断言（原 :277/:339）改「假 reporter 驱动到终态 → 从 ``align_result()``
再断」；**偏移/总时长/轨道头反映等原判据逐条保留**（真异步面另由
``test_multitrack_align_t1087.py`` 以主窗 + 真任务中心覆盖）。
"""

import pathlib
import re
import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.i18n import tr
from acouscope.ui.widgets.multitrack import align as align_mod
from acouscope.ui.widgets.multitrack.align import (
    DEFAULT_GATE_DB, DEFAULT_MIN_SPEECH_MS, NUDGE_COARSE_MS, NUDGE_FINE_MS,
    OFFSET_MAX_MS, OFFSET_MIN_MS, compute_offsets, detect_onset_ms, frame_db_curve,
    first_speech_frame, nudge_offset_ms, clamp_offset_ms, align_session,
)
from acouscope.ui.widgets.multitrack.track_header import TrackHeader
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "acouscope" / "ui" / "widgets" / "multitrack" / "align.py"
)
_ALIGN_KEYS = (
    "multitrack.align.tip", "multitrack.align.done", "multitrack.align.skipped",
    "multitrack.align.all_none", "multitrack.align.no_tracks",
    "multitrack.align.none", "multitrack.align.onset",
    "multitrack.tt.offset_coarse", "multitrack.tt.align",
)

SR = 8000
TONE_AMP = 0.5          # ≈ -9 dBFS（远高于默认门限）
TONE_WEAK = 0.01        # ≈ -43 dBFS（低于默认门限）


def _tone(n: int, sr: int = SR, amp: float = TONE_AMP, freq: float = 440.0):
    t = np.arange(int(n), dtype=np.float64) / float(sr)
    return amp * np.sin(2.0 * np.pi * freq * t)


def _clip(onset_s: float, dur_s: float, sr: int = SR, amp: float = TONE_AMP):
    """前导静音 onset_s 秒 + 纯音 dur_s 秒（合成信号，自足可复现）。"""
    return np.concatenate([
        np.zeros(int(round(sr * onset_s)), dtype=np.float64),
        _tone(int(round(sr * dur_s)), sr, amp=amp),
    ])


def _session(onsets: dict, *, sr: int = SR, dur: float = 1.0):
    """按 {path: 前导静音秒} 构造会话（stub 读取器，零 IO）。"""
    table = {path: _clip(onset, dur, sr) for path, onset in onsets.items()}
    frames = len(next(iter(table.values()))) if table else int(round(sr * dur))
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": sr, "channels": 1,
                                   "duration": len(table[str(p)]) / float(sr)},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, frames / float(sr), points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (table[str(p)], sr),
    )
    tracks = {p: session.add_path(p, label=p.rsplit("/", 1)[-1]) for p in onsets}
    return session, table, tracks


# ---------------------------------------------------------------------------
# 检测引擎（纯逻辑）
# ---------------------------------------------------------------------------


def test_detect_onset_synthetic_300ms_leading_silence():
    x = _clip(0.3, 1.0)
    assert detect_onset_ms(x, SR) == pytest.approx(300, abs=2 * 10)   # ±2 帧（10ms/帧）
    assert frame_db_curve(x, SR)[1].max() > DEFAULT_GATE_DB


def test_detect_onset_gate_boundary_and_speech_duration():
    assert detect_onset_ms(_tone(SR, amp=TONE_WEAK), SR) is None      # 低于门限 → 无起点
    assert detect_onset_ms(_tone(SR), SR) == 0                        # 起点即 0
    y = np.concatenate([_tone(int(SR * 0.01)), np.zeros(int(SR * 0.49)), _tone(SR)])
    assert detect_onset_ms(y, SR) == pytest.approx(500, abs=10)       # 单帧瞬态被 min_speech 挡掉
    assert detect_onset_ms(y, SR, min_speech_ms=10) == 0              # 放宽后瞬态即算起点


def test_detect_onset_defensive_cases_do_not_raise():
    assert detect_onset_ms(np.zeros(0), SR) is None                   # 空输入
    assert detect_onset_ms(np.zeros(SR), SR) is None                  # 全静默
    assert detect_onset_ms(np.ones(3), SR) is None                    # 短于 1 帧
    assert detect_onset_ms(_clip(0.3, 1.0), 0) is None                # 采样率非法
    assert first_speech_frame(np.zeros(0)) is None


def test_detect_onset_stereo_uses_loudest_channel():
    silent = np.zeros(int(SR * 0.5))
    stereo = np.column_stack([
        np.concatenate([silent, np.zeros(int(SR * 0.5))]),
        np.concatenate([silent, _tone(int(SR * 0.5))]),
    ])
    assert detect_onset_ms(stereo, SR) == pytest.approx(500, abs=10)


def test_detect_onset_does_not_modify_input():
    x = _clip(0.3, 0.5).astype(np.float32)
    snapshot = x.copy()
    detect_onset_ms(x, SR)
    assert x.dtype == np.float32
    assert np.array_equal(x, snapshot)                                # 逐位一致（无损红线）
    db = frame_db_curve(x, SR)[1]
    assert db.size > 0


def test_frame_db_curve_reuses_temporal_rms_db():
    x = _clip(0.1, 0.4)
    times, db = frame_db_curve(x, SR)
    from acouscope.analysis.temporal import TemporalAnalyzer

    ref_times, ref_db = TemporalAnalyzer(SR).rms_db(
        x, frame_size=int(SR * align_mod.HOP_MS / 1000.0),
        hop_size=int(SR * align_mod.HOP_MS / 1000.0),
    )
    assert np.allclose(times, ref_times)
    assert np.allclose(db, ref_db)                                    # 复用现成 rms_db，无第二套口径
    src = _SRC.read_text(encoding="utf-8")
    assert "TemporalAnalyzer" in src and "detect_leading_silence" not in src


def test_detect_onset_long_recording_scales_linearly():
    x = _clip(0.5, 600.0)                                             # 约 10 分钟
    start = time.perf_counter()
    onset = detect_onset_ms(x, SR)
    elapsed = time.perf_counter() - start
    assert onset == pytest.approx(500, abs=10)
    assert elapsed < 5.0                                              # O(n) 单次扫描（非逐样本循环）


def test_compute_offsets_reference_rules():
    onsets = {"a": 500, "b": 200, "c": None}
    result = compute_offsets(onsets, ["a", "b", "c"])
    assert result.reference_id == "b"                                 # 默认最早发声轨
    assert result.offsets == {"a": -300.0, "b": 0.0}
    assert result.skipped == ["c"] and result.applied == 2

    explicit = compute_offsets(onsets, ["a", "b", "c"], reference_id="a")
    assert explicit.reference_id == "a"
    assert explicit.offsets == {"a": 0.0, "b": 300.0}

    none = compute_offsets({"a": None, "b": None}, ["a", "b"])
    assert none.reference_id is None and none.offsets == {} and none.skipped == ["a", "b"]
    assert none.applied == 0


def test_nudge_and_clamp_bounds():
    assert nudge_offset_ms(0.0, NUDGE_FINE_MS) == pytest.approx(1.0)
    assert nudge_offset_ms(-5.0, -NUDGE_COARSE_MS) == pytest.approx(-15.0)
    assert clamp_offset_ms(1e9) == OFFSET_MAX_MS
    assert clamp_offset_ms(-1e9) == OFFSET_MIN_MS


# ---------------------------------------------------------------------------
# 会话编排（多轨偏移 + 无损红线）
# ---------------------------------------------------------------------------


def test_align_session_offsets_and_audio_bitwise_unchanged():
    session, table, tracks = _session({"/tmp/a.wav": 0.30, "/tmp/b.wav": 0.0})
    before = {p: arr.copy() for p, arr in table.items()}
    for track in tracks.values():
        track.load_full()                                              # 预载：对齐前已有驻留样本
    refs = {p: t.data for p, t in tracks.items()}

    result = align_session(session)
    assert result.reference_id == tracks["/tmp/b.wav"].track_id        # 最早发声轨（0ms）
    assert session.get(tracks["/tmp/a.wav"].track_id).offset_ms == pytest.approx(-300)
    assert session.get(tracks["/tmp/b.wav"].track_id).offset_ms == pytest.approx(0)

    for path, arr in table.items():                                    # 音频数据零改动
        assert np.array_equal(arr, before[path])
    for path, track in tracks.items():
        assert track.data is refs[path]                                # 同一对象（未重绑定/未复制）


def test_align_session_idempotent_rerun():
    session, table, tracks = _session({"/tmp/a.wav": 0.30, "/tmp/b.wav": 0.12})
    first = align_session(session)
    snapshot = {p: arr.copy() for p, arr in table.items()}
    offsets_first = {t.track_id: t.offset_ms for t in session.tracks()}

    second = align_session(session)
    assert second.offsets == first.offsets                             # 幂等覆盖
    assert {t.track_id: t.offset_ms for t in session.tracks()} == offsets_first
    for path, arr in table.items():
        assert np.array_equal(arr, snapshot[path])


def test_align_session_skips_silent_track_keeps_offset():
    session, _table, tracks = _session({"/tmp/a.wav": 0.25, "/tmp/silent.wav": 0.05})
    silent_id = tracks["/tmp/silent.wav"].track_id
    session.set_offset_ms(silent_id, 123.0)                            # 用户既有偏移
    session.get(silent_id).load_full()
    session.get(silent_id).set_data(np.zeros(SR))                      # 全静默轨

    result = align_session(session)
    assert silent_id in result.skipped and result.onsets[silent_id] is None
    assert session.get(silent_id).offset_ms == pytest.approx(123.0)     # 未检出 → 不动既有偏移
    assert session.get(tracks["/tmp/a.wav"].track_id).offset_ms == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 轨道头微调交互
# ---------------------------------------------------------------------------


def _header(track):
    return TrackHeader(track, index=0)


def test_header_offset_nudge_controls_and_emit(qapp):
    session, _table, tracks = _session({"/tmp/a.wav": 0.0})
    track = session.get(tracks["/tmp/a.wav"].track_id)
    header = _header(track)
    seen = []
    header.offsetChanged.connect(lambda tid, value: seen.append((tid, value)))

    assert header.spin_offset.singleStep() == pytest.approx(NUDGE_FINE_MS)   # ±1ms 精调
    assert header.btn_offset_coarse_back.text() == f"-{int(NUDGE_COARSE_MS)}"
    assert header.btn_offset_coarse_fwd.text() == f"+{int(NUDGE_COARSE_MS)}"
    header.spin_offset.stepBy(1)                                       # 数值框 ±1ms 步进
    assert header.offset_ms() == pytest.approx(1.0)
    header.btn_offset_coarse_fwd.click()                               # +10ms
    assert header.offset_ms() == pytest.approx(11.0)
    header.btn_offset_coarse_back.click()                              # -10ms
    assert header.offset_ms() == pytest.approx(1.0)
    header.spin_offset.setValue(1e6)                                   # 超范围夹紧
    assert header.offset_ms() == pytest.approx(OFFSET_MAX_MS)
    assert seen[-1] == (track.track_id, OFFSET_MAX_MS)
    assert seen and all(tid == track.track_id for tid, _v in seen)


def test_header_align_state_labels(qapp):
    session, _table, tracks = _session({"/tmp/a.wav": 0.0})
    header = _header(session.get(tracks["/tmp/a.wav"].track_id))
    assert header.align_state() == "unset" and header.lbl_align.isHidden() is True
    header.set_align_state(312)
    assert header.align_state() == "detected"
    assert header.lbl_align.text() == tr("multitrack.align.onset").format(ms=312)
    assert header.lbl_align.isHidden() is False
    header.set_align_state(None)
    assert header.align_state() == "none"
    assert header.lbl_align.text() == tr("multitrack.align.none")
    header.clear_align_state()
    assert header.lbl_align.isHidden() is True


# ---------------------------------------------------------------------------
# 轨道区：自动对齐入口 + 微调驱动时间基线
# ---------------------------------------------------------------------------


def test_panel_auto_align_updates_headers_and_baseline(qapp):
    from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel

    session, table, tracks = _session({"/tmp/late.wav": 0.30, "/tmp/early.wav": 0.0})
    panel = MultitrackPanel(session)
    panel.set_session(session)
    total_before = session.total_duration()

    assert panel.btn_align.toolTip() == tr("multitrack.align.tip")
    # T-1087 M6（项目负责人裁）：auto_align 改 fire-and-forget ⇒ 返回值不再是 AlignResult。
    # 本例面板未接宿主 ⇒ 由假 reporter 就地驱动到终态，再从 align_result() 取终态；
    # 原判别力（偏移合成 / 轨道头反映 / 总时长 / 共享时间轴）逐条保留、未削弱。
    assert panel.auto_align() is None                            # 未投递 ⇒ 无句柄
    result = panel.align_result()
    assert result.reference_id == tracks["/tmp/early.wav"].track_id
    late = tracks["/tmp/late.wav"].track_id
    assert session.get(late).offset_ms == pytest.approx(-300)
    header = panel.header_column.header_for(late)
    assert header.offset_ms() == pytest.approx(-300)                 # 终态回填驱动轨道头
    assert header.lbl_align.text() == tr("multitrack.align.onset").format(ms=300)
    assert session.total_duration() == pytest.approx(total_before - 0.3, abs=1e-6)
    assert panel.view.view_range() == pytest.approx((0.0, session.total_duration()))
    for path, arr in table.items():
        assert arr.dtype == np.float64                                   # 对齐零音频改动（形状/值未变）
    assert np.array_equal(table["/tmp/late.wav"], _clip(0.30, 1.0))


def test_panel_manual_nudge_drives_shared_timeline(qapp):
    from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel

    session, table, tracks = _session({"/tmp/a.wav": 0.0})
    panel = MultitrackPanel(session)
    panel.set_session(session)
    tid = tracks["/tmp/a.wav"].track_id
    track = session.get(tid)
    header = panel.header_column.header_for(tid)
    panel.view.set_view_range(-1.0, 2.0)              # 覆盖全轨，规避窗口裁剪
    times0 = panel.view.visible_times(track)[0]
    before = table["/tmp/a.wav"].copy()

    header.btn_offset_coarse_back.click()             # -10ms（经面板编排写偏移元数据）
    assert session.get(tid).offset_ms == pytest.approx(-NUDGE_COARSE_MS)
    assert np.allclose(panel.view.visible_times(track)[0], times0 - 0.01)

    header.spin_offset.setValue(-500.0)               # 数值框精调
    assert session.get(tid).offset_ms == pytest.approx(-500.0)
    assert np.allclose(panel.view.visible_times(track)[0], times0 - 0.5)
    assert session.get(tid).shifted_duration() == pytest.approx(1.0 - 0.5)
    assert session.total_duration() == pytest.approx(0.5)
    assert panel.view.view_range()[1] >= session.total_duration()   # 对比时间基线随之更新
    assert np.array_equal(table["/tmp/a.wav"], before)              # 微调零音频改动


def test_panel_auto_align_without_tracks_is_graceful(qapp):
    from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel

    session, _table, _tracks = _session({})
    panel = MultitrackPanel(session)
    panel.set_session(session)
    assert panel.auto_align() is None                                    # 无轨：提示不崩
    assert session.total_duration() == 0.0


def test_panel_auto_align_all_silent_reports_and_keeps_offsets(qapp):
    from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel

    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": SR, "channels": 1, "duration": 0.5},
        envelope_reader=lambda p, points: (np.zeros(points), np.zeros(points, dtype=np.float32)),
        loader=lambda p: (np.zeros(SR // 2), SR),
    )
    tid = session.add_path("/tmp/silent.wav", label="silent").track_id
    session.set_offset_ms(tid, 42.0)
    panel = MultitrackPanel(session)
    panel.set_session(session)
    panel.auto_align()                                        # T-1087 M6：终态经回填
    result = panel.align_result()
    assert result.reference_id is None and result.offsets == {}
    assert session.get(tid).offset_ms == pytest.approx(42.0)             # 全静默：偏移不变
    assert panel.header_column.header_for(tid).align_state() == "none"


# ---------------------------------------------------------------------------
# i18n 与静态纪律
# ---------------------------------------------------------------------------


def test_align_i18n_keys_in_three_languages():
    import acouscope.i18n as i18n

    strings = getattr(i18n, "_STRINGS")
    for key in _ALIGN_KEYS:
        entry = strings.get(key)
        assert entry, f"缺 i18n 键: {key}"
        assert set(entry) == {"en_US", "zh_CN", "zh_TW"}, f"三语缺失: {key}"
        assert all(str(v).strip() for v in entry.values()), f"空译文: {key}"
    assert tr("multitrack.align.onset").format(ms=1)                   # 键有实际译文
    assert DEFAULT_GATE_DB < 0 and DEFAULT_MIN_SPEECH_MS > 0


def test_align_source_static_discipline():
    src = _SRC.read_text(encoding="utf-8")
    banned = "Mel" + "odyne"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), "含硬编码色值"
    assert not re.search(r"\b\d+(?:\.\d+)?px\b", src), "含硬编码像素"
    assert banned.lower() not in src.lower(), "含禁词"
    assert "QDialog" not in src and ".exec(" not in src
    assert "analysis.silence" not in src and "detect_leading_silence" not in src
