"""
Sort Translator

Applies DSL sort to the appropriate Vega-Lite encoding channel.

Three modes:
  1. Field sort: {field: revenue, order: descending}
     → encoding.x.sort = {field: revenue, order: descending}
  2. Axis sort: {axis: y, order: descending}
     → encoding.x.sort = {encoding: y, order: descending}
  3. Custom order: {field: country, order: [US, UK, FR]}
     → encoding.x.sort = [US, UK, FR]

When channel is omitted, auto-detects the dimension axis (nominal/ordinal) as the
sort target. Falls back to "x" if both axes are the same type.
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import AxisSort, FieldSort
from shelves.schema.field_types import FieldTypeResolver

SortSpec = FieldSort | AxisSort | None

_DIMENSION_TYPES = {"nominal", "ordinal"}


def _detect_sort_channel(encoding: dict[str, Any]) -> str:
    """Pick the dimension axis as the sort target."""
    x_type = encoding.get("x", {}).get("type")
    y_type = encoding.get("y", {}).get("type")
    if y_type in _DIMENSION_TYPES and x_type not in _DIMENSION_TYPES:
        return "y"
    return "x"


def apply_sort(
    encoding: dict[str, Any],
    sort: SortSpec,
    resolver: FieldTypeResolver | None = None,
) -> None:
    """Mutate encoding dict to apply sort on the target channel."""

    if sort is None:
        return

    channel = sort.channel or _detect_sort_channel(encoding)
    target = encoding.get(channel)
    if target is None:
        return

    if isinstance(sort, AxisSort):
        target["sort"] = {"encoding": sort.axis, "order": sort.order}
    elif isinstance(sort, FieldSort):
        if isinstance(sort.order, list):
            target["sort"] = sort.order
        else:
            field = resolver.resolve_base_field(sort.field) if resolver else sort.field
            target["sort"] = {"field": field, "order": sort.order}


def apply_default_sort_from_model(
    encoding: dict[str, Any],
    spec_sort: SortSpec,
    resolver: FieldTypeResolver,
) -> None:
    """
    Apply default sort from the data model when no explicit sort exists on the chart.

    Two modes:
      1. sortOrder on the x-axis dimension → encoding.x.sort = ["US", "UK", ...]
      2. defaultSort on the y-axis measure → encoding.x.sort = {encoding: y, order: "descending"}

    Does nothing if:
      - spec_sort is not None (explicit chart sort wins)
      - encoding has no "x" or "y" channels
      - resolver doesn't provide sort info

    Priority: explicit chart sort > sortOrder > defaultSort
    """
    # Skip if chart already has an explicit sort
    if spec_sort is not None:
        return

    dim_ch = _detect_sort_channel(encoding)
    measure_ch = "y" if dim_ch == "x" else "x"

    dim_enc = encoding.get(dim_ch)
    measure_enc = encoding.get(measure_ch)

    if dim_enc is None:
        return

    # Already has a sort from somewhere — don't override
    if "sort" in dim_enc:
        return

    dim_field = dim_enc.get("field")
    if dim_field is None:
        return

    # Check for sortOrder on the dimension field (explicit category order)
    sort_order = resolver.resolve_sort_order(dim_field)
    if sort_order is not None:
        dim_enc["sort"] = sort_order
        return

    # Check for defaultSort on the measure
    if measure_enc is not None:
        measure_field = measure_enc.get("field")
        if measure_field is not None and isinstance(measure_field, str):
            default_sort = resolver.resolve_default_sort(measure_field)
            if default_sort is not None:
                dim_enc["sort"] = {"encoding": measure_ch, "order": default_sort}
