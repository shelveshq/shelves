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
  contains → expression: indexof(lower(datum[...]), lower(...)) >= 0
"""

from __future__ import annotations

import warnings
from typing import Any

from shelves.schema.chart_schema import ShelfFilter
from shelves.schema.field_types import FieldTypeResolver

_COMPARISON_OPS = {"gt", "lt", "gte", "lte", "between"}
_STRING_OPS = {"contains"}


def build_transforms(
    filters: list[ShelfFilter] | None,
    resolver: FieldTypeResolver | None = None,
) -> list[dict[str, Any]]:
    """Convert DSL filters to Vega-Lite transform list."""

    if not filters:
        return []

    transforms = []
    for f in filters:
        _warn_operator_field_type_mismatch(f, resolver)
        transforms.append({"filter": _translate_filter(f, resolver)})
    return transforms


def _warn_operator_field_type_mismatch(
    f: ShelfFilter,
    resolver: FieldTypeResolver | None,
) -> None:
    if resolver is None:
        return
    try:
        vl_type = resolver.resolve(f.field)
    except (ValueError, KeyError):
        return

    if f.operator in _STRING_OPS and vl_type in ("quantitative", "temporal"):
        warnings.warn(
            f"Filter operator '{f.operator}' is a string operation but field "
            f"'{f.field}' is {vl_type}. This may produce unexpected results.",
            UserWarning,
            stacklevel=4,
        )
    elif f.operator in _COMPARISON_OPS and vl_type in ("nominal", "ordinal"):
        warnings.warn(
            f"Filter operator '{f.operator}' is a numeric/temporal operation but "
            f"field '{f.field}' is {vl_type}. This may produce unexpected results.",
            UserWarning,
            stacklevel=4,
        )


def _translate_filter(
    f: ShelfFilter, resolver: FieldTypeResolver | None = None
) -> dict[str, Any] | str:
    """Convert a single DSL filter to a Vega-Lite filter predicate."""

    field = resolver.resolve_base_field(f.field) if resolver else f.field
    if field is None:
        raise ValueError(f"Cannot resolve filter field {f.field!r}")

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
        case "contains":
            escaped = str(f.value).replace("\\", "\\\\").replace("'", "\\'")
            return f"indexof(lower(datum['{field}']), lower('{escaped}')) >= 0"
