"""
Filter Translator

Converts DSL filters list into Vega-Lite transform entries.

Each DSL filter → one Vega-Lite filter transform.
Multiple filters are AND-ed (separate transform entries).

Operator mapping:
  eq      → {"field": "x", "equal": value}
  neq     → {"not": {"field": "x", "equal": value}}
  gt/lt/gte/lte → {"field": "x", "gt": value} etc.
  in      → {"field": "x", "oneOf": [...]}
  not_in  → {"not": {"field": "x", "oneOf": [...]}}
  between → {"field": "x", "range": [min, max]}
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import ShelfFilter
from shelves.schema.field_types import FieldTypeResolver


def build_transforms(
    filters: list[ShelfFilter] | None,
    resolver: FieldTypeResolver | None = None,
) -> list[dict[str, Any]]:
    """Convert DSL filters to Vega-Lite transform list."""

    if not filters:
        return []

    return [{"filter": _translate_filter(f, resolver)} for f in filters]


def _translate_filter(f: ShelfFilter, resolver: FieldTypeResolver | None = None) -> Any:
    """Convert a single DSL filter to a Vega-Lite filter predicate."""

    field = resolver.resolve_base_field(f.field) if resolver else f.field

    match f.operator:
        case "eq":
            return {"field": field, "equal": f.value}
        case "neq":
            return {"not": {"field": field, "equal": f.value}}
        case "gt":
            return {"field": field, "gt": f.value}
        case "lt":
            return {"field": field, "lt": f.value}
        case "gte":
            return {"field": field, "gte": f.value}
        case "lte":
            return {"field": field, "lte": f.value}
        case "in":
            return {"field": field, "oneOf": f.values}
        case "not_in":
            return {"not": {"field": field, "oneOf": f.values}}
        case "between":
            return {"field": field, "range": f.range}
        case _:
            raise ValueError(f'Unknown filter operator: "{f.operator}"')
