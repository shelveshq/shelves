"""
Layout Style Resolution Engine

Resolves the style cascade for layout DSL components:
  theme defaults → type defaults → text preset → shared style
  → inline properties → sheet fit → html (wins all)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shelves.schema.layout_schema import (
    ButtonComponent,
    Component,
    LinkComponent,
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


# ─── Render Context ──────────────────────────────────────────────


@dataclass
class RenderContext:
    """Carries shared state through the recursive tree walk."""

    theme: ThemeSpec
    auto_id_counter: int = 0
    sheet_fit_modes: dict[str, str] = field(default_factory=dict)
    sheet_show_titles: dict[str, bool] = field(default_factory=dict)
    sheet_content_dims: dict[str, tuple[int, int]] = field(default_factory=dict)
    sheet_padding: dict[str, int | dict[str, int]] = field(default_factory=dict)

    def next_auto_id(self) -> str:
        """Generate next auto-ID for anonymous sheets."""
        self.auto_id_counter += 1
        return f"auto-{self.auto_id_counter}"


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
) -> str:
    """Resolve component styles to a CSS inline style string.

    Assumes the component has already been through flatten_dashboard, so all
    style-derived properties are pre-merged onto the component.

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

    # Children of horizontal containers are inline-block
    if parent_orientation == "horizontal":
        css["display"] = "inline-block"
        css["vertical-align"] = "top"

    # Step 2: Sizing — solver-computed pixel dimensions
    if resolved_width is not None:
        css["width"] = f"{resolved_width}px"
    if resolved_height is not None:
        css["height"] = f"{resolved_height}px"

    # Step 3: Theme defaults (font-family for text-bearing components)
    if isinstance(component, (TextComponent, ButtonComponent, LinkComponent)):
        css["font-family"] = ctx.theme.layout.font.family.body

    # Step 4: Type defaults
    if isinstance(component, ButtonComponent):
        for k, v in BUTTON_DEFAULTS.items():
            css[k] = v
    elif isinstance(component, LinkComponent):
        for k, v in LINK_DEFAULTS.items():
            css[k] = v

    # Step 5: Text preset
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

    # Step 8: Sheet fit CSS
    fit = component.fit if isinstance(component, SheetComponent) else None

    # For fitted sheets, skip CSS padding — Vega-Lite will handle it via
    # its own padding + autosize:{contains:"padding"}.  CSS padding would
    # shift the SVG inside the div without Vega knowing about it.
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

    # Step 11: Append html escape hatch
    if html_escape:
        if result and not result.endswith(";"):
            result += "; "
        elif result:
            result += " "
        result += html_escape

    return result
