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
from typing import Any

from shelves.compose.legend_link import resolve_legend_links
from shelves.data.errors import ParameterDomainError
from shelves.diagnostics import capture_warnings
from shelves.params.substitute import ParameterSet
from shelves.schema.field_types import FieldTypeResolver
from shelves.schema.layout_schema import (
    FilterComponent,
    LegendComponent,
    ParameterComponent,
    SheetComponent,
    load_dashboard,
)
from shelves.theme.merge import load_theme
from shelves.theme.theme_schema import ThemeSpec
from shelves.translator.layout import translate_dashboard
from shelves.translator.layout_flatten import FlatNode, flatten_dashboard
from shelves.translator.layout_styles import ControlMeta, FilterControlMeta, LegendLink


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
    spec = load_dashboard(dashboard_path, parameters=parameters)

    theme = ThemeSpec() if no_theme else (theme or load_theme())

    # Flatten once (it rebuilds the full tree with style merging) and reuse the
    # result for sheet discovery, legend discovery, and the layout translation.
    flat_tree = flatten_dashboard(spec)
    sheets = _discover_sheets(flat_tree)

    base = chart_base_dir or dashboard_path.parent

    # SHE-79: validate filter declarations against models and sheets.
    filters = _discover_filters(flat_tree)
    sheet_models = _get_sheet_models(sheets, base) if filters else {}
    if filters:
        filter_errors = _validate_filters(
            filters,
            sheets=sheets,
            charts_dir=base,
            models_dir=models_dir,
            sheet_models=sheet_models,
        )
        if filter_errors:
            raise ValueError(
                "Filter validation failed:\n" + "\n".join(f"  - {e}" for e in filter_errors)
            )

    # SHE-80: build filter injections and control metadata.
    filter_injections = (
        _build_filter_injections(filters, sheets, sheet_models, models_dir) if filters else {}
    )
    resolved_data_dir = Path(data_dir) if data_dir else Path.cwd()

    filter_control_meta = (
        _build_filter_control_meta(
            flat_tree, sheets, sheet_models, models_dir, data_base_dir=resolved_data_dir
        )
        if filters
        else {}
    )

    chart_specs, resolvers, chart_warnings = compile_dashboard_charts(
        sheets,
        base,
        theme,
        models_dir=models_dir,
        data_base_dir=resolved_data_dir,
        no_theme=no_theme,
        fail_fast=True,
        parameters=parameters,
        filter_injections=filter_injections,
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
        filter_control_meta=filter_control_meta,
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
    filter_injections: dict[str, list[dict]] | None = None,
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

    `filter_injections` (SHE-80): per-sheet extra filters built from dashboard
    filter controls. Keyed by sheet dom_id, each value is a list of
    ShelfFilter-shaped dicts appended to the chart's filters before compilation.

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
                extra = (filter_injections or {}).get(name)
                vl, chart_spec = compile_chart(
                    yaml_string,
                    theme=theme,
                    no_theme=no_theme,
                    models_dir=models_dir,
                    parameters=parameters,
                    extra_filters=extra,
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
    keyed by dom_id. The flat_tree is walked to find ParameterComponent nodes for
    their inline label override.
    """
    if not controls:
        return {}
    if parameters is None or not parameters.declared:
        undeclared = list(controls.values())
        raise ValueError(
            f"Controls reference parameters {undeclared!r} but no parameters are declared."
        )

    control_nodes: dict[str, ParameterComponent] = {}
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

        if default_str is None and options:
            default_str = options[0]["value"]

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


def _walk_control_nodes(node: FlatNode, out: dict[str, ParameterComponent]) -> None:
    if isinstance(node.component, ParameterComponent) and node.dom_id:
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

    if ptype == "date":
        return "date", None, None, None, None
    if ptype == "number":
        return "stepper", None, None, None, None

    return "text", None, None, None, None


def _discover_controls(flat_tree: FlatNode) -> dict[str, str]:
    """Walk an already-flattened tree and collect every ParameterComponent.

    Returns a dict mapping dom_id → param name.
    """
    controls: dict[str, str] = {}
    _walk_controls(flat_tree, controls)
    return controls


def _walk_controls(node: FlatNode, controls: dict[str, str]) -> None:
    if isinstance(node.component, ParameterComponent):
        assert node.dom_id is not None, "control node missing dom_id"
        controls[node.dom_id] = node.component.param
    for child in node.children:
        _walk_controls(child, controls)


# ─── Filter Discovery & Validation (SHE-79) ─────────────────────────


_DIMENSION_MODES = {"multi", "single", "wildcard"}
_QUANTITATIVE_MODES = {"range", "at_least", "at_most"}
_TEMPORAL_MODES = {"range", "after", "before"}


def _list_available_models(models_dir: Path | str | None) -> list[str]:
    if models_dir is None:
        return []
    d = Path(models_dir)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml") if p.is_file())


def _discover_filters(flat_tree: FlatNode) -> list[FilterComponent]:
    filters: list[FilterComponent] = []
    _walk_filters(flat_tree, filters)
    return filters


def _walk_filters(node: FlatNode, filters: list[FilterComponent]) -> None:
    if isinstance(node.component, FilterComponent):
        filters.append(node.component)
    for child in node.children:
        _walk_filters(child, filters)


def _validate_filters(
    filters: list[FilterComponent],
    *,
    sheets: dict[str, str],
    charts_dir: Path,
    models_dir: Path | str | None = None,
    sheet_models: dict[str, str] | None = None,
) -> list[str]:
    """Validate filter declarations against models and sheets.

    Returns a list of error strings (empty = all valid).
    """
    from shelves.models.loader import load_model
    from shelves.models.schema import (
        NominalDimensionDefinition,
        TemporalDimensionDefinition,
    )

    errors: list[str] = []

    if sheet_models is None:
        sheet_models = _get_sheet_models(sheets, charts_dir)

    for filt in filters:
        try:
            model = load_model(filt.model, models_dir=models_dir)
        except FileNotFoundError:
            available = _list_available_models(models_dir)
            suffix = f" Available models: {', '.join(available)}" if available else ""
            errors.append(f"Filter on '{filt.field}': model '{filt.model}' not found.{suffix}")
            continue

        dim = model.dimensions.get(filt.field)
        measure = model.measures.get(filt.field)
        if dim is None and measure is None:
            available = sorted(list(model.dimensions.keys()) + list(model.measures.keys()))
            errors.append(
                f"Filter field '{filt.field}' not found in model '{filt.model}'. "
                f"Available fields: {', '.join(available)}"
            )
            continue

        if filt.mode is not None:
            if isinstance(dim, TemporalDimensionDefinition):
                valid_modes = _TEMPORAL_MODES
                category = "temporal"
            elif isinstance(dim, NominalDimensionDefinition):
                valid_modes = _DIMENSION_MODES
                category = "dimension"
            elif measure is not None:
                valid_modes = _QUANTITATIVE_MODES
                category = "quantitative"
            else:
                valid_modes = _DIMENSION_MODES
                category = "dimension"

            if filt.mode not in valid_modes:
                errors.append(
                    f"Filter mode '{filt.mode}' is not valid for {category} "
                    f"field '{filt.field}'. Valid modes: {sorted(valid_modes)}"
                )

        if filt.default is not None and filt.mode is not None:
            mode = filt.mode
            if mode in ("multi", "range"):
                if not isinstance(filt.default, list):
                    errors.append(
                        f"Filter on '{filt.field}': mode '{mode}' requires a list "
                        f"default, got {type(filt.default).__name__}"
                    )
                elif mode == "range" and len(filt.default) != 2:
                    errors.append(
                        f"Filter on '{filt.field}': mode 'range' requires a "
                        f"[min, max] default (2 elements), got {len(filt.default)}"
                    )
            else:
                if isinstance(filt.default, list):
                    errors.append(
                        f"Filter on '{filt.field}': mode '{mode}' requires a "
                        f"scalar default, got list"
                    )

        if filt.targets == "all":
            matching = [sid for sid, m in sheet_models.items() if m == filt.model]
            if not matching:
                used_models = sorted(set(sheet_models.values()))
                errors.append(
                    f"Filter on '{filt.field}' targets all sheets with model "
                    f"'{filt.model}', but no sheet uses that model. "
                    f"Models used by sheets: {', '.join(used_models)}"
                )
        else:
            for target in filt.targets:
                if target not in sheets:
                    errors.append(
                        f"Filter on '{filt.field}' targets sheet '{target}', "
                        f"which does not exist. Available sheets: "
                        f"{', '.join(sorted(sheets.keys()))}"
                    )
                elif target in sheet_models and sheet_models[target] != filt.model:
                    errors.append(
                        f"Filter on '{filt.field}' uses model '{filt.model}' "
                        f"but target sheet '{target}' uses model "
                        f"'{sheet_models[target]}'."
                    )

    # Each (model, field, mode) filter must be unique across the dashboard: the
    # interactive override map is keyed by "model.field.mode", so two filters
    # that resolve to the same triple would share one override slot and clobber
    # each other on recompile (SHE-82 review, finding 2).
    seen: set[tuple[str, str, str]] = set()
    for filt in filters:
        try:
            resolved_mode = filt.mode if filt.mode is not None else _infer_mode(filt, models_dir)
        except FileNotFoundError:
            continue  # model-not-found is already reported above
        key = (filt.model, filt.field, resolved_mode)
        if key in seen:
            errors.append(
                f"Duplicate filter: model '{filt.model}', field '{filt.field}', "
                f"mode '{resolved_mode}' appears more than once. Each "
                f"model/field/mode filter must be unique within a dashboard "
                f"(interactive overrides are keyed by that triple)."
            )
        else:
            seen.add(key)

    return errors


# ─── Filter Injection (SHE-80) ────────────────────────────────────────


def _filter_override_key(model: str, field: str, mode: str) -> str:
    """Key for the interactive filter-override map: ``"model.field.mode"``.

    Includes the resolved mode so two filters on the same field but different
    modes (e.g. a wildcard search box and a multi-select list) each get their
    own override slot instead of clobbering one another (SHE-82 review).
    """
    return f"{model}.{field}.{mode}"


_MODE_TO_OPERATOR: dict[str, str] = {
    "multi": "in",
    "single": "eq",
    "wildcard": "contains",
    "range": "between",
    "at_least": "gte",
    "at_most": "lte",
    "after": "gte",
    "before": "lte",
}

_MODE_TO_WIDGET: dict[str, str] = {
    "multi": "multi_select",
    "single": "dropdown",
    "wildcard": "text",
    "at_least": "stepper",
    "at_most": "stepper",
    "after": "date",
    "before": "date",
}


def _infer_mode(filt: FilterComponent, models_dir: Path | str | None) -> str:
    """Infer filter mode from the field's type when mode is None."""
    from shelves.models.loader import load_model
    from shelves.models.schema import TemporalDimensionDefinition

    model = load_model(filt.model, models_dir=models_dir)
    dim = model.dimensions.get(filt.field)
    if dim is not None:
        if isinstance(dim, TemporalDimensionDefinition):
            return "range"
        return "multi"
    return "range"


def _infer_filter_widget(mode: str, filt: FilterComponent, models_dir: Path | str | None) -> str:
    """Infer widget type from mode, with field-type awareness for range.

    For the dimension modes `single`/`multi`, the `dropdown` flag picks between a
    compact dropdown widget (True, the default) and a top-aligned, scrollable
    open list (False).
    """
    if mode == "single":
        return "dropdown" if filt.dropdown else "single_list"
    if mode == "multi":
        return "multi_dropdown" if filt.dropdown else "multi_select"
    if mode == "range":
        from shelves.models.loader import load_model
        from shelves.models.schema import TemporalDimensionDefinition

        model = load_model(filt.model, models_dir=models_dir)
        dim = model.dimensions.get(filt.field)
        if isinstance(dim, TemporalDimensionDefinition):
            return "date_range"
        return "range"
    return _MODE_TO_WIDGET[mode]


def _resolve_filter_targets(
    filt: FilterComponent,
    sheets: dict[str, str],
    sheet_models: dict[str, str],
) -> list[str]:
    """Resolve a filter's targets to a list of sheet DOM IDs."""
    if filt.targets == "all":
        return [sid for sid, m in sheet_models.items() if m == filt.model]
    return [t for t in filt.targets if t in sheets]


def _build_shelf_filter_dict(mode: str, field: str, default: object) -> dict:
    """Build a ShelfFilter-shaped dict from a mode and default value."""
    operator = _MODE_TO_OPERATOR[mode]

    if mode == "multi":
        if not isinstance(default, list):
            raise TypeError(
                f"Filter mode 'multi' requires a list default, got {type(default).__name__}"
            )
        return {"field": field, "operator": operator, "values": default}

    if mode == "range":
        if not isinstance(default, list) or len(default) != 2:
            raise TypeError(
                f"Filter mode 'range' requires a [min, max] list default, "
                f"got {type(default).__name__}"
            )
        return {"field": field, "operator": operator, "range": default}

    return {"field": field, "operator": operator, "value": default}


def _build_filter_injections(
    filters: list[FilterComponent],
    sheets: dict[str, str],
    sheet_models: dict[str, str],
    models_dir: Path | str | None,
    *,
    filter_overrides: dict[str, Any] | None = None,
) -> dict[str, list[dict]]:
    """Build per-sheet filter injection dicts.

    Returns {sheet_dom_id: [ShelfFilter-shaped dicts]} for sheets that need
    extra filters injected before compilation.

    ``filter_overrides`` maps ``"model.field"`` → value; when present for a
    filter, the override replaces ``filt.default``.  A ``None`` override
    means "unfiltered" — the filter is skipped (same as a null default).
    """
    injections: dict[str, list[dict]] = {}
    overrides = filter_overrides or {}

    for filt in filters:
        mode = filt.mode if filt.mode is not None else _infer_mode(filt, models_dir)
        targets = _resolve_filter_targets(filt, sheets, sheet_models)

        override_key = _filter_override_key(filt.model, filt.field, mode)
        # .get() would swallow None overrides (None = unfiltered, not "use default")
        value = overrides[override_key] if override_key in overrides else filt.default  # noqa: SIM401

        if value is None:
            continue

        shelf_filter = _build_shelf_filter_dict(mode, filt.field, value)
        for target in targets:
            injections.setdefault(target, []).append(shelf_filter)

    return injections


def _discover_filters_with_dom_ids(
    flat_tree: FlatNode,
) -> list[tuple[str, FilterComponent]]:
    """Walk the flat tree and collect (dom_id, FilterComponent) pairs."""
    result: list[tuple[str, FilterComponent]] = []
    _walk_filters_with_ids(flat_tree, result)
    return result


def _walk_filters_with_ids(
    node: FlatNode,
    result: list[tuple[str, FilterComponent]],
) -> None:
    if isinstance(node.component, FilterComponent) and node.dom_id is not None:
        result.append((node.dom_id, node.component))
    for child in node.children:
        _walk_filters_with_ids(child, result)


def _get_sheet_models(sheets: dict[str, str], charts_dir: Path) -> dict[str, str]:
    """Map sheet DOM IDs to their model names by reading chart YAMLs."""
    import yaml as _yaml

    sheet_models: dict[str, str] = {}
    for sheet_id, link in sheets.items():
        chart_path = charts_dir / link
        if chart_path.exists():
            try:
                raw = _yaml.safe_load(chart_path.read_text())
            except _yaml.YAMLError:
                continue
            if isinstance(raw, dict) and "data" in raw:
                sheet_models[sheet_id] = raw["data"]
    return sheet_models


def _measure_bounds_duckdb(
    model: Any,
    field: str,
    data_base_dir: Path | None,
) -> tuple:
    """MIN/MAX of a measure's raw column via DuckDB."""
    from shelves.data.duckdb_adapter import DuckDBAdapter, _from_clause, _quote_identifier

    meas = model.measures.get(field)
    col = meas.column if meas is not None and meas.column else field
    adapter = DuckDBAdapter(base_dir=data_base_dir)
    file_path = adapter._source_file(model)
    expr = _quote_identifier(col)
    sql = f'SELECT MIN({expr}) AS "min", MAX({expr}) AS "max"\nFROM {_from_clause(file_path)}'
    rows = adapter._execute(sql)
    return (rows[0]["min"], rows[0]["max"]) if rows else (None, None)


def _resolve_filter_options(
    filt: FilterComponent,
    mode: str,
    *,
    models_dir: Path | str | None,
    data_base_dir: Path | None,
) -> tuple[list | None, bool]:
    """Resolve filter options from the data layer at compose time.

    Returns `(options, truncated)` — the options being a list of {value, label}
    dicts for categorical modes, a [min, max] pair for bounds modes, or None for
    wildcard. `truncated` is True when the domain hit MAX_DOMAIN_CARDINALITY and
    the list is only a prefix of the real one, in which case a `default:` outside
    it cannot be judged invalid.
    """
    if mode == "wildcard":
        return None, False

    from shelves.data.domains import (
        LiteralParamType,
        _inline_domain,
        _normalize,
        resolve_field_domain,
    )
    from shelves.models.loader import load_model
    from shelves.models.resolver import ModelResolver
    from shelves.models.schema import InlineSource, TemporalDimensionDefinition
    from shelves.params.schema import FieldRef

    model = load_model(filt.model, models_dir=models_dir)
    resolver = ModelResolver(model)
    is_measure = resolver.is_measure(filt.field)

    dim = model.dimensions.get(filt.field)
    is_temporal = isinstance(dim, TemporalDimensionDefinition)

    param_type: LiteralParamType
    if mode in ("multi", "single"):
        param_type = "string"
    elif is_temporal or mode in ("after", "before"):
        param_type = "date"
    else:
        param_type = "number"

    if is_measure:
        if model.source is None:
            raise ValueError(f"model {filt.model!r} has no source — cannot resolve filter options")

        import time

        from shelves.data.domains import DOMAIN_CACHE_TTL, _domain_cache

        cache_key = (
            "inline" if isinstance(model.source, InlineSource) else model.source.type,
            filt.model,
            filt.field,
            param_type,
        )
        cached = _domain_cache.get(cache_key)
        if cached is not None:
            domain, ts, _cached_warnings = cached
            if time.monotonic() - ts <= DOMAIN_CACHE_TTL:
                return [domain.min, domain.max], False

        if isinstance(model.source, InlineSource):
            raw = _inline_domain(
                model, filt.field, resolver, kind="bounds", data_base_dir=data_base_dir
            )
        elif model.source.type == "file":
            raw = _measure_bounds_duckdb(model, filt.field, data_base_dir)
        else:
            raise ValueError(
                f"measure bounds for field {filt.field!r} are not supported on "
                f"the {model.source.type!r} backend — use a dimension or mode: wildcard"
            )
        low, high = raw
        if low is None or high is None:
            raise ValueError(f"filter field {filt.field!r} resolved to an empty domain")
        result = [
            _normalize(low, param_type, False),
            _normalize(high, param_type, False),
        ]

        from shelves.data.domains import Domain

        _domain_cache[cache_key] = (
            Domain(
                kind="bounds",
                param_type=param_type,
                source=f"{filt.model}.{filt.field}",
                min=result[0],
                max=result[1],
            ),
            time.monotonic(),
            (),  # measure-bounds resolution emits no cacheable warnings
        )
        return result, False

    ref = FieldRef(model=filt.model, field=filt.field)
    domain = resolve_field_domain(
        ref, param_type, models_dir=models_dir, data_base_dir=data_base_dir
    )

    if domain.kind == "values":
        options = [{"value": v, "label": str(v)} for v in (domain.values or [])]
        return options, domain.truncated
    return [domain.min, domain.max], False


def _validate_filter_default(
    filt: FilterComponent, mode: str, options: list | None, *, truncated: bool = False
) -> None:
    """Validate that a filter's default value is within resolved options.

    A truncated domain is only a prefix of the real value set, so membership
    cannot be disproved — warn instead of rejecting a possibly-valid default.
    """
    if filt.default is None or options is None:
        return

    from shelves.data.domains import MAX_DOMAIN_CARDINALITY, _normalize

    if mode in ("multi", "single"):
        values = {o["value"] for o in options}
        if mode == "multi":
            defaults = filt.default if isinstance(filt.default, list) else [filt.default]
        else:
            defaults = [filt.default]
        for d in defaults:
            nd = _normalize(d, "string", False)
            if nd in values:
                continue
            if truncated:
                warnings.warn(
                    f"filter default {d!r} for field {filt.field!r} was not checked — "
                    f"the domain was truncated at {MAX_DOMAIN_CARDINALITY} values, "
                    "so membership is unknown.",
                    stacklevel=2,
                )
                continue
            raise ValueError(
                f"filter default {d!r} is not in the resolved domain for field {filt.field!r}"
            )
    elif mode in ("range", "at_least", "at_most", "after", "before"):
        lo, hi = options[0], options[1]
        is_temporal = isinstance(lo, str) and len(lo) == 10 and "-" in lo
        param_type = "date" if is_temporal else "number"
        check_vals = filt.default if isinstance(filt.default, list) else [filt.default]
        for v in check_vals:
            nv = _normalize(v, param_type, is_temporal)
            if nv < lo or nv > hi:
                raise ValueError(
                    f"filter default {v!r} is outside the resolved domain for "
                    f"field {filt.field!r} (min: {lo}, max: {hi})"
                )


def _build_filter_control_meta(
    flat_tree: FlatNode,
    sheets: dict[str, str],
    sheet_models: dict[str, str],
    models_dir: Path | str | None,
    data_base_dir: Path | None = None,
    *,
    filter_overrides: dict[str, Any] | None = None,
) -> dict[str, FilterControlMeta]:
    """Build FilterControlMeta for each filter control in the layout tree.

    ``filter_overrides`` maps ``"model.field"`` → value; when present for a
    filter, the override replaces ``filt.default`` in the rendered widget so the
    control shows the same value the injection applied (a recompile must not
    reset the widget to the YAML default while the chart stays filtered).
    """
    from shelves.models.loader import load_model

    overrides = filter_overrides or {}

    filter_nodes = _discover_filters_with_dom_ids(flat_tree)
    if not filter_nodes:
        return {}

    meta: dict[str, FilterControlMeta] = {}
    for dom_id, filt in filter_nodes:
        mode = filt.mode if filt.mode is not None else _infer_mode(filt, models_dir)
        operator = _MODE_TO_OPERATOR[mode]
        widget = _infer_filter_widget(mode, filt, models_dir)
        targets = _resolve_filter_targets(filt, sheets, sheet_models)
        target_ids = [f"sheet-{t}" for t in targets]

        title = filt.label
        if title is None:
            try:
                model = load_model(filt.model, models_dir=models_dir)
                dim = model.dimensions.get(filt.field)
                measure = model.measures.get(filt.field)
                field_def = dim or measure
                if field_def is not None:
                    title = field_def.label
            except FileNotFoundError:
                pass
        if title is None:
            title = filt.field

        try:
            options, truncated = _resolve_filter_options(
                filt, mode, models_dir=models_dir, data_base_dir=data_base_dir
            )
        except (ValueError, FileNotFoundError, ParameterDomainError) as e:
            warnings.warn(
                f"Filter options for '{filt.field}' could not be resolved: {e}",
                stacklevel=2,
            )
            options, truncated = None, False
        _validate_filter_default(filt, mode, options, truncated=truncated)

        # The rendered widget follows the active override (if any), so a recompile
        # keeps the control in sync with the value injected into the chart.
        # .get() would swallow None overrides (None = unfiltered, not "use default").
        override_key = _filter_override_key(filt.model, filt.field, mode)
        effective_default = (
            overrides[override_key] if override_key in overrides else filt.default  # noqa: SIM401
        )

        meta[dom_id] = FilterControlMeta(
            field=filt.field,
            model=filt.model,
            mode=mode,
            operator=operator,
            widget=widget,
            title=title,
            targets=target_ids,
            default=effective_default,
            options=options,
            dropdown=filt.dropdown,
        )

    return meta
