from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


async def compile_dashboard_yaml(request: Request) -> JSONResponse:
    """POST /compile-dashboard — compile dashboard YAML body to HTML + component tree."""
    yaml_body = (await request.body()).decode("utf-8")

    if not yaml_body.strip():
        return JSONResponse(
            {"html": None, "errors": ["Empty YAML body"], "warnings": [], "component_tree": []}
        )

    import yaml as _yaml

    try:
        raw = _yaml.safe_load(yaml_body)
    except Exception:
        return JSONResponse(
            {
                "html": None,
                "errors": ["Failed to parse YAML"],
                "warnings": [],
                "component_tree": [],
            }
        )

    if not isinstance(raw, dict) or "dashboard" not in raw:
        return JSONResponse(
            {
                "html": None,
                "errors": ["Not a dashboard YAML"],
                "warnings": [],
                "component_tree": [],
            }
        )

    project_dir: Path = request.app.state.project_dir
    charts_dir: Path = request.app.state.charts_dir
    theme_path: Path | None = request.app.state.theme_path
    models_dir: Path = request.app.state.models_dir
    parameters_path: Path | None = request.app.state.parameters_path
    overrides: dict[str, str] | None = None
    raw_header = request.headers.get("x-shelves-params")
    if raw_header:
        overrides = _parse_override_header(raw_header)

    result = await run_dashboard_pipeline(
        yaml_body,
        project_dir,
        charts_dir,
        theme_path,
        models_dir=models_dir,
        parameters_path=parameters_path,
        overrides=overrides,
    )
    return JSONResponse(result)


async def run_dashboard_pipeline(
    yaml_body: str,
    project_dir: Path,
    charts_dir: Path,
    theme_path: Path | None,
    models_dir: Path | None = None,
    parameters_path: Path | None = None,
    overrides: dict[str, str] | None = None,
) -> dict:
    """Run the dashboard compilation pipeline and return a result dict."""
    from shelves.params.resolve import load_parameter_set
    from shelves.schema.layout_schema import parse_dashboard
    from shelves.theme.merge import load_theme
    from shelves.translator.layout import translate_dashboard
    from shelves.translator.layout_flatten import flatten_dashboard

    # Resolve a models_dir usable for both chart compile and the per-sheet
    # resolver AND data resolution — one value, threaded everywhere, so the two
    # halves of a compile can never read different model directories.
    effective_models_dir = models_dir if models_dir and models_dir.exists() else None

    # SHE-96: parameters must be loaded BEFORE parse_dashboard so ${name}
    # references in text components are substituted before model_validate.
    try:
        parameters = load_parameter_set(
            parameters_path,
            models_dir=effective_models_dir,
            data_base_dir=project_dir,
            overrides=overrides,
        )
    except ValueError as e:
        return {
            "html": None,
            "errors": [str(e)],
            "warnings": [],
            "component_tree": [],
        }

    try:
        spec = parse_dashboard(yaml_body, parameters=parameters)
    except Exception as e:
        return {"html": None, "errors": [str(e)], "warnings": [], "component_tree": []}

    flat_root = flatten_dashboard(spec)
    component_tree = build_component_tree(flat_root)

    # Discover sheets (name → link) — reuse the already-flattened tree.
    from shelves.compose.dashboard import (
        _build_control_meta,
        _build_filter_control_meta,
        _build_filter_injections,
        _discover_controls,
        _discover_filters,
        _discover_sheets,
        _get_sheet_models,
        _validate_filters,
        compile_dashboard_charts,
        link_legends,
    )

    sheets = _discover_sheets(flat_root)

    # SHE-79: validate filter declarations against models and sheets.
    filters = _discover_filters(flat_root)
    sheet_models = _get_sheet_models(sheets, charts_dir) if filters else {}
    if filters:
        filter_errors = _validate_filters(
            filters,
            sheets=sheets,
            charts_dir=charts_dir,
            models_dir=effective_models_dir,
            sheet_models=sheet_models,
        )
        if filter_errors:
            return {
                "html": None,
                "errors": filter_errors,
                "warnings": [],
                "component_tree": component_tree,
            }

    # SHE-80: build filter injections and control metadata.
    try:
        filter_injections = (
            _build_filter_injections(filters, sheets, sheet_models, effective_models_dir)
            if filters
            else {}
        )
        filter_control_meta = (
            _build_filter_control_meta(flat_root, sheets, sheet_models, effective_models_dir)
            if filters
            else {}
        )
    except (TypeError, ValueError) as exc:
        return {
            "html": None,
            "errors": [f"Filter injection failed: {exc}"],
            "warnings": [],
            "component_tree": component_tree,
        }

    # Load theme
    try:
        theme = load_theme(theme_path) if theme_path else load_theme()
    except Exception:
        from shelves.theme.theme_schema import ThemeSpec

        theme = ThemeSpec()

    # Compile each referenced chart via the shared per-sheet loop (the same one
    # compose_dashboard uses — Studio is a surface, not a second compiler).
    # fail_fast=False: a missing/broken chart becomes a warning and an empty
    # sheet box; the rest of the dashboard still renders.
    # restrict_links=True: YAML posted to the server must not read files
    # outside charts_dir (absolute or ../ links are skipped with a warning).
    chart_specs, resolvers, warnings = compile_dashboard_charts(
        sheets,
        charts_dir,
        theme,
        models_dir=effective_models_dir,
        data_base_dir=project_dir,
        fail_fast=False,
        restrict_links=True,
        parameters=parameters,
        filter_injections=filter_injections,
    )

    # SHE-27: link legends to sheet scales + suppress in-sheet legends via the
    # shared helper (same path as compose_dashboard), routing the bad-source
    # ValueError into the Studio result dict rather than warnings.warn.
    try:
        legend_links, legend_warnings = link_legends(flat_root, sheets, chart_specs, resolvers)
    except ValueError as le:
        return {
            "html": None,
            "errors": [str(le)],
            "warnings": warnings,
            "component_tree": component_tree,
            "canvas": {"width": spec.canvas.width, "height": spec.canvas.height},
        }
    warnings.extend(legend_warnings)

    # SHE-92: discover controls and build metadata from the ParameterSet.
    controls = _discover_controls(flat_root)
    try:
        control_meta = _build_control_meta(controls, flat_root, parameters) if controls else {}
    except ValueError as ce:
        return {
            "html": None,
            "errors": [str(ce)],
            "warnings": warnings,
            "component_tree": component_tree,
            "canvas": {"width": spec.canvas.width, "height": spec.canvas.height},
        }

    # vega_src_base: the preview iframe (srcdoc) resolves relative URLs against
    # the studio origin, so it loads the vendored same-origin copies instead of
    # the CDN — immune to CDN blips and content blockers (SHE-77).
    html = translate_dashboard(
        spec,
        theme,
        chart_specs,
        legend_links=legend_links,
        flat_tree=flat_root,
        vega_src_base="/static/vendor",
        control_meta=control_meta,
        filter_control_meta=filter_control_meta,
        interactive=True,
    )

    return {
        "html": html,
        "errors": [],
        "warnings": warnings,
        "component_tree": component_tree,
        "canvas": {"width": spec.canvas.width, "height": spec.canvas.height},
    }


