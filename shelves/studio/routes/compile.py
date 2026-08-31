from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shelves.diagnostics import capture_structured_warnings

# Diagnostics formatting (Pydantic/YAML errors, captured warnings) is owned by
# `routes/_diagnostics` (SHE-105) so this chart route and the dashboard route
# paint identical inline markers. Re-exported here for backward compatibility —
# `lifespan.py` and the chart-route tests import these names from `compile`.
from shelves.studio.routes._diagnostics import (
    _format_validation_errors,
    _format_warnings,
    _format_yaml_error,
)

__all__ = [
    "_format_validation_errors",
    "_format_warnings",
    "_format_yaml_error",
    "compile_yaml",
    "get_schema",
]


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
