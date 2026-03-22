"""
Chart DSL Schema (Phase 1 + Phase 1a)

Pydantic models for the full Chart DSL grammar.

Phase 1 activates:
  - Single field shelves (rows: "revenue")
  - Multi-measure shelves without layers (rows: [{measure: revenue}, ...])
  - All encoding channels, filters, sort, facet

Phase 1a activates:
  - LayerEntry (layer property on MeasureEntry)
  - axis: independent/shared on MeasureEntry
  The schema parses these NOW but the translator compiles them in Phase 1a.
"""

from __future__ import annotations

import re
from typing import Literal, Union

import yaml
from pydantic import BaseModel, Field, model_validator


# DSL version — bump when the grammar changes.
# Follows semver: major = breaking, minor = additive, patch = fixes.
DSL_VERSION = "0.3.0"  # breaking: removed legacy DataSource inline declaration

# ─── Primitives ────────────────────────────────────────────────────

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")

MarkType = Literal[
    "bar",
    "line",
    "area",
    "circle",
    "square",
    "text",
    "point",
    "rule",
    "tick",
    "rect",
    "arc",
    "geoshape",
]

FilterOperator = Literal[
    "in",
    "not_in",
    "eq",
    "neq",
    "gt",
    "lt",
    "gte",
    "lte",
    "between",
]

SortOrder = Literal["ascending", "descending"]
ScaleResolve = Literal["independent", "shared"]
TimeGrain = Literal["day", "week", "month", "quarter", "year"]


# ─── Mark Definition ──────────────────────────────────────────────


class MarkObject(BaseModel):
    """Extended mark with style properties."""

    type: MarkType
    style: Literal["solid", "dashed", "dotted"] | None = None
    point: bool | None = None
    opacity: float | None = Field(None, ge=0.0, le=1.0)


# marks can be a string shorthand ("bar") or an object ({ type, style, ... })
MarkSpec = Union[MarkType, MarkObject]


# ─── Color Encoding ──────────────────────────────────────────────


class ColorFieldMapping(BaseModel):
    """Explicit color field with optional type override."""

    field: str
    type: Literal["quantitative", "nominal", "ordinal", "temporal"] | None = None


ColorSpec = Union[str, ColorFieldMapping]


# ─── Tooltip ──────────────────────────────────────────────────────


class TooltipField(BaseModel):
    field: str
    format: str | None = None


TooltipSpec = Union[list[str], list[TooltipField]]


# ─── Filters ──────────────────────────────────────────────────────


class ShelfFilter(BaseModel):
    field: str
    operator: FilterOperator
    value: str | int | float | None = None
    values: list[str | int | float] | None = None
    range: list[str | int | float] | None = Field(None, min_length=2, max_length=2)

    @model_validator(mode="after")
    def _validate_operator_and_values(self) -> "ShelfFilter":
        """
        Enforce that each operator uses the correct value field:

        - in / not_in  -> requires `values`, forbids `value` and `range`
        - between      -> requires `range`, forbids `value` and `values`
        - eq / neq / gt / lt / gte / lte -> requires `value`,
          forbids `values` and `range`
        """
        op = self.operator
        has_value = self.value is not None
        has_values = self.values is not None
        has_range = self.range is not None

        if op in ("in", "not_in"):
            if not has_values:
                raise ValueError("Filter operator 'in'/'not_in' requires 'values' to be set.")
            if has_value or has_range:
                raise ValueError(
                    "Filter operator 'in'/'not_in' only supports 'values'; 'value' and 'range' must be omitted."
                )

        elif op == "between":
            if not has_range:
                raise ValueError("Filter operator 'between' requires 'range' to be set.")
            if has_value or has_values:
                raise ValueError(
                    "Filter operator 'between' only supports 'range'; 'value' and 'values' must be omitted."
                )

        else:
            # eq, neq, gt, lt, gte, lte
            if not has_value:
                raise ValueError(f"Filter operator '{op}' requires 'value' to be set.")
            if has_values or has_range:
                raise ValueError(
                    f"Filter operator '{op}' only supports 'value'; 'values' and 'range' must be omitted."
                )

        return self


# ─── Sort ─────────────────────────────────────────────────────────


class FieldSort(BaseModel):
    """Sort by a field's values (ascending/descending or custom order)."""

    field: str
    order: SortOrder | list[str]
    channel: Literal["x", "y"] = "x"


class AxisSort(BaseModel):
    """Sort by another axis's values (e.g., sort x by y values)."""

    axis: Literal["x", "y"]
    order: SortOrder
    channel: Literal["x", "y"] = "x"


SortSpec = Union[FieldSort, AxisSort]


# ─── Facet ────────────────────────────────────────────────────────


class RowColumnFacet(BaseModel):
    """Facet by row, column, or both (grid)."""

    row: str | None = None
    column: str | None = None
    axis: ScaleResolve | None = None

    @model_validator(mode="after")
    def at_least_one_channel(self):
        if not self.row and not self.column:
            raise ValueError("RowColumnFacet requires at least one of 'row' or 'column'")
        return self


class WrapFacet(BaseModel):
    """Wrapping facet — single dimension wrapped into a grid."""

    field: str
    columns: int = Field(gt=0)
    sort: SortOrder | None = None
    axis: ScaleResolve | None = None


