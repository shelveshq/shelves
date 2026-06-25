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
from tests.conftest import DATA_DIR, MODELS_DIR, YAML_DIR


def _run(coro):
    return asyncio.run(coro)


def _pipeline(yaml_body: str) -> dict:
    """Run the dashboard pipeline against the shared chart/model fixtures."""

    async def _test():
        return await run_dashboard_pipeline(
            yaml_body,
            project_dir=DATA_DIR,  # inline data (orders.json/csv) lives here
            charts_dir=YAML_DIR,  # simple_bar.yaml / scatter.yaml / dual_axis.yaml
            theme_path=None,
            models_dir=MODELS_DIR,  # orders.yaml model → field labels/types
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
        assert 'data-scale="color"' in attrs

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
        assert 'data-scale="size"' in attrs
        assert 'data-source="sheet-scatter_chart"' in attrs

        specs = _embedded_specs(html)
        # size suppressed (linked) AND color suppressed (always-suppress):
        assert specs["sheet-scatter_chart"]["encoding"]["size"]["legend"] is None
        assert specs["sheet-scatter_chart"]["encoding"]["color"]["legend"] is None

        # scatter.yaml also color-encodes `country` with no legend element → one
        # warning, surfaced in the Studio warnings list (NOT a Python warning).
        assert any("color" in w and "scatter_chart" in w for w in result["warnings"])

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
