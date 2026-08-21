"""
SHE-85: legend `--shelves-legend-*` theme tokens.

`legend_render.js` carried hardcoded swatch/label/title/gradient styles with
"no dedicated theme tokens yet" comments. This retrofits them onto the same
`layout.*` → CSS-custom-property mechanism SHE-82 built for filters: a
`LegendTokens` block (defaults exactly matching the historical values) emitted
as `--shelves-legend-*` on any dashboard that has legends, with the JS reading
`var(--shelves-legend-*, <default>)` so it still renders standalone.

Contract: `docs/foundational/Filter Specification.md` §9; gate: verify-render
(pixel-identical default — screenshot-checked separately).
"""

from pathlib import Path

from shelves.compose.dashboard import compose_dashboard
from shelves.theme.merge import load_theme
from shelves.theme.theme_schema import LegendTokens
from tests.conftest import DATA_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR


def _compose(fixture_name: str, **kwargs) -> str:
    return compose_dashboard(
        dashboard_path=LAYOUT_DIR / fixture_name,
        chart_base_dir=YAML_DIR,
        data_dir=DATA_DIR,
        models_dir=MODELS_DIR,
        **kwargs,
    )


class TestLegendTokenSchema:
    def test_defaults_match_historical_hardcoded_values(self):
        lg = LegendTokens()
        assert lg.font_size == 12
        assert lg.title_weight == 600
        assert lg.swatch_size == 12
        assert lg.swatch_radius == 2
        assert lg.gap == 4
        assert lg.gap_horizontal == 12

    def test_tokens_are_overridable(self):
        assert LegendTokens(font_size=16, swatch_size=20).font_size == 16
        assert LegendTokens(font_size=16, swatch_size=20).swatch_size == 20


class TestLegendTokenEmission:
    def test_legend_dashboard_emits_legend_tokens(self):
        html = _compose("legend_link_color.yaml")
        assert "--shelves-legend-font-size:" in html
        assert "--shelves-legend-title-weight:" in html
        assert "--shelves-legend-swatch-size:" in html
        assert "--shelves-legend-swatch-radius:" in html
        assert "--shelves-legend-gap:" in html
        assert "--shelves-legend-gap-horizontal:" in html

    def test_default_values_emitted(self):
        html = _compose("legend_link_color.yaml")
        assert "--shelves-legend-font-size: 12px" in html
        assert "--shelves-legend-title-weight: 600" in html
        assert "--shelves-legend-swatch-size: 12px" in html

    def test_custom_tokens_flow_through(self):
        theme = load_theme()
        theme.layout.legend.font_size = 16
        theme.layout.legend.swatch_size = 20
        html = _compose("legend_link_color.yaml", theme=theme)
        assert "--shelves-legend-font-size: 16px" in html
        assert "--shelves-legend-swatch-size: 20px" in html


class TestDefaultThemeYaml:
    def test_default_theme_yaml_lists_legend_block(self):
        text = Path("shelves/theme/default_theme.yaml").read_text(encoding="utf-8")
        assert "legend:" in text
        assert "swatch_size: 12" in text
        assert "title_weight: 600" in text
