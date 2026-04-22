"""
Studio WebSocket + File Watcher Tests — KAN-205

Tests for:
  - should_compile() filter function
  - ConnectionManager broadcast logic
  - WebSocket /ws endpoint lifecycle
  - Full watcher→compile→broadcast integration (via subprocess + real server)
"""

from __future__ import annotations

import asyncio
import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock


from tests.conftest import MODELS_DIR, SubprocessOutputDrainer

from shelves.studio.server import (
    ConnectionManager,
    _compile_file_and_broadcast,
    create_app,
)
from shelves.studio.watcher import COMPILE_EXTENSIONS, WATCH_EXTENSIONS, should_compile

# ─── Helpers ─────────────────────────────────────────────────────

VALID_YAML = """\
sheet: "WS Test"
data: orders
cols: country
rows: revenue
marks: bar
"""

INVALID_YAML = """\
sheet: "Bad"
marks: bar
"""

_SERVER_PORT = 15175  # unique port for WS integration tests


def _setup_project(tmp_path: Path) -> Path:
    """Create a project dir with the orders model fixture."""
    (tmp_path / "models").mkdir()
    shutil.copy(MODELS_DIR / "orders.yaml", tmp_path / "models" / "orders.yaml")
    return tmp_path


# ─── should_compile() — pure function ────────────────────────────


class TestShouldCompile:
    def test_yaml_extension_triggers_compile(self):
        assert should_compile(Path("charts/revenue.yaml")) is True

    def test_yml_extension_triggers_compile(self):
        assert should_compile(Path("charts/revenue.yml")) is True

    def test_json_does_not_trigger_compile(self):
        assert should_compile(Path("data/orders.json")) is False

    def test_py_does_not_trigger_compile(self):
        assert should_compile(Path("schema.py")) is False

    def test_no_extension_does_not_trigger_compile(self):
        assert should_compile(Path("Makefile")) is False

    def test_compile_extensions_constant(self):
        assert ".yaml" in COMPILE_EXTENSIONS
        assert ".yml" in COMPILE_EXTENSIONS
        assert ".json" not in COMPILE_EXTENSIONS

    def test_watch_extensions_constant(self):
        assert ".yaml" in WATCH_EXTENSIONS
        assert ".yml" in WATCH_EXTENSIONS
        assert ".json" in WATCH_EXTENSIONS


# ─── ConnectionManager — unit tests ──────────────────────────────


class TestConnectionManager:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_connect_increments_client_count(self):
        async def _test():
            manager = ConnectionManager()
            ws = AsyncMock()
            await manager.connect(ws)
            assert manager.client_count == 1
            ws.accept.assert_awaited_once()

        self._run(_test())

    def test_disconnect_decrements_client_count(self):
        async def _test():
            manager = ConnectionManager()
            ws = AsyncMock()
            await manager.connect(ws)
            manager.disconnect(ws)
            assert manager.client_count == 0

        self._run(_test())

    def test_disconnect_nonexistent_client_is_safe(self):
        async def _test():
            manager = ConnectionManager()
            ws = AsyncMock()
            manager.disconnect(ws)  # should not raise
            assert manager.client_count == 0

        self._run(_test())

    def test_broadcast_sends_to_all_clients(self):
        async def _test():
            manager = ConnectionManager()
            ws1 = AsyncMock()
            ws2 = AsyncMock()
            await manager.connect(ws1)
            await manager.connect(ws2)
            msg = {"type": "compile_result", "path": "chart.yaml"}
            await manager.broadcast(msg)
            ws1.send_json.assert_awaited_once_with(msg)
            ws2.send_json.assert_awaited_once_with(msg)

        self._run(_test())

    def test_broadcast_removes_dead_client(self):
        async def _test():
            manager = ConnectionManager()
            ws_alive = AsyncMock()
            ws_dead = AsyncMock()
            ws_dead.send_json.side_effect = RuntimeError("connection closed")
            await manager.connect(ws_alive)
            await manager.connect(ws_dead)
            msg = {"type": "test"}
            await manager.broadcast(msg)
            # Dead client removed
            assert manager.client_count == 1
            # Alive client still received the message
            ws_alive.send_json.assert_awaited_once_with(msg)

        self._run(_test())

    def test_broadcast_to_empty_manager_is_safe(self):
        async def _test():
            manager = ConnectionManager()
            await manager.broadcast({"type": "test"})  # no-op, no crash

        self._run(_test())


# ─── WebSocket endpoint — TestClient ─────────────────────────────


class TestWebSocketEndpoint:
    def test_ws_connect_disconnect(self, tmp_path):
        """WebSocket connects and disconnects without errors."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path)
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                # Connected — server accepted without error
                # Close cleanly
                ws.close()

    def test_ws_connect_multiple_clients(self, tmp_path):
        """Multiple WebSocket clients can connect simultaneously."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path)
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws1:
                with client.websocket_connect("/ws") as ws2:
                    ws1.close()
                    ws2.close()


