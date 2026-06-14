"""
Label Tests (KAN-269)

Tests for data labels on bar/column charts — schema parsing, helper functions,
and full compilation (single-measure + stacked panels).
"""

import pytest
from pydantic import ValidationError

from shelves.schema.chart_schema import LabelConfig, parse_chart
from shelves.translator.labels import (
    detect_orientation,
    is_bar_mark,
    resolve_label_cascade,
    resolve_label_spec,
)
from tests.conftest import MODELS_DIR, compile_fixture, load_yaml

# ═══ Schema Tests ═══════════════════════════════════════════════════


class TestLabelSchema:
    def test_label_true_parses(self):
        spec = parse_chart(load_yaml("label_bar_simple.yaml"))
        assert spec.label is True

    def test_label_false_parses(self):
        yaml = """\
sheet: "Test"
data: orders
cols: country
rows: revenue
marks: bar
label: false
"""
        spec = parse_chart(yaml)
        assert spec.label is False

    def test_label_config_parses(self):
        spec = parse_chart(load_yaml("label_bar_config.yaml"))
        assert isinstance(spec.label, LabelConfig)
        assert spec.label.position == "top"
        assert spec.label.color == "#333333"
        assert spec.label.size == 10
        assert spec.label.format == ",.0f"

    def test_label_omitted_is_none(self):
        spec = parse_chart(load_yaml("simple_bar.yaml"))
        assert spec.label is None

    def test_invalid_position_rejected(self):
        yaml = """\
sheet: "Test"
data: orders
cols: country
rows: revenue
marks: bar
label:
  position: center
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml)

    def test_invalid_color_rejected(self):
        yaml = """\
sheet: "Test"
data: orders
cols: country
rows: revenue
marks: bar
label:
  color: "not-a-color"
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml)

    def test_zero_size_rejected(self):
        yaml = """\
sheet: "Test"
data: orders
cols: country
rows: revenue
marks: bar
label:
  size: 0
"""
        with pytest.raises(ValidationError):
            parse_chart(yaml)


# ═══ Helper Unit Tests ══════════════════════════════════════════════


class TestLabelHelpers:
    def test_resolve_label_spec_none(self):
        assert resolve_label_spec(None) is None

    def test_resolve_label_spec_false(self):
        assert resolve_label_spec(False) is None

    def test_resolve_label_spec_true(self):
        result = resolve_label_spec(True)
        assert isinstance(result, LabelConfig)
        assert result.field is None
        assert result.position is None

    def test_resolve_label_spec_config(self):
        cfg = LabelConfig(position="top", color="#FF0000")
        assert resolve_label_spec(cfg) is cfg

    def test_resolve_label_cascade_layer_wins(self):
        assert resolve_label_cascade(False, True, True) is False

    def test_resolve_label_cascade_entry_wins(self):
        assert resolve_label_cascade(None, False, True) is False

    def test_resolve_label_cascade_top_level(self):
        assert resolve_label_cascade(None, None, True) is True

    def test_resolve_label_cascade_all_none(self):
        assert resolve_label_cascade(None, None, None) is None

    def test_detect_orientation_vertical(self):
        from shelves.models.loader import load_model
        from shelves.models.resolver import ModelResolver

        spec = parse_chart(load_yaml("label_bar_simple.yaml"))
        model = load_model("orders", models_dir=MODELS_DIR)
        resolver = ModelResolver(model)
        assert detect_orientation(spec, resolver) == "vertical"

    def test_detect_orientation_horizontal(self):
        from shelves.models.loader import load_model
        from shelves.models.resolver import ModelResolver

        spec = parse_chart(load_yaml("label_bar_horizontal.yaml"))
        model = load_model("orders", models_dir=MODELS_DIR)
        resolver = ModelResolver(model)
        assert detect_orientation(spec, resolver) == "horizontal"

    def test_is_bar_mark_string(self):
        assert is_bar_mark("bar") is True
        assert is_bar_mark("line") is False
        assert is_bar_mark("area") is False
        assert is_bar_mark("text") is False

    def test_is_bar_mark_object(self):
        from shelves.schema.chart_schema import MarkObject

        assert is_bar_mark(MarkObject(type="bar")) is True
        assert is_bar_mark(MarkObject(type="line")) is False


