# SPDX-License-Identifier: GPL-3.0-only
"""分析参数快照单元测试（B1-03 / R9）：参数面采集、确定性、A4 单源跟随、项目文件往返。"""

import json

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.note_hmm import NOTE_HMM_PARAMS  # noqa: E402
from acouscope.analysis.params_snapshot import (  # noqa: E402
    ANALYSIS_PARAMS_METADATA_KEY,
    analysis_params_snapshot,
    params_snapshot_to_metadata,
)
from acouscope.dsp.units import get_reference_hz, set_reference_hz  # noqa: E402


def test_snapshot_shape_and_params_verbatim():
    """① 快照含 A4 参考与 note_hmm 参数面，且与全局真值逐键相等（防写死脱钩）。"""
    snap = analysis_params_snapshot()
    assert snap["note_hmm_params"] == NOTE_HMM_PARAMS
    assert snap["note_hmm_params"]["bins_per_semitone"] == 3
    assert snap["a4_reference_hz"] == pytest.approx(get_reference_hz())
    assert isinstance(snap["version"], str) and snap["version"]
    assert isinstance(snap["pyin_marker"], str) and snap["pyin_marker"]
    assert snap["pcp_params"]["bins"] == 120


def test_snapshot_deterministic():
    """② 同参数面两次调用逐位一致（可复现前提）。"""
    assert analysis_params_snapshot() == analysis_params_snapshot()


def test_snapshot_follows_a4_single_source():
    """③ 改 A4 全局单源后快照随之改变（证明真读单源，非常量）；finally 恢复。"""
    old = get_reference_hz()
    try:
        set_reference_hz(441.0)
        assert analysis_params_snapshot()["a4_reference_hz"] == pytest.approx(441.0)
    finally:
        set_reference_hz(old)
    assert analysis_params_snapshot()["a4_reference_hz"] == pytest.approx(old)


def test_snapshot_roundtrip_via_project_metadata(tmp_path):
    """④ 快照经 ProjectFile.metadata（JSON 字符串）save→load 往返取回同一值。"""
    from acouscope.app.project import ProjectFile, ProjectManager

    raw = params_snapshot_to_metadata()
    assert isinstance(raw, str)  # Dict[str, str] 不变式
    pm = ProjectManager()
    pm.new("snapshot-test")
    pm.current.files.append(ProjectFile(path="/nonexistent/x.wav", label="x"))
    pm.current.files[0].metadata[ANALYSIS_PARAMS_METADATA_KEY] = raw
    proj_path = tmp_path / "snap.acouproj"
    pm.save(proj_path)
    loaded = ProjectManager().load(str(proj_path))
    back = loaded.files[0].metadata[ANALYSIS_PARAMS_METADATA_KEY]
    assert isinstance(back, str)
    assert json.loads(back) == analysis_params_snapshot()


def test_snapshot_bound_on_save_project(tmp_path):
    """⑤ 绑定实证：save_project(grid_model=...) 后 metadata 含快照 JSON 且可取回。"""
    import numpy as np

    from acouscope.app.controller import AppController
    from acouscope.audio import AudioIO
    from acouscope.analysis.pitch_grid import PitchGridModel

    wav = tmp_path / "tone.wav"
    AudioIO().save(
        0.5 * np.sin(2 * np.pi * 220.0 * np.arange(4410) / 44100), 44100, str(wav)
    )
    controller = AppController()
    controller.open_file(wav)
    model = PitchGridModel(notes=[], snap_mode="off")
    proj_path = tmp_path / "bound.acouproj"
    controller.save_project(proj_path, grid_model=model)
    raw = json.loads(proj_path.read_text(encoding="utf-8"))
    entry = next(f for f in raw["files"] if f["path"] == str(wav))
    assert ANALYSIS_PARAMS_METADATA_KEY in entry["metadata"]
    assert json.loads(entry["metadata"][ANALYSIS_PARAMS_METADATA_KEY]) == (
        analysis_params_snapshot()
    )
