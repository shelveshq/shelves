"""
Shared Studio diagnostics formatting (SHE-105).

The chart route (`compile.py`) and the dashboard route (`dashboard.py`) both
turn Pydantic errors, YAML-syntax errors, and captured warnings into the dict
shape `editor.js` consumes (`friendly_msg`/`display_loc`/`source`/`line`/`col`).
Keeping the formatters here — one implementation, imported by both — is what
lets the two routes paint identical inline markers. `format_validation_items`
additionally adapts the SHE-54 `ValidationErrorItem` (the renderer MCP
`validate_spec` uses) into that same shape, so the dashboard error surface and
`validate_spec` agree by construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shelves.schema.yaml_position import resolve_locs
from shelves.validation import friendly_message as _friendly_msg

if TYPE_CHECKING:
    from pydantic import ValidationError

    from shelves.validation import ValidationErrorItem


def runtime_error_item(msg: str, *, source: str = "runtime", type_: str = "runtime_error") -> dict:
    """A locless, top-of-file structured error dict (the Studio error shape).

    The fallback for dashboard failures with no expressible YAML position
    (empty body, wrong root key, an unexpected exception). Emitting the full
    dict — never a bare string — keeps every consumer (`applyCompileMarkers`,
    the overlay, the status counts) rendering an error uniformly; a bare string
    error is silently dropped by the marker pass (SHE-105).
    """
    return {
        "loc": [],
        "display_loc": [],
        "msg": msg,
        "friendly_msg": msg,
        "source": source,
        "type": type_,
        "line": None,
        "col": None,
    }


def _format_yaml_error(exc: Exception) -> dict:
    line = None
    col = None
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        line = mark.line + 1
        col = mark.column + 1

    problem = getattr(exc, "problem", None)
    if problem:
        friendly = problem.replace("<stream end>", "end of input")
        friendly = friendly.replace("<block end>", "end of block")
        friendly = friendly[0].upper() + friendly[1:] if friendly else friendly
    else:
        friendly = str(exc)

    return {
        "loc": [],
        "display_loc": [],
        "msg": str(exc),
        "friendly_msg": friendly,
        "source": "yaml",
        "type": "yaml_syntax",
        "line": line,
        "col": col,
    }


def _format_validation_errors(
    exc: ValidationError,
    yaml_text: str,
) -> list[dict]:
    """Convert a Pydantic ValidationError into structured error dicts with line/col."""
    errors = exc.errors()
    resolved = resolve_locs(yaml_text, [err["loc"] for err in errors])
    result = []
    for err, info in zip(errors, resolved, strict=True):
        pos = info["position"]
        result.append(
            {
                "loc": list(err["loc"]),
                "display_loc": info["display_loc"],
                "msg": err["msg"],
                "friendly_msg": _friendly_msg(err["type"], err["msg"]),
                "source": "dsl",
                "type": err["type"],
                "line": pos[0] if pos else None,
                "col": pos[1] if pos else None,
            }
        )
    return result


def _format_warnings(raw_warnings: list[dict], yaml_text: str) -> list[dict]:
    """Resolve each captured warning's loc to a line/col, mirroring the error shape.

    Warnings carrying a `loc` (from a `PositionedWarning`) go through the same
    `resolve_locs` path the structured error renderer uses — one parse for all
    warnings, key-position placement, and display-loc cleaning. Warnings with no
    loc (or a loc that no longer resolves) get null line/col; the editor falls
    back to the top of the file for those.
    """
    indexed = [(i, tuple(w["loc"])) for i, w in enumerate(raw_warnings) if w.get("loc")]
    resolved = resolve_locs(yaml_text, [loc for _, loc in indexed])
    by_index = {i: info for (i, _), info in zip(indexed, resolved, strict=True)}

    result: list[dict] = []
    for i, w in enumerate(raw_warnings):
        info = by_index.get(i)
        pos = info["position"] if info else None
        result.append(
            {
                "loc": list(w["loc"]) if w.get("loc") else [],
                "display_loc": info["display_loc"] if info else [],
                "msg": w["msg"],
                "code": w.get("code") or "warning",
                "source": "warning",
                "line": pos[0] if pos else None,
                "col": pos[1] if pos else None,
            }
        )
    return result


# Map the SHE-54 error `source` onto the Studio frontend's tag vocabulary:
# schema/model both read as `[DSL]` (the chart route's treatment), yaml stays yaml.
_SOURCE_TO_STUDIO = {"schema": "dsl", "model": "dsl", "yaml": "yaml"}


def format_validation_items(items: list[ValidationErrorItem]) -> list[dict]:
    """Adapt SHE-54 `ValidationErrorItem`s → the Studio error dict shape.

    Reuses the renderer `validate_dashboard_yaml` (and MCP `validate_spec`)
    already produce, so the dashboard route's schema / yaml-syntax error markers
    are identical to the MCP tool's for the same YAML. `friendly_msg` = the
    renderer's plain-language `message`; `display_loc` = the dotted `path`;
    `type` = the stable `code`.
    """
    result: list[dict] = []
    for it in items:
        result.append(
            {
                "loc": list(it.loc),
                "display_loc": [it.path] if it.path else [],
                "msg": it.message,
                "friendly_msg": it.message,
                "source": _SOURCE_TO_STUDIO.get(it.source, it.source),
                "type": it.code,
                "line": it.line,
                "col": it.col,
            }
        )
    return result
