from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("shelves.studio.files")

_TREE_EXTENSIONS = {".yaml", ".yml", ".json"}


async def get_project(request: Request) -> JSONResponse:
    """GET /project — return typed top-level groups from the configured dirs."""
    state = request.app.state
    groups = [
        ("charts", state.charts_dir),
        ("dashboards", state.dashboards_dir),
        ("models", state.models_dir),
        ("assets", state.assets_dir),
    ]
    tree = build_group_tree(state.project_dir, groups)
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


def build_group_tree(
    project_dir: Path,
    groups: list[tuple[str, Path]],
) -> list[dict[str, Any]]:
    """
    Build the /project tree as typed top-level groups.

    groups is [(role, dir), …] with role ∈ charts|dashboards|models|assets;
    emits one entry per existing, non-empty configured dir:
    {"name": dir.name, "type": "dir", "path": rel, "group": role, "children": …}.
    Dirs that resolve outside project_dir are skipped with a warning
    (resolve_safe stays single-root, so their files would be unreachable).
    Duplicate dirs are emitted once — first role wins.
    """
    root = project_dir.resolve()
    seen: set[Path] = set()
    entries: list[dict[str, Any]] = []
    for role, d in groups:
        rd = d.resolve()
        if rd in seen:
            continue
        seen.add(rd)
        if not rd.is_relative_to(root):
            logger.warning(
                "Configured %s dir %s is outside the project dir %s — omitted from the tree",
                role,
                rd,
                root,
            )
            continue
        if not rd.is_dir():
            continue
        children = build_tree(rd, root)
        if not children:
            continue
        entries.append(
            {
                "name": rd.name,
                "type": "dir",
                "path": str(rd.relative_to(root)),
                "group": role,
                "children": children,
            }
        )
    return entries


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
