"""
Panel Encoding Builder

Shared panel encoding logic for stacked and layered panels. Builds the full
Vega-Lite encoding dict for a single non-layered panel in a multi-measure
stacked layout.
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import ChartSpec, MeasureEntry
from shelves.schema.field_types import FieldTypeResolver
from shelves.translator.encodings import (
    _auto_inject_from_model,
    build_color,
    build_detail,
    build_field_encoding,
    build_size,
    build_tooltip,
)
from shelves.translator.resolution import resolve_property
from shelves.translator.sort import apply_sort


def build_panel_encoding(
    entry: MeasureEntry,
    shared_enc: dict[str, Any],
    shared_field: str,
    shared_axis: str,
    measure_axis: str,
    spec: ChartSpec,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """
    Build the full Vega-Lite encoding dict for a single non-layered panel.

    Does NOT handle shared axis suppression, mark building, transforms,
    or opacity merging — the caller handles those.
    """
    encoding: dict[str, Any] = {}

    shared_axis_enc = {**shared_enc}
    _auto_inject_from_model(shared_axis_enc, shared_field, resolver, None, channel=shared_axis)
    encoding[shared_axis] = shared_axis_enc

    measure_enc = build_field_encoding(entry.measure, resolver)
    _auto_inject_from_model(measure_enc, entry.measure, resolver, None, channel=measure_axis)
    encoding[measure_axis] = measure_enc

    color = resolve_property(None, entry.color, spec.color)
    if color is not None:
        encoding["color"] = build_color(color, resolver)

    detail = resolve_property(None, entry.detail, spec.detail)
    if detail:
        encoding["detail"] = build_detail(detail, resolver)

    size = resolve_property(None, entry.size, spec.size)
    if size is not None:
        encoding["size"] = build_size(size, resolver)

    if spec.tooltip:
        encoding["tooltip"] = build_tooltip(spec.tooltip, resolver)

    apply_sort(encoding, spec.sort, resolver)

    return encoding
