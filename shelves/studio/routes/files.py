from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("shelves.studio.files")

_TREE_EXTENSIONS = {".yaml", ".yml", ".json"}
# Create/rename/delete are restricted to tree-visible file types; SHE-52's
# write allow-list builds on the same set.
_ALLOWED_WRITE_EXTENSIONS = _TREE_EXTENSIONS
_EXTENSION_ERROR = "Only .yaml, .yml, and .json files are allowed"

# The primary groups are listed in /project even when empty or missing so the
# UI can offer "create the first file" there (SHE-42); assets keeps the
# SHE-39 omit-when-empty rule (no create affordance).
_ALWAYS_LISTED_ROLES = {"charts", "dashboards", "models"}

# ─── New-file starter templates (SHE-42) ─────────────────────────
# Verified against the real pipeline (2026-07-13):
#  - chart: parse_chart-valid; compiling in a fresh project reports the
#    friendly "Data model 'my_model' not found" marker — intentional guidance.
#  - dashboard: composes to HTML with zero errors ('vertical', NOT 'column').
#  - model: load_model-valid once `model:` == filename stem (interpolated).
CHART_TEMPLATE = """\
sheet: "New Chart"

# Point `data` at a model: models/<name>.yaml -> data: <name>
data: my_model

cols: my_dimension
rows: my_measure
marks: bar
"""

DASHBOARD_TEMPLATE = """\
dashboard: "New Dashboard"

canvas:
  width: 1200
  height: 800

# components:
#   my_chart:
#     sheet: charts/my_chart.yaml

root:
  orientation: vertical
  contains: []
"""

MODEL_TEMPLATE = """\
model: {stem}
label: "New Model"

# source:
#   type: file
#   path: data/my_data.csv

measures:
  my_measure:
    label: "My Measure"

dimensions:
  my_dimension:
    label: "My Dimension"
"""


def template_for(state: Any, resolved: Path) -> str:
    """Starter content for a new file, chosen by the configured dir it lands in.

    Only .yaml/.yml files get a template; .json and files outside every
    primary dir get "". Uses is_relative_to against the RESOLVED configured
    dirs (same symlink discipline as the watcher).
    """
    if resolved.suffix not in {".yaml", ".yml"}:
        return ""
    for configured, template in (
        (state.charts_dir, CHART_TEMPLATE),
        (state.dashboards_dir, DASHBOARD_TEMPLATE),
        (state.models_dir, MODEL_TEMPLATE),
    ):
        if resolved.is_relative_to(configured.resolve()):
            return template.format(stem=resolved.stem) if template is MODEL_TEMPLATE else template
    return ""


def theme_alias(theme_path: Path | None) -> str | None:
    """The exact tree path that aliases the configured theme file.

    "@theme/<filename>" — a sentinel, not a directory namespace. Returns
    None when no theme is configured. Exact-string matching (no user path
    math) is what keeps the alias traversal-safe by construction.
    """
    return None if theme_path is None else f"@theme/{theme_path.name}"


def _resolve_readwrite_path(state: Any, rel: str) -> tuple[Path | None, str | None]:
    """Resolve a GET/PUT /file path: the theme alias, or resolve_safe.

    Returns (resolved, None) on success, (None, error) on failure. Only
    GET/PUT go through this — create/rename/delete stay resolve_safe-only,
    so the alias can never be deleted, renamed, or shadowed.
    """
    theme = getattr(state, "theme_path", None)
    if theme is not None and rel == theme_alias(theme):
        return theme.resolve(), None
    resolved, error = resolve_safe(state.project_dir, rel)
    return (None, error) if error else (resolved, None)


async def _broadcast(request: Request, payload: dict[str, Any]) -> None:
    """Broadcast a payload via app.state.manager.

    Direct broadcast: the watcher also fires for these fs events, but relying
    on it makes UI refresh timing nondeterministic (and dead under TestClient
    without lifespan). Duplicates are harmless — sidebar.js debounces
    fetchTree by 500ms and editor.js's handlers are idempotent.
    """
    await request.app.state.manager.broadcast(payload)


async def _broadcast_file_change(request: Request, event: str, rel: str) -> None:
    await _broadcast(request, {"type": "file_change", "event": event, "path": rel})


async def get_project(request: Request) -> JSONResponse:
    """GET /project — return typed top-level groups from the configured dirs."""
    state = request.app.state
    groups = [
        ("charts", state.charts_dir),
        ("dashboards", state.dashboards_dir),
        ("models", state.models_dir),
        ("assets", state.assets_dir),
    ]
    tree = build_group_tree(state.project_dir, groups, theme_path=state.theme_path)
    return JSONResponse(tree)


async def get_file(request: Request) -> JSONResponse | Response:
    """GET /file?path=<relative> — read file content (accepts the theme alias)."""
    rel = request.query_params.get("path", "")

    resolved, error = _resolve_readwrite_path(request.app.state, rel)
    if error or resolved is None:
        return Response(status_code=400, content=error)

    if not resolved.exists():
        return Response(status_code=404, content="File not found")

    return JSONResponse({"content": resolved.read_text(), "path": rel})


