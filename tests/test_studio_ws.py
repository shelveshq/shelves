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

from shelves.studio.connection import ConnectionManager
from shelves.studio.lifespan import compile_file_and_broadcast as _compile_file_and_broadcast
from shelves.studio.server import create_app
from shelves.studio.watcher import COMPILE_EXTENSIONS, WATCH_EXTENSIONS, should_compile
from tests.conftest import FIXTURES_DIR, MODELS_DIR, SubprocessOutputDrainer

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
    """Create a project dir with the orders model fixture and a charts dir.

    charts/ must exist at server start: the watcher is scoped to the
    configured dirs (SHE-39) and only watches those that exist.
    """
    (tmp_path / "models").mkdir()
    shutil.copy(MODELS_DIR / "orders.yaml", tmp_path / "models" / "orders.yaml")
    (tmp_path / "charts").mkdir()
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
        from tests.conftest import LoopbackTestClient as TestClient

        app = create_app(project_dir=tmp_path)
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            # Connected — server accepted without error
            # Close cleanly
            ws.close()

    def test_ws_connect_multiple_clients(self, tmp_path):
        """Multiple WebSocket clients can connect simultaneously."""
        from tests.conftest import LoopbackTestClient as TestClient

        app = create_app(project_dir=tmp_path)
        with (
            TestClient(app) as client,
            client.websocket_connect("/ws") as ws1,
            client.websocket_connect("/ws") as ws2,
        ):
            ws1.close()
            ws2.close()


# ─── Default theme applied without --theme ───────────────────────


class TestDefaultThemeInCompile:
    """/compile and file watcher must apply the default theme even when
    no --theme path is passed to shelves-studio."""

    _CHART_YAML = "sheet: S\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"

    def test_compile_endpoint_applies_default_theme(self):
        """POST /compile with no theme_path returns a spec with config.title tokens."""
        from tests.conftest import LoopbackTestClient as TestClient

        app = create_app(project_dir=FIXTURES_DIR, theme_path=None, models_dir=MODELS_DIR)
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
                project_dir=FIXTURES_DIR,
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

    def test_watcher_broadcast_includes_model(self, tmp_path):
        """The broadcast payload carries the model name, in shape-parity with
        POST /compile (SHE-43 Data view header)."""

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
                project_dir=FIXTURES_DIR,
            )

            assert captured, "No broadcast emitted"
            assert captured[-1]["model"] == "orders"

        asyncio.run(_test())

    def test_watcher_broadcast_positions_warnings(self, tmp_path):
        """Watcher warnings are structured, positioned objects — same shape as
        POST /compile — so a chart yields the same inline marker whether typed
        or saved (SHE-101)."""

        async def _test():
            chart_path = tmp_path / "chart.yaml"
            chart_path.write_text(
                'sheet: S\ndata: orders\ncols: country\nkpi:\n  value: revenue\n  format: "$,.0f"\n'
            )

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
                project_dir=FIXTURES_DIR,
            )

            assert captured, "No broadcast emitted"
            warns = captured[-1]["warnings"]
            assert len(warns) == 1
            warn = warns[0]
            assert isinstance(warn, dict)
            assert warn["code"] == "kpi_shelves_ignored"
            assert warn["source"] == "warning"
            assert warn["line"] == 4
            assert warn["col"] == 1

        asyncio.run(_test())


# ─── Watcher broadcasts structured YAML syntax errors ────────────


class TestWatcherYamlSyntaxError:
    """A YAML syntax error on the file-watch path must broadcast a
    structured error dict (so the editor can place an inline marker),
    matching the /compile route — not a bare string."""

    def test_malformed_yaml_broadcasts_structured_error(self, tmp_path):
        async def _test():
            chart_path = tmp_path / "bad.yaml"
            chart_path.write_text("sheet: test\n  bad: indent\n")

            captured: list[dict] = []

            class _Capture:
                async def broadcast(self, msg: dict) -> None:
                    captured.append(msg)

            await _compile_file_and_broadcast(
                chart_path,
                "bad.yaml",
                _Capture(),  # type: ignore[arg-type]
                models_dir=MODELS_DIR,
                theme_path=None,
                project_dir=FIXTURES_DIR,
            )

            assert captured, "No broadcast emitted"
            errors = captured[-1]["errors"]
            assert len(errors) == 1
            err = errors[0]
            assert isinstance(err, dict), f"Expected structured error, got {err!r}"
            assert err["source"] == "yaml"
            assert err["type"] == "yaml_syntax"
            assert err["line"] == 2

        asyncio.run(_test())


