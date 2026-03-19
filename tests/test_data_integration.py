"""
Tests for the data resolution pipeline — inline and Cube modes.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from src.schema.chart_schema import parse_chart
from src.translator.translate import translate_chart
from src.theme.merge import merge_theme
from src.data.bind import resolve_data
from src.data.cube_client import CubeConfigError
from src.render.to_html import render_html
from tests.conftest import load_yaml


class TestResolveData:
    """Test resolve_data orchestration."""

    @pytest.fixture
    def simple_spec(self):
        yaml = load_yaml("simple_bar.yaml")
        return parse_chart(yaml)

    @pytest.fixture
    def simple_vl(self, simple_spec):
        return translate_chart(simple_spec)

    def test_inline_rows_bypass_cube(self, simple_vl, simple_spec):
        rows = [{"category": "A", "net_sales": 100}]
        result = resolve_data(simple_vl, simple_spec, rows=rows)
        assert result["data"]["values"] == rows

    def test_inline_empty_rows(self, simple_vl, simple_spec):
        result = resolve_data(simple_vl, simple_spec, rows=[])
        assert result["data"]["values"] == []

    def test_cube_config_error_when_no_rows_no_env(self, simple_vl, simple_spec, monkeypatch):
        monkeypatch.delenv("CUBE_API_URL", raising=False)
        monkeypatch.delenv("CUBE_API_TOKEN", raising=False)
        with pytest.raises(CubeConfigError):
            resolve_data(simple_vl, simple_spec)

    @respx.mock
    def test_cube_fetch_when_no_rows(self, monkeypatch):
        """Full pipeline: YAML → translate → resolve_data (Cube) → has data."""
        monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000")
        monkeypatch.setenv("CUBE_API_TOKEN", "tok")

        respx.post("http://localhost:4000/cubejs-api/v1/load").mock(
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

        yaml = load_yaml("cube_sales_by_category.yaml")
        spec = parse_chart(yaml)
        vl = translate_chart(spec)
        result = resolve_data(vl, spec)

        assert len(result["data"]["values"]) == 2
        assert result["data"]["values"][0] == {"net_sales": 100, "category": "Furniture"}


class TestEndToEndPipeline:
    """Full pipeline tests with mocked Cube responses."""

    @respx.mock
    def test_full_pipeline_with_cube(self, monkeypatch):
        """YAML → parse → translate → theme → Cube data → render HTML."""
        monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000")
        monkeypatch.setenv("CUBE_API_TOKEN", "tok")

        respx.post("http://localhost:4000/cubejs-api/v1/load").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"orders.net_sales": 150, "orders.category": "Furniture"},
                        {"orders.net_sales": 300, "orders.category": "Office Supplies"},
                        {"orders.net_sales": 450, "orders.category": "Technology"},
                    ]
                },
            )
        )

        yaml = load_yaml("cube_sales_by_category.yaml")
        spec = parse_chart(yaml)
        vl = translate_chart(spec)
        themed = merge_theme(vl)
        bound = resolve_data(themed, spec)
        html = render_html(bound, title=spec.sheet)

        # Verify we got a complete HTML page with data
        assert "<!DOCTYPE html>" in html
        assert "Net Sales by Category" in html
        assert "Furniture" in html
        assert "vegaEmbed" in html

    @respx.mock
    def test_time_grain_chart(self, monkeypatch):
        """YAML with time_grain → Cube timeDimensions → rendered chart."""
        monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000")
        monkeypatch.setenv("CUBE_API_TOKEN", "tok")

        route = respx.post("http://localhost:4000/cubejs-api/v1/load").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"orders.net_sales": 100, "orders.order_date": "2024-01-01T00:00:00.000"},
                        {"orders.net_sales": 120, "orders.order_date": "2024-02-01T00:00:00.000"},
                    ]
                },
            )
        )

        yaml = load_yaml("cube_sales_over_time.yaml")
        spec = parse_chart(yaml)
        vl = translate_chart(spec)
        bound = resolve_data(vl, spec)

        assert len(bound["data"]["values"]) == 2

        # Verify the Cube query used timeDimensions
        import json
        body = json.loads(route.calls[0].request.content)
        assert "timeDimensions" in body["query"]
        assert body["query"]["timeDimensions"][0]["granularity"] == "month"

    @respx.mock
    def test_filtered_chart(self, monkeypatch):
        """YAML with filters → pushed to Cube query."""
        monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000")
        monkeypatch.setenv("CUBE_API_TOKEN", "tok")

        route = respx.post("http://localhost:4000/cubejs-api/v1/load").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"orders.net_sales": 80, "orders.category": "Furniture"}]},
            )
        )

        yaml = load_yaml("cube_filtered.yaml")
        spec = parse_chart(yaml)
        vl = translate_chart(spec)
        bound = resolve_data(vl, spec)

        assert len(bound["data"]["values"]) == 1

        # Verify filters were sent to Cube
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["query"]["filters"] == [
            {"member": "orders.segment", "operator": "equals", "values": ["Consumer"]}
        ]
