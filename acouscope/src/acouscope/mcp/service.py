# SPDX-License-Identifier: GPL-3.0-only
"""MCP service layer — pure functions with zero Qt / mcp dependency.

Provides policy loading, path validation, audio description, file measurement,
CSV I/O, and host config generation for the AcouScope MCP server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

# Audio I/O (no Qt)
from acouscope.audio.io import AudioIO

# Multitrack analysis stack (no Qt — only the data/analysis layers)
from acouscope.ui.widgets.multitrack.analysis_source import (
    MEASURE_KIND,
    AnalysisSource,
    TrackResultCache,
    run_analysis_on_tracks,
)
from acouscope.ui.widgets.multitrack.measure_summary import (
    MEASUREMENT_COLUMNS,
    read_measurements_csv as _read_measurements_csv,
    rows_from_cache,
    write_measurements_csv as _write_measurements_csv,
)

# Config
from acouscope.utils.config import Settings

# Logging (writes to stderr only, never stdout)
from acouscope.utils.log import get_logger

logger = get_logger("acouscope.mcp.service")


class _SessionShim:
    """Lightweight shim providing only tracks() for rows_from_cache.

    Avoids importing MultitrackSession (which requires theme.track_palette()).
    """

    def __init__(self, track_infos):
        self._track_infos = list(track_infos)

    def tracks(self):
        return self._track_infos


def load_policy(settings_path=None) -> dict:
    """Load MCP policy from settings.

    Returns a policy dict with keys:
        enabled: bool
        allowed_roots: tuple[Path, ...]
        out_dir: Path | None
        max_files: int (32)
        max_total_bytes: int (512 MiB)
    """
    if settings_path is not None:
        s = Settings.load(filepath=Path(settings_path))
    else:
        s = Settings.load()

    enabled = bool(getattr(s, "mcp_enabled", False))
    raw_roots = getattr(s, "mcp_allowed_roots", "") or ""
    out_dir_str = getattr(s, "mcp_out_dir", "") or ""

    allowed_roots: list[Path] = []
    if enabled and raw_roots:
        for part in raw_roots.split(os.pathsep):
            part = part.strip()
            if not part:
                continue
            try:
                resolved = Path(part).resolve(strict=True)
                allowed_roots.append(resolved)
            except (OSError, ValueError):
                logger.warning("mcp: skipping invalid allowed_root %r", part)

    out_dir = None
    if enabled and out_dir_str:
        try:
            out_dir = Path(out_dir_str.strip()).resolve(strict=True)
        except (OSError, ValueError):
            logger.warning("mcp: skipping invalid out_dir %r", out_dir_str)

    if not enabled or not allowed_roots:
        allowed_roots = ()

    return {
        "enabled": enabled,
        "allowed_roots": tuple(allowed_roots),
        "out_dir": out_dir,
        "max_files": 32,
        "max_total_bytes": 512 * 1024 * 1024,
    }


def validate_path(
    path,
    policy: dict,
    *,
    for_write: bool = False,
    allow_csv: bool = False,
) -> Path:
    """Validate a path against MCP policy.

    Raises PermissionError, FileNotFoundError, or ValueError on violation.
    Returns the resolved Path on success.
    """
    p = Path(path).resolve()

    if not policy["allowed_roots"]:
        raise PermissionError("mcp policy: no allowed roots configured")

    # Resolve roots for comparison (macOS /var/folders is a symlink)
    resolved_roots = [Path(r).resolve() for r in policy["allowed_roots"]]

    # Check against allowed roots (always required)
    in_root = any(p.is_relative_to(r) for r in resolved_roots)
    if not in_root:
        raise PermissionError(
            f"mcp policy: {path} not within any allowed root"
        )

    # Additional check for write targets: must also be within out_dir
    if for_write:
        if policy["out_dir"] is None:
            raise PermissionError("mcp policy: write target but no out_dir configured")
        resolved_out = Path(policy["out_dir"]).resolve()
        if not p.is_relative_to(resolved_out):
            raise PermissionError(
                f"mcp policy: {path} not within out_dir {policy['out_dir']}"
            )

    # Extension check (single source of truth: AudioIO.SOUNDFILE_FORMATS + optional .csv)
    if allow_csv:
        ext_ok = p.suffix.lower() in (set(AudioIO.SOUNDFILE_FORMATS) | {".csv"})
    else:
        ext_ok = p.suffix.lower() in AudioIO.SOUNDFILE_FORMATS
    if not ext_ok:
        raise ValueError(f"mcp policy: unsupported extension {p.suffix!r} for {path}")

    # File existence (skip for write targets — they will be created)
    if not for_write:
        if not p.exists():
            raise FileNotFoundError(f"mcp policy: {path} does not exist")
        if not p.is_file():
            raise FileNotFoundError(f"mcp policy: {path} is not a file")

    return p


def _to_python_scalar(value):
    """Convert numpy scalar to Python scalar; pass through otherwise."""
    if isinstance(value, np.generic):
        return value.item()
    return value


def describe_audio(path, *, policy: dict) -> dict:
    """Describe an audio file without loading samples."""
    p = validate_path(path, policy)
    info = AudioIO().get_info(p)
    return {
        "name": p.name,
        "sample_rate": info.sample_rate,
        "channels": info.channels,
        "duration": float(info.duration),
        "frames": int(info.samples),
    }


def measure_files(
    paths,
    *,
    include_f0: bool = True,
    max_concurrency: int = 1,
    out_csv=None,
    policy: dict | None = None,
) -> dict:
    """Measure multiple audio files using the existing analysis chain.

    Returns a dict with schema_version, columns, rows, csv_path, errors.
    """
    if policy is None:
        policy = load_policy()

    paths = list(paths)
    if not paths:
        raise ValueError("mcp: no input paths provided")
    if len(paths) > policy["max_files"]:
        raise ValueError(
            f"mcp: {len(paths)} files exceeds max_files={policy['max_files']}"
        )

    # Validate all paths first (fail fast)
    validated: list[Path] = []
    total_bytes = 0
    for p in paths:
        vp = validate_path(p, policy)
        validated.append(vp)
        try:
            total_bytes += vp.stat().st_size
        except OSError:
            pass

    if total_bytes > policy["max_total_bytes"]:
        raise ValueError(
            f"mcp: total size {total_bytes} exceeds max_total_bytes={policy['max_total_bytes']}"
        )

    # Clamp concurrency to [1, 4]
    max_concurrency = min(4, max(1, int(max_concurrency)))

    # Build track_infos for the session shim
    track_infos = []
    sources = []
    audio = AudioIO()

    for i, vp in enumerate(validated):
        track_id = str(i)
        source_name = vp.stem

        try:
            data, sample_rate = audio.load(vp)
        except Exception as exc:
            logger.error("mcp: failed to load %s: %s", vp, exc)
            track_infos.append(
                {"track_id": track_id, "label": vp.name, "offset_ms": 0.0}
            )
            sources.append(AnalysisSource(source_name, None, None, track_id=track_id))
            continue

        sources.append(
            AnalysisSource(source_name, data, sample_rate, track_id=track_id)
        )
        track_infos.append(
            {"track_id": track_id, "label": vp.name, "offset_ms": 0.0}
        )

    # Create a lightweight session shim (only needs tracks())
    def make_track_info(info):
        class Info:
            pass
        o = Info()
        o.track_id = info["track_id"]
        o.label = info["label"]
        o.offset_ms = info["offset_ms"]
        return o

    shim_tracks = [make_track_info(t) for t in track_infos]
    session_shim = _SessionShim(shim_tracks)

    # Run measure analysis (concurrent)
    cache = TrackResultCache()
    errors: list[str] = []

    try:
        handles = run_analysis_on_tracks(
            sources,
            MEASURE_KIND,
            cache=cache,
            max_concurrency=max_concurrency,
        )
    except Exception as exc:
        errors.append(f"measure run failed: {type(exc).__name__}: {exc}")

    # Run pitch analysis (serial) if requested
    if include_f0:
        try:
            run_analysis_on_tracks(
                sources,
                "pitch",
                cache=cache,
            )
        except Exception as exc:
            errors.append(f"pitch run failed: {type(exc).__name__}: {exc}")

    # Extract rows from cache
    raw_rows = rows_from_cache(session_shim, cache)

    # Convert numpy scalars to Python floats in the returned rows
    rows = []
    for row in raw_rows:
        clean_row = {}
        for key, value in row.items():
            clean_row[key] = _to_python_scalar(value)
        rows.append(clean_row)

    result = {
        "schema_version": "1",
        "columns": tuple(MEASUREMENT_COLUMNS),
        "rows": rows,
        "csv_path": None,
        "errors": errors,
    }

    # Write CSV if requested
    if out_csv is not None:
        csv_path = validate_path(out_csv, policy, for_write=True, allow_csv=True)
        try:
            _write_measurements_csv(csv_path, rows)
            result["csv_path"] = str(csv_path)
        except Exception as exc:
            errors.append(f"csv write failed: {exc}")

    return result


def read_measurements_csv(path, *, policy: dict) -> dict:
    """Read a previously written measurements CSV."""
    p = validate_path(path, policy, allow_csv=True)
    rows = _read_measurements_csv(p)
    # Convert numpy scalars in read-back values
    clean_rows = []
    for row in rows:
        clean_row = {}
        for key, value in row.items():
            clean_row[key] = _to_python_scalar(value)
        clean_rows.append(clean_row)
    return {
        "schema_version": "1",
        "columns": tuple(MEASUREMENT_COLUMNS),
        "rows": clean_rows,
    }


def build_host_config() -> dict:
    """Generate host-side MCP server config (without starting anything)."""
    # Determine the src directory of this package
    pkg_dir = Path(__file__).resolve()
    # Walk up to find the src directory containing acouscope/
    while pkg_dir.name != "src" and pkg_dir.parent != pkg_dir:
        if (pkg_dir / "acouscope").is_dir():
            break
        pkg_dir = pkg_dir.parent

    return {
        "mcpServers": {
            "acouscope": {
                "command": sys.executable,
                "args": ["-m", "acouscope.mcp_server"],
                "env": {
                    "PYTHONPATH": str(pkg_dir),
                },
            }
        }
    }