def _parse_override_header(raw: str) -> dict[str, str] | None:
    """Parse and validate the X-Shelves-Params header value.

    Returns a dict of string overrides, or None on parse/validation failure.
    Logs a warning instead of silently swallowing errors.
    """
    import json as _json
    import logging

    logger = logging.getLogger("shelves.studio")
    try:
        parsed = _json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("Malformed X-Shelves-Params header (ignored): %s", exc)
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "X-Shelves-Params header is not a JSON object (got %s, ignored)",
            type(parsed).__name__,
        )
        return None
    return {str(k): str(v) for k, v in parsed.items()}


def build_component_tree(flat_root: Any) -> list[dict]:
    """Walk a FlatNode tree and produce a flat list for the component tree strip.

    Walk order is depth-first pre-order.
    Each entry: {name, type, depth, link?, children_count}
    """
    from shelves.schema.layout_schema import ParameterComponent, SheetComponent
    from shelves.translator.layout_flatten import FlatNode

    result: list[dict] = []

    def _walk(node: FlatNode, depth: int) -> None:
        comp = node.component
        comp_type = type(comp).__name__.lower().replace("component", "")
        # Normalize type names
        if hasattr(comp, "orientation"):
            comp_type = getattr(comp, "orientation", "vertical")
        elif isinstance(comp, SheetComponent):
            comp_type = "sheet"
        elif isinstance(comp, ParameterComponent):
            comp_type = "parameter"

        entry: dict = {
            "name": node.name,
            "type": comp_type,
            "depth": depth,
            "children_count": len(node.children),
        }
        if isinstance(comp, SheetComponent):
            entry["link"] = comp.link

        result.append(entry)
        for child in node.children:
            _walk(child, depth + 1)

    _walk(flat_root, 0)
    return result
