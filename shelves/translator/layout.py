"""
Layout DSL → HTML Translator

Walks a validated DashboardSpec tree and produces a complete HTML page
using solver-computed fixed pixel layout (with inline-block for horizontal
flows) and optional vegaEmbed chart embedding.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
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
        # Gap-overflow is warned by the solver (the single owner of layout
        # invariants); by render time it has already shrunk children to fit, so
        # a renderer-side check would only duplicate that warning (KAN-295).
        if orientation == "horizontal":
            spacer = f'<div style="display: inline-block; width: {gap}px; height: 1px;"></div>'
        else:
            spacer = f'<div style="height: {gap}px;"></div>'
        return spacer.join(child_htmls)

    return "".join(child_htmls)


def _build_button_link_inner_css(defn: ButtonComponent | LinkComponent) -> str:
    """Build CSS for a button/link inner element (no padding — outer div handles it)."""
    from shelves.translator.layout_styles import (
        _STYLE_EXTRA_KEYS,
        BUTTON_DEFAULTS,
        LINK_DEFAULTS,
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


def _render_root(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    assert isinstance(node.component, RootComponent)
    inner = _render_children(node, node.component, ctx)
    return f'<div style="{safe_outer}">{inner}</div>'


def _render_container(
    node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str
) -> str:
    assert isinstance(node.component, ContainerComponent)
    inner_html = _render_children(node, node.component, ctx)
    return f'<div style="{safe_outer}"><div style="{safe_inner}">{inner_html}</div></div>'


def _render_sheet(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    defn = node.component
    sheet_name = node.name or ctx.next_auto_id()
    if defn.fit is not None:  # type: ignore[union-attr]
        ctx.sheet_fit_modes[sheet_name] = defn.fit  # type: ignore[union-attr]
    if not defn.show_title:  # type: ignore[union-attr]
        ctx.sheet_show_titles[sheet_name] = False
    ctx.sheet_content_dims[sheet_name] = (node.content_width, node.content_height)
    safe_name = html.escape(sheet_name, quote=True)
    return (
        f'<div style="{safe_outer}"><div id="sheet-{safe_name}" style="{safe_inner}"></div></div>'
    )


def _render_text(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    escaped_content = html.escape(node.component.content)  # type: ignore[union-attr]
    return f'<div style="{safe_outer}"><div style="{safe_inner}">{escaped_content}</div></div>'


def _render_button_link(
    node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str
) -> str:
    defn = node.component
    if defn.target != "_self":  # type: ignore[union-attr]
        rel = ' rel="noopener noreferrer"' if defn.target == "_blank" else ""  # type: ignore[union-attr]
        target_attr = f' target="{defn.target}"{rel}'  # type: ignore[union-attr]
    else:
        target_attr = ""
    escaped_text = html.escape(defn.text)  # type: ignore[union-attr]
    escaped_href = html.escape(defn.href, quote=True)  # type: ignore[union-attr]
    a_css = _build_button_link_inner_css(defn)  # type: ignore[arg-type]
    if defn.html:  # type: ignore[union-attr]
        if a_css and not a_css.endswith(";"):
            a_css += "; "
        a_css += defn.html  # type: ignore[union-attr]
    safe_a_css = html.escape(a_css, quote=True)
    return (
        f'<div style="{safe_outer}">'
        f'<a href="{escaped_href}"{target_attr} style="{safe_a_css}">{escaped_text}</a>'
        f"</div>"
    )


def _render_image(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    defn = node.component
    escaped_src = html.escape(defn.src, quote=True)  # type: ignore[union-attr]
    escaped_alt = html.escape(defn.alt, quote=True)  # type: ignore[union-attr]
    img_css = "width: 100%; height: 100%; object-fit: contain"
    inner_css = resolve_inner_styles(defn, ctx)
    if inner_css:
        img_css += "; " + inner_css
    if defn.html:  # type: ignore[union-attr]
        img_css += "; " + defn.html  # type: ignore[union-attr]
    safe_img_css = html.escape(img_css, quote=True)
    return (
        f'<div style="{safe_outer}">'
        f'<img src="{escaped_src}" alt="{escaped_alt}"'
        f' style="{safe_img_css}">'
        f"</div>"
    )


def _render_blank(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    return f'<div style="{safe_outer}"><div style="{safe_inner}"></div></div>'


_RENDERERS: dict[type, Callable[[ResolvedNode, RenderContext, str, str], str]] = {
    RootComponent: _render_root,
    ContainerComponent: _render_container,
    SheetComponent: _render_sheet,
    TextComponent: _render_text,
    ButtonComponent: _render_button_link,
    LinkComponent: _render_button_link,
    ImageComponent: _render_image,
    BlankComponent: _render_blank,
}


def render_node(
    node: ResolvedNode,
    ctx: RenderContext,
    parent_orientation: Literal["horizontal", "vertical"] | None = None,
) -> str:
    """Recursively render a ResolvedNode tree to HTML."""
    defn = node.component

    outer_css = resolve_styles(
        defn,
        node.name,
        ctx,
        parent_orientation=parent_orientation,
        resolved_width=node.outer_width,
        resolved_height=node.outer_height,
        has_wrapper=not isinstance(defn, RootComponent),
    )
    safe_outer = html.escape(outer_css, quote=True)

    inner_fit = defn.fit if isinstance(defn, SheetComponent) else None
    inner_css = (
        "" if isinstance(defn, RootComponent) else resolve_inner_styles(defn, ctx, fit=inner_fit)
    )
    safe_inner = html.escape(inner_css, quote=True)

    renderer = _RENDERERS.get(type(defn))
    if renderer is None:
        return ""
    return renderer(node, ctx, safe_outer, safe_inner)


def _is_compound_spec(spec: dict) -> bool:
    """Check if a Vega-Lite spec is compound (facet/concat/repeat).

    Compound specs don't support responsive container sizing — only
    single-view and layered specs do.
    """
    return any(k in spec for k in ("facet", "hconcat", "vconcat", "concat", "repeat"))


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
    fit_js = ""
    script_lines = []
    if chart_specs:
        # Serialize specs, applying fit modes and show_title
        specs_obj = {}
        # sheet id -> {width, height}: compound specs are sized in the browser.
        # The sizer measures real axis/title extents in the DOM and fits the spec
        # to this solved box — concat fully, facet/repeat width-only for now.
        fit_targets: dict[str, dict[str, int]] = {}
        for sheet_name, spec in chart_specs.items():
            modified_spec = dict(spec)
            fit = fit_modes.get(sheet_name)
            sheet_id = f"sheet-{sheet_name}"

            # show_title: false → null the title before any sizing.
            if show_titles.get(sheet_name) is False:
                modified_spec["title"] = None

            compound = _is_compound_spec(modified_spec)
            dims = content_dims.get(sheet_name)

            if compound and fit and dims:
                cw, ch = dims
                is_concat = "vconcat" in modified_spec or "hconcat" in modified_spec
                # Concat fits in any direction; facet/repeat are width-only (height
                # is data-dependent — full browser-side facet fit is KAN-294).
                if is_concat or fit in ("width", "fill"):
                    fit_targets[sheet_id] = {"width": cw, "height": ch}
            elif not compound:
                uses_container = False
                if fit in ("width", "fill"):
                    modified_spec["width"] = "container"
                    uses_container = True
                if fit in ("height", "fill"):
                    modified_spec["height"] = "container"
                    uses_container = True
                if uses_container:
                    modified_spec["autosize"] = {"type": "fit"}

            # Zero out Vega's intrinsic padding and background — the CSS outer
            # wrapper handles spacing and background colour instead.
            existing_cfg = modified_spec.get("config")
            cfg = dict(existing_cfg) if existing_cfg is not None else {}
            modified_spec["config"] = cfg
            cfg["padding"] = 0
            cfg["background"] = "transparent"

            specs_obj[sheet_id] = modified_spec

        specs_json = json.dumps(specs_obj, indent=2).replace("</", r"<\/")
        script_lines.append(f"    const specs = {specs_json};")

        if fit_targets:
            # Compound concat sheets need the browser sizer: inline it and route
            # those ids through compoundFit.fit; everything else stays a plain embed.
            from shelves.render.to_html import load_compound_fit_js

            fit_js = load_compound_fit_js()
            fit_json = json.dumps(fit_targets).replace("</", r"<\/")
            script_lines.append(f"    const fitTargets = {fit_json};")
            script_lines.append("    Object.entries(specs).forEach(([id, spec]) => {")
            script_lines.append("      const box = fitTargets[id];")
            script_lines.append("      if (box && window.compoundFit) {")
            script_lines.append("        compoundFit.fit(`#${id}`, spec, box, { actions: false });")
            script_lines.append("      } else {")
            script_lines.append(
                "        vegaEmbed(`#${id}`, spec, { actions: false }).catch(console.error);"
            )
            script_lines.append("      }")
            script_lines.append("    });")
        else:
            script_lines.append("    Object.entries(specs).forEach(([id, spec]) => {")
            script_lines.append(
                "      vegaEmbed(`#${id}`, spec, { actions: false }).catch(console.error);"
            )
            script_lines.append("    });")

    script_block = "\n".join(script_lines)
    fit_block = f"  <script>\n{fit_js}\n  </script>\n" if fit_js else ""

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
{fit_block}  <script>
{script_block}
  </script>
</body>
</html>"""
