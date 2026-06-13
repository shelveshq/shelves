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

        # KAN-223-A: shared-scale text layer must omit axis key (not null)
        assert "axis" not in text_layer["encoding"]["x"]
        assert "axis" not in text_layer["encoding"]["y"]
        assert "title" not in text_layer["encoding"]["x"]
        assert "title" not in text_layer["encoding"]["y"]

        # Primary bar layer still owns the axis (regression check)
        assert mark_layer["encoding"]["y"]["axis"] == {"format": "$,.0f", "grid": True}
        assert mark_layer["encoding"]["y"]["title"] == "Revenue"

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

        # KAN-223-A: shared-scale text layer must omit axis key (not null)
        assert "axis" not in text_layer["encoding"]["x"]
        assert "axis" not in text_layer["encoding"]["y"]
        assert "title" not in text_layer["encoding"]["x"]
        assert "title" not in text_layer["encoding"]["y"]

    def test_line_label(self):
        vl = compile_fixture("label_line.yaml")
        assert "layer" in vl
        text_layer = vl["layer"][1]

        mark = text_layer["mark"]
        assert mark["type"] == "text"
        assert mark["baseline"] == "bottom"
        assert mark["dy"] == -8  # line gets extra clearance

        # KAN-223-A: shared-scale text layer must omit axis key (not null)
        assert "axis" not in text_layer["encoding"]["x"]
        assert "axis" not in text_layer["encoding"]["y"]
        assert "title" not in text_layer["encoding"]["x"]
        assert "title" not in text_layer["encoding"]["y"]

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

        # Shared-scale: text layer y encoding must omit axis key (not null)
        assert "axis" not in text_layer_rev["encoding"]["y"]
        assert "axis" not in text_layer_ord["encoding"]["y"]

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

        # KAN-223-A: shared axis (x) omits key; independent axis (y) uses null
        assert "axis" not in text_layer["encoding"]["x"]
        assert text_layer["encoding"]["y"]["axis"] is None
        assert "title" not in text_layer["encoding"]["x"]
        assert "title" not in text_layer["encoding"]["y"]

        # Primary bar layer and arpu line layer keep their axis metadata
        assert bar_layer["encoding"]["y"]["axis"] == {"format": "$,.0f", "grid": True}
        assert "title" in bar_layer["encoding"]["y"]
        assert arpu_layer["encoding"]["y"]["axis"] == {"format": "$,.2f", "grid": True}

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

    def test_layered_both_no_duplicate_axis(self):
        """Dual-axis layered spec: text layers must not duplicate primary axes."""
        vl = compile_fixture("label_layered_both.yaml")
        assert vl["resolve"]["scale"]["y"] == "independent"

        layers = vl["layer"]
        assert len(layers) == 4

        # Primary mark layers keep axis + title
        bar_layer = layers[0]
        assert bar_layer["encoding"]["y"]["axis"] == {"format": "$,.0f", "grid": True}
        assert bar_layer["encoding"]["y"]["title"] == "Revenue"

        line_layer = layers[2]
        assert line_layer["encoding"]["y"]["axis"] == {"format": "$,.2f", "grid": True}
        assert line_layer["encoding"]["y"]["title"] == "ARPU"

        # Text layers: shared axis (x) omits key; independent axis (y) uses null
        revenue_text = layers[1]
        arpu_text = layers[3]
        for text_layer in (revenue_text, arpu_text):
            assert text_layer["mark"]["type"] == "text"
            assert "axis" not in text_layer["encoding"]["x"]
            assert text_layer["encoding"]["y"]["axis"] is None
            assert "title" not in text_layer["encoding"]["x"]
            assert "title" not in text_layer["encoding"]["y"]

        # Field/type/timeUnit preserved (positioning on shared scale still works)
        assert revenue_text["encoding"]["x"]["field"] == "week"
        assert revenue_text["encoding"]["x"]["type"] == "temporal"
        assert revenue_text["encoding"]["x"]["timeUnit"] == "yearweek"
        assert revenue_text["encoding"]["y"]["field"] == "revenue"
        assert arpu_text["encoding"]["y"]["field"] == "arpu"

    def test_layered_horizontal_label(self):
        """Horizontal layered chart: label layer must not swap x/y encodings."""
        vl = compile_fixture("label_layered_horizontal.yaml")
        assert "layer" in vl
        assert vl["resolve"]["scale"]["x"] == "independent"

        # bar(revenue) + text(revenue) + bar(cost) + text(cost) = 4 layers
        assert len(vl["layer"]) == 4

        bar_layer = vl["layer"][0]
        revenue_text = vl["layer"][1]
        cost_text = vl["layer"][3]

        # Primary bar: y=country (shared), x=revenue (measure)
        assert bar_layer["encoding"]["y"]["field"] == "country"
        assert bar_layer["encoding"]["x"]["field"] == "revenue"

        # Revenue text label: must match primary's axis assignment
        assert revenue_text["mark"]["type"] == "text"
        assert revenue_text["encoding"]["y"]["field"] == "country"
        assert revenue_text["encoding"]["x"]["field"] == "revenue"
        assert revenue_text["encoding"]["text"]["field"] == "revenue"

        # Cost text label: same axis assignment
        assert cost_text["mark"]["type"] == "text"
        assert cost_text["encoding"]["y"]["field"] == "country"
        assert cost_text["encoding"]["x"]["field"] == "cost"
        assert cost_text["encoding"]["text"]["field"] == "cost"

        # Shared axis (y) omits axis key; independent axis (x) uses null
        for text_layer in (revenue_text, cost_text):
            assert "axis" not in text_layer["encoding"]["y"]
            assert text_layer["encoding"]["x"]["axis"] is None
            assert "title" not in text_layer["encoding"]["y"]
            assert "title" not in text_layer["encoding"]["x"]

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


