from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

_TREE_EXTENSIONS = {".yaml", ".yml", ".json"}


async def get_project(request: Request) -> JSONResponse:
    """GET /project — return the project directory tree."""
    project_dir: Path = request.app.state.project_dir
    tree = build_tree(project_dir, project_dir)
    return JSONResponse(tree)


async def get_file(request: Request) -> JSONResponse | Response:
    """GET /file?path=<relative> — read file content."""
    project_dir: Path = request.app.state.project_dir
    rel = request.query_params.get("path", "")

    resolved, error = resolve_safe(project_dir, rel)
    if error:
        return Response(status_code=400, content=error)

    if not resolved.exists():
        return Response(status_code=404, content="File not found")

    return JSONResponse({"content": resolved.read_text(), "path": rel})


async def put_file(request: Request) -> JSONResponse | Response:
    """PUT /file?path=<relative> — write file content."""
    project_dir: Path = request.app.state.project_dir
    rel = request.query_params.get("path", "")

    resolved, error = resolve_safe(project_dir, rel)
    if error:
        return Response(status_code=400, content=error)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    content = (await request.body()).decode("utf-8")
    resolved.write_text(content)

    return JSONResponse({"ok": True, "path": rel})


def resolve_safe(project_dir: Path, rel: str) -> tuple[Path, str | None]:
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


def build_tree(path: Path, root: Path) -> list[dict[str, Any]]:
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
            subtree = build_tree(child, root)
            entries.append({"name": child.name, "type": "dir", "path": rel, "children": subtree})
        elif child.is_file() and child.suffix in _TREE_EXTENSIONS:
            entries.append({"name": child.name, "type": "file", "path": rel})

    return entries
