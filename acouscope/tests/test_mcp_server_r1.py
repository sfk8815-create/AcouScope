# SPDX-License-Identifier: GPL-3.0-only
"""MCP server tests — protocol handshake, end-to-end equivalence, security."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import anyio
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    base = tmp_path_factory.mktemp("mcp_server_wavs")
    files = []
    for freq in [220, 330, 440]:
        fpath = base / f"tone_{freq}hz.wav"
        _make_sine_wav(fpath, freq)
        files.append(str(fpath))
    return files


def _parse_tool_result(result):
    """Parse call_tool result — try structuredContent first, then JSON text."""
    if result.structuredContent is not None:
        return result.structuredContent
    # Fall back to parsing JSON from text content
    text = result.content[0].text
    return json.loads(text)


def test_protocol_handshake(test_wavs, monkeypatch):
    """Criterion 1: list_tools returns exactly 3 tools; list_resources has 2 URIs."""
    from acouscope.mcp.server import mcp

    # Monkeypatch load_policy for in-process test
    root = Path(test_wavs[0]).resolve().parent
    policy = {
        "enabled": True,
        "allowed_roots": (root,),
        "out_dir": root,
        "max_files": 32,
        "max_total_bytes": 512 * 1024 * 1024,
    }

    async def run_test():
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(mcp) as session:
            # List tools
            tools_result = await session.list_tools()
            tool_names = sorted([t.name for t in tools_result.tools])
            print(f"TOOL NAMES: {tool_names}")

            assert len(tools_result.tools) == 3, \
                f"expected 3 tools, got {len(tools_result.tools)}: {[t.name for t in tools_result.tools]}"
            assert tool_names == ["describe_audio", "measure_files", "read_measurements_csv"]

            # Verify each tool has non-empty inputSchema properties
            for t in tools_result.tools:
                props = t.inputSchema.get("properties", {})
                assert len(props) > 0, f"tool {t.name} has empty inputSchema properties"

            # List resources
            res_result = await session.list_resources()
            res_uris = [str(r.uri) for r in res_result.resources]
            print(f"RESOURCE URIS: {res_uris}")

            assert "acouscope://schema/measurements" in res_uris, \
                f"missing schema resource: {res_uris}"
            assert "acouscope://server/info" in res_uris, \
                f"missing info resource: {res_uris}"

            # Read measurements schema
            from acouscope.ui.widgets.multitrack.measure_summary import MEASUREMENT_COLUMNS

            schema = await session.read_resource("acouscope://schema/measurements")
            # Parse the content — check both structured and text forms
            schema_text = None
            if hasattr(schema, "contents"):
                for item in schema.contents:
                    if hasattr(item, "text") and item.text:
                        schema_text = item.text
                        break
            if not schema_text:
                raise AssertionError(f"could not extract schema text from {schema}")

            parsed = json.loads(schema_text)
            col_names = parsed["columns"]
            print(f"SCHEMA COLUMNS: {col_names}")
            assert col_names == list(MEASUREMENT_COLUMNS), \
                f"schema columns mismatch: {col_names} != {list(MEASUREMENT_COLUMNS)}"

            print("PROTOCOL HANDSHAKE: OK")

    anyio.run(run_test)


def test_end_to_end_equivalence(test_wavs, monkeypatch):
    """Criterion 2: call_tool results match direct service calls."""
    from acouscope.mcp.server import mcp

    root = Path(test_wavs[0]).resolve().parent
    policy = {
        "enabled": True,
        "allowed_roots": (root,),
        "out_dir": root,
        "max_files": 32,
        "max_total_bytes": 512 * 1024 * 1024,
    }

    # Monkeypatch service.load_policy for the MCP tools
    import acouscope.mcp.service as svc_module

    monkeypatch.setattr(
        svc_module, "load_policy", lambda **kw: policy
    )

    # First call service directly to get reference values
    direct_result = svc_module.measure_files(test_wavs, policy=policy)
    assert len(direct_result["rows"]) == 3

    async def run_test():
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(mcp) as session:
            # Call measure_files tool
            result = await session.call_tool("measure_files", {
                "paths": test_wavs,
                "include_f0": True,
                "max_concurrency": 1,
            })

            tool_result = _parse_tool_result(result)
            assert "rows" in tool_result, f"tool result missing 'rows': {list(tool_result.keys())}"

            # Compare row count
            assert len(tool_result["rows"]) == len(direct_result["rows"]), \
                f"row count mismatch: {len(tool_result['rows'])} != {len(direct_result['rows'])}"

            # Compare each row, each column
            from acouscope.ui.widgets.multitrack.measure_summary import MEASUREMENT_COLUMNS

            for i, (tool_row, direct_row) in enumerate(
                zip(tool_result["rows"], direct_result["rows"])
            ):
                for col in MEASUREMENT_COLUMNS:
                    tv = tool_row.get(col)
                    dv = direct_row.get(col)
                    # String columns: exact match
                    if col in ("track", "file", "status"):
                        assert tv == dv, f"row {i} col {col}: {tv!r} != {dv!r}"
                    elif tv is None and dv is None:
                        pass
                    else:
                        # Numeric: exact match (same processing path)
                        assert tv == dv, f"row {i} col {col}: {tv!r} != {dv!r}"

            # F0 accuracy: within 0.5 Hz of expected frequencies
            expected_f0 = [220.0, 330.0, 440.0]
            for i, expected in enumerate(expected_f0):
                f0 = tool_result["rows"][i].get("f0_median_hz")
                assert f0 is not None, f"row {i} f0_median_hz is None"
                assert abs(f0 - expected) <= 0.5, \
                    f"row {i} f0 {f0:.2f} Hz deviates > 0.5 Hz from expected {expected} Hz"

            # JSON serialization of entire result
            serialized = json.dumps(tool_result)
            assert len(serialized) > 0, "json.dumps produced empty string"

            print(f"E2E EQUIVALENCE: OK ({len(tool_result['rows'])} rows)")
            print(f"  f0 values: {[r.get('f0_median_hz') for r in tool_result['rows']]}")
            print(f"  JSON length: {len(serialized)} bytes")

    anyio.run(run_test)


def test_security_and_stdout(test_wavs, monkeypatch):
    """Criterion 3: structured errors, no traceback, no PyQt import on import."""

    # Part A: call_tool error handling
    from acouscope.mcp.server import mcp

    root = Path(test_wavs[0]).resolve().parent
    policy = {
        "enabled": True,
        "allowed_roots": (root,),
        "out_dir": root,
        "max_files": 32,
        "max_total_bytes": 512 * 1024 * 1024,
    }

    import acouscope.mcp.service as svc_module
    monkeypatch.setattr(svc_module, "load_policy", lambda **kw: policy)

    async def run_test():
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(mcp) as session:
            # Call with path outside allowed roots → should get structured error
            outside_path = "/tmp/outside_allowed_roots.wav"
            result = await session.call_tool("describe_audio", {"path": outside_path})

            error_result = _parse_tool_result(result)
            assert "error" in error_result, \
                f"expected 'error' key in result, got: {list(error_result.keys())}"
            assert error_result["error"] == "PermissionError", \
                f"expected PermissionError, got {error_result['error']}"

            # Serialize to check no traceback leaked
            serialized = json.dumps(error_result)
            assert "Traceback" not in serialized, \
                f"traceback leaked into error result: {serialized[:200]}"

            print(f"ERROR HANDLING: OK ({error_result['error']})")
            print(f"  message: {error_result.get('message', 'N/A')}")

    anyio.run(run_test)

    # Part B: import acouscope.mcp_server does not load PyQt6
    env = dict(os.environ)
    env["PYTHONPATH"] = WT_SRC + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import sys\n"
        f"sys.path.insert(0, '{WT_SRC}')\n"
        "import io\n"
        "old_stdout = sys.stdout\n"
        "captured = io.StringIO()\n"
        "sys.stdout = captured\n"
        "import acouscope.mcp_server\n"
        "sys.stdout = old_stdout\n"
        'has_pyqt6 = "PyQt6" in sys.modules or any(k.startswith("PyQt6.") for k in sys.modules)\n'
        'has_qapp = "QApplication" in sys.modules\n'
        'out_text = captured.getvalue()\n'
        'print(f"has_pyqt6:{has_pyqt6}")\n'
        'print(f"has_qapp:{has_qapp}")\n'
        "print('out_empty:' + str(out_text == ''))\n"
        "print('out_len:' + str(len(out_text)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, f"import failed: {result.stderr}"
    output = result.stdout.strip()
    print(f"IMPORT TEST OUTPUT:\n{output}")

    assert "has_pyqt6:False" in output, f"PyQt6 was loaded during import: {output}"
    assert "has_qapp:False" in output, f"QApplication was loaded during import: {output}"
    assert "out_empty:True" in output, f"stdout not empty during import: {output}"

    print("IMPORT SIDE-EFFECT TESTS: OK")
