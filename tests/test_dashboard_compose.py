"""
Dashboard Composition Tests — Type-Led Syntax

Tests end-to-end composition: dashboard YAML → chart compilation → layout
translation → single HTML output. Also tests CLI dashboard detection.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from shelves.compose.dashboard import (
    _discover_controls,
    compose_dashboard,
)
from shelves.schema.layout_schema import parse_dashboard
from shelves.theme.merge import load_theme
from shelves.translator.layout_flatten import flatten_dashboard
from tests.conftest import DATA_DIR, FIXTURES_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR

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
    def test_compose_flattens_tree_once(self, monkeypatch):
        """compose_dashboard should flatten the layout tree exactly once and
        thread it to sheet discovery, legend discovery, and translate_dashboard —
        not re-flatten in each (it rebuilds the full tree with style merging)."""
        import shelves.compose.dashboard as compose_mod
        import shelves.translator.layout as layout_mod

        counts = {"compose": 0, "layout": 0}
        orig = compose_mod.flatten_dashboard

        def counting_compose(spec):
            counts["compose"] += 1
            return orig(spec)

        def counting_layout(spec):
            counts["layout"] += 1
            return orig(spec)

        monkeypatch.setattr(compose_mod, "flatten_dashboard", counting_compose)
        monkeypatch.setattr(layout_mod, "flatten_dashboard", counting_layout)

        _compose("compose_minimal.yaml")

        # Flattened once in compose and reused everywhere downstream.
        assert counts["compose"] == 1
        assert counts["layout"] == 0

    def test_compose_minimal_dashboard(self):
        """Single chart dashboard produces valid HTML with vegaEmbed."""
        html = _compose("compose_minimal.yaml")
        assert "<!DOCTYPE html>" in html
        assert "<title>Compose Test</title>" in html
        assert 'id="sheet-revenue_chart"' in html
        assert "vegaEmbed" in html
        assert '"mark"' in html

    def test_compose_multi_chart_dashboard(self):
        """Multiple charts in one dashboard, each compiled and embedded."""
        html = _compose("compose_multi.yaml")
        assert 'id="sheet-bar_chart"' in html
        assert 'id="sheet-line_chart"' in html
        assert "vegaEmbed" in html

    def test_compose_with_non_chart_components(self):
        """Mixed component types (text + sheets) compose correctly."""
        html = _compose("compose_with_text.yaml")
        assert "Dashboard Title" in html
        assert "Updated daily" in html
        assert 'id="sheet-revenue_chart"' in html
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
        assert "vegaEmbed" in html

    def test_compose_predefined_with_divergent_name(self):
        """When a predefined component's ref name differs from its name property,
        the chart spec key and HTML element ID must still match (both use ref name)."""

        # Write a temp fixture: ref name is "rev_kpi", but name property is "revenue"
        yaml_str = """\
dashboard: "Divergent Name"
canvas: { width: 800, height: 600 }
components:
  rev_kpi:
    sheet: simple_bar.yaml
    name: revenue
root:
  orientation: vertical
  contains:
    - rev_kpi
"""
        dashboard_path = LAYOUT_DIR / "_tmp_divergent_name.yaml"
        dashboard_path.write_text(yaml_str)
        try:
            html = compose_dashboard(
                dashboard_path=dashboard_path,
                chart_base_dir=YAML_DIR,
                data_dir=DATA_DIR,
                models_dir=MODELS_DIR,
            )
            # The ref name "rev_kpi" should be used everywhere, not "revenue"
            assert 'id="sheet-rev_kpi"' in html
            assert "vegaEmbed" in html
            # The chart spec must be keyed by the same name used in the DOM
            assert "sheet-rev_kpi" in html
        finally:
            dashboard_path.unlink(missing_ok=True)

    def test_compose_with_fit_modes(self):
        """fit property flows through to VL spec and CSS."""
        html = _compose("compose_fit.yaml")
        assert 'id="sheet-wide_chart"' in html
        assert 'id="sheet-full_chart"' in html
        assert '"width": "container"' in html
        assert "overflow-y: auto" in html
        assert "overflow: hidden" in html

    def test_compose_no_theme(self):
        """no_theme=True skips theme merging for charts and layout."""
        html = _compose("compose_minimal.yaml", no_theme=True)
        assert "<!DOCTYPE html>" in html
        assert 'id="sheet-revenue_chart"' in html
        assert "vegaEmbed" in html

    def test_no_theme_overrides_explicit_theme(self):
        """no_theme=True must ignore an explicitly provided theme."""
        custom_theme = load_theme()
        result_with_theme = _compose("compose_minimal.yaml", theme=custom_theme, no_theme=True)
        result_no_theme = _compose("compose_minimal.yaml", no_theme=True)
        # Both have no_theme=True — the explicit theme should be discarded,
        # so both should produce identical output.
        assert result_with_theme == result_no_theme

    def test_compose_dashboard_with_no_sheets(self):
        """Dashboard with only text components produces valid HTML, no vegaEmbed calls."""
        from shelves.schema.layout_schema import parse_dashboard
        from shelves.theme.merge import load_theme as lt
        from shelves.translator.layout import translate_dashboard

        yaml_str = """\
