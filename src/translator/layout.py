"""
Layout DSL → HTML Translator

Walks a validated DashboardSpec tree and produces a complete HTML page
using solver-computed fixed pixel layout (with inline-block for horizontal
flows) and optional vegaEmbed chart embedding.
"""

from __future__ import annotations

import html
import json
from typing import Literal

from src.schema.layout_schema import (
    BlankComponent,
    ButtonComponent,
    Canvas,
    ContainerComponent,
    DashboardSpec,
    ImageComponent,
    LinkComponent,
    RootComponent,
    SheetComponent,
    TextComponent,
)
from src.theme.theme_schema import ThemeSpec
from src.translator.layout_flatten import flatten_dashboard
from src.translator.layout_solver import ResolvedNode, parse_spacing, solve_layout
from src.translator.layout_styles import RenderContext, resolve_styles


def translate_dashboard(
    dashboard: DashboardSpec,
    theme: ThemeSpec,
    chart_specs: dict[str, dict] | None = None,
) -> str:
    """Translate a DashboardSpec to a complete HTML page."""
    ctx = RenderContext(theme=theme)

    # Flatten first: resolve all style refs and component refs
    flat_tree = flatten_dashboard(dashboard)

    # Solve layout to get concrete pixel dimensions
    resolved_tree = solve_layout(flat_tree)

    body_html = render_node(resolved_tree, ctx)

    return wrap_html_page(
        dashboard_name=dashboard.dashboard,
        body_html=body_html,
        chart_specs=chart_specs or {},
        theme=theme,
        canvas=dashboard.canvas,
        sheet_fit_modes=ctx.sheet_fit_modes,
        sheet_show_titles=ctx.sheet_show_titles,
        sheet_content_dims=ctx.sheet_content_dims,
        sheet_padding=ctx.sheet_padding,
    )


def _get_orientation(defn: RootComponent | ContainerComponent) -> Literal["horizontal", "vertical"]:
    """Get orientation from a container or root component."""
    if isinstance(defn, RootComponent):
        return defn.orientation
    return defn.type


def render_node(
    node: ResolvedNode,
    ctx: RenderContext,
    parent_orientation: Literal["horizontal", "vertical"] | None = None,
) -> str:
    """Recursively render a ResolvedNode tree to HTML."""
    defn = node.component
    name = node.name

    # Resolve CSS styles with solver-computed dimensions
    css = resolve_styles(
        defn,
        name,
        ctx,
        parent_orientation=parent_orientation,
        resolved_width=node.outer_width,
        resolved_height=node.outer_height,
    )

    safe_css = html.escape(css, quote=True)

    # Dispatch on type
    if isinstance(defn, (ContainerComponent, RootComponent)):
        orientation = _get_orientation(defn)
        gap = defn.gap or 0
        child_htmls = [render_node(c, ctx, parent_orientation=orientation) for c in node.children]

        if gap and len(child_htmls) > 1:
            # Verify gap fits: children + gaps must not exceed content area
            if orientation == "horizontal":
                children_total = sum(c.outer_width for c in node.children)
                available = node.content_width
            else:
                children_total = sum(c.outer_height for c in node.children)
                available = node.content_height
            total_gap = gap * (len(child_htmls) - 1)

            if children_total + total_gap > available:
                import warnings

                warnings.warn(
                    f"Gap of {gap}px ({total_gap}px total) does not fit in container "
                    f"'{node.name or 'root'}': children use {children_total}px, "
                    f"content area is {available}px",
                    stacklevel=2,
                )

            if orientation == "horizontal":
                spacer = f'<div style="display: inline-block; width: {gap}px; height: 1px;"></div>'
            else:
                spacer = f'<div style="height: {gap}px;"></div>'
            inner = spacer.join(child_htmls)
        else:
            inner = "".join(child_htmls)

        return f'<div style="{safe_css}">{inner}</div>'

    elif isinstance(defn, SheetComponent):
        sheet_name = name or ctx.next_auto_id()
        if defn.fit is not None:
            ctx.sheet_fit_modes[sheet_name] = defn.fit
        if not defn.show_title:
            ctx.sheet_show_titles[sheet_name] = False
        ctx.sheet_content_dims[sheet_name] = (node.content_width, node.content_height)
        if defn.padding is not None and defn.fit is not None:
            top, right, bottom, left = parse_spacing(defn.padding)
            if top == right == bottom == left:
                ctx.sheet_padding[sheet_name] = top
            else:
                ctx.sheet_padding[sheet_name] = {
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "left": left,
                }
        safe_name = html.escape(sheet_name, quote=True)
        return f'<div id="sheet-{safe_name}" style="{safe_css}"></div>'

    elif isinstance(defn, TextComponent):
        escaped_content = html.escape(defn.content)
        return f'<div style="{safe_css}">{escaped_content}</div>'

    elif isinstance(defn, (ButtonComponent, LinkComponent)):
        target_attr = f' target="{defn.target}"' if defn.target != "_self" else ""
        escaped_text = html.escape(defn.text)
        escaped_href = html.escape(defn.href, quote=True)
        return f'<a href="{escaped_href}"{target_attr} style="{safe_css}">{escaped_text}</a>'

    elif isinstance(defn, ImageComponent):
        escaped_src = html.escape(defn.src, quote=True)
        escaped_alt = html.escape(defn.alt, quote=True)
        img_css = css
        if "object-fit" not in img_css:
            if img_css:
                img_css += "; object-fit: contain"
            else:
                img_css = "object-fit: contain"
        safe_img_css = html.escape(img_css, quote=True)
        return f'<img src="{escaped_src}" alt="{escaped_alt}" style="{safe_img_css}">'

    elif isinstance(defn, BlankComponent):
        return f'<div style="{safe_css}"></div>'

    return ""


