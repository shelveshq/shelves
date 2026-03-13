"""
Field Type Resolver Tests

Validates DataBlockResolver resolves field names to the correct
Vega-Lite types based on the DataSource block.
"""

import pytest

from src.schema.chart_schema import DataSource, TimeGrainConfig
from src.schema.field_types import DataBlockResolver, FieldTypeResolver


class TestDataBlockResolver:
    def test_measure_resolves_to_quantitative(self):
        data = DataSource(
            model="orders",
            measures=["revenue", "orders", "arpu"],
            dimensions=["country", "week"],
        )
        resolver = DataBlockResolver(data)

        assert resolver.resolve("revenue") == "quantitative"
        assert resolver.resolve("orders") == "quantitative"
        assert resolver.resolve("arpu") == "quantitative"

    def test_dimension_resolves_to_nominal(self):
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=["country", "region"],
        )
        resolver = DataBlockResolver(data)

        assert resolver.resolve("country") == "nominal"
        assert resolver.resolve("region") == "nominal"

    def test_temporal_dimension_resolves_to_temporal(self):
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=["country", "week"],
            time_grain=TimeGrainConfig(field="week", grain="week"),
        )
        resolver = DataBlockResolver(data)

        assert resolver.resolve("week") == "temporal"
        assert resolver.resolve("country") == "nominal"

    def test_unknown_field_raises_value_error(self):
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=["country"],
        )
        resolver = DataBlockResolver(data)

        with pytest.raises(ValueError, match="nonexistent"):
            resolver.resolve("nonexistent")

    def test_error_message_includes_available_fields(self):
        data = DataSource(
            model="orders",
            measures=["revenue", "arpu"],
            dimensions=["country", "week"],
        )
        resolver = DataBlockResolver(data)

        with pytest.raises(ValueError, match="measures=") as exc_info:
            resolver.resolve("nonexistent")

        error_msg = str(exc_info.value)
        assert "revenue" in error_msg or "arpu" in error_msg
        assert "country" in error_msg or "week" in error_msg

    def test_no_time_grain_all_dimensions_nominal(self):
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=["country", "week"],
        )
        resolver = DataBlockResolver(data)

        assert resolver.resolve("week") == "nominal"
        assert resolver.resolve("country") == "nominal"

    def test_satisfies_protocol(self):
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=["country"],
        )
        resolver = DataBlockResolver(data)

        assert isinstance(resolver, FieldTypeResolver)

    def test_empty_dimensions(self):
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=[],
        )
        resolver = DataBlockResolver(data)

        assert resolver.resolve("revenue") == "quantitative"
        with pytest.raises(ValueError):
            resolver.resolve("country")

    def test_only_temporal_field_is_temporal_not_all_dimensions(self):
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=["country", "week", "region"],
            time_grain=TimeGrainConfig(field="week", grain="week"),
        )
        resolver = DataBlockResolver(data)

        assert resolver.resolve("week") == "temporal"
        assert resolver.resolve("country") == "nominal"
        assert resolver.resolve("region") == "nominal"

    def test_measures_checked_before_dimensions(self):
        # Field in both lists — measures win
        data = DataSource(
            model="orders",
            measures=["revenue"],
            dimensions=["revenue"],
        )
        resolver = DataBlockResolver(data)

        assert resolver.resolve("revenue") == "quantitative"
