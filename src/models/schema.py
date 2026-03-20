"""
Data Model Manifest Schema

Pydantic models for the data model YAML format. A data model manifest
defines every measure, dimension, and temporal field for a semantic model —
including types, labels, formats, sort defaults, and temporal grain support.

This is the equivalent of Tableau's Data pane expressed as version-controlled YAML.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field, model_validator

TimeGrain = Literal["day", "week", "month", "quarter", "year"]
SortOrder = Literal["ascending", "descending"]


class MeasureDefinition(BaseModel):
    """
    One measure field in a data model manifest.

    Measures are quantitative fields (numbers). The label, format, and
    defaultSort are used downstream for axis auto-titles, formatting,
    and sort inference. aggregation is informational only — the actual
    aggregation is the semantic layer's responsibility.
    """

    label: str = Field(min_length=1)
    """Human-readable name used for axis titles, legend, and tooltips. e.g. "Revenue"."""

    format: str | None = None
    """D3 format string. Auto-applied to axes, tooltips, and labels. e.g. "$,.0f"."""

    description: str | None = None
    """For documentation and LLM context when generating charts."""

    defaultSort: SortOrder | None = None
    """Applied when this measure is on an axis and no explicit sort is set."""

    aggregation: str | None = None
    """Informational only (sum, avg, count, min, max). Actual aggregation is the semantic layer's job."""


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
    """Vega-Lite field type. Defaults to "nominal" when omitted."""

    label: str = Field(min_length=1)
    """Human-readable name."""

    description: str | None = None
    """Documentation / LLM context."""

    defaultSort: SortOrder | None = None
    """Default sort when this field is on an axis."""

    sortOrder: list[str] | None = None
    """Explicit category order. Overrides defaultSort. Translates to VL encoding.sort array."""


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
    """Discriminator — must be "temporal" to route to this model."""

    label: str = Field(min_length=1)
    """Human-readable name."""

    description: str | None = None
    """Documentation / LLM context."""

    grains: list[TimeGrain] = Field(default=["day", "week", "month", "quarter", "year"])
    """Supported granularities. Defaults to all five when omitted."""

    defaultGrain: TimeGrain
    """Required. Used when the chart references this field without a grain suffix."""

    format: dict[str, str] | None = None
    """Per-grain D3 format strings. Keys must be valid TimeGrain values."""

    @model_validator(mode="after")
    def default_grain_in_grains(self) -> "TemporalDimensionDefinition":
        """defaultGrain must be one of the declared supported grains."""
        if self.defaultGrain not in self.grains:
            raise ValueError(f"defaultGrain '{self.defaultGrain}' is not in grains {self.grains}")
        return self

    @model_validator(mode="after")
    def format_keys_are_valid_grains(self) -> "TemporalDimensionDefinition":
        """If format is set, all keys must be valid TimeGrain values."""
        if self.format:
            valid = {"day", "week", "month", "quarter", "year"}
            invalid = set(self.format.keys()) - valid
            if invalid:
                raise ValueError(
                    f"format keys {invalid} are not valid grains. Valid grains: {sorted(valid)}"
                )
        return self


# Discriminated union on the `type` field.
# When `type` is "temporal" → TemporalDimensionDefinition.
# When `type` is "nominal", "ordinal", or omitted → NominalDimensionDefinition.
# Pydantic v2 tries TemporalDimensionDefinition first (Literal["temporal"] is a
# stronger discriminant), then falls back to NominalDimensionDefinition.
DimensionDefinition = Union[TemporalDimensionDefinition, NominalDimensionDefinition]


class InlineSource(BaseModel):
    """Data source pointing to a local JSON file."""

    type: Literal["inline"]
    path: str = Field(min_length=1)
    """Relative path to the JSON data file from the project root."""


class CubeSource(BaseModel):
    """Data source pointing to a Cube.dev cube."""

    type: Literal["cube"]
    cube: str = Field(min_length=1)
    """Cube name in the Cube.dev schema (e.g. "Orders")."""


ModelSource = Union[InlineSource, CubeSource]


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
    """Dict of measure field name → MeasureDefinition. At least one required."""

    dimensions: dict[str, DimensionDefinition]
    """Dict of dimension field name → DimensionDefinition (nominal or temporal)."""

    @model_validator(mode="after")
    def measures_not_empty(self) -> "DataModel":
        """A data model must define at least one measure."""
        if not self.measures:
            raise ValueError("A data model must have at least one measure")
        return self
