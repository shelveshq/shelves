"""
Shelves Studio — FastAPI server

Creates and configures the FastAPI application that powers Shelves Studio.

Endpoints:
  GET  /          → serves index.html (placeholder for KAN-206/207 workspace)
  POST /compile   → accepts YAML body, returns {vega_lite_spec, errors, warnings}
  GET  /schema    → returns ChartSpec JSON Schema for Monaco validation
  GET  /project   → returns the project directory tree as JSON
  GET  /file      → reads file content (query param: path)
  PUT  /file      → writes file content (query param: path, body: content)
  WS   /ws        → WebSocket endpoint for live-reload push (server → client)
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("shelves.studio.server")

_STATIC_DIR = Path(__file__).parent / "static"

# File extensions shown in the project tree
_TREE_EXTENSIONS = {".yaml", ".yml", ".json"}

# Loopback hostnames allowed to open Studio WebSockets. Studio binds to
# 127.0.0.1, so only same-host origins are legitimate; any other Origin is
# a cross-site request from another page and must be rejected.
_ALLOWED_WS_HOSTS = {"localhost", "127.0.0.1", "::1"}

# How long the terminal WS has to send its auth message before we close it.
_TERMINAL_AUTH_TIMEOUT_SECONDS = 5.0


def _is_allowed_ws_origin(origin: str | None) -> bool:
    """Return True if a WebSocket Origin header points to a loopback host.

    Browsers always send Origin for WebSocket handshakes from page context,
    so a missing/empty Origin is treated as untrusted too.
    """
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in _ALLOWED_WS_HOSTS


class ConnectionManager:
    """
    Manages active WebSocket connections for broadcast.

    One instance per app (stored in app.state) for test isolation.
    Not designed for multi-process deployments — Studio is a local dev tool.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection from the set."""
        self._connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """
        Send a JSON message to all connected clients.

        Removes any client that fails to receive the message (disconnected).
        """
        dead: set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)


def _make_lifespan(
    project_dir: Path,
    theme_path: Path | None,
    models_dir: Path,
    charts_dir: Path,
):
    """
    Create a FastAPI lifespan context manager that starts/stops the file watcher.
    """
    from shelves.studio.watcher import should_compile, watch_project

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager: ConnectionManager = app.state.manager
        stop_event = asyncio.Event()

        async def on_change(event: str, abs_path: Path) -> None:
            try:
                rel = str(abs_path.relative_to(project_dir))
            except ValueError:
                rel = abs_path.name

            await manager.broadcast({"type": "file_change", "event": event, "path": rel})

            if should_compile(abs_path) and event != "deleted":
                await _compile_file_and_broadcast(
                    abs_path,
                    rel,
                    manager,
                    models_dir,
                    theme_path,
                    project_dir=project_dir,
                    charts_dir=charts_dir,
                )

        task = asyncio.create_task(watch_project(project_dir, on_change, stop_event))
        try:
            yield
        finally:
            stop_event.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return lifespan


async def _compile_file_and_broadcast(
    abs_path: Path,
    rel: str,
    manager: ConnectionManager,
    models_dir: Path,
    theme_path: Path | None,
    project_dir: Path | None = None,
    charts_dir: Path | None = None,
) -> None:
    """Read a YAML file, compile it, and broadcast the result."""
    import yaml as _yaml

    from shelves.data.bind import resolve_data
    from shelves.schema.chart_schema import parse_chart
    from shelves.theme.merge import load_theme, merge_theme
    from shelves.translator.translate import translate_chart

    try:
        content = abs_path.read_text()
        if not content.strip():
            await manager.broadcast(
                {
                    "type": "compile_result",
                    "path": rel,
                    "vega_lite_spec": None,
                    "errors": ["Empty YAML body"],
                    "warnings": [],
                }
            )
            return

        # Route dashboard YAML to the dashboard pipeline
        raw = _yaml.safe_load(content)
        if isinstance(raw, dict) and "dashboard" in raw:
            await _compile_dashboard_file_and_broadcast(
                abs_path,
                rel,
                manager,
                models_dir,
                theme_path,
                project_dir=project_dir,
                charts_dir=charts_dir,
            )
            return

        # Skip non-chart YAML (e.g. models)
        if not isinstance(raw, dict) or "sheet" not in raw:
            return

        spec = parse_chart(content)
        vl_spec = translate_chart(spec, models_dir=models_dir if models_dir.exists() else None)

        if theme_path is not None:
            theme = load_theme(theme_path)
            vl_spec = merge_theme(vl_spec, theme)

        # Resolve data from models (Cube sources)
        warnings: list[str] = []
        try:
            vl_spec = resolve_data(vl_spec, spec, models_dir=models_dir)
        except Exception as e:
            warnings.append(f"Data resolution skipped: {e}")

        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": vl_spec,
                "errors": [],
                "warnings": warnings,
            }
        )
    except Exception as e:
        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": None,
                "errors": [str(e)],
                "warnings": [],
            }
        )


async def _compile_dashboard_file_and_broadcast(
    abs_path: Path,
    rel: str,
    manager: ConnectionManager,
    models_dir: Path,
    theme_path: Path | None,
    project_dir: Path | None = None,
    charts_dir: Path | None = None,
) -> None:
    """Read a dashboard YAML file, compile it, and broadcast the result."""
    try:
        content = abs_path.read_text()
        # Prefer the app-configured project root; fall back to the dashboard's
        # parent only if we weren't told where the project lives. This is what
        # lets chart links resolve correctly when dashboards are nested
        # (e.g. <project>/dashboards/sales.yaml referencing <project>/charts/foo.yaml).
        effective_project_dir = project_dir or abs_path.parent
        resolved_charts = charts_dir or (effective_project_dir / "charts")
        result = await _run_dashboard_pipeline(
            content,
            effective_project_dir,
            resolved_charts,
            theme_path,
            models_dir=models_dir,
        )
        await manager.broadcast(
            {
                "type": "dashboard_compile_result",
                "path": rel,
                **result,
            }
        )
    except Exception as e:
        await manager.broadcast(
            {
                "type": "dashboard_compile_result",
                "path": rel,
                "html": None,
                "errors": [str(e)],
                "warnings": [],
                "component_tree": [],
            }
        )


def create_app(
    project_dir: Path,
    theme_path: Path | None = None,
    models_dir: Path | None = None,
    charts_dir: Path | None = None,
    dashboards_dir: Path | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application for Shelves Studio.

    Args:
        project_dir: Absolute path to the analyst's project directory.
        theme_path: Optional absolute path to a theme YAML file.
        models_dir: Directory containing model YAML files. Defaults to project_dir/models.
        charts_dir: Directory containing chart YAML files. Defaults to project_dir/charts.
        dashboards_dir: Directory containing dashboard YAML files. Defaults to project_dir/dashboards.

    Returns:
        Configured FastAPI instance.
    """
    resolved_models = models_dir or (project_dir / "models")
    resolved_charts = charts_dir or (project_dir / "charts")
    resolved_dashboards = dashboards_dir or (project_dir / "dashboards")

    lifespan = _make_lifespan(project_dir, theme_path, resolved_models, resolved_charts)

    app = FastAPI(title="Shelves Studio", lifespan=lifespan)

    # Store configuration in app state so route handlers can access it
    app.state.project_dir = project_dir
    app.state.theme_path = theme_path
    app.state.models_dir = resolved_models
    app.state.charts_dir = resolved_charts
    app.state.dashboards_dir = resolved_dashboards
    app.state.manager = ConnectionManager()
    # Per-app random token gating the terminal WS. The token is embedded in
    # the served HTML as a <meta> tag, so same-origin scripts can read it
    # but cross-origin pages (blocked by CORS) cannot.
    app.state.terminal_token = secrets.token_urlsafe(32)

    # CORS — allow localhost origins for browser access during development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8089",
            "http://127.0.0.1:8089",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Routes ────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        html = (_STATIC_DIR / "index.html").read_text()
        token = _html.escape(app.state.terminal_token, quote=True)
        meta = f'<meta name="shelves-terminal-token" content="{token}">'
        return html.replace("</head>", f"  {meta}\n</head>", 1)

    @app.post("/compile")
    async def compile_yaml(request: Request) -> JSONResponse:
        return await _compile_yaml(request)

    @app.get("/schema")
    async def get_schema() -> JSONResponse:
        return await _get_schema()

    @app.get("/project")
    async def get_project(request: Request) -> JSONResponse:
        return await _get_project(request)

    @app.get("/file", response_model=None)
    async def get_file(request: Request) -> JSONResponse | Response:
        return await _get_file(request)

    @app.put("/file", response_model=None)
    async def put_file(request: Request) -> JSONResponse | Response:
        return await _put_file(request)

    @app.post("/compile-dashboard")
    async def compile_dashboard(request: Request) -> JSONResponse:
        return await _compile_dashboard_yaml(request)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        manager: ConnectionManager = ws.app.state.manager
        await manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)

    @app.websocket("/ws/terminal")
    async def ws_terminal(ws: WebSocket) -> None:
        """
        Terminal WebSocket endpoint.

        Protocol (client -> server):
            {"type": "auth", "token": "<string>"}     — REQUIRED first message
            {"type": "input", "data": "<string>"}     — keystrokes to write to PTY
            {"type": "resize", "rows": N, "cols": N}  — terminal resize event

        Protocol (server -> client):
            {"type": "output", "data": "<base64>"}     — PTY output (base64-encoded)
            {"type": "exit", "code": N}                — shell process exited

        Security:
          * The Origin header must be a loopback origin — browsers always
            send Origin for WS, so cross-site pages are rejected before accept.
          * The client must send an auth message with the per-app token
            within _TERMINAL_AUTH_TIMEOUT_SECONDS. This defends against a
            malicious local process or browser extension that could bypass
            the Origin check.
        Each authenticated connection gets its own PtyManager instance.
        On disconnect, the PTY is closed and the subprocess terminated.
        """
        import base64 as _base64
        import json as _json

        from shelves.studio.terminal import PtyManager

        if not _is_allowed_ws_origin(ws.headers.get("origin")):
            await ws.close(code=1008)
            return

        await ws.accept()

        # Require auth before spawning a shell.
        expected_token: str = ws.app.state.terminal_token
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=_TERMINAL_AUTH_TIMEOUT_SECONDS)
            auth_msg = _json.loads(raw)
        except (TimeoutError, WebSocketDisconnect, ValueError):
            await ws.close(code=1008)
            return

        token = auth_msg.get("token") if isinstance(auth_msg, dict) else None
        if (
            not isinstance(auth_msg, dict)
            or auth_msg.get("type") != "auth"
            or not isinstance(token, str)
            or not secrets.compare_digest(token, expected_token)
        ):
            await ws.close(code=1008)
            return

        project_dir = str(ws.app.state.project_dir)
        mgr = PtyManager(cwd=project_dir)
        try:
            mgr.spawn()
        except OSError as e:
            await ws.send_json({"type": "exit", "code": -1, "error": str(e)})
            await ws.close()
            return

        async def _read_loop() -> None:
            try:
                while mgr.is_alive:
                    data = await mgr.read()
                    if not data:
                        break
                    await ws.send_json(
                        {"type": "output", "data": _base64.b64encode(data).decode("ascii")}
                    )
                # Shell exited
                code = mgr._proc.returncode if mgr._proc else 0
                try:
                    await ws.send_json({"type": "exit", "code": code or 0})
                except Exception:
                    pass
            except Exception:
                pass

        read_task = asyncio.create_task(_read_loop())

        try:
            while True:
                try:
                    raw = await ws.receive_text()
                except WebSocketDisconnect:
                    break
                try:
                    msg = _json.loads(raw)
                except Exception:
                    # Malformed JSON — close gracefully
                    break
                msg_type = msg.get("type")
                if msg_type == "input":
                    data_str = msg.get("data", "")
                    if data_str:
                        mgr.write(data_str.encode())
                elif msg_type == "resize":
                    rows = int(msg.get("rows", 24))
                    cols = int(msg.get("cols", 80))
                    mgr.resize(rows, cols)
                # Unknown types are silently ignored
        except Exception:
            pass
        finally:
            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass
            mgr.close()

    # Serve static assets (JS modules, CSS) — must come after explicit routes
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app