# ─── Watcher broadcasts structured runtime errors ────────────────


class TestWatcherRuntimeError:
    """A generic (non-YAML, non-validation) exception on the file-watch path
    must broadcast the same structured error dict as POST /compile's
    runtime-error path — not a bare string (SHE-50 / review finding #13)."""

    def test_runtime_error_broadcasts_structured_dict(self, tmp_path, monkeypatch):
        import shelves.pipeline

        def _boom(*_args, **_kwargs):
            raise RuntimeError("translator exploded")

        monkeypatch.setattr(shelves.pipeline, "compile_chart", _boom)

        async def _test():
            chart_path = tmp_path / "chart.yaml"
            chart_path.write_text(VALID_YAML)

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
                project_dir=FIXTURES_DIR,
            )

            assert captured, "No broadcast emitted"
            errors = captured[-1]["errors"]
            assert len(errors) == 1
            err = errors[0]
            assert isinstance(err, dict), f"Expected structured error, got {err!r}"
            assert err["source"] == "runtime"
            assert err["type"] == "runtime_error"
            assert err["msg"] == "translator exploded"
            assert err["friendly_msg"] == "translator exploded"

        asyncio.run(_test())


# ─── Vanished-file race (transient temp/atomic-save files) ───────


class TestWatcherVanishedFile:
    """A file that is created and deleted before the watcher reads it (test
    temp files, editor atomic-save swap files) must NOT surface a compile
    error. The read race should be a silent no-op."""

    def test_vanished_chart_file_emits_no_error(self, tmp_path):
        async def _test():
            missing = tmp_path / "_tmp_gone.yaml"  # never created on disk

            captured: list[dict] = []

            class _Capture:
                async def broadcast(self, msg: dict) -> None:
                    captured.append(msg)

            await _compile_file_and_broadcast(
                missing,
                "_tmp_gone.yaml",
                _Capture(),  # type: ignore[arg-type]
                models_dir=MODELS_DIR,
                theme_path=None,
                project_dir=FIXTURES_DIR,
            )

            assert captured == [], f"Vanished file should emit nothing, got {captured}"

        asyncio.run(_test())

    def test_vanished_dashboard_file_emits_no_error(self, tmp_path):
        from shelves.studio.lifespan import (
            compile_dashboard_file_and_broadcast as _compile_dashboard,
        )

        async def _test():
            missing = tmp_path / "_tmp_gone_dashboard.yaml"  # never created

            captured: list[dict] = []

            class _Capture:
                async def broadcast(self, msg: dict) -> None:
                    captured.append(msg)

            await _compile_dashboard(
                missing,
                "_tmp_gone_dashboard.yaml",
                _Capture(),  # type: ignore[arg-type]
                models_dir=MODELS_DIR,
                theme_path=None,
                project_dir=FIXTURES_DIR,
            )

            assert captured == [], f"Vanished dashboard should emit nothing, got {captured}"

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


# ─── Watcher scoped to configured dirs (SHE-39) ──────────────────


