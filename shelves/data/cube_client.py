"""
Cube.dev REST API Client

Classifies chart fields via ModelResolver, builds a Cube query, and fetches
rows with unprefixed keys.

Phase 3: replaces inline JSON data for charts backed by a semantic model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from shelves.data.fields import collect_chart_fields
from shelves.models.schema import CubeSource, DataModel
from shelves.schema.chart_schema import (
    ChartSpec,
    ShelfFilter,
)
from shelves.schema.field_types import FieldTypeResolver

# ─── Errors ──────────────────────────────────────────────────────────


class CubeError(Exception):
    """Base error for Cube.dev client operations."""


class CubeConfigError(CubeError):
    """Missing or invalid Cube configuration."""


class CubeQueryError(CubeError):
    """Cube API returned an error response."""


class CubeAuthError(CubeError):
    """Cube API returned 401 or 403."""


class CubeServerError(CubeError):
    """Cube API returned 5xx."""


class CubeTimeoutError(CubeError):
    """Cube request timed out."""


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


# ─── HTTP Transport ─────────────────────────────────────────────────


class HTTPTransport(Protocol):
    def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response: ...


class HttpxTransport:
    """Default transport using httpx.Client."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        with httpx.Client(timeout=self._timeout) as client:
            return client.post(url, json=json, headers=headers)


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
    fields = collect_chart_fields(chart_spec)

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
    transport: HTTPTransport | None = None,
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
        transport: HTTP transport. If None, uses HttpxTransport (default httpx).

    Returns:
        List of row dicts with field names matching the DSL (no cube prefix).

    Raises:
        CubeConfigError: If environment variables are not set.
        CubeAuthError: If Cube returns 401 or 403.
        CubeServerError: If Cube returns 5xx.
        CubeTimeoutError: If the request times out.
        CubeQueryError: If Cube returns any other non-200 status.
    """
    if config is None:
        config = CubeConfig.from_env()

    if transport is None:
        transport = HttpxTransport()

    assert isinstance(model.source, CubeSource), "resolve_data requires a CubeSource"
    cube_name = model.source.cube
    query = build_cube_query(cube_name, chart_spec, resolver)

    url = f"{config.api_url}/cubejs-api/v1/load"
    headers = {"Authorization": config.api_token}

    try:
        response = transport.post(url, json={"query": query}, headers=headers)
    except httpx.TimeoutException as e:
        raise CubeTimeoutError(f"Cube request timed out: {e}") from e

    if response.status_code != 200:
        body = response.text[:500]
        if response.status_code in (401, 403):
            raise CubeAuthError(f"Cube auth error (HTTP {response.status_code}): {body}")
        elif response.status_code >= 500:
            raise CubeServerError(f"Cube server error (HTTP {response.status_code}): {body}")
        else:
            raise CubeQueryError(f"Cube API error (HTTP {response.status_code}): {body}")

    raw_rows = response.json().get("data", [])
    return [_strip_prefix(row) for row in raw_rows]