# ─── Default theme applied without --theme ───────────────────────


class TestDefaultThemeInCompile:
    """/compile and file watcher must apply the default theme even when
    no --theme path is passed to shelves-studio."""

    _CHART_YAML = "sheet: S\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"

    def test_compile_endpoint_applies_default_theme(self, tmp_path):
        """POST /compile with no theme_path returns a spec with config.title tokens."""
        from starlette.testclient import TestClient

        app = create_app(project_dir=tmp_path, theme_path=None, models_dir=MODELS_DIR)
        with TestClient(app) as client:
            resp = client.post("/compile", content=self._CHART_YAML)
        assert resp.status_code == 200
        body = resp.json()
        assert body["errors"] == [], body["errors"]
        spec = body["vega_lite_spec"]
        assert spec is not None
        assert "config" in spec, "Default theme not applied — config missing"
        assert "title" in spec["config"], "config.title missing from default theme"
        title_cfg = spec["config"]["title"]
        assert "subtitleFontSize" in title_cfg
        assert "anchor" in title_cfg
        assert "offset" in title_cfg

    def test_watcher_broadcast_applies_default_theme(self, tmp_path):
        """_compile_file_and_broadcast with theme_path=None includes config."""

        async def _test():
            chart_path = tmp_path / "chart.yaml"
            chart_path.write_text(self._CHART_YAML)

            captured: list[dict] = []

            class _Capture:
                async def broadcast(self, msg: dict) -> None:
                    captured.append(msg)

            await _compile_file_and_broadcast(
                chart_path,
                "chart.yaml",
                _Capture(),  # type: ignore[arg-type]
                models_dir=MODELS_DIR,
                theme_path=None,
            )

            assert captured, "No broadcast emitted"
            msg = captured[-1]
            assert msg["errors"] == [], msg
            spec = msg["vega_lite_spec"]
            assert spec is not None
            assert "config" in spec, "Default theme not applied in watcher broadcast"
            assert "title" in spec["config"]
            assert "subtitleFontSize" in spec["config"]["title"]

        asyncio.run(_test())


# ─── Dashboard hot-reload project root resolution ────────────────


class TestDashboardHotReloadProjectDir:
    """
    Regression: hot-reloading a nested dashboard YAML must resolve chart
    links relative to the project root, not the dashboard file's parent.
    """

    _DASHBOARD_YAML = """\
dashboard: "Nested"
canvas:
  width: 1440
  height: 900
root:
  orientation: vertical
  contains:
    - sheet: simple.yaml
      name: only
      width: "100%"
"""

    _CHART_YAML = "sheet: S\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"

    def test_nested_dashboard_resolves_charts_from_project_root(self, tmp_path):
        """A dashboards/<file>.yaml finds charts/ under the project root."""

        async def _test():
            (tmp_path / "charts").mkdir()
            (tmp_path / "charts" / "simple.yaml").write_text(self._CHART_YAML)
            (tmp_path / "dashboards").mkdir()
            dash_path = tmp_path / "dashboards" / "sales.yaml"
            dash_path.write_text(self._DASHBOARD_YAML)

            captured: list[dict] = []

            class _Capture:
                async def broadcast(self, msg: dict) -> None:
                    captured.append(msg)

            # project_dir/charts_dir must reach the compile path — if they
            # didn't, the dashboard pipeline would fall back to
            # dash_path.parent (= dashboards/) and fail to find simple.yaml.
            await _compile_file_and_broadcast(
                dash_path,
                "dashboards/sales.yaml",
                _Capture(),  # type: ignore[arg-type]
                models_dir=tmp_path / "models",
                theme_path=None,
                project_dir=tmp_path,
                charts_dir=tmp_path / "charts",
            )

            assert captured, "No broadcast emitted"
            msg = captured[-1]
            assert msg["type"] == "dashboard_compile_result", msg
            assert msg["errors"] == [], f"Chart resolution failed: {msg['errors']}"
            assert msg["html"] is not None

        asyncio.run(_test())


# ─── Full integration — real server via subprocess ───────────────


