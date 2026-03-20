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
        assert spec.data == "orders"

    def test_line_chart(self):
        spec = parse_chart(load_yaml("line_chart.yaml"))
        assert spec.data == "orders"

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

    def test_grouped_bar(self):
        spec = parse_chart(load_yaml("grouped_bar.yaml"))
        assert spec.marks == "bar"
        assert spec.color == "product"
        assert spec.cols == "country"

    def test_multi_line(self):
        spec = parse_chart(load_yaml("multi_line.yaml"))
        assert spec.marks == "line"
        assert spec.color == "country"
        assert spec.data == "orders"

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
data: orders
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
data: orders
marks: sparkle
""")

    def test_rejects_invalid_filter_operator(self):
        with pytest.raises(ValidationError):
            parse_chart("""
sheet: "Test"
data: orders
marks: bar
filters:
  - field: country
    operator: contains
    value: "US"
""")