dashboard: "Text Only"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Just text"
      preset: title
"""
        spec = parse_dashboard(yaml_str)
        theme = lt()
        html = translate_dashboard(spec, theme, chart_specs={})
        assert "<!DOCTYPE html>" in html
        assert "Just text" in html
        assert "vegaEmbed" not in html


# ─── Rendered Signal (SHE-67) ────────────────────────────────────


class TestDashboardRenderedSignal:
    """The composed page must post {type:'shelves:rendered'} to its parent
    once every embed promise has settled — Studio's dashboard preview holds
    its loading veil until this message; other hosts simply never listen."""

    def test_embeds_collected_and_signal_posted(self):
        html = _compose("compose_multi.yaml")
        assert "embeds.push(vegaEmbed" in html
        assert "Promise.allSettled(embeds)" in html
        assert "parent.postMessage({ type: 'shelves:rendered' }, '*')" in html

    def test_no_sheet_dashboard_still_posts_signal(self):
        """With no charts the signal must fire immediately, or Studio's veil
        would only clear on its fallback timeout."""
        from shelves.schema.layout_schema import parse_dashboard
        from shelves.translator.layout import translate_dashboard

        yaml_str = """\
dashboard: "Text Only"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Just text"
      preset: title
"""
        spec = parse_dashboard(yaml_str)
        html = translate_dashboard(spec, load_theme(), chart_specs={})
        assert "Promise.allSettled(embeds)" in html
        assert "parent.postMessage({ type: 'shelves:rendered' }, '*')" in html


class TestVegaScriptSources:
    """SHE-77: standalone HTML loads the pinned CDN URLs; a caller (Studio)
    can redirect the three render libs to a same-origin vendored base."""

    def test_compose_defaults_to_pinned_cdn(self):
        from shelves.render.to_html import VEGA_LIB_CDN_URLS

        html = _compose("compose_multi.yaml")
        for url in VEGA_LIB_CDN_URLS:
            assert f'<script src="{url}"></script>' in html

    def test_vega_src_base_swaps_to_vendored(self):
        from shelves.render.to_html import VEGA_LIB_FILES
        from shelves.schema.layout_schema import parse_dashboard
        from shelves.translator.layout import translate_dashboard

        yaml_str = """\
dashboard: "Vendored"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Just text"
      preset: title
