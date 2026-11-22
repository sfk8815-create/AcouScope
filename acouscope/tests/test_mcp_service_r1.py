# SPDX-License-Identifier: GPL-3.0-only
"""MCP service layer tests — headless import, numerical equivalence, security."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Force offscreen Qt for any incidental imports
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure worktree src is on path
WT_SRC = str(Path(__file__).resolve().parents[1] / "src")
if WT_SRC not in sys.path:
    sys.path.insert(0, WT_SRC)


def _make_sine_wav(path: Path, freq: float, duration: float = 1.0, sr: int = 44100) -> None:
    """Generate a sine wave WAV file."""
    import soundfile as sf

    t = np.arange(0, duration * sr, dtype=np.float64) / sr
    signal = 0.5 * np.sin(2 * np.pi * freq * t)
    sf.write(str(path), signal, sr)


@pytest.fixture(scope="module")
def test_wavs(tmp_path_factory):
    """Create 3 synthetic WAV files for testing."""
    base = tmp_path_factory.mktemp("mcp_wavs")
    files = []
    for freq in [220, 330, 440]:
        fpath = base / f"tone_{freq}hz.wav"
        _make_sine_wav(fpath, freq)
        files.append(str(fpath))
    return files


def test_headless_import():
    """Criterion 1: import acouscope.mcp.service without loading PyQt6."""
    env = dict(os.environ)
    env["PYTHONPATH"] = WT_SRC + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import sys\n"
        f"sys.path.insert(0, '{WT_SRC}')\n"
        "import acouscope.mcp.service\n"
        'has_pyqt6 = "PyQt6" in sys.modules or any(k.startswith("PyQt6.") for k in sys.modules)\n'
        'print(f"has_pyqt6:{has_pyqt6}")\n'
        "from acouscope.ui.widgets.multitrack import MultitrackSession, TrackModel, format_seconds\n"
        'print(f"MultitrackSession module:{MultitrackSession.__module__}")\n'
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout.strip()
    print("HEADLESS IMPORT OUTPUT:")
    for line in output.split("\n"):
        print(f"  {line}")
    assert "has_pyqt6:False" in output, f"PyQt6 was loaded: {output}"
    assert "MultitrackSession module:acouscope.ui.widgets.multitrack.track_model" in output


def test_numerical_equivalence(test_wavs):
    """Criterion 2: measure_files rows match manual chain; CSV round-trip; np.float64→float."""
    from acouscope.mcp.service import measure_files, read_measurements_csv

    root = Path(test_wavs[0]).resolve().parent
    policy = {
        "enabled": True,
        "allowed_roots": (root,),
        "out_dir": root,
        "max_files": 32,
        "max_total_bytes": 512 * 1024 * 1024,
    }

    # Call measure_files through the service layer
    result = measure_files(test_wavs, policy=policy)
    assert len(result["rows"]) == 3

    # Manual chain: AnalysisSource → run_analysis_on_tracks → rows_from_cache
    from acouscope.audio.io import AudioIO
    from acouscope.ui.widgets.multitrack.analysis_source import (
        MEASURE_KIND,
        AnalysisSource,
        TrackResultCache,
        run_analysis_on_tracks,
    )
    from acouscope.ui.widgets.multitrack.measure_summary import rows_from_cache

    audio = AudioIO()
    sources = []
    track_infos = []
    for i, wpath in enumerate(test_wavs):
        data, sr = audio.load(wpath)
        sources.append(AnalysisSource(Path(wpath).stem, data, sr, track_id=str(i)))
        track_infos.append(
            {"track_id": str(i), "label": Path(wpath).name, "offset_ms": 0.0}
        )

    class ShimTrack:
        pass

    shim_tracks = []
    for info in track_infos:
        t = ShimTrack()
        t.track_id = info["track_id"]
        t.label = info["label"]
        t.offset_ms = info["offset_ms"]
        shim_tracks.append(t)

    class ShimSession:
        def tracks(self):
            return shim_tracks

    cache = TrackResultCache()
    run_analysis_on_tracks(sources, MEASURE_KIND, cache=cache)
    # Service also runs pitch analysis serially — manual chain must match
    try:
        run_analysis_on_tracks(sources, "pitch", cache=cache)
    except Exception:
        pass
    manual_rows = rows_from_cache(ShimSession(), cache)

    # Compare all 13 columns exactly (no tolerance — precision only improves)
    from acouscope.ui.widgets.multitrack.measure_summary import MEASUREMENT_COLUMNS

    STRING_COLUMNS = {"track", "file", "status"}
    print("NUMERICAL EQUIVALENCE (13 columns, exact):")
    for i in range(3):
        svc_row = result["rows"][i]
        man_row = manual_rows[i]
        for col in MEASUREMENT_COLUMNS:
            sv, mv = svc_row[col], man_row[col]
            if col in STRING_COLUMNS:
                assert sv == mv, f"row {i} col {col}: {sv!r} != {mv!r}"
            else:
                if sv is None and mv is None:
                    continue
                assert sv == mv, \
                    f"row {i} col {col}: {sv!r} != {mv!r}"
        print(f"  row {i}: OK (all 13 columns match)")

    # CSV round-trip
    csv_path = root / "test_mcp_output.csv"
    result2 = measure_files(test_wavs, policy=policy, out_csv=str(csv_path))
    print(f"  CSV path: {result2['csv_path']}")
    print(f"  CSV errors: {result2['errors']}")
    assert result2["csv_path"] is not None and Path(result2["csv_path"]).exists()
    read_back = read_measurements_csv(csv_path, policy=policy)
    assert len(read_back["rows"]) == 3
    STRING_COLUMNS = {"track", "file", "status"}
    for i in range(3):
        orig_row = result2["rows"][i]
        rb_row = read_back["rows"][i]
        for col in MEASUREMENT_COLUMNS:
            ov, rv = orig_row[col], rb_row[col]
            if col in STRING_COLUMNS:
                assert ov == rv, f"CSV roundtrip row {i} col {col}: {ov!r} != {rv!r}"
            else:
                if ov is None and rv is None:
                    continue
                assert ov == rv, \
                    f"CSV roundtrip row {i} col {col}: {ov!r} != {rv!r}"
    csv_path.unlink()

    # np.float64 → Python float conversion
    for row in result["rows"]:
        assert not any(isinstance(v, np.generic) for v in row.values()), \
            f"numpy scalar found in service result: {row}"
        if row["rms_db"] is not None:
            assert type(row["rms_db"]) is float, f"rms_db should be Python float: {type(row['rms_db'])}"

    # JSON serialization
    result_no_paths = {k: v for k, v in result.items() if k != "csv_path"}
    json_str = json.dumps(result_no_paths)
    assert len(json_str) > 0

    print("CSV ROUNDTRIP: OK")
    print("TYPE CONVERSIONS: OK (all Python floats)")
    print("JSON DUMPS: OK")


def test_security_checks(test_wavs):
    """Criterion 3: validate_path rejects violations."""
    from acouscope.mcp.service import describe_audio, measure_files, validate_path

    root = Path(test_wavs[0]).resolve().parent
    policy = {
        "enabled": True,
        "allowed_roots": (root,),
        "out_dir": root,
        "max_files": 32,
        "max_total_bytes": 512 * 1024 * 1024,
    }

    print("SECURITY CHECKS:")

    # 1. Empty allowed_roots → PermissionError
    empty_policy = dict(policy, allowed_roots=())
    try:
        validate_path(test_wavs[0], empty_policy)
        assert False, "should have raised PermissionError"
    except PermissionError as e:
        print(f"  empty_roots: OK ({e})")

    # 2. Path traversal via .. → PermissionError
    outside = root.parent / "outside.wav"
    outside.write_bytes(b"\x00")
    try:
        validate_path(str(outside), policy)
        assert False, "should have raised PermissionError for outside path"
    except PermissionError as e:
        print(f"  outside_path: OK ({e})")
    finally:
        outside.unlink()

    # 3. Symlink escape → PermissionError
    link = root / "escape_link.wav"
    try:
        link.symlink_to(outside)
        try:
            validate_path(str(link), policy)
            assert False, "should have raised PermissionError for symlink escape"
        except PermissionError as e:
            print(f"  symlink_escape: OK ({e})")
    finally:
        if link.exists():
            link.unlink()

    # 4. Too many files → ValueError
    try:
        measure_files([test_wavs[0]] * 33, policy=policy)
        assert False, "should have raised ValueError for 33 files"
    except ValueError as e:
        print(f"  too_many_files: OK ({e})")

    # 5. out_csv outside allowed roots → PermissionError, file not created
    bad_out = root.parent / "bad_output.csv"
    with pytest.raises(PermissionError):
        measure_files(test_wavs, policy=policy, out_csv=str(bad_out))
    assert not bad_out.exists(), "bad out_csv file should not exist"
    print("  out_csv_outside: OK (PermissionError raised, file not created)")

    # 6. describe_audio success path
    desc = describe_audio(test_wavs[0], policy=policy)
    assert set(desc.keys()) == {"name", "sample_rate", "channels", "duration", "frames"}
    assert desc["sample_rate"] == 44100
    assert desc["frames"] > 0
    print(f"  describe_audio success: OK (name={desc['name']}, frames={desc['frames']})")

    # 7. describe_audio rejects non-whitelisted files
    outside2 = root.parent / "not_allowed.wav"
    outside2.write_bytes(b"\x00")
    try:
        describe_audio(str(outside2), policy=policy)
        assert False, "should have raised for non-whitelisted file"
    except (PermissionError, FileNotFoundError):
        print("  describe_outside: OK")
    finally:
        if outside2.exists():
            outside2.unlink()

    print("  Security checks: OK (all violations correctly rejected)")
