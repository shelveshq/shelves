"""
SHE-84: control/filter `text` theme token.

`_inputStyle`/`_labelStyle` in control_render.js set a background from the
surface token but no color, so widget text is invisible on a dark control or
filter surface. A `text` token on both `ControlTokens` and `FilterTokens`,
emitted as `--shelves-control-text` / `--shelves-filter-text`, fixes it.
"""

from pathlib import Path

from shelves.compose.dashboard import compose_dashboard
from shelves.theme.merge import load_theme
from shelves.theme.theme_schema import ControlTokens, FilterTokens
from tests.conftest import DATA_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR


def _compose(fixture_name: str, **kwargs) -> str:
    return compose_dashboard(
        dashboard_path=LAYOUT_DIR / fixture_name,
        chart_base_dir=YAML_DIR,
        data_dir=DATA_DIR,
        models_dir=MODELS_DIR,
        **kwargs,
    )


class TestTextTokenSchema:
    def test_control_tokens_default_text(self):
        assert ControlTokens().text == "#1a1a1a"

    def test_filter_tokens_default_text(self):
        assert FilterTokens().text == "#1a1a1a"

    def test_text_is_overridable(self):
        assert FilterTokens(text="#eeeeee").text == "#eeeeee"


class TestTextTokenEmission:
    def test_filter_dashboard_emits_both_text_tokens(self):
        html = _compose("filter_dashboard.yaml")
        assert "--shelves-control-text:" in html
        assert "--shelves-filter-text:" in html

    def test_default_text_value_emitted(self):
        html = _compose("filter_dashboard.yaml")
        assert "--shelves-filter-text: #1a1a1a" in html

    def test_custom_text_flows_through(self):
        theme = load_theme()
        theme.layout.filter.text = "#f0f0f0"
        theme.layout.control.text = "#0f0f0f"
        html = _compose("filter_dashboard.yaml", theme=theme)
        assert "--shelves-filter-text: #f0f0f0" in html
        assert "--shelves-control-text: #0f0f0f" in html


class TestDefaultThemeYaml:
    def test_default_theme_yaml_lists_text(self):
        text = Path("shelves/theme/default_theme.yaml").read_text(encoding="utf-8")
        # Both control and filter blocks name the token for discoverability.
        assert text.count("text:") >= 2
