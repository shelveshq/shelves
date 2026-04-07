"""
Data Model Schema and Loader Tests

Tests for src/models/schema.py (Pydantic model validation) and
src/models/loader.py (file loading, caching, error handling).

TestModelSchema — pure schema validation, constructs models from dicts/YAML.
TestLoader      — file I/O, caching, name validation, error cases.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from shelves.models.schema import (
    CubeSource,
    DataModel,
    InlineSource,
    MeasureDefinition,
    NominalDimensionDefinition,
    TemporalDimensionDefinition,
)
from shelves.models.loader import load_model, clear_model_cache

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "models"


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear model cache before and after every test to prevent cross-test pollution."""
    clear_model_cache()
    yield
    clear_model_cache()


# ─── Schema Tests ─────────────────────────────────────────────────────────────


class TestModelSchema:
    def test_full_model_parses(self):
        model = load_model("orders", models_dir=FIXTURES_DIR)

        assert model.model == "orders"
        assert model.label == "Orders"
        assert model.description == "Transactional order data"
        assert isinstance(model.source, InlineSource)
        assert model.source.path == "data/orders.json"

        # Measures
        assert len(model.measures) == 5
        rev = model.measures["revenue"]
        assert rev.label == "Revenue"
        assert rev.format == "$,.0f"
        assert rev.defaultSort == "descending"
        assert rev.aggregation == "sum"
        assert rev.description == "Total revenue in USD"

        oc = model.measures["order_count"]
        assert oc.format == ",.0f"

        arpu = model.measures["arpu"]
        assert arpu.aggregation == "avg"

        # Nominal dimensions
        country = model.dimensions["country"]
        assert isinstance(country, NominalDimensionDefinition)
        assert country.label == "Country"
        assert country.sortOrder == ["US", "UK", "FR", "DE", "JP"]
        assert country.type == "nominal"

        region = model.dimensions["region"]
        assert isinstance(region, NominalDimensionDefinition)
        assert region.type == "nominal"

        # Temporal dimensions
        week = model.dimensions["week"]
        assert isinstance(week, TemporalDimensionDefinition)
        assert week.type == "temporal"
        assert week.defaultGrain == "week"
        assert week.format == {
            "day": "%b %d, %Y",
            "week": "%b %d",
            "month": "%b %Y",
            "year": "%Y",
        }
        assert week.grains == ["day", "week", "month", "quarter", "year"]

        month = model.dimensions["month"]
        assert isinstance(month, TemporalDimensionDefinition)
        assert month.defaultGrain == "month"

    def test_measure_minimal(self):
        m = MeasureDefinition(label="Revenue")
        assert m.label == "Revenue"
        assert m.format is None
        assert m.description is None
        assert m.defaultSort is None
        assert m.aggregation is None

    def test_dimension_defaults_to_nominal(self):
        model = DataModel.model_validate(
            {
                "model": "test",
                "label": "Test",
                "measures": {"m1": {"label": "M1"}},
                "dimensions": {"country": {"label": "Country"}},
            }
        )
        dim = model.dimensions["country"]
        assert isinstance(dim, NominalDimensionDefinition)
        assert dim.type == "nominal"

    def test_temporal_default_grains(self):
        dim = TemporalDimensionDefinition(type="temporal", label="Order Date", defaultGrain="month")
        assert dim.grains == ["day", "week", "month", "quarter", "year"]

    def test_temporal_explicit_grains(self):
        model = load_model("temporal_explicit_grains", models_dir=FIXTURES_DIR)
        year_field = model.dimensions["year_field"]
        assert isinstance(year_field, TemporalDimensionDefinition)
        assert year_field.grains == ["year"]
        assert year_field.defaultGrain == "year"

    def test_temporal_requires_default_grain(self):
        with pytest.raises(ValidationError):
            TemporalDimensionDefinition(type="temporal", label="Date")

    def test_default_grain_must_be_in_grains(self):
        with pytest.raises(ValidationError, match="not in grains"):
            TemporalDimensionDefinition(
                type="temporal",
                label="Date",
                grains=["year"],
                defaultGrain="month",
            )

    def test_temporal_format_map(self):
        dim = TemporalDimensionDefinition(
            type="temporal",
            label="Week",
            defaultGrain="week",
            format={"day": "%b %d, %Y", "week": "%b %d", "month": "%b %Y"},
        )
        assert dim.format == {
            "day": "%b %d, %Y",
            "week": "%b %d",
            "month": "%b %Y",
        }

    def test_temporal_invalid_format_key(self):
        with pytest.raises(ValidationError, match="not valid grains"):
            TemporalDimensionDefinition(
                type="temporal",
                label="Date",
                defaultGrain="month",
                format={"weekly": "%b %d"},
            )

    def test_nominal_sort_order(self):
        dim = NominalDimensionDefinition(label="Country", sortOrder=["US", "UK", "FR"])
        assert dim.sortOrder == ["US", "UK", "FR"]
        assert dim.type == "nominal"

    def test_ordinal_dimension(self):
        dim = NominalDimensionDefinition(type="ordinal", label="T-Shirt Size")
        assert dim.type == "ordinal"
        assert isinstance(dim, NominalDimensionDefinition)

    def test_inline_source(self):
        source = InlineSource(type="inline", path="data/orders.json")
        assert isinstance(source, InlineSource)
        assert source.path == "data/orders.json"

    def test_cube_source(self):
        source = CubeSource(type="cube", cube="Orders")
        assert isinstance(source, CubeSource)
        assert source.cube == "Orders"

    def test_source_optional(self):
        model = DataModel.model_validate(
            {
                "model": "test",
                "label": "Test",
                "measures": {"m1": {"label": "M1"}},
                "dimensions": {"d1": {"label": "D1"}},
            }
        )
        assert model.source is None

    def test_empty_measures_rejected(self):
        with pytest.raises(ValidationError, match="at least one measure"):
            DataModel.model_validate(
                {
                    "model": "empty_measures",
                    "label": "Empty",
                    "measures": {},
                    "dimensions": {"d1": {"label": "D1"}},
                }
            )