"""
        spec = parse_dashboard(yaml_str)
        html = translate_dashboard(
            spec, load_theme(), chart_specs={}, vega_src_base="/static/vendor"
        )
        for name in VEGA_LIB_FILES:
            assert f'<script src="/static/vendor/{name}"></script>' in html
        assert "jsdelivr.net/npm/vega" not in html


# ─── Warning Tests ───────────────────────────────────────────────


class TestDashboardComposeWarnings:
    def test_data_resolution_failure_warns_and_still_renders(self, monkeypatch):
        """A data-resolution failure must never be silent (it used to be
        swallowed by contextlib.suppress): the dashboard still renders — the
        chart just has no data — and a warning names the sheet and the cause."""
        import shelves.pipeline as pipeline_mod

        def boom(vl, spec, **kwargs):
            raise RuntimeError("simulated data failure")

        monkeypatch.setattr(pipeline_mod, "resolve_model_data", boom)

        with pytest.warns(UserWarning, match="Data resolution skipped for 'revenue_chart'"):
            html = _compose("compose_minimal.yaml")

        assert 'id="sheet-revenue_chart"' in html
        assert "vegaEmbed" in html

    def test_studio_route_uses_the_same_chart_loop(self, monkeypatch):
        """Guard the unification: run_dashboard_pipeline must go through
        compile_dashboard_charts, not its own per-sheet loop."""
        import asyncio

        import shelves.compose.dashboard as compose_mod
        from shelves.studio.routes.dashboard import run_dashboard_pipeline

        calls = {"n": 0}
        orig = compose_mod.compile_dashboard_charts

        def counting(*args, **kwargs):
            calls["n"] += 1
            return orig(*args, **kwargs)

        monkeypatch.setattr(compose_mod, "compile_dashboard_charts", counting)

        yaml_body = (
            'dashboard: "Shared Loop"\n'
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - sheet: simple_bar.yaml\n"
            "      name: revenue_chart\n"
        )
        result = asyncio.run(
            run_dashboard_pipeline(
                yaml_body,
                project_dir=FIXTURES_DIR,
                charts_dir=YAML_DIR,
                theme_path=None,
                models_dir=MODELS_DIR,
            )
        )
        assert result["html"] is not None
        assert calls["n"] == 1

    def test_relative_parent_links_still_work_in_compose(self, tmp_path):
        """Link containment (restrict_links) is a Studio-surface concern — the
        CLI compose path deliberately keeps ../ links working, since local
        dashboards may legitimately reference charts outside --chart-dir."""
        import shutil

        charts = tmp_path / "charts"
        charts.mkdir()
        shutil.copy(YAML_DIR / "simple_bar.yaml", tmp_path / "outside.yaml")

        dashboard_path = tmp_path / "dash.yaml"
        dashboard_path.write_text(
            'dashboard: "Parent Link"\n'
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - sheet: ../outside.yaml\n"
            "      name: outside_chart\n"
        )

        html = compose_dashboard(
            dashboard_path=dashboard_path,
            chart_base_dir=charts,
            data_dir=DATA_DIR,
            models_dir=MODELS_DIR,
        )
        assert 'id="sheet-outside_chart"' in html
        assert "vegaEmbed" in html


class TestCompileDashboardChartsStructuredWarnings:
    """SHE-105: `compile_dashboard_charts` returns structured warning dicts
    (`{msg, code, sheet, child_loc}`), not bare strings; both surfaces consume
    that one shape."""

    def _compile(self, sheets: dict[str, str], **kwargs):
        from shelves.compose.dashboard import compile_dashboard_charts

        theme = load_theme()
        return compile_dashboard_charts(
            sheets,
            YAML_DIR,
            theme,
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            **kwargs,
        )

    def test_child_warning_is_structured_and_sheet_tagged(self):
        _specs, _resolvers, warnings = self._compile({"c1": "tooltip_disaggregation.yaml"})
        tt = [w for w in warnings if w["code"] == "tooltip_disaggregation"]
        assert len(tt) == 1
        w = tt[0]
        assert w["sheet"] == "c1"
        assert w["msg"].startswith("Sheet 'c1': ")
        assert "region" in w["msg"]
        # child_loc points into the *child* file (informational only).
        assert tuple(w["child_loc"]) == ("tooltip", 0)

    def test_missing_file_warning_is_structured(self):
        _specs, _resolvers, warnings = self._compile({"ghost": "nope.yaml"}, fail_fast=False)
        assert len(warnings) == 1
        w = warnings[0]
        assert w["sheet"] == "ghost"
        assert w["code"] is None
        assert w["child_loc"] is None
        assert "Chart file not found" in w["msg"]

    def test_compose_reemits_structured_warning_message(self):
        """compose_dashboard re-emits each structured warning's message via
        warnings.warn — the human-readable text is unchanged."""
        self_yaml = LAYOUT_DIR / "_tmp_tooltip_dash.yaml"
        self_yaml.write_text(
            'dashboard: "TT"\n'
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - sheet: tooltip_disaggregation.yaml\n"
            "      name: c1\n"
        )
        try:
            with pytest.warns(UserWarning, match=r"Sheet 'c1': Tooltip field 'region'"):
                compose_dashboard(
                    dashboard_path=self_yaml,
                    chart_base_dir=YAML_DIR,
                    data_dir=FIXTURES_DIR,
                    models_dir=MODELS_DIR,
                )
        finally:
            self_yaml.unlink(missing_ok=True)


# ─── Error Tests ─────────────────────────────────────────────────


class TestDashboardComposeErrors:
    def test_compose_missing_chart_file(self):
        yaml_str = """\
dashboard: "Bad Link"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: does_not_exist.yaml
      name: bad_chart
