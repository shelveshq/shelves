"""
Studio CLI Tests — KAN-211

Tests for the shelves-studio CLI entry point and FastAPI server.
Covers: argument parsing, server startup, compile endpoint, file endpoints,
project tree endpoint, and graceful shutdown.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import FIXTURES_DIR, SubprocessOutputDrainer

# ─── Imports under test ──────────────────────────────────────────
# These will fail with ImportError until the module is created (expected red state).
from shelves.studio.cli import build_parser
from shelves.studio.server import create_app

# ─── Helpers ─────────────────────────────────────────────────────

PROJECT_DIR = FIXTURES_DIR  # tests/fixtures/ — has models/, yaml/, data/ subdirs


def _client():
    """Create a TestClient for the studio FastAPI app."""
    from starlette.testclient import TestClient

    app = create_app(project_dir=PROJECT_DIR)
    return TestClient(app)


# ─── CLI Argument Parsing ─────────────────────────────────────────


class TestCliArgumentParsing:
    def test_cli_argument_parsing_all_flags(self):
        """All CLI flags are parsed with correct types."""
        parser = build_parser()
        args = parser.parse_args(
            [
                "--port",
                "9000",
                "--no-browser",
                "--dir",
                "/tmp/project",
                "--theme",
                "mytheme.yaml",
                "--charts-dir",
                "/tmp/charts",
                "--dashboards-dir",
                "/tmp/dashboards",
                "--models-dir",
                "/tmp/models",
            ]
        )
        assert args.port == 9000
        assert args.no_browser is True
        assert args.dir == "/tmp/project"
        assert args.theme == "mytheme.yaml"
        assert args.charts_dir == "/tmp/charts"
        assert args.dashboards_dir == "/tmp/dashboards"
        assert args.models_dir == "/tmp/models"

    def test_cli_default_arguments(self):
        """Default values match the spec."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.port == 5173
        assert args.no_browser is False
        assert args.dir == "."
        assert args.theme is None
        assert args.charts_dir is None
        assert args.dashboards_dir is None
        assert args.models_dir is None

    def test_cli_port_must_be_int(self):
        """Non-integer port raises argparse error."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--port", "abc"])


# ─── Server: Index Page ──────────────────────────────────────────


class TestServerIndexPage:
    def test_get_root_returns_html(self):
        """GET / returns 200 with HTML content type and Shelves Studio title."""
        client = _client()
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<title>Shelves Studio</title>" in response.text
        # KAN-206: Monaco editor loaded via modular JS entry point
        assert "/static/js/main.js" in response.text
        assert 'id="editor"' in response.text
        assert 'id="preview"' in response.text

    def test_workspace_layout_structure(self):
        """GET / returns HTML with workspace layout regions."""
        client = _client()
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="toolbar"' in response.text
        assert 'id="editor-pane"' in response.text
        assert 'id="preview-pane"' in response.text

    def test_workspace_includes_vega_libraries(self):
        """GET / returns HTML with Vega CDN scripts and preview DOM elements."""
        client = _client()
        response = client.get("/")
        assert response.status_code == 200
        # KAN-207: Vega CDN scripts
        assert "vega-embed" in response.text
        # KAN-207: Preview DOM elements
        assert 'id="preview"' in response.text
        assert 'id="error-overlay"' in response.text
        assert 'id="json-view"' in response.text

    def test_workspace_includes_sidebar(self):
        """GET / returns HTML with file explorer sidebar DOM elements."""
        client = _client()
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="sidebar"' in response.text
        assert 'id="file-tree"' in response.text

    def test_workspace_includes_dashboard_elements(self):
        """GET / returns HTML with dashboard preview DOM elements."""
        client = _client()
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="dashboard-preview"' in response.text
        assert 'id="component-tree-strip"' in response.text
        assert 'data-view="dashboard"' in response.text

    def test_workspace_includes_terminal_panel(self):
        """GET / returns HTML with terminal panel DOM elements and xterm.js CDN."""
        client = _client()
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="terminal-panel"' in response.text
        assert 'id="terminal-tabs"' in response.text
        assert "xterm" in response.text


# ─── Monaco Worker Configuration ────────────────────────────────


class TestMonacoWorkerConfig:
    """The YAML web worker must be configured or Monaco will fail to load it."""

    def test_editor_js_configures_monaco_environment(self):
        """editor.js must set window.MonacoEnvironment so Monaco finds the YAML worker."""
        client = _client()
        response = client.get("/static/js/editor.js")
        assert response.status_code == 200
        assert "MonacoEnvironment" in response.text, (
            "editor.js must configure window.MonacoEnvironment with a getWorker function "
            "so Monaco can locate the YAML language worker"
        )

    def test_editor_js_handles_yaml_worker_label(self):
        """The MonacoEnvironment getWorker must handle the 'yaml' worker label."""
        client = _client()
        response = client.get("/static/js/editor.js")
        assert response.status_code == 200
        # The worker config must specifically handle YAML — this is the label
        # monaco-yaml registers with Monaco's language service
        assert "yaml.worker" in response.text, (
            "editor.js must reference yaml.worker in its MonacoEnvironment config "
            "so the YAML language service worker loads from the correct URL"
        )


# ─── Compile Endpoint ────────────────────────────────────────────


class TestCompileEndpoint:
    _VALID_YAML = """\
