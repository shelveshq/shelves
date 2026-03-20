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
from pathlib import Path

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
    models_dir: str | Path | None = None,
) -> dict:
    """
    Attach data to a Vega-Lite spec, using inline rows or Cube.dev.

    If rows are provided, uses them directly (inline mode).
    Otherwise, loads the model and fetches from its configured source.

    Args:
        spec: Compiled Vega-Lite spec (no data yet).
        chart_spec: The parsed ChartSpec (needed for field extraction + filters).
        rows: Pre-fetched rows. If None, queries the model's data source.
        models_dir: Optional path to models directory. Defaults to
                    <project_root>/models/.

    Returns:
        Vega-Lite spec with data attached.

    Raises:
        CubeConfigError: If Cube env vars are missing and no rows provided.
        CubeQueryError: If the Cube API returns an error.
        ValueError: If the model has no configured data source.
    """
    if rows is not None:
        return bind_data(spec, rows)

    from src.models.loader import load_model
    from src.models.resolver import ModelResolver

    model = load_model(chart_spec.data, models_dir=models_dir)
    resolver = ModelResolver(model)

    if model.source and model.source.type == "cube":
        from src.data.cube_client import fetch_from_cube_model

        fetched = fetch_from_cube_model(model, chart_spec, resolver)
        return bind_data(spec, fetched)

    raise ValueError(
        f"No data provided for model '{chart_spec.data}'. "
        "Pass --data or configure a Cube source in the model."
    )
