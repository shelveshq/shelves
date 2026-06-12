"""
Data Model Manifest Schema

Pydantic models for the data model YAML format. A data model manifest
defines every measure, dimension, and temporal field for a semantic model —
including types, labels, formats, sort defaults, and temporal grain support.

This is the equivalent of Tableau's Data pane expressed as version-controlled YAML.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TimeGrain = Literal["day", "week", "month", "quarter", "year"]
SortOrder = Literal["ascending", "descending"]
Aggregation = Literal["sum", "count", "avg", "min", "max", "count_distinct"]
JoinType = Literal["left", "inner"]

_CALC_REF_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class MeasureDefinition(BaseModel):
    """
    One measure field in a data model manifest.

    Measures are quantitative fields (numbers). The label, format, and
    defaultSort are used downstream for axis auto-titles, formatting,
    and sort inference. aggregation is informational only — the actual
    aggregation is the semantic layer's responsibility.
    """

    label: str = Field(min_length=1)
    format: str | None = None
    description: str | None = None
    defaultSort: SortOrder | None = None
    aggregation: Aggregation | None = None
    column: str | None = None
    calculation: str | None = None

    @model_validator(mode="after")
    def column_calculation_exclusive(self) -> MeasureDefinition:
        if self.column is not None and self.calculation is not None:
            raise ValueError(
                "'column' and 'calculation' are mutually exclusive — use one or the other"
            )
        return self


class NominalDimensionDefinition(BaseModel):
    """
    A categorical (nominal or ordinal) dimension field.

    When `type` is omitted in the YAML, it defaults to "nominal".
    Set `type: ordinal` for fields with a meaningful category order
    (e.g. T-shirt sizes, survey ratings).

    `sortOrder` translates to Vega-Lite encoding.sort array, overriding
    any defaultSort when set.
    """

    type: Literal["nominal", "ordinal"] = "nominal"
    label: str = Field(min_length=1)
    description: str | None = None
    defaultSort: SortOrder | None = None
    sortOrder: list[str] | None = None
    column: str | None = None
    calculation: str | None = None

    @model_validator(mode="after")
    def column_calculation_exclusive(self) -> NominalDimensionDefinition:
        if self.column is not None and self.calculation is not None:
            raise ValueError(
                "'column' and 'calculation' are mutually exclusive — use one or the other"
            )
        return self


class TemporalDimensionDefinition(BaseModel):
    """
    A temporal dimension field with grain support.

    `type: temporal` is the discriminator that distinguishes this from
    NominalDimensionDefinition. `defaultGrain` is required — it is used
    when a chart writes `cols: order_date` without dot-notation grain selection.

    `grains` restricts which granularities are supported. Omit it to allow
    all five (day, week, month, quarter, year). Only specify it if you need
    to restrict available grains (e.g. a "year" field that only supports `year`).

    `format` is a per-grain dict of D3 format strings, auto-applied to axes.
    """

    type: Literal["temporal"]
    label: str = Field(min_length=1)
    description: str | None = None
    grains: list[TimeGrain] = Field(default=["day", "week", "month", "quarter", "year"])
    defaultGrain: TimeGrain
    format: dict[str, str] | None = None
    column: str | None = None
    calculation: str | None = None

    @model_validator(mode="after")
    def default_grain_in_grains(self) -> TemporalDimensionDefinition:
        if self.defaultGrain not in self.grains:
            raise ValueError(f"defaultGrain '{self.defaultGrain}' is not in grains {self.grains}")
        return self

    @model_validator(mode="after")
    def format_keys_are_valid_grains(self) -> TemporalDimensionDefinition:
        if self.format:
            valid = {"day", "week", "month", "quarter", "year"}
            invalid = set(self.format.keys()) - valid
            if invalid:
                raise ValueError(
                    f"format keys {invalid} are not valid grains. Valid grains: {sorted(valid)}"
                )
        return self

    @model_validator(mode="after")
    def column_calculation_exclusive(self) -> TemporalDimensionDefinition:
        if self.column is not None and self.calculation is not None:
            raise ValueError(
                "'column' and 'calculation' are mutually exclusive — use one or the other"
            )
        return self


# Discriminated union on the `type` field.
# When `type` is "temporal" → TemporalDimensionDefinition.
# When `type` is "nominal", "ordinal", or omitted → NominalDimensionDefinition.
# Pydantic v2 tries TemporalDimensionDefinition first (Literal["temporal"] is a
# stronger discriminant), then falls back to NominalDimensionDefinition.
DimensionDefinition = TemporalDimensionDefinition | NominalDimensionDefinition


class InlineSource(BaseModel):
    """Data source pointing to a local JSON file (deprecated — use FileSource)."""

    type: Literal["inline"]
    path: str = Field(min_length=1)


class CubeSource(BaseModel):
    """Data source pointing to a Cube.dev cube."""

    type: Literal["cube"]
    cube: str = Field(min_length=1)


class FileSource(BaseModel):
    """Data source pointing to a local flat file (CSV, Parquet, JSON)."""

    type: Literal["file"]
    path: str = Field(min_length=1)


class JoinDefinition(BaseModel):
    """A declared join from this model to another model."""

    model: str = Field(min_length=1)
    type: JoinType
    on: str = Field(min_length=1)


ModelSource = FileSource | CubeSource | InlineSource


class DataModel(BaseModel):
    """
    A complete data model manifest.

    Defines every measure and dimension for a semantic model, including
    types, labels, formats, sort defaults, and temporal grain support.
    Chart specs reference a model by name (data: orders) instead of
    redeclaring field metadata in every chart.

    The `model` field must match the YAML filename stem — this is enforced
    by the loader, not this schema.
    """

    model: str = Field(min_length=1)
    """Model identifier. Must match the YAML filename stem (e.g. "orders" for orders.yaml)."""

    label: str = Field(min_length=1)
    """Human-readable name for the model (e.g. "Orders")."""

    description: str | None = None
    """Documentation string for the model."""

    source: ModelSource | None = None
    """Data source configuration. Optional — charts can override data binding."""

    measures: dict[str, MeasureDefinition]
    dimensions: dict[str, DimensionDefinition]
    joins: dict[str, JoinDefinition] | None = None

    @model_validator(mode="after")
    def measures_not_empty(self) -> DataModel:
        if not self.measures:
            raise ValueError("A data model must have at least one measure")
        return self

    @model_validator(mode="after")
    def validate_calculation_refs(self) -> DataModel:
        from graphlib import CycleError, TopologicalSorter

        graph: dict[str, set[str]] = {}
        for name, measure in self.measures.items():
            if measure.calculation is None:
                continue
            refs = set(_CALC_REF_RE.findall(measure.calculation))
            for ref in refs:
                if ref not in self.measures:
                    raise ValueError(
                        f"Measure '{name}' calculation references '{{{{ {ref} }}}}' "
                        f"which is not a defined measure. "
                        f"Available measures: {sorted(self.measures.keys())}"
                    )
            if refs:
                graph[name] = refs

        if graph:
            try:
                ts = TopologicalSorter(graph)
                list(ts.static_order())
            except CycleError as e:
                raise ValueError(f"Cyclic calculation dependency detected: {e}") from None

        return self
