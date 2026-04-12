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

WebSocket /ws and PTY /ws/terminal are implemented in KAN-205 and KAN-210.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

_STATIC_DIR = Path(__file__).parent / "static"

# File extensions shown in the project tree
_TREE_EXTENSIONS = {".yaml", ".yml", ".json"}


def create_app(
    project_dir: Path,
    theme_path: Path | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application for Shelves Studio.

    Args:
        project_dir: Absolute path to the analyst's project directory.
        theme_path: Optional absolute path to a theme YAML file.

    Returns:
        Configured FastAPI instance.
    """
    app = FastAPI(title="Shelves Studio")

    # Store configuration in app state so route handlers can access it
    app.state.project_dir = project_dir
    app.state.theme_path = theme_path
    app.state.models_dir = project_dir / "models"

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

    return app


# ─── Route Implementations ───────────────────────────────────────


async def _compile_yaml(request: Request) -> JSONResponse:
    """POST /compile — compile YAML body to Vega-Lite spec."""
    from shelves.schema.chart_schema import parse_chart
    from shelves.translator.translate import translate_chart
    from shelves.theme.merge import load_theme, merge_theme

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
    Build a directory tree as a list of {name, type, children?} dicts.

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
        if child.is_dir():
            subtree = _build_tree(child, root)
            entries.append({"name": child.name, "type": "dir", "children": subtree})
        elif child.is_file() and child.suffix in _TREE_EXTENSIONS:
            entries.append({"name": child.name, "type": "file"})

    return entries
