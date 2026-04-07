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

Sort targets the x encoding by default. Set channel: y to sort the y axis.
"""

from __future__ import annotations

from typing import Any, Union

from shelves.schema.chart_schema import FieldSort, AxisSort
from shelves.schema.field_types import FieldTypeResolver

SortSpec = Union[FieldSort, AxisSort, None]


def apply_sort(
    encoding: dict[str, Any],
    sort: SortSpec,
    resolver: FieldTypeResolver | None = None,
) -> None:
    """Mutate encoding dict to apply sort on the target channel."""

    if sort is None:
        return

    target = encoding.get(sort.channel)
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

    x_enc = encoding.get("x")
    y_enc = encoding.get("y")

    if x_enc is None:
        return

    # Already has a sort from somewhere — don't override
    if "sort" in x_enc:
        return

    x_field = x_enc.get("field")
    if x_field is None:
        return

    # Check for sortOrder on the x-axis field (explicit category order)
    sort_order = resolver.resolve_sort_order(x_field)
    if sort_order is not None:
        x_enc["sort"] = sort_order
        return

    # Check for defaultSort on the y-axis measure
    if y_enc is not None:
        y_field = y_enc.get("field")
        if y_field is not None and isinstance(y_field, str):
            default_sort = resolver.resolve_default_sort(y_field)
            if default_sort is not None:
                x_enc["sort"] = {"encoding": "y", "order": default_sort}
