"""
Tests for DataSourceAdapter protocol and registry.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from shelves.data.bind import resolve_data
from shelves.models.loader import clear_model_cache
from tests.conftest import load_yaml

MODELS_DIR = Path(__file__).parent / "fixtures" / "models"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def test_cube_adapter_registered():
    from shelves.data.sources import get_adapter

    adapter = get_adapter("cube")
    assert adapter is not None


def test_unknown_source_raises():
    from shelves.data.sources import get_adapter

    with pytest.raises(KeyError, match="duckdb"):
        get_adapter("duckdb")


@respx.mock
def test_resolve_data_uses_registry(monkeypatch):
    """resolve_data with a cube-sourced model goes through the adapter registry."""
    monkeypatch.setenv("CUBE_API_URL", "http://localhost:4000")
    monkeypatch.setenv("CUBE_API_TOKEN", "tok")
    respx.post("http://localhost:4000/cubejs-api/v1/load").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"orders.net_sales": 42, "orders.category": "Tech"},
                ]
            },
        )
    )
    yaml = load_yaml("cube_sales_by_category.yaml")
    spec = parse_chart(yaml)
    vl = translate_chart(spec, models_dir=MODELS_DIR)
    result = resolve_data(vl, spec, models_dir=MODELS_DIR)
    assert result["data"]["values"] == [{"net_sales": 42, "category": "Tech"}]
