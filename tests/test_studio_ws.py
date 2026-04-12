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


from tests.conftest import MODELS_DIR

from shelves.studio.server import ConnectionManager, create_app
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


# ─── Full integration — real server via subprocess ───────────────


class TestWatchIntegration:
    """
    Integration tests that start a real uvicorn server in a subprocess
    and verify the watcher → compile → WebSocket broadcast flow.

    Using a subprocess ensures a single event loop (matching production),
    avoiding the cross-event-loop coordination issues of TestClient.
    """

    def _start_server(self, project_dir: Path, port: int) -> subprocess.Popen:
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
        time.sleep(2.0)  # Give uvicorn time to start
        return proc

    def _stop_server(self, proc: subprocess.Popen) -> None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def test_file_write_triggers_ws_messages(self, tmp_path):
        """Writing a YAML file via PUT triggers file_change and compile_result messages."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT
        proc = self._start_server(project_dir, port)
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
                assert compile_msgs[0]["warnings"] == []
                spec = compile_msgs[0]["vega_lite_spec"]
                assert spec is not None
                assert spec["mark"] == "bar"
                assert spec["encoding"]["x"]["field"] == "country"
                assert spec["encoding"]["y"]["field"] == "revenue"
        finally:
            self._stop_server(proc)

    def test_invalid_yaml_triggers_error_compile_result(self, tmp_path):
        """Writing invalid YAML produces a compile_result with errors."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 1
        proc = self._start_server(project_dir, port)
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
            self._stop_server(proc)

    def test_multiple_clients_receive_broadcast(self, tmp_path):
        """All connected WebSocket clients receive the broadcast."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 2
        proc = self._start_server(project_dir, port)
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
            self._stop_server(proc)

    def test_json_file_no_compile_result(self, tmp_path):
        """Writing a .json file sends file_change but NOT compile_result."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 3
        proc = self._start_server(project_dir, port)
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
            self._stop_server(proc)
