"""
Data Source Adapter Registry

Defines the DataSourceAdapter protocol and a registry for pluggable data sources.
New adapters register themselves at import time.
"""

from __future__ import annotations

from typing import Any, Protocol

from shelves.models.schema import DataModel
from shelves.schema.chart_schema import ChartSpec
from shelves.schema.field_types import FieldTypeResolver


class DataSourceAdapter(Protocol):
    """Protocol for fetching data from a source configured in a DataModel."""

    def fetch(
        self,
        model: DataModel,
        chart_spec: ChartSpec,
        resolver: FieldTypeResolver,
    ) -> list[dict[str, Any]]:
        """Fetch rows from the data source."""
        ...


_registry: dict[str, DataSourceAdapter] = {}


def register(source_type: str, adapter: DataSourceAdapter) -> None:
    """Register an adapter for a data source type (e.g. "cube")."""
    _registry[source_type] = adapter


def get_adapter(source_type: str) -> DataSourceAdapter:
    """
    Look up a registered adapter by source type.

    Raises KeyError if no adapter is registered for the given type.
    """
    if source_type not in _registry:
        raise KeyError(
            f"No data source adapter registered for type '{source_type}'. "
            f"Available: {sorted(_registry.keys())}"
        )
    return _registry[source_type]


class CubeDataSourceAdapter:
    """Adapter that fetches data from Cube.dev via cube_client."""

    def fetch(
        self,
        model: DataModel,
        chart_spec: ChartSpec,
        resolver: FieldTypeResolver,
    ) -> list[dict[str, Any]]:
        from shelves.data.cube_client import fetch_from_cube_model

        return fetch_from_cube_model(model, chart_spec, resolver)


register("cube", CubeDataSourceAdapter())


def _register_file_adapter() -> None:
    from shelves.data.duckdb_adapter import DuckDBAdapter

    register("file", DuckDBAdapter())


_register_file_adapter()
