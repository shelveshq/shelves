"""
Tests for KAN-200: Model-based chart spec translation.

Tests that `data: "orders"` (string shorthand) parses correctly,
routes through ModelResolver, and produces correct Vega-Lite output.
Also verifies backward compatibility with legacy DataSource form.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.schema.chart_schema import DSL_VERSION, DataSource, parse_chart
from src.translator.translate import translate_chart
from src.models.loader import clear_model_cache

from tests.conftest import load_yaml

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MODELS_DIR = FIXTURES_DIR / "models"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the model cache before each test."""
    clear_model_cache()
    yield
    clear_model_cache()


class TestModelParse:
    """Tests that data: string parses correctly."""

    def test_data_string_parses(self):
        spec = parse_chart(
            'sheet: "Revenue by Country"\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n'
        )
        assert spec.data == "orders"
        assert isinstance(spec.data, str)

    def test_legacy_data_source_parses(self):
        yaml_str = load_yaml("simple_bar.yaml")
        spec = parse_chart(yaml_str)
        assert isinstance(spec.data, DataSource)

    def test_dsl_version(self):
        assert DSL_VERSION == "0.2.0"


class TestModelTranslate:
    """End-to-end tests: model-based spec → Vega-Lite output."""

    def test_model_simple_bar(self):
        yaml_str = load_yaml("model_simple_bar.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert vl["$schema"] == "https://vega.github.io/schema/vega-lite/v6.json"
        assert vl["mark"] == "bar"
        assert vl["encoding"]["x"]["field"] == "country"
        assert vl["encoding"]["x"]["type"] == "nominal"
        assert vl["encoding"]["y"]["field"] == "revenue"
        assert vl["encoding"]["y"]["type"] == "quantitative"

    def test_model_temporal_dot_notation(self):
        yaml_str = load_yaml("model_temporal_dot.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert vl["$schema"] == "https://vega.github.io/schema/vega-lite/v6.json"
        assert vl["mark"] == "line"

        x_enc = vl["encoding"]["x"]
        assert x_enc["field"] == "week"
        assert x_enc["type"] == "temporal"
        assert x_enc["timeUnit"] == "yearmonth"
        assert x_enc["axis"]["format"] == "%b %Y"

        y_enc = vl["encoding"]["y"]
        assert y_enc["field"] == "revenue"
        assert y_enc["type"] == "quantitative"

    def test_model_stacked_panels(self):
        yaml_str = load_yaml("model_stacked.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert vl["$schema"] == "https://vega.github.io/schema/vega-lite/v6.json"
        assert vl["repeat"]["row"] == ["revenue", "order_count"]

        inner = vl["spec"]
        assert inner["mark"] == "line"

        x_enc = inner["encoding"]["x"]
        assert x_enc["field"] == "week"
        assert x_enc["type"] == "temporal"
        assert x_enc["timeUnit"] == "yearmonth"

        y_enc = inner["encoding"]["y"]
        assert y_enc["field"] == {"repeat": "row"}
        assert y_enc["type"] == "quantitative"

    def test_nonexistent_model_raises(self):
        spec = parse_chart('sheet: "Bad"\ndata: nonexistent\ncols: x\nrows: y\nmarks: bar\n')
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_unknown_field_raises(self):
        spec = parse_chart(
            'sheet: "Bad"\ndata: orders\ncols: nonexistent\nrows: revenue\nmarks: bar\n'
        )
        with pytest.raises(ValueError, match="nonexistent"):
            translate_chart(spec, models_dir=MODELS_DIR)

    def test_custom_models_dir(self):
        spec = parse_chart('sheet: "Test"\ndata: orders\ncols: country\nrows: revenue\nmarks: bar')
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert vl["encoding"]["x"]["field"] == "country"
