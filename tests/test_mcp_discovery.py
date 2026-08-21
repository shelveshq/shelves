"""
MCP discovery-tool tests (SHE-55).

The discovery tools are thin wrappers over the existing public API — the model
loader/resolver, the semantic-layer domain resolver
(`shelves.data.domains.resolve_field_domain`), and the parameters loader. These
tests drive the pure tool functions in `shelves.mcp.tools` directly, plus one
in-memory round trip through the assembled MCP server to prove registration and
JSON serialization.

Contract: `docs/foundational/MCP Specification.md` §3.1 (discovery) and §7
(non-goals: no file I/O, no raw SQL, stateless).
"""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
import respx

from shelves.data.domains import clear_domain_cache
from shelves.models.loader import clear_model_cache
from shelves.schema.chart_schema import DSL_VERSION
from tests.conftest import FIXTURES_DIR, MODELS_DIR


@pytest.fixture(autouse=True)
def _reset_caches():
    """Model and domain caches are process-global — reset around each test."""
    clear_model_cache()
    clear_domain_cache()
    yield
    clear_model_cache()
    clear_domain_cache()


def _ctx(models_dir=MODELS_DIR, project_dir=FIXTURES_DIR):
    from shelves.mcp.tools import MCPContext

    return MCPContext.create(project_dir=project_dir, models_dir=models_dir)


# ─── get_model ────────────────────────────────────────────────────


def test_get_model_menu():
    from shelves.mcp.tools import get_model

    out = get_model(_ctx(), "orders")

    assert out["model"] == "orders"
    assert out["label"] == "Orders"
    assert out["source_type"] == "inline"
    assert out["dsl_version"] == DSL_VERSION

    measures = {m["name"]: m for m in out["measures"]}
    assert measures["revenue"]["label"] == "Revenue"
    assert measures["revenue"]["format"] == "$,.0f"
    assert measures["revenue"]["aggregation"] == "sum"
    # No measure in orders.yaml is a calculation.
    assert all(m["calculated"] is False for m in out["measures"])

    dims = {d["name"]: d for d in out["dimensions"]}
    assert dims["country"]["type"] == "nominal"
    # Temporal dimension exposes grains + default_grain + a usage hint.
    assert dims["week"]["type"] == "temporal"
    assert dims["week"]["default_grain"] == "week"
    assert "week" in dims["week"]["grains"]
    assert "usage" in dims["week"]

    # The model schema has no `synonyms` field — the menu must not invent one.
    assert "synonyms" not in measures["revenue"]
    assert "synonyms" not in dims["country"]


def test_get_model_flags_calculated_measures():
    from shelves.mcp.tools import get_model

    out = get_model(_ctx(), "file_orders")
    measures = {m["name"]: m for m in out["measures"]}
    assert measures["revenue"]["calculated"] is False
    assert measures["profit"]["calculated"] is True  # calculation: {{revenue}}-{{cost}}
    assert measures["margin"]["calculated"] is True


def test_get_model_unknown():
    from shelves.mcp.tools import get_model

    out = get_model(_ctx(), "nope")
    assert "error" in out
    assert out["error"]["code"] == "unknown_model"
    assert "orders" in out["error"]["valid_options"]


# ─── list_models ──────────────────────────────────────────────────


def test_list_models_scans_dir():
    from shelves.mcp.tools import list_models

    entries = {e["model"]: e for e in list_models(_ctx())}

    # Valid models appear with their backend + label.
    assert entries["orders"]["source_type"] == "inline"
    assert entries["orders"]["label"] == "Orders"
    assert entries["file_orders"]["source_type"] == "file"

    # parameters.yaml is a parameters file, not a model — it must be excluded.
    assert "parameters" not in entries

    # A file that fails to parse as a DataModel is surfaced, not hidden.
    assert "error" in entries["invalid_yaml"]


def test_list_models_empty_dir(tmp_path):
    from shelves.mcp.tools import list_models

    assert list_models(_ctx(models_dir=tmp_path)) == []