def _is_compound_spec(spec: dict) -> bool:
    """Check if a Vega-Lite spec is compound (facet/concat/repeat).

    Compound specs don't support responsive container sizing — only
    single-view and layered specs do.
    """
    return any(k in spec for k in ("facet", "hconcat", "vconcat", "concat", "repeat"))


# Vega-Lite's default gap between facet cells.
_VL_FACET_SPACING_DEFAULT = 20


def _fit_compound_width(spec: dict, container_width: int, padding: int | dict[str, int]) -> None:
    """Hot-fix: calculate per-cell width for faceted specs so the chart
    fits horizontally in its container.

    Vega-Lite compound specs don't support width:"container".  For faceted
    specs we know `columns` at compile time, so we can derive the per-cell
    width.  Height is left to Vega's default because the number of rows
    depends on the data (unknown at layout time).

    TODO: revisit with a proper facet sizing strategy.
    """
    columns = spec.get("columns", 1)
    spacing = _VL_FACET_SPACING_DEFAULT
    # Check for user-specified spacing in config
    cfg = spec.get("config", {})
    facet_cfg = cfg.get("facet", {})
    if isinstance(facet_cfg.get("spacing"), (int, float)):
        spacing = facet_cfg["spacing"]

    if isinstance(padding, dict):
        h_pad = padding.get("left", 0) + padding.get("right", 0)
    else:
        h_pad = int(padding) * 2
    available = container_width - h_pad
    cell_width = max(1, (available - spacing * (columns - 1)) // columns)

    # Set width on the inner spec (cell-level), not top-level
    if "spec" in spec:
        inner = dict(spec["spec"])
        inner["width"] = cell_width
        spec["spec"] = inner
    else:
        # Non-facet compound (concat/repeat) — best-effort top-level
        spec["width"] = cell_width


def wrap_html_page(
    dashboard_name: str,
    body_html: str,
    chart_specs: dict[str, dict],
    theme: ThemeSpec,
    canvas: Canvas,
    sheet_fit_modes: dict[str, str] | None = None,
    sheet_show_titles: dict[str, bool] | None = None,
    sheet_content_dims: dict[str, tuple[int, int]] | None = None,
    sheet_padding: dict[str, int | dict[str, int]] | None = None,
) -> str:
    """Wrap rendered component tree in a full HTML page."""
    fit_modes = sheet_fit_modes or {}
    show_titles = sheet_show_titles or {}
    content_dims = sheet_content_dims or {}
    pad_values = sheet_padding or {}
    body_font = theme.layout.font.family.body

    # Build vegaEmbed script
    script_lines = []
    if chart_specs:
        # Serialize specs, applying fit modes and show_title
        specs_obj = {}
        for sheet_name, spec in chart_specs.items():
            modified_spec = dict(spec)
            fit = fit_modes.get(sheet_name)

            if fit is not None:
                # Transfer the sheet's padding to the Vega spec so
                # autosize:{contains:"padding"} can absorb it.  CSS
                # padding is suppressed on fitted sheets (it would shift
                # the SVG without Vega knowing).  Also strip any theme
                # config.padding so it doesn't conflict.
                sheet_pad = pad_values.get(sheet_name, 0)
                modified_spec["padding"] = sheet_pad
                if "config" in modified_spec:
                    config = dict(modified_spec["config"])
                    config.pop("padding", None)
                    modified_spec["config"] = config

            compound = _is_compound_spec(modified_spec)
            dims = content_dims.get(sheet_name)

            if compound and fit and dims:
                # Hot-fix: compound specs don't support width:"container".
                # Fit width by calculating per-cell size from columns.
                # Height is left to Vega (row count is data-dependent).
                # TODO: revisit with a proper facet sizing strategy.
                cw, _ch = dims
                raw_pad = modified_spec.get("padding", 0)
                # Extract horizontal padding for width calculation
                if isinstance(raw_pad, dict):
                    h_pad = raw_pad.get("left", 0) + raw_pad.get("right", 0)
                else:
                    h_pad = int(raw_pad) * 2
                # CSS padding is suppressed for fitted sheets, so Vega
                # fills the full outer dims.  Reconstruct outer from
                # content + padding (solver subtracted it).
                outer_w = cw + h_pad
                if fit in ("width", "fill"):
                    _fit_compound_width(modified_spec, outer_w, raw_pad)
            else:
                uses_container = False
                if fit in ("width", "fill"):
                    modified_spec["width"] = "container"
                    uses_container = True
                if fit in ("height", "fill"):
                    modified_spec["height"] = "container"
                    uses_container = True
                if uses_container:
                    modified_spec["autosize"] = {
                        "type": "fit",
                        "contains": "padding",
                    }

            # show_title: false → null out the title
            if show_titles.get(sheet_name) is False:
                modified_spec["title"] = None
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
