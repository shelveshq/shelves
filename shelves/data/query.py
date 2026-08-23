"""
Semantic-layer query (SHE-56).

`run_model_query` fetches aggregated rows for an ad-hoc measure/dimension
selection through the same adapter path a chart uses — no raw SQL, no new query
logic. It builds a synthetic ``ChartSpec`` (measures on ``rows``, the first
dimension on ``cols``, the rest on ``tooltip``) and routes it through the
adapter registry, so DuckDB and Cube group and aggregate exactly as they do for
a real chart. Backs the MCP `query_model` tool.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from shelves.data.errors import NoDataSourceError
from shelves.models.loader import load_model
from shelves.models.resolver import ModelResolver
from shelves.schema.chart_schema import ChartSpec, ShelfFilter


def run_model_query(
    model_name: str,
    measures: list[str],
    dimensions: list[str] | None = None,
    filters: list[ShelfFilter] | None = None,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Aggregated rows for ``measures`` grouped by ``dimensions``.

    Routes through the source adapter (file → DuckDB, cube → Cube.dev). Inline
    and source-less models cannot aggregate and raise ``NoDataSourceError``.
    Callers validate field references and filter shapes before calling.
    """
    dimensions = dimensions or []
    model = load_model(model_name, models_dir=models_dir)
    resolver = ModelResolver(model)

    raw: dict[str, Any] = {
        "sheet": "query",
        "data": model_name,
        "rows": [{"measure": m} for m in measures],
        "marks": "bar",
    }
    if dimensions:
        raw["cols"] = dimensions[0]
    if dimensions[1:]:
        raw["tooltip"] = dimensions[1:]
    if filters:
        raw["filters"] = [f.model_dump() for f in filters]
    spec = ChartSpec.model_validate(raw)

    source_type = model.source.type if model.source is not None else None
    if source_type == "file":
        from shelves.data.duckdb_adapter import DuckDBAdapter

        adapter: Any = DuckDBAdapter(base_dir=data_base_dir)
    elif source_type is not None and source_type != "inline":
        from shelves.data.sources import get_adapter

        adapter = get_adapter(source_type)
    else:
        raise NoDataSourceError(
            f"Model {model_name!r} uses an {source_type or 'unset'} source, which cannot "
            "aggregate a query. query_model needs a file or cube source; render the "
            "inline data as a chart instead."
        )

    # The synthetic spec carries extra dimensions on tooltip; the chart-time
    # disaggregation warning (fields.py) is irrelevant to an explicit
    # aggregation query. Suppress ONLY that warning — any other warning the
    # adapter raises (KPI/format notices, real problems) must still surface.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Tooltip field .* disaggregate the data",
            category=UserWarning,
        )
        return adapter.fetch(model, spec, resolver)
