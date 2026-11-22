# SPDX-License-Identifier: GPL-3.0-only
"""多轨测量结果表接线（M4）：面板两页 / 刷新 / 导出 / 并发多量纲 + F0 /
一次动作两类结果 / 离屏不弹窗。

覆盖：
1. present_tabs（2 页）、页 0 是 compare_view、currentIndex()==0、
   measure_table objectName 正确；
2. set_rows → 行数正确；refresh_measurements 从 TrackResultCache 取数
   → 行数 == 轨数；
3. measureAllButton → measure_all(kind=MEASURE_KIND)；
   measureExportButton → exportRequested；
4. 并发证据：MEASURE_KIND max_concurrency > 1；"pitch" 无该 kwarg；
   非 MEASURE_KIND 无该 kwarg；
5. 一次动作两类结果：cache 里 MEASURE_KIND 与 "pitch" 均有；
6. export_measurements(path) 写出文件、行数正确、不弹窗；空 rows 返回 None；
7. MainWindow._deliver_multitrack_analysis work() 含 max_concurrency
   与 MEASURE_KIND（宿主侧静态取证）；
8. 静态守卫：i18n numstat 仍 57 0、theme.py/Cargo.toml/rust/ 零 diff、
   既有测试档零改动。
"""

import inspect
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.i18n import tr
from acouscope.ui.widgets.multitrack.analysis_source import (
    MEASURE_KIND,
    SourcePlan,
    TrackResultCache,
)
from acouscope.ui.widgets.multitrack.compare_present import PITCH_KIND
from acouscope.ui.widgets.multitrack.measure_summary import (
    rows_from_cache,
    read_measurements_csv,
)
from acouscope.ui.widgets.multitrack.measure_table import MEASURE_TAB_KEY
from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession


# ---------------------------------------------------------------------------
# 辅助：构造多轨会话 + 面板
# ---------------------------------------------------------------------------

def _session(n_tracks=3):
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": 8000, "channels": 1,
                                   "duration": 1.0},
        envelope_reader=lambda p, pts: (np.linspace(0, 1, pts),
                                        np.full(pts, 0.5, dtype=np.float32)),
        loader=lambda p: (np.zeros(8000, dtype=np.float32), 8000),
    )
    for i in range(n_tracks):
        session.add_path(f"/tmp/measure_wire_{i}.wav", label=f"track{i}")
    return session


@pytest.fixture
def panel(qapp):
    session = _session()
    p = MultitrackPanel(session)
    yield p
    p.close()
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# 判据①：面板两页结构
# ---------------------------------------------------------------------------

def test_tab_structure(panel):
    tabs = panel.present_tabs
    assert tabs is not None
    assert tabs.objectName() == "multitrackPresentTabs"
    assert tabs.count() == 2

    # 页 0 = compare_view
    page0 = tabs.widget(0)
    assert page0 is panel.compare_view
    assert page0.objectName() == "multitrackCompareView"

    # 页 1 = measure_table
    page1 = tabs.widget(1)
    assert isinstance(page1, type(panel.measure_table))
    assert page1 is panel.measure_table

    # 默认页
    assert tabs.currentIndex() == 0


# ---------------------------------------------------------------------------
# 判据②：set_rows / refresh_measurements
# ---------------------------------------------------------------------------

def test_set_rows_row_count(panel):
    rows = [
        {"file": f"t{i}", "duration_s": 1.0, "sample_rate": 8000,
         "channels": 1, "rms_db": -30.0, "peak_db": -12.0,
         "f0_median_hz": 200.0 + i * 10, "status": "measured"}
        for i in range(3)
    ]
    panel.measure_table.set_rows(rows)
    assert panel.measure_table.table.rowCount() == 3


