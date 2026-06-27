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

import contextlib
import warnings
from pathlib import Path

from shelves.compose.legend_link import resolve_legend_links
from shelves.models.loader import load_model
from shelves.models.resolver import ModelResolver
from shelves.schema.chart_schema import ChartSpec
from shelves.schema.field_types import FieldTypeResolver
from shelves.schema.layout_schema import (
    LegendComponent,
    SheetComponent,
    load_dashboard,
)
from shelves.theme.merge import load_theme
from shelves.theme.theme_schema import ThemeSpec
from shelves.translator.layout import translate_dashboard
from shelves.translator.layout_flatten import FlatNode, flatten_dashboard
from shelves.translator.layout_styles import LegendLink


def compose_dashboard(
    dashboard_path: Path,
    theme: ThemeSpec | None = None,
    chart_base_dir: Path | None = None,
    data_dir: Path | None = None,
    models_dir: Path | str | None = None,
    no_theme: bool = False,
    asset_url_prefix: str = "assets/",
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
        asset_url_prefix: URL prefix prepended to relative image srcs (default
            "assets/"). The render CLI passes a path computed relative to the
            output HTML's location.

    Returns:
        Complete HTML string for the dashboard.

    Raises:
        FileNotFoundError: if a sheet's link path doesn't resolve to a file.
        pydantic.ValidationError: if the dashboard or a chart YAML is invalid.
    """
    spec = load_dashboard(dashboard_path)

    theme = ThemeSpec() if no_theme else (theme or load_theme())

    # Flatten once (it rebuilds the full tree with style merging) and reuse the
    # result for sheet discovery, legend discovery, and the layout translation.
    flat_tree = flatten_dashboard(spec)
    sheets = _discover_sheets(flat_tree)

    base = chart_base_dir or dashboard_path.parent
    resolved_data_dir = Path(data_dir) if data_dir else Path.cwd()

    chart_specs: dict[str, dict] = {}
    resolvers: dict[str, FieldTypeResolver] = {}
    for name, link in sheets.items():
        chart_path = base / link
        if not chart_path.exists():
            raise FileNotFoundError(
                f"Chart file not found: {chart_path} (referenced by sheet '{name}')"
            )
        try:
            vl, chart_spec = _compile_chart(
                chart_path, theme, resolved_data_dir, models_dir, no_theme
            )
            resolver = ModelResolver(load_model(chart_spec.data, models_dir=models_dir))
        except Exception as e:
            raise RuntimeError(
                f"Failed to compile chart for sheet '{name}' (link: {link}): {e}"
            ) from e
        chart_specs[name] = vl
        resolvers[name] = resolver

    # SHE-10: link legends to sheet scales + suppress in-sheet legends.
    legend_links, legend_warnings = link_legends(flat_tree, sheets, chart_specs, resolvers)
    for msg in legend_warnings:
        warnings.warn(msg, stacklevel=2)

    html = translate_dashboard(
        spec,
        theme,
        chart_specs,
        asset_url_prefix=asset_url_prefix,
        legend_links=legend_links,
        flat_tree=flat_tree,
    )
    return html


def link_legends(
    flat_tree: FlatNode,
    sheets: dict[str, str],
    chart_specs: dict[str, dict],  # MUTATED: in-sheet legend suppression
    resolvers: dict[str, FieldTypeResolver],
) -> tuple[dict[tuple[str, str], LegendLink], list[str]]:
    """Discover legends in the layout tree, drop those bound to a sheet that
    failed to compile, and resolve the rest to scales (SHE-10).

    Shared by `compose_dashboard` and the Studio route so both treat legends
    identically — discovery, the compiled-sheet filter, and resolution live in
    one place rather than being re-implemented per surface.

    The filter relies on `chart_specs` and `resolvers` being kept in lock-step
    (every name in one is in the other), which both callers guarantee. A legend
    whose source matches no sheet at all is *kept* so `resolve_legend_links`
    still raises the bad-source ValueError; a legend bound to a sheet that did
    not compile (absent from `chart_specs`) is skipped so it renders as an empty
    box rather than dereferencing a resolver that was never built.
    """
    link_to_sheet: dict[str, str] = {}
    for name, link in sheets.items():
        link_to_sheet.setdefault(link, name)
    legends = [
        lg
        for lg in _discover_legends(flat_tree)
        if link_to_sheet.get(lg.source) is None or link_to_sheet[lg.source] in chart_specs
    ]
    return resolve_legend_links(legends, sheets, chart_specs, resolvers)


def _discover_sheets(flat_tree: FlatNode) -> dict[str, str]:
    """Walk an already-flattened layout tree and find all sheet components.

    Returns a dict mapping component name → link path.
    Anonymous sheets get auto-generated names (auto-1, auto-2, ...).
    """
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


def _discover_legends(flat_tree: FlatNode) -> list[LegendComponent]:
    """Walk an already-flattened layout tree and collect every LegendComponent
    (in document order)."""
    legends: list[LegendComponent] = []
    _walk_legends(flat_tree, legends)
    return legends


def _walk_legends(node: FlatNode, legends: list[LegendComponent]) -> None:
    """Recursively collect LegendComponents from a FlatNode tree."""
    if isinstance(node.component, LegendComponent):
        legends.append(node.component)
    for child in node.children:
        _walk_legends(child, legends)


def _compile_chart(
    chart_path: Path,
    theme: ThemeSpec,
    data_dir: Path,
    models_dir: Path | str | None,
    no_theme: bool,
) -> tuple[dict, ChartSpec]:
    """Compile a single chart YAML through the full pipeline.

    Pipeline: parse_chart → translate_chart → merge_theme → data binding.

    Data binding is model-driven: loads the chart's model, then routes
    by source type — inline reads from data_dir, cube fetches from API.

    Returns (vega_lite_spec, chart_spec); the ChartSpec is needed by the caller
    to build a resolver for legend linking (SHE-10).
    """
    from shelves.pipeline import compile_chart, resolve_model_data

    yaml_string = chart_path.read_text()
    vl, spec = compile_chart(
        yaml_string,
        theme=theme,
        no_theme=no_theme,
        models_dir=models_dir,
    )

    with contextlib.suppress(Exception):
        vl = resolve_model_data(vl, spec, models_dir=models_dir, data_base_dir=data_dir)

    return vl, spec
