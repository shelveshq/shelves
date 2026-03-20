"""
Stacked Panels Compiler (Phase 1)

Handles multi-measure shelves: rows or cols is a list of MeasureEntry.

Compilation strategy:
  - All entries have same mark (or inherit top-level) → Vega-Lite `repeat`
  - Entries have different marks → Vega-Lite `vconcat` (rows) or `hconcat` (cols)
  - Entry has `layer` → delegate to layers.py (Phase 1a)

The shared axis (the single-field shelf) is duplicated into each panel.
"""

from __future__ import annotations

from typing import Any

from src.schema.chart_schema import ChartSpec, MeasureEntry, MarkSpec
from src.schema.field_types import FieldTypeResolver
from src.translator.marks import build_mark
from src.translator.encodings import build_color, build_tooltip, build_field_encoding
from src.translator.filters import build_transforms
from src.translator.sort import apply_sort

VegaLiteSpec = dict[str, Any]


def compile_stacked(spec: ChartSpec, resolver: FieldTypeResolver) -> VegaLiteSpec:
    """Compile a multi-measure stacked spec."""

    rows_is_multi = isinstance(spec.rows, list)
    entries: list[MeasureEntry] = spec.rows if rows_is_multi else spec.cols  # type: ignore
    shared_field: str = spec.cols if rows_is_multi else spec.rows  # type: ignore
    shared_axis = "x" if rows_is_multi else "y"
    measure_axis = "y" if rows_is_multi else "x"
    concat_key = "vconcat" if rows_is_multi else "hconcat"

    # Check if any entry has layers (Phase 1a)
    has_layers = any(e.layer for e in entries)
    if has_layers:
        # Phase 1a: delegate to layers-aware compilation
        from src.translator.patterns.layers import compile_stacked_with_layers

        return compile_stacked_with_layers(
            spec, entries, shared_field, shared_axis, measure_axis, concat_key, resolver
        )

    # Resolve the shared axis encoding
    shared_enc = build_field_encoding(shared_field, resolver)

    # Build transforms (filters apply to all panels)
    transforms = build_transforms(spec.filters, resolver)

    # Try repeat path: all entries use the same effective mark
    effective_marks = [_resolve_mark(e, spec.marks) for e in entries]
    all_same_mark = len(set(str(m) for m in effective_marks)) == 1

    if all_same_mark and not any(e.color or e.detail or e.size for e in entries):
        # Clean repeat: all panels identical except the measure field
        return _compile_repeat(
            entries,
            effective_marks[0],
            shared_enc,
            shared_axis,
            measure_axis,
            spec,
            resolver,
            transforms,
        )

    # vconcat/hconcat: each panel is its own spec
    return _compile_concat(
        entries,
        effective_marks,
        shared_enc,
        shared_axis,
        measure_axis,
        concat_key,
        spec,
        resolver,
        transforms,
    )


def _resolve_mark(entry: MeasureEntry, default_mark: MarkSpec | None) -> MarkSpec:
    """Get the effective mark for an entry, falling back to the top-level default."""
    if entry.mark is not None:
        return entry.mark
    if default_mark is not None:
        return default_mark
    raise ValueError(f'Measure entry "{entry.measure}" has no mark and no top-level marks default.')


def _compile_repeat(
    entries: list[MeasureEntry],
    mark: MarkSpec,
    shared_enc: dict,
    shared_axis: str,
    measure_axis: str,
    spec: ChartSpec,
    resolver: FieldTypeResolver,
    transforms: list,
) -> VegaLiteSpec:
    """Compile to Vega-Lite repeat spec (all panels share the same mark)."""

    measures = [e.measure for e in entries]
    repeat_channel = "row" if measure_axis == "y" else "column"

    inner_encoding: dict[str, Any] = {
        shared_axis: shared_enc,
        measure_axis: {
            "field": {"repeat": repeat_channel},
            "type": "quantitative",
        },
    }

    # Apply shared color/tooltip from top-level
    if spec.color is not None:
        inner_encoding["color"] = build_color(spec.color, resolver)
    if spec.tooltip:
        inner_encoding["tooltip"] = build_tooltip(spec.tooltip, resolver)

    inner_spec: VegaLiteSpec = {
        "mark": build_mark(mark),
        "encoding": inner_encoding,
    }

    if transforms:
        inner_spec["transform"] = transforms

    apply_sort(inner_encoding, spec.sort, resolver)

    return {
        "repeat": {repeat_channel: measures},
        "spec": inner_spec,
    }


def _compile_concat(
    entries: list[MeasureEntry],
    effective_marks: list[MarkSpec],
    shared_enc: dict,
    shared_axis: str,
    measure_axis: str,
    concat_key: str,
    spec: ChartSpec,
    resolver: FieldTypeResolver,
    transforms: list,
) -> VegaLiteSpec:
    """Compile to Vega-Lite vconcat/hconcat (panels may differ in mark/color)."""

    panels = []
    for entry, mark in zip(entries, effective_marks):
        panel_encoding: dict[str, Any] = {
            shared_axis: {**shared_enc},
            measure_axis: {
                "field": entry.measure,
                "type": "quantitative",
            },
        }

        # Color: entry-level overrides top-level
        color = entry.color if entry.color is not None else spec.color
        if color is not None:
            panel_encoding["color"] = build_color(color, resolver)

        # Detail: entry-level overrides top-level
        detail = entry.detail if entry.detail is not None else spec.detail
        if detail:
            panel_encoding["detail"] = {
                "field": detail,
                "type": resolver.resolve(detail),
            }

        # Size: entry-level overrides top-level
        size = entry.size if entry.size is not None else spec.size
        if size is not None:
            if isinstance(size, (int, float)):
                panel_encoding["size"] = {"value": size}
            else:
                panel_encoding["size"] = {"field": size, "type": resolver.resolve(size)}

        # Tooltip: shared from top-level
        if spec.tooltip:
            panel_encoding["tooltip"] = build_tooltip(spec.tooltip, resolver)

        panel: VegaLiteSpec = {
            "mark": build_mark(mark),
            "encoding": panel_encoding,
        }

        if transforms:
            panel["transform"] = transforms

        apply_sort(panel_encoding, spec.sort, resolver)
        panels.append(panel)

    return {concat_key: panels}
