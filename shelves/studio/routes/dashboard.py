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
    # SHE-92: controls in the iframe post param overrides via the parent frame,
    # which sends them as a JSON-encoded X-Shelves-Params header.
    overrides: dict[str, str] | None = None
    raw_header = request.headers.get("x-shelves-params")
    if raw_header:
        import contextlib
        import json as _json

        with contextlib.suppress(Exception):
            overrides = _json.loads(raw_header)

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
    from shelves.schema.layout_schema import parse_dashboard
    from shelves.theme.merge import load_theme
    from shelves.translator.layout import translate_dashboard
    from shelves.translator.layout_flatten import flatten_dashboard

    try:
        spec = parse_dashboard(yaml_body)
    except Exception as e:
        return {"html": None, "errors": [str(e)], "warnings": [], "component_tree": []}

    flat_root = flatten_dashboard(spec)
    component_tree = build_component_tree(flat_root)

    # Discover sheets (name → link) — reuse the already-flattened tree.
    from shelves.compose.dashboard import (
        _build_control_meta,
        _discover_controls,
        _discover_sheets,
        compile_dashboard_charts,
        link_legends,
    )

    sheets = _discover_sheets(flat_root)

    # Load theme
    try:
        theme = load_theme(theme_path) if theme_path else load_theme()
    except Exception:
        from shelves.theme.theme_schema import ThemeSpec

        theme = ThemeSpec()

    # Resolve a models_dir usable for both chart compile and the per-sheet
    # resolver AND data resolution — one value, threaded everywhere, so the two
    # halves of a compile can never read different model directories.
    effective_models_dir = models_dir if models_dir and models_dir.exists() else None

    from shelves.params.resolve import load_parameter_set

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
            "component_tree": component_tree,
            "canvas": {"width": spec.canvas.width, "height": spec.canvas.height},
        }

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
    )

    return {
        "html": html,
        "errors": [],
        "warnings": warnings,
        "component_tree": component_tree,
        "canvas": {"width": spec.canvas.width, "height": spec.canvas.height},
    }


def build_component_tree(flat_root: Any) -> list[dict]:
    """Walk a FlatNode tree and produce a flat list for the component tree strip.

    Walk order is depth-first pre-order.
    Each entry: {name, type, depth, link?, children_count}
    """
    from shelves.schema.layout_schema import ControlComponent, SheetComponent
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
        elif isinstance(comp, ControlComponent):
            comp_type = "control"

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