# ─── Route Implementations ───────────────────────────────────────


async def _compile_yaml(request: Request) -> JSONResponse:
    """POST /compile — compile YAML body to Vega-Lite spec."""
    import yaml as _yaml

    from shelves.data.bind import resolve_data
    from shelves.schema.chart_schema import parse_chart
    from shelves.theme.merge import load_theme, merge_theme
    from shelves.translator.translate import translate_chart

    yaml_body = (await request.body()).decode("utf-8")

    if not yaml_body.strip():
        return JSONResponse({"vega_lite_spec": None, "errors": ["Empty YAML body"], "warnings": []})

    # Skip non-chart YAML (e.g. dashboards, models)
    try:
        raw = _yaml.safe_load(yaml_body)
        if not isinstance(raw, dict) or "sheet" not in raw:
            return JSONResponse({"vega_lite_spec": None, "errors": [], "warnings": []})
    except Exception:
        pass  # Let parse_chart handle malformed YAML

    try:
        spec = parse_chart(yaml_body)
    except Exception as e:
        return JSONResponse({"vega_lite_spec": None, "errors": [str(e)], "warnings": []})

    try:
        models_dir = request.app.state.models_dir
        vl_spec = translate_chart(spec, models_dir=models_dir if models_dir.exists() else None)
    except Exception as e:
        return JSONResponse({"vega_lite_spec": None, "errors": [str(e)], "warnings": []})

    theme_path: Path | None = request.app.state.theme_path
    if theme_path is not None:
        try:
            theme = load_theme(theme_path)
            vl_spec = merge_theme(vl_spec, theme)
        except Exception as e:
            return JSONResponse({"vega_lite_spec": None, "errors": [str(e)], "warnings": []})

    # Resolve data from models (Cube sources)
    warnings: list[str] = []
    try:
        models_dir = request.app.state.models_dir
        vl_spec = resolve_data(vl_spec, spec, models_dir=models_dir)
    except Exception as e:
        warnings.append(f"Data resolution skipped: {e}")

    return JSONResponse({"vega_lite_spec": vl_spec, "errors": [], "warnings": warnings})


