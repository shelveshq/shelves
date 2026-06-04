"""KPI / Big Number Pattern Compiler"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import ChartSpec
from shelves.schema.field_types import FieldTypeResolver
from shelves.theme.merge import load_theme
from shelves.translator.filters import build_transforms

VegaLiteSpec = dict[str, Any]


def _load_kpi_theme() -> dict[str, Any]:
    theme = load_theme()
    return theme.chart.kpi


def _text_mark(text_enc: dict, *, font_size, font_weight, color: str | None) -> dict:
    mark: dict[str, Any] = {
        "type": "text",
        "fontSize": font_size,
        "fontWeight": font_weight,
        "align": "left",
        "baseline": "middle",
    }
    if color is not None:
        mark["color"] = color
    return {
        "mark": mark,
        "encoding": {"text": text_enc, "x": {"value": 0}},
        "height": 1,
    }


def compile_kpi(spec: ChartSpec, resolver: FieldTypeResolver) -> VegaLiteSpec:
    kpi = spec.kpi
    assert kpi is not None, "compile_kpi requires spec.kpi (routed by translate_chart)"

    if kpi.comparison is not None:
        raise NotImplementedError(
            "KPI comparison rendering is not yet implemented (KAN-260). "
            "Remove the `comparison` block to render a simple KPI."
        )

    if not resolver.is_measure(kpi.value):
        raise ValueError(
            f"kpi.value {kpi.value!r} is not a measure in the data model for spec {spec.sheet!r}."
        )

    theme_kpi = _load_kpi_theme()
    title_text = kpi.title or spec.sheet
    spacing = kpi.spacing if kpi.spacing is not None else theme_kpi["spacing"]

    title_row = _text_mark(
        {"value": title_text},
        font_size=theme_kpi["title"]["fontSize"],
        font_weight=theme_kpi["title"]["fontWeight"],
        color=theme_kpi["title"]["color"],
    )
    value_row = _text_mark(
        {"field": kpi.value, "type": "quantitative", "format": kpi.format},
        font_size=theme_kpi["value"]["fontSize"],
        font_weight=theme_kpi["value"]["fontWeight"],
        color=theme_kpi["value"]["color"],
    )

    result: VegaLiteSpec = {
        "vconcat": [title_row, value_row],
        "spacing": spacing,
        "config": {"view": {"stroke": None}, "concat": {"spacing": spacing}},
    }

    filter_transforms = build_transforms(spec.filters, resolver)
    if filter_transforms:
        result["transform"] = filter_transforms

    return result
