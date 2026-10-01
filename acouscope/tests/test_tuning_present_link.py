# SPDX-License-Identifier: GPL-3.0-only
"""T-1034a 轮 B：音级归属接上对比呈现 + A4 参考口径注入律制。

三例守卫：
① 跨面一致性 @A4=442（本件核心判据）：叠加层 / 取用点 / compare 逐帧音级
   三面同口径；任一面按 440 ⇒ 必红；
② 反向：非 12 平均律不被吸附（just_major 550 Hz → 音级 2，12TET → 4）+
   换律制后读数取新值（作废重算真生效）；
③ 静态面：改动面 ⊆ 授权面、禁碰档逐档零 diff、新档禁出现 A4 写入调用
   （A4 在测试内只经 monkeypatch 只读注入）。

全部离屏；不显示主窗体。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.analysis.tunings.templates import get_template
from acouscope.dsp import units
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import ComparePresentWidget
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope"


class _PitchStub:
    """逐轨音高结果桩（只含呈现层消费的 times / f0_hz）。"""

    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _session(n: int = 2, duration: float = 2.0, sr: int = 8000) -> MultitrackSession:
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": sr, "channels": 1,
                                   "duration": duration},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, duration, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(sr * duration)), sr),
    )
    for i in range(n):
        session.add_path(f"/tmp/t1034b{i}.wav", label=f"track{i}")
    return session


def _seed(cache, track_id, *, times, f0, kind="pitch"):
    result = _PitchStub(times, f0)
    cache.put(TrackResultCache.key(track_id, kind, None), result)
    return result


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（不 show）；teardown close。"""
    monkeypatch.setenv("HOME", str(tmp_path))

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    win = MainWindow(controller)
    yield win
    win.close()


def test_cross_face_consistency_at_a4_442(window, monkeypatch):
    """@A4=442：叠加层 / 唯一取用点 / compare 逐帧音级三面同口径（按 440 ⇒ 必红）。"""
    monkeypatch.setattr(units, "_reference_hz", 442.0)  # 只读注入，禁 set_reference_hz
    window.action_tuning_ruler.setChecked(True)          # 用户动作式启用 → 12tet + 应用

    # ① 叠加层面：overlay[0].freq_hz == 442（既有正确参照）
    overlay = window._build_tuning_overlay_lines()
    assert overlay is not None and overlay
    assert overlay[0].freq_hz == pytest.approx(442.0)

    # 唯一取用点：模板恒 440 ⇒ 注入后 reference_freq == 442
    tuning = window._current_tuning()
    assert tuning is not None
    assert tuning.reference_freq == pytest.approx(442.0)
    # 漏斗推送：对比呈现拿到同一注入口径（frozen dataclass 值相等）
    presentation = window.multitrack_panel.presentation()
    assert presentation.tuning() == tuning

    # ② compare 面：逐帧音级 == units.hz_to_cents(f, 442) 折算口径（同一 f0 逐帧相等）
    times = np.linspace(0.0, 1.5, 30)
    offsets = np.tile(np.array([0.0, 49.0, 151.0, 240.0, 349.0, 500.0]), 5)
    ref_f0 = np.full(30, 442.0)
    oth_f0 = 442.0 * 2 ** (offsets / 1200.0)
    session = _session(2)
    cache = TrackResultCache()
    _seed(cache, session.tracks()[0].track_id, times=times, f0=ref_f0)
    _seed(cache, session.tracks()[1].track_id, times=times, f0=oth_f0)
    widget = ComparePresentWidget(session, cache)
    widget.refresh()
    widget.set_tuning(window._current_tuning())          # 真链路：取用点对象进呈现层
    summary = widget.compute_diff()
    assert summary is not None and summary.tracks
    track = summary.tracks[0]
    assert track.pairs == 30
    degrees = np.asarray(track.degrees, dtype=int)
    expected = np.array(
        [tuning.cents_to_degree(float(units.hz_to_cents(float(f), ref_freq=442.0)))
         for f in oth_f0],
        dtype=int,
    )
    assert np.array_equal(degrees, expected)

    # 必红自证：若仍按模板 440 ⇒ 逐帧音级与上面不同
    raw_440 = get_template("12tet")
    degrees_if_440 = np.array(
        [raw_440.freq_to_degree(float(f)) for f in oth_f0], dtype=int
    )
    assert not np.array_equal(degrees, degrees_if_440)

    # 关闭标尺 → 推送清空（零残留语义同步覆盖呈现层）
    window.action_tuning_ruler.setChecked(False)
    assert window.multitrack_panel.presentation().tuning() is None