FacetSpec = Union[WrapFacet, RowColumnFacet]


# ─── Axis Config ──────────────────────────────────────────────────


class AxisChannelConfig(BaseModel):
    title: str | None = None
    format: str | None = None
    grid: bool | None = None


class AxisConfig(BaseModel):
    x: AxisChannelConfig | None = None
    y: AxisChannelConfig | None = None


# ─── KPI (special pattern) ────────────────────────────────────────


class KPIComparison(BaseModel):
    measure: str
    format: str | None = None
    type: Literal["percent_change", "absolute_change", "value"] | None = None


class KPIConfig(BaseModel):
    measure: str
    format: str | None = None
    comparison: KPIComparison | None = None


# ─── Multi-Measure Shelf Entries ──────────────────────────────────


class LayerEntry(BaseModel):
    """
    A measure layered on top of a parent MeasureEntry (Phase 1a).

    Layers share the chart space with their parent — they're overlaid,
    not stacked as separate panels. Each layer can override mark, color,
    detail, size, and opacity, or inherit from the parent entry / top-level.
    """

    measure: str
    mark: MarkSpec | None = None
    color: ColorSpec | None = None
    detail: str | None = None
    size: str | int | float | None = None
    opacity: float | None = Field(None, ge=0.0, le=1.0)


class MeasureEntry(BaseModel):
    """
    One entry on the multi-measure shelf (rows or cols).

    Without `layer`: a standalone panel in a stacked layout.
    With `layer`: a multi-axis panel where the parent measure and
    layer measures share the same chart space.

    Encoding properties (mark, color, detail, size, opacity) on this
    entry act as defaults for its layer entries.
    """

    measure: str
    mark: MarkSpec | None = None
    color: ColorSpec | None = None
    detail: str | None = None
    size: str | int | float | None = None
    opacity: float | None = Field(None, ge=0.0, le=1.0)

    # Phase 1a: layers overlaid on this measure
    layer: list[LayerEntry] | None = None

    # Phase 1a: axis scale resolution for layers
    # "independent" = each measure gets its own axis scale
    # "shared" = all measures share one axis scale (default)
    axis: ScaleResolve | None = None


# A shelf is either a single field name or a list of measure entries
ShelfSpec = Union[str, list[MeasureEntry]]


# ─── Top-Level Chart Spec ─────────────────────────────────────────


class ChartSpec(BaseModel):
    """
    A fully validated Chart DSL spec.

    Supports three shelf shapes:
      1. String field name → single-measure chart (Phase 1)
      2. List of MeasureEntry without layers → stacked panels (Phase 1)
      3. List of MeasureEntry with layers → multi-axis / stacked layers (Phase 1a)

    Top-level marks/color/detail/size act as inheritable defaults for
    measure entries and their layers.
    """

    version: str | None = Field(
        None,
        description="DSL version this spec targets (e.g. '0.1.0'). Optional; used for forwards-compatibility checks.",
    )

    sheet: str = Field(min_length=1)
    description: str | None = None
    data: str = Field(min_length=1, description="Model name referencing a DataModel manifest.")

    # Shelf assignments
    cols: ShelfSpec | None = None
    rows: ShelfSpec | None = None

    # Default mark — inherited by measure entries / layers that don't set their own
    marks: MarkSpec | None = None

    # Default encoding channels — inherited by entries / layers
    color: ColorSpec | None = None
    detail: str | None = None
    size: str | int | float | None = None
    tooltip: TooltipSpec | None = None

    # Interactions
    filters: list[ShelfFilter] | None = None
    sort: SortSpec | None = None

    # Partitioning
    facet: FacetSpec | None = None

    # Axis config (for single-measure charts)
    axis: AxisConfig | None = None

    # KPI special pattern
    kpi: KPIConfig | None = None

    @model_validator(mode="after")
    def at_most_one_multi_measure_shelf(self):
        """Only one of rows/cols can be a multi-measure list."""
        rows_multi = isinstance(self.rows, list)
        cols_multi = isinstance(self.cols, list)
        if rows_multi and cols_multi:
            raise ValueError(
                "Only one of rows/cols can have multiple measures. "
                "Use a single field for the other axis."
            )
        return self

    @model_validator(mode="after")
    def single_measure_requires_marks(self):
        """When rows/cols are strings (Phase 1), top-level marks is required."""
        rows_is_str = isinstance(self.rows, str)
        cols_is_str = isinstance(self.cols, str) or self.cols is None
        if rows_is_str and cols_is_str and self.marks is None and self.kpi is None:
            raise ValueError(
                "Top-level 'marks' is required for single-measure charts. "
                "For multi-measure charts, set mark on each measure entry."
            )
        return self


# ─── Public API ───────────────────────────────────────────────────


def parse_chart(yaml_string: str) -> ChartSpec:
    """
    Parse a YAML string and validate against the Chart DSL schema.

    Returns a ChartSpec on success, raises pydantic.ValidationError on failure.

    Usage:
        spec = parse_chart(Path("chart.yaml").read_text())
    """
    raw = yaml.safe_load(yaml_string)
    return ChartSpec.model_validate(raw)
