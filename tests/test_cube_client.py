"""
Tests for Cube.dev client — query building, filter translation, response parsing.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from src.schema.chart_schema import DataSource, ShelfFilter
from src.data.cube_client import (
    CubeConfig,
    CubeConfigError,
    CubeQueryError,
    build_cube_query,
    fetch_from_cube,
    _strip_prefix,
)


# ─── CubeConfig ──────────────────────────────────────────────────────


class TestCubeConfig:
    def test_from_env_success(self, monkeypatch):
        monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000")
        monkeypatch.setenv("CUBE_API_TOKEN", "secret-token")
        config = CubeConfig.from_env()
        assert config.api_url == "http://localhost:4000"
        assert config.api_token == "secret-token"

    def test_from_env_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000/")
        monkeypatch.setenv("CUBE_API_TOKEN", "tok")
        config = CubeConfig.from_env()
        assert config.api_url == "http://localhost:4000"

    def test_from_env_missing_url(self, monkeypatch):
        monkeypatch.delenv("CUBE_API_URL", raising=False)
        monkeypatch.setenv("CUBE_API_TOKEN", "tok")
        with pytest.raises(CubeConfigError, match="CUBE_API_URL"):
            CubeConfig.from_env()

    def test_from_env_missing_token(self, monkeypatch):
        monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000")
        monkeypatch.delenv("CUBE_API_TOKEN", raising=False)
        with pytest.raises(CubeConfigError, match="CUBE_API_TOKEN"):
            CubeConfig.from_env()


# ─── build_cube_query ────────────────────────────────────────────────


class TestBuildCubeQuery:
    def _make_data(self, **overrides) -> DataSource:
        defaults = {
            "model": "orders",
            "measures": ["net_sales"],
            "dimensions": ["category"],
        }
        defaults.update(overrides)
        return DataSource(**defaults)

    def test_basic_measures_and_dimensions(self):
        data = self._make_data()
        query = build_cube_query(data)
        assert query["measures"] == ["orders.net_sales"]
        assert query["dimensions"] == ["orders.category"]
        assert "timeDimensions" not in query
        assert "filters" not in query

    def test_multiple_measures(self):
        data = self._make_data(measures=["net_sales", "quantity"])
        query = build_cube_query(data)
        assert query["measures"] == ["orders.net_sales", "orders.quantity"]

    def test_time_grain_creates_time_dimensions(self):
        data = self._make_data(
            dimensions=["category", "order_date"],
            time_grain={"field": "order_date", "grain": "month"},
        )
        query = build_cube_query(data)
        # order_date should NOT be in dimensions (moved to timeDimensions)
        assert query["dimensions"] == ["orders.category"]
        assert query["timeDimensions"] == [
            {"dimension": "orders.order_date", "granularity": "month"}
        ]

    def test_filters_translate_eq(self):
        data = self._make_data()
        filters = [ShelfFilter(field="segment", operator="eq", value="Consumer")]
        query = build_cube_query(data, filters)
        assert query["filters"] == [
            {"member": "orders.segment", "operator": "equals", "values": ["Consumer"]}
        ]

    def test_filters_translate_in(self):
        data = self._make_data()
        filters = [ShelfFilter(field="region", operator="in", values=["East", "West"])]
        query = build_cube_query(data, filters)
        assert query["filters"] == [
            {"member": "orders.region", "operator": "equals", "values": ["East", "West"]}
        ]

    def test_filters_translate_not_in(self):
        data = self._make_data()
        filters = [ShelfFilter(field="region", operator="not_in", values=["South"])]
        query = build_cube_query(data, filters)
        assert query["filters"] == [
            {"member": "orders.region", "operator": "notEquals", "values": ["South"]}
        ]

    def test_filters_translate_comparison_ops(self):
        data = self._make_data()
        for dsl_op, cube_op in [("gt", "gt"), ("lt", "lt"), ("gte", "gte"), ("lte", "lte")]:
            filters = [ShelfFilter(field="quantity", operator=dsl_op, value=10)]
            query = build_cube_query(data, filters)
            assert query["filters"] == [
                {"member": "orders.quantity", "operator": cube_op, "values": ["10"]}
            ]

    def test_between_filter_splits_to_two(self):
        data = self._make_data()
        filters = [ShelfFilter(field="quantity", operator="between", range=[5, 20])]
        query = build_cube_query(data, filters)
        assert query["filters"] == [
            {"member": "orders.quantity", "operator": "gte", "values": ["5"]},
            {"member": "orders.quantity", "operator": "lte", "values": ["20"]},
        ]

    def test_filter_values_are_strings(self):
        data = self._make_data()
        filters = [ShelfFilter(field="quantity", operator="eq", value=42)]
        query = build_cube_query(data, filters)
        assert query["filters"][0]["values"] == ["42"]

    def test_no_filters_omits_key(self):
        data = self._make_data()
        query = build_cube_query(data, filters=None)
        assert "filters" not in query

    def test_empty_filters_omits_key(self):
        data = self._make_data()
        query = build_cube_query(data, filters=[])
        assert "filters" not in query


# ─── _strip_prefix ───────────────────────────────────────────────────


class TestStripPrefix:
    def test_strips_cube_prefix(self):
        row = {"orders.net_sales": 123.45, "orders.category": "Furniture"}
        assert _strip_prefix(row) == {"net_sales": 123.45, "category": "Furniture"}

    def test_handles_no_prefix(self):
        row = {"count": 5}
        assert _strip_prefix(row) == {"count": 5}

    def test_time_dimension_key(self):
        # Cube returns time dimensions as "orders.order_date.month"
        row = {"orders.order_date": "2024-01-01T00:00:00.000"}
        assert _strip_prefix(row) == {"order_date": "2024-01-01T00:00:00.000"}


# ─── fetch_from_cube (mocked HTTP) ──────────────────────────────────


class TestFetchFromCube:
    CUBE_URL = "http://localhost:4000"
    CUBE_TOKEN = "test-token"

    @pytest.fixture
    def config(self):
        return CubeConfig(api_url=self.CUBE_URL, api_token=self.CUBE_TOKEN)

    @pytest.fixture
    def data(self):
        return DataSource(model="orders", measures=["net_sales"], dimensions=["category"])

    @respx.mock
    def test_successful_fetch(self, config, data):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"orders.net_sales": 100, "orders.category": "Furniture"},
                        {"orders.net_sales": 200, "orders.category": "Technology"},
                    ]
                },
            )
        )
        rows = fetch_from_cube(data, config=config)
        assert rows == [
            {"net_sales": 100, "category": "Furniture"},
            {"net_sales": 200, "category": "Technology"},
        ]

    @respx.mock
    def test_sends_correct_headers(self, config, data):
        route = respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        fetch_from_cube(data, config=config)
        assert route.calls[0].request.headers["authorization"] == self.CUBE_TOKEN

    @respx.mock
    def test_sends_correct_query(self, config, data):
        route = respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        fetch_from_cube(data, config=config)
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["query"]["measures"] == ["orders.net_sales"]
        assert body["query"]["dimensions"] == ["orders.category"]

    @respx.mock
    def test_http_error_raises(self, config, data):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(400, text="Bad query")
        )
        with pytest.raises(CubeQueryError, match="400"):
            fetch_from_cube(data, config=config)

    @respx.mock
    def test_server_error_raises(self, config, data):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(500, text="Internal error")
        )
        with pytest.raises(CubeQueryError, match="500"):
            fetch_from_cube(data, config=config)

    @respx.mock
    def test_empty_data_response(self, config, data):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        rows = fetch_from_cube(data, config=config)
        assert rows == []

    @respx.mock
    def test_with_filters(self, config, data):
        route = respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        filters = [ShelfFilter(field="segment", operator="eq", value="Consumer")]
        fetch_from_cube(data, filters=filters, config=config)
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["query"]["filters"] == [
            {"member": "orders.segment", "operator": "equals", "values": ["Consumer"]}
        ]

    def test_uses_env_config_when_none(self, monkeypatch, data):
        monkeypatch.delenv("CUBE_API_URL", raising=False)
        monkeypatch.delenv("CUBE_API_TOKEN", raising=False)
        with pytest.raises(CubeConfigError):
            fetch_from_cube(data)
