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

    def test_stacked_bar_label_has_stack(self):
        vl = compile_fixture("label_grouped_bar.yaml")
        text_layer = vl["layer"][1]
        # Text marks don't auto-stack — must match the bar's stack: zero
        assert text_layer["encoding"]["y"]["stack"] == "zero"

    def test_unstacked_bar_label_no_stack(self):
        vl = compile_fixture("label_bar_simple.yaml")
        text_layer = vl["layer"][1]
        # No color grouping → bar isn't stacked → label shouldn't stack
        assert "stack" not in text_layer["encoding"]["y"]

    def test_hex_color_bar_label_no_stack(self):
        yaml = """\
sheet: "Test"
data: orders
cols: country
rows: revenue
marks: bar
color: "#4A90D9"
label: true
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        text_layer = vl["layer"][1]
        # Hex color → value encoding, no stacking
        assert "stack" not in text_layer["encoding"]["y"]

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


# ═══ Layer Label Compilation Tests (KAN-278) ═══════════════════════


class TestLayerLabelCompilation:
    def test_layer_bar_line_labels_bar_only(self):
        vl = compile_fixture("label_layer_bar_line.yaml")
        assert "layer" in vl
        assert len(vl["layer"]) == 3

        # Primary bar layer
        bar_layer = vl["layer"][0]
        assert bar_layer["mark"] == "bar"
        assert bar_layer["encoding"]["x"]["field"] == "week"
        assert bar_layer["encoding"]["y"]["field"] == "revenue"
        assert bar_layer["encoding"]["color"]["field"] == "country"
        assert "tooltip" in bar_layer["encoding"]

        # Label layer for bar
        label_layer = vl["layer"][1]
        assert label_layer["mark"]["type"] == "text"
        assert label_layer["mark"]["baseline"] == "top"
        assert label_layer["mark"]["dy"] == 6
        assert label_layer["mark"]["color"] == "#ffffff"
        assert label_layer["encoding"]["x"]["field"] == "week"
        assert label_layer["encoding"]["y"]["field"] == "revenue"
        assert label_layer["encoding"]["text"]["field"] == "revenue"
        assert label_layer["encoding"]["text"]["type"] == "quantitative"
        assert label_layer["encoding"]["text"]["format"] == "$,.0f"
        assert label_layer["encoding"]["detail"]["field"] == "country"
        assert label_layer["encoding"]["detail"]["type"] == "nominal"
        assert "tooltip" not in label_layer["encoding"]

        # Secondary line layer — no label injected
        line_layer = vl["layer"][2]
        assert line_layer["mark"]["type"] == "line"

        # Resolve for independent y
        assert vl["resolve"] == {"scale": {"y": "independent"}}

    def test_layer_entry_label_config(self):
        yaml = """\
sheet: "Revenue & Orders"
data: orders
cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: order_count
        mark: bar
        label:
          position: top
          color: "#333333"
          size: 10
          format: ",.0f"
    axis: independent
label: true
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "layer" in vl
        # [primary_bar, primary_label, secondary_bar, secondary_label]
        assert len(vl["layer"]) == 4

        # Primary bar label — defaults (inside-top, white)
        primary_label = vl["layer"][1]
        assert primary_label["mark"]["type"] == "text"
        assert primary_label["mark"]["baseline"] == "top"
        assert primary_label["mark"]["dy"] == 6
        assert primary_label["mark"]["color"] == "#ffffff"

        # Secondary bar label — config overrides
        secondary_label = vl["layer"][3]
        assert secondary_label["mark"]["type"] == "text"
        assert secondary_label["mark"]["baseline"] == "bottom"
        assert secondary_label["mark"]["dy"] == -6
        assert secondary_label["mark"]["color"] == "#333333"
        assert secondary_label["mark"]["fontSize"] == 10
        assert secondary_label["encoding"]["text"]["format"] == ",.0f"

    def test_layer_entry_label_false_suppresses(self):
        vl = compile_fixture("label_layer_suppress.yaml")
        assert "layer" in vl
        # [primary_bar, primary_label, secondary_bar] — secondary has NO label
        assert len(vl["layer"]) == 3

        assert vl["layer"][0]["mark"] == "bar"
        assert vl["layer"][1]["mark"]["type"] == "text"
        assert vl["layer"][2]["mark"] == "bar"

    def test_entry_label_false_suppresses_all(self):
        yaml = """\
sheet: "Revenue & Orders"
data: orders
cols: week
rows:
  - measure: revenue
    mark: bar
    label: false
    layer:
      - measure: order_count
        mark: bar
    axis: independent
label: true
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "layer" in vl
        # No labels — entry-level false overrides top-level true
        assert len(vl["layer"]) == 2
        assert vl["layer"][0]["mark"] == "bar"
        assert vl["layer"][1]["mark"] == "bar"

    def test_stacked_layers_with_labels(self):
        vl = compile_fixture("label_stacked_layers_labeled.yaml")
        assert "vconcat" in vl
        assert len(vl["vconcat"]) == 2

        # Panel 0: layered bar+line — bar gets label
        panel0 = vl["vconcat"][0]
        assert "layer" in panel0
        assert len(panel0["layer"]) == 3
        assert panel0["layer"][0]["mark"] == "bar"
        assert panel0["layer"][1]["mark"]["type"] == "text"
        assert panel0["layer"][2]["mark"]["type"] == "line"

        # Panel 1: simple bar — wrapped with label
        panel1 = vl["vconcat"][1]
        assert "layer" in panel1
        assert len(panel1["layer"]) == 2
        assert panel1["layer"][0]["mark"] == "bar"
        assert panel1["layer"][1]["mark"]["type"] == "text"

    def test_stacked_layers_simple_line_skipped(self):
        yaml = """\