# ─── Loader Tests ─────────────────────────────────────────────────────────────


class TestLoader:
    def test_load_model(self):
        model = load_model("orders", models_dir=FIXTURES_DIR)
        assert isinstance(model, DataModel)
        assert model.model == "orders"

    def test_cache_returns_same_instance(self):
        first = load_model("orders", models_dir=FIXTURES_DIR)
        second = load_model("orders", models_dir=FIXTURES_DIR)
        assert first is second

    def test_clear_cache(self):
        first = load_model("orders", models_dir=FIXTURES_DIR)
        clear_model_cache()
        second = load_model("orders", models_dir=FIXTURES_DIR)
        assert first is not second

    def test_nonexistent_model_raises(self):
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            load_model("nonexistent", models_dir=FIXTURES_DIR)

    def test_name_mismatch_raises(self):
        with pytest.raises(ValueError, match="Model name mismatch"):
            load_model("invalid_name_mismatch", models_dir=FIXTURES_DIR)

    def test_empty_measures_file_raises(self):
        with pytest.raises(ValidationError, match="at least one measure"):
            load_model("empty_measures", models_dir=FIXTURES_DIR)

    def test_custom_models_dir(self):
        model = load_model("orders", models_dir=FIXTURES_DIR)
        assert model.model == "orders"

    def test_different_dirs_cached_independently(self, tmp_path):
        """Two different models_dir values produce independent cache entries."""
        # Load from FIXTURES_DIR
        m1 = load_model("orders", models_dir=FIXTURES_DIR)
        # Copy the model to a temp dir so we have two distinct paths
        import shutil

        shutil.copy(FIXTURES_DIR / "orders.yaml", tmp_path / "orders.yaml")
        m2 = load_model("orders", models_dir=tmp_path)
        # Different cache keys → different instances
        assert m1 is not m2
        # But same logical content
        assert m1.model == m2.model == "orders"

    def test_load_minimal_model(self):
        model = load_model("minimal", models_dir=FIXTURES_DIR)
        assert model.model == "minimal"
        assert len(model.measures) == 1
        assert "m1" in model.measures
        assert model.source is None
