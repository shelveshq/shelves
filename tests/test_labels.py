"""
Label Tests (KAN-223)

Schema parsing (TestLabelSchema) and compilation tests (TestLabelCompilation)
for the `label` property — data labels as implicit text-mark layers.
"""

import textwrap

import pytest
from pydantic import ValidationError

from shelves.schema.chart_schema import LabelConfig, parse_chart
from tests.conftest import compile_fixture, MODELS_DIR


class TestLabelSchema:
    """Schema-level parsing tests — no compilation needed."""

    def test_label_true_parses(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label: true
        """)
        )
        assert spec.label is True

    def test_label_false_parses(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label: false
        """)
        )
        assert spec.label is False

    def test_label_omitted_defaults_to_none(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: country
            rows: revenue
            marks: bar
        """)
        )
        assert spec.label is None

    def test_label_config_object_parses(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label:
              position: inside-top
              color: "#ffffff"
              size: 10
              format: "$,.0f"
              field: revenue
        """)
        )
        assert isinstance(spec.label, LabelConfig)
        assert spec.label.position == "inside-top"
        assert spec.label.color == "#ffffff"
        assert spec.label.size == 10
        assert spec.label.format == "$,.0f"
        assert spec.label.field == "revenue"

    def test_label_on_measure_entry_parses(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: week
            rows:
              - measure: revenue
                mark: bar
                label: true
              - measure: order_count
                mark: line
                label: false
        """)
        )
        assert spec.rows[0].label is True
        assert spec.rows[1].label is False

    def test_label_on_layer_entry_parses(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: week
            rows:
              - measure: revenue
                mark: bar
                label: true
                layer:
                  - measure: arpu
                    mark: line
                    label: false
        """)
        )
        assert spec.rows[0].label is True
        assert spec.rows[0].layer[0].label is False

    def test_invalid_position(self):
        with pytest.raises(ValidationError):
            parse_chart(
                textwrap.dedent("""
                sheet: Bad
                data: orders
                cols: country
                rows: revenue
                marks: bar
                label:
                  position: center
            """)
            )

    def test_invalid_label_color(self):
        with pytest.raises(ValidationError):
            parse_chart(
                textwrap.dedent("""
                sheet: Bad
                data: orders
                cols: country
                rows: revenue
                marks: bar
                label:
                  color: "not-a-color"
            """)
            )


class TestLabelHelpers:
    """Unit tests for pure helper functions in labels.py."""

    def test_resolve_label_spec_none(self):
        from shelves.translator.labels import resolve_label_spec

        assert resolve_label_spec(None) is None

    def test_resolve_label_spec_false(self):
        from shelves.translator.labels import resolve_label_spec

        assert resolve_label_spec(False) is None

    def test_resolve_label_spec_true(self):
        from shelves.translator.labels import resolve_label_spec

        result = resolve_label_spec(True)
        assert isinstance(result, LabelConfig)

    def test_resolve_label_spec_config(self):
        from shelves.translator.labels import resolve_label_spec

        cfg = LabelConfig(position="top")
        result = resolve_label_spec(cfg)
        assert result is cfg

    def test_resolve_label_cascade_layer_wins(self):
        from shelves.translator.labels import resolve_label_cascade

        assert resolve_label_cascade(False, True, True) is False

    def test_resolve_label_cascade_entry_wins_when_layer_none(self):
        from shelves.translator.labels import resolve_label_cascade

        assert resolve_label_cascade(None, False, True) is False

    def test_resolve_label_cascade_top_level_fallback(self):
        from shelves.translator.labels import resolve_label_cascade

        assert resolve_label_cascade(None, None, True) is True

    def test_resolve_label_cascade_all_none(self):
        from shelves.translator.labels import resolve_label_cascade

        assert resolve_label_cascade(None, None, None) is None


