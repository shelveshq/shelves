"""
Panel Encoding Builder Tests

Unit tests for translator/panel.py — shared panel encoding logic.
"""

from shelves.schema.chart_schema import MeasureEntry, parse_chart
from shelves.models.loader import load_model
from shelves.models.resolver import ModelResolver
from shelves.translator.encodings import build_field_encoding
from shelves.translator.panel import build_panel_encoding
from tests.conftest import load_yaml, MODELS_DIR


def _make_resolver() -> ModelResolver:
    model = load_model("orders", models_dir=MODELS_DIR)
    return ModelResolver(model)


class TestBuildPanelEncoding:
    def test_basic_panel(self):
        """build_panel_encoding produces correct encoding for a simple entry."""
        entry = MeasureEntry(measure="revenue", mark="bar")
        spec = parse_chart(load_yaml("stacked_diff_marks.yaml"))
        resolver = _make_resolver()
        shared_enc = build_field_encoding("week", resolver)

        encoding = build_panel_encoding(
            entry=entry,
            shared_enc=shared_enc,
            shared_field="week",
            shared_axis="x",
            measure_axis="y",
            spec=spec,
            resolver=resolver,
        )
        assert encoding["x"]["field"] == "week"
        assert encoding["y"]["field"] == "revenue"

    def test_entry_color_overrides_top_level(self):
        entry = MeasureEntry(measure="revenue", mark="bar", color="#ff0000")
        spec = parse_chart("""
sheet: "Test"
data: orders
cols: week
marks: bar
color: country
rows:
  - measure: revenue
    mark: bar
    color: "#ff0000"
  - measure: order_count
    mark: line
""")
        resolver = _make_resolver()
        shared_enc = build_field_encoding("week", resolver)

        encoding = build_panel_encoding(
            entry=entry,
            shared_enc=shared_enc,
            shared_field="week",
            shared_axis="x",
            measure_axis="y",
            spec=spec,
            resolver=resolver,
        )
        assert encoding["color"] == {"value": "#ff0000"}

    def test_top_level_color_used_when_entry_has_none(self):
        entry = MeasureEntry(measure="revenue", mark="bar")
        spec = parse_chart("""
sheet: "Test"
data: orders
cols: week
marks: bar
color: country
rows:
  - measure: revenue
    mark: bar
  - measure: order_count
    mark: line
""")
        resolver = _make_resolver()
        shared_enc = build_field_encoding("week", resolver)

        encoding = build_panel_encoding(
            entry=entry,
            shared_enc=shared_enc,
            shared_field="week",
            shared_axis="x",
            measure_axis="y",
            spec=spec,
            resolver=resolver,
        )
        assert encoding["color"]["field"] == "country"

    def test_no_color_when_both_none(self):
        entry = MeasureEntry(measure="revenue", mark="bar")
        spec = parse_chart("""
sheet: "Test"
data: orders
cols: week
marks: bar
rows:
  - measure: revenue
    mark: bar
  - measure: order_count
    mark: line
""")
        resolver = _make_resolver()
        shared_enc = build_field_encoding("week", resolver)

        encoding = build_panel_encoding(
            entry=entry,
            shared_enc=shared_enc,
            shared_field="week",
            shared_axis="x",
            measure_axis="y",
            spec=spec,
            resolver=resolver,
        )
        assert "color" not in encoding
