"""
Shelves Studio CLI — `shelves-studio` entry point

Usage:
  shelves-studio                    # start on localhost:5173, open browser
  shelves-studio --port 8080        # custom port
  shelves-studio --no-browser       # skip auto-open
  shelves-studio --dir myproject/   # project directory
  shelves-studio --theme mytheme.yaml
  shelves-studio --charts-dir src/charts --models-dir src/models

Starts a FastAPI dev server and (by default) opens a browser tab.
Press Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser for shelves-studio.

    Returns an ArgumentParser with:
      --port      int, default 5173
      --no-browser flag (skip browser auto-open)
      --dir       str, default "." (project directory)
      --theme     str, optional (path to theme YAML)
    """
    parser = argparse.ArgumentParser(
        prog="shelves-studio",
        description="Shelves Studio — local dev server for chart and dashboard authoring",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5173,
        help="Port to listen on (default: 5173)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="Skip auto-opening a browser tab",
    )
    parser.add_argument(
        "--dir",
        default=".",
        help="Project directory to serve (default: current directory)",
    )
    parser.add_argument(
        "--theme",
        default=None,
        help="Path to a custom theme YAML file",
    )
    parser.add_argument(
        "--charts-dir",
        default=None,
        help="Directory containing chart YAML files (default: <dir>/charts)",
    )
    parser.add_argument(
        "--dashboards-dir",
        default=None,
        help="Directory containing dashboard YAML files (default: <dir>/dashboards)",
    )
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Directory containing model YAML files (default: <dir>/models)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Auto-reload the server when Shelves source files change (dev mode)",
    )
    return parser


def _app_from_env() -> FastAPI:
    """uvicorn app factory for ``--reload`` mode.

    The reloader runs the app in a subprocess that re-imports it, so the
    configuration can't be passed as constructor args — main() stashes it in
    environment variables before calling ``uvicorn.run(..., reload=True)`` and
    this factory reads them back out.
    """
    from shelves.studio.server import create_app

    def _opt_path(key: str) -> Path | None:
        val = os.environ.get(key)
        return Path(val) if val else None

    return create_app(
        project_dir=Path(os.environ["SHELVES_STUDIO_DIR"]),
        theme_path=_opt_path("SHELVES_STUDIO_THEME"),
        models_dir=_opt_path("SHELVES_STUDIO_MODELS_DIR"),
        charts_dir=_opt_path("SHELVES_STUDIO_CHARTS_DIR"),
        dashboards_dir=_opt_path("SHELVES_STUDIO_DASHBOARDS_DIR"),
    )


def main() -> None:
    """Entry point for the shelves-studio CLI command."""
    import uvicorn
    from dotenv import load_dotenv

    from shelves.studio.server import create_app

    load_dotenv()  # Load environment variables from .env file (for CUBE_API_URL, etc.)

    parser = build_parser()
    args = parser.parse_args()

    # Validate --dir
    project_dir = Path(args.dir).resolve()
    if not project_dir.exists():
        print(f"Error: Directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)
    if not project_dir.is_dir():
        print(f"Error: Not a directory: {args.dir}", file=sys.stderr)
        sys.exit(1)

    # Resolve --theme
    theme_path: Path | None = None
    if args.theme:
        theme_path = Path(args.theme).resolve()

    # Resolve directory overrides (default to subdirs of project_dir)
    models_dir = Path(args.models_dir).resolve() if args.models_dir else None
    charts_dir = Path(args.charts_dir).resolve() if args.charts_dir else None
    dashboards_dir = Path(args.dashboards_dir).resolve() if args.dashboards_dir else None

    # Build the app
    app = create_app(
        project_dir=project_dir,
        theme_path=theme_path,
        models_dir=models_dir,
        charts_dir=charts_dir,
        dashboards_dir=dashboards_dir,
    )

    url = f"http://localhost:{args.port}"

    # Print startup banner (mirrors shelves-dev style)
    print("Shelves Studio")
    print(f"  Project:     {project_dir}")
    print(f"  Charts:      {app.state.charts_dir}")
    print(f"  Dashboards:  {app.state.dashboards_dir}")
    print(f"  Models:      {app.state.models_dir}")
    print(f"  Theme:       {theme_path or 'Default'}")
    print(f"  Preview:     {url}")
    print("  Press Ctrl+C to stop\n")

    # Schedule browser open after a short delay (gives uvicorn time to bind)
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()

    # uvicorn handles SIGINT/SIGTERM gracefully
    if args.reload:
        # Reload needs an import string + factory: the reloader re-imports the
        # app in a worker subprocess, so config travels via env vars (read back
        # by _app_from_env). Watch the shelves package for .py changes.
        os.environ["SHELVES_STUDIO_DIR"] = str(project_dir)
        if theme_path:
            os.environ["SHELVES_STUDIO_THEME"] = str(theme_path)
        if models_dir:
            os.environ["SHELVES_STUDIO_MODELS_DIR"] = str(models_dir)
        if charts_dir:
            os.environ["SHELVES_STUDIO_CHARTS_DIR"] = str(charts_dir)
        if dashboards_dir:
            os.environ["SHELVES_STUDIO_DASHBOARDS_DIR"] = str(dashboards_dir)
        uvicorn.run(
            "shelves.studio.cli:_app_from_env",
            factory=True,
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
            reload=True,
            reload_dirs=[str(Path(__file__).resolve().parents[1])],
        )
    else:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