def _find_headroom_layer(layers: list) -> dict | None:
    """Find the invisible headroom layer (tick with opacity 0) in a layer list."""
    for layer in layers:
        mark = layer.get("mark", {})
        if isinstance(mark, dict) and mark.get("type") == "tick" and mark.get("opacity") == 0:
            return layer
    return None


def _headroom_extends(headroom_layer: dict, axis: str, field: str, agg_op: str) -> bool:
    """Check that a headroom layer aggregates the expected field on the expected axis."""
    transforms = headroom_layer.get("transform", [])
    if len(transforms) < 2:
        return False
    agg = transforms[0].get("aggregate", [{}])[0]
    if agg.get("op") != agg_op or agg.get("field") != field:
        return False
    enc = headroom_layer.get("encoding", {})
    return axis in enc and enc[axis].get("field") == "_hroom"


class TestLabelHeadroom:
    """Headroom injection tests: outside-positioned labels extend the axis domain."""

    def test_bar_label_headroom_top(self):
        """Vertical bar with label: true → headroom layer extends y via max."""
        vl = compile_fixture("label_bar_simple.yaml")
        assert "layer" in vl
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is not None
        assert _headroom_extends(hroom, "y", "revenue", "max")
        assert "padding" not in vl

    def test_horizontal_bar_label_headroom_right(self):
        """Horizontal bar with label: true → headroom layer extends x via max."""
        vl = compile_fixture("label_horizontal_bar.yaml")
        assert "layer" in vl
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is not None
        assert _headroom_extends(hroom, "x", "revenue", "max")
        assert "padding" not in vl

    def test_line_label_headroom_top(self):
        """Line chart with label: true → headroom layer extends y via max."""
        vl = compile_fixture("label_line.yaml")
        assert "layer" in vl
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is not None
        assert _headroom_extends(hroom, "y", "revenue", "max")
        assert "padding" not in vl

    def test_stacked_label_headroom(self):
        """Stacked bar panels with labels → each panel has a headroom layer."""
        vl = compile_fixture("label_stacked.yaml")
        assert "vconcat" in vl
        for panel in vl["vconcat"]:
            hroom = _find_headroom_layer(panel["layer"])
            assert hroom is not None
        assert "padding" not in vl

    def test_layered_label_headroom(self):
        """Layered chart: primary bar with label → headroom layer extends y."""
        vl = compile_fixture("label_layered.yaml")
        assert "layer" in vl
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is not None
        assert _headroom_extends(hroom, "y", "revenue", "max")
        assert "padding" not in vl

    def test_layered_both_labels_headroom(self):
        """Dual-axis with both labels → headroom layers present."""
        vl = compile_fixture("label_layered_both.yaml")
        assert "layer" in vl
        headroom_layers = [
            l for l in vl["layer"]
            if isinstance(l.get("mark"), dict) and l["mark"].get("opacity") == 0
        ]
        assert len(headroom_layers) >= 1
        assert "padding" not in vl

    def test_layered_horizontal_label_headroom(self):
        """Horizontal layered chart: both labels → headroom layers on x."""
        vl = compile_fixture("label_layered_horizontal.yaml")
        assert "layer" in vl
        headroom_layers = [
            l for l in vl["layer"]
            if isinstance(l.get("mark"), dict) and l["mark"].get("opacity") == 0
        ]
        assert len(headroom_layers) >= 1
        assert "padding" not in vl

    def test_scatter_label_headroom(self):
        """Circle mark with label: true → headroom layer extends y."""
        vl = compile_fixture("label_scatter.yaml")
        assert "layer" in vl
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is not None
        assert _headroom_extends(hroom, "y", "order_count", "max")
        assert "padding" not in vl

    def test_label_inside_position_no_headroom(self):
        """Inside-positioned label → no headroom layer, no view padding."""
        vl = compile_fixture("label_bar_config.yaml")
        assert "layer" in vl
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is None
        assert "padding" not in vl

    def test_label_categorical_axis_view_padding(self):
        """Label extending along x (nominal) → view-level padding.left: 40."""
        vl = compile_fixture("label_left.yaml")
        assert "layer" in vl
        assert vl.get("padding") == {"left": 40}
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is None

    def test_label_bottom_headroom(self):
        """Position bottom on vertical bar → headroom layer extends y via min."""
        vl = compile_fixture("label_bottom.yaml")
        assert "layer" in vl
        hroom = _find_headroom_layer(vl["layer"])
        assert hroom is not None
        assert _headroom_extends(hroom, "y", "revenue", "min")
        assert "padding" not in vl
