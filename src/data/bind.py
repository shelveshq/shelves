"""
Data Binder

Attaches data to a compiled Vega-Lite spec.

Two modes:
  1. Inline: bind_data(spec, rows) — attaches pre-fetched rows directly.
  2. Semantic layer: resolve_data(spec, chart_spec) — fetches from Cube.dev,
     or falls back to inline rows if provided.

For faceted specs, data goes on the TOP-LEVEL spec.
Vega-Lite propagates data from parent to faceted children.
"""

from __future__ import annotations

import copy

from src.schema.chart_schema import ChartSpec


def bind_data(spec: dict, values: list[dict]) -> dict:
    """Attach inline data values to a Vega-Lite spec."""
    result = copy.deepcopy(spec)
    result["data"] = {"values": values}
    return result


def resolve_data(
    spec: dict,
    chart_spec: ChartSpec,
    rows: list[dict] | None = None,
) -> dict:
    """
    Attach data to a Vega-Lite spec, using inline rows or Cube.dev.

    If rows are provided, uses them directly (inline mode).
    Otherwise, fetches from Cube.dev using the chart's data block.

    Args:
        spec: Compiled Vega-Lite spec (no data yet).
        chart_spec: The parsed ChartSpec (needed for data block + filters).
        rows: Pre-fetched rows. If None, queries Cube.dev.

    Returns:
        Vega-Lite spec with data attached.

    Raises:
        CubeConfigError: If Cube env vars are missing and no rows provided.
        CubeQueryError: If the Cube API returns an error.
    """
    if rows is not None:
        return bind_data(spec, rows)

    from src.data.cube_client import fetch_from_cube

    fetched = fetch_from_cube(chart_spec.data, chart_spec.filters)
    return bind_data(spec, fetched)
