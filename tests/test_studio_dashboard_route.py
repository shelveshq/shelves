"""
Studio dashboard route tests — KAN-298

The Studio dashboard preview must render the dashboard on its declared canvas
size. The backend contract for that is: the /compile-dashboard pipeline returns
the declared (or default) canvas dimensions so the frontend can pin the iframe.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from shelves.studio.routes.dashboard import run_dashboard_pipeline
from tests.conftest import FIXTURES_DIR, MODELS_DIR, YAML_DIR


def _run(coro):
    return asyncio.run(coro)


def _pipeline(
    yaml_body: str,
    parameters_path: Path | None = None,
    overrides: dict[str, str] | None = None,
) -> dict:
    """Run the dashboard pipeline against the shared chart/model fixtures.

    `parameters_path` defaults to `<models_dir>/parameters.yaml`; pass a
    non-existent path to run against a project that declares no parameters.
    """

    async def _test():
        return await run_dashboard_pipeline(
            yaml_body,
            project_dir=FIXTURES_DIR,
            charts_dir=YAML_DIR,  # simple_bar.yaml / scatter.yaml / dual_axis.yaml
            theme_path=None,
            models_dir=MODELS_DIR,  # orders.yaml model → field labels/types
            parameters_path=parameters_path,
            overrides=overrides,
        )

    return _run(_test())


def _legend_attrs(html: str) -> str:
    """Return the attribute string between the legend div's id and style."""
    m = re.search(r'<div id="legend-[^"]+"([^>]*) style=', html)
    assert m is not None, "legend div not found"
    return m.group(1)


def _embedded_specs(html: str) -> dict:
    """Parse the `const specs = {...};` block from the dashboard HTML."""
    m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
    assert m is not None, "embedded specs block not found"
    return json.loads(m.group(1))


class TestCompileDashboardCanvas:
    def test_compile_dashboard_returns_declared_canvas(self, tmp_path: Path):
        yaml_body = (
            'dashboard: "Canvas Test"\n'
            "canvas:\n"
            "  width: 1024\n"
            "  height: 768\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            '    - text: "Hello"\n'
            "      preset: title\n"
        )

        async def _test():
            return await run_dashboard_pipeline(
                yaml_body,
                project_dir=tmp_path,
                charts_dir=tmp_path,
                theme_path=None,
                models_dir=None,
            )

        result = _run(_test())
        assert result["html"] is not None
        assert result["canvas"] == {"width": 1024, "height": 768}

    def test_compile_dashboard_default_canvas(self, tmp_path: Path):
        yaml_body = (
            'dashboard: "Default Canvas"\n'
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            '    - text: "Hi"\n'
            "      preset: title\n"
        )

        async def _test():
            return await run_dashboard_pipeline(
                yaml_body,
                project_dir=tmp_path,
                charts_dir=tmp_path,
                theme_path=None,
                models_dir=None,
            )

        result = _run(_test())
        assert result["canvas"] == {"width": 1440, "height": 900}


class TestStudioMissingChart:
    def test_missing_chart_file_warns_and_renders_rest(self, tmp_path: Path):
        """A missing chart link is a per-sheet warning, not a whole-dashboard
        error — consistent with how a chart that fails to compile behaves
        (the dashboard renders, the sheet is an empty box)."""
        yaml_body = (
            'dashboard: "Missing Link"\n'
            "canvas:\n"
            "  width: 800\n"
            "  height: 600\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            '    - text: "Still here"\n'
            "      preset: title\n"
            "    - sheet: does_not_exist.yaml\n"
            "      name: ghost\n"
        )

        async def _test():
            return await run_dashboard_pipeline(
                yaml_body,
                project_dir=tmp_path,
                charts_dir=tmp_path,
                theme_path=None,
                models_dir=None,
            )

        result = _run(_test())
        assert result["html"] is not None
        assert result["errors"] == []
        assert "Still here" in result["html"]
        assert any("Chart file not found" in w and "ghost" in w for w in result["warnings"])
        # The warning shows the link the user typed, not the server's absolute
        # path (PR #58 review: don't leak filesystem paths to Studio users).
        assert not any(str(tmp_path) in w for w in result["warnings"])

    def test_traversal_link_is_rejected_with_warning(self, tmp_path: Path):
        """A link that escapes charts_dir (../ or absolute) is skipped with a
        warning in the Studio pipeline — dashboard YAML must not read files
        outside the charts directory (PR #58 review; mirrors resolve_safe)."""
        charts = tmp_path / "charts"
        charts.mkdir()
        # A perfectly valid chart OUTSIDE charts_dir — reachable only by traversal.
        (tmp_path / "outside.yaml").write_text(
            "sheet: Outside\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
        )

        for link in ("../outside.yaml", str(tmp_path / "outside.yaml")):
            yaml_body = (
                'dashboard: "Traversal"\n'
                "canvas:\n"
                "  width: 800\n"
                "  height: 600\n"
                "root:\n"
                "  orientation: vertical\n"
                "  contains:\n"
                f"    - sheet: {link}\n"
                "      name: sneaky\n"
            )

            async def _test(body=yaml_body):
                return await run_dashboard_pipeline(
                    body,
                    project_dir=FIXTURES_DIR,
                    charts_dir=charts,
                    theme_path=None,
                    models_dir=MODELS_DIR,
                )

            result = _run(_test())
            assert result["html"] is not None
            assert result["errors"] == []
            assert any(
                "outside the charts directory" in w and "sneaky" in w for w in result["warnings"]
            ), f"no traversal warning for link {link!r}: {result['warnings']}"
            # The chart must NOT have been compiled/embedded.
            assert "Outside" not in result["html"]