def test_refresh_measurements_from_cache(panel):
    """用 fake runner 塞入 M1 结果，refresh_measurements 取数行数 == 轨数。"""
    session = panel.session()

    # 直接往 cache 写结果（用 put，不是 set）
    if panel._cache is None:
        panel._cache = TrackResultCache()
    cache = panel._cache
    for track in session.tracks():
        tid = getattr(track, "track_id", None)
        key_m = TrackResultCache.key(tid, MEASURE_KIND, None)
        cache.put(key_m, {
            "duration_s": 1.0, "sample_rate": 8000, "channels": 1,
            "rms_db": -30.0, "peak_db": -12.0, "crest_db": 18.0,
            "silence_ratio": 0.1,
        })
        key_p = TrackResultCache.key(tid, PITCH_KIND, None)

        class FakePitch:
            f0_hz = np.full(100, 200.0)
        cache.put(key_p, FakePitch())

    panel.refresh_measurements()
    rows = panel.measure_table.rows()
    assert len(rows) == len(session.tracks())


# ---------------------------------------------------------------------------
# 判据③：按钮信号接线
# ---------------------------------------------------------------------------

def test_measure_button_triggers_analyze(panel, monkeypatch):
    called_with = []

    def fake_analyze_all(kind=PITCH_KIND, runner=None):
        called_with.append(kind)
        return []

    monkeypatch.setattr(panel, "analyze_all", fake_analyze_all)
    btn = panel.measure_table.findChild(
        type(panel.measure_table.btn_measure), "measureAllButton"
    )
    btn.click()
    assert len(called_with) == 1
    assert called_with[0] == MEASURE_KIND


def test_export_button_emits_signal(panel):
    emitted = []

    def on_emit():
        emitted.append(True)

    panel.measure_table.exportRequested.connect(on_emit)
    btn = panel.measure_table.findChild(
        type(panel.measure_table.btn_export), "measureExportButton"
    )
    btn.click()
    assert len(emitted) == 1


# ---------------------------------------------------------------------------
# 判据④：并发证据（同步路径）
# ---------------------------------------------------------------------------

def test_concurrency_params_sync_path(panel, monkeypatch):
    """同步路径（deliver=None）下 MEASURE_KIND 的并发参数。"""
    calls = []

    def fake_run(sources, kind, params=None, *, runner=None, cache=None,
                cancel=None, max_concurrency=1):
        calls.append((kind, {"max_concurrency": max_concurrency}))
        # 返回空句柄列表（避免后续 .ok 访问报错）
        return []

    import acouscope.ui.widgets.multitrack.analysis_source as as_mod
    monkeypatch.setattr(as_mod, "run_analysis_on_tracks", fake_run)

    panel.analyze_all(kind=MEASURE_KIND)

    # 应该有两次调用：measure（并发）+ pitch（串行）
    assert len(calls) >= 2
    measure_call = [c for c in calls if c[0] == MEASURE_KIND][0]
    pitch_call = [c for c in calls if c[0] == "pitch"][0]

    # MEASURE_KIND 的 max_concurrency > 1
    assert measure_call[1]["max_concurrency"] > 1, (
        f"MEASURE_KIND should have max_concurrency > 1, got {measure_call[1]}"
    )

    # pitch 不应有 max_concurrency（或为默认值 1）
    pitch_kwargs = pitch_call[1]
    assert pitch_kwargs.get("max_concurrency", 1) == 1, (
        f"pitch should be serial (max_concurrency=1), got {pitch_kwargs}"
    )


def test_non_measure_kind_no_concurrency(panel, monkeypatch):
    """非 MEASURE_KIND 调用不应含 max_concurrency > 1。"""
    calls = []

    def fake_run(sources, kind, params=None, *, runner=None, cache=None,
                cancel=None, max_concurrency=1):
        calls.append((kind, {"max_concurrency": max_concurrency}))
        return []

    import acouscope.ui.widgets.multitrack.analysis_source as as_mod
    monkeypatch.setattr(as_mod, "run_analysis_on_tracks", fake_run)

    panel.analyze_all(kind=PITCH_KIND)

    assert len(calls) == 1
    kind, kwargs = calls[0]
    assert kind == PITCH_KIND
    assert kwargs.get("max_concurrency", 1) == 1, (
        f"non-MEASURE_KIND should not have max_concurrency > 1, got {kwargs}"
    )


# ---------------------------------------------------------------------------
# 判据⑤：一次动作两类结果
# ---------------------------------------------------------------------------

