"""
Layout Style Resolution Engine

Resolves the five-level style cascade for layout DSL components:
  theme defaults → navigation type defaults → text preset → shared style
  → inline properties → sheet fit → html (wins all)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.schema.layout_schema import (
    StyleProperties,
)
from src.theme.theme_schema import ThemeSpec


# ─── Navigation Component Defaults ───────────────────────────────

NAVIGATION_BUTTON_DEFAULTS: dict[str, str] = {
    "background": "#4A90D9",
    "color": "#FFFFFF",
    "border-radius": "6px",
    "padding": "8px 20px",
    "text-decoration": "none",
    "cursor": "pointer",
    "display": "inline-flex",
    "align-items": "center",
}

NAVIGATION_LINK_DEFAULTS: dict[str, str] = {
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

    components: dict[str, Any]
    styles: dict[str, StyleProperties]
    theme: ThemeSpec
    auto_id_counter: int = 0
    sheet_fit_modes: dict[str, str] = field(default_factory=dict)

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


def _size_to_flex(value: Any) -> str:
    """Convert a DSL size value to a CSS flex property value.

    None or "auto" → "1"
    int            → "0 0 {value}px"
    str "Npx"      → "0 0 {value}"
    str "N%"       → "0 0 {value}"
    """
    if value is None or value == "auto":
        return "1"
    if isinstance(value, int):
        return f"0 0 {value}px"
    s = str(value)
    if s.endswith("px") or s.endswith("%"):
        return f"0 0 {s}"
    # Bare number string
    if s.isdigit():
        return f"0 0 {s}px"
    return "1"


def _resolve_sizing(
    component: Any,
    parent_orientation: Literal["horizontal", "vertical"] | None,
) -> dict[str, str]:
    """Translate DSL size values to CSS flex properties."""
    if parent_orientation is None:
        return {}

    width = getattr(component, "width", None)
    height = getattr(component, "height", None)

    css: dict[str, str] = {}

    if parent_orientation == "horizontal":
        main_value = width
        cross_value = height
        cross_prop = "height"
    else:
        main_value = height
        cross_value = width
        cross_prop = "width"

    # Main-axis
    css["flex"] = _size_to_flex(main_value)

    # Cross-axis
    if cross_value is not None and cross_value != "auto":
        if isinstance(cross_value, int):
            css[cross_prop] = f"{cross_value}px"
        else:
            s = str(cross_value)
            if s.endswith("px") or s.endswith("%"):
                css[cross_prop] = s
            elif s.isdigit():
                css[cross_prop] = f"{s}px"

    return css


# ─── Align / Justify ─────────────────────────────────────────────

_ALIGN_MAP = {
    "start": "flex-start",
    "center": "center",
    "end": "flex-end",
    "stretch": "stretch",
}

_JUSTIFY_MAP = {
    "start": "flex-start",
    "center": "center",
    "end": "flex-end",
    "between": "space-between",
    "around": "space-around",
    "evenly": "space-evenly",
}


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
    component: Any,
    name: str | None,
    ctx: RenderContext,
    parent_orientation: Literal["horizontal", "vertical"] | None,
) -> str:
    """Resolve component styles to a CSS inline style string.

    Resolution order:
    1. Layout/structural CSS (display, flex-direction, sizing)
    2. Theme defaults (font family)
    3. Navigation type defaults (button or link)
    4. Text preset (if TextComponent with preset)
    5. Shared style (if component.style references styles dict)
    6. Inline properties (component-level overrides from extra fields)
    7. Margin/padding
    8. Sheet fit CSS
    9. html escape hatch (raw CSS, appended last)
    """
    css: dict[str, str] = {}
    comp_type = getattr(component, "type", None)

    # Step 1: Structural CSS
    if comp_type in ("root", "container"):
        orientation = getattr(component, "orientation", "vertical")
        css["display"] = "flex"
        css["flex-direction"] = "row" if orientation == "horizontal" else "column"

        if comp_type == "root":
            # Root gets canvas dimensions via wrap_html_page injection
            css["overflow"] = "hidden"

        # Align/justify
        align = getattr(component, "align", None)
        if align and align in _ALIGN_MAP:
            css["align-items"] = _ALIGN_MAP[align]

        justify = getattr(component, "justify", None)
        if justify and justify in _JUSTIFY_MAP:
            css["justify-content"] = _JUSTIFY_MAP[justify]

    elif comp_type == "text":
        css["display"] = "flex"
        css["align-items"] = "center"

    # Step 2: Sizing (main-axis flex + cross-axis)
    sizing = _resolve_sizing(component, parent_orientation)
    css.update(sizing)

    # Step 3: Theme defaults (font-family for text-bearing components)
    if comp_type in ("text", "navigation", "navigation_button", "navigation_link"):
        css["font-family"] = ctx.theme.layout.font.family.body

    # Step 4: Navigation type defaults
    if comp_type in ("navigation", "navigation_button"):
        for k, v in NAVIGATION_BUTTON_DEFAULTS.items():
            css[k] = v
    elif comp_type == "navigation_link":
        for k, v in NAVIGATION_LINK_DEFAULTS.items():
            css[k] = v

    # Step 5: Text preset
    preset_name = getattr(component, "preset", None)
    if preset_name and preset_name in ctx.theme.layout.presets:
        preset = ctx.theme.layout.presets[preset_name]
        css["font-size"] = f"{preset.font_size}px"
        css["font-weight"] = str(preset.font_weight)
        css["color"] = preset.color
        if preset.text_align:
            css["text-align"] = preset.text_align

    # Step 6: Shared style
    style_ref = getattr(component, "style", None)
    if style_ref and style_ref in ctx.styles:
        style_props = ctx.styles[style_ref]
        for field_name in type(style_props).model_fields:
            val = getattr(style_props, field_name)
            if val is not None:
                css_name = _css_prop_name(field_name)
                if css_name == "shadow":
                    css["box-shadow"] = str(val)
                elif isinstance(val, (int, float)) and field_name in (
                    "border_radius",
                    "font_size",
                ):
                    css[css_name] = f"{val}px"
                else:
                    css[css_name] = str(val)

    # Step 7: Inline overrides from __pydantic_extra__
    extras = getattr(component, "__pydantic_extra__", None) or {}
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

    # Also check declared fields that act as inline overrides
    # (font_size on TextComponent is a declared field via extras on the model,
    #  but it's actually in __pydantic_extra__ because it's not on the base)
    # We handle padding/margin separately below.

    # Step 8: Margin and padding
    margin = getattr(component, "margin", None)
    margin_css = _format_spacing(margin)
    if margin_css:
        css["margin"] = margin_css

    padding = getattr(component, "padding", None)
    padding_css = _format_spacing(padding)
    if padding_css:
        css["padding"] = padding_css

    # Step 9: Sheet fit CSS
    fit = getattr(component, "fit", None)
    if fit == "width":
        css["overflow-y"] = "auto"
    elif fit == "height":
        css["overflow-x"] = "auto"
    elif fit == "fill":
        css["overflow"] = "hidden"

    # Step 10: Serialize CSS dict
    html_escape = getattr(component, "html", None)

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