sheet: "Revenue & Orders"
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
        color: "#666666"
    axis: independent
  - measure: order_count
    mark: line
label: true
tooltip: [week, revenue, arpu, order_count]
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "vconcat" in vl

        # Panel 0: layered — bar gets label
        panel0 = vl["vconcat"][0]
        assert "layer" in panel0
        assert len(panel0["layer"]) == 3

        # Panel 1: simple line — NOT wrapped (no layer key)
        panel1 = vl["vconcat"][1]
        assert "layer" not in panel1
        assert panel1["mark"] == "line"

    def test_filter_hoisting_with_labels(self):
        yaml = """\
sheet: "Revenue & ARPU"
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
        color: "#666666"
    axis: independent
label: true
filters:
  - field: country
    operator: in
    values: ["US", "UK"]
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        # Transforms at layer-group level
        assert "transform" in vl
        # NOT on individual layer children
        for layer_child in vl["layer"]:
            assert "transform" not in layer_child

    def test_sort_preserved_on_primary_label(self):
        yaml = """\
sheet: "Revenue & ARPU"
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
        color: "#666666"
    axis: independent
label: true
sort:
  field: revenue
  order: descending
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)

        primary_bar = vl["layer"][0]
        assert "sort" in primary_bar["encoding"]["x"]

        label_layer = vl["layer"][1]
        assert label_layer["encoding"]["x"]["sort"] == primary_bar["encoding"]["x"]["sort"]

        secondary_line = vl["layer"][2]
        assert "sort" not in secondary_line["encoding"]["x"]

    def test_color_field_to_detail_on_label(self):
        vl = compile_fixture("label_layer_bar_line.yaml")
        label_layer = vl["layer"][1]
        # Color field NOT on color encoding — moved to detail
        assert "color" not in label_layer["encoding"]
        # Color field used as detail for correct per-group positioning
        assert label_layer["encoding"]["detail"]["field"] == "country"
        assert label_layer["encoding"]["detail"]["type"] == "nominal"
        # Contrast color set via mark properties, not data-driven
        assert label_layer["mark"]["color"] == "#ffffff"

    def test_hex_color_not_inherited(self):
        yaml = """\
sheet: "Revenue & ARPU"
data: orders
cols: week
rows:
  - measure: revenue
    mark: bar
    color: "#4A90D9"
    layer:
      - measure: arpu
        mark:
          type: line
          style: dashed
        color: "#666666"
    axis: independent
label: true
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        label_layer = vl["layer"][1]
        assert "color" not in label_layer["encoding"]
        assert "detail" not in label_layer["encoding"]
        # Label still gets contrast color via mark property
        assert label_layer["mark"]["color"] == "#ffffff"

    def test_inside_contrast_white(self):
        vl = compile_fixture("label_layer_bar_line.yaml")
        label_layer = vl["layer"][1]
        assert label_layer["mark"]["color"] == "#ffffff"
        assert label_layer["mark"]["baseline"] == "top"
        assert label_layer["mark"]["dy"] == 6

    def test_outside_contrast_dark(self):
        yaml = """\
sheet: "Revenue & ARPU"
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
        color: "#666666"
    axis: independent
label:
  position: top
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        label_layer = vl["layer"][1]
        assert label_layer["mark"]["color"] == "#333333"
        assert label_layer["mark"]["baseline"] == "bottom"
        assert label_layer["mark"]["dy"] == -6

    def test_tooltip_not_on_label(self):
        vl = compile_fixture("label_layer_bar_line.yaml")
        primary_bar = vl["layer"][0]
        assert "tooltip" in primary_bar["encoding"]

        label_layer = vl["layer"][1]
        assert "tooltip" not in label_layer["encoding"]

        secondary_line = vl["layer"][2]
        assert "tooltip" not in secondary_line["encoding"]

    def test_axis_metadata_stripped(self):
        vl = compile_fixture("label_layer_bar_line.yaml")
        primary_bar = vl["layer"][0]
        assert "title" in primary_bar["encoding"]["x"]
        assert "axis" in primary_bar["encoding"]["x"]
        assert "title" in primary_bar["encoding"]["y"]
        assert "axis" in primary_bar["encoding"]["y"]

        label_layer = vl["layer"][1]
        # Shared axis (x): axis popped — doesn't interfere with dimension labels
        assert "title" not in label_layer["encoding"]["x"]
        assert "axis" not in label_layer["encoding"]["x"]
        # Measure axis (y): axis explicitly null — prevents duplicate under independent resolution
        assert "title" not in label_layer["encoding"]["y"]
        assert label_layer["encoding"]["y"]["axis"] is None

    def test_all_non_bar_layers_no_labels(self):
        yaml = """\
sheet: "Revenue & Cost"
data: orders
cols: week
rows:
  - measure: revenue
    mark: line
    layer:
      - measure: cost
        mark: area
label: true
"""
        spec = parse_chart(yaml)
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "layer" in vl
        assert len(vl["layer"]) == 2

    def test_label_omitted_no_change(self):
        vl = compile_fixture("dual_axis.yaml")
        assert "layer" in vl
        assert len(vl["layer"]) == 2
        # No label layers — existing behavior preserved
        for child in vl["layer"]:
            assert child["mark"] != {"type": "text"} or "text" not in child.get("encoding", {})
