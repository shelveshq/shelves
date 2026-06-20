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

from collections.abc import Callable
from pathlib import Path
from typing import Any

from shelves.models.loader import load_model
from shelves.models.resolver import ModelResolver
from shelves.schema.chart_schema import ChartSpec
from shelves.schema.field_types import FieldTypeResolver
from shelves.translator.facet import apply_facet
from shelves.translator.patterns.kpi import compile_kpi
from shelves.translator.patterns.single import compile_single
from shelves.translator.patterns.stacked import compile_stacked

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"

VegaLiteSpec = dict[str, Any]

_PatternEntry = tuple[
    Callable[[ChartSpec], bool],
    Callable[[ChartSpec, FieldTypeResolver], dict],
]


def _is_multi_measure(spec: ChartSpec) -> bool:
    return isinstance(spec.rows, list) or isinstance(spec.cols, list)


def _is_single_measure(spec: ChartSpec) -> bool:
    return not _is_multi_measure(spec)


PATTERN_COMPILERS: list[_PatternEntry] = [
    (_is_multi_measure, compile_stacked),
    (_is_single_measure, compile_single),
]


def translate_chart(
    spec: ChartSpec,
    models_dir: str | Path | None = None,
    resolver: FieldTypeResolver | None = None,
    kpi_tokens: dict | None = None,
) -> VegaLiteSpec:
    """Compile a validated ChartSpec into a Vega-Lite spec dict.

    kpi_tokens: the ``kpi`` theme token dict, injected by the caller (the
    pipeline passes the loaded theme's tokens so custom themes are honored).
    When None and the spec is a KPI, the built-in default tokens are loaded
    lazily.
    """
    if resolver is None:
        model = load_model(spec.data, models_dir=models_dir)
        resolver = ModelResolver(model)

    if spec.kpi is not None:
        if kpi_tokens is None:
            from shelves.theme.kpi_tokens import load_kpi_tokens

            kpi_tokens = load_kpi_tokens()
        top_level = compile_kpi(spec, resolver, kpi_tokens)
        top_level["$schema"] = VEGA_LITE_SCHEMA
        return top_level

    inner = None
    for predicate, compiler in PATTERN_COMPILERS:
        if predicate(spec):
            inner = compiler(spec, resolver)
            break

    if inner is None:
        raise ValueError("No pattern compiler matched the spec")

    label_intents = inner.pop("_label_intents", [])

    top_level = apply_facet(inner, spec.facet)
    top_level["$schema"] = VEGA_LITE_SCHEMA

    if label_intents:
        top_level["usermeta"] = {"shelves": {"labels": label_intents}}

    if spec.description:
        top_level["title"] = {"text": spec.sheet, "subtitle": spec.description}
    else:
        top_level["title"] = spec.sheet

    return top_level
