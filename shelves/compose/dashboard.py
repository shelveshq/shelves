"""
Dashboard Composition

Top-level orchestrator that composes a complete dashboard from a YAML file:
1. Parse dashboard YAML → DashboardSpec
2. Discover all sheet components in the layout tree
3. Compile each referenced chart YAML through the full pipeline
4. Pass compiled chart specs to the layout translator
5. Return a self-contained HTML string

`compile_dashboard_charts` is the single per-sheet compile loop shared with
the Studio dashboard route — Studio is a surface, not a second compiler. Only
the *presentation* of failures differs per surface (`fail_fast` + how the
returned warnings are shown), never the loop itself.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from shelves.compose.legend_link import resolve_legend_links
from shelves.diagnostics import capture_warnings
from shelves.params.substitute import ParameterSet
from shelves.schema.field_types import FieldTypeResolver
from shelves.schema.layout_schema import (
    ControlComponent,
    LegendComponent,
    SheetComponent,
    load_dashboard,
)
from shelves.theme.merge import load_theme
from shelves.theme.theme_schema import ThemeSpec
from shelves.translator.layout import translate_dashboard
from shelves.translator.layout_flatten import FlatNode, flatten_dashboard
from shelves.translator.layout_styles import ControlMeta, LegendLink


def compose_dashboard(
    dashboard_path: Path,
    theme: ThemeSpec | None = None,
    chart_base_dir: Path | None = None,
    data_dir: Path | None = None,
    models_dir: Path | str | None = None,
    no_theme: bool = False,
    asset_url_prefix: str = "assets/",
    parameters: ParameterSet | None = None,
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
        parameters: Resolved project parameters, threaded to every sheet's
            compile. Built ONCE by the caller so all sheets in the dashboard
            see identical values.

    Returns:
        Complete HTML string for the dashboard.

    Raises:
        FileNotFoundError: if a sheet's link path doesn't resolve to a file.
        RuntimeError: if a chart YAML fails to compile (wraps the cause).
        pydantic.ValidationError: if the dashboard YAML is invalid.

    Data-resolution failures do not raise — the chart renders without data and
    the failure is emitted via `warnings.warn` (same message format Studio
    shows in its warnings panel).
    """
    spec = load_dashboard(dashboard_path)

    theme = ThemeSpec() if no_theme else (theme or load_theme())

    # Flatten once (it rebuilds the full tree with style merging) and reuse the
    # result for sheet discovery, legend discovery, and the layout translation.
    flat_tree = flatten_dashboard(spec)
    sheets = _discover_sheets(flat_tree)

    base = chart_base_dir or dashboard_path.parent
    resolved_data_dir = Path(data_dir) if data_dir else Path.cwd()

    chart_specs, resolvers, chart_warnings = compile_dashboard_charts(
        sheets,
        base,
        theme,
        models_dir=models_dir,
        data_base_dir=resolved_data_dir,
        no_theme=no_theme,
        fail_fast=True,
        parameters=parameters,
    )
    for msg in chart_warnings:
        warnings.warn(msg, stacklevel=2)

    # SHE-10: link legends to sheet scales + suppress in-sheet legends.
    legend_links, legend_warnings = link_legends(flat_tree, sheets, chart_specs, resolvers)
    for msg in legend_warnings:
        warnings.warn(msg, stacklevel=2)

    # SHE-92: discover controls and build metadata from the ParameterSet.
    controls = _discover_controls(flat_tree)
    control_meta = _build_control_meta(controls, flat_tree, parameters) if controls else {}

    html = translate_dashboard(
        spec,
        theme,
        chart_specs,
        asset_url_prefix=asset_url_prefix,
        legend_links=legend_links,
        flat_tree=flat_tree,
        control_meta=control_meta,
    )
    return html


