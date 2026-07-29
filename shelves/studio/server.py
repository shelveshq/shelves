"""
Shelves Studio — FastAPI server

Creates and configures the FastAPI application that powers Shelves Studio.

Endpoints:
  GET  /          → serves index.html (placeholder for KAN-206/207 workspace)
  POST /compile   → accepts YAML body, returns {vega_lite_spec, errors, warnings}
  GET  /schema    → returns ChartSpec JSON Schema for Monaco validation
  GET  /project   → returns the project directory tree as JSON
  GET  /file      → reads file content (query param: path; accepts the @theme/<name> alias)
  PUT  /file      → writes file content (query param: path, body: content;
                    theme writes broadcast theme_changed)
  POST /file      → creates a new file (409 if exists; templated by dir)
  POST /file/rename → renames/moves a file (query: path, to)
  DELETE /file    → deletes a file
  WS   /ws        → WebSocket endpoint for live-reload push (server → client)

Security:
  All HTTP endpoints (and mounts) validate the Host header against loopback
  hosts (TrustedHostMiddleware) to block DNS rebinding; PUT /file enforces
  the same .yaml/.yml/.json write allow-list as create/rename/delete (the
  configured theme file is exempt). The terminal WS additionally requires a
  loopback Origin and a per-app token.
"""

from __future__ import annotations

import html as _html
import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from shelves.render.to_html import load_label_patch_js
from shelves.studio.connection import ConnectionManager
from shelves.studio.lifespan import make_lifespan
from shelves.studio.routes import compile, dashboard, files, terminal

logger = logging.getLogger("shelves.studio.server")

_STATIC_DIR = Path(__file__).parent / "static"

# Loopback-only Host allow-list (SHE-52). Binding to 127.0.0.1 does not stop
# DNS rebinding — the victim's browser is the vector, and it sends the
# attacker hostname in Host. TrustedHostMiddleware strips the port before
# matching, so explicit ports pass. "::1" is omitted deliberately: the server
# binds the IPv4 loopback only (cli.BIND_HOST), so an IPv6 Host can never
# belong to a legitimate request — and Starlette's host parsing predates
# bracketed IPv6 literals anyway.
_ALLOWED_HTTP_HOSTS = ["localhost", "127.0.0.1"]


class _LenientStaticFiles(StaticFiles):
    """StaticFiles that tolerates a missing or late-created directory.

    The project assets dir often does not exist when studio starts (a user adds
    `assets/` and references an image later). Stock StaticFiles raises on the
    first request if the directory is missing; we skip that check so requests
    simply 404 until files appear, then serve them — no restart required.
    """

    async def check_config(self) -> None:  # pragma: no cover - trivial override
        return


def create_app(
    project_dir: Path,
    theme_path: Path | None = None,
    models_dir: Path | None = None,
    charts_dir: Path | None = None,
    dashboards_dir: Path | None = None,
    assets_dir: Path | None = None,
    parameters_path: Path | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application for Shelves Studio.

    Args:
        project_dir: Absolute path to the analyst's project directory.
        theme_path: Optional absolute path to a theme YAML file.
        models_dir: Directory containing model YAML files. Defaults to project_dir/models.
        charts_dir: Directory containing chart YAML files. Defaults to project_dir/charts.
        dashboards_dir: Directory containing dashboard YAML files.
            Defaults to project_dir/dashboards.
        assets_dir: Directory of image assets served at /assets. Defaults to
            project_dir/assets. Need not exist at startup — it is served
            whenever files appear in it.
        parameters_path: Path to parameters.yaml. Defaults to
            <models_dir>/parameters.yaml. Need not exist — a project with no
            parameters simply has none.

    Returns:
        Configured FastAPI instance.
    """
    resolved_models = models_dir or (project_dir / "models")
    resolved_charts = charts_dir or (project_dir / "charts")
    resolved_dashboards = dashboards_dir or (project_dir / "dashboards")
    resolved_assets = assets_dir or (project_dir / "assets")
    resolved_parameters = parameters_path or (resolved_models / "parameters.yaml")

    lifespan = make_lifespan(
        project_dir,
        theme_path,
        resolved_models,
        resolved_charts,
        resolved_dashboards,
        resolved_assets,
        resolved_parameters,
    )

    app = FastAPI(title="Shelves Studio", lifespan=lifespan)

    # Store configuration in app state so route handlers can access it
    app.state.project_dir = project_dir
    app.state.theme_path = theme_path
    app.state.models_dir = resolved_models
    app.state.charts_dir = resolved_charts
    app.state.dashboards_dir = resolved_dashboards
    # Stored even when the directory is absent so the startup banner can show the
    # resolved path; only the StaticFiles mount below is conditional.
    app.state.assets_dir = resolved_assets
    app.state.parameters_path = resolved_parameters
    app.state.manager = ConnectionManager()
    # Per-app random token gating the terminal WS. The token is embedded in
    # the served HTML as a <meta> tag, so same-origin scripts can read it
    # but cross-origin pages (blocked by CORS) cannot.
    app.state.terminal_token = secrets.token_urlsafe(32)

    # Host validation (SHE-52): reject DNS-rebinding requests on every HTTP
    # endpoint and mount. The terminal WS keeps its own stricter Origin +
    # token defense (routes/terminal.py).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_ALLOWED_HTTP_HOSTS)

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
        return await compile.compile_yaml(request)

    @app.get("/schema")
    async def get_schema() -> JSONResponse:
        return await compile.get_schema()

    @app.get("/label-patch.js")
    async def label_patch_js() -> Response:
        # Canonical label-patch script shared with the standalone HTML renderer.
        # Served fresh from shelves/render/label_patch.js so the studio and CLI
        # render paths can never drift, and edits show up without a restart.
        return Response(load_label_patch_js(), media_type="text/javascript")

    @app.get("/project")
    async def get_project(request: Request) -> JSONResponse:
        return await files.get_project(request)

    @app.get("/file", response_model=None)
    async def get_file(request: Request) -> JSONResponse | Response:
        return await files.get_file(request)

    @app.put("/file", response_model=None)
    async def put_file(request: Request) -> JSONResponse | Response:
        return await files.put_file(request)

    @app.post("/file", response_model=None)
    async def post_file(request: Request) -> JSONResponse | Response:
        return await files.post_file(request)

    @app.post("/file/rename", response_model=None)
    async def rename_file(request: Request) -> JSONResponse | Response:
        return await files.rename_file(request)

    @app.delete("/file", response_model=None)
    async def delete_file(request: Request) -> JSONResponse | Response:
        return await files.delete_file(request)

    @app.post("/compile-dashboard")
    async def compile_dashboard(request: Request) -> JSONResponse:
        return await dashboard.compile_dashboard_yaml(request)

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
    async def ws_terminal_endpoint(ws: WebSocket) -> None:
        await terminal.ws_terminal(ws)

    # Serve static assets (JS modules, CSS) — must come after explicit routes
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Serve the project's assets so dashboards can reference images relative to
    # the assets dir (e.g. image: png/logo.png → emitted src "assets/png/logo.png").
    # The dashboard preview iframe uses srcdoc, so relative URLs resolve against
    # this server origin → /assets/….
    # Mount unconditionally via _LenientStaticFiles: the directory commonly does
    # not exist yet at startup (a user adds assets/ later), and files are
    # resolved per-request, so they are served as soon as they appear — no
    # restart needed. Missing files/dir return 404, not 500.
    app.mount(
        "/assets",
        _LenientStaticFiles(directory=str(resolved_assets), check_dir=False),
        name="assets",
    )

    return app
