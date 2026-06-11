from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shelves.studio.yaml_position import yaml_loc_to_position

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


def _clean_loc(loc: list) -> list:
    cleaned = []
    for seg in loc:
        if isinstance(seg, str):
            if seg.startswith("literal["):
                continue
            if seg[0:1].isupper() and seg.isidentifier():
                continue
            if re.match(r"^(list|dict|set)\[", seg):
                continue
        cleaned.append(seg)
    return cleaned


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
    result = []
    for err in exc.errors():
        loc = err["loc"]
        pos = yaml_loc_to_position(yaml_text, loc)
        result.append(
            {
                "loc": list(loc),
                "display_loc": _clean_loc(list(loc)),
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

    from shelves.pipeline import compile_chart, resolve_model_data

    yaml_body = (await request.body()).decode("utf-8")

    if not yaml_body.strip():
        return JSONResponse({"vega_lite_spec": None, "errors": ["Empty YAML body"], "warnings": []})

    # Skip non-chart YAML (e.g. dashboards, models)
    try:
        raw = _yaml.safe_load(yaml_body)
        if not isinstance(raw, dict) or "sheet" not in raw:
            return JSONResponse({"vega_lite_spec": None, "errors": [], "warnings": []})
    except Exception:
        pass  # Let compile_chart handle malformed YAML

    models_dir = request.app.state.models_dir
    theme_path: Path | None = request.app.state.theme_path

    try:
        vl_spec, spec = compile_chart(
            yaml_body,
            theme_path=theme_path,
            models_dir=models_dir if models_dir.exists() else None,
        )
    except ValidationError as e:
        return JSONResponse(
            {
                "vega_lite_spec": None,
                "errors": _format_validation_errors(e, yaml_body),
                "warnings": [],
            }
        )
    except _yaml.YAMLError as e:
        return JSONResponse(
            {
                "vega_lite_spec": None,
                "errors": [_format_yaml_error(e)],
                "warnings": [],
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
            }
        )

    warnings: list[str] = []
    try:
        vl_spec = resolve_model_data(
            vl_spec,
            spec,
            models_dir=models_dir,
            data_base_dir=request.app.state.project_dir,
        )
    except Exception as e:
        warnings.append(f"Data resolution skipped: {e}")

    return JSONResponse({"vega_lite_spec": vl_spec, "errors": [], "warnings": warnings})


async def get_schema() -> JSONResponse:
    """GET /schema — return ChartSpec JSON Schema for Monaco YAML validation."""
    from shelves.schema.chart_schema import ChartSpec

    return JSONResponse(ChartSpec.model_json_schema())
