# SPDX-License-Identifier: GPL-3.0-only
"""T-804：音高网格工程序列化存取测试（project.py + controller 层）。

覆盖 HARD-RULE 5 清单：
① round-trip：save_project(grid_model=...) → load → get_saved_pitch_grid 还原，
  且 model.to_dict() 前后一致；
② 遗留兼容：无 pitch_grid 键的旧工程 load 正常、get_saved_pitch_grid() 返回 None；
③ 损坏数据：analysis_results["pitch_grid"] = {"bad": 1} → load 不抛异常；
④ save_project 默认 grid_model=None 时 analysis_results 不含 pitch_grid 键；
⑤ main_window 接线源码锚点（_do_save_project 内 "grid_model=" 存在）。

口径：offscreen、不构造 MainWindow.show()、不改既有测试。
"""

import json
from pathlib import Path

import numpy as np
import pytest

SR = 44100


def _sine(freq: float, duration: float = 1.0, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * duration)) / sr
    return np.sin(2 * np.pi * freq * t)


def _make_grid_model():
    """构建确定性音高网格模型（两音符块 + 12TET 吸附，含偏差量）。"""
    from acouscope.analysis.pitch_grid import (
        PitchGridModel,
        PitchNote,
        SNAP_12TET,
    )

    model = PitchGridModel(
        notes=[
            PitchNote(start_s=0.0, end_s=0.5, f0_hz=440.0, conf=0.9),
            PitchNote(start_s=0.6, end_s=1.2, f0_hz=494.0, conf=0.8),
        ],
        snap_mode=SNAP_12TET,
    )
    return model.apply_snap()


