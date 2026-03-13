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

from src.schema.chart_schema import ShelfFilter


def build_transforms(filters: list[ShelfFilter] | None) -> list[dict[str, Any]]:
    """Convert DSL filters to Vega-Lite transform list."""

    if not filters:
        return []

    return [{"filter": _translate_filter(f)} for f in filters]


def _translate_filter(f: ShelfFilter) -> Any:
    """Convert a single DSL filter to a Vega-Lite filter predicate."""

    match f.operator:
        case "eq":
            return {"field": f.field, "equal": f.value}
        case "neq":
            return {"not": {"field": f.field, "equal": f.value}}
        case "gt":
            return {"field": f.field, "gt": f.value}
        case "lt":
            return {"field": f.field, "lt": f.value}
        case "gte":
            return {"field": f.field, "gte": f.value}
        case "lte":
            return {"field": f.field, "lte": f.value}
        case "in":
            return {"field": f.field, "oneOf": f.values}
        case "not_in":
            return {"not": {"field": f.field, "oneOf": f.values}}
        case "between":
            return {"field": f.field, "range": f.range}
        case _:
            raise ValueError(f'Unknown filter operator: "{f.operator}"')