class TestWatcherScope:
    """The watch is rooted at project_dir (which always exists) and events
    are filtered to the configured scope dirs (SHE-39 + PR #62 review):
    files outside the scope never reach on_change, while scope dirs created
    after startup are picked up live — no restart required."""

    def test_watcher_picks_up_late_created_dirs(self, tmp_path):
        """A scope dir created after the watcher starts still triggers events."""
        from shelves.studio.watcher import watch_project

        async def _test():
            charts = tmp_path / "charts"  # does NOT exist at watcher start

            events: list[tuple[str, Path]] = []

            async def on_change(event: str, path: Path) -> None:
                events.append((event, path))

            stop = asyncio.Event()
            task = asyncio.create_task(watch_project(tmp_path, [charts], on_change, stop))
            await asyncio.sleep(0.5)  # let awatch arm before mutating the tree
            charts.mkdir()
            (charts / "a.yaml").write_text("sheet: x\n")
            for _ in range(80):
                if events:
                    break
                await asyncio.sleep(0.1)
            stop.set()
            await asyncio.wait_for(task, timeout=5)
            assert events, "No event for a file in a dir created after watcher start"
            assert events[0][1].name == "a.yaml"

        asyncio.run(_test())

    def test_watcher_filters_events_outside_scope_dirs(self, tmp_path):
        """Files outside the scope dirs never reach on_change."""
        from shelves.studio.watcher import watch_project

        async def _test():
            charts = tmp_path / "charts"
            charts.mkdir()
            docs = tmp_path / "docs"
            docs.mkdir()

            events: list[tuple[str, Path]] = []

            async def on_change(event: str, path: Path) -> None:
                events.append((event, path))

            stop = asyncio.Event()
            task = asyncio.create_task(watch_project(tmp_path, [charts], on_change, stop))
            await asyncio.sleep(0.5)
            (docs / "notes.yaml").write_text("x: 1\n")
            (tmp_path / "root.yaml").write_text("x: 1\n")
            (charts / "a.yaml").write_text("sheet: x\n")
            for _ in range(80):
                if events:
                    break
                await asyncio.sleep(0.1)
            # Give any stray out-of-scope events a beat to arrive before asserting
            await asyncio.sleep(0.5)
            stop.set()
            await asyncio.wait_for(task, timeout=5)
            assert events, "No event for charts/a.yaml"
            assert all(p.name == "a.yaml" for _, p in events), (
                f"Out-of-scope files leaked through the filter: {events}"
            )

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
                    params={"path": "charts/chart.yaml"},
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
                assert compile_msgs[0]["path"] == "charts/chart.yaml"
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
                    params={"path": "charts/bad.yaml"},
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
                    params={"path": "charts/chart.yaml"},
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
                    params={"path": "charts/data.json"},
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

    def test_assets_file_change_broadcasts(self, tmp_path):
        """assets/ is in the watch scope: adding a file there refreshes the
        tree via file_change (PR #62 review — tree scope must equal watch
        scope). The dir doesn't exist at startup, so this also covers the
        late-created-dir path end-to-end."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 5
        proc, drainer = self._start_server(project_dir, port)
        try:
            with websockets.sync.client.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                httpx.put(
                    f"http://127.0.0.1:{port}/file",
                    params={"path": "assets/logo.json"},
                    content="{}",
                )
                messages = []
                for _ in range(2):
                    try:
                        raw = ws.recv(timeout=5)
                        messages.append(json.loads(raw))
                    except TimeoutError:
                        break
                file_changes = [m for m in messages if m["type"] == "file_change"]
                assert any(m["path"] == "assets/logo.json" for m in file_changes), (
                    f"No file_change for assets/logo.json: {messages}"
                )
        finally:
            self._stop_server(proc, drainer)

    def test_watcher_ignores_files_outside_configured_dirs(self, tmp_path):
        """YAML edits outside charts/dashboards/models produce no broadcast;
        edits inside charts/ still do (SHE-39)."""
        import httpx
        import websockets.sync.client

        project_dir = _setup_project(tmp_path)
        port = _SERVER_PORT + 4
        proc, drainer = self._start_server(project_dir, port)
        try:
            with websockets.sync.client.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                # Outside every configured dir → the watcher must not see it
                httpx.put(
                    f"http://127.0.0.1:{port}/file",
                    params={"path": "tests_fixture.yaml"},
                    content=VALID_YAML,
                )
                # Inside charts/ → broadcasts as today
                httpx.put(
                    f"http://127.0.0.1:{port}/file",
                    params={"path": "charts/a.yaml"},
                    content=VALID_YAML,
                )
                messages = []
                for _ in range(4):
                    try:
                        raw = ws.recv(timeout=5)
                        messages.append(json.loads(raw))
                    except TimeoutError:
                        break

                paths = {m.get("path") for m in messages}
                assert "tests_fixture.yaml" not in paths, (
                    f"Outside-dir file leaked into broadcasts: {messages}"
                )
                types = {m["type"] for m in messages}
                assert "file_change" in types, f"No file_change for charts/a.yaml: {messages}"
                assert "compile_result" in types, f"No compile_result for charts/a.yaml: {messages}"
                assert all(m.get("path") == "charts/a.yaml" for m in messages), messages
        finally:
            self._stop_server(proc, drainer)
