"""
Layer Compiler (Phase 1a)

Handles MeasureEntry objects that have a `layer` property. Called by stacked.py
when it detects layers in any entry of a multi-measure shelf.

═══ Architecture: KAN-111 / KAN-112 split ════════════════════════════════════

This module is built around one core function (`compile_layer_entry`) and one
dispatcher (`compile_stacked_with_layers`). The dispatcher is the single owner
of the "layered shelf compilation" decision; stacked.py delegates ALL layered
specs to it without inspecting them further.

  compile_stacked_with_layers(spec, entries, ...)
      │
      ├── len(entries) == 1   →  compile_layer_entry(entries[0], ...)
      │                          [KAN-111 — implemented here]
      │
      └── len(entries) > 1    →  iterate entries; for each, either call
                                 compile_layer_entry (if entry.layer) or
                                 _build_simple_panel (if no layer); wrap the
                                 results in vconcat/hconcat.
                                 [KAN-112 — implemented]

`compile_layer_entry` is reusable as the unit of work — KAN-112's multi-entry
loop calls it for any entry that has layers. KAN-112 only adds the iteration
shell, the simple-panel builder, and the concat wrapping; the layer logic
itself is stable.

═══ What compile_layer_entry produces ════════════════════════════════════════

For a single MeasureEntry:

    rows:
      - measure: revenue
        mark: bar
        color: country
        layer:
          - measure: arpu
            mark: {type: line, style: dashed}
            color: "#666666"
        axis: independent

it produces:

    {
      "layer": [
        {"mark": "bar",
         "encoding": {"x": <shared>, "y": {"field": "revenue", ...},
                      "color": {"field": "country", ...},
                      "tooltip": [...]}},
        {"mark": {"type": "line", "strokeDash": [6, 4]},
         "encoding": {"x": <shared>, "y": {"field": "arpu", ...},
                      "color": {"value": "#666666"}}}
      ],
      "resolve": {"scale": {"y": "independent"}},   # only if axis: independent
      "transform": [...]                             # only if spec.filters set
    }

═══ Inheritance ══════════════════════════════════════════════════════════════

Encoding properties cascade top-level → entry → layer (more specific wins):
  - mark   — 3-level cascade. Must resolve to something (raises ValueError if not).
  - color  — 3-level cascade. None at all levels → no color encoding.
  - detail — 3-level cascade WITH explicit-null suppression. Layer's
             `detail: null` (vs omitted) suppresses inheritance.
  - size   — 3-level cascade.
  - opacity — does NOT cascade. Each level applies opacity to its own mark.

`tooltip` is set at spec-level only and applied to the primary layer only.
`filter` is set at spec-level only and applied to the layer-group top-level.
`sort` is set at spec-level only and applied to the primary layer's shared axis.

═══ Facet interaction ════════════════════════════════════════════════════════

facet.py wraps whatever inner spec it receives. A layer spec
{layer: [...], resolve: {...}} wraps identically to a simple
{mark: ..., encoding: ...}. No changes needed in facet.py for layers.
The integration test (KAN-113) lives in test_layers.py.
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import ChartSpec, ColorSpec, LayerEntry, MarkSpec, MeasureEntry
from shelves.schema.field_types import FieldTypeResolver
from shelves.translator.encodings import (
    _auto_inject_from_model,
    build_color,
    build_detail,
    build_field_encoding,
    build_size,
    build_tooltip,
)
from shelves.translator.filters import build_transforms
from shelves.translator.marks import build_mark
from shelves.translator.sort import apply_sort


def compile_stacked_with_layers(
    spec: ChartSpec,
    entries: list[MeasureEntry],
    shared_field: str,
    shared_axis: str,
    measure_axis: str,
    concat_key: str,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """
    Compile a multi-measure shelf where at least one entry has a `layer`.

    Dispatcher:
      - len(entries) == 1: pure layer spec via compile_layer_entry.
        No vconcat wrapper needed — the single entry's layers ARE the
        whole chart.
      - len(entries) > 1:  KAN-112. Iterate entries, call compile_layer_entry
        for layered entries and _build_simple_panel for standalone entries,
        wrap in {concat_key: [...]}.

    Args:
        spec, resolver:                    Standard.
        entries:                            spec.rows or spec.cols (the multi-measure shelf).
        shared_field:                       Field name on the non-multi shelf (e.g. "week").
        shared_axis, measure_axis:          "x"/"y" — derived by stacked.py.
        concat_key:                         "vconcat" if rows is multi, "hconcat" if cols is multi.
                                            Only used by the multi-entry branch (KAN-112).

    Returns: Vega-Lite spec dict (layer for single-entry; concat for multi-entry).
    """
    # Build the shared axis encoding once — both branches need it.
    shared_enc = build_field_encoding(shared_field, resolver)

    # Single-entry branch (KAN-111): pure layer spec, no concat wrapper.
    if len(entries) == 1:
        return compile_layer_entry(
            entry=entries[0],
            shared_enc=shared_enc,
            shared_field=shared_field,
            shared_axis=shared_axis,
            measure_axis=measure_axis,
            spec=spec,
            resolver=resolver,
        )

    # Multi-entry branch (KAN-112): vconcat/hconcat of layer + simple panels.
    # Transforms go per-panel (vconcat/hconcat children are independent unit specs).
    # compile_layer_entry already adds transforms at the layer-group level;
    # _build_simple_panel adds them to its own output.
    panels: list[dict[str, Any]] = []
    for entry in entries:
        if entry.layer:
            panels.append(
                compile_layer_entry(
                    entry=entry,
                    shared_enc=shared_enc,
                    shared_field=shared_field,
                    shared_axis=shared_axis,
                    measure_axis=measure_axis,
                    spec=spec,
                    resolver=resolver,
                )
            )
        else:
            panels.append(
                _build_simple_panel(
                    entry=entry,
                    shared_enc=shared_enc,
                    shared_field=shared_field,
                    shared_axis=shared_axis,
                    measure_axis=measure_axis,
                    spec=spec,
                    resolver=resolver,
                )
            )

    return {concat_key: panels}


def compile_layer_entry(
    entry: MeasureEntry,
    shared_enc: dict[str, Any],
    shared_field: str,
    shared_axis: str,
    measure_axis: str,
    spec: ChartSpec,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """
    Compile a single MeasureEntry with a `layer` list into a Vega-Lite layer spec.

    The entry's measure is the primary layer (gets tooltip + sort). Each item in
    entry.layer is a secondary layer (no tooltip, no sort). All layers share the
    same axis encoding (shared_enc) but bind their own measure to measure_axis.

    Produces:
        {
          "layer": [primary, *secondaries],
          "resolve": {"scale": {<measure_axis>: "independent"}},   # if entry.axis == "independent"
          "transform": [...]                                         # if spec.filters non-empty
        }

    Args:
        entry:        The MeasureEntry. Caller MUST ensure entry.layer is a non-empty list.
        shared_enc:   Pre-built encoding dict for the shared axis (output of
                      build_field_encoding). Title/format/grid auto-injection has
                      NOT been applied yet — this function applies it on per-layer copies.
        shared_field: Field name on the shared axis (e.g. "week").
        shared_axis:  "x" or "y" — which axis is shared across layers.
        measure_axis: opposite of shared_axis; the per-layer measure goes here.
        spec:         The full ChartSpec (used for top-level marks/color/detail/size,
                      tooltip, filters, sort).
        resolver:     Field type resolver from the model.

    Raises: ValueError if no mark can be resolved for the entry's primary measure.
    """
    # Step 1: Resolve primary mark (must succeed).
    primary_mark = _resolve_mark(
        layer_mark=None,
        entry_mark=entry.mark,
        top_level_mark=spec.marks,
        measure_name=entry.measure,
    )

    # Step 2: Build the primary layer (entry's own measure).
    primary_color = _resolve_property(None, entry.color, spec.color)
    primary_detail = _resolve_property(None, entry.detail, spec.detail)
    primary_size = _resolve_property(None, entry.size, spec.size)
    primary_opacity = entry.opacity  # opacity does NOT cascade

    primary = _build_layer_spec(
        measure=entry.measure,
        mark=primary_mark,
        color=primary_color,
        detail=primary_detail,
        size=primary_size,
        opacity=primary_opacity,
        shared_enc=shared_enc,
        shared_field=shared_field,
        shared_axis=shared_axis,
        measure_axis=measure_axis,
        spec=spec,
        resolver=resolver,
        is_primary=True,
    )

    # Step 3: Build each secondary layer.
    secondaries = []
    for layer in entry.layer:  # type: ignore[union-attr]
        layer_mark = _resolve_mark(
            layer_mark=layer.mark,
            entry_mark=entry.mark,
            top_level_mark=spec.marks,
            measure_name=layer.measure,
        )
        layer_color = _resolve_property(layer.color, entry.color, spec.color)
        layer_detail = _resolve_layer_detail(layer, entry, spec)
        layer_size = _resolve_property(layer.size, entry.size, spec.size)
        layer_opacity = layer.opacity

        secondary = _build_layer_spec(
            measure=layer.measure,
            mark=layer_mark,
            color=layer_color,
            detail=layer_detail,
            size=layer_size,
            opacity=layer_opacity,
            shared_enc=shared_enc,
            shared_field=shared_field,
            shared_axis=shared_axis,
            measure_axis=measure_axis,
            spec=spec,
            resolver=resolver,
            is_primary=False,
        )
        secondaries.append(secondary)

    # Step 4: Assemble.
    result: dict[str, Any] = {"layer": [primary, *secondaries]}

    # Step 5: Resolve only for explicit independent.
    if entry.axis == "independent":
        result["resolve"] = {"scale": {measure_axis: "independent"}}

    # Step 6: Transforms at the layer-group level.
    transforms = build_transforms(spec.filters, resolver)
    if transforms:
        result["transform"] = transforms

    return result


def _build_simple_panel(
    entry: MeasureEntry,
    shared_enc: dict[str, Any],
    shared_field: str,
    shared_axis: str,
    measure_axis: str,
    spec: ChartSpec,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """
    Build a single non-layered panel for use inside a multi-entry stacked layout
    where at least one sibling entry has layers.

    Mirrors the per-panel logic of stacked.py:_compile_concat but builds ONE
    panel at a time so it can be interleaved with compile_layer_entry panels.
    Does NOT add transforms — the caller hoists transforms to the concat level.
    """
    # Step 1: Resolve mark.
    mark = _resolve_mark(
        layer_mark=None,
        entry_mark=entry.mark,
        top_level_mark=spec.marks,
        measure_name=entry.measure,
    )

    # Step 2: Build encoding.
    encoding: dict[str, Any] = {}

    # 2a: Shared axis — copy and inject title/format/grid.
    shared_axis_enc = {**shared_enc}
    _auto_inject_from_model(shared_axis_enc, shared_field, resolver, None, channel=shared_axis)
    encoding[shared_axis] = shared_axis_enc

    # 2b: Measure axis.
    measure_enc = build_field_encoding(entry.measure, resolver)
    _auto_inject_from_model(measure_enc, entry.measure, resolver, None, channel=measure_axis)
    encoding[measure_axis] = measure_enc

    # Step 3: Color — entry overrides top-level.
    color = entry.color if entry.color is not None else spec.color
    if color is not None:
        encoding["color"] = build_color(color, resolver)

    # Step 4: Detail — entry overrides top-level.
    detail = entry.detail if entry.detail is not None else spec.detail
    if detail is not None:
        encoding["detail"] = build_detail(detail, resolver)

    # Step 5: Size — entry overrides top-level.
    size = entry.size if entry.size is not None else spec.size
    if size is not None:
        encoding["size"] = build_size(size, resolver)

    # Step 6: Tooltip.
    if spec.tooltip:
        encoding["tooltip"] = build_tooltip(spec.tooltip, resolver)

    # Step 7: Sort.
    apply_sort(encoding, spec.sort, resolver)

    # Step 8: Build mark (merge entry opacity if set).
    vl_mark = _apply_opacity_to_mark(build_mark(mark), entry.opacity)

    panel: dict[str, Any] = {"mark": vl_mark, "encoding": encoding}

    # Step 9: Transforms per-panel (matching stacked.py:_compile_concat behavior).
    transforms = build_transforms(spec.filters, resolver)
    if transforms:
        panel["transform"] = transforms

    return panel


def _build_layer_spec(
    measure: str,
    mark: MarkSpec,
    color: ColorSpec | None,
    detail: str | None,
    size: str | int | float | None,
    opacity: float | None,
    shared_enc: dict[str, Any],
    shared_field: str,
    shared_axis: str,
    measure_axis: str,
    spec: ChartSpec,
    resolver: FieldTypeResolver,
    is_primary: bool,
) -> dict[str, Any]:
    """
    Build one Vega-Lite child spec inside a layer group: {"mark": ..., "encoding": {...}}.

    Mark, color, detail, size are all already resolved by the caller (compile_layer_entry).
    is_primary controls whether tooltip and sort are applied (primary only).

    KAN-112 may reuse this for any layered child within a multi-entry vconcat.
    """
    # Step 1: Build mark; merge opacity if set.
    vl_mark = _apply_opacity_to_mark(build_mark(mark), opacity)

    # Step 2: Build encoding.
    encoding: dict[str, Any] = {}

    # 2a: Shared axis — copy and inject title/format/grid.
    shared_axis_enc = {**shared_enc}
    _auto_inject_from_model(shared_axis_enc, shared_field, resolver, None, channel=shared_axis)
    encoding[shared_axis] = shared_axis_enc

    # 2b: Measure axis.
    measure_enc = build_field_encoding(measure, resolver)
    _auto_inject_from_model(measure_enc, measure, resolver, None, channel=measure_axis)
    encoding[measure_axis] = measure_enc

    # Steps 3-5: Color, detail, size (all already resolved).
    if color is not None:
        encoding["color"] = build_color(color, resolver)
    if detail is not None:
        encoding["detail"] = build_detail(detail, resolver)
    if size is not None:
        encoding["size"] = build_size(size, resolver)

    # Step 6: Tooltip + sort — primary only.
    if is_primary:
        if spec.tooltip:
            encoding["tooltip"] = build_tooltip(spec.tooltip, resolver)
        apply_sort(encoding, spec.sort, resolver)
        # NOTE: do NOT call apply_default_sort_from_model — see plan's "Default sort from model".

    return {"mark": vl_mark, "encoding": encoding}


def _apply_opacity_to_mark(
    vl_mark: str | dict[str, Any],
    opacity: float | None,
) -> str | dict[str, Any]:
    """
    Merge opacity into a Vega-Lite mark value.

    None opacity        → return mark unchanged.
    String mark + opacity → promote to {"type": mark, "opacity": opacity}.
    Dict mark + opacity   → set "opacity" key only if not already present
                            (build_mark may have set it from MarkObject.opacity;
                            that mark-object opacity wins).
    """
    if opacity is None:
        return vl_mark
    if isinstance(vl_mark, str):
        return {"type": vl_mark, "opacity": opacity}
    if "opacity" not in vl_mark:
        vl_mark["opacity"] = opacity
    return vl_mark


def _resolve_property(
    layer_value: Any,
    entry_value: Any,
    top_level_value: Any,
) -> Any:
    """
    Generic 3-level cascade: layer > entry > top-level. Returns first non-None,
    or None if all None. Used for color and size.

    NOT used for mark (which raises) or detail (explicit-null semantics).
    NOT used for opacity (which doesn't cascade).
    """
    if layer_value is not None:
        return layer_value
    if entry_value is not None:
        return entry_value
    return top_level_value


def _resolve_mark(
    layer_mark: MarkSpec | None,
    entry_mark: MarkSpec | None,
    top_level_mark: MarkSpec | None,
    measure_name: str,
) -> MarkSpec:
    """
    Resolve mark via 3-level cascade. Mark MUST resolve.
    Raises ValueError("No mark defined for measure '<name>'") if all three are None.
    """
    if layer_mark is not None:
        return layer_mark
    if entry_mark is not None:
        return entry_mark
    if top_level_mark is not None:
        return top_level_mark
    raise ValueError(f"No mark defined for measure '{measure_name}'")


def _resolve_layer_detail(
    layer: LayerEntry,
    entry: MeasureEntry,
    spec: ChartSpec,
) -> str | None:
    """
    Resolve detail for a LAYER entry, with explicit-null suppression.

    Pydantic's `model_fields_set` distinguishes:
      - Field omitted from YAML → inherit from entry → spec
      - Field explicitly set to null → suppress (return None)

    Cascade:
      1. If layer wrote `detail: <anything>` (including null) → use that value.
      2. Else inherit entry.detail.
      3. Else inherit spec.detail.
    """
    if "detail" in layer.model_fields_set:
        return layer.detail
    if entry.detail is not None:
        return entry.detail
    return spec.detail