"""
        dashboard_path = LAYOUT_DIR / "_tmp_missing.yaml"
        dashboard_path.write_text(yaml_str)
        try:
            with pytest.raises(FileNotFoundError, match=r"does_not_exist\.yaml"):
                compose_dashboard(
                    dashboard_path=dashboard_path,
                    chart_base_dir=YAML_DIR,
                )
        finally:
            dashboard_path.unlink(missing_ok=True)

    def test_compose_invalid_chart_yaml(self):
        bad_chart = YAML_DIR / "_tmp_bad_chart.yaml"
        bad_chart.write_text("invalid_key: true\n")

        dashboard_yaml = """\
dashboard: "Bad Chart"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: _tmp_bad_chart.yaml
      name: broken
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
                sys.executable,
                "-m",
                "shelves.cli.render",
                "tests/fixtures/layout/compose_minimal.yaml",
                "--chart-dir",
                "tests/fixtures/yaml",
                "--models-dir",
                "tests/fixtures/models",
                "--data-dir",
                "tests/fixtures",
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
                sys.executable,
                "-m",
                "shelves.cli.render",
                "tests/fixtures/yaml/simple_bar.yaml",
                "--data",
                "tests/fixtures/data/orders.json",
                "--models-dir",
                "tests/fixtures/models",
                "--data-dir",
                "tests/fixtures",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Rendered:" in result.stdout


# ─── Parameter Control Discovery (SHE-97: renamed from control) ──


class TestParameterCompose:
    """SHE-97: end-to-end compose with parameter components → HTML with data-param attrs."""

    def test_compose_parameter_dashboard(self):
        from shelves.params.resolve import load_parameter_set

        parameters = load_parameter_set(
            MODELS_DIR / "parameters.yaml",
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )
        html = _compose("control_dashboard.yaml", parameters=parameters)
        assert "<!DOCTYPE html>" in html
        assert 'data-param="metric"' in html
        assert 'data-param="status"' in html
        assert 'data-param="top_n"' in html
        # Inline label override on status parameter
        assert 'data-title="Order Status"' in html
        # Widget inference: metric=field→dropdown, top_n=number range→stepper
        assert 'data-control="dropdown"' in html
        assert 'data-control="stepper"' in html
        # control_render.js inlined
        assert "controlRender" in html
        # The sheet still renders
        assert "vegaEmbed" in html

    def test_compose_parameter_with_override(self):
        from shelves.params.resolve import load_parameter_set

        parameters = load_parameter_set(
            MODELS_DIR / "parameters.yaml",
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            overrides={"metric": "cost"},
        )
        html = _compose("control_dashboard.yaml", parameters=parameters)
        assert "data-default='&quot;cost&quot;'" in html

    def test_compose_parameter_undeclared_param_raises(self):
        yaml_str = """\
dashboard: "Bad Parameter"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - parameter: nonexistent
"""
        dashboard_path = LAYOUT_DIR / "_tmp_bad_parameter.yaml"
        dashboard_path.write_text(yaml_str)
        try:
            with pytest.raises(ValueError, match="nonexistent"):
                compose_dashboard(
                    dashboard_path=dashboard_path,
                    chart_base_dir=YAML_DIR,
                    data_dir=DATA_DIR,
                    models_dir=MODELS_DIR,
                )
        finally:
            dashboard_path.unlink(missing_ok=True)


class TestParameterDiscovery:
    """SHE-97: _discover_controls walks a flat tree collecting parameter components."""

    def test_discover_controls_finds_all(self):
        spec = parse_dashboard("""\
dashboard: "Parameters"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - horizontal:
        gap: 16
        contains:
          - parameter: metric
          - parameter: status
    - sheet: charts/foo.yaml
      name: chart_1
""")
        flat = flatten_dashboard(spec)
        controls = _discover_controls(flat)
        assert set(controls.values()) == {"metric", "status"}
        assert len(controls) == 2

    def test_discover_controls_empty_when_none(self):
        spec = parse_dashboard("""\
dashboard: "No Parameters"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: chart_1
""")
        flat = flatten_dashboard(spec)
        controls = _discover_controls(flat)
        assert controls == {}

    def test_discover_controls_nested(self):
        spec = parse_dashboard("""\
dashboard: "Nested"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - vertical:
        contains:
          - horizontal:
              contains:
                - parameter: top_n
""")
        flat = flatten_dashboard(spec)
        controls = _discover_controls(flat)
        assert "top_n" in controls.values()
