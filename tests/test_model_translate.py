"""
Tests for model-based chart spec translation.

Tests that `data: "orders"` parses correctly, routes through
ModelResolver, and produces correct Vega-Lite output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shelves.schema.chart_schema import DSL_VERSION, parse_chart
from shelves.translator.translate import translate_chart
from shelves.models.loader import clear_model_cache

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

    def test_dsl_version(self):
        assert DSL_VERSION == "0.4.0"


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

        # NEW: auto-injected from model
        assert vl["encoding"]["x"]["title"] == "Country"
        assert vl["encoding"]["y"]["title"] == "Revenue"
        assert vl["encoding"]["y"]["axis"]["format"] == "$,.0f"
        assert vl["encoding"]["y"]["axis"]["grid"] is True
        assert vl["encoding"]["x"]["axis"]["grid"] is False

        # NEW: default sort from model (country has sortOrder)
        assert vl["encoding"]["x"]["sort"] == ["US", "UK", "FR", "DE", "JP"]

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
        # NEW
        assert x_enc["title"] == "Week"
        assert x_enc["axis"]["grid"] is False

        y_enc = vl["encoding"]["y"]
        assert y_enc["field"] == "revenue"
        assert y_enc["type"] == "quantitative"
        # NEW
        assert y_enc["title"] == "Revenue"
        assert y_enc["axis"]["format"] == "$,.0f"
        assert y_enc["axis"]["grid"] is True

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
        # NEW
        assert x_enc["title"] == "Week"
        assert x_enc["axis"]["format"] == "%b %Y"

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