async def _get_schema() -> JSONResponse:
    """GET /schema — return ChartSpec JSON Schema for Monaco YAML validation."""
    from shelves.schema.chart_schema import ChartSpec

    return JSONResponse(ChartSpec.model_json_schema())


async def _get_project(request: Request) -> JSONResponse:
    """GET /project — return the project directory tree."""
    project_dir: Path = request.app.state.project_dir
    tree = _build_tree(project_dir, project_dir)
    return JSONResponse(tree)


async def _get_file(request: Request) -> JSONResponse | Response:
    """GET /file?path=<relative> — read file content."""
    project_dir: Path = request.app.state.project_dir
    rel = request.query_params.get("path", "")

    resolved, error = _resolve_safe(project_dir, rel)
    if error:
        return Response(status_code=400, content=error)

    if not resolved.exists():
        return Response(status_code=404, content="File not found")

    return JSONResponse({"content": resolved.read_text(), "path": rel})


async def _put_file(request: Request) -> JSONResponse | Response:
    """PUT /file?path=<relative> — write file content."""
    project_dir: Path = request.app.state.project_dir
    rel = request.query_params.get("path", "")

    resolved, error = _resolve_safe(project_dir, rel)
    if error:
        return Response(status_code=400, content=error)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    content = (await request.body()).decode("utf-8")
    resolved.write_text(content)

    return JSONResponse({"ok": True, "path": rel})