class TestStudioDashboardLegends:
    """SHE-27 — independent dashboard legends wired into the Studio preview."""

    def test_color_legend_links_and_suppresses(self):
        yaml_body = (
            'dashboard: "Legend Link Color"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: simple_bar.yaml\n"
            "      name: sales_chart\n"
            "    - legend: simple_bar.yaml\n"
            "      field: country\n"
            "      width: 180\n"
        )
        result = _pipeline(yaml_body)
        assert result["errors"] == []

        html = result["html"]
        assert html is not None

        # 1. The legend placeholder carries the resolved data attributes.
        attrs = _legend_attrs(html)
        assert 'data-source="sheet-sales_chart"' in attrs
        assert 'data-channel="color"' in attrs
        assert "data-scale" not in attrs

        # 2. The embedded sheet spec has the in-sheet color legend suppressed.
        specs = _embedded_specs(html)
        assert specs["sheet-sales_chart"]["encoding"]["color"]["legend"] is None

        # 3. The legend links its only legend-producing channel → NO warning.
        assert result["warnings"] == []

    def test_size_legend_links(self):
        yaml_body = (
            'dashboard: "Legend Link Size"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: scatter.yaml\n"
            "      name: scatter_chart\n"
            "    - legend: scatter.yaml\n"
            "      field: revenue\n"
            "      width: 180\n"
        )
        result = _pipeline(yaml_body)
        assert result["errors"] == []

        html = result["html"]
        attrs = _legend_attrs(html)
        assert 'data-channel="size"' in attrs
        assert "data-scale" not in attrs
        assert 'data-source="sheet-scatter_chart"' in attrs

        specs = _embedded_specs(html)
        # size suppressed (linked) AND color suppressed (always-suppress):
        assert specs["sheet-scatter_chart"]["encoding"]["size"]["legend"] is None
        assert specs["sheet-scatter_chart"]["encoding"]["color"]["legend"] is None

        # scatter.yaml also color-encodes `country` with no legend element → one
        # warning, surfaced in the Studio warnings list (NOT a Python warning).
        assert any("color" in w and "scatter_chart" in w for w in result["warnings"])

    def test_labeled_chart_emits_channel_not_namespaced_scale(self):
        """Studio path: a legend on a labeled chart (name: mark_0) emits only the
        bare channel intent — SHE-28 no longer reconstructs mark_0_color in
        Python. Mirrors the compose path; the browser resolves the live scale."""
        yaml_body = (
            'dashboard: "Legend Labeled"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: label_bar_match_color.yaml\n"
            "      name: labeled_chart\n"
            "    - legend: label_bar_match_color.yaml\n"
            "      field: country\n"
            "      width: 180\n"
        )
        result = _pipeline(yaml_body)
        assert result["errors"] == []

        attrs = _legend_attrs(result["html"])
        assert 'data-channel="color"' in attrs
        assert "data-scale" not in attrs

        specs = _embedded_specs(result["html"])
        assert specs["sheet-labeled_chart"]["encoding"]["color"]["legend"] is None

    def test_unlinked_channel_warns_in_warnings_list(self):
        yaml_body = (
            'dashboard: "Legend Unlinked"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - sheet: simple_bar.yaml\n"
            "      name: sales_chart\n"
        )
        result = _pipeline(yaml_body)
        assert result["errors"] == []
        assert result["html"] is not None

        # Warning surfaced in the Studio warnings panel, NOT via warnings.warn.
        assert any(
            "sales_chart" in w and "color" in w and "no dashboard legend" in w
            for w in result["warnings"]
        )

        specs = _embedded_specs(result["html"])
        assert specs["sheet-sales_chart"]["encoding"]["color"]["legend"] is None

    def test_bad_source_returns_error(self):
        yaml_body = (
            'dashboard: "Legend Bad Source"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: simple_bar.yaml\n"
            "      name: sales_chart\n"
            "    - legend: heatmap.yaml\n"
            "      field: category\n"
            "      width: 180\n"
        )
        result = _pipeline(yaml_body)
        assert result["html"] is None
        assert any(re.search(r"heatmap\.yaml.*no sheet", e) for e in result["errors"])

    def test_field_not_encoded_returns_error(self):
        yaml_body = (
            'dashboard: "Legend Field Not Encoded"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: simple_bar.yaml\n"
            "      name: sales_chart\n"
            "    - legend: simple_bar.yaml\n"
            "      field: revenue\n"
            "      width: 180\n"
        )
        result = _pipeline(yaml_body)
        assert result["html"] is None
        assert any(re.search(r"revenue.*not encoded", e) for e in result["errors"])

    def test_layered_sheet_returns_error(self):
        yaml_body = (
            'dashboard: "Legend Layered"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: dual_axis.yaml\n"
            "      name: dual\n"
            "    - legend: dual_axis.yaml\n"
            "      field: country\n"
            "      width: 180\n"
        )
        result = _pipeline(yaml_body)
        assert result["html"] is None
        assert any(re.search(r"not supported yet", e) for e in result["errors"])

    def test_legend_for_sheet_with_failed_model_load_does_not_crash(self, monkeypatch):
        """#1: a chart that COMPILES but whose model load fails afterward must not
        crash. chart_specs and resolvers must stay in lock-step — the sheet is
        treated as failed (warning) and its legend is filtered out, rather than
        the legend dereferencing a resolver that was never built (KeyError → 500).

        Repro: translate_chart binds `load_model` at its own import time, so chart
        compilation still succeeds; only the route's own re-imported load_model —
        the call that builds the resolver after the spec compiles — sees this
        failure, exactly the divergence the bug requires.
        """
        import shelves.models.loader as loader_mod

        def flaky_load_model(*_args, **_kwargs):
            raise FileNotFoundError("simulated missing model manifest")

        monkeypatch.setattr(loader_mod, "load_model", flaky_load_model)

        yaml_body = (
            'dashboard: "Legend Failed Model"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: simple_bar.yaml\n"
            "      name: sales_chart\n"
            "    - legend: simple_bar.yaml\n"
            "      field: country\n"
            "      width: 180\n"
        )
        # The monkeypatch breaks load_model, so skip parameter resolution.
        result = _pipeline(yaml_body, parameters_path=FIXTURES_DIR / "no_such_parameters.yaml")
        # Does not crash; no unhandled 500 surfaced as an error:
        assert result["html"] is not None
        assert result["errors"] == []
        # The sheet whose resolver failed produced a warning:
        assert any("sales_chart" in w for w in result["warnings"])
        # Its legend rendered as an empty box: no resolved data attributes.
        attrs = _legend_attrs(result["html"])
        assert "data-source" not in attrs
        assert "data-scale" not in attrs

    def test_legend_for_failed_sheet_renders_empty_box(self, tmp_path: Path):
        """A legend bound to a sheet that failed to compile must not crash — it
        renders as an empty box (no data-source/data-scale), and the failed chart
        only produces a warning. (User requirement, beyond the base ticket.)"""
        (tmp_path / "broken.yaml").write_text("invalid_key: true\n")
        yaml_body = (
            'dashboard: "Legend Failed Sheet"\n'
            "canvas:\n"
            "  width: 1000\n"
            "  height: 800\n"
            "root:\n"
            "  orientation: horizontal\n"
            "  contains:\n"
            "    - sheet: broken.yaml\n"
            "      name: broken_chart\n"
            "    - legend: broken.yaml\n"
            "      field: country\n"
            "      width: 180\n"
        )

        async def _test():
            return await run_dashboard_pipeline(
                yaml_body,
                project_dir=tmp_path,
                charts_dir=tmp_path,
                theme_path=None,
                models_dir=None,
            )

        result = _run(_test())
        # Does not crash, no legend validation error:
        assert result["html"] is not None
        assert result["errors"] == []
        # The broken chart produced a warning:
        assert any("broken_chart" in w for w in result["warnings"])
        # The legend rendered as an empty box: no resolved data attributes.
        attrs = _legend_attrs(result["html"])
        assert "data-source" not in attrs
        assert "data-scale" not in attrs