sheet: "Test"
data: orders
cols: country
rows: revenue
marks: bar
"""

    def test_compile_valid_yaml_returns_spec(self):
        """POST /compile with valid YAML returns vega_lite_spec and empty errors."""
        client = _client()
        response = client.post("/compile", content=self._VALID_YAML)
        assert response.status_code == 200
        body = response.json()
        assert body["errors"] == []
        spec = body["vega_lite_spec"]
        assert spec is not None
        assert spec["mark"] == "bar"
        assert spec["encoding"]["x"]["field"] == "country"
        assert spec["encoding"]["y"]["field"] == "revenue"

    def test_compile_invalid_yaml_returns_errors(self):
        """POST /compile with invalid YAML returns null spec and structured errors."""
        client = _client()
        bad_yaml = "sheet: Test\nmarks: bar\n"  # missing required data/rows/cols
        response = client.post("/compile", content=bad_yaml)
        assert response.status_code == 200
        body = response.json()
        assert body["vega_lite_spec"] is None
        assert len(body["errors"]) > 0
        assert body["warnings"] == []

    def test_compile_empty_body_returns_errors(self):
        """POST /compile with empty body returns structured errors, not 500."""
        client = _client()
        response = client.post("/compile", content="")
        assert response.status_code == 200
        body = response.json()
        assert body["vega_lite_spec"] is None
        assert len(body["errors"]) > 0

    def test_compile_dashboard_yaml_skips_chart_parse(self):
        """POST /compile with dashboard YAML returns null spec and no errors."""
        client = _client()
        dashboard_yaml = "dashboard: Superstore\nlayout:\n  type: grid\n"
        response = client.post("/compile", content=dashboard_yaml)
        assert response.status_code == 200
        body = response.json()
        # Dashboard files are not charts — compile should skip gracefully
        assert body["vega_lite_spec"] is None
        assert body["errors"] == []

    def test_compile_calls_resolve_data(self):
        """POST /compile calls resolve_data to bind data from models (e.g. Cube)."""
        from unittest.mock import patch

        from starlette.testclient import TestClient

        app = create_app(project_dir=PROJECT_DIR)
        client = TestClient(app)

        fake_rows = [{"country": "US", "revenue": 100}]

        def mock_resolve(spec, chart_spec, models_dir=None):
            import copy

            result = copy.deepcopy(spec)
            result["data"] = {"values": fake_rows}
            return result

        with patch("shelves.data.bind.resolve_data", side_effect=mock_resolve) as mock_rd:
            response = client.post("/compile", content=self._VALID_YAML)

        assert mock_rd.called, "Expected resolve_data to be called during compile"
        body = response.json()
        assert body["errors"] == []
        spec = body["vega_lite_spec"]
        assert spec is not None
        assert "data" in spec, "Expected resolve_data to bind data onto the spec"
        assert spec["data"]["values"] == fake_rows

    def test_compile_data_resolution_failure_returns_warning(self):
        """When resolve_data raises, compile still returns the spec with a warning."""
        from unittest.mock import patch

        from starlette.testclient import TestClient

        app = create_app(project_dir=PROJECT_DIR)
        client = TestClient(app)

        with patch(
            "shelves.data.bind.resolve_data",
            side_effect=ValueError("No Cube source configured"),
        ):
            response = client.post("/compile", content=self._VALID_YAML)

        body = response.json()
        # Spec should still be returned (not null) — data resolution failure is non-fatal
        assert body["vega_lite_spec"] is not None
        assert body["errors"] == []
        assert len(body["warnings"]) > 0
        assert "data" in body["warnings"][0].lower() or "cube" in body["warnings"][0].lower()


# ─── Schema Endpoint ─────────────────────────────────────────────


class TestSchemaEndpoint:
    def test_get_schema_returns_json_schema(self):
        """GET /schema returns a valid JSON Schema object."""
        client = _client()
        response = client.get("/schema")
        assert response.status_code == 200
        schema = response.json()
        assert schema["type"] == "object"
        assert "properties" in schema


# ─── Project Endpoint ────────────────────────────────────────────


class TestProjectEndpoint:
    def test_get_project_returns_tree(self):
        """GET /project returns a non-empty directory tree."""
        client = _client()
        response = client.get("/project")
        assert response.status_code == 200
        tree = response.json()
        # Should contain at least one entry from the fixtures dir
        assert isinstance(tree, list)
        assert len(tree) > 0

    def test_get_project_empty_dir(self, tmp_path):
        """GET /project for an empty directory returns an empty list."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path)
        client = TestClient(app)
        response = client.get("/project")
        assert response.status_code == 200
        assert response.json() == []

    def test_project_tree_structure(self):
        """Each tree entry has name and type fields."""
        client = _client()
        response = client.get("/project")
        tree = response.json()
        for entry in tree:
            assert "name" in entry
            assert "type" in entry
            assert entry["type"] in ("file", "dir")

    def test_project_tree_includes_path(self):
        """Each tree entry has a path field with relative path from project root."""
        client = _client()
        response = client.get("/project")
        tree = response.json()

        def check_paths(entries, prefix=""):
            for entry in entries:
                assert "path" in entry, f"Missing 'path' on entry: {entry}"
                if prefix:
                    assert entry["path"].startswith(prefix), (
                        f"Expected path to start with '{prefix}', got '{entry['path']}'"
                    )
                if entry["type"] == "dir" and "children" in entry:
                    check_paths(entry["children"], entry["path"] + "/")

        check_paths(tree)

    def test_project_tree_nested_path(self, tmp_path):
        """Nested directory paths are correctly constructed relative to project root."""
        from starlette.testclient import TestClient

        # Create nested structure: charts/sales/revenue.yaml
        (tmp_path / "charts" / "sales").mkdir(parents=True)
        (tmp_path / "charts" / "sales" / "revenue.yaml").write_text("sheet: test\n")

        app = create_app(project_dir=tmp_path)
        client = TestClient(app)
        response = client.get("/project")
        tree = response.json()

        # Find charts dir
        charts = next((e for e in tree if e["name"] == "charts"), None)
        assert charts is not None
        assert charts["path"] == "charts"

        # Find sales subdir
        sales = next((e for e in charts["children"] if e["name"] == "sales"), None)
        assert sales is not None
        assert sales["path"] == "charts/sales"

        # Find revenue.yaml file
        revenue = next((e for e in sales["children"] if e["name"] == "revenue.yaml"), None)
        assert revenue is not None
        assert revenue["path"] == "charts/sales/revenue.yaml"