def compile_dashboard_charts(
    sheets: dict[str, str],
    charts_dir: Path,
    theme: ThemeSpec,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
    no_theme: bool = False,
    fail_fast: bool = False,
    restrict_links: bool = False,
    parameters: ParameterSet | None = None,
) -> tuple[dict[str, dict], dict[str, FieldTypeResolver], list[str]]:
    """Compile every sheet's chart through the shared pipeline.

    The ONE dashboard chart loop — used by `compose_dashboard` (CLI) and the
    Studio dashboard route. Per sheet: read the YAML, `compile_chart`, best-
    effort `resolve_model_data`, build the ModelResolver, publish. The same
    `models_dir`/`data_base_dir` values feed compilation AND data resolution,
    so the two halves of a compile can never read different model universes.

    Failure semantics:
      - Missing chart file / compile error: `fail_fast=True` raises
        (FileNotFoundError / RuntimeError — the CLI contract); `fail_fast=False`
        records a warning and skips the sheet (the Studio contract — the
        dashboard still renders, the sheet is an empty box).
      - Data-resolution error: ALWAYS a warning ("Data resolution skipped for
        '<sheet>': ..."), never fatal — the chart renders without data.
      - `restrict_links=True` (the Studio server): a link that resolves
        outside `charts_dir` (absolute path or `..` traversal) is skipped with
        a warning — dashboard YAML posted to the server must not read
        arbitrary files (mirrors the route-level `resolve_safe` rule). The CLI
        compose surface leaves this off: local dashboards may legitimately
        reference charts outside --chart-dir via `../`.

    Warning messages show the link as written in the YAML; only the fail-fast
    exceptions carry the resolved absolute path (useful in CLI tracebacks,
    not something to surface to Studio clients).
      - Python warnings emitted during a sheet's compile (KPI shelf conflicts,
        tooltip disaggregation, ...) are captured into the returned list,
        prefixed with the sheet name, so Studio can display them.

    SHE-27: the resolver is built BEFORE publishing either dict, so
    `chart_specs` and `resolvers` stay in lock-step — a sheet that failed has
    neither, and legend linking never dereferences a resolver that was never
    built.

    Returns:
        (chart_specs, resolvers, warnings) — chart_specs/resolvers keyed by
        sheet dom_id; warnings as human-readable strings.
    """
    # Late imports, deliberately: the pipeline import avoids a circular import
    # through shelves/__init__, and load_model must be re-read per call so a
    # monkeypatched shelves.models.loader.load_model (resolver-failure tests)
    # is seen — a module-top binding would be frozen at import time.
    from shelves.models.loader import load_model
    from shelves.models.resolver import ModelResolver
    from shelves.pipeline import compile_chart, resolve_model_data

    chart_specs: dict[str, dict] = {}
    resolvers: dict[str, FieldTypeResolver] = {}
    warnings_out: list[str] = []

    for name, link in sheets.items():
        chart_path = charts_dir / link
        if restrict_links and not _link_is_contained(chart_path, charts_dir):
            warnings_out.append(
                f"Chart link '{link}' (sheet '{name}') is outside the charts "
                "directory and was skipped."
            )
            continue
        if not chart_path.exists():
            if fail_fast:
                raise FileNotFoundError(
                    f"Chart file not found: {chart_path} (referenced by sheet '{name}')"
                )
            warnings_out.append(f"Chart file not found: {link} (sheet '{name}')")
            continue

        try:
            with capture_warnings(warnings_out, prefix=f"Sheet '{name}': "):
                yaml_string = chart_path.read_text()
                vl, chart_spec = compile_chart(
                    yaml_string,
                    theme=theme,
                    no_theme=no_theme,
                    models_dir=models_dir,
                    parameters=parameters,
                )
                try:
                    vl = resolve_model_data(
                        vl,
                        chart_spec,
                        models_dir=models_dir,
                        data_base_dir=data_base_dir,
                        parameters=parameters,
                    )
                except Exception as de:
                    warnings_out.append(f"Data resolution skipped for '{name}': {de}")
                resolver = ModelResolver(load_model(chart_spec.data, models_dir=models_dir))
        except Exception as e:
            if fail_fast:
                raise RuntimeError(
                    f"Failed to compile chart for sheet '{name}' (link: {link}): {e}"
                ) from e
            warnings_out.append(f"Chart '{name}' ({link}): {e}")
            continue
        chart_specs[name] = vl
        resolvers[name] = resolver

    return chart_specs, resolvers, warnings_out


