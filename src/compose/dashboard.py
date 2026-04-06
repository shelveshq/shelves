"""
Dashboard Composition

Top-level orchestrator that composes a complete dashboard from a YAML file:
1. Parse dashboard YAML → DashboardSpec
2. Discover all sheet components in the layout tree
3. Compile each referenced chart YAML through the full pipeline
4. Pass compiled chart specs to the layout translator
5. Return a self-contained HTML string
"""

from __future__ import annotations

from pathlib import Path

from src.schema.chart_schema import parse_chart
from src.schema.layout_schema import (
    DashboardSpec,
    SheetComponent,
    load_dashboard,
)
from src.theme.merge import load_theme, merge_theme
from src.theme.theme_schema import ThemeSpec
from src.translator.layout import translate_dashboard
from src.translator.layout_flatten import FlatNode, flatten_dashboard
from src.translator.translate import translate_chart


def compose_dashboard(
    dashboard_path: Path,
    theme: ThemeSpec | None = None,
    chart_base_dir: Path | None = None,
    data_dir: Path | None = None,
    models_dir: Path | str | None = None,
    no_theme: bool = False,
) -> str:
    """Compose a complete dashboard from a dashboard YAML file.

    Args:
        dashboard_path: Path to the dashboard YAML file.
        theme: Optional ThemeSpec. If None, loads the default theme.
        chart_base_dir: Base directory for resolving chart link paths.
                       If None, defaults to the dashboard file's parent dir.
        data_dir: Base directory for resolving inline data source paths.
                 If None, defaults to the current working directory.
        models_dir: Optional path to models directory.
        no_theme: If True, skip theme merging for charts and layout.

    Returns:
        Complete HTML string for the dashboard.

    Raises:
        FileNotFoundError: if a sheet's link path doesn't resolve to a file.
        pydantic.ValidationError: if the dashboard or a chart YAML is invalid.
    """
    spec = load_dashboard(dashboard_path)

    if not no_theme:
        theme = theme or load_theme()
    else:
        theme = ThemeSpec()

    sheets = _discover_sheets(spec)

    base = chart_base_dir or dashboard_path.parent
    resolved_data_dir = Path(data_dir) if data_dir else Path.cwd()

    chart_specs: dict[str, dict] = {}
    for name, link in sheets.items():
        chart_path = base / link
        if not chart_path.exists():
            raise FileNotFoundError(
                f"Chart file not found: {chart_path} (referenced by sheet '{name}')"
            )
        try:
            vl = _compile_chart(chart_path, theme, resolved_data_dir, models_dir, no_theme)
        except Exception as e:
            raise RuntimeError(
                f"Failed to compile chart for sheet '{name}' (link: {link}): {e}"
            ) from e
        chart_specs[name] = vl

    html = translate_dashboard(spec, theme, chart_specs)
    return html


def _discover_sheets(spec: DashboardSpec) -> dict[str, str]:
    """Walk the flattened layout tree and find all sheet components.

    Returns a dict mapping component name → link path.
    Anonymous sheets get auto-generated names (auto-1, auto-2, ...).
    """
    flat_tree = flatten_dashboard(spec)
    sheets: dict[str, str] = {}
    auto_counter = [0]
    _walk_flat_tree(flat_tree, sheets, auto_counter)
    return sheets


def _walk_flat_tree(
    node: FlatNode,
    sheets: dict[str, str],
    auto_counter: list[int],
) -> None:
    """Recursively walk a FlatNode tree and collect sheet components."""
    comp = node.component
    if isinstance(comp, SheetComponent):
        sheet_name = node.name or f"auto-{_next_auto(auto_counter)}"
        if sheet_name not in sheets:
            sheets[sheet_name] = comp.link
    for child in node.children:
        _walk_flat_tree(child, sheets, auto_counter)


def _next_auto(counter: list[int]) -> int:
    counter[0] += 1
    return counter[0]


def _compile_chart(
    chart_path: Path,
    theme: ThemeSpec,
    data_dir: Path,
    models_dir: Path | str | None,
    no_theme: bool,
) -> dict:
    """Compile a single chart YAML through the full pipeline.

    Pipeline: parse_chart → translate_chart → merge_theme → data binding.

    Data binding is model-driven: loads the chart's model, then routes
    by source type — inline reads from data_dir, cube fetches from API.
    """
    yaml_string = chart_path.read_text()
    spec = parse_chart(yaml_string)

    vl = translate_chart(spec, models_dir=models_dir)

    if not no_theme:
        vl = merge_theme(vl, theme)

    # Data binding: load model and route by source type
    try:
        from src.models.loader import load_model

        model = load_model(spec.data, models_dir=models_dir)
        if model.source and model.source.type == "inline":
            import json

            data_path = Path(model.source.path)
            if not data_path.is_absolute():
                data_path = data_dir / data_path
            if data_path.exists():
                rows = json.loads(data_path.read_text())
                from src.data.bind import resolve_data

                vl = resolve_data(vl, spec, rows=rows)
        elif model.source and model.source.type == "cube":
            from src.data.bind import resolve_data

            vl = resolve_data(vl, spec, models_dir=models_dir)
    except Exception:
        pass  # Data binding is best-effort at compose time

    return vl
