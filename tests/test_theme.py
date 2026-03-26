"""
Theme Tests

Tests for ThemeSpec loading, preset color resolution, and merge_theme integration.
"""

from pathlib import Path

from src.theme.merge import load_theme, merge_theme
from src.theme.theme_schema import ThemeSpec


# ─── Theme Loading ────────────────────────────────────────────────


class TestThemeLoading:
    def test_load_default_theme(self):
        theme = load_theme()
        assert isinstance(theme, ThemeSpec)
        assert theme.chart.background == "#ffffff"
        assert theme.chart.mark == {"color": "#4A90D9"}
        assert theme.layout.text.primary == "#1a1a1a"
        assert theme.layout.surface == "#ffffff"
        assert theme.layout.background == "#f5f5f5"

    def test_chart_section_is_valid_vl_config(self):
        theme = load_theme()
        chart = theme.chart.model_dump()
        # Must have standard VL config keys
        assert "background" in chart
        assert "mark" in chart
        assert "axis" in chart
        assert "range" in chart
        assert len(chart["range"]["category"]) == 8
        # Must have extra keys that VL expects
        assert "view" in chart
        assert chart["view"]["fill"] == "#f8f9fa"
        assert "bar" in chart
        assert chart["bar"]["cornerRadius"] == 2
        assert chart["padding"] == 16

    def test_layout_presets_match_spec(self):
        theme = load_theme()
        presets = theme.layout.presets

        # All six presets must exist
        assert set(presets.keys()) == {"title", "subtitle", "heading", "body", "caption", "label"}

        # Spot-check values per Layout DSL spec section 5.4
        assert presets["title"].font_size == 24
        assert presets["title"].font_weight == "bold"
        assert presets["subtitle"].font_size == 18
        assert presets["subtitle"].font_weight == 600
        assert presets["heading"].font_size == 16
        assert presets["body"].font_size == 14
        assert presets["caption"].font_size == 12
        assert presets["label"].font_size == 11
        assert presets["label"].font_weight == 500

    def test_preset_color_resolution(self):
        theme = load_theme()
        presets = theme.layout.presets

        # "text.primary" should have resolved to "#1a1a1a"
        assert presets["title"].color == "#1a1a1a"
        assert presets["heading"].color == "#1a1a1a"
        assert presets["body"].color == "#1a1a1a"

        # "text.secondary" should have resolved to "#666666"
        assert presets["subtitle"].color == "#666666"
        assert presets["label"].color == "#666666"

        # "text.tertiary" should have resolved to "#999999"
        assert presets["caption"].color == "#999999"

    def test_load_custom_theme(self):
        custom_path = Path(__file__).parent / "fixtures" / "themes" / "custom_brand.yaml"
        theme = load_theme(custom_path)
        assert isinstance(theme, ThemeSpec)
        # Custom values override defaults
        assert theme.chart.background == "#1a1a2e"
        assert theme.chart.mark == {"color": "#e94560"}
        assert theme.layout.text.primary == "#ffffff"
        assert theme.layout.surface == "#1a1a2e"
        # Unspecified values fall back to Pydantic defaults
        assert theme.layout.font.family.body == "Inter, system-ui, sans-serif"
        assert theme.layout.font.size.md == 14


# ─── Theme Merge ─────────────────────────────────────────────────


class TestThemeMerge:
    def test_merge_theme_uses_chart_section(self):
        theme = load_theme()
        spec = {"mark": "bar", "encoding": {}}
        result = merge_theme(spec, theme)
        assert "config" in result
        assert result["config"]["background"] == "#ffffff"
        assert result["config"]["mark"] == {"color": "#4A90D9"}
        assert len(result["config"]["range"]["category"]) == 8
        # Layout section must NOT leak into VL config
        assert "layout" not in result["config"]
        assert "text" not in result["config"]
        assert "presets" not in result["config"]

    def test_merge_theme_backward_compat(self):
        spec = {"mark": "bar"}
        # Old-style flat dict (no "chart" key)
        legacy_theme = {"background": "#222", "padding": 0}
        result = merge_theme(spec, legacy_theme)
        assert result["config"]["background"] == "#222"
        assert result["config"]["padding"] == 0

    def test_custom_theme_merge_into_spec(self):
        custom_path = Path(__file__).parent / "fixtures" / "themes" / "custom_brand.yaml"
        theme = load_theme(custom_path)
        spec = {"mark": "bar", "encoding": {}}
        result = merge_theme(spec, theme)
        # Custom chart colors propagate to VL config
        assert result["config"]["background"] == "#1a1a2e"
        assert result["config"]["mark"]["color"] == "#e94560"
        # Layout section still does not leak
        assert "layout" not in result["config"]
