"""
Dot Notation Tests

Tests for dot-notation support through the translator layer:
  - build_field_encoding with ModelResolver
  - All grain-to-timeUnit mappings
  - Auto-format injection from model
  - Filter/sort base field resolution
"""

from pathlib import Path

import pytest

from shelves.models.loader import load_model, clear_model_cache
from shelves.models.resolver import ModelResolver
from shelves.schema.chart_schema import AxisChannelConfig, ColorFieldMapping, ShelfFilter, FieldSort
from shelves.translator.encodings import build_color, build_field_encoding, _auto_inject_from_model
from shelves.translator.filters import build_transforms
from shelves.translator.sort import apply_sort

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "models"


@pytest.fixture(autouse=True)
def reset_cache():
    clear_model_cache()
    yield
    clear_model_cache()


@pytest.fixture
def orders_model():
    return load_model("orders", models_dir=FIXTURES_DIR)


# ─── build_field_encoding ────────────────────────────────────────────────────


class TestBuildFieldEncoding:
    def test_temporal_with_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        enc = build_field_encoding("week.month", resolver)
        assert enc == {"field": "week", "type": "temporal", "timeUnit": "yearmonth"}

    def test_temporal_default_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        enc = build_field_encoding("week", resolver)
        assert enc == {"field": "week", "type": "temporal", "timeUnit": "yearweek"}

    def test_measure_no_time_unit(self, orders_model):
        resolver = ModelResolver(orders_model)
        enc = build_field_encoding("revenue", resolver)
        assert enc == {"field": "revenue", "type": "quantitative"}
        assert "timeUnit" not in enc

    def test_all_grain_mappings(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert build_field_encoding("week.day", resolver)["timeUnit"] == "yearmonthdate"
        assert build_field_encoding("week.week", resolver)["timeUnit"] == "yearweek"
        assert build_field_encoding("week.month", resolver)["timeUnit"] == "yearmonth"
        assert build_field_encoding("week.quarter", resolver)["timeUnit"] == "yearquarter"
        assert build_field_encoding("week.year", resolver)["timeUnit"] == "year"


# ─── Auto-format injection ───────────────────────────────────────────────────


class TestAutoFormat:
    def test_format_injected_from_model(self, orders_model):
        resolver = ModelResolver(orders_model)
        enc = build_field_encoding("week.month", resolver)
        _auto_inject_from_model(enc, "week.month", resolver, None, channel="x")
        assert enc["axis"]["format"] == "%b %Y"
        assert enc["axis"]["grid"] is False
        assert enc["title"] == "Week"

    def test_format_not_injected_with_override(self, orders_model):
        resolver = ModelResolver(orders_model)
        enc = build_field_encoding("week.month", resolver)
        axis_cfg = AxisChannelConfig(format="%Y")
        _auto_inject_from_model(enc, "week.month", resolver, axis_cfg, channel="x")
        # Chart override should win — format should not be replaced
        assert enc.get("axis", {}).get("format") != "%b %Y"


# ─── Filter base field resolution ────────────────────────────────────────────


class TestFilterBaseField:
    def test_filter_strips_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        filters = [ShelfFilter(field="week.month", operator="eq", value="2024-01")]
        transforms = build_transforms(filters, resolver)
        assert transforms[0]["filter"]["field"] == "week"


# ─── Sort base field resolution ──────────────────────────────────────────────


class TestSortBaseField:
    def test_sort_strips_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        encoding = {"x": {"field": "week", "type": "temporal"}}
        sort = FieldSort(field="week.month", order="ascending")
        apply_sort(encoding, sort, resolver)
        assert encoding["x"]["sort"]["field"] == "week"


# ─── Stacked shared axis ────────────────────────────────────────────────────


class TestColorFieldMappingDotNotation:
    def test_color_field_mapping_includes_time_unit(self, orders_model):
        resolver = ModelResolver(orders_model)
        color = ColorFieldMapping(field="week.month")
        enc = build_color(color, resolver)
        assert enc["field"] == "week"
        assert enc["type"] == "temporal"
        assert enc["timeUnit"] == "yearmonth"
        assert enc["legend"]["title"] == "Week"

    def test_color_field_mapping_explicit_type_override(self, orders_model):
        resolver = ModelResolver(orders_model)
        color = ColorFieldMapping(field="week.month", type="ordinal")
        enc = build_color(color, resolver)
        assert enc["type"] == "ordinal"
        assert enc["timeUnit"] == "yearmonth"


class TestStackedDotNotation:
    def test_shared_axis_uses_build_field_encoding(self, orders_model):
        resolver = ModelResolver(orders_model)
        enc = build_field_encoding("week.month", resolver)
        assert enc["field"] == "week"
        assert enc["timeUnit"] == "yearmonth"