class TestLabelCompilation:
    """Full compilation tests: YAML fixture → Vega-Lite dict."""

    def test_bar_label_true(self):
        vl = compile_fixture("label_bar_simple.yaml")
        assert "layer" in vl
        assert len(vl["layer"]) == 2

        mark_layer = vl["layer"][0]
        assert mark_layer["mark"] == "bar"
        assert mark_layer["encoding"]["x"]["field"] == "country"
        assert mark_layer["encoding"]["y"]["field"] == "revenue"

        text_layer = vl["layer"][1]
        assert text_layer["mark"]["type"] == "text"
        assert text_layer["mark"]["baseline"] == "bottom"
        assert text_layer["mark"]["dy"] == -6

        assert text_layer["encoding"]["x"]["field"] == "country"
        assert text_layer["encoding"]["y"]["field"] == "revenue"
        assert text_layer["encoding"]["text"]["field"] == "revenue"
        assert text_layer["encoding"]["text"]["type"] == "quantitative"
        assert text_layer["encoding"]["text"]["format"] == "$,.0f"

    def test_bar_label_config(self):
        vl = compile_fixture("label_bar_config.yaml")
        assert "layer" in vl
        text_layer = vl["layer"][1]

        mark = text_layer["mark"]
        assert mark["type"] == "text"
        assert mark["baseline"] == "top"
        assert mark["dy"] == 6
        assert mark["color"] == "#ffffff"
        assert mark["fontSize"] == 10

        assert text_layer["encoding"]["text"]["field"] == "revenue"
        assert text_layer["encoding"]["text"]["format"] == "$,.0f"

    def test_horizontal_bar_label(self):
        vl = compile_fixture("label_horizontal_bar.yaml")
        assert "layer" in vl
        text_layer = vl["layer"][1]

        mark = text_layer["mark"]
        assert mark["type"] == "text"
        assert mark["align"] == "left"
        assert mark["dx"] == 6

        # Horizontal: measure is on x, dimension on y
        assert text_layer["encoding"]["x"]["field"] == "revenue"
        assert text_layer["encoding"]["y"]["field"] == "country"
        assert text_layer["encoding"]["text"]["field"] == "revenue"
        assert text_layer["encoding"]["text"]["type"] == "quantitative"

    def test_line_label(self):
        vl = compile_fixture("label_line.yaml")
        assert "layer" in vl
        text_layer = vl["layer"][1]

        mark = text_layer["mark"]
        assert mark["type"] == "text"
        assert mark["baseline"] == "bottom"
        assert mark["dy"] == -8  # line gets extra clearance

    def test_label_format_override(self):
        vl = compile_fixture("label_format_override.yaml")
        text_layer = vl["layer"][1]
        assert text_layer["encoding"]["text"]["format"] == "$.0s"

    def test_label_custom_field(self):
        vl = compile_fixture("label_custom_field.yaml")
        text_layer = vl["layer"][1]
        text_enc = text_layer["encoding"]["text"]
        assert text_enc["field"] == "country"
        assert text_enc["type"] == "nominal"
        assert "format" not in text_enc

    def test_label_false_no_layer(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label: false
        """)
        )
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "layer" not in vl
        assert vl["mark"] == "bar"

    def test_label_none_no_layer(self):
        vl = compile_fixture("simple_bar.yaml")
        assert "layer" not in vl

    def test_label_on_text_mark_noop(self):
        spec = parse_chart(
            textwrap.dedent("""
            sheet: Test
            data: orders
            cols: country
            rows: revenue
            marks: text
            label: true
        """)
        )
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        # text mark with label: true — no extra text layer
        assert "layer" not in vl

    def test_stacked_label(self):
        vl = compile_fixture("label_stacked.yaml")
        assert "vconcat" in vl
        assert vl["spacing"] == 10

        revenue_panel = vl["vconcat"][0]
        order_panel = vl["vconcat"][1]

        # Revenue panel: layered
        assert "layer" in revenue_panel
        assert len(revenue_panel["layer"]) == 2
        text_layer_rev = revenue_panel["layer"][1]
        assert text_layer_rev["mark"]["type"] == "text"
        assert text_layer_rev["encoding"]["text"]["field"] == "revenue"
        assert text_layer_rev["encoding"]["text"]["format"] == "$,.0f"

        # Order_count panel: layered
        assert "layer" in order_panel
        assert len(order_panel["layer"]) == 2
        text_layer_ord = order_panel["layer"][1]
        assert text_layer_ord["mark"]["type"] == "text"
        assert text_layer_ord["encoding"]["text"]["field"] == "order_count"
        assert text_layer_ord["encoding"]["text"]["format"] == ",.0f"

        # KAN-232: top panel's x axis should be suppressed
        for child in revenue_panel["layer"]:
            assert child["encoding"]["x"].get("axis") is None

    def test_stacked_per_entry_label(self):
        vl = compile_fixture("label_stacked_per_entry.yaml")
        assert "vconcat" in vl

        revenue_panel = vl["vconcat"][0]
        order_panel = vl["vconcat"][1]

        # Revenue has label: true → two-child layer
        assert "layer" in revenue_panel
        assert revenue_panel["layer"][1]["mark"]["type"] == "text"
        assert revenue_panel["layer"][1]["encoding"]["text"]["field"] == "revenue"

        # Order_count has label: false → bare panel (no layer)
        assert "layer" not in order_panel
        assert order_panel["mark"] == "line"

    def test_layered_label(self):
        vl = compile_fixture("label_layered.yaml")
        assert "layer" in vl
        # primary (bar) + text layer for revenue + arpu line = 3 layers
        assert len(vl["layer"]) == 3

        bar_layer = vl["layer"][0]
        text_layer = vl["layer"][1]
        arpu_layer = vl["layer"][2]

        assert bar_layer["mark"] == "bar"
        assert text_layer["mark"]["type"] == "text"
        assert text_layer["encoding"]["text"]["field"] == "revenue"

        # arpu is a line layer — no label since entry.layer[0].label is None
        assert arpu_layer["encoding"]["y"]["field"] == "arpu"

    def test_layered_label_both(self):
        vl = compile_fixture("label_layered_both.yaml")
        assert "layer" in vl
        # bar + text(revenue) + line(arpu) + text(arpu) = 4 layers
        assert len(vl["layer"]) == 4

        assert vl["layer"][0]["mark"] == "bar"
        assert vl["layer"][1]["mark"]["type"] == "text"
        assert vl["layer"][1]["encoding"]["text"]["field"] == "revenue"
        assert vl["layer"][1]["mark"]["dy"] == -6  # bar offset

        assert vl["layer"][2]["encoding"]["y"]["field"] == "arpu"
        assert vl["layer"][3]["mark"]["type"] == "text"
        assert vl["layer"][3]["encoding"]["text"]["field"] == "arpu"
        assert vl["layer"][3]["mark"]["dy"] == -8  # line offset

    def test_label_with_color_encoding(self):
        vl = compile_fixture("label_with_color.yaml")
        text_layer = vl["layer"][1]

        # Color inherited from parent with legend: null (suppresses duplicate legend)
        assert "color" in text_layer["encoding"]
        color_enc = text_layer["encoding"]["color"]
        assert color_enc["field"] == "country"
        assert color_enc["type"] == "nominal"
        assert color_enc["legend"] is None

    def test_label_with_filter(self):
        vl = compile_fixture("label_with_filter.yaml")
        assert "layer" in vl
        # Transform should be at the layer-group level, NOT inside each child
        assert "transform" in vl
        for child in vl["layer"]:
            assert "transform" not in child
