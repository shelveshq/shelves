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
from shelves.translator.encodings import build_encodings
from shelves.translator.filters import build_transforms
from shelves.translator.labels import attach_label_intent, resolve_measure_field
from shelves.translator.marks import build_mark
from shelves.translator.sort import apply_default_sort_from_model, apply_sort

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

    # Label intent
    intent = attach_label_intent(
        inner, "mark_0", resolve_measure_field(spec, resolver), spec.label, resolver
    )
    if intent is not None:
        inner["_label_intents"] = [intent]

    return inner
