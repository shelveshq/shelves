"""
Tests for chart field extraction — collect_chart_fields.
"""

from __future__ import annotations

import warnings

from shelves.data.fields import collect_chart_fields
from shelves.schema.chart_schema import parse_chart

# ─── collect_chart_fields ──────────────────────────────────────────


class TestCollectChartFields:
    def test_simple_bar(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        fields = collect_chart_fields(spec)
        assert fields == {"category", "net_sales"}

    def test_with_color_and_detail(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "color: segment\ndetail: segment\n"
        )
        fields = collect_chart_fields(spec)
        assert fields == {"category", "net_sales", "segment"}

    def test_hex_color_excluded(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'color: "#ff0000"\n'
        )
        fields = collect_chart_fields(spec)
        assert "#ff0000" not in fields

    def test_filter_fields_included(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'filters:\n  - field: segment\n    operator: eq\n    value: "Consumer"\n'
        )
        fields = collect_chart_fields(spec)
        assert "segment" in fields

    def test_size_field_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: circle\n'
            "size: net_sales\n"
        )
        fields = collect_chart_fields(spec)
        assert "net_sales" in fields
        assert "category" in fields

    def test_size_numeric_not_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: circle\n'
            "size: 100\n"
        )
        fields = collect_chart_fields(spec)
        assert fields == {"category", "net_sales"}

    def test_tooltip_existing_fields_no_warning(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "tooltip: [category, net_sales]\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = collect_chart_fields(spec)
        assert "category" in fields
        assert "net_sales" in fields
        assert len(w) == 0

    def test_tooltip_new_field_warns(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "tooltip: [category, segment]\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = collect_chart_fields(spec)
        assert "segment" in fields
        assert "category" in fields
        assert "net_sales" in fields
        assert len(w) == 1
        assert "segment" in str(w[0].message)
        assert "detail" in str(w[0].message)

    def test_tooltip_object_new_field_warns(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "tooltip:\n  - field: segment\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = collect_chart_fields(spec)
        assert "segment" in fields
        assert len(w) == 1
        assert "segment" in str(w[0].message)

    def test_tooltip_mixed_warns_only_new(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "color: segment\n"
            "tooltip: [category, net_sales, segment, order_date]\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = collect_chart_fields(spec)
        assert fields == {"category", "net_sales", "segment", "order_date"}
        assert len(w) == 1
        assert "order_date" in str(w[0].message)

    def test_wrap_facet_field_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: order_date\nrows: net_sales\nmarks: line\n'
            "facet:\n  field: category\n  columns: 3\n"
        )
        fields = collect_chart_fields(spec)
        assert "category" in fields
        assert "order_date" in fields
        assert "net_sales" in fields

    def test_row_column_facet_fields_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: order_date\nrows: net_sales\nmarks: line\n'
            "facet:\n  row: category\n  column: segment\n"
        )
        fields = collect_chart_fields(spec)
        assert "category" in fields
        assert "segment" in fields

    def test_field_sort_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "sort:\n  field: net_sales\n  order: descending\n"
        )
        fields = collect_chart_fields(spec)
        assert "net_sales" in fields

    def test_axis_sort_no_extra_fields(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "sort:\n  axis: y\n  order: ascending\n"
        )
        fields = collect_chart_fields(spec)
        assert fields == {"category", "net_sales"}

    def test_measure_entry_size_field_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\n'
            "rows:\n  - measure: net_sales\n    mark: circle\n    size: segment\n"
        )
        fields = collect_chart_fields(spec)
        assert "segment" in fields
        assert "net_sales" in fields
        assert "category" in fields

    def test_entry_color_field_mapping_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\n'
            "rows:\n  - measure: net_sales\n    mark: bar\n    color:\n      field: segment\n"
        )
        fields = collect_chart_fields(spec)
        assert "segment" in fields