# ─── File Endpoints ──────────────────────────────────────────────


class TestFileEndpoints:
    def test_get_file_returns_content(self):
        """GET /file?path=yaml/simple_bar.yaml returns file content."""
        client = _client()
        response = client.get("/file", params={"path": "yaml/simple_bar.yaml"})
        assert response.status_code == 200
        body = response.json()
        assert "content" in body
        assert "sheet:" in body["content"]

    def test_get_file_not_found(self):
        """GET /file for nonexistent file returns 404."""
        client = _client()
        response = client.get("/file", params={"path": "yaml/does_not_exist.yaml"})
        assert response.status_code == 404

    def test_get_file_path_traversal_rejected(self):
        """GET /file with path traversal attempt returns 400."""
        client = _client()
        response = client.get("/file", params={"path": "../../etc/passwd"})
        assert response.status_code == 400

    def test_put_file_writes_content(self, tmp_path):
        """PUT /file writes content to disk."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path)
        client = TestClient(app)

        content = "sheet: Test\nmarks: bar\n"
        response = client.put("/file", params={"path": "test.yaml"}, content=content)
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True

        written = (tmp_path / "test.yaml").read_text()
        assert written == content

    def test_put_file_path_traversal_rejected(self, tmp_path):
        """PUT /file with path traversal attempt returns 400."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path)
        client = TestClient(app)
        response = client.put("/file", params={"path": "../../evil.txt"}, content="pwned")
        assert response.status_code == 400