async def _compile_dashboard_yaml(request: Request) -> JSONResponse:
    """POST /compile-dashboard — compile dashboard YAML body to HTML + component tree."""
    yaml_body = (await request.body()).decode("utf-8")

    if not yaml_body.strip():
        return JSONResponse(
            {"html": None, "errors": ["Empty YAML body"], "warnings": [], "component_tree": []}
        )

    import yaml as _yaml

    try:
        raw = _yaml.safe_load(yaml_body)
    except Exception:
        return JSONResponse(
            {
                "html": None,
                "errors": ["Failed to parse YAML"],
                "warnings": [],
                "component_tree": [],
            }
        )

    if not isinstance(raw, dict) or "dashboard" not in raw:
        return JSONResponse(
            {
                "html": None,
                "errors": ["Not a dashboard YAML"],
                "warnings": [],
                "component_tree": [],
            }
        )

    project_dir: Path = request.app.state.project_dir
    charts_dir: Path = request.app.state.charts_dir
    theme_path: Path | None = request.app.state.theme_path
    models_dir: Path = request.app.state.models_dir
    result = await _run_dashboard_pipeline(
        yaml_body, project_dir, charts_dir, theme_path, models_dir=models_dir
    )
    return JSONResponse(result)


async def _run_dashboard_pipeline(
    yaml_body: str,
    project_dir: Path,
    charts_dir: Path,
    theme_path: Path | None,
    models_dir: Path | None = None,
) -> dict:
    """Run the dashboard compilation pipeline and return a result dict."""
    from shelves.data.bind import resolve_data
    from shelves.schema.chart_schema import parse_chart
    from shelves.schema.layout_schema import parse_dashboard
    from shelves.theme.merge import load_theme, merge_theme
    from shelves.translator.layout import translate_dashboard
    from shelves.translator.layout_flatten import flatten_dashboard
    from shelves.translator.translate import translate_chart

    try:
        spec = parse_dashboard(yaml_body)
    except Exception as e:
        return {"html": None, "errors": [str(e)], "warnings": [], "component_tree": []}

    flat_root = flatten_dashboard(spec)
    component_tree = _build_component_tree(flat_root)

    # Discover sheets (name → link)
    from shelves.compose.dashboard import _discover_sheets

    sheets = _discover_sheets(spec)

    # Load theme
    try:
        theme = load_theme(theme_path) if theme_path else load_theme()
    except Exception:
        from shelves.theme.theme_schema import ThemeSpec

        theme = ThemeSpec()

    # Compile each referenced chart (resolved relative to charts_dir)
    warnings: list[str] = []
    chart_specs: dict[str, dict] = {}
    for name, link in sheets.items():
        chart_path = charts_dir / link
        if not chart_path.exists():
            return {
                "html": None,
                "errors": [f"Chart file not found: {link} (sheet '{name}')"],
                "warnings": [],
                "component_tree": [],
            }
        try:
            chart_yaml = chart_path.read_text()
            chart_spec = parse_chart(chart_yaml)
            vl = translate_chart(
                chart_spec, models_dir=models_dir if models_dir and models_dir.exists() else None
            )
            vl = merge_theme(vl, theme)
            # Data binding (best-effort)
            try:
                vl = resolve_data(vl, chart_spec, models_dir=models_dir)
            except Exception as de:
                warnings.append(f"Data resolution skipped for '{name}': {de}")
            chart_specs[name] = vl
        except Exception as e:
            warnings.append(f"Chart '{name}' ({link}): {e}")

    html = translate_dashboard(spec, theme, chart_specs)
    html = _inject_click_targets(html, sheets)

    return {"html": html, "errors": [], "warnings": warnings, "component_tree": component_tree}


