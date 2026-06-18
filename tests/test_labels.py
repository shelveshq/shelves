"""
Label Intent Tests (KAN-281)

Tests for label schema parsing, label helper functions, and label intent
emission across all three pattern compilers (single, stacked, layers).
"""

import textwrap

import pytest
from pydantic import ValidationError

from shelves.schema.chart_schema import LabelConfig, parse_chart
from shelves.translator.labels import (
    build_label_intent,
    resolve_label_cascade,
    resolve_label_spec,
    resolve_measure_field,
)
from tests.conftest import MODELS_DIR, compile_fixture

# ─── Schema Tests ────────────────────────────────────────────────────


class TestLabelSchema:
    """Parsing and validation of the label DSL property."""

    def test_label_true_parses(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
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
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label: false
        """)
        )
        assert spec.label is False

    def test_label_config_parses(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label:
              vertical: top
              horizontal: right
              color: "#333333"
              size: 10
              format: ",.0f"
              field: order_count
        """)
        )
        assert isinstance(spec.label, LabelConfig)
        assert spec.label.vertical == "top"
        assert spec.label.horizontal == "right"
        assert spec.label.color == "#333333"
        assert spec.label.size == 10
        assert spec.label.format == ",.0f"
        assert spec.label.field == "order_count"

    def test_label_match_color_parses(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label:
              color: match
        """)
        )
        assert isinstance(spec.label, LabelConfig)
        assert spec.label.color == "match"

    def test_label_on_measure_entry(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: week
            rows:
              - measure: revenue
                mark: bar
                label: false
              - measure: order_count
                mark: line
            label: true
        """)
        )
        assert spec.rows[0].label is False
        assert spec.rows[1].label is None
        assert spec.label is True

    def test_label_on_layer_entry(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: week
            rows:
              - measure: revenue
                mark: bar
                layer:
                  - measure: arpu
                    mark: line
                    label: false
                axis: independent
            label: true
        """)
        )
        assert spec.rows[0].layer[0].label is False

    def test_invalid_color_rejected(self):
        with pytest.raises(ValidationError):
            parse_chart(
                textwrap.dedent("""\
                sheet: "Test"
                data: orders
                cols: country
                rows: revenue
                marks: bar
                label:
                  color: "not-a-color"
            """)
            )

    def test_zero_size_rejected(self):
        with pytest.raises(ValidationError):
            parse_chart(
                textwrap.dedent("""\
                sheet: "Test"
                data: orders
                cols: country
                rows: revenue
                marks: bar
                label:
                  size: 0
            """)
            )

    def test_negative_size_rejected(self):
        with pytest.raises(ValidationError):
            parse_chart(
                textwrap.dedent("""\
                sheet: "Test"
                data: orders
                cols: country
                rows: revenue
                marks: bar
                label:
                  size: -1
            """)
            )

    def test_invalid_vertical_rejected(self):
        with pytest.raises(ValidationError):
            parse_chart(
                textwrap.dedent("""\
                sheet: "Test"
                data: orders
                cols: country
                rows: revenue
                marks: bar
                label:
                  vertical: inside-top
            """)
            )

    def test_invalid_horizontal_rejected(self):
        with pytest.raises(ValidationError):
            parse_chart(
                textwrap.dedent("""\
                sheet: "Test"
                data: orders
                cols: country
                rows: revenue
                marks: bar
                label:
                  horizontal: top
            """)
            )


# ─── Helper Unit Tests ───────────────────────────────────────────────


class TestLabelHelpers:
    """Unit tests for the labels.py helper functions."""

    def test_resolve_label_spec_none(self):
        assert resolve_label_spec(None) is None

    def test_resolve_label_spec_false(self):
        assert resolve_label_spec(False) is None

    def test_resolve_label_spec_true(self):
        result = resolve_label_spec(True)
        assert isinstance(result, LabelConfig)
        assert result.field is None
        assert result.horizontal is None
        assert result.vertical is None

    def test_resolve_label_spec_config(self):
        config = LabelConfig(vertical="top", size=10)
        assert resolve_label_spec(config) is config

    def test_cascade_layer_wins(self):
        result = resolve_label_cascade(False, True, True)
        assert result is False

    def test_cascade_entry_wins(self):
        result = resolve_label_cascade(None, False, True)
        assert result is False

    def test_cascade_top_wins(self):
        result = resolve_label_cascade(None, None, True)
        assert result is True

    def test_cascade_all_none(self):
        result = resolve_label_cascade(None, None, None)
        assert result is None

    def test_resolve_measure_field_rows_measure(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: country
            rows: revenue
            marks: bar
        """)
        )
        from shelves.models.loader import load_model
        from shelves.models.resolver import ModelResolver

        model = load_model("orders", models_dir=MODELS_DIR)
        resolver = ModelResolver(model)
        assert resolve_measure_field(spec, resolver) == "revenue"

    def test_resolve_measure_field_cols_measure(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: revenue
            rows: country
            marks: bar
        """)
        )
        from shelves.models.loader import load_model
        from shelves.models.resolver import ModelResolver

        model = load_model("orders", models_dir=MODELS_DIR)
        resolver = ModelResolver(model)
        assert resolve_measure_field(spec, resolver) == "revenue"

    def test_build_label_intent_defaults(self):
        from shelves.models.loader import load_model
        from shelves.models.resolver import ModelResolver

        model = load_model("orders", models_dir=MODELS_DIR)
        resolver = ModelResolver(model)
        config = LabelConfig()
        result = build_label_intent("mark_0", "revenue", config, resolver)
        assert result == {
            "markName": "mark_0",
            "field": "revenue",
            "type": "quantitative",
            "format": "$,.0f",
            "horizontal": None,
            "vertical": None,
            "size": 11,
            "color": None,
        }

    def test_build_label_intent_overrides(self):
        from shelves.models.loader import load_model
        from shelves.models.resolver import ModelResolver

        model = load_model("orders", models_dir=MODELS_DIR)
        resolver = ModelResolver(model)
        config = LabelConfig(
            field="order_count",
            horizontal="right",
            vertical="top",
            color="#333333",
            size=10,
            format=",.0f",
        )
        result = build_label_intent("mark_1", "revenue", config, resolver)
        assert result == {
            "markName": "mark_1",
            "field": "order_count",
            "type": "quantitative",
            "format": ",.0f",
            "horizontal": "right",
            "vertical": "top",
            "size": 10,
            "color": "#333333",
        }


# ─── Compilation Tests ───────────────────────────────────────────────


class TestLabelCompilation:
    """End-to-end compilation tests: YAML → Vega-Lite with label intents."""

    def test_bar_simple(self):
        vl = compile_fixture("label_bar_simple.yaml")

        assert vl["name"] == "mark_0"
        assert vl["mark"] == "bar"
        assert "layer" not in vl

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0] == {
            "markName": "mark_0",
            "field": "revenue",
            "type": "quantitative",
            "format": "$,.0f",
            "horizontal": None,
            "vertical": None,
            "size": 11,
            "color": None,
        }

    def test_bar_horizontal(self):
        vl = compile_fixture("label_bar_horizontal.yaml")

        labels = vl["usermeta"]["charter"]["labels"]
        assert labels[0]["field"] == "revenue"
        assert labels[0]["format"] == "$,.0f"
        assert labels[0]["horizontal"] is None
        assert labels[0]["vertical"] is None

    def test_bar_config_overrides(self):
        vl = compile_fixture("label_bar_config.yaml")

        labels = vl["usermeta"]["charter"]["labels"]
        assert labels[0] == {
            "markName": "mark_0",
            "field": "revenue",
            "type": "quantitative",
            "format": ",.0f",
            "horizontal": None,
            "vertical": "top",
            "size": 10,
            "color": "#333333",
        }

    def test_bar_custom_field(self):
        vl = compile_fixture("label_bar_custom_field.yaml")

        labels = vl["usermeta"]["charter"]["labels"]
        assert labels[0]["field"] == "order_count"
        assert labels[0]["type"] == "quantitative"
        assert labels[0]["format"] == ",.0f"

    def test_bar_match_color(self):
        vl = compile_fixture("label_bar_match_color.yaml")

        labels = vl["usermeta"]["charter"]["labels"]
        assert labels[0]["color"] == "match"

    def test_line_emits_intent(self):
        vl = compile_fixture("label_line.yaml")

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0]["markName"] == "mark_0"
        assert labels[0]["field"] == "revenue"

        assert vl["mark"] == "line"
        assert "layer" not in vl

    def test_label_false_no_intent(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Revenue by Country"
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label: false
        """)
        )
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert "usermeta" not in vl
        assert "name" not in vl

    def test_label_omitted_no_intent(self):
        vl = compile_fixture("simple_bar.yaml")
        assert "usermeta" not in vl
        assert "name" not in vl

    def test_both_axes(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Revenue by Country"
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label:
              vertical: top
              horizontal: right
        """)
        )
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)
        labels = vl["usermeta"]["charter"]["labels"]
        assert labels[0]["vertical"] == "top"
        assert labels[0]["horizontal"] == "right"

    # ─── Stacked Tests ───────────────────────────────────────────

    def test_stacked_vconcat(self):
        vl = compile_fixture("label_stacked_vconcat.yaml")

        assert "vconcat" in vl
        assert len(vl["vconcat"]) == 2

        assert vl["vconcat"][0]["name"] == "mark_0"
        assert vl["vconcat"][1]["name"] == "mark_1"

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 2
        assert labels[0] == {
            "markName": "mark_0",
            "field": "revenue",
            "type": "quantitative",
            "format": "$,.0f",
            "horizontal": None,
            "vertical": None,
            "size": 11,
            "color": None,
        }
        assert labels[1] == {
            "markName": "mark_1",
            "field": "order_count",
            "type": "quantitative",
            "format": ",.0f",
            "horizontal": None,
            "vertical": None,
            "size": 11,
            "color": None,
        }

        for panel in vl["vconcat"]:
            assert "layer" not in panel

    def test_stacked_per_entry_cascade(self):
        vl = compile_fixture("label_stacked_per_entry.yaml")

        assert "vconcat" in vl
        assert len(vl["vconcat"]) == 2

        assert vl["vconcat"][0]["name"] == "mark_0"
        assert "name" not in vl["vconcat"][1]

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0]["markName"] == "mark_0"
        assert labels[0]["field"] == "revenue"

    def test_stacked_same_mark_degrades_to_concat(self):
        vl = compile_fixture("label_stacked_same_mark.yaml")

        assert "vconcat" in vl
        assert "repeat" not in vl
        assert len(vl["vconcat"]) == 2

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 2
        assert labels[0]["field"] == "revenue"
        assert labels[0]["format"] == "$,.0f"
        assert labels[1]["field"] == "order_count"
        assert labels[1]["format"] == ",.0f"

    # ─── Layer Tests ─────────────────────────────────────────────

    def test_layer_entry_labels(self):
        vl = compile_fixture("label_layers.yaml")

        assert "layer" in vl
        assert len(vl["layer"]) == 2

        assert vl["layer"][0]["name"] == "mark_0"
        assert vl["layer"][1]["name"] == "mark_1"

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 2
        assert labels[0]["markName"] == "mark_0"
        assert labels[0]["field"] == "revenue"
        assert labels[0]["format"] == "$,.0f"
        assert labels[1]["markName"] == "mark_1"
        assert labels[1]["field"] == "arpu"
        assert labels[1]["format"] == "$,.2f"

    def test_stacked_layers_labels(self):
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Revenue+ARPU Panel, Orders Panel"
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
              - measure: order_count
                mark: line
            label: true
        """)
        )
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert "vconcat" in vl
        assert len(vl["vconcat"]) == 2

        assert "layer" in vl["vconcat"][0]
        assert vl["vconcat"][0]["layer"][0]["name"] == "mark_0"
        assert vl["vconcat"][0]["layer"][1]["name"] == "mark_1"

        assert vl["vconcat"][1]["name"] == "mark_2"

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 3
        assert labels[0]["field"] == "revenue"
        assert labels[1]["field"] == "arpu"
        assert labels[2]["field"] == "order_count"

    def test_per_layer_label_suppression(self):
        # `label: false` on a single layer suppresses only that mark's intent;
        # siblings under top-level `label: true` still emit (was label_layer_suppress).
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: week
            rows:
              - measure: revenue
                mark: bar
                layer:
                  - measure: arpu
                    mark: bar
                    label: false
                axis: independent
            label: true
        """)
        )
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)

        labels = vl["usermeta"]["charter"]["labels"]
        assert {lbl["markName"] for lbl in labels} == {"mark_0"}
        assert labels[0]["field"] == "revenue"
        # The suppressed layer still gets a name, just no intent referencing it.
        assert vl["layer"][1]["name"] == "mark_1"

    def test_labels_survive_filter_transform(self):
        # A filter transform must not drop label intent (was label_bar_filtered).
        spec = parse_chart(
            textwrap.dedent("""\
            sheet: "Test"
            data: orders
            cols: country
            rows: revenue
            marks: bar
            label: true
            filters:
              - field: country
                operator: neq
                value: "FR"
        """)
        )
        from shelves.translator.translate import translate_chart

        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert "transform" in vl  # filter survived
        assert vl["name"] == "mark_0"
        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0]["markName"] == "mark_0"
        assert labels[0]["field"] == "revenue"


# ─── Point / Tick Mark Label Tests (KAN-285) ───────────────────────


class TestPointMarkLabels:
    """Regression guards: point-family and tick marks emit label intent."""

    def test_circle_emits_intent(self):
        vl = compile_fixture("label_scatter.yaml")

        assert vl["mark"] == "circle"
        assert vl["name"] == "mark_0"

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0] == {
            "markName": "mark_0",
            "field": "order_count",
            "type": "quantitative",
            "format": ",.0f",
            "horizontal": None,
            "vertical": None,
            "size": 11,
            "color": None,
        }

    def test_circle_custom_field(self):
        vl = compile_fixture("label_scatter_field.yaml")

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0] == {
            "markName": "mark_0",
            "field": "country",
            "type": "nominal",
            "format": None,
            "horizontal": None,
            "vertical": None,
            "size": 11,
            "color": None,
        }

    def test_point_emits_intent(self):
        vl = compile_fixture("label_point.yaml")

        assert vl["mark"] == "point"
        assert vl["name"] == "mark_0"

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0]["field"] == "order_count"
        assert labels[0]["markName"] == "mark_0"

    def test_tick_emits_intent(self):
        vl = compile_fixture("label_tick.yaml")

        assert vl["mark"] == "tick"
        assert vl["name"] == "mark_0"

        labels = vl["usermeta"]["charter"]["labels"]
        assert len(labels) == 1
        assert labels[0] == {
            "markName": "mark_0",
            "field": "revenue",
            "type": "quantitative",
            "format": "$,.0f",
            "horizontal": None,
            "vertical": None,
            "size": 11,
            "color": None,
        }
