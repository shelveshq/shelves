"""
Shelves Studio CLI — `shelves-studio` entry point

Usage:
  shelves-studio                    # start on localhost:5173, open browser
  shelves-studio --port 8080        # custom port
  shelves-studio --no-browser       # skip auto-open
  shelves-studio --dir charts/      # project directory
  shelves-studio --theme mytheme.yaml

Starts a FastAPI dev server and (by default) opens a browser tab.
Press Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path


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
    return parser


def main() -> None:
    """Entry point for the shelves-studio CLI command."""
    import uvicorn

    from shelves.studio.server import create_app

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

    # Build the app
    app = create_app(project_dir=project_dir, theme_path=theme_path)

    url = f"http://localhost:{args.port}"

    # Print startup banner (mirrors shelves-dev style)
    print("Shelves Studio")
    print(f"  Project:  {project_dir}")
    print(f"  Preview:  {url}")
    print(f"  Theme:    {theme_path or 'Default'}")
    print("  Press Ctrl+C to stop\n")

    # Schedule browser open after a short delay (gives uvicorn time to bind)
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()

    # uvicorn handles SIGINT/SIGTERM gracefully
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
