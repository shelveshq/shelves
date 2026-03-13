"""
Facet Translator

If the DSL spec includes a facet property, wraps the inner spec
(mark + encoding + transforms) inside a Vega-Lite facet operator.

Four modes:
  1. Row facet:    facet.row → {facet: {row: {...}}, spec: inner}
  2. Column facet: facet.column → {facet: {column: {...}}, spec: inner}
  3. Grid facet:   facet.row + facet.column → both channels
  4. Wrap facet:   facet.field + facet.columns → {facet: {...}, columns: N, spec: inner}

PHASE 1b NOTE:
  This function is agnostic about what's inside inner_spec.
  Single mark (Phase 1) or layer list (Phase 1b) — wrapping is identical.
"""

from __future__ import annotations

from typing import Any, Union

from src.schema.chart_schema import RowColumnFacet, WrapFacet

FacetSpec = Union[WrapFacet, RowColumnFacet, None]
VegaLiteSpec = dict[str, Any]


def apply_facet(inner_spec: VegaLiteSpec, facet: FacetSpec) -> VegaLiteSpec:
    """Wrap inner spec in a facet operator, or return as-is if no facet."""

    if facet is None:
        return {**inner_spec}

    # Wrapping facet: field + columns
    if isinstance(facet, WrapFacet):
        facet_def: dict[str, Any] = {"field": facet.field, "type": "nominal"}
        if facet.sort:
            facet_def["sort"] = {"order": facet.sort}

        result: VegaLiteSpec = {
            "facet": facet_def,
            "columns": facet.columns,
            "spec": inner_spec,
        }
        if facet.resolve:
            result["resolve"] = facet.resolve.model_dump(exclude_none=True)
        return result

    # Row/column/grid facet
    if isinstance(facet, RowColumnFacet):
        facet_channels: dict[str, Any] = {}
        if facet.row:
            facet_channels["row"] = {"field": facet.row, "type": "nominal"}
        if facet.column:
            facet_channels["column"] = {"field": facet.column, "type": "nominal"}

        result = {
            "facet": facet_channels,
            "spec": inner_spec,
        }
        if facet.resolve:
            result["resolve"] = facet.resolve.model_dump(exclude_none=True)
        return result

    # Fallback — shouldn't reach here if schema validation passed
    return {**inner_spec}
