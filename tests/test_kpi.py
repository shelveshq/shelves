"""
KPI / Big Number Pattern Tests

Tests for the simple KPI translator (KAN-259): title + value text marks
compiled to a 2-row vconcat. Comparison rendering is deferred to KAN-260.
"""

import pytest

from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from tests.conftest import MODELS_DIR, compile_fixture


class TestSimpleKPI:
    def test_simple_kpi_two_rows(self):
        vl = compile_fixture("kpi_simple.yaml")

        assert vl["$schema"] == "https://vega.github.io/schema/vega-lite/v6.json"
        assert "title" not in vl
        assert "facet" not in vl and "repeat" not in vl
        assert len(vl["vconcat"]) == 2

        assert vl["vconcat"][0]["encoding"]["text"]["value"] == "Total Revenue"
        assert vl["vconcat"][0]["mark"]["fontSize"] == 13
        assert vl["vconcat"][0]["mark"]["fontWeight"] == 500
        assert vl["vconcat"][0]["mark"]["color"] == "#666666"
        assert vl["vconcat"][0]["mark"]["align"] == "left"
        assert vl["vconcat"][0]["mark"]["baseline"] == "middle"
        assert vl["vconcat"][0]["height"] == 1

        assert vl["vconcat"][1]["encoding"]["text"]["field"] == "revenue"
        assert vl["vconcat"][1]["encoding"]["text"]["type"] == "quantitative"
        assert vl["vconcat"][1]["encoding"]["text"]["format"] == "$,.0f"
        assert vl["vconcat"][1]["mark"]["fontSize"] == 36
        assert vl["vconcat"][1]["mark"]["fontWeight"] == 600
        assert vl["vconcat"][1]["mark"]["color"] == "#1a1a1a"
        assert vl["vconcat"][1]["height"] == 1

        assert vl["spacing"] == 4
        assert vl["config"] == {"view": {"stroke": None}, "concat": {"spacing": 4}}
        assert "transform" not in vl

    def test_explicit_title_overrides_sheet(self):
        vl = compile_fixture("kpi_explicit_title.yaml")

        assert vl["vconcat"][0]["encoding"]["text"]["value"] == "Monthly Revenue"
        assert "title" not in vl

    def test_custom_spacing(self):
        vl = compile_fixture("kpi_custom_spacing.yaml")

        assert vl["spacing"] == 12
        assert vl["config"]["concat"]["spacing"] == 12

    def test_spacing_zero(self):
        yaml_str = """\
sheet: "Compact"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  spacing: 0
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert vl["spacing"] == 0
        assert vl["config"]["concat"]["spacing"] == 0

    def test_kpi_with_filters(self):
        vl = compile_fixture("kpi_with_filters.yaml")

        assert vl["transform"] == [{"filter": {"field": "country", "equal": "US"}}]
        assert len(vl["vconcat"]) == 2
        assert vl["vconcat"][0]["encoding"]["text"]["value"] == "US Revenue"
        assert vl["vconcat"][1]["encoding"]["text"]["field"] == "revenue"


class TestKPIErrors:
    def test_value_not_a_measure(self):
        yaml_str = """\
sheet: "Bad KPI"
data: orders
kpi:
  value: not_a_real_field
  format: "$,.0f"
"""
        spec = parse_chart(yaml_str)
        with pytest.raises(ValueError, match="not_a_real_field"):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_value_is_dimension(self):
        yaml_str = """\
sheet: "Bad KPI"
data: orders
kpi:
  value: country
  format: "$,.0f"
"""
        spec = parse_chart(yaml_str)
        with pytest.raises(ValueError, match="country"):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_comparison_not_implemented(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: delta_percent
"""
        spec = parse_chart(yaml_str)
        with pytest.raises(NotImplementedError, match="KAN-260"):
            translate_chart(spec, models_dir=MODELS_DIR)
