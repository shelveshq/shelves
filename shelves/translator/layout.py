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

from shelves.schema.layout_schema import (
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
from shelves.theme.theme_schema import ThemeSpec
from shelves.translator.layout_flatten import flatten_dashboard
from shelves.translator.layout_solver import ResolvedNode, solve_layout
from shelves.translator.layout_styles import RenderContext, resolve_inner_styles, resolve_styles


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
    )


def _get_orientation(defn: RootComponent | ContainerComponent) -> Literal["horizontal", "vertical"]:
    """Get orientation from a container or root component."""
    if isinstance(defn, RootComponent):
        return defn.orientation
    return defn.type


def _render_children(
    node: ResolvedNode,
    defn: ContainerComponent | RootComponent,
    ctx: RenderContext,
) -> str:
    """Render container children HTML string."""
    orientation = _get_orientation(defn)
    gap = defn.gap or 0
    child_htmls = [render_node(c, ctx, parent_orientation=orientation) for c in node.children]

    if gap and len(child_htmls) > 1:
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
        return spacer.join(child_htmls)

    return "".join(child_htmls)


def _build_button_link_inner_css(defn: ButtonComponent | LinkComponent) -> str:
    """Build CSS for a button/link inner element (no padding — outer div handles it)."""
    from shelves.translator.layout_styles import (
        BUTTON_DEFAULTS,
        LINK_DEFAULTS,
        _STYLE_EXTRA_KEYS,
        _css_prop_name,
    )

    defaults = dict(BUTTON_DEFAULTS if isinstance(defn, ButtonComponent) else LINK_DEFAULTS)
    defaults.pop("padding", None)

    extras = defn.__pydantic_extra__ or {}
    for key, val in extras.items():
        if key in _STYLE_EXTRA_KEYS and val is not None:
            css_name = _css_prop_name(key)
            if css_name == "shadow":
                defaults["box-shadow"] = str(val)
            else:
                defaults[css_name] = str(val)

    return "; ".join(f"{k}: {v}" for k, v in defaults.items())


def render_node(
    node: ResolvedNode,
    ctx: RenderContext,
    parent_orientation: Literal["horizontal", "vertical"] | None = None,
) -> str:
    """Recursively render a ResolvedNode tree to HTML.

    Every non-root component uses a div-in-div structure: an outer div owns
    dimensions, padding, overflow, and box-sizing; an inner div (or inner
    element) holds the content at width:100%/height:100%.

    Root components use a single div (they have no parent layout concerns).
    """
    defn = node.component
    name = node.name

    outer_css = resolve_styles(
        defn,
        name,
        ctx,
        parent_orientation=parent_orientation,
        resolved_width=node.outer_width,
        resolved_height=node.outer_height,
        has_wrapper=not isinstance(defn, RootComponent),
    )
    safe_outer = html.escape(outer_css, quote=True)

    # Root: single div containing all children
    if isinstance(defn, RootComponent):
        inner = _render_children(node, defn, ctx)
        return f'<div style="{safe_outer}">{inner}</div>'

    # All other components: div-in-div
    inner_css = resolve_inner_styles(defn, ctx)
    safe_inner = html.escape(inner_css, quote=True)

    if isinstance(defn, ContainerComponent):
        inner_html = _render_children(node, defn, ctx)
        return f'<div style="{safe_outer}"><div style="{safe_inner}">{inner_html}</div></div>'

    elif isinstance(defn, SheetComponent):
        sheet_name = name or ctx.next_auto_id()
        if defn.fit is not None:
            ctx.sheet_fit_modes[sheet_name] = defn.fit
        if not defn.show_title:
            ctx.sheet_show_titles[sheet_name] = False
        ctx.sheet_content_dims[sheet_name] = (node.content_width, node.content_height)
        safe_name = html.escape(sheet_name, quote=True)
        return (
            f'<div style="{safe_outer}">'
            f'<div id="sheet-{safe_name}" style="{safe_inner}"></div>'
            f"</div>"
        )

    elif isinstance(defn, TextComponent):
        escaped_content = html.escape(defn.content)
        return f'<div style="{safe_outer}"><div style="{safe_inner}">{escaped_content}</div></div>'

    elif isinstance(defn, (ButtonComponent, LinkComponent)):
        target_attr = f' target="{defn.target}"' if defn.target != "_self" else ""
        escaped_text = html.escape(defn.text)
        escaped_href = html.escape(defn.href, quote=True)
        a_css = _build_button_link_inner_css(defn)
        safe_a_css = html.escape(a_css, quote=True)
        return (
            f'<div style="{safe_outer}">'
            f'<a href="{escaped_href}"{target_attr} style="{safe_a_css}">{escaped_text}</a>'
            f"</div>"
        )

    elif isinstance(defn, ImageComponent):
        escaped_src = html.escape(defn.src, quote=True)
        escaped_alt = html.escape(defn.alt, quote=True)
        return (
            f'<div style="{safe_outer}">'
            f'<img src="{escaped_src}" alt="{escaped_alt}"'
            f' style="width: 100%; height: 100%; object-fit: contain">'
            f"</div>"
        )

    elif isinstance(defn, BlankComponent):
        return f'<div style="{safe_outer}"><div style="{safe_inner}"></div></div>'

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
) -> str:
    """Wrap rendered component tree in a full HTML page."""
    fit_modes = sheet_fit_modes or {}
    show_titles = sheet_show_titles or {}
    content_dims = sheet_content_dims or {}
    body_font = theme.layout.font.family.body

    # Build vegaEmbed script
    script_lines = []
    if chart_specs:
        # Serialize specs, applying fit modes and show_title
        specs_obj = {}
        for sheet_name, spec in chart_specs.items():
            modified_spec = dict(spec)
            fit = fit_modes.get(sheet_name)

            compound = _is_compound_spec(modified_spec)
            dims = content_dims.get(sheet_name)

            if compound and fit and dims:
                # Hot-fix: compound specs don't support width:"container".
                # content_dims already has padding subtracted by the solver,
                # so pass padding=0.
                cw, _ch = dims
                if fit in ("width", "fill"):
                    _fit_compound_width(modified_spec, cw, 0)
            else:
                uses_container = False
                if fit in ("width", "fill"):
                    modified_spec["width"] = "container"
                    uses_container = True
                if fit in ("height", "fill"):
                    modified_spec["height"] = "container"
                    uses_container = True
                if uses_container:
                    modified_spec["autosize"] = {"type": "fit"}

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
