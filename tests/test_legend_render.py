"""
SHE-11: legend data-attribute baking + runtime populate wiring.

Python can't execute the browser renderer, so these assert the GENERATED
HTML/JS: the data attributes compose bakes onto each legend div, that
legend_render.js is inlined, and that the embed loop captures the view and calls
populate. The pure markup core is unit-tested in shelves/render/legend_render.test.js
(node --test).
"""

import re

import pytest

from shelves.compose.dashboard import compose_dashboard
from tests.conftest import DATA_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR


def _compose(fixture_name: str, **kwargs) -> str:
    return compose_dashboard(
        dashboard_path=LAYOUT_DIR / fixture_name,
        chart_base_dir=YAML_DIR,
        data_dir=DATA_DIR,
        models_dir=MODELS_DIR,
        **kwargs,
    )


def _legend_div(html: str) -> str:
    """Return the opening <div ...> tag of the first legend placeholder."""
    m = re.search(r'<div id="legend-[^"]+"[^>]*>', html)
    assert m is not None, "legend div not found"
    return m.group(0)


class TestLegendDataAttrs:
    def test_color_legend_data_attrs(self):
        div = _legend_div(_compose("legend_link_color.yaml"))
        assert 'data-source="sheet-sales_chart"' in div
        assert 'data-scale="color"' in div
        assert 'data-orientation="vertical"' in div
        assert 'data-title="Country"' in div  # default = model label

    def test_explicit_title_wins(self):
        div = _legend_div(_compose("legend_render_titled.yaml"))
        assert 'data-title="Sales Region"' in div
        assert 'data-title="Country"' not in div

    def test_horizontal_orientation(self):
        div = _legend_div(_compose("legend_render_horizontal.yaml"))
        assert 'data-orientation="horizontal"' in div

    def test_gradient_color_data_attrs(self):
        div = _legend_div(_compose("legend_gradient_color.yaml"))
        assert 'data-source="sheet-heat"' in div
        assert 'data-scale="color"' in div
        assert 'data-channel="color"' in div
        assert 'data-format="$,.0f"' in div  # revenue.format from the model
        assert 'data-title="Revenue"' in div  # model label default

    def test_nominal_color_no_format_attr(self):
        # simple_bar.yaml color: country (nominal) -> resolve_format is None -> no attr.
        div = _legend_div(_compose("legend_link_color.yaml"))
        assert "data-format=" not in div


class TestLegendRuntimeWiring:
    def test_renderer_inlined_and_populate_wired(self):
        html = _compose("legend_link_color.yaml")
        # Renderer script inlined:
        assert "global.legendRender = api" in html
        # View captured + legends populated after embed:
        assert ".then(" in html
        assert "legendRender.populate(r.view, id, document)" in html

    def test_no_legend_no_renderer(self):
        # A sheet with a color encoding but no legend element → SHE-10 warns and
        # nothing legend-related is inlined.
        with pytest.warns(UserWarning, match="no dashboard legend"):
            html = _compose("legend_unlinked.yaml")
        assert "global.legendRender = api" not in html
        assert "legendRender.populate(" not in html