# ─── Graceful Shutdown ───────────────────────────────────────────


class TestGracefulShutdown:
    def test_graceful_shutdown_on_sigint(self, tmp_path):
        """SIGINT causes the server process to exit cleanly (exit code 0)."""
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "shelves.studio.cli",
                "--no-browser",
                "--port",
                "15173",
                "--dir",
                str(tmp_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Drain pipes so uvicorn output can't deadlock a full pipe buffer,
        # but keep the bytes around so we can surface them on failure.
        drainer = SubprocessOutputDrainer(proc)
        time.sleep(2.0)  # Give uvicorn time to start
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            drainer.join()
            pytest.fail(
                "Server did not exit within 5 seconds after SIGINT\n"
                f"STDOUT:\n{drainer.stdout_text}\n"
                f"STDERR:\n{drainer.stderr_text}"
            )
        drainer.join()
        assert proc.returncode == 0, (
            f"Expected exit 0, got {proc.returncode}\n"
            f"STDOUT:\n{drainer.stdout_text}\n"
            f"STDERR:\n{drainer.stderr_text}"
        )


# ─── Compile Dashboard Endpoint ─────────────────────────────────


class TestCompileDashboardEndpoint:
    _CHART_YAML = "sheet: Simple\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"

    _DASHBOARD_YAML = """\
dashboard: "Test Dashboard"
canvas:
  width: 1440
  height: 900
root:
  orientation: vertical
  contains:
    - sheet: simple.yaml
      name: revenue_chart
      width: "100%"
"""

    _DASHBOARD_TWO_SHEETS = """\
dashboard: "Two Sheet Dashboard"
canvas:
  width: 1440
  height: 900
root:
  orientation: vertical
  contains:
    - horizontal:
        contains:
          - sheet: simple.yaml
            name: sheet_a
            width: "50%"
          - sheet: simple.yaml
            name: sheet_b
            width: "50%"
"""

    def _make_project(self, tmp_path):
        (tmp_path / "charts").mkdir()
        (tmp_path / "charts" / "simple.yaml").write_text(self._CHART_YAML)

    def test_compile_dashboard_returns_html(self, tmp_path):
        """POST /compile-dashboard with valid YAML returns HTML and empty errors."""
        from starlette.testclient import TestClient

        self._make_project(tmp_path)
        app = create_app(project_dir=tmp_path)
        client = TestClient(app)

        response = client.post("/compile-dashboard", content=self._DASHBOARD_YAML)
        assert response.status_code == 200
        body = response.json()
        assert body["errors"] == []
        assert body["html"] is not None
        assert "<!DOCTYPE html>" in body["html"]
        assert isinstance(body["warnings"], list)
        assert isinstance(body["component_tree"], list)
        # Root node is vertical
        assert body["component_tree"][0]["type"] == "vertical"

    def test_compile_dashboard_component_tree_structure(self, tmp_path):
        """POST /compile-dashboard returns flat component_tree with correct structure."""
        from starlette.testclient import TestClient

        self._make_project(tmp_path)
        app = create_app(project_dir=tmp_path)
        client = TestClient(app)

        response = client.post("/compile-dashboard", content=self._DASHBOARD_TWO_SHEETS)
        assert response.status_code == 200
        body = response.json()
        assert body["errors"] == []
        tree = body["component_tree"]
        assert isinstance(tree, list)

        # Root node
        root = tree[0]
        assert root["depth"] == 0
        assert root["type"] == "vertical"

        # Children have depth 1
        children = [n for n in tree if n["depth"] == 1]
        assert len(children) > 0

        # Sheet nodes have type "sheet" and a link field
        sheets = [n for n in tree if n["type"] == "sheet"]
        assert len(sheets) == 2
        for s in sheets:
            assert "link" in s
            assert s["link"] == "simple.yaml"

    def test_compile_dashboard_invalid_yaml(self, tmp_path):
        """POST /compile-dashboard with invalid dashboard YAML returns errors."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path)
        client = TestClient(app)

        response = client.post("/compile-dashboard", content="dashboard: test\n")
        assert response.status_code == 200
        body = response.json()
        assert body["html"] is None
        assert len(body["errors"]) > 0
        assert body["warnings"] == []
        assert body["component_tree"] == []

    def test_compile_dashboard_missing_chart(self, tmp_path):
        """POST /compile-dashboard with a missing chart reference returns errors."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path)
        client = TestClient(app)

        yaml_body = """\
dashboard: "Missing Chart"
canvas:
  width: 1440
  height: 900
root:
  orientation: vertical
  contains:
    - sheet: nonexistent.yaml
      name: bad_sheet
      width: "100%"
"""
        response = client.post("/compile-dashboard", content=yaml_body)
        assert response.status_code == 200
        body = response.json()
        assert body["html"] is None
        assert len(body["errors"]) > 0
        assert any("not found" in e.lower() for e in body["errors"])
        assert body["component_tree"] == []


# ─── Terminal Endpoint ──────────────────────────────────────────


_LOCAL_ORIGIN_HEADERS = {"origin": "http://localhost"}


def _terminal_app_client():
    """Return (app, TestClient) so tests can read the terminal token."""
    from starlette.testclient import TestClient

    app = create_app(project_dir=PROJECT_DIR)
    return app, TestClient(app)


def _open_terminal_ws(app, client):
    """Open an authenticated /ws/terminal connection. Returns the cm."""
    ws_cm = client.websocket_connect("/ws/terminal", headers=_LOCAL_ORIGIN_HEADERS)
    return ws_cm


class TestTerminalEndpoint:
    def test_terminal_ws_rejects_cross_origin(self):
        """Non-loopback Origin handshakes are refused before any shell spawns."""
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        app = create_app(project_dir=PROJECT_DIR)
        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/terminal", headers={"origin": "https://evil.example.com"}
            ) as ws:
                ws.receive_text()

    def test_terminal_ws_rejects_null_origin(self):
        """Sandboxed-iframe style 'Origin: null' is rejected."""
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        app = create_app(project_dir=PROJECT_DIR)
        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/terminal", headers={"origin": "null"}) as ws:
                ws.receive_text()

    def test_terminal_ws_rejects_bad_token(self):
        """Wrong auth token closes the connection before spawning a PTY."""
        from starlette.websockets import WebSocketDisconnect

        app, client = _terminal_app_client()
        with pytest.raises(WebSocketDisconnect):
            with _open_terminal_ws(app, client) as ws:
                ws.send_json({"type": "auth", "token": "not-the-right-token"})
                # Server should close; receive raises WebSocketDisconnect
                ws.receive_text()

    def test_terminal_ws_rejects_missing_auth(self):
        """Sending a non-auth message first closes the connection."""
        from starlette.websockets import WebSocketDisconnect

        app, client = _terminal_app_client()
        with pytest.raises(WebSocketDisconnect):
            with _open_terminal_ws(app, client) as ws:
                ws.send_json({"type": "input", "data": "echo hello\r"})
                ws.receive_text()

    def test_terminal_ws_connects(self):
        """WebSocket connection to /ws/terminal is accepted and can be closed cleanly."""
        app, client = _terminal_app_client()
        with _open_terminal_ws(app, client) as ws:
            ws.send_json({"type": "auth", "token": app.state.terminal_token})
            # Authenticated — connection open
            assert ws is not None

    def test_terminal_ws_resize_message(self):
        """Server handles resize message without error; connection stays open."""
        app, client = _terminal_app_client()
        with _open_terminal_ws(app, client) as ws:
            ws.send_json({"type": "auth", "token": app.state.terminal_token})
            ws.send_json({"type": "resize", "rows": 24, "cols": 80})
            # No exception raised — connection remains open

    def test_terminal_ws_input_message(self):
        """Server writes input to PTY and returns at least one output message."""
        app, client = _terminal_app_client()
        with _open_terminal_ws(app, client) as ws:
            ws.send_json({"type": "auth", "token": app.state.terminal_token})
            ws.send_json({"type": "input", "data": "echo hello\r"})
            msg = ws.receive_json()
            assert msg["type"] == "output"
            assert "data" in msg
            import base64

            decoded = base64.b64decode(msg["data"])
            assert isinstance(decoded, bytes)

    def test_multiple_terminal_connections(self):
        """Each WebSocket connection gets an independent PTY; both can be closed."""
        app, client = _terminal_app_client()
        token = app.state.terminal_token
        with _open_terminal_ws(app, client) as ws1:
            ws1.send_json({"type": "auth", "token": token})
            with _open_terminal_ws(app, client) as ws2:
                ws2.send_json({"type": "auth", "token": token})
                assert ws1 is not None
                assert ws2 is not None
                ws1.send_json({"type": "resize", "rows": 30, "cols": 120})