class TestProjectPitchGrid:
    @pytest.fixture
    def controller(self):
        from acouscope.app.controller import AppController

        return AppController()

    @pytest.fixture
    def wav_file(self, tmp_path):
        from acouscope.audio import AudioIO

        path = tmp_path / "tone.wav"
        AudioIO().save(0.5 * _sine(440, duration=0.5), SR, str(path))
        return path

    # ------------------------------------------------------------------
    # ① round-trip
    # ------------------------------------------------------------------

    def test_round_trip(self, controller, wav_file, tmp_path):
        """① 建 model → save_project(grid_model=...) → load → 还原模型且 to_dict 前后一致。"""
        from acouscope.analysis.pitch_grid import PitchGridModel

        model = _make_grid_model()
        before = model.to_dict()
        proj_path = tmp_path / "t.acouproj"

        controller.open_file(wav_file)
        controller.save_project(proj_path, grid_model=model)

        assert proj_path.exists()
        # 落盘序列化：pitch_grid 为 JSON 安全 dict
        raw = json.loads(proj_path.read_text(encoding="utf-8"))
        entry = next(
            f for f in raw["files"] if f["path"] == str(wav_file)
        )
        assert entry["analysis_results"]["pitch_grid"] == before

        project, info = controller.load_project(proj_path)
        assert info is not None
        restored = controller.get_saved_pitch_grid()
        assert isinstance(restored, PitchGridModel)
        assert restored.to_dict() == before
        # 逐音符核对（含吸附表示层与偏差量）
        for a, b in zip(restored.notes, model.notes):
            assert (a.start_s, a.end_s, a.f0_hz, a.conf) == (
                b.start_s,
                b.end_s,
                b.f0_hz,
                b.conf,
            )
            assert a.snapped_f0_hz == b.snapped_f0_hz
            assert a.deviation_cents == b.deviation_cents

    # ------------------------------------------------------------------
    # ② 遗留兼容
    # ------------------------------------------------------------------

    def test_legacy_project_without_pitch_grid(self, controller, wav_file, tmp_path):
        """② 无 pitch_grid 键的旧工程 load 正常、get_saved_pitch_grid() 返回 None。"""
        controller.open_file(wav_file)
        marks = [{"freq": 440.0, "note": "A4", "cents": 0.0, "midi": 69.0}]
        proj_path = tmp_path / "legacy.acouproj"
        controller.save_project(proj_path, annotations=marks)

        # 直接构造更早期形态（analysis_results 仅含 harmonic_marks）的旧工程
        raw = json.loads(proj_path.read_text(encoding="utf-8"))
        for entry in raw["files"]:
            entry["analysis_results"] = {
                "harmonic_marks": entry["analysis_results"].get("harmonic_marks", [])
            }
        legacy_path = tmp_path / "legacy_old.acouproj"
        legacy_path.write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )

        project, _ = controller.load_project(legacy_path)
        assert project is not None
        assert "pitch_grid" not in project.files[0].analysis_results
        assert controller.get_saved_pitch_grid() is None

    # ------------------------------------------------------------------
    # ③ 损坏数据
    # ------------------------------------------------------------------

    def test_corrupted_pitch_grid_loads_without_crash(self, controller, wav_file, tmp_path):
        """③ analysis_results["pitch_grid"] = {"bad": 1} → load 不抛异常。

        from_dict 对缺键 dict 容忍（成功还原空模型）→ 按契约还原模型；
        另加真失败数据 {"notes": [{"bad": 1}]}（PitchNote 意外关键字 → TypeError）
        验证失败分支保留原 dict、零崩溃。
        """
        from acouscope.analysis.pitch_grid import PitchGridModel

        controller.open_file(wav_file)
        proj_path = tmp_path / "bad.acouproj"
        controller.save_project(proj_path)

        raw = json.loads(proj_path.read_text(encoding="utf-8"))
        for entry in raw["files"]:
            entry.setdefault("analysis_results", {})["pitch_grid"] = {"bad": 1}
        raw_path = tmp_path / "bad_saved.acouproj"
        raw_path.write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )

        # 不抛异常
        project = controller.project.load(raw_path)
        assert project is not None
        # from_dict 容忍缺键 → 还原成功（空模型）
        assert isinstance(
            project.files[0].analysis_results["pitch_grid"], PitchGridModel
        )

        # 失败分支：PitchNote 意外关键字 → from_dict 抛异常 → 保留原 dict
        raw2 = json.loads(proj_path.read_text(encoding="utf-8"))
        for entry in raw2["files"]:
            entry.setdefault("analysis_results", {})["pitch_grid"] = {
                "notes": [{"bad": 1}]
            }
        raw2_path = tmp_path / "bad_saved2.acouproj"
        raw2_path.write_text(
            json.dumps(raw2, ensure_ascii=False), encoding="utf-8"
        )
        project2 = controller.project.load(raw2_path)
        assert project2.files[0].analysis_results["pitch_grid"] == {
            "notes": [{"bad": 1}]
        }
        assert not isinstance(
            project2.files[0].analysis_results["pitch_grid"], PitchGridModel
        )

    # ------------------------------------------------------------------
    # ④ 默认参数零行为变更
    # ------------------------------------------------------------------

    def test_default_grid_model_none_no_key(self, controller, wav_file, tmp_path):
        """④ save_project 默认 grid_model=None 时 analysis_results 不含 pitch_grid 键。"""
        controller.open_file(wav_file)
        proj_path = tmp_path / "nogrid.acouproj"
        controller.save_project(proj_path)

        raw = json.loads(proj_path.read_text(encoding="utf-8"))
        for entry in raw["files"]:
            assert "pitch_grid" not in entry["analysis_results"]
        assert controller.get_saved_pitch_grid() is None

    # ------------------------------------------------------------------
    # ⑤ main_window 接线源码锚点
    # ------------------------------------------------------------------

    def test_main_window_save_wiring_anchor(self):
        """⑤ 核心保存 _save_project_to 内存在 grid_model= 接线（T-322 抽取后源码锚点 1 例）。"""
        root = Path(__file__).resolve().parents[1]
        text = (
            root / "src" / "acouscope" / "ui" / "main_window.py"
        ).read_text(encoding="utf-8")
        func_start = text.index("def _save_project_to")
        # 截取到下一个同层 def（下一方法）为止
        func_body = text[func_start:]
        nxt = func_body.find("\n    def ", 1)
        if nxt != -1:
            func_body = func_body[:nxt]
        assert "grid_model=" in func_body