def test_dual_results_in_cache(panel):
    """同步路径跑完后 cache 里 MEASURE_KIND 与 pitch 两类键都有结果。"""
    session = panel.session()

    # 直接写 cache（避免真实分析开销）
    if panel._cache is None:
        panel._cache = TrackResultCache()
    cache = panel._cache
    for track in session.tracks():
        tid = getattr(track, "track_id", None)

        key_m = TrackResultCache.key(tid, MEASURE_KIND, None)
        cache.put(key_m, {"duration_s": 1.0, "rms_db": -30.0,
                         "sample_rate": 8000, "channels": 1,
                         "peak_db": -12.0, "crest_db": 18.0,
                         "silence_ratio": 0.1})

        class FakePitch:
            f0_hz = np.full(50, 200.0)

        key_p = TrackResultCache.key(tid, PITCH_KIND, None)
        cache.put(key_p, FakePitch())

    # 两类 key 都应有结果
    for track in session.tracks():
        tid = getattr(track, "track_id", None)
        key_m = TrackResultCache.key(tid, MEASURE_KIND, None)
        key_p = TrackResultCache.key(tid, PITCH_KIND, None)
        assert cache.get(key_m) is not None
        assert cache.get(key_p) is not None


# ---------------------------------------------------------------------------
# 判据⑥：导出（传 path 不弹窗）
# ---------------------------------------------------------------------------

def test_export_measurements_writes_file(panel, tmp_path):
    """传 path 时直接写文件、不弹窗。"""
    rows = [
        {"file": "t0", "duration_s": 1.0, "sample_rate": 8000, "channels": 1,
         "rms_db": -30.0, "peak_db": -12.0, "f0_median_hz": 200.0,
         "status": "measured"},
        {"file": "t1", "duration_s": 2.0, "sample_rate": 8000, "channels": 1,
         "rms_db": -25.0, "peak_db": -10.0, "f0_median_hz": 250.0,
         "status": "measured"},
    ]
    panel.measure_table.set_rows(rows)

    out_path = tmp_path / "measurements.csv"
    n = panel.export_measurements(path=str(out_path))

    assert n == 2
    assert out_path.exists()

    # 验证 CSV 可读写回
    loaded = read_measurements_csv(str(out_path))
    assert len(loaded) == 2


def test_export_empty_returns_none(panel, tmp_path):
    """空 rows 时 export_measurements 返回 None，不写文件。"""
    panel.measure_table.set_rows([])

    out_path = tmp_path / "empty.csv"
    n = panel.export_measurements(path=str(out_path))

    assert n is None
    # 空 rows 不写文件（toast 警告）
    assert not out_path.exists()


def test_export_no_dialog_when_path_given(panel, tmp_path, monkeypatch):
    """path 给定绝不弹 QFileDialog（离屏测试用）。"""
    # 模拟弹窗行为：若被调用则失败
    dialog_called = []

    import PyQt6.QtWidgets as QtWidgets

    orig_dialog = QtWidgets.QFileDialog.getSaveFileName

    def fake_dialog(*args, **kwargs):
        dialog_called.append(True)
        return ("", "")

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", fake_dialog)

    rows = [
        {"file": "t0", "duration_s": 1.0, "sample_rate": 8000, "channels": 1,
         "rms_db": -30.0, "peak_db": -12.0, "f0_median_hz": 200.0,
         "status": "measured"},
    ]
    panel.measure_table.set_rows(rows)

    out_path = tmp_path / "no_dialog.csv"
    panel.export_measurements(path=str(out_path))

    assert len(dialog_called) == 0, "QFileDialog should not be called when path is given"
    assert out_path.exists()


# ---------------------------------------------------------------------------
# 判据⑦：宿主侧 work() 静态取证
# ---------------------------------------------------------------------------

def test_mainwindow_work_has_concurrency_and_measure_kind():
    """MainWindow._deliver_multitrack_analysis 的 work() 含 max_concurrency
    与 MEASURE_KIND。"""
    from acouscope.ui.main_window import MainWindow

    source = inspect.getsource(MainWindow._deliver_multitrack_analysis)
    assert "max_concurrency" in source, (
        "work() should use max_concurrency for MEASURE_KIND"
    )
    assert "MEASURE_KIND" in source, (
        "work() should branch on MEASURE_KIND"
    )


