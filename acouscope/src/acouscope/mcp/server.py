# SPDX-License-Identifier: GPL-3.0-only
"""MCP FastMCP server wrapping the service layer.

Provides 3 tools (describe_audio, measure_files, read_measurements_csv)
and 2 resources (acouscope://schema/measurements, acouscope://server/info).
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from acouscope.mcp import service

mcp = FastMCP("AcouScope", json_response=True)


@mcp.tool()
def describe_audio(path: str) -> dict:
    """Describe an audio file without loading samples.

    Args:
        path: Absolute path to the audio file (must be within allowed roots).

    Returns:
        Dict with name, sample_rate, channels, duration, frames.
    """
    try:
        return service.describe_audio(path, policy=service.load_policy())
    except (PermissionError, ValueError, FileNotFoundError) as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


@mcp.tool()
def measure_files(
    paths: list[str],
    include_f0: bool = True,
    max_concurrency: int = 1,
    out_csv: str | None = None,
) -> dict:
    """Measure multiple audio files and return analysis results.

    Args:
        paths: List of absolute audio file paths.
        include_f0: Include pitch (F0) analysis; serial, slower but more accurate.
        max_concurrency: Max concurrent measure analyses (clamped to 1-4).
        out_csv: Optional absolute path for CSV output file.

    Returns:
        Dict with schema_version, columns, rows, csv_path, errors.
    """
    try:
        return service.measure_files(
            paths,
            include_f0=include_f0,
            max_concurrency=max_concurrency,
            out_csv=out_csv,
            policy=service.load_policy(),
        )
    except (PermissionError, ValueError, FileNotFoundError) as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


@mcp.tool()
def read_measurements_csv(path: str) -> dict:
    """Read a previously written measurements CSV file.

    Args:
        path: Absolute path to the measurements CSV.

    Returns:
        Dict with schema_version, columns, rows.
    """
    try:
        return service.read_measurements_csv(path, policy=service.load_policy())
    except (PermissionError, ValueError, FileNotFoundError) as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


@mcp.resource("acouscope://schema/measurements")
def measurements_schema() -> str:
    """JSON schema for measurement results.

    Returns JSON with columns (13 field names) and status values
    (measured/partial/missing).
    """
    from acouscope.ui.widgets.multitrack.measure_summary import MEASUREMENT_COLUMNS

    return json.dumps({
        "columns": list(MEASUREMENT_COLUMNS),
        "status_values": ["measured", "partial", "missing"],
    })


@mcp.resource("acouscope://server/info")
def server_info() -> str:
    """Server identity and configuration source.

    Returns JSON with name, schema_version, transport, policy_source.
    """
    return json.dumps({
        "name": "AcouScope",
        "schema_version": "1",
        "transport": "stdio",
        "policy_source": "settings.json",
    })
