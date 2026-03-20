"""
Cube.dev REST API Client

Translates the DSL data block into a Cube query, executes it via HTTP,
and returns tabular rows with unprefixed field names.

Phase 3: replaces inline JSON data for charts backed by a semantic model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from src.schema.chart_schema import DataSource, ShelfFilter


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
    data: DataSource,
    filters: list[ShelfFilter] | None = None,
) -> dict[str, Any]:
    """
    Build a Cube REST API query dict from the DSL data block.

    Prefixes all field names with the model name (e.g. "orders.net_sales")
    since the Cube API requires fully-qualified member names.
    """
    model = data.model

    # Measures — always prefixed
    measures = [f"{model}.{m}" for m in data.measures]

    # Dimensions — prefixed, but exclude time_grain field (goes to timeDimensions)
    time_field = data.time_grain.field if data.time_grain else None
    dimensions = [f"{model}.{d}" for d in data.dimensions if d != time_field]

    query: dict[str, Any] = {
        "measures": measures,
        "dimensions": dimensions,
    }

    # Time dimensions
    if data.time_grain:
        query["timeDimensions"] = [
            {
                "dimension": f"{model}.{data.time_grain.field}",
                "granularity": data.time_grain.grain,
            }
        ]

    # Filters
    if filters:
        cube_filters = _translate_filters(filters, model)
        if cube_filters:
            query["filters"] = cube_filters

    return query


def _translate_filters(
    filters: list[ShelfFilter],
    model: str,
) -> list[dict[str, Any]]:
    """Convert DSL ShelfFilter list to Cube filter format."""
    result = []

    for f in filters:
        member = f"{model}.{f.field}"

        if f.operator == "between":
            # Cube has no generic 'between' — emit gte + lte pair
            result.append({"member": member, "operator": "gte", "values": [str(f.range[0])]})
            result.append({"member": member, "operator": "lte", "values": [str(f.range[1])]})
        elif f.operator in ("in", "not_in"):
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
    "orders.order_date.month" → "order_date.month" (split on first dot only... but
    actually Cube uses the format "cube.field" for dimensions and "cube.field.granularity"
    for time dimensions — we want to strip just the cube prefix).
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


def fetch_from_cube(
    data: DataSource,
    filters: list[ShelfFilter] | None = None,
    config: CubeConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch data from a Cube.dev instance.

    Builds a query from the DSL data block, executes it against the Cube
    REST API, and returns rows with unprefixed field names ready for
    Vega-Lite data binding.

    Args:
        data: The chart's DataSource (model, measures, dimensions, time_grain).
        filters: Optional DSL filters to push down to Cube.
        config: Cube connection config. If None, reads from environment.

    Returns:
        List of row dicts with field names matching the DSL (no cube prefix).

    Raises:
        CubeConfigError: If environment variables are not set.
        CubeQueryError: If the Cube API returns an error.
    """
    if config is None:
        config = CubeConfig.from_env()

    query = build_cube_query(data, filters)

    url = f"{config.api_url}/cubejs-api/v1/load"
    headers = {"Authorization": config.api_token}

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json={"query": query}, headers=headers)

    if response.status_code != 200:
        raise CubeQueryError(f"Cube API error (HTTP {response.status_code}): {response.text}")

    body = response.json()
    raw_rows = body.get("data", [])

    return [_strip_prefix(row) for row in raw_rows]
