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
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger("shelves.studio.server")

_STATIC_DIR = Path(__file__).parent / "static"

# File extensions shown in the project tree
_TREE_EXTENSIONS = {".yaml", ".yml", ".json"}


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


def _make_lifespan(project_dir: Path, theme_path: Path | None, models_dir: Path):
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
                await _compile_file_and_broadcast(abs_path, rel, manager, models_dir, theme_path)

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
) -> None:
    """Read a YAML file, compile it, and broadcast the result."""
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

        spec = parse_chart(content)
        vl_spec = translate_chart(spec, models_dir=models_dir if models_dir.exists() else None)

        if theme_path is not None:
            theme = load_theme(theme_path)
            vl_spec = merge_theme(vl_spec, theme)

        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": vl_spec,
                "errors": [],
                "warnings": [],
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

    lifespan = _make_lifespan(project_dir, theme_path, resolved_models)

    app = FastAPI(title="Shelves Studio", lifespan=lifespan)

    # Store configuration in app state so route handlers can access it
    app.state.project_dir = project_dir
    app.state.theme_path = theme_path
    app.state.models_dir = resolved_models
    app.state.charts_dir = resolved_charts
    app.state.dashboards_dir = resolved_dashboards
    app.state.manager = ConnectionManager()

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
        return (_STATIC_DIR / "index.html").read_text()

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

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        manager: ConnectionManager = ws.app.state.manager
        await manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)

    return app


# ─── Route Implementations ───────────────────────────────────────


async def _compile_yaml(request: Request) -> JSONResponse:
    """POST /compile — compile YAML body to Vega-Lite spec."""
    from shelves.schema.chart_schema import parse_chart
    from shelves.theme.merge import load_theme, merge_theme
    from shelves.translator.translate import translate_chart

    yaml_body = (await request.body()).decode("utf-8")

    if not yaml_body.strip():
        return JSONResponse({"vega_lite_spec": None, "errors": ["Empty YAML body"], "warnings": []})

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

    return JSONResponse({"vega_lite_spec": vl_spec, "errors": [], "warnings": []})


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
