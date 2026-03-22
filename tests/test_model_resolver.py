"""
ModelResolver Tests

Validates that ModelResolver correctly resolves field types, labels, formats,
time units, sort defaults, and sort orders from a loaded DataModel.

Uses the orders fixture model (tests/fixtures/models/orders.yaml) which has:
  Measures: revenue ($,.0f, descending), order_count (,.0f), arpu ($,.2f), cost, margin_pct
  Nominal dims: country (sortOrder=[US,UK,FR,DE,JP], ascending), region, product
  Temporal dims: week (defaultGrain=week), month (defaultGrain=month)
"""

from pathlib import Path

import pytest

from src.models.loader import load_model, clear_model_cache
from src.models.resolver import ModelResolver
from src.schema.field_types import FieldTypeResolver

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "models"


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear model cache before and after every test."""
    clear_model_cache()
    yield
    clear_model_cache()


@pytest.fixture
def orders_model():
    return load_model("orders", models_dir=FIXTURES_DIR)


# ─── resolve_type / resolve ────────────────────────────────────────────────────


class TestResolveType:
    def test_measure_returns_quantitative(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_type("revenue") == "quantitative"
        assert resolver.resolve_type("order_count") == "quantitative"

    def test_nominal_returns_nominal(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_type("country") == "nominal"
        assert resolver.resolve_type("region") == "nominal"

    def test_dot_notation_on_measure_raises(self, orders_model):
        resolver = ModelResolver(orders_model)
        with pytest.raises(ValueError, match="not valid for measure"):
            resolver.resolve_type("revenue.something")

    def test_dot_notation_on_nominal_raises(self, orders_model):
        resolver = ModelResolver(orders_model)
        with pytest.raises(ValueError, match="not valid for nominal dimension"):
            resolver.resolve_type("country.foo")

    def test_dot_notation_on_formula_raises(self, orders_model):
        resolver = ModelResolver(orders_model, formulas={"calc_margin": "revenue - cost"})
        with pytest.raises(ValueError, match="not valid for formula"):
            resolver.resolve_type("calc_margin.month")

    def test_temporal_with_grain_returns_temporal(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_type("week.month") == "temporal"

    def test_temporal_no_grain_returns_temporal(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_type("week") == "temporal"

    def test_invalid_grain_raises(self):
        model = load_model("temporal_explicit_grains", models_dir=FIXTURES_DIR)
        resolver = ModelResolver(model)
        # model has grains: [year] only
        with pytest.raises(ValueError, match="not supported"):
            resolver.resolve_type("year_field.month")

    def test_valid_grain_passes(self, orders_model):
        resolver = ModelResolver(orders_model)
        # orders model has default grains (all five)
        assert resolver.resolve_type("week.month") == "temporal"
        assert resolver.resolve_type("week.day") == "temporal"

    def test_unknown_field_raises(self, orders_model):
        resolver = ModelResolver(orders_model)
        with pytest.raises(ValueError, match="nonexistent"):
            resolver.resolve_type("nonexistent")

    def test_formula_returns_quantitative(self, orders_model):
        resolver = ModelResolver(orders_model, formulas={"calc_margin": "revenue - cost"})
        assert resolver.resolve_type("calc_margin") == "quantitative"

    def test_resolve_alias(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve("revenue") == "quantitative"
        assert resolver.resolve("country") == "nominal"

    def test_satisfies_protocol(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert isinstance(resolver, FieldTypeResolver)


# ─── resolve_label ─────────────────────────────────────────────────────────────


class TestResolveLabel:
    def test_measure_label(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_label("revenue") == "Revenue"
        assert resolver.resolve_label("order_count") == "Orders"

    def test_formula_label_humanized(self, orders_model):
        resolver = ModelResolver(orders_model, formulas={"total_revenue": ""})
        assert resolver.resolve_label("total_revenue") == "Total Revenue"


# ─── resolve_format ────────────────────────────────────────────────────────────


class TestResolveFormat:
    def test_measure_format(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_format("revenue") == "$,.0f"

    def test_temporal_format_with_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_format("week.month") == "%b %Y"
        assert resolver.resolve_format("week.day") == "%b %d, %Y"

    def test_temporal_format_default_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        # week's defaultGrain is "week", format map has "week" → "%b %d"
        assert resolver.resolve_format("week") == "%b %d"

    def test_nominal_format_none(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_format("country") is None


# ─── resolve_time_unit ─────────────────────────────────────────────────────────


class TestResolveTimeUnit:
    def test_temporal_time_unit_with_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_time_unit("week.month") == "yearmonth"
        assert resolver.resolve_time_unit("week.week") == "yearweek"
        assert resolver.resolve_time_unit("week.day") == "yearmonthdate"
        assert resolver.resolve_time_unit("week.quarter") == "yearquarter"
        assert resolver.resolve_time_unit("week.year") == "year"

    def test_temporal_time_unit_default_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        # week's defaultGrain is "week"
        assert resolver.resolve_time_unit("week") == "yearweek"

    def test_non_temporal_returns_none(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_time_unit("revenue") is None
        assert resolver.resolve_time_unit("country") is None


# ─── resolve_base_field ────────────────────────────────────────────────────────


class TestResolveBaseField:
    def test_strips_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_base_field("week.month") == "week"
        assert resolver.resolve_base_field("revenue") == "revenue"


# ─── resolve_default_sort / resolve_sort_order ────────────────────────────────


class TestResolveSortDefaults:
    def test_default_sort(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_default_sort("revenue") == "descending"
        assert resolver.resolve_default_sort("country") == "ascending"
        assert resolver.resolve_default_sort("region") is None

    def test_sort_order(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_sort_order("country") == ["US", "UK", "FR", "DE", "JP"]
        assert resolver.resolve_sort_order("revenue") is None
        assert resolver.resolve_sort_order("week") is None


# ─── resolve_grain ────────────────────────────────────────────────────────────


class TestResolveGrain:
    def test_temporal_explicit_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_grain("week.month") == "month"
        assert resolver.resolve_grain("week.day") == "day"
        assert resolver.resolve_grain("week.year") == "year"

    def test_temporal_default_grain(self, orders_model):
        resolver = ModelResolver(orders_model)
        # week's defaultGrain is "week"
        assert resolver.resolve_grain("week") == "week"

    def test_non_temporal_returns_none(self, orders_model):
        resolver = ModelResolver(orders_model)
        assert resolver.resolve_grain("revenue") is None
        assert resolver.resolve_grain("country") is None


# ─── is_measure / is_dimension ────────────────────────────────────────────────


class TestFieldClassification:
    def test_is_measure_and_dimension(self, orders_model):
        resolver = ModelResolver(orders_model, formulas={"calc": ""})
        assert resolver.is_measure("revenue") is True
        assert resolver.is_dimension("revenue") is False
        assert resolver.is_measure("country") is False
        assert resolver.is_dimension("country") is True
        assert resolver.is_measure("calc") is True
        assert resolver.is_dimension("calc") is False
        assert resolver.is_dimension("week") is True
