"""
KPI / Big Number Pattern Tests

Tests for the KPI translator: simple KPI (title + value, 2-row vconcat)
and comparison block (title + value + comparison, 3-row vconcat).
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


class TestKPIComparison:
    def test_delta_percent_full(self):
        vl = compile_fixture("kpi_full.yaml")

        assert vl["$schema"] == "https://vega.github.io/schema/vega-lite/v6.json"
        assert len(vl["vconcat"]) == 3

        # Title row
        assert vl["vconcat"][0]["encoding"]["text"]["value"] == "Monthly Revenue"
        assert vl["vconcat"][0]["mark"]["fontSize"] == 13
        assert vl["vconcat"][0]["mark"]["fontWeight"] == 500
        assert vl["vconcat"][0]["mark"]["color"] == "#666666"

        # Value row
        assert vl["vconcat"][1]["encoding"]["text"]["field"] == "revenue"
        assert vl["vconcat"][1]["encoding"]["text"]["format"] == "$,.0f"
        assert vl["vconcat"][1]["mark"]["fontSize"] == 36

        # Comparison row — mark has no color (comes from encoding)
        comp_row = vl["vconcat"][2]
        assert comp_row["mark"]["type"] == "text"
        assert comp_row["mark"]["fontSize"] == 12
        assert comp_row["mark"]["fontWeight"] == 400
        assert comp_row["mark"]["align"] == "left"
        assert comp_row["mark"]["baseline"] == "middle"
        assert "color" not in comp_row["mark"]
        assert comp_row["encoding"]["text"] == {
            "field": "comparison_text",
            "type": "nominal",
        }
        assert comp_row["encoding"]["x"] == {"value": 0}
        assert comp_row["height"] == 1

        # Conditional color — up_is_good
        assert comp_row["encoding"]["color"] == {
            "condition": {"test": "datum.delta >= 0", "value": "#16A34A"},
            "value": "#DC2626",
        }

        # Transforms — 3 calculate transforms
        assert len(vl["transform"]) == 3
        delta_expr = "abs(datum.cost) > 0 ? (datum.revenue - datum.cost) / abs(datum.cost) : null"
        assert vl["transform"][0] == {"calculate": delta_expr, "as": "delta"}
        assert vl["transform"][1] == {
            "calculate": "datum.delta != null ? (datum.delta >= 0 ? '▲' : '▼') : null",
            "as": "indicator",
        }
        comp_text_expr = (
            "datum.delta != null ? datum.indicator + ' '"
            " + format(abs(datum.delta), '.1%')"
            " + '  vs. Prior Month' : null"
        )
        assert vl["transform"][2] == {
            "calculate": comp_text_expr,
            "as": "comparison_text",
        }

        # Custom spacing
        assert vl["spacing"] == 8
        assert vl["config"] == {"view": {"stroke": None}, "concat": {"spacing": 8}}

    def test_delta_absolute_down_is_good(self):
        vl = compile_fixture("kpi_comparison_delta_absolute.yaml")

        assert len(vl["vconcat"]) == 3
        assert vl["vconcat"][0]["encoding"]["text"]["value"] == "Operating Cost"
        assert vl["vconcat"][1]["encoding"]["text"]["field"] == "cost"

        # Transforms — subtraction, null-guarded on comparison field
        assert vl["transform"][0] == {
            "calculate": "datum.revenue != null ? datum.cost - datum.revenue : null",
            "as": "delta",
        }
        assert vl["transform"][1] == {
            "calculate": "datum.delta != null ? (datum.delta >= 0 ? '▲' : '▼') : null",
            "as": "indicator",
        }
        # Format inherits kpi.format ($,.0f) since comp.format is not set
        comp_text_expr = (
            "datum.delta != null ? datum.indicator + ' '"
            " + format(abs(datum.delta), '$,.0f')"
            " + '  vs. Revenue' : null"
        )
        assert vl["transform"][2] == {
            "calculate": comp_text_expr,
            "as": "comparison_text",
        }

        # down_is_good — condition flips to datum.delta <= 0
        assert vl["vconcat"][2]["encoding"]["color"] == {
            "condition": {"test": "datum.delta <= 0", "value": "#16A34A"},
            "value": "#DC2626",
        }

        # Default spacing
        assert vl["spacing"] == 4

    def test_value_mode_neutral(self):
        vl = compile_fixture("kpi_comparison_value.yaml")

        assert len(vl["vconcat"]) == 3
        assert vl["vconcat"][0]["encoding"]["text"]["value"] == "Q1 Revenue"

        # Only 1 transform — no delta/indicator
        assert len(vl["transform"]) == 1
        assert vl["transform"][0] == {
            "calculate": "datum.cost != null ? format(datum.cost, '$,.0f') + '  Cost Basis' : null",
            "as": "comparison_text",
        }

        # Neutral color — fixed value, no conditional
        assert vl["vconcat"][2]["encoding"]["color"] == {"value": "#6B7280"}

    def test_delta_percent_defaults(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert len(vl["vconcat"]) == 3
        assert len(vl["transform"]) == 3

        # Default format is .1%, no label suffix
        comp_text_expr = (
            "datum.delta != null ? datum.indicator + ' ' + format(abs(datum.delta), '.1%') : null"
        )
        assert vl["transform"][2] == {
            "calculate": comp_text_expr,
            "as": "comparison_text",
        }

        # Default polarity is up_is_good
        assert vl["vconcat"][2]["encoding"]["color"] == {
            "condition": {"test": "datum.delta >= 0", "value": "#16A34A"},
            "value": "#DC2626",
        }

    def test_no_label(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: delta_percent
    polarity: up_is_good
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # No label suffix in comparison_text
        comp_text_expr = (
            "datum.delta != null ? datum.indicator + ' ' + format(abs(datum.delta), '.1%') : null"
        )
        assert vl["transform"][2] == {
            "calculate": comp_text_expr,
            "as": "comparison_text",
        }

    def test_custom_format_override(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: delta_percent
    format: ".2%"
    label: "vs. Cost"
    polarity: up_is_good
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Custom format .2% overrides default .1%
        comp_text_expr = (
            "datum.delta != null ? datum.indicator + ' '"
            " + format(abs(datum.delta), '.2%')"
            " + '  vs. Cost' : null"
        )
        assert vl["transform"][2] == {
            "calculate": comp_text_expr,
            "as": "comparison_text",
        }

    def test_delta_absolute_inherits_kpi_format(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.2f"
  comparison:
    field: cost
    mode: delta_absolute
    label: "vs. Cost"
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Format inherited from kpi.format ($,.2f)
        comp_text_expr = (
            "datum.delta != null ? datum.indicator + ' '"
            " + format(abs(datum.delta), '$,.2f')"
            " + '  vs. Cost' : null"
        )
        assert vl["transform"][2] == {
            "calculate": comp_text_expr,
            "as": "comparison_text",
        }

    def test_comparison_with_filters(self):
        yaml_str = """\
