from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shelves.diagnostics import capture_structured_warnings
from shelves.schema.yaml_position import resolve_locs
from shelves.validation import friendly_message as _friendly_msg

# Error rendering (friendly-message table, literal parsing) is owned by
# `shelves.validation` (SHE-54) so the CLI, the MCP tool, and this route render
# Pydantic errors identically. This route keeps its own response *shape* (the
# `friendly_msg`/`display_loc`/`source` dict the studio frontend consumes); only
# the message text comes from the shared renderer.


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


async def compile_yaml(request: Request) -> JSONResponse:
    """POST /compile — compile YAML body to Vega-Lite spec."""
    import yaml as _yaml

    from shelves.params.resolve import load_parameter_set
    from shelves.params.substitute import ParameterReferenceError as _ParameterReferenceError
    from shelves.pipeline import compile_chart, resolve_model_data

    yaml_body = (await request.body()).decode("utf-8")

    if not yaml_body.strip():
        return JSONResponse(
            {
                "vega_lite_spec": None,
                "errors": ["Empty YAML body"],
                "warnings": [],
                "model": None,
            }
        )

    # Skip non-chart YAML (e.g. dashboards, models)
    try:
        raw = _yaml.safe_load(yaml_body)
        if not isinstance(raw, dict) or "sheet" not in raw:
            return JSONResponse(
                {"vega_lite_spec": None, "errors": [], "warnings": [], "model": None}
            )
    except Exception:
        pass  # Let compile_chart handle malformed YAML

    models_dir = request.app.state.models_dir
    theme_path: Path | None = request.app.state.theme_path
    effective_models_dir = models_dir if models_dir.exists() else None

    # Python warnings emitted during compile (KPI shelf conflicts, tooltip
    # disaggregation, ...) are invisible to Studio unless captured into the
    # structured warnings list the frontend displays.
    raw_warnings: list[dict] = []
    try:
        with capture_structured_warnings(raw_warnings):
            parameters = load_parameter_set(
                request.app.state.parameters_path,
                models_dir=effective_models_dir,
                data_base_dir=request.app.state.project_dir,
            )
            vl_spec, spec = compile_chart(
                yaml_body,
                theme_path=theme_path,
                models_dir=effective_models_dir,
                parameters=parameters,
            )
    except ValidationError as e:
        return JSONResponse(
            {
                "vega_lite_spec": None,
                "errors": _format_validation_errors(e, yaml_body),
                "warnings": [],
                "model": None,
            }
        )
    except _ParameterReferenceError as e:
        return JSONResponse(
            {
                "vega_lite_spec": None,
                "errors": [
                    {
                        "loc": [d.path],
                        "display_loc": [d.path],
                        "msg": d.message,
                        "friendly_msg": d.message,
                        "source": "parameter",
                        "type": d.code,
                        "line": None,
                        "col": None,
                    }
                    for d in e.diagnostics
                ],
                "warnings": [],
                "model": None,
            }
        )
    except _yaml.YAMLError as e:
        return JSONResponse(
            {
                "vega_lite_spec": None,
                "errors": [_format_yaml_error(e)],
                "warnings": [],
                "model": None,
            }
        )
    except Exception as e:
        return JSONResponse(
            {
                "vega_lite_spec": None,
                "errors": [
                    {
                        "loc": [],
                        "display_loc": [],
                        "msg": str(e),
                        "friendly_msg": str(e),
                        "source": "runtime",
                        "type": "runtime_error",
                        "line": None,
                        "col": None,
                    }
                ],
                "warnings": [],
                "model": None,
            }
        )

    try:
        with capture_structured_warnings(raw_warnings):
            vl_spec = resolve_model_data(
                vl_spec,
                spec,
                models_dir=models_dir,
                data_base_dir=request.app.state.project_dir,
                parameters=parameters,
            )
    except Exception as e:
        raw_warnings.append({"msg": f"Data resolution skipped: {e}", "loc": None, "code": None})

    # model stays set when only data resolution was skipped — the compile
    # itself succeeded (the Data view labels its skipped state with it).
    return JSONResponse(
        {
            "vega_lite_spec": vl_spec,
            "errors": [],
            "warnings": _format_warnings(raw_warnings, yaml_body),
            "model": spec.data,
        }
    )


async def get_schema() -> JSONResponse:
    """GET /schema — return ChartSpec JSON Schema for Monaco YAML validation."""
    from shelves.schema.json_schema import chart_json_schema

    return JSONResponse(chart_json_schema())
