"""
Layout DSL → HTML Translator

Walks a validated DashboardSpec tree and produces a complete HTML page
with CSS flexbox layout and optional vegaEmbed chart embedding.
"""

from __future__ import annotations

import html
import json
from typing import Any, Literal

from src.schema.layout_schema import (
    Canvas,
    DashboardSpec,
    resolve_child,
)
from src.theme.theme_schema import ThemeSpec
from src.translator.layout_styles import RenderContext, resolve_styles


def translate_dashboard(
    dashboard: DashboardSpec,
    theme: ThemeSpec,
    chart_specs: dict[str, dict] | None = None,
) -> str:
    """Translate a DashboardSpec to a complete HTML page."""
    components = dashboard.components or {}
    styles = dashboard.styles or {}

    ctx = RenderContext(components=components, styles=styles, theme=theme)

    body_html = render_node(dashboard.root, ctx, parent_orientation=None)

    return wrap_html_page(
        dashboard_name=dashboard.dashboard,
        body_html=body_html,
        chart_specs=chart_specs or {},
        theme=theme,
        canvas=dashboard.canvas,
        sheet_fit_modes=ctx.sheet_fit_modes,
    )


def render_node(
    node: Any,
    ctx: RenderContext,
    parent_orientation: Literal["horizontal", "vertical"] | None,
) -> str:
    """Recursively render a component tree node to HTML."""
    # Resolve node to (name, component)
    comp_type = getattr(node, "type", None)

    if comp_type == "root":
        name = None
        defn = node
    else:
        name, defn = resolve_child(node, ctx.components)
        comp_type = getattr(defn, "type", None)

    # Resolve CSS styles
    css = resolve_styles(defn, name, ctx, parent_orientation)

    # Root canvas dimensions are injected by wrap_html_page

    # Dispatch on type
    if comp_type in ("root", "container"):
        orientation = getattr(defn, "orientation", "vertical")
        children = getattr(defn, "contains", [])
        inner = "".join(render_node(c, ctx, orientation) for c in children)
        return f'<div style="{css}">{inner}</div>'

    elif comp_type == "sheet":
        sheet_name = name or ctx.next_auto_id()
        fit = getattr(defn, "fit", None)
        if fit is not None:
            ctx.sheet_fit_modes[sheet_name] = fit
        return f'<div id="sheet-{sheet_name}" style="{css}"></div>'

    elif comp_type == "text":
        escaped_content = html.escape(defn.content)
        return f'<div style="{css}">{escaped_content}</div>'

    elif comp_type in ("navigation", "navigation_button", "navigation_link"):
        target_attr = f' target="{defn.target}"' if defn.target != "_self" else ""
        escaped_text = html.escape(defn.text)
        escaped_link = html.escape(defn.link, quote=True)
        return f'<a href="{escaped_link}"{target_attr} style="{css}">{escaped_text}</a>'

    elif comp_type == "image":
        escaped_src = html.escape(defn.src, quote=True)
        escaped_alt = html.escape(defn.alt, quote=True)
        img_css = css
        if "object-fit" not in img_css:
            if img_css:
                img_css += "; object-fit: contain"
            else:
                img_css = "object-fit: contain"
        return f'<img src="{escaped_src}" alt="{escaped_alt}" style="{img_css}">'

    elif comp_type == "blank":
        return f'<div style="{css}"></div>'

    return ""


def wrap_html_page(
    dashboard_name: str,
    body_html: str,
    chart_specs: dict[str, dict],
    theme: ThemeSpec,
    canvas: Canvas,
    sheet_fit_modes: dict[str, str] | None = None,
) -> str:
    """Wrap rendered component tree in a full HTML page."""
    fit_modes = sheet_fit_modes or {}
    body_font = theme.layout.font.family.body

    # Inject canvas dimensions into the root div
    # The first <div in body_html is the root — inject width/height
    root_style_inject = f"width: {canvas.width}px; height: {canvas.height}px; "
    if body_html.startswith('<div style="'):
        body_html = body_html.replace('<div style="', f'<div style="{root_style_inject}', 1)

    # Build vegaEmbed script
    script_lines = []
    if chart_specs:
        # Serialize specs, applying fit modes
        specs_obj = {}
        for sheet_name, spec in chart_specs.items():
            modified_spec = dict(spec)
            fit = fit_modes.get(sheet_name)
            if fit in ("width", "fill"):
                modified_spec["width"] = "container"
            if fit in ("height", "fill"):
                modified_spec["height"] = "container"
            specs_obj[f"sheet-{sheet_name}"] = modified_spec

        specs_json = json.dumps(specs_obj, indent=2)
        script_lines.append(f"    const specs = {specs_json};")
        script_lines.append("    Object.entries(specs).forEach(([id, spec]) => {")
        script_lines.append(
            "      vegaEmbed(`#${id}`, spec, { actions: false }).catch(console.error);"
        )
        script_lines.append("    });")

    script_block = "\n".join(script_lines)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(dashboard_name)}</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@6"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: {body_font}; }}
    img {{ display: block; object-fit: contain; }}
  </style>
</head>
<body>
  {body_html}
  <script>
{script_block}
  </script>
</body>
</html>"""
