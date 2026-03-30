"""
Dashboard Composition Tests

Tests end-to-end composition: dashboard YAML → chart compilation → layout
translation → single HTML output. Also tests CLI dashboard detection.
"""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import DATA_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR

from src.compose.dashboard import compose_dashboard
from src.theme.merge import load_theme

THEMES_DIR = Path(__file__).parent / "fixtures" / "themes"


# ─── Helpers ──────────────────────────────────────────────────────


def _compose(fixture_name: str, **kwargs) -> str:
    """Compose a dashboard from a layout fixture file."""
    dashboard_path = LAYOUT_DIR / fixture_name
    return compose_dashboard(
        dashboard_path=dashboard_path,
        chart_base_dir=YAML_DIR,
        data_dir=DATA_DIR,
        models_dir=MODELS_DIR,
        **kwargs,
    )


# ─── Happy Path Tests ────────────────────────────────────────────


class TestDashboardCompose:
    def test_compose_minimal_dashboard(self):
        """Single chart dashboard produces valid HTML with vegaEmbed."""
        html = _compose("compose_minimal.yaml")
        assert "<!DOCTYPE html>" in html
        assert "<title>Compose Test</title>" in html
        assert 'id="sheet-revenue_chart"' in html
        assert '"sheet-revenue_chart"' in html  # spec key in vegaEmbed script
        assert "vegaEmbed" in html
        assert '"mark"' in html

    def test_compose_multi_chart_dashboard(self):
        """Multiple charts in one dashboard, each compiled and embedded."""
        html = _compose("compose_multi.yaml")
        assert 'id="sheet-bar_chart"' in html
        assert 'id="sheet-line_chart"' in html
        assert '"sheet-bar_chart"' in html
        assert '"sheet-line_chart"' in html
        assert "vegaEmbed" in html

    def test_compose_with_non_chart_components(self):
        """Mixed component types (text + sheets) compose correctly."""
        html = _compose("compose_with_text.yaml")
        assert "Dashboard Title" in html
        assert "Updated daily" in html
        assert 'id="sheet-revenue_chart"' in html
        assert '"sheet-revenue_chart"' in html
        assert "vegaEmbed" in html

    def test_compose_with_custom_theme(self):
        """Custom themes flow through to both chart specs and layout HTML."""
        custom_theme = load_theme(THEMES_DIR / "custom_brand.yaml")
        html = _compose("compose_minimal.yaml", theme=custom_theme)
        assert "font-family:" in html

    def test_compose_predefined_components(self):
        """Sheets in the components block (string ref) are discovered and compiled."""
        html = _compose("compose_predefined.yaml")
        assert 'id="sheet-revenue"' in html
        assert '"sheet-revenue"' in html
        assert "vegaEmbed" in html

    def test_compose_with_fit_modes(self):
        """fit property flows through to VL spec and CSS."""
        html = _compose("compose_fit.yaml")
        assert 'id="sheet-wide_chart"' in html
        assert 'id="sheet-full_chart"' in html
        # fit: width → VL width: "container"
        assert '"width": "container"' in html
        # fit: fill → both dimensions
        assert '"height": "container"' in html
        # CSS overflow rules
        assert "overflow-y: auto" in html  # from fit: width
        assert "overflow: hidden" in html  # from fit: fill

    def test_compose_no_theme(self):
        """no_theme=True skips theme merging for charts and layout."""
        html = _compose("compose_minimal.yaml", no_theme=True)
        assert "<!DOCTYPE html>" in html
        assert 'id="sheet-revenue_chart"' in html
        assert '"sheet-revenue_chart"' in html
        assert "vegaEmbed" in html

    def test_compose_dashboard_with_no_sheets(self):
        """Dashboard with only text components produces valid HTML, no vegaEmbed calls."""
        # Inline spec — no fixture needed
        from src.schema.layout_schema import parse_dashboard
        from src.theme.merge import load_theme as lt
        from src.translator.layout import translate_dashboard

        yaml_str = """
dashboard: "Text Only"
canvas: { width: 800, height: 600 }
root:
  type: root
  orientation: vertical
  contains:
    - type: text
      content: "Just text"
      preset: title
"""
        spec = parse_dashboard(yaml_str)
        theme = lt()
        html = translate_dashboard(spec, theme, chart_specs={})
        assert "<!DOCTYPE html>" in html
        assert "Just text" in html
        assert "vegaEmbed" not in html


# ─── Error Tests ─────────────────────────────────────────────────


class TestDashboardComposeErrors:
    def test_compose_missing_chart_file(self):
        """Missing chart link raises FileNotFoundError with filename."""
        yaml_str = """
dashboard: "Bad Link"
canvas: { width: 800, height: 600 }
root:
  type: root
  orientation: vertical
  contains:
    - bad_chart:
        type: sheet
        link: "does_not_exist.yaml"
"""
        dashboard_path = LAYOUT_DIR / "_tmp_missing.yaml"
        dashboard_path.write_text(yaml_str)
        try:
            with pytest.raises(FileNotFoundError, match="does_not_exist.yaml"):
                compose_dashboard(
                    dashboard_path=dashboard_path,
                    chart_base_dir=YAML_DIR,
                )
        finally:
            dashboard_path.unlink(missing_ok=True)

    def test_compose_invalid_chart_yaml(self):
        """Invalid chart YAML propagates error with sheet context."""
        # Create a chart YAML that's valid YAML but invalid DSL (no sheet field)
        bad_chart = YAML_DIR / "_tmp_bad_chart.yaml"
        bad_chart.write_text("invalid_key: true\n")

        dashboard_yaml = """
dashboard: "Bad Chart"
canvas: { width: 800, height: 600 }
root:
  type: root
  orientation: vertical
  contains:
    - broken:
        type: sheet
        link: "_tmp_bad_chart.yaml"
"""
        dashboard_path = LAYOUT_DIR / "_tmp_bad_chart_dashboard.yaml"
        dashboard_path.write_text(dashboard_yaml)
        try:
            with pytest.raises(Exception, match="broken"):
                compose_dashboard(
                    dashboard_path=dashboard_path,
                    chart_base_dir=YAML_DIR,
                )
        finally:
            bad_chart.unlink(missing_ok=True)
            dashboard_path.unlink(missing_ok=True)


# ─── CLI Tests ───────────────────────────────────────────────────


class TestCLI:
    def test_cli_detects_dashboard_yaml(self):
        """CLI auto-detects dashboard files and routes to dashboard pipeline."""
        result = subprocess.run(
            [
                ".venv/bin/python",
                "-m",
                "src.cli.render",
                "tests/fixtures/layout/compose_minimal.yaml",
                "--chart-dir",
                "tests/fixtures/yaml",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Rendered:" in result.stdout
        output_path = Path(__file__).parent.parent / "output" / "compose-test.html"
        assert output_path.exists()
        html = output_path.read_text()
        assert "<!DOCTYPE html>" in html
        assert "vegaEmbed" in html

    def test_cli_chart_yaml_still_works(self):
        """Existing chart rendering still works — no regression."""
        result = subprocess.run(
            [
                ".venv/bin/python",
                "-m",
                "src.cli.render",
                "tests/fixtures/yaml/simple_bar.yaml",
                "--data",
                "tests/fixtures/data/orders.json",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Rendered:" in result.stdout
