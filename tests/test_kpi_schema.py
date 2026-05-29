"""
KPI Schema Tests

Tests KPI block parsing (schema validation) and theme token loading.
All test expectations are derived from the KPI Specification
(docs/foundational/KPI Specification.md) and the plan (docs/plans/KAN-258.md).
"""

import pytest
from pydantic import ValidationError

from shelves.schema.chart_schema import parse_chart
from tests.conftest import load_yaml

# ===========================================================================
# Happy path — KPI block parses correctly
# ===========================================================================


class TestKPISchemaHappyPath:
    def test_simple_kpi(self):
        spec = parse_chart(load_yaml("kpi_simple.yaml"))
        assert spec.sheet == "Total Revenue"
        assert spec.data == "orders"
        assert spec.kpi.value == "revenue"
        assert spec.kpi.format == "$,.0f"
        assert spec.kpi.title is None
        assert spec.kpi.spacing is None
        assert spec.kpi.comparison is None
        assert spec.cols is None
        assert spec.rows is None
        assert spec.marks is None

    def test_full_kpi(self):
        spec = parse_chart(load_yaml("kpi_full.yaml"))
        assert spec.kpi.value == "revenue"
        assert spec.kpi.format == "$,.0f"
        assert spec.kpi.title == "Monthly Revenue"
        assert spec.kpi.spacing == 8
        assert spec.kpi.comparison.field == "cost"
        assert spec.kpi.comparison.mode == "delta_percent"
        assert spec.kpi.comparison.format == ".1%"
        assert spec.kpi.comparison.label == "vs. Prior Month"
        assert spec.kpi.comparison.polarity == "up_is_good"

    def test_comparison_defaults(self):
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
        assert spec.kpi.comparison.mode == "delta_percent"
        assert spec.kpi.comparison.format is None
        assert spec.kpi.comparison.label is None
        assert spec.kpi.comparison.polarity == "up_is_good"

    def test_delta_absolute_mode(self):
        yaml_str = """\
sheet: "Operating Cost"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: delta_absolute
    polarity: down_is_good
"""
        spec = parse_chart(yaml_str)
        assert spec.kpi.comparison.mode == "delta_absolute"
        assert spec.kpi.comparison.polarity == "down_is_good"

    def test_value_mode(self):
        yaml_str = """\
sheet: "Q1 Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: value
    format: "$,.0f"
    label: "Target"
    polarity: neutral
"""
        spec = parse_chart(yaml_str)
        assert spec.kpi.comparison.mode == "value"
        assert spec.kpi.comparison.polarity == "neutral"
        assert spec.kpi.comparison.label == "Target"

    def test_kpi_with_filters(self):
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
"""
        spec = parse_chart(yaml_str)
        assert spec.filters is not None
        assert len(spec.filters) == 1
        assert spec.filters[0].field == "country"
        assert spec.kpi.value == "revenue"

    def test_zero_spacing(self):
        yaml_str = """\
sheet: "Compact KPI"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  spacing: 0
"""
        spec = parse_chart(yaml_str)
        assert spec.kpi.spacing == 0


# ===========================================================================
# Edge cases
# ===========================================================================


class TestKPISchemaEdgeCases:
    def test_kpi_with_shelves_warns(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
cols: country
rows: revenue
marks: bar
kpi:
  value: revenue
  format: "$,.0f"
"""
        with pytest.warns(UserWarning, match="KPI spec has cols/rows/marks set"):
            spec = parse_chart(yaml_str)
        assert spec.kpi is not None
        assert spec.cols == "country"

    def test_kpi_bypasses_marks_requirement(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
"""
        spec = parse_chart(yaml_str)
        assert spec.kpi is not None
        assert spec.marks is None


# ===========================================================================
# Error / validation cases
# ===========================================================================


class TestKPISchemaErrors:
    def test_missing_value(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  format: "$,.0f"
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml_str)

    def test_missing_format(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml_str)

    def test_empty_format(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: ""
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml_str)

    def test_same_value_and_comparison_field(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: revenue
"""
        with pytest.raises(ValidationError, match=r"value and comparison\.field must be different"):
            parse_chart(yaml_str)

    def test_invalid_mode(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    mode: sparkline
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml_str)

    def test_invalid_polarity(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    field: cost
    polarity: always_green
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml_str)

    def test_missing_comparison_field(self):
        yaml_str = """\
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  comparison:
    mode: delta_percent
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml_str)


# ===========================================================================
# Theme — KPI tokens
# ===========================================================================


class TestKPITheme:
    def test_default_theme_has_kpi_section(self):
        from shelves.theme.merge import load_theme

        theme = load_theme()
        kpi = theme.chart.kpi
        assert kpi["title"]["fontSize"] == 13
        assert kpi["title"]["fontWeight"] == 500
        assert kpi["title"]["color"] == "#666666"
        assert kpi["value"]["fontSize"] == 36
        assert kpi["value"]["fontWeight"] == 600
        assert kpi["value"]["color"] == "#1a1a1a"
        assert kpi["comparison"]["fontSize"] == 12
        assert kpi["comparison"]["fontWeight"] == 400
        assert kpi["semantic"]["positive"] == "#16A34A"
        assert kpi["semantic"]["negative"] == "#DC2626"
        assert kpi["semantic"]["neutral"] == "#6B7280"
        assert kpi["spacing"] == 4

    def test_custom_theme_overrides_kpi(self, tmp_path):
        from shelves.theme.merge import load_theme

        custom_theme = tmp_path / "theme.yaml"
        custom_theme.write_text("""\
chart:
  kpi:
    value:
      fontSize: 48
""")
        theme = load_theme(custom_theme)
        kpi = theme.chart.kpi
        assert kpi["value"]["fontSize"] == 48
        # Other tokens retain defaults
        assert kpi["title"]["fontSize"] == 13
        assert kpi["semantic"]["positive"] == "#16A34A"