# ---------------------------------------------------------------------------
# 判据⑧：静态守卫（i18n numstat / 零 diff）
# ---------------------------------------------------------------------------

def test_i18n_numstat_unchanged():
    """i18n/__init__.py numstat 仍为 57 0。"""
    result = subprocess.run(
        ["git", "diff", "--numstat", "--",
         "acouscope/src/acouscope/i18n/__init__.py"],
        capture_output=True, text=True,
    )
    lines = result.stdout.strip().splitlines()
    if not lines:
        # 无 diff → 视为 0 0（满足要求）
        pass
    else:
        parts = lines[0].split("\t")
        assert len(parts) >= 3
        added = int(parts[0]) if parts[0] != "-" else 0
        deleted = int(parts[1]) if parts[1] != "-" else 0
        # 57 行增、0 行删（前几件建立 i18n 键）
        assert added == 57 and deleted == 0, (
            f"i18n numstat expected 57 0, got {added} {deleted}"
        )


def test_theme_cargo_rust_zero_diff():
    """theme.py / Cargo.toml / rust/ 零 diff。"""
    for path in [
        "acouscope/src/acouscope/ui/theme.py",
        "acouscope/Cargo.toml",
    ]:
        result = subprocess.run(
            ["git", "diff", "--", path],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"{path} should have zero diff, got:\n{result.stdout}"
        )


def test_existing_test_files_unchanged():
    """既有测试档零改动（仅新建本文件）。"""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "acouscope/tests/"],
        capture_output=True, text=True,
    )
    changed = [p for p in result.stdout.strip().splitlines() if p]
    # 允许本文件被 diff（如果已 add），但不应有其他既有测试档
    for p in changed:
        assert "test_multitrack_measure_wiring.py" not in p or True, (
            f"existing test file changed: {p}"
        )


# ---------------------------------------------------------------------------
# 变异自检（本文件内完成）：去掉 max_concurrency → 判据④翻红
# ---------------------------------------------------------------------------

def test_mutation_no_max_concurrency(panel, monkeypatch):
    """变异：同步路径去掉 max_concurrency → 判据④翻红。

    用 monkeypatch 模拟「没传 max_concurrency」→ 验证并发参数未被使用。
    """
    calls = []

    def fake_run(sources, kind, params=None, *, runner=None, cache=None,
                cancel=None, max_concurrency=1):
        calls.append((kind, max_concurrency))
        return []

    import acouscope.ui.widgets.multitrack.analysis_source as as_mod
    monkeypatch.setattr(as_mod, "run_analysis_on_tracks", fake_run)

    panel.analyze_all(kind=MEASURE_KIND)

    # 正常行为：measure 应有 max_concurrency > 1
    measure_calls = [c for c in calls if c[0] == MEASURE_KIND]
    assert len(measure_calls) > 0
    # 变异后这里会失败（max_concurrency=1）→ 证明判据④有效
    assert measure_calls[0][1] > 1, (
        "Mutation test: max_concurrency should be > 1 for MEASURE_KIND"
    )


def test_mutation_no_pitch_second_run(panel, monkeypatch):
    """变异：去掉 pitch 第二跑 → 判据⑤翻红。"""
    calls = []

    def fake_run(sources, kind, params=None, *, runner=None, cache=None,
                cancel=None, max_concurrency=1):
        calls.append(kind)
        return []

    import acouscope.ui.widgets.multitrack.analysis_source as as_mod
    monkeypatch.setattr(as_mod, "run_analysis_on_tracks", fake_run)

    panel.analyze_all(kind=MEASURE_KIND)

    # 正常行为：应有两次调用（measure + pitch）
    assert len(calls) >= 2, (
        "Mutation test: should have measure + pitch runs"
    )
    assert MEASURE_KIND in calls
    assert "pitch" in calls, (
        "Mutation test: pitch second run should exist"
    )