# ═══ Compilation Tests ══════════════════════════════════════════════


class TestLabelCompilation:
    def test_bar_simple(self):
        vl = compile_fixture("label_bar_simple.yaml")
        assert "layer" in vl
        assert len(vl["layer"]) == 2

        bar_layer = vl["layer"][0]
        assert bar_layer["mark"] == "bar"
        assert bar_layer["encoding"]["x"]["field"] == "country"
        assert bar_layer["encoding"]["x"]["title"] == "Country"
        assert bar_layer["encoding"]["y"]["field"] == "revenue"
        assert bar_layer["encoding"]["y"]["title"] == "Revenue"

        text_layer = vl["layer"][1]
        assert text_layer["mark"]["type"] == "text"
        assert text_layer["mark"]["baseline"] == "top"
        assert text_layer["mark"]["dy"] == 6
        assert text_layer["mark"]["color"] == "#ffffff"

        assert text_layer["encoding"]["x"]["field"] == "country"
        assert text_layer["encoding"]["y"]["field"] == "revenue"
        assert text_layer["encoding"]["text"]["field"] == "revenue"
        assert text_layer["encoding"]["text"]["type"] == "quantitative"
        assert text_layer["encoding"]["text"]["format"] == "$,.0f"

        # Axis metadata stripped from text layer
        assert "title" not in text_layer["encoding"]["x"]
        assert "axis" not in text_layer["encoding"]["x"]
        assert "title" not in text_layer["encoding"]["y"]
        assert "axis" not in text_layer["encoding"]["y"]

        # No transform when no filters
        assert "transform" not in vl

    def test_bar_horizontal(self):
        vl = compile_fixture("label_bar_horizontal.yaml")
        assert "layer" in vl
        assert len(vl["layer"]) == 2

        text_layer = vl["layer"][1]
        assert text_layer["mark"]["type"] == "text"
        assert text_layer["mark"]["align"] == "right"
        assert text_layer["mark"]["dx"] == -6
        assert text_layer["mark"]["color"] == "#ffffff"

        assert text_layer["encoding"]["x"]["field"] == "revenue"
        assert text_layer["encoding"]["y"]["field"] == "country"
        assert text_layer["encoding"]["text"]["field"] == "revenue"
        assert text_layer["encoding"]["text"]["format"] == "$,.0f"

    def test_bar_config_overrides(self):
        vl = compile_fixture("label_bar_config.yaml")
        text_layer = vl["layer"][1]

        # position: top → outside-top (baseline bottom, dy -6)
        assert text_layer["mark"]["baseline"] == "bottom"
        assert text_layer["mark"]["dy"] == -6
        assert text_layer["mark"]["color"] == "#333333"
        assert text_layer["mark"]["fontSize"] == 10

        assert text_layer["encoding"]["text"]["format"] == ",.0f"

    def test_bar_custom_field(self):
        vl = compile_fixture("label_bar_custom_field.yaml")
        text_layer = vl["layer"][1]

        assert text_layer["encoding"]["text"]["field"] == "order_count"
        assert text_layer["encoding"]["text"]["type"] == "quantitative"
        assert text_layer["encoding"]["text"]["format"] == ",.0f"

    def test_grouped_bar_with_color(self):
        vl = compile_fixture("label_grouped_bar.yaml")
        assert "layer" in vl
        text_layer = vl["layer"][1]

        # Color field moved to detail for grouping (not color, to avoid overriding label color)
        assert "color" not in text_layer["encoding"]
        assert text_layer["encoding"]["detail"]["field"] == "product"
        assert text_layer["encoding"]["detail"]["type"] == "nominal"

        # Label still gets default contrast color via mark properties
        assert text_layer["mark"]["color"] == "#ffffff"

        # Tooltip NOT on text layer
        assert "tooltip" not in text_layer["encoding"]

    def test_filter_hoisted_to_layer_group(self):
        vl = compile_fixture("label_bar_filtered.yaml")
        assert "layer" in vl

        # Transforms at top level of the layer group
        assert "transform" in vl
        assert vl["transform"][0]["filter"]["oneOf"] == ["US", "UK", "DE"]

        # NOT on individual layers
        assert "transform" not in vl["layer"][0]
        assert "transform" not in vl["layer"][1]

    def test_label_false_no_layer(self):
        yaml = """\
sheet: "Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
label: false
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "layer" not in vl
        assert vl["mark"] == "bar"

    def test_label_omitted_no_layer(self):
        vl = compile_fixture("simple_bar.yaml")
        assert "layer" not in vl
        assert vl["mark"] == "bar"

    def test_sort_preserved(self):
        vl = compile_fixture("label_bar_sorted.yaml")
        assert "layer" in vl

        bar_layer = vl["layer"][0]
        assert "sort" in bar_layer["encoding"]["x"]

        # Sort preserved on label layer for correct positioning
        text_layer = vl["layer"][1]
        assert text_layer["encoding"]["x"]["sort"] == bar_layer["encoding"]["x"]["sort"]

    def test_stacked_vconcat_labels(self):
        vl = compile_fixture("label_stacked_diff_marks.yaml")
        assert "vconcat" in vl
        assert len(vl["vconcat"]) == 2

        # First panel (bar) should be wrapped with label layer
        bar_panel = vl["vconcat"][0]
        assert "layer" in bar_panel
        assert len(bar_panel["layer"]) == 2
        assert bar_panel["layer"][0]["mark"] == "bar"
        assert bar_panel["layer"][1]["mark"]["type"] == "text"
        assert bar_panel["layer"][1]["mark"]["baseline"] == "top"
        assert bar_panel["layer"][1]["mark"]["dy"] == 6

        # Second panel (line) should NOT be wrapped — silently skipped
        line_panel = vl["vconcat"][1]
        assert "layer" not in line_panel
        assert line_panel["mark"] == "line"

        # Shared axis hiding still applies: top panel x-axis suppressed
        # After label wrapping, suppression applies to BOTH layer children
        for layer_spec in bar_panel["layer"]:
            assert layer_spec["encoding"]["x"]["axis"] is None
            assert "title" not in layer_spec["encoding"]["x"]

        # Bottom panel's x-axis is shown
        assert line_panel["encoding"]["x"]["axis"] is not None

    def test_stacked_per_entry_label(self):
        vl = compile_fixture("label_stacked_per_entry.yaml")
        assert "vconcat" in vl
        assert len(vl["vconcat"]) == 2

        # First panel (revenue): inherits top-level label: true → wrapped
        first_panel = vl["vconcat"][0]
        assert "layer" in first_panel

        # Second panel (order_count): label: false at entry → NOT wrapped
        second_panel = vl["vconcat"][1]
        assert "layer" not in second_panel

    def test_stacked_same_mark_degrades_to_concat(self):
        vl = compile_fixture("label_stacked_same_mark.yaml")
        # With label: true, repeat degrades to vconcat
        assert "vconcat" in vl
        assert "repeat" not in vl
        assert len(vl["vconcat"]) == 2

        # Each panel is wrapped with its own label layer
        for panel in vl["vconcat"]:
            assert "layer" in panel
            assert panel["layer"][1]["mark"]["type"] == "text"

        # Shared axis shown on both panels (shared_axis: true)
        for panel in vl["vconcat"]:
            bar_enc = panel["layer"][0]["encoding"]
            assert bar_enc["x"].get("axis") is not None or "title" in bar_enc["x"]

    def test_non_bar_mark_skipped(self):
        vl = compile_fixture("label_line_skipped.yaml")
        assert "layer" not in vl
        assert vl["mark"] == "line"

    def test_inside_position_default_white_label(self):
        vl = compile_fixture("label_bar_simple.yaml")
        text_layer = vl["layer"][1]
        assert text_layer["mark"]["color"] == "#ffffff"

    def test_outside_position_default_dark_label(self):
        vl = compile_fixture("label_bar_config.yaml")
        # label_bar_config uses position: top (outside)
        text_layer = vl["layer"][1]
        assert text_layer["mark"]["color"] == "#333333"

    def test_explicit_color_overrides_default(self):
        yaml = """\
sheet: "Test"
data: orders
cols: country
rows: revenue
marks: bar
label:
  color: "#FF0000"
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        text_layer = vl["layer"][1]
        assert text_layer["mark"]["color"] == "#FF0000"
