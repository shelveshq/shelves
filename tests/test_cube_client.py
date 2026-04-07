"""
Tests for Cube.dev client — query building, filter translation, response parsing.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import httpx
import pytest
import respx

from shelves.schema.chart_schema import parse_chart
from shelves.models.loader import load_model, clear_model_cache
from shelves.models.resolver import ModelResolver
from shelves.data.cube_client import (
    CubeConfig,
    CubeConfigError,
    CubeQueryError,
    build_cube_query,
    fetch_from_cube_model,
    _strip_prefix,
    _collect_chart_fields,
)

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


# ─── _collect_chart_fields ──────────────────────────────────────────


class TestCollectChartFields:
    def test_simple_bar(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        fields = _collect_chart_fields(spec)
        assert fields == {"category", "net_sales"}

    def test_with_color_and_detail(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "color: segment\ndetail: segment\n"
        )
        fields = _collect_chart_fields(spec)
        assert fields == {"category", "net_sales", "segment"}

    def test_hex_color_excluded(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'color: "#ff0000"\n'
        )
        fields = _collect_chart_fields(spec)
        assert "#ff0000" not in fields

    def test_filter_fields_included(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'filters:\n  - field: segment\n    operator: eq\n    value: "Consumer"\n'
        )
        fields = _collect_chart_fields(spec)
        assert "segment" in fields

    def test_size_field_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: circle\n'
            "size: net_sales\n"
        )
        fields = _collect_chart_fields(spec)
        assert "net_sales" in fields
        assert "category" in fields

    def test_size_numeric_not_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: circle\n'
            "size: 100\n"
        )
        fields = _collect_chart_fields(spec)
        # 100 should not appear as a field name
        assert fields == {"category", "net_sales"}

    def test_tooltip_existing_fields_no_warning(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "tooltip: [category, net_sales]\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = _collect_chart_fields(spec)
        assert "category" in fields
        assert "net_sales" in fields
        assert len(w) == 0  # no warnings — both fields already on axes

    def test_tooltip_new_field_warns(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "tooltip: [category, segment]\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = _collect_chart_fields(spec)
        assert "segment" in fields  # still collected
        assert "category" in fields
        assert "net_sales" in fields
        # Only segment triggers a warning (category is already on cols)
        assert len(w) == 1
        assert "segment" in str(w[0].message)
        assert "detail" in str(w[0].message)

    def test_tooltip_object_new_field_warns(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "tooltip:\n  - field: segment\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = _collect_chart_fields(spec)
        assert "segment" in fields
        assert len(w) == 1
        assert "segment" in str(w[0].message)

    def test_tooltip_mixed_warns_only_new(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "color: segment\n"
            "tooltip: [category, net_sales, segment, order_date]\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fields = _collect_chart_fields(spec)
        assert fields == {"category", "net_sales", "segment", "order_date"}
        # Only order_date is new — category on cols, net_sales on rows, segment on color
        assert len(w) == 1
        assert "order_date" in str(w[0].message)

    def test_wrap_facet_field_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: order_date\nrows: net_sales\nmarks: line\n'
            "facet:\n  field: category\n  columns: 3\n"
        )
        fields = _collect_chart_fields(spec)
        assert "category" in fields
        assert "order_date" in fields
        assert "net_sales" in fields

    def test_row_column_facet_fields_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: order_date\nrows: net_sales\nmarks: line\n'
            "facet:\n  row: category\n  column: segment\n"
        )
        fields = _collect_chart_fields(spec)
        assert "category" in fields
        assert "segment" in fields

    def test_field_sort_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "sort:\n  field: net_sales\n  order: descending\n"
        )
        fields = _collect_chart_fields(spec)
        assert "net_sales" in fields

    def test_axis_sort_no_extra_fields(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            "sort:\n  axis: y\n  order: ascending\n"
        )
        fields = _collect_chart_fields(spec)
        # AxisSort references axes, not fields — no extra fields added
        assert fields == {"category", "net_sales"}

    def test_measure_entry_size_field_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\n'
            "rows:\n  - measure: net_sales\n    mark: circle\n    size: segment\n"
        )
        fields = _collect_chart_fields(spec)
        assert "segment" in fields
        assert "net_sales" in fields
        assert "category" in fields

    def test_entry_color_field_mapping_collected(self):
        spec = parse_chart(
            'sheet: "Test"\ndata: cube_orders\ncols: category\n'
            "rows:\n  - measure: net_sales\n    mark: bar\n    color:\n      field: segment\n"
        )
        fields = _collect_chart_fields(spec)
        assert "segment" in fields


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
            'sheet: "Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
            'filters:\n  - field: category\n    operator: in\n    values: ["Furniture", "Technology"]\n'
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
        with pytest.raises(CubeQueryError, match="500"):
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
