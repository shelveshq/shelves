"""KPI / Big Number Pattern Compiler

Typography tokens are injected via the ``kpi_tokens`` parameter — this module
imports nothing from ``shelves.theme``.
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import ChartSpec, KPIComparison
from shelves.schema.field_types import FieldTypeResolver
from shelves.translator.filters import build_transforms

VegaLiteSpec = dict[str, Any]


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


def _comparison_text_expr(fmt: str, label: str | None) -> str:
    """Build a null-guarded Vega-Lite calculate expression for delta comparison text."""
    label_suffix = f" + '  {label}'" if label else ""
    inner = f"datum.indicator + ' ' + format(abs(datum.delta), '{fmt}'){label_suffix}"
    return f"datum.delta != null ? {inner} : null"


def _build_comparison(
    value_field: str,
    comp: KPIComparison,
    kpi_format: str,
    theme_kpi: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build Vega-Lite calculate transforms and comparison text mark row."""
    semantic = theme_kpi["semantic"]
    transforms: list[dict[str, Any]] = []

    if comp.mode == "delta_percent":
        fmt = comp.format or ".1%"
        transforms = [
            {
                "calculate": (
                    f"abs(datum.{comp.field}) > 0"
                    f" ? (datum.{value_field} - datum.{comp.field})"
                    f" / abs(datum.{comp.field})"
                    f" : null"
                ),
                "as": "delta",
            },
            {
                "calculate": ("datum.delta != null ? (datum.delta >= 0 ? '▲' : '▼') : null"),
                "as": "indicator",
            },
            {
                "calculate": _comparison_text_expr(fmt, comp.label),
                "as": "comparison_text",
            },
        ]

    elif comp.mode == "delta_absolute":
        fmt = comp.format or kpi_format
        transforms = [
            {
                "calculate": (
                    f"datum.{comp.field} != null ? datum.{value_field} - datum.{comp.field} : null"
                ),
                "as": "delta",
            },
            {
                "calculate": ("datum.delta != null ? (datum.delta >= 0 ? '▲' : '▼') : null"),
                "as": "indicator",
            },
            {
                "calculate": _comparison_text_expr(fmt, comp.label),
                "as": "comparison_text",
            },
        ]

    elif comp.mode == "value":
        fmt = comp.format or kpi_format
        label_suffix = f" + '  {comp.label}'" if comp.label else ""
        inner = f"format(datum.{comp.field}, '{fmt}'){label_suffix}"
        transforms = [
            {
                "calculate": f"datum.{comp.field} != null ? {inner} : null",
                "as": "comparison_text",
            },
        ]

    if comp.polarity == "neutral" or comp.mode == "value":
        color_enc: dict[str, Any] = {"value": semantic["neutral"]}
    elif comp.polarity == "down_is_good":
        color_enc = {
            "condition": {"test": "datum.delta <= 0", "value": semantic["positive"]},
            "value": semantic["negative"],
        }
    else:
        color_enc = {
            "condition": {"test": "datum.delta >= 0", "value": semantic["positive"]},
            "value": semantic["negative"],
        }

    comp_row = _text_mark(
        {"field": "comparison_text", "type": "nominal"},
        font_size=theme_kpi["comparison"]["fontSize"],
        font_weight=theme_kpi["comparison"]["fontWeight"],
        color=None,
    )
    comp_row["encoding"]["color"] = color_enc

    return transforms, comp_row


def compile_kpi(
    spec: ChartSpec,
    resolver: FieldTypeResolver,
    kpi_tokens: dict[str, Any],
) -> VegaLiteSpec:
    kpi = spec.kpi
    assert kpi is not None, "compile_kpi requires spec.kpi (routed by translate_chart)"

    if not resolver.is_measure(kpi.value):
        raise ValueError(
            f"kpi.value {kpi.value!r} is not a measure in the data model for spec {spec.sheet!r}."
        )

    if kpi.comparison is not None and not resolver.is_measure(kpi.comparison.field):
        raise ValueError(
            f"kpi.comparison.field {kpi.comparison.field!r} is not a measure"
            f" in the data model for spec {spec.sheet!r}."
        )

    title_text = kpi.title or spec.sheet
    spacing = kpi.spacing if kpi.spacing is not None else kpi_tokens["spacing"]

    title_row = _text_mark(
        {"value": title_text},
        font_size=kpi_tokens["title"]["fontSize"],
        font_weight=kpi_tokens["title"]["fontWeight"],
        color=kpi_tokens["title"]["color"],
    )
    value_row = _text_mark(
        {"field": kpi.value, "type": "quantitative", "format": kpi.format},
        font_size=kpi_tokens["value"]["fontSize"],
        font_weight=kpi_tokens["value"]["fontWeight"],
        color=kpi_tokens["value"]["color"],
    )

    rows = [title_row, value_row]
    comp_transforms: list[dict[str, Any]] = []

    if kpi.comparison is not None:
        comp_transforms, comp_row = _build_comparison(
            kpi.value, kpi.comparison, kpi.format, kpi_tokens
        )
        rows.append(comp_row)

    result: VegaLiteSpec = {
        "vconcat": rows,
        "spacing": spacing,
        "config": {"view": {"stroke": None}, "concat": {"spacing": spacing}},
    }

    filter_transforms = build_transforms(spec.filters, resolver)
    all_transforms = filter_transforms + comp_transforms
    if all_transforms:
        result["transform"] = all_transforms

    return result
