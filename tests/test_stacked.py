"""
Stacked Panel Tests

Tests for multi-measure shelves compiled to repeat or vconcat.
"""

import pytest
from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from tests.conftest import load_yaml, compile_fixture, MODELS_DIR


class TestStackedPanels:
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

        # KAN-232: top panel's shared x-axis is suppressed; bottom panel's is shown
        assert panel_0["encoding"]["x"]["axis"] is None
        assert "title" not in panel_0["encoding"]["x"]
        assert panel_1["encoding"]["x"]["title"] == "Week"
        assert panel_1["encoding"]["x"]["axis"]["format"] == "%b %d"
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
            # field and type preserved on all panels even when axis is suppressed
            assert panel["encoding"]["x"]["field"] == "week"
            assert panel["encoding"]["x"]["type"] == "temporal"
        # KAN-232: only the bottom panel retains the shared axis title
        bottom = vl["vconcat"][-1]
        assert bottom["encoding"]["x"]["title"] == "Week"

    def test_vconcat_hides_shared_axis_default(self):
        """KAN-232: default hides shared x-axis on non-bottom panels (vconcat)."""
        vl = compile_fixture("stacked_diff_marks.yaml")
        panels = vl["vconcat"]
        # Top panel: shared x hidden
        assert panels[0]["encoding"]["x"]["axis"] is None
        assert "title" not in panels[0]["encoding"]["x"]
        # Bottom panel: shared x shown with full axis
        assert panels[1]["encoding"]["x"]["title"] == "Week"
        assert panels[1]["encoding"]["x"]["axis"]["format"] == "%b %d"
        # Spacing added
        assert vl["spacing"] == 10

    def test_repeat_degrades_to_vconcat_with_axis_hiding(self):
        """KAN-232: same-mark repeat degrades to vconcat when axis hiding is active (default)."""
        vl = compile_fixture("stacked_panels.yaml")
        # repeat is no longer used — axis hiding requires per-panel control
        assert "repeat" not in vl
        assert "vconcat" in vl
        panels = vl["vconcat"]
        assert len(panels) == 3

        # All panels are line marks
        for p in panels:
            assert p["mark"] == "line"

        # Top two panels hide shared x-axis
        assert panels[0]["encoding"]["x"]["axis"] is None
        assert "title" not in panels[0]["encoding"]["x"]
        assert panels[1]["encoding"]["x"]["axis"] is None
        assert "title" not in panels[1]["encoding"]["x"]

        # Bottom panel shows shared x-axis
        assert panels[2]["encoding"]["x"]["title"] == "Week"
        assert panels[2]["encoding"]["x"]["axis"]["format"] == "%b %d"

        # Each panel binds its own measure
        assert panels[0]["encoding"]["y"]["field"] == "revenue"
        assert panels[1]["encoding"]["y"]["field"] == "order_count"
        assert panels[2]["encoding"]["y"]["field"] == "arpu"

        # Spacing
        assert vl["spacing"] == 10

    def test_shared_axis_true_preserves_repeat(self):
        """KAN-232: when all entries have shared_axis:true, the repeat optimization is preserved."""
        vl = compile_fixture("stacked_shared_axis_all.yaml")
        assert "repeat" in vl
        assert "vconcat" not in vl
        assert vl["repeat"]["row"] == ["revenue", "order_count", "arpu"]
        assert vl["spec"]["mark"] == "line"
        # Shared axis shown with full metadata
        x_enc = vl["spec"]["encoding"]["x"]
        assert x_enc["field"] == "week"
        assert x_enc["title"] == "Week"
        assert x_enc["axis"]["format"] == "%b %d"
        # No spacing on repeat specs
        assert "spacing" not in vl

    def test_shared_axis_override_on_middle_panel(self):
        """KAN-232: shared_axis:true on a non-edge panel forces it to show its axis."""
        vl = compile_fixture("stacked_shared_axis_middle.yaml")
        assert "vconcat" in vl
        panels = vl["vconcat"]
        assert len(panels) == 3

        # Top panel (revenue, bar): no shared_axis → default hide
        assert panels[0]["encoding"]["x"]["axis"] is None
        assert "title" not in panels[0]["encoding"]["x"]

        # Middle panel (order_count, line): shared_axis: true → shows
        assert panels[1]["encoding"]["x"]["title"] == "Week"
        assert panels[1]["encoding"]["x"]["axis"]["format"] == "%b %d"

        # Bottom panel (arpu, line): default edge → shows
        assert panels[2]["encoding"]["x"]["title"] == "Week"
        assert panels[2]["encoding"]["x"]["axis"]["format"] == "%b %d"

        assert vl["spacing"] == 10

    def test_shared_axis_false_hides_edge_panel(self):
        """KAN-232: shared_axis:false on the edge panel hides even the bottom panel's axis."""
        vl = compile_fixture("stacked_shared_axis_hide_edge.yaml")
        assert "vconcat" in vl
        panels = vl["vconcat"]
        assert len(panels) == 2
        # Both panels hide
        for p in panels:
            assert p["encoding"]["x"]["axis"] is None
            assert "title" not in p["encoding"]["x"]
        assert vl["spacing"] == 10

    def test_hconcat_hides_shared_axis_default(self):
        """KAN-232: for hconcat (cols multi-measure), shared y-axis hidden on non-left panels."""
        vl = compile_fixture("stacked_hconcat_axis_hiding.yaml")
        assert "hconcat" in vl
        panels = vl["hconcat"]
        assert len(panels) == 2

        # Left panel (revenue): shared y shown
        assert panels[0]["encoding"]["y"]["field"] == "country"
        assert panels[0]["encoding"]["y"]["axis"] is not None

        # Right panel (order_count): shared y hidden
        assert panels[1]["encoding"]["y"]["field"] == "country"
        assert panels[1]["encoding"]["y"]["axis"] is None
        assert "title" not in panels[1]["encoding"]["y"]

        assert vl["spacing"] == 10


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

    def test_parses_shared_axis_on_measure_entry(self):
        """KAN-232: shared_axis parses as bool | None."""
        spec = parse_chart(load_yaml("stacked_shared_axis_all.yaml"))
        for entry in spec.rows:
            assert entry.shared_axis is True

    def test_parses_shared_axis_none_by_default(self):
        spec = parse_chart(load_yaml("stacked_panels.yaml"))
        for entry in spec.rows:
            assert entry.shared_axis is None

    def test_parses_layer_entry_and_compiles(self):
        """Schema accepts layers; single-entry layer specs compile (KAN-111)."""
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

        # Now compiles successfully through translate_chart
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "layer" in vl
        assert len(vl["layer"]) == 2
        assert vl["resolve"] == {"scale": {"y": "independent"}}
