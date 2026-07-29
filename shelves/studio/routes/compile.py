from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shelves.diagnostics import capture_warnings
from shelves.studio.yaml_position import resolve_locs

_FRIENDLY_MESSAGES: dict[str, str | Callable[[str], str]] = {
    "missing": "Required field",
    "extra_forbidden": "Unknown field",
    "string_type": "Expected a text value",
    "int_type": "Expected a whole number",
    "float_type": "Expected a number",
    "bool_type": "Expected true or false",
    "model_type": "Expected a name or an object with properties",
    "less_than_equal": lambda msg: msg.replace("Input should be l", "Value should be l"),
    "greater_than_equal": lambda msg: msg.replace("Input should be g", "Value should be g"),
}

_LITERAL_RE = re.compile(r"^Input should be (.+)$")


def _friendly_msg(err_type: str, raw_msg: str) -> str:
    entry = _FRIENDLY_MESSAGES.get(err_type)
    if entry is not None:
        return entry(raw_msg) if callable(entry) else entry

    if err_type == "literal_error":
        m = _LITERAL_RE.match(raw_msg)
        if m:
            values = m.group(1).replace("'", "").replace(" or ", ", ")
            return f"Invalid value. Expected: {values}"

    return raw_msg


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
    warnings: list[str] = []
    try:
        with capture_warnings(warnings):
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
        with capture_warnings(warnings):
            vl_spec = resolve_model_data(
                vl_spec,
                spec,
                models_dir=models_dir,
                data_base_dir=request.app.state.project_dir,
                parameters=parameters,
            )
    except Exception as e:
        warnings.append(f"Data resolution skipped: {e}")

    # model stays set when only data resolution was skipped — the compile
    # itself succeeded (the Data view labels its skipped state with it).
    return JSONResponse(
        {"vega_lite_spec": vl_spec, "errors": [], "warnings": warnings, "model": spec.data}
    )


async def get_schema() -> JSONResponse:
    """GET /schema — return ChartSpec JSON Schema for Monaco YAML validation."""
    from shelves.schema.chart_schema import ChartSpec

    return JSONResponse(ChartSpec.model_json_schema())