# ─── PTY Manager ─────────────────────────────────────────────────


class TestPtyManagerCancellation:
    """
    Regression: PtyManager.read() must unregister its loop reader when the
    awaiting task is cancelled, so the fd can close cleanly and no callback
    fires on a closed fd.
    """

    def test_read_cancellation_removes_loop_reader(self):
        import asyncio
        import os
        import pty as _pty

        from shelves.studio.terminal import PtyManager

        async def _test():
            mgr = PtyManager()
            master, slave = _pty.openpty()
            # Inject the fd without spawning a shell — we only care about
            # the add_reader/remove_reader accounting here.
            mgr._master_fd = master
            loop = asyncio.get_running_loop()
            try:
                task = asyncio.create_task(mgr.read())
                # Let read() reach `await future` and register the reader.
                await asyncio.sleep(0)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                # remove_reader returns False when no reader is registered
                # for the fd — i.e. read() already cleaned up.
                assert loop.remove_reader(master) is False
            finally:
                os.close(master)
                os.close(slave)

        asyncio.run(_test())


# ─── Edge Cases ──────────────────────────────────────────────────


class TestCliValidation:
    def test_nonexistent_dir_exits_nonzero(self, tmp_path):
        """--dir pointing to a nonexistent path exits with code 1."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "shelves.studio.cli",
                "--no-browser",
                "--dir",
                "/nonexistent_shelves_test_path_xyz",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()

    def test_dir_is_file_exits_nonzero(self):
        """--dir pointing to a file exits with code 1."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "shelves.studio.cli",
                "--no-browser",
                "--dir",
                "pyproject.toml",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        assert (
            "not a directory" in result.stderr.lower() or "not a directory" in result.stdout.lower()
        )
