"""
Schema Tests

Validates that YAML chart specs parse correctly through Pydantic.
Tests both valid specs (should pass) and invalid specs (should raise).
"""

import pytest
from pydantic import ValidationError

from src.schema.chart_schema import parse_chart
from tests.conftest import load_yaml


class TestParseValidSpecs:
    def test_simple_bar(self):
        spec = parse_chart(load_yaml("simple_bar.yaml"))
        assert spec.sheet == "Revenue by Country"
        assert spec.marks == "bar"
        assert spec.cols == "country"
        assert spec.rows == "revenue"
        assert spec.data.model == "orders"

    def test_line_chart_with_time_grain(self):
        spec = parse_chart(load_yaml("line_chart.yaml"))
        assert spec.data.time_grain is not None
        assert spec.data.time_grain.field == "week"
        assert spec.data.time_grain.grain == "week"

    def test_scatter_with_size(self):
        spec = parse_chart(load_yaml("scatter.yaml"))
        assert spec.marks == "circle"
        assert spec.size == "revenue"

    def test_facet_row(self):
        spec = parse_chart(load_yaml("facet_row.yaml"))
        assert spec.facet is not None
        assert hasattr(spec.facet, "row")
        assert spec.facet.row == "region"

    def test_facet_wrap(self):
        spec = parse_chart(load_yaml("facet_wrap.yaml"))
        assert spec.facet is not None
        assert hasattr(spec.facet, "field")
        assert spec.facet.field == "country"
        assert spec.facet.columns == 4

    def test_heatmap_with_quantitative_color(self):
        spec = parse_chart(load_yaml("heatmap.yaml"))
        assert spec.marks == "rect"
        assert hasattr(spec.color, "field")
        assert spec.color.field == "revenue"
        assert spec.color.type == "quantitative"


class TestParseInvalidSpecs:
    def test_rejects_missing_sheet(self):
        with pytest.raises(ValidationError):
            parse_chart("""
data:
  model: orders
  measures: [revenue]
  dimensions: [country]
marks: bar
""")

    def test_rejects_missing_data(self):
        with pytest.raises(ValidationError):
            parse_chart("""
sheet: "Test"
marks: bar
""")

    def test_rejects_unknown_mark_type(self):
        with pytest.raises(ValidationError):
            parse_chart("""
sheet: "Test"
data:
  model: orders
  measures: [revenue]
  dimensions: [country]
marks: sparkle
""")

    def test_rejects_invalid_filter_operator(self):
        with pytest.raises(ValidationError):
            parse_chart("""
sheet: "Test"
data:
  model: orders
  measures: [revenue]
  dimensions: [country]
marks: bar
filters:
  - field: country
    operator: contains
    value: "US"
""")
