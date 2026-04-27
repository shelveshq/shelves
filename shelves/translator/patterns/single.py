"""
Single-Measure Chart Compiler

Handles the simple case: both rows and cols are string field names.
Produces a single-mark Vega-Lite spec with encoding channels.

This is the Phase 1 compilation path, unchanged from the original.
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import ChartSpec
from shelves.schema.field_types import FieldTypeResolver
from shelves.translator.marks import build_mark
from shelves.translator.encodings import build_encodings
from shelves.translator.filters import build_transforms
from shelves.translator.sort import apply_sort, apply_default_sort_from_model
from shelves.translator.labels import (
    build_label_layer,
    detect_orientation,
    get_mark_type,
    resolve_label_spec,
    wrap_spec_with_label,
)

VegaLiteSpec = dict[str, Any]


def compile_single(spec: ChartSpec, resolver: FieldTypeResolver) -> VegaLiteSpec:
    """Compile a single-measure ChartSpec into a Vega-Lite spec dict."""

    inner: VegaLiteSpec = {}

    # Mark (required for single-measure charts, enforced by schema validator)
    assert spec.marks is not None, "compile_single requires marks (enforced by schema)"
    inner["mark"] = build_mark(spec.marks)

    # Encoding channels
    inner["encoding"] = build_encodings(spec, resolver)

    # Sort — explicit chart sort first
    apply_sort(inner["encoding"], spec.sort, resolver)

    # Default sort from model — only if no explicit sort
    apply_default_sort_from_model(inner["encoding"], spec.sort, resolver)

    # Transforms (filters)
    transforms = build_transforms(spec.filters, resolver)
    if transforms:
        inner["transform"] = transforms

    # Label wrapping
    label_config = resolve_label_spec(spec.label)
    if label_config is not None:
        orientation = detect_orientation(spec, resolver)
        measure_field = spec.rows if orientation == "vertical" else spec.cols
        assert isinstance(measure_field, str)
        mark_type = get_mark_type(spec.marks)  # type: ignore[arg-type]

        # Skip label layer for text marks
        if mark_type != "text":
            color_enc = inner["encoding"].get("color")
            # Only pass color_enc if it's field-based (not a hex value)
            if color_enc and "field" not in color_enc:
                color_enc = None
            detail_enc = inner["encoding"].get("detail")

            label_layer = build_label_layer(
                measure_field=measure_field,
                base_x_enc=inner["encoding"]["x"],
                base_y_enc=inner["encoding"]["y"],
                label_config=label_config,
                mark_type=mark_type,
                orientation=orientation,
                resolver=resolver,
                color_enc=color_enc,
                detail_enc=detail_enc,
            )
            inner = wrap_spec_with_label(inner, label_layer)

    return inner