def _link_is_contained(chart_path: Path, charts_dir: Path) -> bool:
    """True if `chart_path` resolves to a location inside `charts_dir`.

    Resolves symlinks and `..` segments; an unresolvable path is treated as
    escaping (fail closed).
    """
    try:
        return chart_path.resolve().is_relative_to(charts_dir.resolve())
    except OSError:
        return False


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

    Returns a dict mapping the sheet's `dom_id` (the explicit name, or `auto-N`
    for anonymous sheets — assigned once by flatten, SHE-29) → link path.
    """
    sheets: dict[str, str] = {}
    _walk_flat_tree(flat_tree, sheets)
    return sheets


def _walk_flat_tree(node: FlatNode, sheets: dict[str, str]) -> None:
    """Recursively collect sheet components, keyed by their flatten-time dom_id."""
    comp = node.component
    if isinstance(comp, SheetComponent):
        assert node.dom_id is not None, "sheet node missing dom_id (flatten must assign it)"
        if node.dom_id not in sheets:
            sheets[node.dom_id] = comp.link
    for child in node.children:
        _walk_flat_tree(child, sheets)


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


def _build_control_meta(
    controls: dict[str, str],
    flat_tree: FlatNode,
    parameters: ParameterSet | None,
) -> dict[str, ControlMeta]:
    """Build ControlMeta for each discovered control from the ParameterSet.

    Validates that each control's param is a declared parameter. Returns a dict
    keyed by dom_id. The flat_tree is walked to find ControlComponent nodes for
    their inline label override.
    """
    if not controls:
        return {}
    if parameters is None or not parameters.declared:
        undeclared = list(controls.values())
        raise ValueError(
            f"Controls reference parameters {undeclared!r} but no parameters are declared."
        )

    control_nodes: dict[str, ControlComponent] = {}
    _walk_control_nodes(flat_tree, control_nodes)

    meta: dict[str, ControlMeta] = {}
    for dom_id, param_name in controls.items():
        if param_name not in parameters.declared:
            raise ValueError(
                f"'{param_name}' is not a declared parameter. "
                f"Declared: {', '.join(sorted(parameters.declared))}."
            )

        param_def = parameters.declared[param_name]
        comp = control_nodes.get(dom_id)
        inline_label = comp.label if comp else None
        title = inline_label or param_def.label or param_name

        default = parameters.values.get(param_name)
        default_str = str(default) if default is not None else None

        widget, options, rmin, rmax, rstep = _infer_widget(param_def, param_name, parameters)

        meta[dom_id] = ControlMeta(
            param=param_name,
            widget=widget,
            title=title,
            default=default_str,
            options=options,
            min=rmin,
            max=rmax,
            step=rstep,
        )
    return meta


def _walk_control_nodes(node: FlatNode, out: dict[str, ControlComponent]) -> None:
    if isinstance(node.component, ControlComponent) and node.dom_id:
        out[node.dom_id] = node.component
    for child in node.children:
        _walk_control_nodes(child, out)


def _infer_widget(
    param_def: object,
    param_name: str,
    parameters: ParameterSet,
) -> tuple[str, list[dict[str, str]] | None, str | None, str | None, str | None]:
    """Infer widget type and build options/range from a parameter definition.

    Returns (widget, options, min, max, step).
    """
    from shelves.params.schema import FieldRef, RangeBounds

    ptype = param_def.type  # type: ignore[attr-defined]
    values = param_def.values  # type: ignore[attr-defined]

    if ptype == "field":
        opts = []
        for v in values or []:
            if isinstance(v, FieldRef) and v.field:
                opts.append({"value": v.field, "label": v.field})
        return "dropdown", opts, None, None, None

    if values:
        first = values[0]
        if isinstance(first, RangeBounds):
            widget = "date" if ptype == "date" else "stepper"
            return (
                widget,
                None,
                str(first.min),
                str(first.max),
                str(first.step) if first.step is not None else None,
            )
        if isinstance(first, FieldRef):
            domain = parameters.domains.get(param_name)
            if domain and domain.values:
                opts = [{"value": str(v), "label": str(v)} for v in domain.values]
            else:
                current = parameters.values.get(param_name)
                opts = [{"value": str(current), "label": str(current)}] if current else []
            return "dropdown", opts, None, None, None
        opts = [{"value": str(v), "label": str(v)} for v in values]
        return "dropdown", opts, None, None, None

    if ptype == "string":
        return "text", None, None, None, None

    return "text", None, None, None, None


def _discover_controls(flat_tree: FlatNode) -> dict[str, str]:
    """Walk an already-flattened tree and collect every ControlComponent.

    Returns a dict mapping dom_id → param name.
    """
    controls: dict[str, str] = {}
    _walk_controls(flat_tree, controls)
    return controls


def _walk_controls(node: FlatNode, controls: dict[str, str]) -> None:
    if isinstance(node.component, ControlComponent):
        assert node.dom_id is not None, "control node missing dom_id"
        controls[node.dom_id] = node.component.param
    for child in node.children:
        _walk_controls(child, controls)
