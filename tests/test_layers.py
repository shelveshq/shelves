"""
Layer Tests (Phase 1a)

Schema parsing (TestLayerSchemaParsing) passes throughout.
Compilation tests (TestLayerCompilation) pass after KAN-111 is implemented.
Deferred tests (TestLayerStackingDeferred) remain NotImplementedError until KAN-112.
"""

import textwrap

import pytest
from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from tests.conftest import compile_fixture, load_yaml, MODELS_DIR


class TestLayerSchemaParsing:
    """These all pass now — the schema accepts layers."""

    def test_dual_axis_parses(self):
        spec = parse_chart(load_yaml("dual_axis.yaml"))
        assert isinstance(spec.rows, list)
        assert len(spec.rows) == 1
        entry = spec.rows[0]
        assert entry.measure == "revenue"
        assert entry.layer is not None
        assert len(entry.layer) == 1
        assert entry.layer[0].measure == "arpu"
        assert entry.axis == "independent"

    def test_triple_axis_parses(self):
        spec = parse_chart(load_yaml("triple_axis.yaml"))
        entry = spec.rows[0]
        assert entry.measure == "revenue"
        assert len(entry.layer) == 2
        assert entry.layer[0].measure == "arpu"
        assert entry.layer[1].measure == "margin_pct"
        assert entry.layer[1].opacity == 0.3

    def test_stacked_layers_parses(self):
        spec = parse_chart(load_yaml("stacked_layers.yaml"))
        assert len(spec.rows) == 2
        # First entry has layers
        assert spec.rows[0].layer is not None
        assert spec.rows[0].layer[0].measure == "arpu"
        # Second entry is standalone
        assert spec.rows[1].layer is None
        assert spec.rows[1].measure == "order_count"

    def test_layers_faceted_parses(self):
        spec = parse_chart(load_yaml("layers_faceted.yaml"))
        assert spec.rows[0].layer is not None
        assert spec.facet is not None
        assert hasattr(spec.facet, "row")
        assert spec.facet.row == "region"

    def test_layer_mark_object_parses(self):
        spec = parse_chart(load_yaml("dual_axis.yaml"))
        layer = spec.rows[0].layer[0]
        # Mark should be parsed as MarkObject with style
        assert hasattr(layer.mark, "type")
        assert layer.mark.type == "line"
        assert layer.mark.style == "dashed"

    def test_layer_inherits_nothing_by_default(self):
        """Layer entries with no mark/color/detail have None — inheritance
        is handled by the translator, not the schema."""
        yaml_str = textwrap.dedent(
            """
            sheet: "Test"
            data: orders
            cols: week
            marks: line
            rows:
              - measure: revenue
                layer:
                  - measure: arpu
            """
        )
        spec = parse_chart(yaml_str)
        layer = spec.rows[0].layer[0]
        assert layer.mark is None
        assert layer.color is None
        assert layer.detail is None


