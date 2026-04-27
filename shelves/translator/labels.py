"""
Label Layer Builder (KAN-223)

Builds implicit text-mark layers for data labels. Called by single.py,
stacked.py, and layers.py after constructing the primary mark spec.
"""

from __future__ import annotations

from typing import Any, Literal

from shelves.schema.chart_schema import LabelConfig, LabelSpec, MarkSpec
from shelves.schema.field_types import FieldTypeResolver

LabelPosition = Literal["top", "bottom", "left", "right", "inside-top", "inside-right"]

LABEL_POSITION_MAP: dict[tuple[str, str], dict[str, Any]] = {
    # (orientation, position) → text mark properties
    # Vertical orientation (measure on y-axis)
    ("vertical", "top"): {"baseline": "bottom", "dy": -6},
    ("vertical", "bottom"): {"baseline": "top", "dy": 8},
    ("vertical", "inside-top"): {"baseline": "top", "dy": 6},
    ("vertical", "left"): {"align": "right", "dx": -6},
    ("vertical", "right"): {"align": "left", "dx": 6},
    # Horizontal orientation (measure on x-axis)
    ("horizontal", "right"): {"align": "left", "dx": 6},
    ("horizontal", "left"): {"align": "right", "dx": -6},
    ("horizontal", "inside-right"): {"align": "right", "dx": -6},
    ("horizontal", "top"): {"baseline": "bottom", "dy": -6},
    ("horizontal", "bottom"): {"baseline": "top", "dy": 8},
}

# Slightly more clearance for marks without flat edges
_LINE_AREA_DY_ADJUSTMENT = -2  # e.g., "top" uses dy=-8 instead of -6

DEFAULT_LABEL_POSITION: dict[str, str] = {
    "vertical": "top",
    "horizontal": "right",
}

_LINE_AREA_MARKS = {"line", "area", "point", "circle"}


def resolve_label_spec(label: LabelSpec | None) -> LabelConfig | None:
    """
    Normalize a LabelSpec into a LabelConfig or None.

    - None → None (not set)
    - False → None (explicitly disabled)
    - True → LabelConfig() with all defaults
    - LabelConfig → return as-is
    """
    if label is None:
        return None
    if label is False:
        return None
    if label is True:
        return LabelConfig()
    if isinstance(label, LabelConfig):
        return label
    return None


def resolve_label_cascade(
    layer_label: LabelSpec | None,
    entry_label: LabelSpec | None,
    top_label: LabelSpec | None,
) -> LabelSpec | None:
    """
    3-level cascade for labels: layer > entry > top-level.
    Returns first non-None value (including False).
    None means "not set, inherit from parent".
    """
    if layer_label is not None:
        return layer_label
    if entry_label is not None:
        return entry_label
    return top_label


def get_mark_type(mark: MarkSpec) -> str:
    """Extract the mark type string from a MarkSpec (string or MarkObject)."""
    if isinstance(mark, str):
        return mark
    return mark.type


def _strip_axis_metadata(enc: dict[str, Any]) -> dict[str, Any]:
    """
    Strip axis-rendering metadata from a positional encoding copy.

    Removes the ``axis`` key and ``title`` so the text layer doesn't
    interfere with the primary mark's axis.  For **shared** scales (the
    common case) the key must be *absent* — ``axis: null`` would suppress
    the shared axis entirely.  For **independent** scales the caller sets
    ``axis: null`` explicitly after this helper returns.
    """
    enc.pop("axis", None)
    enc.pop("title", None)
    return enc


def build_label_layer(
    measure_field: str,
    base_x_enc: dict[str, Any],
    base_y_enc: dict[str, Any],
    label_config: LabelConfig,
    mark_type: str,
    orientation: str,
    resolver: FieldTypeResolver,
    color_enc: dict[str, Any] | None = None,
    detail_enc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a Vega-Lite text mark layer spec for data labels.

    Returns: {"mark": {"type": "text", ...}, "encoding": {..., "text": {...}}}
    """
    # Step 1: Determine the label field
    label_field = label_config.field if label_config.field else measure_field

    # Step 2: Determine position and mark properties
    position = (
        label_config.position if label_config.position else DEFAULT_LABEL_POSITION[orientation]
    )
    pos_props = dict(
        LABEL_POSITION_MAP.get((orientation, position), {"baseline": "bottom", "dy": -6})
    )

    # Adjust dy for line/area/point/circle marks
    if mark_type in _LINE_AREA_MARKS and "dy" in pos_props:
        pos_props["dy"] += _LINE_AREA_DY_ADJUSTMENT

    # Step 3: Build text mark properties
    mark_props: dict[str, Any] = {"type": "text"}
    mark_props.update(pos_props)
    if label_config.color:
        mark_props["color"] = label_config.color
    if label_config.size:
        mark_props["fontSize"] = label_config.size

    # Step 4: Build encoding — copy x/y, then strip axis metadata so the
    #         text layer doesn't redraw the primary mark's axes.
    encoding: dict[str, Any] = {
        "x": _strip_axis_metadata({**base_x_enc}),
        "y": _strip_axis_metadata({**base_y_enc}),
    }

    # Build text encoding
    text_enc: dict[str, Any] = {
        "field": label_field,
        "type": resolver.resolve(label_field),
    }
    # Format: explicit override first, then model auto-format
    fmt = label_config.format if label_config.format else resolver.resolve_format(label_field)
    if fmt is not None:
        text_enc["format"] = fmt

    encoding["text"] = text_enc

    # Inherit field-based color encoding with legend: null
    if color_enc is not None and "field" in color_enc:
        color_copy = {**color_enc, "legend": None}
        encoding["color"] = color_copy

    # Inherit detail encoding
    if detail_enc is not None:
        encoding["detail"] = detail_enc

    return {"mark": mark_props, "encoding": encoding}


def wrap_spec_with_label(
    spec: dict[str, Any],
    label_layer: dict[str, Any],
) -> dict[str, Any]:
    """
    Wrap a single-mark spec in a layer with a text label appended.

    Input:  {"mark": ..., "encoding": ..., "transform": [...]}
    Output: {"layer": [{"mark": ..., "encoding": ...}, label_layer], "transform": [...]}
    """
    # Extract transform — it goes on the layer group
    transforms = spec.pop("transform", None)

    mark_spec = {"mark": spec["mark"], "encoding": spec["encoding"]}
    result: dict[str, Any] = {"layer": [mark_spec, label_layer]}

    if transforms:
        result["transform"] = transforms

    return result


def detect_orientation(spec: Any, resolver: FieldTypeResolver) -> str:
    """
    Detect chart orientation from shelf assignments.

    Returns "vertical" or "horizontal".

    - If rows is a list (multi-measure on rows) → "vertical"
    - If cols is a list (multi-measure on cols) → "horizontal"
    - If both are strings: check resolver.is_measure(rows) → "vertical"
    - Else → "horizontal"
    """
    if isinstance(spec.rows, list):
        return "vertical"
    if isinstance(spec.cols, list):
        return "horizontal"
    # Single-measure: check if rows is a measure
    if isinstance(spec.rows, str) and resolver.is_measure(spec.rows):
        return "vertical"
    return "horizontal"
