"""
Charter — AI-Native Visual Analytics Platform

Public API:
    parse_chart(yaml_string)       → validated ChartSpec model
    translate_chart(spec)          → Vega-Lite dict (no data, no theme)
    merge_theme(vl_spec, theme)    → Vega-Lite dict with theme config applied
    bind_data(vl_spec, rows)       → Vega-Lite dict with data.values attached
    render_html(vl_spec)           → standalone HTML string with vegaEmbed

Typical pipeline:
    spec   = parse_chart(yaml_string)
    vl     = translate_chart(spec)
    themed = merge_theme(vl, theme)
    bound  = bind_data(themed, rows)
    html   = render_html(bound)
"""

from src.schema.chart_schema import parse_chart, ChartSpec, DSL_VERSION
from src.schema.layout_schema import parse_dashboard, DashboardSpec
from src.translator.translate import translate_chart
from src.translator.layout import translate_dashboard
from src.theme.merge import merge_theme, load_theme
from src.data.bind import bind_data, resolve_data
from src.render.to_html import render_html

__all__ = [
    "parse_chart",
    "parse_dashboard",
    "translate_chart",
    "translate_dashboard",
    "merge_theme",
    "load_theme",
    "bind_data",
    "resolve_data",
    "render_html",
    "ChartSpec",
    "DashboardSpec",
    "DSL_VERSION",
]