class TestWatchIntegration:
    """
    Integration tests that start a real uvicorn server in a subprocess
    and verify the watcher → compile → WebSocket broadcast flow.

    Using a subprocess ensures a single event loop (matching production),
    avoiding the cross-event-loop coordination issues of TestClient.
    """

    def _start_server(
        self, project_dir: Path, port: int
    ) -> tuple[subprocess.Popen, SubprocessOutputDrainer]:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "shelves.studio.cli",
                "--no-browser",
                "--port",
                str(port),
                "--dir",
                str(project_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Drain pipes in background so uvicorn can't block on a full kernel
        # pipe buffer, while still keeping output for failure diagnostics.
        drainer = SubprocessOutputDrainer(proc)
        time.sleep(2.0)  # Give uvicorn time to start
        # Early-fail with captured output if the server crashed during boot.
        if proc.poll() is not None:
            drainer.join()
            raise AssertionError(
                f"Studio server exited during startup (code={proc.returncode})\n"
                f"STDOUT:\n{drainer.stdout_text}\n"
                f"STDERR:\n{drainer.stderr_text}"
            )
        return proc, drainer

    def _stop_server(self, proc: subprocess.Popen, drainer: SubprocessOutputDrainer) -> None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        drainer.join()

    def test_file_write_triggers_ws_messages(self, tmp_path):
        """Writing a YAML file via PUT triggers file_change and compile_result messages."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT
        proc, drainer = self._start_server(project_dir, port)
        try:
            with websockets.sync.client.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                # Write a valid YAML file via HTTP PUT
                httpx.put(
                    f"http://127.0.0.1:{port}/file",
                    params={"path": "chart.yaml"},
                    content=VALID_YAML,
                )
                # Collect messages (expect file_change + compile_result)
                messages = []
                for _ in range(2):
                    try:
                        raw = ws.recv(timeout=5)
                        messages.append(json.loads(raw))
                    except TimeoutError:
                        break

                types = {m["type"] for m in messages}
                assert "file_change" in types, f"No file_change in: {messages}"
                assert "compile_result" in types, f"No compile_result in: {messages}"

                compile_msgs = [m for m in messages if m["type"] == "compile_result"]
                assert len(compile_msgs) == 1
                assert compile_msgs[0]["path"] == "chart.yaml"
                assert compile_msgs[0]["errors"] == []
                spec = compile_msgs[0]["vega_lite_spec"]
                assert spec is not None
                assert spec["mark"] == "bar"
                assert spec["encoding"]["x"]["field"] == "country"
                assert spec["encoding"]["y"]["field"] == "revenue"
        finally:
            self._stop_server(proc, drainer)

    def test_invalid_yaml_triggers_error_compile_result(self, tmp_path):
        """Writing invalid YAML produces a compile_result with errors."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 1
        proc, drainer = self._start_server(project_dir, port)
        try:
            with websockets.sync.client.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                httpx.put(
                    f"http://127.0.0.1:{port}/file",
                    params={"path": "bad.yaml"},
                    content=INVALID_YAML,
                )
                messages = []
                for _ in range(2):
                    try:
                        raw = ws.recv(timeout=5)
                        messages.append(json.loads(raw))
                    except TimeoutError:
                        break

                compile_msgs = [m for m in messages if m["type"] == "compile_result"]
                assert len(compile_msgs) == 1
                assert compile_msgs[0]["vega_lite_spec"] is None
                assert len(compile_msgs[0]["errors"]) > 0
        finally:
            self._stop_server(proc, drainer)

    def test_multiple_clients_receive_broadcast(self, tmp_path):
        """All connected WebSocket clients receive the broadcast."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 2
        proc, drainer = self._start_server(project_dir, port)
        try:
            with (
                websockets.sync.client.connect(f"ws://127.0.0.1:{port}/ws") as ws1,
                websockets.sync.client.connect(f"ws://127.0.0.1:{port}/ws") as ws2,
            ):
                httpx.put(
                    f"http://127.0.0.1:{port}/file",
                    params={"path": "chart.yaml"},
                    content=VALID_YAML,
                )
                # Both clients should receive compile_result
                for ws in (ws1, ws2):
                    received_compile = False
                    for _ in range(2):
                        try:
                            raw = ws.recv(timeout=5)
                            msg = json.loads(raw)
                            if msg["type"] == "compile_result":
                                received_compile = True
                                break
                        except TimeoutError:
                            break
                    assert received_compile, "WebSocket client did not receive compile_result"
        finally:
            self._stop_server(proc, drainer)

    def test_json_file_no_compile_result(self, tmp_path):
        """Writing a .json file sends file_change but NOT compile_result."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 3
        proc, drainer = self._start_server(project_dir, port)
        try:
            with websockets.sync.client.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                httpx.put(
                    f"http://127.0.0.1:{port}/file",
                    params={"path": "data.json"},
                    content='[{"country": "US", "revenue": 100}]',
                )
                messages = []
                for _ in range(3):
                    try:
                        raw = ws.recv(timeout=2)
                        messages.append(json.loads(raw))
                    except TimeoutError:
                        break

                types = {m["type"] for m in messages}
                assert "compile_result" not in types, (
                    f"compile_result should NOT be sent for .json: {messages}"
                )
        finally:
            self._stop_server(proc, drainer)
