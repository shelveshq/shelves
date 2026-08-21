"""
`shelves-mcp` entry point (SHE-55).

Launches the stdio MCP discovery server from the project root. The `init`
subcommand (`.mcp.json` generation) is reserved for SHE-59.
"""

from __future__ import annotations

import argparse
import sys

from shelves.mcp.tools import MCPContext

_MISSING_SDK_HINT = (
    "The MCP server needs the 'mcp' package. Install it with:\n    pip install \"shelves-bi[mcp]\""
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shelves-mcp",
        description="Shelves MCP server: expose the semantic model to coding agents.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project root (default: current working directory).",
    )
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Directory of model YAMLs (default: <project-dir>/models).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = MCPContext.create(project_dir=args.project_dir, models_dir=args.models_dir)

    # The `mcp` SDK is imported lazily inside `build_server`, so a missing SDK
    # surfaces when the server is built (inside `serve`), not at import time —
    # `serve(ctx)` must be inside the try, or the install hint never fires.
    try:
        from shelves.mcp.server import serve

        serve(ctx)
    except ModuleNotFoundError as e:
        if e.name == "mcp" or (e.name or "").startswith("mcp."):
            print(_MISSING_SDK_HINT, file=sys.stderr)
            return 1
        raise

    return 0


if __name__ == "__main__":
    sys.exit(main())