def _build_component_tree(flat_root: Any) -> list[dict]:
    """Walk a FlatNode tree and produce a flat list for the component tree strip.

    Walk order is depth-first pre-order.
    Each entry: {name, type, depth, link?, children_count}
    """
    from shelves.schema.layout_schema import SheetComponent
    from shelves.translator.layout_flatten import FlatNode

    result: list[dict] = []

    def _walk(node: FlatNode, depth: int) -> None:
        comp = node.component
        comp_type = type(comp).__name__.lower().replace("component", "")
        # Normalize type names
        if hasattr(comp, "orientation"):
            comp_type = getattr(comp, "orientation", "vertical")
        elif isinstance(comp, SheetComponent):
            comp_type = "sheet"

        entry: dict = {
            "name": node.name,
            "type": comp_type,
            "depth": depth,
            "children_count": len(node.children),
        }
        if isinstance(comp, SheetComponent):
            entry["link"] = comp.link

        result.append(entry)
        for child in node.children:
            _walk(child, depth + 1)

    _walk(flat_root, 0)
    return result


def _inject_click_targets(html: str, sheets: dict[str, str]) -> str:
    """Add data-chart-link attributes and dashed borders to sheet divs in dashboard HTML.

    Merges click-target styles into the existing style attribute rather than
    adding a duplicate (browsers ignore the second style= attribute).
    """
    import re

    for name, link in sheets.items():
        pattern = rf'(<div id="sheet-{re.escape(name)}")\s+(style=")'
        replacement = (
            rf'\1 data-chart-link="{link}"'
            r" \2border: 2px dashed rgba(108,140,255,0.4); cursor: pointer; "
        )
        html = re.sub(pattern, replacement, html, count=1)
    return html


# ─── Helpers ─────────────────────────────────────────────────────


def _resolve_safe(project_dir: Path, rel: str) -> tuple[Path, str | None]:
    """
    Resolve a relative path within project_dir, rejecting path traversal.

    Returns (resolved_path, None) on success, (_, error_message) on failure.
    """
    if not rel:
        return project_dir, "Missing path parameter"

    try:
        resolved = (project_dir / rel).resolve()
    except Exception:
        return project_dir, "Invalid path"

    if not resolved.is_relative_to(project_dir.resolve()):
        return project_dir, f"Path '{rel}' is outside the project directory"

    return resolved, None


def _build_tree(path: Path, root: Path) -> list[dict[str, Any]]:
    """
    Build a directory tree as a list of {name, type, path, children?} dicts.

    path is the relative path from root (e.g., "charts/revenue.yaml").
    Only includes files with extensions in _TREE_EXTENSIONS and directories.
    Sorts: directories first, then alphabetically.
    """
    if not path.is_dir():
        return []

    entries = []
    try:
        children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return []

    for child in children:
        if child.name.startswith("."):
            continue
        rel = str(child.relative_to(root))
        if child.is_dir():
            subtree = _build_tree(child, root)
            entries.append({"name": child.name, "type": "dir", "path": rel, "children": subtree})
        elif child.is_file() and child.suffix in _TREE_EXTENSIONS:
            entries.append({"name": child.name, "type": "file", "path": rel})

    return entries
