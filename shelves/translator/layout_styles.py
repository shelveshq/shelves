"""
Layout Style Resolution Engine

Resolves the style cascade for layout DSL components:
  theme defaults → type defaults → text preset → shared style
  → inline properties → sheet fit → html (wins all)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from shelves.schema.layout_schema import (
    ButtonComponent,
    Component,
    FilterComponent,
    LinkComponent,
    ParameterComponent,
    RootComponent,
    SheetComponent,
    TextComponent,
)
from shelves.theme.theme_schema import ThemeSpec

# ─── Button / Link Defaults ─────────────────────────────────────

BUTTON_DEFAULTS: dict[str, str] = {
    "background": "#4A90D9",
    "color": "#FFFFFF",
    "border-radius": "6px",
    "padding": "8px 20px",
    "text-decoration": "none",
    "cursor": "pointer",
}

LINK_DEFAULTS: dict[str, str] = {
    "color": "#4A90D9",
    "text-decoration": "underline",
    "cursor": "pointer",
    "background": "transparent",
    "padding": "0",
    "border-radius": "0",
}


# ─── Legend Link ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ControlMeta:
    """Compose-time metadata for a control component, consumed by the translator."""

    param: str
    widget: str  # "dropdown" | "stepper" | "date" | "text"
    title: str
    default: str | None
    options: list[dict[str, str]] | None = None  # [{value, label}] for dropdowns
    min: str | None = None
    max: str | None = None
    step: str | None = None


@dataclass(frozen=True)
class FilterControlMeta:
    """Compose-time metadata for a filter control, consumed by the translator."""

    field: str
    model: str
    mode: str
    operator: str
    widget: str
    title: str
    targets: list[str]
    default: Any = None
    options: Any = None


@dataclass(frozen=True)
class LegendLink:
    """Resolved binding from a legend element to its sheet's encoding (SHE-10/11).

    SHE-28: the binding is the bare encoding *channel* — the runtime resolves the
    compiled Vega scale from it against the live view (exact `view.scale(channel)`
    for single-view specs, or a `*_<channel>` suffix scan for namespaced/labeled
    specs). Python no longer reconstructs the compiled scale name (no convention
    coupling to Vega-Lite's `{name}_{channel}` scheme).
    """

    sheet_id: str  # the linked sheet's DOM id, e.g. "sheet-sales_chart"
    channel: str  # the encoding channel ("color"/"size"/"shape") — the source of
    # truth the browser resolves the live scale from
    title: str  # SHE-11: legend heading — explicit override or the field's model label
    format: str | None = None  # SHE-12: d3 format spec for gradient/size tick labels;
    # None for un-formatted (e.g. nominal) fields


# ─── Render Context ──────────────────────────────────────────────


@dataclass
class RenderContext:
    """Carries shared state through the recursive tree walk."""

    theme: ThemeSpec
    # URL prefix prepended to relative image srcs (e.g. "assets/"). Differs per
    # render pipeline: studio/dev serve at /assets, render computes a relpath.
    asset_url_prefix: str = "assets/"
    sheet_fit_modes: dict[str, str] = field(default_factory=dict)
    sheet_show_titles: dict[str, bool] = field(default_factory=dict)
    sheet_content_dims: dict[str, tuple[int, int]] = field(default_factory=dict)
    # SHE-10: (legend.source, legend.field) -> resolved link. Empty for the
    # studio/direct-translate paths that don't resolve legends yet.
    legend_links: dict[tuple[str, str], LegendLink] = field(default_factory=dict)
    # SHE-92: dom_id -> ControlMeta for each control component.
    control_meta: dict[str, ControlMeta] = field(default_factory=dict)
    # SHE-80: dom_id -> FilterControlMeta for each filter component.
    filter_control_meta: dict[str, FilterControlMeta] = field(default_factory=dict)


# ─── CSS Helpers ─────────────────────────────────────────────────


def _css_prop_name(field_name: str) -> str:
    """Convert Python field name to CSS property name.

    font_size → font-size, border_radius → border-radius
    """
    return field_name.replace("_", "-")


def _format_spacing(value: int | str | None) -> str | None:
    """Convert margin/padding DSL value to CSS.

    16        → "16px"
    "8 16"    → "8px 16px"
    None      → None
    """
    if value is None:
        return None
    if isinstance(value, int):
        return f"{value}px"
    parts = str(value).split()
    return " ".join(f"{p}px" if p.isdigit() else p for p in parts)


# ─── Style Properties That Come From Inline Extras ───────────────

_STYLE_EXTRA_KEYS = {
    "background",
    "color",
    "font_size",
    "font_weight",
    "font_family",
    "text_align",
    "border",
    "border_top",
    "border_bottom",
    "border_left",
    "border_right",
    "border_radius",
    "shadow",
    "opacity",
}


# ─── Main Resolve Function ───────────────────────────────────────


def resolve_styles(
    component: Component | RootComponent,
    name: str | None,
    ctx: RenderContext,
    parent_orientation: Literal["horizontal", "vertical"] | None,
    resolved_width: int | None = None,
    resolved_height: int | None = None,
    has_wrapper: bool = False,
) -> str:
    """Resolve component styles to a CSS inline style string.

    Assumes the component has already been through flatten_dashboard, so all
    style-derived properties are pre-merged onto the component.

    When has_wrapper=True (div-in-div outer div):
      - Includes padding, overflow:hidden, box-sizing:border-box
      - Includes visual styles, margin, html escape hatch
      - For sheets: fit-specific overflow replaces default overflow:hidden

    When has_wrapper=False (single div, legacy path):
      - Same as original behavior

    Resolution order:
    1. Structural CSS (overflow, display for horizontal children)
    2. Solver-computed pixel dimensions
    3. Theme defaults (font family)
    4. Type defaults (button or link)
    5. Text preset
    6. Extras from __pydantic_extra__ (includes style-merged visual props)
    7. Margin/padding (model fields, may be style-merged)
    8. Sheet fit CSS
    9. html escape hatch (raw CSS, appended last)
    """
    css: dict[str, str] = {}

    # Step 1: Structural CSS
    if isinstance(component, RootComponent):
        css["overflow"] = "hidden"

    # Anchor leaves (link/button) render an <a> directly inside the outer box
    # with no inner companion div, so they cannot use resolve_inner_styles for
    # centering.  Make the outer box a flex container that vertically centers
    # the <a> (KAN-293), matching the centered text in the same row.
    is_anchor_leaf = isinstance(component, (LinkComponent, ButtonComponent))

    # Children of horizontal containers are inline-block (inline-flex for anchors
    # so they stay in the inline row while centering their <a> vertically).
    if parent_orientation == "horizontal":
        css["display"] = "inline-flex" if is_anchor_leaf else "inline-block"
        css["vertical-align"] = "top"
    elif is_anchor_leaf:
        css["display"] = "flex"

    if is_anchor_leaf:
        css["align-items"] = "center"

    # Step 2: Sizing — solver-computed pixel dimensions
    if resolved_width is not None:
        css["width"] = f"{resolved_width}px"
    if resolved_height is not None:
        css["height"] = f"{resolved_height}px"

    # Step 3: Theme defaults (font-family for text-bearing components)
    if isinstance(component, (TextComponent, ButtonComponent, LinkComponent)) and not has_wrapper:
        css["font-family"] = ctx.theme.layout.font.family.body

    # Step 4: Type defaults
    if not has_wrapper:
        if isinstance(component, ButtonComponent):
            for k, v in BUTTON_DEFAULTS.items():
                css[k] = v
        elif isinstance(component, LinkComponent):
            for k, v in LINK_DEFAULTS.items():
                css[k] = v

    # Step 5: Text preset — applied regardless of wrapper (font props cascade to inner div)
    if isinstance(component, TextComponent) and component.preset:
        preset_name = component.preset
        if preset_name in ctx.theme.layout.presets:
            preset = ctx.theme.layout.presets[preset_name]
            css["font-size"] = f"{preset.font_size}px"
            css["font-weight"] = str(preset.font_weight)
            css["color"] = preset.color
            if preset.text_align:
                css["text-align"] = preset.text_align

    # Step 6: Inline extras from __pydantic_extra__ (includes style-merged visual props)
    # Visual extras (background, border, shadow, etc.) go on the outer div in both paths.
    # Font/text extras (font_size, color) also go here — they cascade to inner content.
    extras = component.__pydantic_extra__ or {}
    for key, val in extras.items():
        if key in _STYLE_EXTRA_KEYS and val is not None:
            css_name = _css_prop_name(key)
            if css_name == "shadow":
                css["box-shadow"] = str(val)
            elif isinstance(val, (int, float)) and key in (
                "border_radius",
                "font_size",
            ):
                css[css_name] = f"{val}px"
            else:
                css[css_name] = str(val)

    # Step 7: Margin and padding
    margin_css = _format_spacing(component.margin)
    if margin_css:
        css["margin"] = margin_css

    fit = component.fit if isinstance(component, SheetComponent) else None

    if has_wrapper:
        # Outer div: padding + box-sizing only.  Overflow/clipping is handled
        # by the INNER content div (resolve_inner_styles) so that the clip
        # boundary is the content box (inside padding), not the padding box.
        padding_css = _format_spacing(component.padding)
        if padding_css:
            css["padding"] = padding_css
        css["box-sizing"] = "border-box"
    else:
        # Step 8: Single-div path — include padding (but NOT for fitted sheets)
        if not (isinstance(component, SheetComponent) and fit is not None):
            padding_css = _format_spacing(component.padding)
            if padding_css:
                css["padding"] = padding_css

        if fit == "width":
            css["overflow-y"] = "auto"
        elif fit == "height":
            css["overflow-x"] = "auto"
        elif fit == "fill":
            css["overflow"] = "hidden"

    # Step 9: Serialize CSS dict
    html_escape = component.html

    parts = [f"{k}: {v}" for k, v in css.items()]
    result = "; ".join(parts)

    # Append html escape hatch
    if html_escape:
        if result and not result.endswith(";"):
            result += "; "
        elif result:
            result += " "
        result += html_escape

    return result


def resolve_inner_styles(
    component: Component | RootComponent,
    ctx: RenderContext,
    fit: Literal["width", "height", "fill"] | None = None,
) -> str:
    """Resolve CSS for the inner content div in a div-in-div structure.

    Always: width:100%; height:100%
    Sheets: + position:relative, and a fit-aware overflow so the clip/scroll
            boundary is the *content box* (inside the outer wrapper's padding):
              fit == "width"  -> overflow-y: auto
              fit == "height" -> overflow-x: auto
              fit in ("fill", None) -> overflow: hidden
    Text:   + overflow:hidden and flex column centering so the text is
            vertically centered within its box (KAN-293).  The ellipsis clipping
            (KAN-295) does NOT live here — text-overflow:ellipsis is inert on a
            flex container, so it is carried by a block holder div that
            _render_text nests inside this flex-centering div.
    Other:  + overflow:hidden so wrapped containers/images/blanks clip at their
            content box (the outer wrapper no longer carries overflow).

    `fit` is ignored for all non-sheet components.
    """
    css: dict[str, str] = {
        "width": "100%",
        "height": "100%",
    }
    if isinstance(component, SheetComponent):
        css["position"] = "relative"
        # Step: fit-aware clip/scroll on the inner content div
        if fit == "width":
            css["overflow-y"] = "auto"
        elif fit == "height":
            css["overflow-x"] = "auto"
        else:  # "fill" or None
            css["overflow"] = "hidden"
    elif isinstance(component, TextComponent):
        # Clip overflow within the box.  The ellipsis itself is applied on the
        # block holder div (see _render_text) because text-overflow:ellipsis has
        # no effect on a flex container.
        css["overflow"] = "hidden"
        # Vertically center the text within its box.  flex-direction:column with
        # justify-content:center centers on the block (vertical) axis while the
        # holder stays a full-width item so text-align (horizontal) is preserved.
        css["display"] = "flex"
        css["flex-direction"] = "column"
        css["justify-content"] = "center"
    elif isinstance(component, (ParameterComponent, FilterComponent)):
        css["display"] = "flex"
        css["align-items"] = "center"
    else:
        # Container/Image/Blank: clip child content at the content box.  The
        # outer wrapper dropped overflow when clipping moved to the inner div,
        # so without this, child overflow would bleed past the component.
        css["overflow"] = "hidden"

    parts = [f"{k}: {v}" for k, v in css.items()]
    return "; ".join(parts)
