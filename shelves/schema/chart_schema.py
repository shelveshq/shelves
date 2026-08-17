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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from shelves.params.substitute import ParameterReferenceError, ParameterSet, substitute_parameters

# Reject unknown keys everywhere in the chart grammar (SHE-54). A silently
# ignored key (e.g. `colour:` for `color:`) is an LLM trap and a human
# footgun; the validator turns it into a "did you mean" error instead. Shared
# so every model in this grammar forbids extras identically.
_STRICT = ConfigDict(extra="forbid")

# DSL version — bump when ANY DSL grammar changes (chart or layout).
# Follows semver: major = breaking, minor = additive, patch = fixes.
# 0.8.0: label grammar changed — LabelConfig.position replaced by
# horizontal/vertical, and color now accepts "match" (KAN-281). Breaking for
# specs that used the old `position` key (now silently ignored by Pydantic).
# 0.9.0: axis channel toggles — AxisChannelConfig gains ruler/ticks/labels
# booleans; AxisConfig.x/.y accept a bare bool (false drops the axis). The
# x-off/y-on grid default moved from a hardcoded encoding injection to the
# theme (axisX/axisY). Additive → minor.
# 0.10.0: project-level parameters (models/parameters.yaml) with $name /
# ${name} references in field slots, filter values, and title text (SHE-89).
# No ChartSpec field changes — references are substituted before parsing.
# Additive → minor.
# 0.11.0: control leaf type added to the layout DSL (SHE-92). Additive → minor.
# 0.12.0: control → parameter leaf type rename (SHE-97). Breaking → minor (pre-1.0).
# 0.13.0: filter leaf type + contains operator + compose-time filter injection (SHE-79/80).
# 0.14.0: filter `dropdown` bool (single/multi widget style). Additive → minor.
DSL_VERSION = "0.14.0"

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
    "contains",
]

SortOrder = Literal["ascending", "descending"]
ScaleResolve = Literal["independent", "shared"]
TimeGrain = Literal["day", "week", "month", "quarter", "year"]


# ─── Mark Definition ──────────────────────────────────────────────


class MarkObject(BaseModel):
    """Extended mark with style properties."""

    model_config = _STRICT

    type: MarkType
    style: Literal["solid", "dashed", "dotted"] | None = None
    point: bool | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)


# marks can be a string shorthand ("bar") or an object ({ type, style, ... })
MarkSpec = MarkType | MarkObject


# ─── Color Encoding ──────────────────────────────────────────────


class ColorFieldMapping(BaseModel):
    """Explicit color field with optional type override."""

    model_config = _STRICT

    field: str
    type: Literal["quantitative", "nominal", "ordinal", "temporal"] | None = None


ColorSpec = str | ColorFieldMapping


# ─── Tooltip ──────────────────────────────────────────────────────


class TooltipField(BaseModel):
    model_config = _STRICT

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
    "contains": ("value", ["values", "range"]),
}


class ShelfFilter(BaseModel):
    model_config = _STRICT

    field: str
    operator: FilterOperator
    value: str | int | float | None = None
    values: list[str | int | float] | None = None
    range: list[str | int | float] | None = Field(default=None, min_length=2, max_length=2)

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

    model_config = _STRICT

    field: str
    order: SortOrder | list[str]
    channel: Literal["x", "y"] | None = None


class AxisSort(BaseModel):
    """Sort by another axis's values (e.g., sort x by y values)."""

    model_config = _STRICT

    axis: Literal["x", "y"]
    order: SortOrder
    channel: Literal["x", "y"] | None = None


SortSpec = FieldSort | AxisSort


# ─── Facet ────────────────────────────────────────────────────────


class RowColumnFacet(BaseModel):
    """Facet by row, column, or both (grid)."""

    model_config = _STRICT

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

    model_config = _STRICT

    field: str
    columns: int = Field(gt=0)
    sort: SortOrder | None = None
    axis: ScaleResolve | None = None


FacetSpec = WrapFacet | RowColumnFacet


# ─── Axis Config ──────────────────────────────────────────────────


class AxisChannelConfig(BaseModel):
    """Per-channel axis customization for single-measure charts.

    Booleans are passthroughs into the channel's Vega-Lite ``axis`` object.
    Each is None by default → the property is omitted from the encoding so it
    inherits the theme default (config.axisX / config.axisY).

    Naming: ``ruler`` (Tableau's "Axis Ruler") maps to VL ``axis.domain`` —
    the baseline drawn along the axis. Line *styling* stays theme-only.
    """

    model_config = _STRICT

    title: str | None = None
    format: str | None = None
    grid: bool | None = None  # → VL axis.grid
    ruler: bool | None = None  # → VL axis.domain (Tableau "Axis Ruler")
    ticks: bool | None = None  # → VL axis.ticks
    labels: bool | None = None  # → VL axis.labels


class AxisConfig(BaseModel):
    # Each channel may be a bare bool or a granular config object.
    #   False  → encoding.<channel>.axis = null (drop the axis entirely)
    #   True   → show the axis with all theme defaults (no overrides)
    #   object → granular per-property toggles
    # Mirrors how LabelSpec accepts ``bool | LabelConfig``.
    model_config = _STRICT

    x: bool | AxisChannelConfig | None = None
    y: bool | AxisChannelConfig | None = None


# ─── Label Configuration ─────────────────────────────────────────

LabelHorizontal = Literal["left", "center", "right"]
LabelVertical = Literal["top", "center", "bottom"]


class LabelConfig(BaseModel):
    """Configuration for data labels on a mark."""

    model_config = _STRICT

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

    model_config = _STRICT

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

    model_config = _STRICT

    value: str
    format: str = Field(min_length=1)
    title: str | None = None
    spacing: int | None = Field(default=None, ge=0)
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

    model_config = _STRICT

    measure: str
    mark: MarkSpec | None = None
    color: ColorSpec | None = None
    detail: str | None = None
    size: str | int | float | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
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

    model_config = _STRICT

    measure: str
    mark: MarkSpec | None = None
    color: ColorSpec | None = None
    detail: str | None = None
    size: str | int | float | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)

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

    model_config = _STRICT

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


def parse_chart(
    yaml_string: str,
    *,
    parameters: ParameterSet | None = None,
) -> ChartSpec:
    """
    Parse a YAML string and validate against the Chart DSL schema.

    Returns a ChartSpec on success, raises pydantic.ValidationError on failure.

    `$name` / `${name}` references are substituted before validation using
    `parameters` (SHE-89). None means no parameters are declared — a spec that
    contains references then fails with an undeclared-reference error.

    Usage:
        spec = parse_chart(Path("chart.yaml").read_text())

    Raises:
        ValueError: a reference is undeclared, sits in a forbidden position, or
            has the wrong type for its slot; or the YAML declares an inline
            `parameters:` block (parameters live in models/parameters.yaml).
    """
    raw = yaml.safe_load(yaml_string)
    if not isinstance(raw, dict):
        # Preserve today's error behavior for malformed input.
        return ChartSpec.model_validate(raw)

    result = substitute_parameters(raw, parameters or ParameterSet.empty())
    if result.errors:
        raise ParameterReferenceError(result.errors)

    return ChartSpec.model_validate(result.data)