async def put_file(request: Request) -> JSONResponse | Response:
    """PUT /file?path=<relative> — write file content (accepts the theme alias)."""
    rel = request.query_params.get("path", "")

    resolved, error = _resolve_readwrite_path(request.app.state, rel)
    if error or resolved is None:
        return Response(status_code=400, content=error)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    content = (await request.body()).decode("utf-8")
    resolved.write_text(content)

    # Theme write → tell clients to recompile with the new theme. Direct and
    # unconditional (same rationale as the create/rename/delete broadcasts):
    # the watcher can't see an outside-project theme at all, and even
    # in-project the direct event is deterministic. No file_change for the
    # alias — the tree entry is static.
    theme = getattr(request.app.state, "theme_path", None)
    if theme is not None and resolved == theme.resolve():
        await _broadcast(request, {"type": "theme_changed", "path": rel})

    return JSONResponse({"ok": True, "path": rel})


async def post_file(request: Request) -> JSONResponse | Response:
    """POST /file?path=<relative> — create a new file; 409 if it exists.

    Body (optional, utf-8) = initial content (used by Duplicate); empty body
    → template_for(...). Creates parent dirs.
    """
    project_dir: Path = request.app.state.project_dir
    rel = request.query_params.get("path", "")

    resolved, error = resolve_safe(project_dir, rel)
    if error:
        return Response(status_code=400, content=error)
    if resolved.suffix not in _ALLOWED_WRITE_EXTENSIONS:
        return Response(status_code=400, content=_EXTENSION_ERROR)
    if resolved.exists():
        return Response(status_code=409, content="File already exists")

    body = await request.body()
    content = body.decode("utf-8") if body else template_for(request.app.state, resolved)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)

    await _broadcast_file_change(request, "created", rel)
    return JSONResponse({"ok": True, "path": rel}, status_code=201)


async def rename_file(request: Request) -> JSONResponse | Response:
    """POST /file/rename?path=<old>&to=<new> — move/rename a file."""
    project_dir: Path = request.app.state.project_dir
    rel = request.query_params.get("path", "")
    to_rel = request.query_params.get("to", "")

    source, error = resolve_safe(project_dir, rel)
    if error:
        return Response(status_code=400, content=error)
    if not to_rel:
        return Response(status_code=400, content="Missing to parameter")
    target, error = resolve_safe(project_dir, to_rel)
    if error:
        return Response(status_code=400, content=error)

    if target.suffix not in _ALLOWED_WRITE_EXTENSIONS:
        return Response(status_code=400, content=_EXTENSION_ERROR)
    if not source.exists():
        return Response(status_code=404, content="File not found")
    if not source.is_file():
        return Response(status_code=400, content="Not a file")
    if target.exists():
        return Response(status_code=409, content="File already exists")

    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)

    await _broadcast_file_change(request, "deleted", rel)
    await _broadcast_file_change(request, "created", to_rel)
    return JSONResponse({"ok": True, "path": to_rel})


async def delete_file(request: Request) -> JSONResponse | Response:
    """DELETE /file?path=<relative> — delete a file (never a directory)."""
    project_dir: Path = request.app.state.project_dir
    rel = request.query_params.get("path", "")

    resolved, error = resolve_safe(project_dir, rel)
    if error:
        return Response(status_code=400, content=error)
    if not resolved.exists():
        return Response(status_code=404, content="File not found")
    # is_file before the extension check: a directory (usually suffix-less)
    # must report "Not a file", not a misleading extension error.
    if not resolved.is_file():
        return Response(status_code=400, content="Not a file")
    if resolved.suffix not in _ALLOWED_WRITE_EXTENSIONS:
        return Response(status_code=400, content=_EXTENSION_ERROR)

    resolved.unlink()

    await _broadcast_file_change(request, "deleted", rel)
    return JSONResponse({"ok": True})


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
    theme_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Build the /project tree as typed top-level groups.

    groups is [(role, dir), …] with role ∈ charts|dashboards|models|assets;
    emits one entry per configured dir:
    {"name": dir.name, "type": "dir", "path": rel, "group": role, "children": …}.
    Primary roles (charts/dashboards/models) are listed even when the dir is
    empty or missing — children: [] — so the UI can offer "create the first
    file" (SHE-42); assets keeps the omit-when-empty rule.
    Dirs that resolve outside project_dir are skipped with a warning
    (resolve_safe stays single-root, so their files would be unreachable).
    Duplicate dirs are emitted once — first role wins.
    When theme_path names an existing file, a top-level theme entry is
    appended last: real relative path when inside the project, else the
    exact-match "@theme/<name>" alias (SHE-44).

    Known edge (accepted, PR #62 review): a configured dir equal to
    project_dir walks the whole project into that group — deliberate, since
    a flat project may legitimately set charts_dir=project_dir — and other
    configured dirs nested inside it then appear twice (once in the walk,
    once as their own group) sharing collapse-state keys.
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
        children = build_tree(rd, root) if rd.is_dir() else []
        if not children and role not in _ALWAYS_LISTED_ROLES:
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
    if theme_path is not None:
        tp = theme_path.resolve()
        if tp.is_file():  # missing theme → no entry (nothing to open)
            rel = str(tp.relative_to(root)) if tp.is_relative_to(root) else theme_alias(theme_path)
            entries.append({"name": tp.name, "type": "file", "path": rel, "group": "theme"})
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