# ─── sample_field_values ──────────────────────────────────────────


def test_sample_field_values_nominal():
    from shelves.mcp.tools import sample_field_values

    out = sample_field_values(_ctx(), "duckdb_orders", "region")
    assert out["field"] == "region"
    assert out["kind"] == "values"
    assert set(out["values"]) == {"APAC", "EU", "NA"}
    assert out["truncated"] is False
    assert out["dsl_version"] == DSL_VERSION


def test_sample_field_values_temporal_bounds():
    from shelves.mcp.tools import sample_field_values

    out = sample_field_values(_ctx(), "duckdb_orders", "order_date")
    assert out["field"] == "order_date"
    assert out["kind"] == "bounds"
    # order_date default grain is month → bounds truncate to month starts.
    assert out["min"] == "2024-01-01"
    assert out["max"] == "2024-02-01"
    assert "values" not in out


def test_sample_field_values_respects_limit():
    from shelves.mcp.tools import sample_field_values

    out = sample_field_values(_ctx(), "duckdb_orders", "region", limit=2)
    assert out["kind"] == "values"
    assert len(out["values"]) == 2
    assert out["truncated"] is True


def test_sample_field_values_on_measure():
    from shelves.mcp.tools import sample_field_values

    out = sample_field_values(_ctx(), "orders", "revenue")
    assert out["error"]["code"] == "not_a_dimension"
    assert "country" in out["error"]["valid_options"]


def test_sample_field_values_unknown_field():
    from shelves.mcp.tools import sample_field_values

    out = sample_field_values(_ctx(), "orders", "contry")
    assert out["error"]["code"] == "unknown_field"
    assert out["error"]["did_you_mean"] == "country"


def test_sample_field_values_invalid_model_returns_structured_error():
    """A model file that exists but is malformed is a structured error, not a
    raised exception across the protocol boundary (spec §1 principle 3)."""
    from shelves.mcp.tools import sample_field_values

    out = sample_field_values(_ctx(), "invalid_yaml", "anything")
    assert out["error"]["code"] == "invalid_model"


_CUBE_URL = "http://localhost:4000"
_CUBE_LOAD = f"{_CUBE_URL}/cubejs-api/v1/load"


@respx.mock
def test_sample_field_values_cube_backend(monkeypatch):
    """SHE-55 acceptance: distinct values for a Cube model, not just DuckDB —
    the shared domain resolver must give the same shape on the Cube backend."""
    from shelves.mcp.tools import sample_field_values

    monkeypatch.setenv("CUBE_API_URL", _CUBE_URL)
    monkeypatch.setenv("CUBE_API_TOKEN", "test-token")
    respx.post(_CUBE_LOAD).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"orders.category": "Furniture"},
                    {"orders.category": "Tech"},
                    {"orders.category": "Office"},
                ]
            },
        )
    )

    out = sample_field_values(_ctx(), "cube_orders", "category")
    assert out["kind"] == "values"
    assert set(out["values"]) == {"Furniture", "Tech", "Office"}
    assert out["dsl_version"] == DSL_VERSION


# ─── list_parameters ──────────────────────────────────────────────


def test_list_parameters():
    from shelves.mcp.tools import list_parameters

    out = list_parameters(_ctx())
    params = {p["name"]: p for p in out["parameters"]}
    assert out["dsl_version"] == DSL_VERSION

    assert params["region"]["type"] == "string"
    assert params["region"]["default"] == "EMEA"
    assert params["region"]["has_field_domain"] is True  # values: orders.region

    assert params["status"]["type"] == "string"
    assert params["status"]["has_field_domain"] is False  # literal list

    assert params["top_n"]["type"] == "number"
    assert params["top_n"]["default"] == 10
    assert params["top_n"]["has_field_domain"] is False  # range

    assert params["metric"]["type"] == "field"


def test_list_parameters_absent(tmp_path):
    from shelves.mcp.tools import list_parameters

    out = list_parameters(_ctx(models_dir=tmp_path))
    assert out["parameters"] == []