class TestLayerCompilation:
    """Positive compilation tests for single-entry layered specs (KAN-111)."""

    def test_dual_axis_compiles(self):
        vl = compile_fixture("dual_axis.yaml")
        assert vl["$schema"] == "https://vega.github.io/schema/vega-lite/v6.json"
        assert vl["title"] == "Revenue & ARPU by Week"
        assert "layer" in vl
        assert len(vl["layer"]) == 2

        primary = vl["layer"][0]
        assert primary["mark"] == "bar"
        assert primary["encoding"]["y"]["field"] == "revenue"
        assert primary["encoding"]["y"]["title"] == "Revenue"
        assert primary["encoding"]["y"]["axis"]["format"] == "$,.0f"
        assert primary["encoding"]["x"]["field"] == "week"
        assert primary["encoding"]["color"]["field"] == "country"
        assert primary["encoding"]["detail"]["field"] == "country"
        tooltip_fields = [t["field"] for t in primary["encoding"]["tooltip"]]
        assert tooltip_fields == ["week", "country", "revenue", "arpu"]

        secondary = vl["layer"][1]
        assert secondary["mark"] == {"type": "line", "strokeDash": [6, 4]}
        assert secondary["encoding"]["y"]["field"] == "arpu"
        assert secondary["encoding"]["y"]["title"] == "ARPU"
        assert secondary["encoding"]["color"] == {"value": "#666666"}
        # Detail inherited from entry (cascade entry → layer)
        assert secondary["encoding"]["detail"]["field"] == "country"
        # No tooltip on secondary
        assert "tooltip" not in secondary["encoding"]

        assert vl["resolve"] == {"scale": {"y": "independent"}}

    def test_triple_axis_compiles(self):
        vl = compile_fixture("triple_axis.yaml")
        assert vl["title"] == "Revenue, ARPU & Margin"
        assert len(vl["layer"]) == 3

        assert vl["layer"][0]["mark"] == "bar"
        assert vl["layer"][0]["encoding"]["color"] == {"value": "#4A90D9"}

        assert vl["layer"][1]["mark"] == {"type": "line", "point": True}
        assert vl["layer"][1]["encoding"]["y"]["field"] == "arpu"

        # Opacity merges into mark, promoting string mark to dict
        assert vl["layer"][2]["mark"] == {"type": "area", "opacity": 0.3}
        assert vl["layer"][2]["encoding"]["y"]["field"] == "margin_pct"
        assert vl["layer"][2]["encoding"]["y"]["axis"]["format"] == ".1%"

        # Tooltip on primary only
        assert "tooltip" in vl["layer"][0]["encoding"]
        assert "tooltip" not in vl["layer"][1]["encoding"]
        assert "tooltip" not in vl["layer"][2]["encoding"]

        assert vl["resolve"] == {"scale": {"y": "independent"}}

    def test_shared_axis_default(self):
        vl = compile_fixture("shared_axis.yaml")
        assert vl["title"] == "Revenue vs Cost"
        assert len(vl["layer"]) == 2
        # Critical: no resolve key when axis is None
        assert "resolve" not in vl

    def test_layer_inherits_from_entry(self):
        vl = compile_fixture("layer_inheritance.yaml")
        # Both layers use line mark (inherited from top-level marks: line)
        assert vl["layer"][0]["mark"] == "line"
        assert vl["layer"][1]["mark"] == "line"
        # Both layers use country color (inherited from top-level color: country)
        assert vl["layer"][0]["encoding"]["color"]["field"] == "country"
        assert vl["layer"][1]["encoding"]["color"]["field"] == "country"
        # No resolve (axis defaults to shared)
        assert "resolve" not in vl

    def test_detail_null_suppresses_inheritance(self):
        vl = compile_fixture("layer_detail_null.yaml")
        # Primary has detail
        assert vl["layer"][0]["encoding"]["detail"]["field"] == "country"
        # Layer has explicit detail: null → no detail key
        assert "detail" not in vl["layer"][1]["encoding"]
        # Sort applied to primary's x channel only
        assert vl["layer"][0]["encoding"]["x"]["sort"] == {
            "field": "revenue",
            "order": "descending",
        }
        assert "sort" not in vl["layer"][1]["encoding"]["x"]

    def test_filter_at_layer_group_level(self):
        vl = compile_fixture("layer_with_filter.yaml")
        # Transform appears ONCE at the layer-group level
        assert "transform" in vl
        assert vl["transform"] == [{"filter": {"field": "country", "oneOf": ["US", "UK"]}}]
        # Individual layers do NOT have transform
        for layer in vl["layer"]:
            assert "transform" not in layer

    def test_size_and_opacity_on_layer(self):
        vl = compile_fixture("layer_size_opacity.yaml")
        layer = vl["layer"][1]
        # Opacity merges into mark object (string mark gets promoted to dict)
        assert layer["mark"] == {"type": "circle", "opacity": 0.5}
        # Size goes into encoding as a value (numeric → {value: N})
        assert layer["encoding"]["size"] == {"value": 200}
        # Primary layer has no opacity / size
        assert vl["layer"][0]["mark"] == "line"
        assert "size" not in vl["layer"][0]["encoding"]

    def test_error_no_mark_for_entry(self):
        yaml_str = textwrap.dedent("""
            sheet: "Bad"
            data: orders
            cols: week
            rows:
              - measure: revenue
                layer:
                  - measure: arpu
                    mark: line
        """)
        spec = parse_chart(yaml_str)
        with pytest.raises(ValueError, match="No mark defined for measure 'revenue'"):
            translate_chart(spec, models_dir=MODELS_DIR)


class TestLayerStackingDeferred:
    """
    Deferred compilation tests for layered specs with additional complexity.

    - test_stacked_layers_raises: multi-entry shelves where some entries have
      layers are KAN-112. Raises NotImplementedError until then.

    - test_layers_faceted_compiles_basic: layers + facet compiles via KAN-111
      (facet.py wraps the layer spec unchanged). This test asserts only the
      structural skeleton. KAN-113 adds detailed assertions — correct facet
      field encoding, resolve propagation through the facet wrapper, and
      per-facet tooltip behaviour.
    """

    def test_stacked_layers_raises(self):
        spec = parse_chart(load_yaml("stacked_layers.yaml"))
        with pytest.raises(NotImplementedError):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_layers_faceted_compiles_basic(self):
        """
        Layers + facet compiles after KAN-111 (facet.py needs no changes).

        KAN-113 TODO: assert facet field encoding, resolve propagation through
        the facet wrapper, and per-facet tooltip behaviour.
        """
        vl = compile_fixture("layers_faceted.yaml")
        # Facet wrapper is present
        assert "facet" in vl
        assert "spec" in vl
        # Inner spec is a layer group
        inner = vl["spec"]
        assert "layer" in inner
        assert len(inner["layer"]) == 2
        # Resolve propagates through facet wrapper (axis: independent on the entry)
        assert inner.get("resolve") == {"scale": {"y": "independent"}}
