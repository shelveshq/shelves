"""
Chart DSL → Vega-Lite Translator

Routes based on spec shape:
  1. Both shelves are strings → patterns/single.py (single-measure chart)
  2. One shelf is a list, no layers → patterns/stacked.py (stacked panels)
  3. One shelf is a list with layers → patterns/stacked.py (delegates to layers.py)

All paths produce a Vega-Lite dict, then facet wrapping is applied uniformly.

Pure function — no side effects, no data fetching, no theme merging.
"""

from __future__ import annotations

from typing import Any

from pathlib import Path

from src.schema.chart_schema import ChartSpec
from src.schema.field_types import DataBlockResolver, FieldTypeResolver
from src.models.loader import load_model
from src.models.resolver import ModelResolver
from src.translator.patterns.single import compile_single
from src.translator.patterns.stacked import compile_stacked
from src.translator.facet import apply_facet

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"

VegaLiteSpec = dict[str, Any]


def translate_chart(
    spec: ChartSpec,
    models_dir: str | Path | None = None,
) -> VegaLiteSpec:
    """
    Compile a validated ChartSpec into a Vega-Lite spec dict.

    When spec.data is a string (model name), loads the model file and
    creates a ModelResolver. When spec.data is a DataSource object,
    uses the legacy DataBlockResolver.

    Args:
        spec: Validated ChartSpec.
        models_dir: Optional path to models directory. Defaults to
                    <project_root>/models/. Useful for tests with fixture models.

    Returns:
        A Vega-Lite spec dict (no data, no theme).
    """
    # Create the appropriate resolver
    if isinstance(spec.data, str):
        model = load_model(spec.data, models_dir=models_dir)
        resolver: FieldTypeResolver = ModelResolver(model)
    else:
        resolver = DataBlockResolver(spec.data)

    # Determine which compilation path to use
    rows_is_multi = isinstance(spec.rows, list)
    cols_is_multi = isinstance(spec.cols, list)

    if rows_is_multi or cols_is_multi:
        # Multi-measure: stacked panels (and/or layers in Phase 1a)
        inner = compile_stacked(spec, resolver)
    else:
        # Single-measure: simple chart
        inner = compile_single(spec, resolver)

    # Facet wrapping — applies uniformly to any inner spec shape
    top_level = apply_facet(inner, spec.facet)
    top_level["$schema"] = VEGA_LITE_SCHEMA

    return top_level
