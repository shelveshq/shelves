"""
CLI: Live-preview dev server for chart and dashboard YAML files

Usage:
  python -m src.cli.dev tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json
  python -m src.cli.dev tests/fixtures/yaml/cube_sales_by_category.yaml
  python -m src.cli.dev tests/fixtures/yaml/simple_bar.yaml --port 8089
  python -m src.cli.dev tests/fixtures/layout/compose_minimal.yaml --chart-dir tests/fixtures/yaml

Opens a local HTTP server with auto-reload. Edit your YAML on the left,
browser on the right — changes appear on save.

Automatically detects dashboard files (presence of 'dashboard' key) and
routes through the dashboard composition pipeline.

When --data is omitted for charts, fetches from Cube.dev (requires CUBE_API_URL
and CUBE_API_TOKEN environment variables).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import yaml as yaml_lib
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.schema.chart_schema import parse_chart
from src.translator.translate import translate_chart
from src.theme.merge import merge_theme, load_theme
from src.data.bind import resolve_data
from src.render.to_html import render_html

from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file (for CUBE_API_URL, etc.)

# Auto-reload snippet injected into served HTML
_RELOAD_SCRIPT = """
<script>
(function() {
  let lastModified = null;
  setInterval(async () => {
    try {
      const resp = await fetch('/__timestamp');
      const ts = await resp.text();
      if (lastModified && ts !== lastModified) location.reload();
      lastModified = ts;
    } catch(e) {}
  }, 500);
})();
</script>
"""


class _State:
    """Shared mutable state between watcher and server."""

    def __init__(self):
        self.html: str = ""
        self.timestamp: str = ""


def _build(
    yaml_path: Path,
    data_path: Path | None,
    no_theme: bool,
    theme_path: Path | None,
    state: _State,
    chart_dir: Path | None = None,
    data_dir: Path | None = None,
    models_dir: Path | None = None,
):
    """Re-run the full pipeline and update state."""
    try:
        yaml_string = yaml_path.read_text()
        raw = yaml_lib.safe_load(yaml_string)

        if "dashboard" in raw:
            html = _build_dashboard(
                yaml_path, no_theme, theme_path, chart_dir, data_dir, models_dir
            )
        else:
            html = _build_chart(yaml_string, data_path, no_theme, theme_path)

        # Inject auto-reload script before </body>
        html = html.replace("</body>", f"{_RELOAD_SCRIPT}</body>")
        state.html = html
        state.timestamp = str(time.time())
        print(f"  Rebuilt: {yaml_path.name} ({time.strftime('%H:%M:%S')})")
    except Exception as e:
        # Show error in browser instead of crashing
        state.html = f"""<!DOCTYPE html>