def test_list_parameters_malformed_returns_structured_error(tmp_path):
    """A broken parameters.yaml is an agent-correctable error, never a raise
    across the protocol boundary (spec §1 principle 3)."""
    from shelves.mcp.tools import list_parameters

    (tmp_path / "parameters.yaml").write_text("parameters:\n  region:\n    values: [a, b\n")
    out = list_parameters(_ctx(models_dir=tmp_path))
    assert out["error"]["code"] == "invalid_parameters"


# ─── list_specs ───────────────────────────────────────────────────


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_list_specs_inventory(tmp_path):
    from shelves.mcp.tools import list_specs

    _write(tmp_path / "charts" / "revenue.yaml", "sheet: Revenue by week\ndata: orders\n")
    _write(
        tmp_path / "dashboards" / "sales.yaml",
        "dashboard: Sales Overview\nroot:\n  type: sheet\n  link: revenue\n",
    )
    _write(
        tmp_path / "models" / "orders.yaml",
        "model: orders\nlabel: Orders\nmeasures:\n  revenue:\n    label: Revenue\n"
        "dimensions:\n  region:\n    label: Region\n",
    )

    out = list_specs(_ctx(project_dir=tmp_path))

    charts = {c["path"]: c for c in out["charts"]}
    dashboards = {d["path"]: d for d in out["dashboards"]}

    assert "charts/revenue.yaml" in charts
    assert charts["charts/revenue.yaml"]["sheet"] == "Revenue by week"
    assert "dashboards/sales.yaml" in dashboards
    assert dashboards["dashboards/sales.yaml"]["name"] == "Sales Overview"
    # The model YAML is neither a chart nor a dashboard.
    assert all("orders.yaml" not in p for p in charts)
    assert all("orders.yaml" not in p for p in dashboards)


def test_list_specs_kind_filter(tmp_path):
    from shelves.mcp.tools import list_specs

    _write(tmp_path / "a.yaml", "sheet: A\n")
    _write(tmp_path / "b.yaml", "dashboard: B\nroot:\n  type: sheet\n  link: a\n")

    out = list_specs(_ctx(project_dir=tmp_path), kind="chart")
    assert [c["sheet"] for c in out["charts"]] == ["A"]
    assert out["dashboards"] == []


def test_list_specs_skips_unreadable_yaml(tmp_path):
    """One non-UTF-8 / unreadable *.yaml must be skipped, not abort the whole
    inventory (spec §1 principle 3)."""
    from shelves.mcp.tools import list_specs

    (tmp_path / "good.yaml").write_text("sheet: Good\n")
    (tmp_path / "binary.yaml").write_bytes(b"\xff\xfe\x00bad")

    out = list_specs(_ctx(project_dir=tmp_path))
    assert [c["sheet"] for c in out["charts"]] == ["Good"]


# ─── server assembly (in-memory round trip) ───────────────────────


def test_server_registers_tools_and_roundtrips():
    import anyio
    from mcp.types import CallToolResult, TextContent

    from shelves.mcp.server import build_server

    server = build_server(_ctx())

    async def go():
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert {
            "list_models",
            "get_model",
            "sample_field_values",
            "list_parameters",
            "list_specs",
        } <= names

        result = await server.call_tool("get_model", {"model": "orders"})
        assert isinstance(result, CallToolResult)
        block = result.content[0]
        assert isinstance(block, TextContent)
        payload = json.loads(block.text)
        assert payload["model"] == "orders"
        assert payload["dsl_version"] == DSL_VERSION

    anyio.run(go)


# Sanity: the temporal-bounds normalization is dates, serialized ISO.
def test_iso_helper_roundtrips_dates():
    from shelves.mcp.tools import _iso

    assert _iso(dt.date(2024, 1, 1)) == "2024-01-01"
    assert _iso("EMEA") == "EMEA"
    assert _iso(42) == 42
