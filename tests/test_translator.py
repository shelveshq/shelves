"""
Translator Tests

Tests the full YAML -> Vega-Lite compilation pipeline.
Each fixture YAML produces a deterministic Vega-Lite dict.
"""

from tests.conftest import compile_fixture


class TestSingleMarkCharts:
    def test_simple_bar(self):
        vl = compile_fixture("simple_bar.yaml")
        # Existing assertions
        assert vl["mark"] == "bar"
        assert vl["encoding"]["x"]["field"] == "country"
        assert vl["encoding"]["y"]["field"] == "revenue"
        assert vl["encoding"]["y"]["type"] == "quantitative"
        assert vl["encoding"]["color"]["field"] == "country"

        # NEW: auto-injected titles
        assert vl["encoding"]["x"]["title"] == "Country"
        assert vl["encoding"]["y"]["title"] == "Revenue"

        # NEW: auto-injected formats
        assert vl["encoding"]["y"]["axis"]["format"] == "$,.0f"

        # NEW: auto-injected grid defaults
        assert vl["encoding"]["x"]["axis"]["grid"] is False
        assert vl["encoding"]["y"]["axis"]["grid"] is True

        # NEW: legend title on color
        assert vl["encoding"]["color"]["legend"]["title"] == "Country"

        # NEW: tooltip auto-labels and formats
        tooltip = vl["encoding"]["tooltip"]
        country_tt = next(t for t in tooltip if t["field"] == "country")
        revenue_tt = next(t for t in tooltip if t["field"] == "revenue")
        assert country_tt["title"] == "Country"
        assert revenue_tt["title"] == "Revenue"
        assert revenue_tt["format"] == "$,.0f"

    def test_grouped_bar(self):
        vl = compile_fixture("grouped_bar.yaml")
        # Existing
        assert vl["encoding"]["color"]["field"] == "product"

        # NEW: legend title from model
        assert vl["encoding"]["color"]["legend"]["title"] == "Product"

        # NEW: axis titles
        assert vl["encoding"]["x"]["title"] == "Country"
        assert vl["encoding"]["y"]["title"] == "Revenue"

    def test_line_chart_temporal_x(self):
        vl = compile_fixture("line_chart.yaml")
        # Existing
        assert vl["encoding"]["x"]["type"] == "temporal"
        assert vl["mark"] == "line"

        # NEW: default grain applied
        assert vl["encoding"]["x"]["timeUnit"] == "yearweek"
        assert vl["encoding"]["x"]["title"] == "Week"
        assert vl["encoding"]["x"]["axis"]["format"] == "%b %d"

        # NEW: y-axis auto-inject
        assert vl["encoding"]["y"]["title"] == "Revenue"
        assert vl["encoding"]["y"]["axis"]["format"] == "$,.0f"
        assert vl["encoding"]["y"]["axis"]["grid"] is True

    def test_multi_line(self):
        vl = compile_fixture("multi_line.yaml")
        assert vl["mark"] == "line"
        assert vl["encoding"]["color"]["field"] == "country"

        # NEW
        assert vl["encoding"]["color"]["legend"]["title"] == "Country"
        assert vl["encoding"]["x"]["title"] == "Week"
        assert vl["encoding"]["y"]["title"] == "Revenue"

    def test_scatter(self):
        vl = compile_fixture("scatter.yaml")
        assert vl["mark"] == "circle"
        assert vl["encoding"]["x"]["type"] == "quantitative"
        assert vl["encoding"]["y"]["type"] == "quantitative"
        assert vl["encoding"]["size"]["field"] == "revenue"

        # NEW: both axes quantitative — both get titles and formats
        assert vl["encoding"]["x"]["title"] == "Revenue"
        assert vl["encoding"]["y"]["title"] == "Orders"
        assert vl["encoding"]["x"]["axis"]["format"] == "$,.0f"
        assert vl["encoding"]["y"]["axis"]["format"] == ",.0f"

        # NEW: grid defaults
        assert vl["encoding"]["x"]["axis"]["grid"] is False
        assert vl["encoding"]["y"]["axis"]["grid"] is True

        # NEW: legend title
        assert vl["encoding"]["color"]["legend"]["title"] == "Country"

    def test_heatmap(self):
        vl = compile_fixture("heatmap.yaml")
        assert vl["mark"] == "rect"
        assert vl["encoding"]["color"]["type"] == "quantitative"

        # NEW: axis titles
        assert vl["encoding"]["x"]["title"] == "Product"
        assert vl["encoding"]["y"]["title"] == "Country"

        # NEW: color field mapping gets legend title
        assert vl["encoding"]["color"]["legend"]["title"] == "Revenue"


class TestSort:
    def test_sort_on_x_encoding(self):
        vl = compile_fixture("simple_bar.yaml")
        assert vl["encoding"]["x"]["sort"] == {
            "field": "revenue",
            "order": "descending",
        }


class TestSchemaPresent:
    def test_has_vega_lite_schema(self):
        vl = compile_fixture("simple_bar.yaml")
        assert "$schema" in vl
        assert "vega-lite" in vl["$schema"]
