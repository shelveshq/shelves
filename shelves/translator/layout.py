"""
Layout DSL → HTML Translator

Walks a validated DashboardSpec tree and produces a complete HTML page
using solver-computed fixed pixel layout (with inline-block for horizontal
flows) and optional vegaEmbed chart embedding.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from typing import Literal

from shelves.schema.layout_schema import (
    BlankComponent,
    ButtonComponent,
    Canvas,
    ContainerComponent,
    DashboardSpec,
    ImageComponent,
    LegendComponent,
    LinkComponent,
    RootComponent,
    SheetComponent,
    TextComponent,
)
from shelves.theme.theme_schema import ThemeSpec
from shelves.translator.layout_flatten import FlatNode, flatten_dashboard
from shelves.translator.layout_solver import ResolvedNode, solve_layout
from shelves.translator.layout_styles import (
    LegendLink,
    RenderContext,
    resolve_inner_styles,
    resolve_styles,
)

# Block holder that carries the ellipsis clipping for text (KAN-295).  Kept off
# the flex-centering inner div because text-overflow:ellipsis is inert on a flex
# container.  Static, escape-safe CSS.
_TEXT_HOLDER_STYLE = "overflow: hidden; text-overflow: ellipsis; white-space: nowrap"


def translate_dashboard(
    dashboard: DashboardSpec,
    theme: ThemeSpec,
    chart_specs: dict[str, dict] | None = None,
    asset_url_prefix: str = "assets/",
    legend_links: dict[tuple[str, str], LegendLink] | None = None,
    flat_tree: FlatNode | None = None,
) -> str:
    """Translate a DashboardSpec to a complete HTML page.

    `asset_url_prefix` is prepended to relative image srcs so dashboards can
    reference images relative to the assets directory (e.g. `image: png/x.png`).
    Studio/dev serve assets at `/assets`, so they pass `"assets/"`; the render
    CLI passes a path computed relative to the output HTML's location.

    `legend_links` maps (legend.source, legend.field) → resolved LegendLink and
    is built by compose_dashboard (SHE-10). Empty for direct-translate callers.

    `flat_tree` lets a caller pass an already-flattened layout tree (compose
    flattens once and reuses it for sheet/legend discovery); when None the tree
    is flattened here.
    """
    ctx = RenderContext(
        theme=theme,
        asset_url_prefix=asset_url_prefix,
        legend_links=legend_links or {},
    )

    # Flatten first (unless a caller already did): resolve style + component refs
    if flat_tree is None:
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
        has_legends=bool(ctx.legend_links),
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
    # SHE-29: the id is assigned once at flatten time and carried on the node;
    # the renderer never re-derives it. flatten_dashboard guarantees a sheet
    # node has a dom_id.
    assert node.dom_id is not None, "sheet node missing dom_id (flatten must assign it)"
    sheet_name = node.dom_id
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
    # The inner div (safe_inner) flex-centers the text vertically (KAN-293).
    # text-overflow:ellipsis is inert on a flex container, so the ellipsis
    # clipping (KAN-295) lives on a block holder div nested inside it.  With the
    # flex column's default align-items:stretch the holder spans the full width,
    # so the ellipsis clips and the outer div's text-align is preserved.
    return (
        f'<div style="{safe_outer}"><div style="{safe_inner}">'
        f'<div style="{_TEXT_HOLDER_STYLE}">{escaped_content}</div>'
        f"</div></div>"
    )


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


# A src is "external" (emitted verbatim) when it has a URI scheme (http:, data:,
# …), is protocol-relative (//host/…), or is already an absolute path (/foo).
# Everything else is treated as relative to the assets directory.
_EXTERNAL_SRC_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//|/)")


def _resolve_image_src(raw: str, asset_url_prefix: str) -> str:
    """Resolve an image src against the asset URL prefix.

    Relative srcs (e.g. `png/logo.png`) are interpreted relative to the assets
    directory and get the prefix prepended. External URLs, protocol-relative
    URLs, data URIs, and absolute paths pass through unchanged.
    """
    if _EXTERNAL_SRC_RE.match(raw):
        return raw
    return f"{asset_url_prefix}{raw}"


def _render_image(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    """Render an <img> in a div-in-div box honoring the fit/center booleans.

    fit=True  -> inner clips; img fills the box with object-fit: contain,
                 anchored center (center=True) or top-left (center=False).
    fit=False -> inner scrolls (overflow: auto); img renders at natural size
                 (center is ignored — natural images sit at the top-left origin).
    The html escape hatch is appended to the img CSS last so user CSS wins.
    """
    defn = node.component
    assert isinstance(defn, ImageComponent)
    escaped_src = html.escape(_resolve_image_src(defn.src, ctx.asset_url_prefix), quote=True)
    escaped_alt = html.escape(defn.alt, quote=True)

    if defn.fit:
        object_position = "center" if defn.center else "left top"
        inner_css = "width: 100%; height: 100%; overflow: hidden"
        img_css = (
            f"width: 100%; height: 100%; object-fit: contain; object-position: {object_position}"
        )
    else:
        # Natural size; the box scrolls when the image overflows.
        inner_css = "width: 100%; height: 100%; overflow: auto"
        img_css = "display: block"

    if defn.html:
        img_css += "; " + defn.html

    safe_inner_css = html.escape(inner_css, quote=True)
    safe_img_css = html.escape(img_css, quote=True)
    return (
        f'<div style="{safe_outer}">'
        f'<div style="{safe_inner_css}">'
        f'<img src="{escaped_src}" alt="{escaped_alt}" style="{safe_img_css}">'
        f"</div>"
        f"</div>"
    )


def _render_blank(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    return f'<div style="{safe_outer}"><div style="{safe_inner}"></div></div>'


def _render_legend(node: ResolvedNode, ctx: RenderContext, safe_outer: str, safe_inner: str) -> str:
    """Render a legend placeholder: an empty, box-styled div in a div-in-div wrapper.

    When the legend resolves to a sheet encoding (SHE-10/11), bake the link in as
    `data-source`/`data-channel`/`data-orientation`/`data-title` so the runtime
    (`legend_render.js`) can resolve the live scale from the channel and render the
    swatch/label content. SHE-28: the channel is emitted, not the compiled scale
    name — the browser resolves the scale. The box stays empty at compile time —
    content is rendered browser-side.

    Mirrors _render_sheet's id scheme (`legend-{name-or-auto-id}`) but does no
    fit/show_title bookkeeping — a legend is not a Vega embed target.
    """
    defn = node.component
    assert isinstance(defn, LegendComponent)
    # SHE-29: id assigned once at flatten time (see _assign_dom_ids).
    assert node.dom_id is not None, "legend node missing dom_id (flatten must assign it)"
    legend_name = node.dom_id
    safe_name = html.escape(legend_name, quote=True)

    link = ctx.legend_links.get((defn.source, defn.field))
    data_attrs = ""
    if link is not None:
        # SHE-12: emit data-format only when the field has a model format, so
        # categorical (nominal) legends stay byte-identical.
        fmt_attr = f' data-format="{html.escape(link.format, quote=True)}"' if link.format else ""
        data_attrs = (
            f' data-source="{html.escape(link.sheet_id, quote=True)}"'
            f' data-channel="{html.escape(link.channel, quote=True)}"'
            f"{fmt_attr}"
            f' data-orientation="{html.escape(defn.orientation, quote=True)}"'
            f' data-title="{html.escape(link.title, quote=True)}"'
        )
    return (
        f'<div style="{safe_outer}">'
        f'<div id="legend-{safe_name}"{data_attrs} style="{safe_inner}"></div>'
        f"</div>"
    )


_RENDERERS: dict[type, Callable[[ResolvedNode, RenderContext, str, str], str]] = {
    RootComponent: _render_root,
    ContainerComponent: _render_container,
    SheetComponent: _render_sheet,
    TextComponent: _render_text,
    ButtonComponent: _render_button_link,
    LinkComponent: _render_button_link,
    ImageComponent: _render_image,
    BlankComponent: _render_blank,
    LegendComponent: _render_legend,
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
    has_legends: bool = False,
) -> str:
    """Wrap rendered component tree in a full HTML page."""
    fit_modes = sheet_fit_modes or {}
    show_titles = sheet_show_titles or {}
    content_dims = sheet_content_dims or {}
    body_font = theme.layout.font.family.body

    # Build vegaEmbed script
    patch_js = ""
    fit_js = ""
    legend_js = ""
    script_lines = []
    # `has_legends` gates the legend renderer + populate wiring. It is derived
    # from the resolved legend links (a div emits data-channel iff its legend
    # resolved), not a substring scan of the body — so a text component that
    # happens to contain 'data-channel=' can't pull the JS in, and an all-unresolved
    # dashboard (nothing to populate) correctly omits it. Non-legend dashboards
    # stay byte-identical.
    # Guard `r` before dereferencing `r.view`: compoundFit.fit's internal .catch
    # resolves with undefined on a fit error, so an unguarded `r.view` would throw.
    populate_tail = (
        ".then(r => { if (r && window.legendRender) legendRender.populate(r.view, id, document); })"
        if has_legends
        else ""
    )
    if chart_specs:
        if has_legends:
            from shelves.render.to_html import load_legend_render_js

            legend_js = load_legend_render_js()
        # Inline the browser-side label patch and pass it to every embed so
        # labels (e.g. heatmap cell values) render in dashboards exactly as they
        # do on the single-chart render path (to_html.py). Without this, the
        # label intent in usermeta.shelves.labels is silently dropped (KAN-307).
        from shelves.render.to_html import load_label_patch_js

        patch_js = load_label_patch_js()

        # Serialize specs, applying fit modes and show_title
        specs_obj = {}
        # sheet id -> {width, height}: compound specs are sized in the browser.
        # The sizer measures real axis/title extents in the DOM and fits the spec
        # to this solved box — concat (KAN-291) and facet/repeat grids (KAN-294).
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
                # Every compound shape is sized in the browser now: concat (KAN-291)
                # and facet/repeat grids (KAN-294). The sizer measures real chrome
                # and fills the solved box in both axes, so route every compound
                # sheet regardless of which axis `fit` names.
                cw, ch = dims
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
        script_lines.append("    const embeds = [];")

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
            script_lines.append(
                "        embeds.push(compoundFit.fit(`#${id}`, spec, box,"
                " { actions: false, patch: labelPatch })"
                + populate_tail
                + ".catch(console.error));"
            )
            script_lines.append("      } else {")
            script_lines.append(
                "        embeds.push(vegaEmbed(`#${id}`, spec,"
                " { actions: false, patch: labelPatch })"
                + populate_tail
                + ".catch(console.error));"
            )
            script_lines.append("      }")
            script_lines.append("    });")
        else:
            script_lines.append("    Object.entries(specs).forEach(([id, spec]) => {")
            script_lines.append(
                "      embeds.push(vegaEmbed(`#${id}`, spec, { actions: false, patch: labelPatch })"
                + populate_tail
                + ".catch(console.error));"
            )
            script_lines.append("    });")
    else:
        script_lines.append("    const embeds = [];")

    # Rendered signal (SHE-67): fires once every embed promise has settled.
    # Studio's dashboard preview holds its loading veil until this message;
    # any other host (standalone file, top-level tab) simply never listens —
    # with no charts it fires immediately.
    script_lines.append("    Promise.allSettled(embeds).then(() => {")
    script_lines.append(
        "      try { parent.postMessage({ type: 'shelves:rendered' }, '*'); } catch (e) {}"
    )
    script_lines.append("    });")

    script_block = "\n".join(script_lines)
    patch_block = f"  <script>\n{patch_js}\n  </script>\n" if patch_js else ""
    fit_block = f"  <script>\n{fit_js}\n  </script>\n" if fit_js else ""
    legend_block = f"  <script>\n{legend_js}\n  </script>\n" if legend_js else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(dashboard_name)}</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@5.33.1/build/vega.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@6.4.3/build/vega-lite.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6.29.0/build/vega-embed.min.js"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: {body_font}; }}
    img {{ display: block; object-fit: contain; }}
  </style>
</head>
<body>
  {body_html}
{patch_block}{fit_block}{legend_block}  <script>
{script_block}
  </script>
</body>
</html>"""