def test_non_12tet_not_snapped_and_switch_refreshes_readout(monkeypatch):
    """just_major 550 Hz → 音级 2（不被 12TET 吸附成 4）；换律制后读数取新值。"""
    monkeypatch.setattr(units, "_reference_hz", 440.0)
    times = np.linspace(0.0, 1.5, 30)
    session = _session(2)
    cache = TrackResultCache()
    _seed(cache, session.tracks()[0].track_id, times=times, f0=np.full(30, 440.0))
    _seed(cache, session.tracks()[1].track_id, times=times, f0=np.full(30, 550.0))
    widget = ComparePresentWidget(session, cache)
    widget.refresh()

    just = get_template("just_major")                    # 550/440 = 5/4 → 音级 2
    widget.set_tuning(just)
    degrees = np.asarray(widget.diff().tracks[0].degrees, dtype=int)
    assert (degrees == 2).all()
    assert not (degrees == 4).any()                      # 断言 2 != 4：非 12 平均律吸附
    assert widget.tuning() is just
    readout = widget.hover_readout_at(float(times[5]))
    assert "#2" in readout
    assert "#4" not in readout
    assert just.name in widget.lbl_hint.text()           # 汇总行挂律制名（模型自带文本）

    tet = get_template("12tet")                          # 同输入换 12TET → 音级 4
    widget.set_tuning(tet)
    degrees = np.asarray(widget.diff().tracks[0].degrees, dtype=int)
    assert (degrees == 4).all()
    readout = widget.hover_readout_at(float(times[5]))
    assert "#4" in readout
    assert "#2" not in readout                           # 作废重算生效：取值已更新
    assert tet.name in widget.lbl_hint.text()


def test_static_face_scope_and_guards():
    """静态面：禁碰档逐档零 diff；新档禁 A4 写入调用；src 调用者仍限两档。"""
    # ① 授权面内容锚：三档新面各自只出现在授权档内（src 全树检索）
    main_src = (_SRC_ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    present_src = (
        _SRC_ROOT / "ui" / "widgets" / "multitrack" / "compare_present.py"
    ).read_text(encoding="utf-8")
    assert "_current_tuning" in main_src
    assert "dataclasses.replace(tuning, reference_freq=float(get_reference_hz()))" in main_src
    assert "presentation().set_tuning(" in main_src
    assert "def set_tuning(" in present_src
    assert "def compute_diff(self, *, tuning=None)" in present_src
    for other in _SRC_ROOT.rglob("*.py"):
        if other.name.startswith("._"):  # AppleDouble 旁车非源码
            continue
        rel = other.relative_to(_SRC_ROOT).as_posix()
        if rel == "ui/main_window.py":
            continue
        assert "_current_tuning" not in other.read_text(encoding="utf-8"), rel

    # ② 禁碰档逐档零 diff（git porcelain 逐档为空；缓存结构/params 随之零碰）
    forbidden = (
        "acouscope/src/acouscope/ui/widgets/multitrack/compare_diff.py",
        "acouscope/src/acouscope/ui/widgets/multitrack/multitrack_view.py",
        "acouscope/src/acouscope/ui/widgets/multitrack/analysis_source.py",
        "acouscope/src/acouscope/ui/widgets/multitrack/track_model.py",
        "acouscope/src/acouscope/ui/widgets/task_center.py",
        "acouscope/src/acouscope/analysis/pcp.py",
        "acouscope/src/acouscope/dsp/units.py",
        "acouscope/src/acouscope/analysis/tunings/tuning_system.py",
        "acouscope/src/acouscope/analysis/tunings/templates.py",
    )
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--"] + list(forbidden),
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"禁碰档出现改动:\n{proc.stdout}"

    # ③ 新档自检：本文件禁出现 A4 写入调用（含注释/文档字符串；只经 monkeypatch 注入）。
    # needle 拼接构造：避免守卫语句自身含该字面量导致自检恒假。
    needle = "set_" + "reference_hz("
    assert needle not in Path(__file__).read_text(encoding="utf-8")
    # src 全树镜像守卫：调用者仍仅限既有两档
    callers = sorted(
        path.relative_to(_SRC_ROOT).as_posix()
        for path in _SRC_ROOT.rglob("*.py")
        if not path.name.startswith("._")  # AppleDouble 旁车非源码
        and needle in path.read_text(encoding="utf-8")
    )
    assert callers == ["dsp/units.py", "ui/main_window.py"]
