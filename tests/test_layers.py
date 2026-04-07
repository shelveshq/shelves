"""
Layer Tests (Phase 1a)

Schema parsing works now. Compilation raises NotImplementedError
until patterns/layers.py is implemented.

When implementing Phase 1a, replace the NotImplementedError assertions
with actual output assertions.
"""

import textwrap

import pytest
from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from tests.conftest import load_yaml, MODELS_DIR


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


class TestLayerCompilationDeferred:
    """These confirm the translator raises NotImplementedError for layers.
    Replace with real assertions when implementing Phase 1a."""

    def test_dual_axis_raises(self):
        spec = parse_chart(load_yaml("dual_axis.yaml"))
        with pytest.raises(NotImplementedError):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_triple_axis_raises(self):
        spec = parse_chart(load_yaml("triple_axis.yaml"))
        with pytest.raises(NotImplementedError):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_stacked_layers_raises(self):
        spec = parse_chart(load_yaml("stacked_layers.yaml"))
        with pytest.raises(NotImplementedError):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_layers_faceted_raises(self):
        spec = parse_chart(load_yaml("layers_faceted.yaml"))
        with pytest.raises(NotImplementedError):
            translate_chart(spec, models_dir=MODELS_DIR)
