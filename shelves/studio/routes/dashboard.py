from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


async def compile_dashboard_yaml(request: Request) -> JSONResponse:
    """POST /compile-dashboard — compile dashboard YAML body to HTML + component tree."""
    yaml_body = (await request.body()).decode("utf-8")

    from shelves.studio.routes._diagnostics import runtime_error_item

    if not yaml_body.strip():
        return JSONResponse(
            {
                "html": None,
                "errors": [runtime_error_item("Empty YAML body", source="yaml")],
                "warnings": [],
                "component_tree": [],
            }
        )

    import yaml as _yaml

    # Malformed YAML falls through to run_dashboard_pipeline so its SHE-54
    # validator can return one *positioned* yaml_syntax error (SHE-105) rather
    # than a bare unanchored string. Only a well-formed non-dashboard mapping is
    # short-circuited here (a router mismatch, not a user diagnostic to place).
    try:
        raw = _yaml.safe_load(yaml_body)
        parse_ok = True
    except Exception:
        parse_ok = False

    if parse_ok and (not isinstance(raw, dict) or "dashboard" not in raw):
        return JSONResponse(
            {
                "html": None,
                "errors": [runtime_error_item("Not a dashboard YAML", source="yaml")],
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

    filter_overrides: dict[str, object] | None = None
    raw_filter_header = request.headers.get("x-shelves-filters")
    if raw_filter_header:
        filter_overrides = _parse_filter_header(raw_filter_header)

    result = await run_dashboard_pipeline(
        yaml_body,
        project_dir,
        charts_dir,
        theme_path,
        models_dir=models_dir,
        parameters_path=parameters_path,
        overrides=overrides,
        filter_overrides=filter_overrides,
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
    filter_overrides: dict[str, object] | None = None,
) -> dict:
    """Run the dashboard compilation pipeline and return a result dict.

    Errors and warnings are returned as **positioned structured objects**
    (SHE-105), matching the chart route: schema / YAML-syntax errors are placed
    inline by the SHE-54 renderer (`validate_dashboard_yaml`, the same one MCP
    `validate_spec` uses); sheet-level warnings anchor on the sheet node in the
    dashboard YAML; deeper runtime errors and dashboard-level warnings degrade
    to top-of-file (null line/col) when no clean loc is expressible.
    """
    import yaml as _yaml

    from shelves.diagnostics import capture_structured_warnings
    from shelves.errors import ShelvesError
    from shelves.params.resolve import load_parameter_set
    from shelves.schema.layout_schema import parse_dashboard
    from shelves.studio.routes._diagnostics import (
        _format_warnings,
        format_validation_items,
        runtime_error_item,
    )
    from shelves.theme.merge import load_theme
    from shelves.translator.layout import translate_dashboard
    from shelves.translator.layout_flatten import flatten_dashboard
    from shelves.validation import validate_dashboard_yaml

    # Resolve a models_dir usable for both chart compile and the per-sheet
    # resolver AND data resolution — one value, threaded everywhere, so the two
    # halves of a compile can never read different model directories.
    effective_models_dir = models_dir if models_dir and models_dir.exists() else None

    # ─ Errors (SHE-105) ────────────────────────────────────────────────
    # Schema + YAML-syntax errors are positioned by the SHE-54 renderer BEFORE
    # the compile pipeline — the identical renderer MCP validate_spec uses, so
    # the two surfaces agree. project_dir is intentionally NOT passed: a missing
    # sheet stays a per-sheet warning (the dashboard still renders the rest),
    # not a hard error.
    schema_result = validate_dashboard_yaml(yaml_body, models_dir=effective_models_dir)
    if schema_result.errors:
        return {
            "html": None,
            "errors": format_validation_items(schema_result.errors),
            "warnings": [],
            "component_tree": [],
        }

    # ─ Warnings (SHE-105) ──────────────────────────────────────────────
    # All warnings accumulate as structured records ({msg, loc, code, sheet})
    # and go through the shared _format_warnings resolver at the end. Sheet-
    # scoped records are re-anchored on the sheet node in the dashboard YAML via
    # `sheet_loc_map`; dashboard-level / legend / pre-loop records stay locless
    # (top-of-file fallback) — never a misleading anchor.
    raw = _yaml.safe_load(yaml_body)
    sheet_loc_map: dict[str, tuple] = {}

    def _finish(records: list[dict]) -> list[dict]:
        for r in records:
            if r.get("sheet") and not r.get("loc"):
                loc = sheet_loc_map.get(r["sheet"])
                if loc is not None:
                    r["loc"] = loc
        return _format_warnings(records, yaml_body)

    def _runtime_error(msg: str, *, source: str = "runtime", type_: str = "runtime_error") -> dict:
        return runtime_error_item(msg, source=source, type_=type_)

    # Records emitted before the per-sheet loop (parameter-domain truncation,
    # unverifiable defaults, filter options that would not resolve).
    pre_records: list[dict] = []

    # SHE-96: parameters must be loaded BEFORE parse_dashboard so ${name}
    # references in text components are substituted before model_validate.
    try:
        with capture_structured_warnings(pre_records):
            parameters = load_parameter_set(
                parameters_path,
                models_dir=effective_models_dir,
                data_base_dir=project_dir,
                overrides=overrides,
            )
    except ValueError as e:
        return {
            "html": None,
            "errors": [_runtime_error(str(e))],
            "warnings": _finish(pre_records),
            "component_tree": [],
        }

    try:
        spec = parse_dashboard(yaml_body, parameters=parameters)
    except Exception as e:
        return {
            "html": None,
            "errors": [_runtime_error(str(e))],
            "warnings": _finish(pre_records),
            "component_tree": [],
        }

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
    sheet_loc_map = _build_sheet_loc_map(raw, sheets)
    filter_loc_map = _build_filter_loc_map(raw)

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
                "errors": [
                    _runtime_error(e, source="dsl", type_="filter_error") for e in filter_errors
                ],
                "warnings": _finish(pre_records),
                "component_tree": component_tree,
            }

    # SHE-80: build filter injections and control metadata. Options resolution
    # warns (unresolvable options, truncated domains, unchecked defaults)
    # instead of raising, so capture or those notices never reach the client.
    try:
        with capture_structured_warnings(pre_records):
            filter_injections = (
                _build_filter_injections(
                    filters,
                    sheets,
                    sheet_models,
                    effective_models_dir,
                    filter_overrides=filter_overrides,
                )
                if filters
                else {}
            )
            filter_control_meta = (
                _build_filter_control_meta(
                    flat_root,
                    sheets,
                    sheet_models,
                    effective_models_dir,
                    data_base_dir=project_dir,
                    filter_overrides=filter_overrides,
                    field_loc_map=filter_loc_map,
                )
                if filters
                else {}
            )
    except (TypeError, ValueError, ShelvesError) as exc:
        # ShelvesError catches a data-layer failure (Cube/DuckDB) raised outside
        # _build_filter_control_meta's own option-resolution guard, so it becomes
        # a positioned error instead of a 500.
        return {
            "html": None,
            "errors": [_runtime_error(f"Filter injection failed: {exc}")],
            "warnings": _finish(pre_records),
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
    chart_specs, resolvers, chart_records = compile_dashboard_charts(
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
    # Chronological: everything resolved before the per-sheet loop ran first.
    records: list[dict] = [*pre_records, *chart_records]

    # SHE-27: link legends to sheet scales + suppress in-sheet legends via the
    # shared helper (same path as compose_dashboard), routing the bad-source
    # ValueError into the Studio result dict rather than warnings.warn.
    try:
        legend_links, legend_warnings = link_legends(flat_root, sheets, chart_specs, resolvers)
    except ValueError as le:
        return {
            "html": None,
            "errors": [_runtime_error(str(le))],
            "warnings": _finish(records),
            "component_tree": component_tree,
            "canvas": {"width": spec.canvas.width, "height": spec.canvas.height},
        }
    # Legend warnings name a sheet in prose but carry no clean YAML loc → locless.
    records.extend({"msg": w, "loc": None, "code": None, "sheet": None} for w in legend_warnings)

    # SHE-92: discover controls and build metadata from the ParameterSet.
    controls = _discover_controls(flat_root)
    try:
        control_meta = _build_control_meta(controls, flat_root, parameters) if controls else {}
    except ValueError as ce:
        return {
            "html": None,
            "errors": [_runtime_error(str(ce))],
            "warnings": _finish(records),
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
        "warnings": _finish(records),
        "component_tree": component_tree,
        "canvas": {"width": spec.canvas.width, "height": spec.canvas.height},
    }


def _build_sheet_loc_map(raw: object, sheets: dict[str, str]) -> dict[str, tuple]:
    """Map each sheet dom_id → the loc of its `sheet:` node in the dashboard YAML.

    Correlates by link: `_dashboard_sheet_refs` yields `(link, loc)` pairs from
    the raw dashboard dict, `sheets` gives dom_id → link. Only links that appear
    **exactly once** in the raw dict are anchored — those map unambiguously to
    their sole `sheet:` node.

    A repeated link is left unanchored (its warnings fall back to top-of-file).
    Raw-document order (which includes the `components:` block, whose entries may
    be unreferenced) and flatten-discovery order (referenced nodes only) need
    not agree, so zipping duplicates by index can land a warning on the wrong
    node — better no anchor than a misleading one. A dom_id whose link has no
    ref at all (named-component indirection) is likewise absent.
    """
    from collections import defaultdict

    from shelves.validation import _dashboard_sheet_refs

    locs_by_link: dict[str, list[tuple]] = defaultdict(list)
    for link, loc in _dashboard_sheet_refs(raw):
        locs_by_link[link].append(loc)

    loc_map: dict[str, tuple] = {}
    for dom_id, link in sheets.items():
        locs = locs_by_link.get(link, [])
        if len(locs) == 1:
            loc_map[dom_id] = locs[0]
    return loc_map


def _build_filter_loc_map(raw: object) -> dict[tuple[str, str], tuple]:
    """Map each filter's ``(model, field)`` → the loc of its `filter:` node.

    Lets a filter-domain warning (unresolvable options, unchecked truncated
    default) anchor on the filter component in the dashboard YAML (SHE-105).
    First occurrence wins for a repeated ``(model, field)`` (best-effort). The
    schema pass runs first and `model` is required, so it is always present here.
    """
    from shelves.validation import _dashboard_filter_refs

    loc_map: dict[tuple[str, str], tuple] = {}
    for field, model, loc in _dashboard_filter_refs(raw):
        if model is not None:
            loc_map.setdefault((model, field), loc)
    return loc_map


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


def _parse_filter_header(raw: str) -> dict[str, object] | None:
    """Parse X-Shelves-Filters header: ``{"model.field": value | null}``."""
    import json as _json
    import logging

    logger = logging.getLogger("shelves.studio")
    try:
        parsed = _json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("Malformed X-Shelves-Filters header (ignored): %s", exc)
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "X-Shelves-Filters header is not a JSON object (got %s, ignored)",
            type(parsed).__name__,
        )
        return None
    return dict(parsed)


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
