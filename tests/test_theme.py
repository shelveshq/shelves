"""
Theme Tests

Tests for ThemeSpec loading, preset color resolution, and merge_theme integration.
"""

from pathlib import Path

from shelves.theme.merge import load_theme, merge_theme
from shelves.theme.theme_schema import ThemeSpec


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

    def test_custom_theme_inherits_default_chart_config(self):
        """Custom theme that only overrides colors should still have all
        default chart config (axis, legend, view, title, padding, etc.)."""
        custom_path = Path(__file__).parent / "fixtures" / "themes" / "custom_brand.yaml"
        theme = load_theme(custom_path)
        chart = theme.chart.model_dump()

        # Custom overrides are applied
        assert chart["background"] == "#1a1a2e"
        assert chart["mark"] == {"color": "#e94560"}
        assert len(chart["range"]["category"]) == 4  # custom palette has 4

        # Default config that custom_brand.yaml does NOT specify must survive
        assert "axis" in chart
        assert chart["axis"]["labelFont"] == "Inter, system-ui, sans-serif"
        assert chart["axis"]["labelFontSize"] == 11
        assert chart["axis"]["gridColor"] == "#f0f0f0"
        assert "legend" in chart
        assert chart["legend"]["labelFontSize"] == 11
        assert "view" in chart
        assert chart["view"]["fill"] == "#f8f9fa"
        assert "title" in chart
        assert chart["title"]["fontSize"] == 16
        assert chart["bar"]["cornerRadius"] == 2
        assert chart["padding"] == 16

    def test_custom_theme_inherits_default_layout_presets(self):
        """Custom theme that doesn't specify presets should inherit all
        default presets with colors resolved against the custom text palette."""
        custom_path = Path(__file__).parent / "fixtures" / "themes" / "custom_brand.yaml"
        theme = load_theme(custom_path)
        presets = theme.layout.presets

        # All six presets must still exist (inherited from default)
        assert set(presets.keys()) == {"title", "subtitle", "heading", "body", "caption", "label"}

        # Preset colors resolve against the CUSTOM text palette, not the default
        assert presets["title"].color == "#ffffff"  # text.primary → custom "#ffffff"
        assert presets["subtitle"].color == "#a0a0a0"  # text.secondary → custom "#a0a0a0"
        assert presets["caption"].color == "#666666"  # text.tertiary → custom "#666666"

        # Preset font sizes are inherited from default
        assert presets["title"].font_size == 24
        assert presets["body"].font_size == 14


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

    def test_merge_theme_default_none(self):
        """merge_theme(spec, None) loads and applies the default theme."""
        spec = {"mark": "bar", "encoding": {}}
        result = merge_theme(spec, None)
        assert "config" in result
        assert result["config"]["background"] == "#ffffff"
        assert result["config"]["mark"] == {"color": "#4A90D9"}

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

    def test_deep_merge_spec_config_overrides_single_key(self):
        """Spec-level config that overrides a single nested key should NOT
        wipe out sibling keys from the theme. e.g. overriding
        axis.labelFontSize should preserve axis.gridColor, axis.labelFont, etc."""
        theme = load_theme()
        spec = {
            "mark": "bar",
            "encoding": {},
            "config": {"axis": {"labelFontSize": 14}},
        }
        result = merge_theme(spec, theme)
        axis = result["config"]["axis"]

        # The spec-level override wins
        assert axis["labelFontSize"] == 14

        # Theme defaults for other axis keys must survive
        assert axis["gridColor"] == "#f0f0f0"
        assert axis["labelFont"] == "Inter, system-ui, sans-serif"
        assert axis["domainColor"] == "#9ca3af"
        assert axis["titleFontSize"] == 12

    def test_deep_merge_spec_config_overrides_multiple_sections(self):
        """Spec-level config overriding keys in multiple nested sections
        should preserve unrelated keys in each section."""
        theme = load_theme()
        spec = {
            "mark": "bar",
            "encoding": {},
            "config": {
                "axis": {"labelFontSize": 14},
                "legend": {"padding": 20},
                "view": {"fill": "#000000"},
            },
        }
        result = merge_theme(spec, theme)

        # Overrides take effect
        assert result["config"]["axis"]["labelFontSize"] == 14
        assert result["config"]["legend"]["padding"] == 20
        assert result["config"]["view"]["fill"] == "#000000"

        # Theme defaults survive in each section
        assert result["config"]["axis"]["gridColor"] == "#f0f0f0"
        assert result["config"]["legend"]["labelFontSize"] == 11
        assert result["config"]["mark"] == {"color": "#4A90D9"}
        assert result["config"]["padding"] == 16

    def test_deep_merge_top_level_scalar_override(self):
        """Spec-level config that overrides a top-level scalar (padding)
        should still work correctly alongside deep merge."""
        theme = load_theme()
        spec = {
            "mark": "bar",
            "encoding": {},
            "config": {"padding": 0, "background": "#111111"},
        }
        result = merge_theme(spec, theme)

        # Overrides win
        assert result["config"]["padding"] == 0
        assert result["config"]["background"] == "#111111"

        # Nested theme defaults survive untouched
        assert result["config"]["axis"]["labelFontSize"] == 11
        assert result["config"]["view"]["fill"] == "#f8f9fa"


