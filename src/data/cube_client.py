"""
Cube.dev REST API Client

Extracts the fields a chart actually uses from the ChartSpec, classifies them
via ModelResolver, builds a Cube query, and fetches rows with unprefixed keys.

Phase 3: replaces inline JSON data for charts backed by a semantic model.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from typing import Any

import httpx

from src.schema.chart_schema import (
    ChartSpec,
    ColorFieldMapping,
    FieldSort,
    HEX_COLOR_RE,
    MeasureEntry,
    RowColumnFacet,
    ShelfFilter,
    WrapFacet,
)
from src.models.schema import CubeSource, DataModel
from src.schema.field_types import FieldTypeResolver


# ─── Errors ──────────────────────────────────────────────────────────


class CubeError(Exception):
    """Base error for Cube.dev client operations."""


class CubeConfigError(CubeError):
    """Missing or invalid Cube configuration."""


class CubeQueryError(CubeError):
    """Cube API returned an error response."""


# ─── Config ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CubeConfig:
    """Connection details for a Cube.dev instance."""

    api_url: str
    api_token: str

    @classmethod
    def from_env(cls) -> CubeConfig:
        """Read CUBE_API_URL and CUBE_API_TOKEN from environment."""
        api_url = os.environ.get("CUBE_API_URL")
        api_token = os.environ.get("CUBE_API_TOKEN")

        if not api_url:
            raise CubeConfigError(
                "CUBE_API_URL environment variable is not set. "
                "Set it to your Cube instance URL (e.g. http://localhost:4000)."
            )
        if not api_token:
            raise CubeConfigError(
                "CUBE_API_TOKEN environment variable is not set. Set it to your Cube API token."
            )

        # Strip trailing slash for consistent URL joining
        return cls(api_url=api_url.rstrip("/"), api_token=api_token)


# ─── Field Extraction ────────────────────────────────────────────────


def _collect_chart_fields(spec: ChartSpec) -> set[str]:
    """
    Extract the set of field names a chart actually references.

    Walks ALL field-bearing properties of ChartSpec:
      - rows, cols (string or MeasureEntry list — including layer entries)
      - color (string field or ColorFieldMapping)
      - detail
      - size (when it's a string field name, not a numeric literal)
      - tooltip (list of strings or TooltipField objects)
      - facet (RowColumnFacet.row, RowColumnFacet.column, WrapFacet.field)
      - sort (FieldSort.field — but NOT AxisSort, which references an axis not a field)
      - filters (ShelfFilter.field)
      - kpi (KPIConfig.measure, KPIComparison.measure)

    Tooltip disaggregation warning:
      Tooltip fields not already referenced by other chart properties are still
      collected (the user asked for them), but a warnings.warn() is emitted for
      each one explaining that including it will disaggregate the data — i.e., it
      behaves as if the field were added to 'detail'.

    Returns the set of field names to send to Cube.
    """
    fields: set[str] = set()

    def _add_shelf(shelf: str | list[MeasureEntry] | None) -> None:
        if shelf is None:
            return
        if isinstance(shelf, str):
            fields.add(shelf)
        else:
            for entry in shelf:
                fields.add(entry.measure)
                if (
                    entry.color
                    and isinstance(entry.color, str)
                    and not HEX_COLOR_RE.match(entry.color)
                ):
                    fields.add(entry.color)
                elif isinstance(entry.color, ColorFieldMapping):
                    fields.add(entry.color.field)
                if entry.detail:
                    fields.add(entry.detail)
                # entry-level size (string = field name; int/float = static)
                if isinstance(entry.size, str):
                    fields.add(entry.size)
                # layer entries
                if entry.layer:
                    for layer in entry.layer:
                        fields.add(layer.measure)
                        if (
                            layer.color
                            and isinstance(layer.color, str)
                            and not HEX_COLOR_RE.match(layer.color)
                        ):
                            fields.add(layer.color)
                        elif isinstance(layer.color, ColorFieldMapping):
                            fields.add(layer.color.field)
                        if layer.detail:
                            fields.add(layer.detail)
                        if isinstance(layer.size, str):
                            fields.add(layer.size)

    _add_shelf(spec.rows)
    _add_shelf(spec.cols)

    if spec.color:
        if isinstance(spec.color, str) and not HEX_COLOR_RE.match(spec.color):
            fields.add(spec.color)
        elif isinstance(spec.color, ColorFieldMapping):
            fields.add(spec.color.field)

    if spec.detail:
        fields.add(spec.detail)

    # top-level size
    if isinstance(spec.size, str):
        fields.add(spec.size)

    # facet
    if spec.facet:
        if isinstance(spec.facet, WrapFacet):
            fields.add(spec.facet.field)
        elif isinstance(spec.facet, RowColumnFacet):
            if spec.facet.row:
                fields.add(spec.facet.row)
            if spec.facet.column:
                fields.add(spec.facet.column)

    # sort
    if spec.sort and isinstance(spec.sort, FieldSort):
        fields.add(spec.sort.field)

    if spec.filters:
        for f in spec.filters:
            fields.add(f.field)

    # kpi
    if spec.kpi:
        fields.add(spec.kpi.measure)
        if spec.kpi.comparison:
            fields.add(spec.kpi.comparison.measure)

    # tooltip (two-pass — warn for fields not already referenced)
    # Snapshot the fields collected so far (everything EXCEPT tooltip).
    # Then collect tooltip fields. Any tooltip field NOT in the snapshot
    # is "tooltip-only" and will disaggregate the Cube query.
    if spec.tooltip:
        pre_tooltip_fields = set(fields)
        for t in spec.tooltip:
            field_name = t if isinstance(t, str) else t.field
            if field_name not in pre_tooltip_fields:
                warnings.warn(
                    f"Tooltip field '{field_name}' is not referenced by any other "
                    f"chart property (rows, cols, color, detail, facet, etc.). "
                    f"Including it in the Cube query will disaggregate the data "
                    f"— it behaves as if '{field_name}' were added to 'detail'.",
                    stacklevel=2,
                )
            fields.add(field_name)

    return fields


# ─── Query Builder ───────────────────────────────────────────────────

# DSL filter operator → Cube filter operator
_FILTER_OP_MAP = {
    "eq": "equals",
    "neq": "notEquals",
    "in": "equals",
    "not_in": "notEquals",
    "gt": "gt",
    "lt": "lt",
    "gte": "gte",
    "lte": "lte",
}


def build_cube_query(
    cube_name: str,
    chart_spec: ChartSpec,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """
    Build a Cube REST API query dict from chart fields.

    Extracts the fields the chart uses, classifies each via the resolver
    (measure → measures, temporal dim → timeDimensions, other → dimensions),
    and prefixes with the cube name for the Cube API.
    """
    fields = _collect_chart_fields(chart_spec)

    measures: list[str] = []
    dimensions: list[str] = []
    time_dimensions: list[dict[str, str]] = []

    for field in sorted(fields):  # sorted for deterministic output
        base_field = resolver.resolve_base_field(field)
        if resolver.is_measure(field):
            measures.append(f"{cube_name}.{base_field}")
        elif (grain := resolver.resolve_grain(field)) is not None:
            time_dimensions.append(
                {
                    "dimension": f"{cube_name}.{base_field}",
                    "granularity": grain,
                }
            )
        else:
            dimensions.append(f"{cube_name}.{base_field}")

    query: dict[str, Any] = {
        "measures": measures,
        "dimensions": dimensions,
    }

    if time_dimensions:
        query["timeDimensions"] = time_dimensions

    # Filters
    if chart_spec.filters:
        cube_filters = _translate_filters(chart_spec.filters, cube_name, resolver)
        if cube_filters:
            query["filters"] = cube_filters

    return query


def _translate_filters(
    filters: list[ShelfFilter],
    cube_name: str,
    resolver: FieldTypeResolver,
) -> list[dict[str, Any]]:
    """Convert DSL ShelfFilter list to Cube filter format."""
    result = []

    for f in filters:
        member = f"{cube_name}.{resolver.resolve_base_field(f.field)}"

        if f.operator == "between":
            # Cube has no generic 'between' — emit gte + lte pair
            assert f.range is not None, "ShelfFilter with operator='between' must have range set"
            result.append({"member": member, "operator": "gte", "values": [str(f.range[0])]})
            result.append({"member": member, "operator": "lte", "values": [str(f.range[1])]})
        elif f.operator in ("in", "not_in"):
            assert f.values is not None, (
                "ShelfFilter with operator='in'/'not_in' must have values set"
            )
            result.append(
                {
                    "member": member,
                    "operator": _FILTER_OP_MAP[f.operator],
                    "values": [str(v) for v in f.values],
                }
            )
        else:
            result.append(
                {
                    "member": member,
                    "operator": _FILTER_OP_MAP[f.operator],
                    "values": [str(f.value)],
                }
            )

    return result


# ─── Response Transformer ────────────────────────────────────────────


def _strip_prefix(row: dict[str, Any]) -> dict[str, Any]:
    """
    Strip cube name prefix from Cube response keys.

    "orders.net_sales" → "net_sales"
    "orders.order_date.month" → "order_date.month"
    """
    result = {}
    for key, value in row.items():
        # Split on first dot to remove cube name prefix
        if "." in key:
            _, unprefixed = key.split(".", 1)
            result[unprefixed] = value
        else:
            result[key] = value
    return result


# ─── Public API ──────────────────────────────────────────────────────


def fetch_from_cube_model(
    model: DataModel,
    chart_spec: ChartSpec,
    resolver: FieldTypeResolver,
    config: CubeConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch data from a Cube.dev instance using a DataModel.

    Extracts fields from the chart spec, classifies them via the resolver,
    builds a Cube query, and returns rows with unprefixed field names.

    Args:
        model: The loaded DataModel (must have a CubeSource).
        chart_spec: The parsed ChartSpec (for field extraction + filters).
        resolver: ModelResolver for classifying fields.
        config: Cube connection config. If None, reads from environment.

    Returns:
        List of row dicts with field names matching the DSL (no cube prefix).

    Raises:
        CubeConfigError: If environment variables are not set.
        CubeQueryError: If the Cube API returns an error.
    """
    if config is None:
        config = CubeConfig.from_env()

    assert isinstance(model.source, CubeSource), "resolve_data requires a CubeSource"
    cube_name = model.source.cube
    query = build_cube_query(cube_name, chart_spec, resolver)

    url = f"{config.api_url}/cubejs-api/v1/load"
    headers = {"Authorization": config.api_token}

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json={"query": query}, headers=headers)

    if response.status_code != 200:
        raise CubeQueryError(f"Cube API error (HTTP {response.status_code}): {response.text}")

    body = response.json()
    raw_rows = body.get("data", [])

    return [_strip_prefix(row) for row in raw_rows]
