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
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

# DSL version — bump when the grammar changes.
# Follows semver: major = breaking, minor = additive, patch = fixes.
DSL_VERSION = "0.7.0"  # Labels: label property on charts (KAN-281)

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
MarkSpec = MarkType | MarkObject


# ─── Color Encoding ──────────────────────────────────────────────


class ColorFieldMapping(BaseModel):
    """Explicit color field with optional type override."""

    field: str
    type: Literal["quantitative", "nominal", "ordinal", "temporal"] | None = None


ColorSpec = str | ColorFieldMapping


# ─── Tooltip ──────────────────────────────────────────────────────


class TooltipField(BaseModel):
    field: str
    format: str | None = None


TooltipSpec = list[str] | list[TooltipField]


# ─── Filters ──────────────────────────────────────────────────────


_OPERATOR_RULES: dict[str, tuple[str, list[str]]] = {
    "in": ("values", ["value", "range"]),
    "not_in": ("values", ["value", "range"]),
    "between": ("range", ["value", "values"]),
    "eq": ("value", ["values", "range"]),
    "neq": ("value", ["values", "range"]),
    "gt": ("value", ["values", "range"]),
    "lt": ("value", ["values", "range"]),
    "gte": ("value", ["values", "range"]),
    "lte": ("value", ["values", "range"]),
}


class ShelfFilter(BaseModel):
    field: str
    operator: FilterOperator
    value: str | int | float | None = None
    values: list[str | int | float] | None = None
    range: list[str | int | float] | None = Field(None, min_length=2, max_length=2)

    @model_validator(mode="after")
    def _validate_operator_and_values(self) -> ShelfFilter:
        rule = _OPERATOR_RULES.get(self.operator)
        if rule is None:
            raise ValueError(f"Unknown filter operator: {self.operator!r}")

        required_field, forbidden_fields = rule
        if getattr(self, required_field) is None:
            raise ValueError(
                f"Filter operator {self.operator!r} requires '{required_field}' to be set."
            )
        for forbidden in forbidden_fields:
            if getattr(self, forbidden) is not None:
                raise ValueError(
                    f"Filter {self.operator!r} only supports"
                    f" '{required_field}';"
                    f" '{forbidden}' must be omitted."
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


SortSpec = FieldSort | AxisSort


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


FacetSpec = WrapFacet | RowColumnFacet


# ─── Axis Config ──────────────────────────────────────────────────


class AxisChannelConfig(BaseModel):
    title: str | None = None
    format: str | None = None
    grid: bool | None = None


class AxisConfig(BaseModel):
    x: AxisChannelConfig | None = None
    y: AxisChannelConfig | None = None


# ─── Label Configuration ─────────────────────────────────────────

LabelHorizontal = Literal["left", "center", "right"]
LabelVertical = Literal["top", "center", "bottom"]


class LabelConfig(BaseModel):
    """Configuration for data labels on a mark."""

    field: str | None = None
    horizontal: LabelHorizontal | None = None
    vertical: LabelVertical | None = None
    color: str | None = None
    size: int | float | None = Field(default=None, gt=0)
    format: str | None = None

    @model_validator(mode="after")
    def _validate_color(self) -> LabelConfig:
        if self.color is not None and self.color != "match" and not HEX_COLOR_RE.match(self.color):
            raise ValueError(
                f"Label color must be a hex color (e.g. '#333333') or 'match', got {self.color!r}"
            )
        return self


LabelSpec = bool | LabelConfig


# ─── KPI (special pattern) ────────────────────────────────────────


class KPIComparison(BaseModel):
    """Configuration for the comparison value displayed beneath the primary KPI metric."""

    field: str
    mode: Literal[
        "delta_percent",
        "delta_absolute",
        "value",
    ] = "delta_percent"
    format: str | None = None
    label: str | None = None
    polarity: Literal[
        "up_is_good",
        "down_is_good",
        "neutral",
    ] = "up_is_good"


class KPIBlock(BaseModel):
    """
    Top-level kpi property on a chart spec.
    When present, the translator routes to the KPI pattern compiler.
    """

    value: str
    format: str = Field(min_length=1)
    title: str | None = None
    spacing: int | None = Field(None, ge=0)
    comparison: KPIComparison | None = None

    @model_validator(mode="after")
    def value_differs_from_comparison_field(self) -> KPIBlock:
        if self.comparison is not None and self.value == self.comparison.field:
            raise ValueError(
                "kpi.value and comparison.field must be different fields "
                f"(both are '{self.value}')."
            )
        return self


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
    label: LabelSpec | None = None


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

    # KAN-232: shared axis visibility in stacked layouts
    # None = use default (show on edge panel only)
    # True = always show the shared axis on this panel
    # False = always hide the shared axis on this panel
    shared_axis: bool | None = None

    label: LabelSpec | None = None


# A shelf is either a single field name or a list of measure entries
ShelfSpec = str | list[MeasureEntry]


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
        description="DSL version this spec targets (e.g. '0.1.0').",
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

    # Data labels
    label: LabelSpec | None = None

    # KPI special pattern
    kpi: KPIBlock | None = None

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

    @model_validator(mode="after")
    def kpi_excludes_shelf_properties(self) -> ChartSpec:
        """When kpi is set, cols/rows/marks are ignored. Warn if present."""
        if self.kpi is not None and (
            self.cols is not None or self.rows is not None or self.marks is not None
        ):
            import warnings

            warnings.warn(
                "KPI spec has cols/rows/marks set — these are ignored when kpi is present.",
                UserWarning,
                stacklevel=2,
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
