"""
Field Type Inference

Resolves field names to Vega-Lite types based on the ChartSpec's data block.

Strategy (Phase 1):
  - data.measures → "quantitative"
  - data.dimensions + time_grain match → "temporal"
  - data.dimensions → "nominal"

Phase 3: types come from Cube.dev metadata, but the interface stays the same.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from src.schema.chart_schema import DataSource

VegaLiteType = Literal["quantitative", "temporal", "nominal", "ordinal"]


@runtime_checkable
class FieldTypeResolver(Protocol):
    """Protocol for resolving field names to Vega-Lite types."""

    def resolve(self, field_name: str) -> VegaLiteType: ...


class DataBlockResolver:
    """
    Phase 1 resolver — infers types from the ChartSpec's data block.
    """

    def __init__(self, data: DataSource) -> None:
        self._measures = set(data.measures)
        self._dimensions = set(data.dimensions)
        self._temporal_field = data.time_grain.field if data.time_grain else None

    def resolve(self, field_name: str) -> VegaLiteType:
        if field_name in self._measures:
            return "quantitative"

        if field_name in self._dimensions:
            if field_name == self._temporal_field:
                return "temporal"
            return "nominal"

        raise ValueError(
            f'Field "{field_name}" not found in data.measures or data.dimensions. '
            f"Available: measures={sorted(self._measures)}, "
            f"dimensions={sorted(self._dimensions)}"
        )