class TestVendoredVegaSources:
    """SHE-77: the Studio dashboard preview (iframe srcdoc resolves relative
    URLs against the studio origin) must load the vendored same-origin render
    libs, never the CDN."""

    def test_pipeline_html_uses_vendored_libs(self, tmp_path: Path):
        from shelves.render.to_html import VEGA_LIB_FILES

        yaml_body = (
            'dashboard: "Vendor Test"\n'
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            '    - text: "Hello"\n'
            "      preset: title\n"
        )

        async def _test():
            return await run_dashboard_pipeline(
                yaml_body,
                project_dir=tmp_path,
                charts_dir=tmp_path,
                theme_path=None,
                models_dir=None,
            )

        result = _run(_test())
        html = result["html"]
        assert html is not None
        for name in VEGA_LIB_FILES:
            assert f'<script src="/static/vendor/{name}"></script>' in html
        assert "jsdelivr.net/npm/vega" not in html


class TestStudioDashboardControls:
    """SHE-92: controls in the Studio dashboard pipeline."""

    CONTROL_YAML = (
        'dashboard: "Controls"\n'
        "canvas: { width: 1440, height: 900 }\n"
        "root:\n"
        "  orientation: vertical\n"
        "  contains:\n"
        "    - horizontal:\n"
        "        gap: 16\n"
        "        height: 48\n"
        "        contains:\n"
        "          - control: metric\n"
        "          - control: status\n"
        '            label: "Order Status"\n'
        "          - control: top_n\n"
        "    - sheet: param_field_swap.yaml\n"
        "      name: chart_1\n"
        '      height: "80%"\n'
    )

    def test_controls_produce_data_param_attrs(self):
        """Controls in the Studio pipeline emit data-param attributes in HTML."""
        result = _pipeline(self.CONTROL_YAML)
        assert result["errors"] == [], result["errors"]
        html = result["html"]
        assert html is not None
        assert 'data-param="metric"' in html
        assert 'data-param="status"' in html
        assert 'data-param="top_n"' in html

    def test_control_label_override_in_html(self):
        """Inline label on a control overrides the parameter label."""
        result = _pipeline(self.CONTROL_YAML)
        html = result["html"]
        assert html is not None
        assert 'data-title="Order Status"' in html

    def test_control_widget_inference(self):
        """Widget type is inferred from the parameter definition."""
        result = _pipeline(self.CONTROL_YAML)
        html = result["html"]
        assert html is not None
        # metric is type:field → dropdown
        assert 'data-param="metric"' in html
        assert 'data-control="dropdown"' in html
        # top_n is type:number with range → stepper
        assert 'data-param="top_n"' in html
        assert 'data-control="stepper"' in html

    def test_component_tree_includes_controls(self):
        """The component tree returned to Studio includes control entries."""
        result = _pipeline(self.CONTROL_YAML)
        assert result["errors"] == []
        tree = result["component_tree"]
        control_entries = [e for e in tree if e["type"] == "control"]
        assert len(control_entries) == 3

    def test_override_header_threads_to_parameter_set(self):
        """X-Shelves-Params header overrides the default parameter values."""
        result = _pipeline(self.CONTROL_YAML)
        assert result["errors"] == []
        html = result["html"]
        # Default value for metric is "revenue"
        assert 'data-default="revenue"' in html

        # Now recompile with an override
        overrides = {"metric": "cost"}
        result2 = _pipeline(self.CONTROL_YAML, overrides=overrides)
        assert result2["errors"] == [], result2["errors"]
        html2 = result2["html"]
        assert html2 is not None
        assert 'data-default="cost"' in html2

    def test_undeclared_control_returns_error(self):
        """A control referencing a non-existent parameter returns an error."""
        yaml_body = (
            'dashboard: "Bad Control"\n'
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - control: nonexistent\n"
        )
        result = _pipeline(yaml_body)
        assert result["html"] is None
        assert any("nonexistent" in e and "not a declared parameter" in e for e in result["errors"])

    def test_control_render_js_inlined(self):
        """When controls are present, control_render.js is inlined in the HTML."""
        result = _pipeline(self.CONTROL_YAML)
        html = result["html"]
        assert html is not None
        assert "controlRender" in html
