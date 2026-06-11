from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from shelves.studio.yaml_position import yaml_loc_to_position


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
                "msg": err["msg"],
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
    except Exception as e:
        return JSONResponse({"vega_lite_spec": None, "errors": [str(e)], "warnings": []})

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
