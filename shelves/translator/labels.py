"""
Label Intent Builder

Builds usermeta label descriptors for the compile-then-patch label
architecture. Python emits label intent; JavaScript handles placement.
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import (
    ChartSpec,
    ColorFieldMapping,
    LabelConfig,
    LabelSpec,
)
from shelves.schema.field_types import FieldTypeResolver


def resolve_label_spec(label: LabelSpec | None) -> LabelConfig | None:
    if label is None or label is False:
        return None
    if label is True:
        return LabelConfig()
    return label


def resolve_label_cascade(
    layer_label: LabelSpec | None,
    entry_label: LabelSpec | None,
    top_label: LabelSpec | None,
) -> LabelSpec | None:
    if layer_label is not None:
        return layer_label
    if entry_label is not None:
        return entry_label
    return top_label


def build_label_intent(
    mark_name: str,
    measure_field: str,
    label_config: LabelConfig,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    field = label_config.field or measure_field
    return {
        "markName": mark_name,
        "field": resolver.resolve_base_field(field),
        "type": resolver.resolve(field),
        "format": label_config.format or resolver.resolve_format(field),
        # Left unset (null) when the user didn't specify a side: the JS patch
        # treats null as the outside default (above/right) and reserves explicit
        # "center" for inside-the-segment placement.
        "horizontal": label_config.horizontal,
        "vertical": label_config.vertical,
        "size": label_config.size or 11,
        "color": label_config.color,
    }


def attach_label_intent(
    panel: dict[str, Any],
    mark_name: str,
    measure_field: str,
    resolved_label: LabelSpec | None,
    resolver: FieldTypeResolver,
) -> dict[str, Any] | None:
    """Name *panel* and build its label intent when *resolved_label* is active.

    Returns the intent dict, or None (leaving *panel* untouched) when there is
    no active label. Centralizes the name↔intent pairing the JS patch relies on
    (the intent's ``markName`` must match the mark the panel compiles to).
    """
    label_config = resolve_label_spec(resolved_label)
    if label_config is None:
        return None
    panel["name"] = mark_name
    return build_label_intent(mark_name, measure_field, label_config, resolver)


def resolve_measure_field(
    spec: ChartSpec,
    resolver: FieldTypeResolver,
) -> str:
    if isinstance(spec.rows, str) and resolver.is_measure(spec.rows):
        return spec.rows
    if isinstance(spec.cols, str) and resolver.is_measure(spec.cols):
        return spec.cols
    # Heatmap case: both shelves are band fields and the measure rides on color.
    # Checked before the band-field fallback so a heatmap labels its colour
    # measure; bar/stacked charts hit the measure branches above and never reach
    # here (KAN-307).
    if isinstance(spec.color, ColorFieldMapping) and resolver.is_measure(spec.color.field):
        return spec.color.field
    if isinstance(spec.color, str) and resolver.is_measure(spec.color):
        return spec.color
    if isinstance(spec.rows, str):
        return spec.rows
    if isinstance(spec.cols, str):
        return spec.cols
    raise ValueError("No string shelf found for label measure resolution")
