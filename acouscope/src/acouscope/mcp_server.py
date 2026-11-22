# SPDX-License-Identifier: GPL-3.0-only
"""AcouScope MCP stdio server entry point.

Run as: python -m acouscope.mcp_server
Or via installed script: acouscope-mcp

Implements JSON-RPC over stdio. stdout is reserved for RPC frames;
all logging and diagnostics go to stderr.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    """Start the MCP server on stdio transport."""
    # Resolve the package's src directory for import path (dev mode)
    pkg_dir = Path(__file__).resolve().parent.parent
    if str(pkg_dir) not in sys.path:
        sys.path.insert(0, str(pkg_dir))

    try:
        from acouscope.mcp.server import mcp
    except ImportError as exc:
        sys.stderr.write(f"acouscope-mcp: missing dependency: {exc}\n")
        sys.stderr.write("Install with: pip install \"mcp>=1.30.0,<2\"\n")
        sys.exit(2)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
