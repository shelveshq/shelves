"""
Tests for Cube.dev client — query building, filter translation, response parsing.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from shelves.data.cube_client import (
    CubeAuthError,
    CubeConfig,
    CubeConfigError,
    CubeQueryError,
    CubeServerError,
    CubeTimeoutError,
    _strip_prefix,
    build_cube_query,
    fetch_from_cube_model,
)
from shelves.models.loader import clear_model_cache, load_model
from shelves.models.resolver import ModelResolver
from shelves.schema.chart_schema import parse_chart

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "models"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


@pytest.fixture
def cube_model():
    return load_model("cube_orders", models_dir=FIXTURES_DIR)


@pytest.fixture
def cube_resolver(cube_model):
    return ModelResolver(cube_model)


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
    def test_basic_measures_and_dimensions(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["measures"] == ["orders.net_sales"]
        assert query["dimensions"] == ["orders.category"]
        assert "timeDimensions" not in query
        assert "filters" not in query

    def test_time_dimension(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: order_date\nrows: net_sales\nmarks: line\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["measures"] == ["orders.net_sales"]
        assert query["dimensions"] == []
        assert query["timeDimensions"] == [
            {"dimension": "orders.order_date", "granularity": "month"}
        ]

    def test_filters_translate_eq(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'filters:\n  - field: segment\n    operator: eq\n    value: "Consumer"\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["filters"] == [
            {"member": "orders.segment", "operator": "equals", "values": ["Consumer"]}
        ]

    def test_filters_translate_in(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\n'
            "rows: net_sales\nmarks: bar\n"
            "filters:\n  - field: category\n    operator: in\n"
            '    values: ["Furniture", "Technology"]\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["filters"] == [
            {
                "member": "orders.category",
                "operator": "equals",
                "values": ["Furniture", "Technology"],
            }
        ]

    def test_filters_translate_not_in(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'filters:\n  - field: category\n    operator: not_in\n    values: ["Furniture"]\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["filters"] == [
            {"member": "orders.category", "operator": "notEquals", "values": ["Furniture"]}
        ]

    def test_between_filter_splits_to_two(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "filters:\n  - field: net_sales\n    operator: between\n    range: [5, 20]\n"
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["filters"] == [
            {"member": "orders.net_sales", "operator": "gte", "values": ["5"]},
            {"member": "orders.net_sales", "operator": "lte", "values": ["20"]},
        ]

    def test_explicit_grain_time_dimension(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: order_date.day\nrows: net_sales\nmarks: line\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["timeDimensions"] == [{"dimension": "orders.order_date", "granularity": "day"}]

    def test_filter_dot_notation_strips_grain(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: order_date\nrows: net_sales\nmarks: line\n'
            'filters:\n  - field: order_date.month\n    operator: eq\n    value: "2024-01"\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
        assert query["filters"] == [
            {"member": "orders.order_date", "operator": "equals", "values": ["2024-01"]}
        ]

    def test_no_filters_omits_key(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        query = build_cube_query("orders", spec, cube_resolver)
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
        row = {"orders.order_date": "2024-01-01T00:00:00.000"}
        assert _strip_prefix(row) == {"order_date": "2024-01-01T00:00:00.000"}


# ─── fetch_from_cube_model (mocked HTTP) ─────────────────────────────


class TestFetchFromCubeModel:
    CUBE_URL = "http://localhost:4000"
    CUBE_TOKEN = "test-token"

    @pytest.fixture
    def config(self):
        return CubeConfig(api_url=self.CUBE_URL, api_token=self.CUBE_TOKEN)

    @pytest.fixture
    def chart_spec(self):
        return parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )

    @respx.mock
    def test_successful_fetch(self, config, cube_model, cube_resolver, chart_spec):
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
        rows = fetch_from_cube_model(cube_model, chart_spec, cube_resolver, config=config)
        assert rows == [
            {"net_sales": 100, "category": "Furniture"},
            {"net_sales": 200, "category": "Technology"},
        ]

    @respx.mock
    def test_sends_correct_headers(self, config, cube_model, cube_resolver, chart_spec):
        route = respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        fetch_from_cube_model(cube_model, chart_spec, cube_resolver, config=config)
        assert route.calls[0].request.headers["authorization"] == self.CUBE_TOKEN

    @respx.mock
    def test_sends_correct_query(self, config, cube_model, cube_resolver, chart_spec):
        route = respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        fetch_from_cube_model(cube_model, chart_spec, cube_resolver, config=config)
        body = json.loads(route.calls[0].request.content)
        assert body["query"]["measures"] == ["orders.net_sales"]
        assert body["query"]["dimensions"] == ["orders.category"]

    @respx.mock
    def test_http_error_raises(self, config, cube_model, cube_resolver, chart_spec):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(400, text="Bad query")
        )
        with pytest.raises(CubeQueryError, match="400"):
            fetch_from_cube_model(cube_model, chart_spec, cube_resolver, config=config)

    @respx.mock
    def test_server_error_raises(self, config, cube_model, cube_resolver, chart_spec):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(500, text="Internal error")
        )
        with pytest.raises(CubeServerError, match="500"):
            fetch_from_cube_model(cube_model, chart_spec, cube_resolver, config=config)

    @respx.mock
    def test_empty_data_response(self, config, cube_model, cube_resolver, chart_spec):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        rows = fetch_from_cube_model(cube_model, chart_spec, cube_resolver, config=config)
        assert rows == []

    @respx.mock
    def test_with_filters(self, config, cube_model, cube_resolver):
        route = respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'filters:\n  - field: segment\n    operator: eq\n    value: "Consumer"\n'
        )
        fetch_from_cube_model(cube_model, spec, cube_resolver, config=config)
        body = json.loads(route.calls[0].request.content)
        assert body["query"]["filters"] == [
            {"member": "orders.segment", "operator": "equals", "values": ["Consumer"]}
        ]

    def test_uses_env_config_when_none(self, monkeypatch, cube_model, cube_resolver, chart_spec):
        monkeypatch.delenv("CUBE_API_URL", raising=False)
        monkeypatch.delenv("CUBE_API_TOKEN", raising=False)
        with pytest.raises(CubeConfigError):
            fetch_from_cube_model(cube_model, chart_spec, cube_resolver)


# ─── FakeTransport for injection tests ──────────────────────────────


class FakeTransport:
    def __init__(self, response_data: list[dict]):
        self.response_data = response_data
        self.last_request: dict | None = None

    def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        self.last_request = {"url": url, "json": json, "headers": headers}
        return httpx.Response(200, json={"data": self.response_data})


# ─── TestFetchWithTransport ─────────────────────────────────────────


class TestFetchWithTransport:
    CUBE_URL = "http://localhost:4000"

    @pytest.fixture
    def config(self):
        return CubeConfig(api_url=self.CUBE_URL, api_token=self.CUBE_TOKEN)

    CUBE_TOKEN = "test-token"

    def test_fake_transport_injection(self, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        transport = FakeTransport(
            [
                {"orders.net_sales": 100, "orders.category": "Furniture"},
            ]
        )
        config = CubeConfig(api_url="http://fake:4000", api_token="tok")
        rows = fetch_from_cube_model(
            cube_model,
            spec,
            cube_resolver,
            config=config,
            transport=transport,
        )
        assert rows == [{"net_sales": 100, "category": "Furniture"}]
        assert transport.last_request is not None
        assert transport.last_request["url"] == "http://fake:4000/cubejs-api/v1/load"
        assert transport.last_request["headers"]["Authorization"] == "tok"

    @respx.mock
    def test_default_transport_uses_httpx(self, cube_model, cube_resolver):
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        config = CubeConfig(api_url=self.CUBE_URL, api_token=self.CUBE_TOKEN)
        rows = fetch_from_cube_model(cube_model, spec, cube_resolver, config=config)
        assert rows == []


# ─── TestHTTPErrorClassification ────────────────────────────────────


class TestHTTPErrorClassification:
    CUBE_URL = "http://localhost:4000"

    @pytest.fixture
    def config(self):
        return CubeConfig(api_url=self.CUBE_URL, api_token="tok")

    @respx.mock
    def test_401_raises_auth_error(self, config, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        with pytest.raises(CubeAuthError, match="401"):
            fetch_from_cube_model(cube_model, spec, cube_resolver, config=config)

    @respx.mock
    def test_403_raises_auth_error(self, config, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        with pytest.raises(CubeAuthError, match="403"):
            fetch_from_cube_model(cube_model, spec, cube_resolver, config=config)

    @respx.mock
    def test_500_raises_server_error(self, config, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(CubeServerError, match="500"):
            fetch_from_cube_model(cube_model, spec, cube_resolver, config=config)

    @respx.mock
    def test_timeout_raises_cube_timeout(self, config, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            side_effect=httpx.TimeoutException("Connection timed out")
        )
        with pytest.raises(CubeTimeoutError, match="timed out"):
            fetch_from_cube_model(cube_model, spec, cube_resolver, config=config)

    @respx.mock
    def test_error_body_truncated(self, config, cube_model, cube_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        long_body = "x" * 1000
        respx.post(f"{self.CUBE_URL}/cubejs-api/v1/load").mock(
            return_value=httpx.Response(400, text=long_body)
        )
        with pytest.raises(CubeQueryError) as exc_info:
            fetch_from_cube_model(cube_model, spec, cube_resolver, config=config)
        assert len(str(exc_info.value)) <= 600
