"""
Stacked Panel Tests

Tests for multi-measure shelves compiled to repeat or vconcat.
"""

import pytest
from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from tests.conftest import load_yaml, compile_fixture


class TestStackedPanels:
    def test_stacked_same_mark_produces_repeat(self):
        vl = compile_fixture("stacked_panels.yaml")
        assert "repeat" in vl
        assert vl["repeat"]["row"] == ["revenue", "order_count", "arpu"]
        assert vl["spec"]["mark"] == "line"
        assert vl["spec"]["encoding"]["x"]["field"] == "week"

        # NEW: shared axis auto-inject
        x_enc = vl["spec"]["encoding"]["x"]
        assert x_enc["title"] == "Week"
        assert x_enc["axis"]["format"] == "%b %d"
        assert x_enc["axis"]["grid"] is False  # x-axis grid default

    def test_stacked_diff_marks_produces_vconcat(self):
        vl = compile_fixture("stacked_diff_marks.yaml")
        assert "vconcat" in vl
        assert len(vl["vconcat"]) == 2

        # First panel: revenue as bar
        panel_0 = vl["vconcat"][0]
        assert panel_0["mark"] == "bar"
        assert panel_0["encoding"]["y"]["field"] == "revenue"
        assert panel_0["encoding"]["color"]["field"] == "country"

        # Second panel: order_count as line
        panel_1 = vl["vconcat"][1]
        assert panel_1["mark"] == "line"
        assert panel_1["encoding"]["y"]["field"] == "order_count"

        # NEW: per-panel auto-injected titles and formats
        assert panel_0["encoding"]["y"]["title"] == "Revenue"
        assert panel_0["encoding"]["y"]["axis"]["format"] == "$,.0f"
        assert panel_1["encoding"]["y"]["title"] == "Orders"
        assert panel_1["encoding"]["y"]["axis"]["format"] == ",.0f"

        # NEW: shared axis title, format, and grid on both panels
        assert panel_0["encoding"]["x"]["title"] == "Week"
        assert panel_1["encoding"]["x"]["title"] == "Week"
        assert panel_0["encoding"]["x"]["axis"]["format"] == "%b %d"
        assert panel_1["encoding"]["x"]["axis"]["format"] == "%b %d"
        assert panel_0["encoding"]["x"]["axis"]["grid"] is False  # x-axis grid default
        assert panel_1["encoding"]["x"]["axis"]["grid"] is False

        # NEW: measure axis grid defaults
        assert panel_0["encoding"]["y"]["axis"]["grid"] is True  # y-axis grid default
        assert panel_1["encoding"]["y"]["axis"]["grid"] is True

        # NEW: color legend title
        assert panel_0["encoding"]["color"]["legend"]["title"] == "Country"
        assert panel_1["encoding"]["color"]["legend"]["title"] == "Country"

    def test_stacked_shared_x_axis(self):
        vl = compile_fixture("stacked_diff_marks.yaml")
        for panel in vl["vconcat"]:
            assert panel["encoding"]["x"]["field"] == "week"
            assert panel["encoding"]["x"]["type"] == "temporal"
            # NEW
            assert panel["encoding"]["x"]["title"] == "Week"


class TestStackedSchema:
    def test_parses_stacked_panels(self):
        spec = parse_chart(load_yaml("stacked_panels.yaml"))
        assert isinstance(spec.rows, list)
        assert len(spec.rows) == 3
        assert spec.rows[0].measure == "revenue"

    def test_parses_stacked_diff_marks(self):
        spec = parse_chart(load_yaml("stacked_diff_marks.yaml"))
        assert isinstance(spec.rows, list)
        assert spec.rows[0].mark == "bar"
        assert spec.rows[1].mark == "line"

    def test_rejects_both_shelves_multi(self):
        with pytest.raises(Exception):
            parse_chart("""
sheet: "Bad"
data: orders
rows:
  - measure: a
  - measure: b
cols:
  - measure: c
""")

    def test_parses_layer_entry_but_compilation_deferred(self):
        """Schema accepts layers, but translator raises NotImplementedError."""
        spec = parse_chart("""
sheet: "With Layers"
data: orders
cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: arpu
        mark:
          type: line
          style: dashed
    axis: independent
""")
        assert spec.rows[0].layer is not None
        assert spec.rows[0].layer[0].measure == "arpu"
        assert spec.rows[0].axis == "independent"

        with pytest.raises(NotImplementedError):
            translate_chart(spec)