sheet: "US Revenue"
data: orders
filters:
  - field: country
    operator: eq
    value: "US"
kpi:
  value: revenue
  format: "$,.0f"
  title: "US Revenue"
  comparison:
    field: cost
    mode: delta_percent
    label: "vs. Cost"
    polarity: up_is_good
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Filter transforms come first, then comparison transforms
        assert len(vl["transform"]) == 4
        assert vl["transform"][0] == {"filter": {"field": "country", "equal": "US"}}
        assert vl["transform"][1]["as"] == "delta"
        assert vl["transform"][2]["as"] == "indicator"
        assert vl["transform"][3]["as"] == "comparison_text"

        assert len(vl["vconcat"]) == 3
        assert vl["vconcat"][0]["encoding"]["text"]["value"] == "US Revenue"

    def test_neutral_polarity_delta_mode(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: delta_percent
    polarity: neutral
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Fixed neutral color, no conditional
        assert vl["vconcat"][2]["encoding"]["color"] == {"value": "#6B7280"}
        # Still generates delta/indicator/comparison_text transforms
        assert len(vl["transform"]) == 3

    def test_value_mode_ignores_polarity(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: value
    format: "$,.0f"
    polarity: up_is_good
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Value mode always uses neutral color regardless of polarity
        assert vl["vconcat"][2]["encoding"]["color"] == {"value": "#6B7280"}


class TestKPIComparisonErrors:
    def test_comparison_field_is_dimension(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: country
"""
        spec = parse_chart(yaml_str)
        with pytest.raises(ValueError, match="country"):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_comparison_field_not_in_model(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: nonexistent_field
"""
        spec = parse_chart(yaml_str)
        with pytest.raises(ValueError, match="nonexistent_field"):
            translate_chart(spec, models_dir=MODELS_DIR)