# ─── Layout Token Validation ────────────────────────────────────


class TestLayoutTokens:
    """Validate that default theme layout tokens match the Layout DSL specification."""

    def test_layout_tokens_match_dsl_spec(self):
        """Cross-reference layout tokens against Layout DSL Specification section 5.4."""
        theme = load_theme()

        # Text presets — values must match DSL spec table
        assert theme.layout.presets["title"].font_size == 24
        assert theme.layout.presets["title"].color == "#1a1a1a"  # resolved from text.primary
        assert theme.layout.presets["subtitle"].font_size == 18
        assert theme.layout.presets["subtitle"].color == "#666666"  # resolved from text.secondary
        assert theme.layout.presets["caption"].font_size == 12
        assert theme.layout.presets["caption"].color == "#999999"  # resolved from text.tertiary
        assert theme.layout.presets["label"].font_size == 11

        # Body font family must match chart axis label font
        chart = theme.chart.model_dump()
        assert theme.layout.font.family.body == chart["axis"]["labelFont"]

        # Dashboard background (Layout DSL examples 8.1, 8.2)
        assert theme.layout.background == "#f5f5f5"

        # Card surface color (Layout DSL examples 8.1 card style)
        assert theme.layout.surface == "#ffffff"

        # Border color (Layout DSL examples 8.1 card border)
        assert theme.layout.border == "#e5e7eb"

    def test_font_coherence_across_sections(self):
        """Chart axis/title/legend fonts all use the same family as layout.font.family.body."""
        theme = load_theme()
        chart = theme.chart.model_dump()
        body_font = theme.layout.font.family.body

        assert chart["axis"]["labelFont"] == body_font
        assert chart["axis"]["titleFont"] == body_font
        assert chart["title"]["font"] == body_font
        assert chart["legend"]["labelFont"] == body_font
        assert chart["legend"]["titleFont"] == body_font

    def test_layout_font_size_scale(self):
        """Layout font size tokens form a monotonically increasing scale."""
        theme = load_theme()
        sizes = theme.layout.font.size
        assert sizes.xs < sizes.sm < sizes.md < sizes.lg < sizes.xl

    def test_layout_font_weight_scale(self):
        """Layout font weight tokens form a monotonically increasing scale."""
        theme = load_theme()
        weights = theme.layout.font.weight
        assert weights.normal < weights.medium < weights.semibold < weights.bold

    def test_all_presets_have_valid_colors(self):
        """After resolution, every preset color is a hex string."""
        theme = load_theme()
        for name, preset in theme.layout.presets.items():
            assert preset.color.startswith("#"), (
                f"Preset '{name}' color not resolved: {preset.color}"
            )

    def test_chart_section_category_palette_length(self):
        """Chart category palette has exactly 8 distinct colors."""
        theme = load_theme()
        palette = theme.chart.model_dump()["range"]["category"]
        assert len(palette) == 8
        assert len(set(palette)) == 8, "Category palette has duplicate colors"

    def test_chart_visual_qa_values(self):
        """Verify all chart section values match the visual QA checklist."""
        theme = load_theme()
        chart = theme.chart.model_dump()

        # Background and view
        assert chart["background"] == "#ffffff"
        assert chart["view"]["fill"] == "#f8f9fa"
        assert chart["padding"] == 16

        # Mark default
        assert chart["mark"]["color"] == "#4A90D9"

        # Axis
        assert chart["axis"]["labelFontSize"] == 11
        assert chart["axis"]["titleFontSize"] == 12
        assert chart["axis"]["gridColor"] == "#f0f0f0"
        assert chart["axis"]["domainColor"] == "#9ca3af"
        assert chart["axis"]["tickColor"] == "#9ca3af"

        # Title
        assert chart["title"]["fontSize"] == 16
        assert chart["title"]["fontWeight"] == 600

        # Legend
        assert chart["legend"]["labelFontSize"] == 11
        assert chart["legend"]["titleFontSize"] == 12

        # Bar corner radius
        assert chart["bar"]["cornerRadius"] == 2
        assert chart["rect"]["cornerRadius"] == 2
