"""
Charter — AI-Native Visual Analytics Platform

Public API:
    parse_chart(yaml_string)       → validated ChartSpec model
    translate_chart(spec)          → Vega-Lite dict (no data, no theme)
    merge_theme(vl_spec, theme)    → Vega-Lite dict with theme config applied
    bind_data(vl_spec, rows)       → Vega-Lite dict with data.values attached
    render_html(vl_spec)           → standalone HTML string with vegaEmbed
    compose_dashboard(path)        → end-to-end dashboard HTML from YAML

Typical pipeline:
    spec   = parse_chart(yaml_string)
    vl     = translate_chart(spec)
    themed = merge_theme(vl, theme)
    bound  = bind_data(themed, rows)
    html   = render_html(bound)
"""

from shelves.compose.dashboard import compose_dashboard
from shelves.data.bind import bind_data, resolve_data
from shelves.pipeline import compile_chart, resolve_model_data
from shelves.render.to_html import render_html
from shelves.schema.chart_schema import DSL_VERSION, ChartSpec, parse_chart
from shelves.schema.layout_schema import DashboardSpec, parse_dashboard
from shelves.theme.merge import load_theme, merge_theme
from shelves.translator.layout import translate_dashboard
from shelves.translator.translate import translate_chart

__all__ = [
    "DSL_VERSION",
    "ChartSpec",
    "DashboardSpec",
    "bind_data",
    "compile_chart",
    "compose_dashboard",
    "load_theme",
    "merge_theme",
    "parse_chart",
    "parse_dashboard",
    "render_html",
    "resolve_data",
    "resolve_model_data",
    "translate_chart",
    "translate_dashboard",
]
