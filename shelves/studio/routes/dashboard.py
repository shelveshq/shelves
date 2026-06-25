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
    result = await run_dashboard_pipeline(
        yaml_body, project_dir, charts_dir, theme_path, models_dir=models_dir
    )
    return JSONResponse(result)


async def run_dashboard_pipeline(
    yaml_body: str,
    project_dir: Path,
    charts_dir: Path,
    theme_path: Path | None,
    models_dir: Path | None = None,
) -> dict:
    """Run the dashboard compilation pipeline and return a result dict."""
    from shelves.pipeline import compile_chart, resolve_model_data
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
    from shelves.compose.dashboard import _discover_sheets

    sheets = _discover_sheets(flat_root)

    # Load theme
    try:
        theme = load_theme(theme_path) if theme_path else load_theme()
    except Exception:
        from shelves.theme.theme_schema import ThemeSpec

        theme = ThemeSpec()

    # Compile each referenced chart (resolved relative to charts_dir)
    warnings: list[str] = []
    chart_specs: dict[str, dict] = {}
    for name, link in sheets.items():
        chart_path = charts_dir / link
        if not chart_path.exists():
            return {
                "html": None,
                "errors": [f"Chart file not found: {link} (sheet '{name}')"],
                "warnings": [],
                "component_tree": [],
            }
        try:
            chart_yaml = chart_path.read_text()
            vl, chart_spec = compile_chart(
                chart_yaml,
                theme=theme,
                models_dir=models_dir if models_dir and models_dir.exists() else None,
            )
            try:
                vl = resolve_model_data(
                    vl,
                    chart_spec,
                    models_dir=models_dir,
                    data_base_dir=project_dir,
                )
            except Exception as de:
                warnings.append(f"Data resolution skipped for '{name}': {de}")
            chart_specs[name] = vl
        except Exception as e:
            warnings.append(f"Chart '{name}' ({link}): {e}")

    html = translate_dashboard(spec, theme, chart_specs)

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
    from shelves.schema.layout_schema import SheetComponent
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
