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

from src.schema.chart_schema import FieldSort, AxisSort
from src.schema.field_types import FieldTypeResolver

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
