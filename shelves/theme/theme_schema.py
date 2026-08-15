"""
ThemeSpec — Pydantic model for the unified theme.yaml.

The theme has two top-level sections:
- chart: A valid Vega-Lite config object (permissive, extra keys allowed)
- layout: Structured tokens for the Layout DSL (text presets, colors, typography)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChartTheme(BaseModel):
    """
    Vega-Lite config object. Permissive — accepts any VL config keys
    beyond the explicitly declared ones.
    """

    model_config = ConfigDict(extra="allow")

    background: str = "#ffffff"
    mark: dict = Field(default_factory=lambda: {"color": "#4A90D9"})
    axis: dict = Field(default_factory=dict)
    legend: dict = Field(default_factory=dict)
    range: dict = Field(default_factory=dict)
    kpi: dict = Field(
        default_factory=lambda: {
            "title": {"fontSize": 13, "fontWeight": 500, "color": "#666666"},
            "value": {"fontSize": 36, "fontWeight": 600, "color": "#1a1a1a"},
            "comparison": {"fontSize": 12, "fontWeight": 400},
            "semantic": {"positive": "#16A34A", "negative": "#DC2626", "neutral": "#6B7280"},
            "spacing": 4,
        }
    )


class LayoutTextColors(BaseModel):
    primary: str = "#1a1a1a"
    secondary: str = "#666666"
    tertiary: str = "#999999"


class LayoutFontFamily(BaseModel):
    body: str = "Inter, system-ui, sans-serif"
    heading: str = "Inter, system-ui, sans-serif"


class LayoutFontSizes(BaseModel):
    xs: int = 11
    sm: int = 12
    md: int = 14
    lg: int = 18
    xl: int = 24


class LayoutFontWeights(BaseModel):
    normal: int = 400
    medium: int = 500
    semibold: int = 600
    bold: int = 700


class LayoutFont(BaseModel):
    family: LayoutFontFamily = Field(default_factory=LayoutFontFamily)
    size: LayoutFontSizes = Field(default_factory=LayoutFontSizes)
    weight: LayoutFontWeights = Field(default_factory=LayoutFontWeights)


class TextPreset(BaseModel):
    """A single text preset (e.g. title, body, caption).

    The `color` field may be a hex value OR a reference like "text.primary"
    which resolves to layout.text.primary at load time.
    """

    font_size: int
    font_weight: int | str
    color: str
    text_align: str = "left"


class ControlTokens(BaseModel):
    surface: str = "#ffffff"
    border: str = "#e5e7eb"
    radius: int = 4
    accent: str = "#4A90D9"
    font_size: int = 13
    height: int = 32
    text: str = "#1a1a1a"
    focus_ring: str = "0 0 0 2px rgba(74, 144, 217, 0.3)"


class FilterTokens(BaseModel):
    surface: str = "#ffffff"
    border: str = "#e5e7eb"
    radius: int = 4
    accent: str = "#4A90D9"
    font_size: int = 13
    height: int = 32
    text: str = "#1a1a1a"
    focus_ring: str = "0 0 0 2px rgba(74, 144, 217, 0.3)"


class LayoutTheme(BaseModel):
    text: LayoutTextColors = Field(default_factory=LayoutTextColors)
    font: LayoutFont = Field(default_factory=LayoutFont)
    surface: str = "#ffffff"
    background: str = "#f5f5f5"
    border: str = "#e5e7eb"
    presets: dict[str, TextPreset] = Field(default_factory=dict)
    control: ControlTokens = Field(default_factory=ControlTokens)
    filter: FilterTokens = Field(default_factory=FilterTokens)


class ThemeSpec(BaseModel):
    """Top-level theme model with chart and layout sections."""

    chart: ChartTheme = Field(default_factory=ChartTheme)
    layout: LayoutTheme = Field(default_factory=LayoutTheme)