<html><head><title>Charter Error</title></head>
<body style="font-family:monospace;padding:24px;background:#fff0f0">
<h2 style="color:#c00">Build Error</h2>
<pre>{e}</pre>
{_RELOAD_SCRIPT}
</body></html>"""
        state.timestamp = str(time.time())
        print(f"  Error: {e}")


def _build_chart(
    yaml_string: str, data_path: Path | None, no_theme: bool, theme_path: Path | None
) -> str:
    """Build a single chart and return HTML."""
    spec = parse_chart(yaml_string)
    vl_spec = translate_chart(spec)

    if not no_theme:
        theme = load_theme(theme_path)
        vl_spec = merge_theme(vl_spec, theme)

    # Data: inline JSON if --data provided, otherwise try model source or Cube
    if data_path:
        rows = json.loads(data_path.read_text())
        vl_spec = resolve_data(vl_spec, spec, rows=rows)
    else:
        from src.models.loader import load_model

        model = load_model(spec.data)
        if model.source and model.source.type == "inline":
            model_data_path = Path(model.source.path)
            if model_data_path.exists():
                rows = json.loads(model_data_path.read_text())
                vl_spec = resolve_data(vl_spec, spec, rows=rows)
            else:
                print(f"Warning: model source path {model_data_path} not found")
        else:
            vl_spec = resolve_data(vl_spec, spec)

    # Dev preview: large chart for easy visual inspection
    vl_spec.setdefault("width", 1400)
    vl_spec.setdefault("height", 800)

    return render_html(vl_spec, title=spec.sheet)


def _build_dashboard(
    yaml_path: Path,
    no_theme: bool,
    theme_path: Path | None,
    chart_dir: Path | None,
    data_dir: Path | None,
    models_dir: Path | None,
) -> str:
    """Build a dashboard and return HTML."""
    from src.compose.dashboard import compose_dashboard

    theme = load_theme(theme_path) if not no_theme else None

    return compose_dashboard(
        dashboard_path=yaml_path,
        theme=theme,
        chart_base_dir=chart_dir,
        data_dir=data_dir,
        models_dir=models_dir,
        no_theme=no_theme,
    )


class _YAMLWatcher(FileSystemEventHandler):
    def __init__(
        self,
        yaml_path,
        data_path,
        no_theme,
        theme_path,
        state,
        chart_dir=None,
        data_dir=None,
        models_dir=None,
    ):
        self._yaml_path = yaml_path
        self._data_path = data_path
        self._no_theme = no_theme
        self._theme_path = theme_path
        self._state = state
        self._chart_dir = chart_dir
        self._data_dir = data_dir
        self._models_dir = models_dir

    def on_modified(self, event):
        if Path(os.fsdecode(event.src_path)).resolve() == self._yaml_path.resolve():
            _build(
                self._yaml_path,
                self._data_path,
                self._no_theme,
                self._theme_path,
                self._state,
                self._chart_dir,
                self._data_dir,
                self._models_dir,
            )


def _make_handler(state: _State):
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/__timestamp":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(state.timestamp.encode())
            elif self.path == "/" or self.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(state.html.encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # suppress request logs

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="Live-preview dev server for chart and dashboard YAML"
    )
    parser.add_argument("yaml_path", help="Path to chart or dashboard YAML file")
    parser.add_argument("--data", help="Path to JSON data file")
    parser.add_argument("--port", type=int, default=8089, help="Server port (default: 8089)")
    parser.add_argument(
        "--no-theme", action="store_true", help="Skip theme merging (takes priority over --theme)"
    )
    parser.add_argument("--theme", help="Path to custom theme YAML file")
    parser.add_argument(
        "--chart-dir", help="Base directory for resolving chart link paths in dashboards"
    )
    parser.add_argument(
        "--data-dir",
        help="Base directory for resolving inline data source paths in dashboards (default: CWD)",
    )
    parser.add_argument(
        "--models-dir",
        help="Directory containing model YAML files for dashboards",
    )
    args = parser.parse_args()

    yaml_path = Path(args.yaml_path).resolve()
    data_path = Path(args.data).resolve() if args.data else None
    theme_path = Path(args.theme).resolve() if args.theme else None
    chart_dir = Path(args.chart_dir).resolve() if args.chart_dir else None
    data_dir = Path(args.data_dir).resolve() if args.data_dir else None
    models_dir = Path(args.models_dir).resolve() if args.models_dir else None

    if not yaml_path.exists():
        print(f"Error: {yaml_path} not found")
        return

    # Detect mode
    raw = yaml_lib.safe_load(yaml_path.read_text())
    is_dashboard = "dashboard" in raw

    state = _State()

    # Initial build
    print("Charter Dev Server")
    print(f"  Watching: {yaml_path}")
    if is_dashboard:
        print("  Mode:     Dashboard")
        if chart_dir:
            print(f"  Charts:   {chart_dir}")
        if data_dir:
            print(f"  Data dir: {data_dir}")
        if models_dir:
            print(f"  Models:   {models_dir}")
    else:
        print("  Mode:     Chart")
        if data_path:
            print(f"  Data:     {data_path}")
        else:
            print("  Data:     Cube.dev (from CUBE_API_URL)")
    print(f"  Theme:    {'None' if args.no_theme else (theme_path or 'Default')}")
    _build(yaml_path, data_path, args.no_theme, theme_path, state, chart_dir, data_dir, models_dir)

    # File watcher
    observer = Observer()
    handler = _YAMLWatcher(
        yaml_path, data_path, args.no_theme, theme_path, state, chart_dir, data_dir, models_dir
    )
    observer.schedule(handler, str(yaml_path.parent), recursive=False)
    observer.start()

    # HTTP server
    server = HTTPServer(("127.0.0.1", args.port), _make_handler(state))
    print(f"  Preview:  http://localhost:{args.port}")
    print("  Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
        observer.stop()
        observer.join()
        server.server_close()


if __name__ == "__main__":
    main()
