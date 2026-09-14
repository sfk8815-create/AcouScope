# SPDX-License-Identifier: GPL-3.0-only
"""音高网格加载侧还原测试（T-805，GUI_backlog #16）。PITCH_GRID_LOAD_RESTORE_V1

接线：main_window._sync_after_open 调 controller.get_saved_pitch_grid()，
返回值 isinstance PitchGridModel 时还原 self._pitch_grid_model（加载侧仅还原
模型，不重建音高控件）。损坏数据经 T-804 反序列化零崩溃路径后残留非法 dict
（非模型），对加载侧有效值为 None，不覆盖既有状态。
"""

import inspect

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.analysis.pitch_grid import PitchGridModel, PitchNote  # noqa: E402
from acouscope.app.controller import AppController  # noqa: E402
from acouscope.ui.main_window import MainWindow  # noqa: E402


def _make_grid() -> PitchGridModel:
    """构造一个含 2 个音符块的真实网格模型。"""
    return PitchGridModel(
        notes=[
            PitchNote(start_s=0.0, end_s=0.5, f0_hz=261.63, conf=0.9),
            PitchNote(start_s=0.6, end_s=1.2, f0_hz=329.63, conf=0.8),
        ],
        snap_mode="12tet",
    )


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控，offscreen，不 show）。"""

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    tone = 0.5 * np.sin(2 * np.pi * 300 * t)
    controller.load_from_array(tone, sr)
    w = MainWindow(controller)
    yield w
    w.close()


class TestGridLoadRestore:
    """_sync_after_open 网格还原接线（T-805）。"""

    def test_saved_grid_restored_after_sync(self, window, monkeypatch):
        """① 工程已存 pitch_grid：_sync_after_open 后 _pitch_grid_model 还原为同对象。"""
        saved = _make_grid()
        monkeypatch.setattr(
            window.controller, "get_saved_pitch_grid", lambda: saved, raising=False
        )
        window._sync_after_open(window.controller.audio_info)

        assert window._pitch_grid_model is saved
        assert [nt.f0_hz for nt in window._pitch_grid_model.notes] == [261.63, 329.63]

    def test_no_saved_grid_keeps_state(self, window, monkeypatch):
        """② 工程未存 pitch_grid（getter 返回 None）：_pitch_grid_model 保持原状态。"""
        monkeypatch.setattr(
            window.controller, "get_saved_pitch_grid", lambda: None, raising=False
        )
        window._sync_after_open(window.controller.audio_info)
        # 全新窗口（无音高分析）：属性未创建，读侧默认 None
        assert getattr(window, "_pitch_grid_model", None) is None

        # 已有分析产物时：None 不覆盖既有模型（原状态保持）
        existing = _make_grid()
        window._pitch_grid_model = existing
        window._sync_after_open(window.controller.audio_info)
        assert window._pitch_grid_model is existing

    def test_corrupt_grid_no_crash_and_no_restore(self, window, tmp_path, monkeypatch):
        """③ 损坏数据（dict 非合法网格）：不抛异常，加载侧有效返回为 None 且不还原。

        T-804 反序列化失败时保留原 dict（非模型）；加载侧 isinstance 守卫使
        其有效值 = None，_sync_after_open 全程无异常、不覆盖既有状态。
        """
        from acouscope.app.project import ProjectManager

        corrupt = {
            "snap_mode": "off",
            "grid_cents": None,
            # 非法 notes 项：缺 start_s/end_s 且含未知键 → from_dict 失败
            "notes": [{"bogus_key": 1, "f0_hz": "not-a-number"}],
        }
        pm = ProjectManager()
        proj = pm.new("T805 corrupt")
        if not proj.files:
            from acouscope.app.project import ProjectFile

            proj.files.append(ProjectFile(path="/nonexistent/T805.wav"))
        proj.files[0].analysis_results["pitch_grid"] = dict(corrupt)
        proj_path = tmp_path / "t805_corrupt.acouproj"
        pm.save(proj_path)

        # 重新加载：零崩溃，损坏 dict 原样保留（T-804 反序列化 fallback）
        loaded = ProjectManager().load(str(proj_path))
        raw = next(f for f in loaded.files).analysis_results.get("pitch_grid")
        assert isinstance(raw, dict) and not isinstance(raw, PitchGridModel)
        # 加载侧口径：非模型 → 有效返回 None
        assert (raw if isinstance(raw, PitchGridModel) else None) is None

        # 情形 A：getter 有效返回 None → 不抛异常、不还原
        monkeypatch.setattr(
            window.controller, "get_saved_pitch_grid", lambda: None, raising=False
        )
        window._sync_after_open(window.controller.audio_info)
        assert getattr(window, "_pitch_grid_model", None) is None

        # 情形 B：getter 直接返回残留损坏 dict（控制器现状）→ 守卫拦截，不覆盖
        existing = _make_grid()
        window._pitch_grid_model = existing
        monkeypatch.setattr(
            window.controller, "get_saved_pitch_grid", lambda: raw, raising=False
        )
        window._sync_after_open(window.controller.audio_info)
        assert window._pitch_grid_model is existing

    def test_sync_after_open_source_anchors(self):
        """④ 源码锚点：_sync_after_open 内含 get_saved_pitch_grid 调用。"""
        src = inspect.getsource(MainWindow._sync_after_open)
        assert "get_saved_pitch_grid" in src
        assert "_pitch_grid_model" in src
        assert "isinstance(grid, PitchGridModel)" in src


class TestCorruptSerializeRoundtrip:
    """损坏/合法数据经工程序列化-反序列化往返（T-804 路径佐证 ③）。"""

    def _project_with_grid(self, pm: "ProjectManager", grid_value):
        from acouscope.app.project import ProjectFile

        proj = pm.new("T805 roundtrip")
        if not proj.files:
            proj.files.append(ProjectFile(path="/nonexistent/x.wav"))
        proj.files[0].analysis_results["pitch_grid"] = grid_value
        return proj

    def test_corrupt_dict_survives_roundtrip_without_model(self, tmp_path):
        from acouscope.app.project import ProjectManager

        pm = ProjectManager()
        proj = self._project_with_grid(pm, {"notes": [{"bogus": True}]})
        p = tmp_path / "t805_rt.acouproj"
        pm.save(p)
        val = ProjectManager().load(str(p)).files[0].analysis_results.get("pitch_grid")
        # 零崩溃：损坏 dict 保留（非模型、非 None）
        assert isinstance(val, dict) and not isinstance(val, PitchGridModel)

    def test_valid_grid_roundtrip_restores_model(self, tmp_path):
        from acouscope.app.project import ProjectManager

        pm = ProjectManager()
        proj = self._project_with_grid(pm, _make_grid())
        p = tmp_path / "t805_rt_ok.acouproj"
        pm.save(p)
        val = ProjectManager().load(str(p)).files[0].analysis_results.get("pitch_grid")
        # 合法网格：to_dict → from_dict 还原为 PitchGridModel（跨会话保真）
        assert isinstance(val, PitchGridModel)
        assert len(val.notes) == 2
        assert val.snap_mode == "12tet"
