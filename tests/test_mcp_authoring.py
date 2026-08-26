"""
MCP authoring-tool tests (SHE-56).

The correction-loop tools — validate_spec, compile_chart, render_chart /
render_dashboard, query_model — are thin wrappers over the existing pipeline
and data layer. These tests drive the pure functions in `shelves.mcp.tools`
directly (dicts in, dicts out), plus one round trip through the assembled
server to prove the PNG image content reaches the protocol boundary.

Contract: `docs/foundational/MCP Specification.md` §3.2, §4.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest
import respx

from shelves.data.duckdb_adapter import DuckDBAdapter
from shelves.models.loader import clear_model_cache, load_model
from shelves.models.resolver import ModelResolver
from shelves.schema.chart_schema import parse_chart
from tests.conftest import FIXTURES_DIR, MODELS_DIR

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _reset_caches():
    clear_model_cache()
    yield
    clear_model_cache()


def _ctx(models_dir=MODELS_DIR, project_dir=FIXTURES_DIR):
    from shelves.mcp.tools import MCPContext

    return MCPContext.create(project_dir=project_dir, models_dir=models_dir)


# Charts + inline data + dashboard copied into a tmp project root so the render
# tools write their PNG/HTML under a throwaway `output/`, never the source tree.
_PROJECT_FILES = [
    "yaml/simple_bar.yaml",
    "yaml/label_bar_simple.yaml",
    "yaml/facet_wrap.yaml",
    "layout/mcp_mini_dashboard.yaml",
    "data/orders.json",
]


@pytest.fixture
def project(tmp_path):
    import shutil

    from shelves.mcp.tools import MCPContext

    for rel in _PROJECT_FILES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES_DIR / rel, dst)
    return MCPContext.create(project_dir=tmp_path, models_dir=MODELS_DIR)


def _text(name):
    return (FIXTURES_DIR / "yaml" / name).read_text()


# ─── validate_spec ────────────────────────────────────────────────


def test_validate_spec_passthrough_matches_library():
    from shelves.mcp.tools import validate_spec
    from shelves.validation import validate_chart_yaml

    text = _text("simple_bar.yaml")
    out = validate_spec(_ctx(), yaml_text=text)
    expected = validate_chart_yaml(text, models_dir=MODELS_DIR).model_dump()

    assert out == expected
    assert out["valid"] is True
    assert out["kind"] == "chart"
    assert out["model_checked"] is True
    assert out["errors"] == []


def test_validate_spec_broken_returns_structured_errors():
    from shelves.mcp.tools import validate_spec

    text = "sheet: X\ndata: orders\ncols: country\nrows: revnue\nmarks: bar\n"
    out = validate_spec(_ctx(), yaml_text=text)

    assert out["valid"] is False
    codes = {e["code"] for e in out["errors"]}
    assert "unknown_field" in codes
    revnue = next(e for e in out["errors"] if e["code"] == "unknown_field")
    assert revnue["did_you_mean"] == "revenue"


def test_validate_spec_detects_dashboard_kind():
    from shelves.mcp.tools import validate_spec

    text = (
        "dashboard: Sales\ncanvas: { width: 1440, height: 900 }\n"
        "root:\n  orientation: vertical\n  contains:\n"
        '    - sheet: yaml/simple_bar.yaml\n      name: c\n      width: "100%"\n'
    )
    out = validate_spec(_ctx(), yaml_text=text)
    assert out["kind"] == "dashboard"
    assert out["valid"] is True


def test_validate_spec_from_path():
    from shelves.mcp.tools import validate_spec

    out = validate_spec(_ctx(), path="yaml/simple_bar.yaml")
    assert out["valid"] is True
    assert out["kind"] == "chart"


# ─── input resolution edge cases ──────────────────────────────────


def test_ambiguous_input():
    from shelves.mcp.tools import validate_spec

    out = validate_spec(_ctx(), yaml_text="sheet: X\n", path="yaml/simple_bar.yaml")
    assert out["error"]["code"] == "ambiguous_input"


def test_missing_input():
    from shelves.mcp.tools import validate_spec

    out = validate_spec(_ctx())
    assert out["error"]["code"] == "missing_input"


def test_path_outside_project():
    from shelves.mcp.tools import validate_spec

    out = validate_spec(_ctx(), path="../../etc/passwd")
    assert out["error"]["code"] == "outside_project"


# ─── compile_chart ────────────────────────────────────────────────


def test_compile_chart_matches_pipeline():
    from shelves.mcp.tools import compile_chart
    from shelves.pipeline import compile_chart as pipeline_compile

    text = _text("simple_bar.yaml")
    out = compile_chart(_ctx(), yaml_text=text)
    expected_vl, expected_spec = pipeline_compile(text, models_dir=MODELS_DIR)

    assert out["vega_lite"] == expected_vl
    assert out["sheet"] == expected_spec.sheet


def test_compile_chart_invalid_returns_validation_payload():
    from shelves.mcp.tools import compile_chart

    text = "sheet: X\ndata: orders\ncols: country\nrows: revnue\nmarks: bar\n"
    out = compile_chart(_ctx(), yaml_text=text)
    assert out["valid"] is False
    assert any(e["code"] == "unknown_field" for e in out["errors"])


def test_compile_chart_theme_resolves_within_project():
    """A theme path resolves against project_dir (like `path`), so a relative
    value works and its config reaches the compiled spec."""
    from shelves.mcp.tools import compile_chart

    out = compile_chart(
        _ctx(), yaml_text=_text("simple_bar.yaml"), theme="themes/custom_brand.yaml"
    )
    assert "vega_lite" in out


def test_compile_chart_theme_outside_project_rejected():
    from shelves.mcp.tools import compile_chart

    out = compile_chart(_ctx(), yaml_text=_text("simple_bar.yaml"), theme="/etc/passwd")
    assert out["error"]["code"] == "outside_project"


def test_compile_chart_theme_missing_rejected():
    from shelves.mcp.tools import compile_chart

    out = compile_chart(
        _ctx(), yaml_text=_text("simple_bar.yaml"), theme="themes/no_such_theme.yaml"
    )
    assert out["error"]["code"] == "theme_not_found"


# ─── render_chart ─────────────────────────────────────────────────


def test_render_chart_png(project):
    from shelves.mcp.tools import render_chart

    out = render_chart(project, path="yaml/simple_bar.yaml", format="png")

    assert out["format"] == "png"
    assert out["path"].endswith(".png")
    raw = base64.b64decode(out["png_base64"])
    assert raw[:8] == _PNG_MAGIC
    assert out["width"] > 0 and out["height"] > 0
    # simple_bar has no data labels and is not a compound spec.
    assert out.get("limitations", []) == []


def test_render_chart_png_writes_file(project):
    from shelves.mcp.tools import render_chart

    out = render_chart(project, path="yaml/simple_bar.yaml", format="png")
    from pathlib import Path

    written = Path(out["path"])
    assert written.exists()
    assert written.read_bytes()[:8] == _PNG_MAGIC


def test_render_chart_png_label_limitation(project):
    from shelves.mcp.tools import render_chart

    out = render_chart(project, path="yaml/label_bar_simple.yaml", format="png")
    assert any("label" in line.lower() for line in out["limitations"])


def test_render_chart_png_compound_limitation(project):
    from shelves.mcp.tools import render_chart

    out = render_chart(project, path="yaml/facet_wrap.yaml", format="png")
    assert any("compound" in line.lower() for line in out["limitations"])


def test_render_chart_html(project):
    from shelves.mcp.tools import render_chart

    out = render_chart(project, path="yaml/simple_bar.yaml", format="html")
    assert out["format"] == "html"
    assert out["path"].endswith(".html")
    assert "png_base64" not in out
    from pathlib import Path

    assert "vegaEmbed" in Path(out["path"]).read_text()


def test_render_chart_invalid_returns_validation_payload():
    from shelves.mcp.tools import render_chart

    text = "sheet: X\ndata: orders\ncols: country\nrows: revnue\nmarks: bar\n"
    out = render_chart(_ctx(), yaml_text=text, format="png")
    assert out["valid"] is False
    assert any(e["code"] == "unknown_field" for e in out["errors"])


_PARAM_CHART = "sheet: Metric by Country\ndata: orders\ncols: country\nrows: $metric\nmarks: bar\n"


def test_render_chart_param_override_applied(project):
    from pathlib import Path

    from shelves.mcp.tools import render_chart

    # metric's declared default is `revenue`; override it with `cost`.
    out = render_chart(project, yaml_text=_PARAM_CHART, format="html", params={"metric": "cost"})
    assert "error" not in out, out
    html = Path(out["path"]).read_text()
    assert "cost" in html
    assert "$metric" not in html


def test_render_chart_undeclared_param_rejected(project):
    from shelves.mcp.tools import render_chart

    out = render_chart(project, yaml_text=_PARAM_CHART, format="html", params={"nonesuch": "x"})
    assert out["error"]["code"] == "invalid_parameters"


def test_render_chart_data_unavailable(monkeypatch):
    from shelves.mcp.tools import render_chart

    monkeypatch.delenv("CUBE_API_URL", raising=False)
    monkeypatch.delenv("CUBE_API_TOKEN", raising=False)
    text = "sheet: X\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n"
    out = render_chart(_ctx(), yaml_text=text, format="png")
    assert out["error"]["code"] == "data_unavailable"


def test_render_chart_vl_convert_missing(project, monkeypatch):
    from shelves.mcp import tools

    def _boom(*_a, **_k):
        raise ModuleNotFoundError("No module named 'vl_convert'", name="vl_convert")

    monkeypatch.setattr("shelves.render.to_png.render_png", _boom)
    out = tools.render_chart(project, path="yaml/simple_bar.yaml", format="png")
    assert out["error"]["code"] == "vl_convert_missing"


def test_render_chart_unknown_format_rejected(project):
    from shelves.mcp.tools import render_chart

    out = render_chart(project, path="yaml/simple_bar.yaml", format="HTML")
    assert out["error"]["code"] == "unsupported_format"
    assert "png" in out["error"]["valid_options"]


def test_render_chart_same_sheet_title_distinct_files(project):
    """Two different charts sharing a `sheet` title must not clobber each
    other's PNG (filename carries a content digest)."""
    from shelves.mcp.tools import render_chart

    base = "sheet: Same Title\ndata: orders\nrows: revenue\nmarks: bar\n"
    a = render_chart(project, yaml_text=base + "cols: region\n", format="png")
    b = render_chart(project, yaml_text=base + "cols: country\n", format="png")
    assert a["path"] != b["path"]


def test_render_chart_inline_missing_data_file(tmp_path):
    """An inline model whose data file is missing must return a structured
    error, not a successful, blank PNG."""
    from shelves.mcp.tools import MCPContext, render_chart

    # A project root with the model dir but no data/orders.json.
    ctx = MCPContext.create(project_dir=tmp_path, models_dir=MODELS_DIR)
    out = render_chart(ctx, yaml_text=_text("simple_bar.yaml"), format="png")
    assert out["error"]["code"] == "data_unavailable"


def test_render_chart_inline_malformed_json(project):
    """Malformed inline JSON is a structured error, not an uncaught crash."""
    from shelves.mcp.tools import render_chart

    (project.project_dir / "data" / "orders.json").write_text("{not valid json")
    out = render_chart(project, path="yaml/simple_bar.yaml", format="png")
    assert out["error"]["code"] == "invalid_data"


# ─── render_dashboard ─────────────────────────────────────────────


def test_render_dashboard_html(project):
    from shelves.mcp.tools import render_dashboard

    out = render_dashboard(project, path="layout/mcp_mini_dashboard.yaml")
    assert out["format"] == "html"
    assert out["path"].endswith(".html")
    from pathlib import Path

    assert "vegaEmbed" in Path(out["path"]).read_text()


def test_render_dashboard_png_unsupported(project):
    from shelves.mcp.tools import render_dashboard

    out = render_dashboard(project, path="layout/mcp_mini_dashboard.yaml", format="png")
    assert out["error"]["code"] == "unsupported_format"


def test_render_dashboard_returns_warnings_list(project):
    """compose_dashboard reports per-sheet problems via warnings.warn; the tool
    surfaces them rather than discarding them into a clean payload."""
    from shelves.mcp.tools import render_dashboard

    out = render_dashboard(project, path="layout/mcp_mini_dashboard.yaml")
    assert isinstance(out["warnings"], list)


def test_render_dashboard_missing_chart_link_is_structured(project):
    """A dashboard link to a missing chart returns a structured error instead
    of crashing across the protocol boundary (compose raises FileNotFoundError).
    """
    from shelves.mcp.tools import render_dashboard

    dash = project.project_dir / "layout" / "broken.yaml"
    dash.write_text(
        'dashboard: "Broken"\n'
        "canvas: { width: 800, height: 600 }\n"
        "root:\n"
        "  orientation: vertical\n"
        "  contains:\n"
        "    - sheet: yaml/does_not_exist.yaml\n"
        "      name: missing\n"
        '      width: "100%"\n'
    )
    out = render_dashboard(project, path="layout/broken.yaml")
    assert "error" in out
    assert out["error"]["code"] == "chart_not_found"


# ─── query_model ──────────────────────────────────────────────────


def _adapter_rows(model_name, chart_yaml):
    model = load_model(model_name, models_dir=MODELS_DIR)
    resolver = ModelResolver(model)
    spec = parse_chart(chart_yaml)
    return DuckDBAdapter(base_dir=FIXTURES_DIR).fetch(model, spec, resolver)


def _sorted_rows(rows):
    """Order-insensitive view of a row list. DuckDB does not guarantee row
    order without an ORDER BY, so two independent aggregations of the same data
    may come back permuted — compare their contents, not their sequence."""
    return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))


def test_query_model_aggregated_rows():
    from shelves.mcp.tools import query_model

    out = query_model(_ctx(), model="duckdb_orders", measures=["revenue"], dimensions=["region"])

    expected = _adapter_rows(
        "duckdb_orders",
        "sheet: q\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n",
    )
    assert _sorted_rows(out["rows"]) == _sorted_rows(expected)
    assert out["row_count"] == len(expected)
    assert out["truncated"] is False


def test_query_model_no_dimensions_grand_total():
    from shelves.mcp.tools import query_model

    out = query_model(_ctx(), model="duckdb_orders", measures=["revenue"])
    assert out["row_count"] == 1
    assert "revenue" in out["rows"][0]


def test_query_model_with_filter():
    from shelves.mcp.tools import query_model

    out = query_model(
        _ctx(),
        model="duckdb_orders",
        measures=["revenue"],
        dimensions=["region"],
        filters=[{"field": "region", "operator": "eq", "value": "NA"}],
    )
    expected = _adapter_rows(
        "duckdb_orders",
        "sheet: q\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n"
        "filters:\n  - field: region\n    operator: eq\n    value: NA\n",
    )
    assert _sorted_rows(out["rows"]) == _sorted_rows(expected)
    assert all(r["region"] == "NA" for r in out["rows"])


def test_query_model_unknown_measure():
    from shelves.mcp.tools import query_model

    out = query_model(_ctx(), model="duckdb_orders", measures=["revnue"], dimensions=["region"])
    assert out["error"]["code"] == "unknown_field"
    assert out["error"]["did_you_mean"] == "revenue"


def test_query_model_respects_limit():
    from shelves.mcp.tools import query_model

    out = query_model(
        _ctx(), model="duckdb_orders", measures=["revenue"], dimensions=["region"], limit=1
    )
    assert out["row_count"] == 1
    assert out["truncated"] is True


def test_query_model_inline_source_unavailable():
    from shelves.mcp.tools import query_model

    out = query_model(_ctx(), model="orders", measures=["revenue"], dimensions=["country"])
    assert out["error"]["code"] == "data_unavailable"


def test_query_model_unknown_filter_field():
    """A filter on a hallucinated field is an agent-correctable error, not the
    raw ValueError the resolver raises deep inside the adapter."""
    from shelves.mcp.tools import query_model

    out = query_model(
        _ctx(),
        model="duckdb_orders",
        measures=["revenue"],
        dimensions=["region"],
        filters=[{"field": "regoin", "operator": "eq", "value": "NA"}],
    )
    assert out["error"]["code"] == "unknown_field"
    assert out["error"]["did_you_mean"] == "region"


def test_query_model_negative_limit_rejected():
    """A negative limit must not silently drop rows off the end and report the
    truncated set as complete."""
    from shelves.mcp.tools import query_model

    out = query_model(
        _ctx(), model="duckdb_orders", measures=["revenue"], dimensions=["region"], limit=-1
    )
    assert out["error"]["code"] == "invalid_limit"


def test_query_model_zero_limit_rejected():
    from shelves.mcp.tools import query_model

    out = query_model(
        _ctx(), model="duckdb_orders", measures=["revenue"], dimensions=["region"], limit=0
    )
    assert out["error"]["code"] == "invalid_limit"


def test_query_model_malformed_filter_keeps_loc():
    """A structural filter error keeps its `loc` so the message is actionable."""
    from shelves.mcp.tools import query_model

    out = query_model(
        _ctx(),
        model="duckdb_orders",
        measures=["revenue"],
        dimensions=["region"],
        # `op` is not a ShelfFilter field (strict schema) — missing `operator`.
        filters=[{"field": "region", "op": "eq", "value": "NA"}],
    )
    assert out["error"]["code"] == "invalid_filter"
    # loc-bearing message, not a bare sentence.
    assert ":" in out["error"]["message"]


def test_run_model_query_suppresses_only_disaggregation_warning(monkeypatch):
    """query.py must silence ONLY the tooltip-disaggregation warning — any other
    warning the adapter raises has to still reach the caller."""
    import warnings as _w

    from shelves.data.query import run_model_query

    class _FakeAdapter:
        def __init__(self, base_dir=None):
            pass

        def fetch(self, model, spec, resolver, **_kw):
            _w.warn(
                "Tooltip field 'x' is not referenced ... Including it in the data "
                "query will disaggregate the data — ...",
                UserWarning,
                stacklevel=2,
            )
            _w.warn("a real adapter problem the caller must see", UserWarning, stacklevel=2)
            return [{"revenue": 1}]

    monkeypatch.setattr("shelves.data.duckdb_adapter.DuckDBAdapter", _FakeAdapter)

    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        rows = run_model_query(
            "duckdb_orders",
            ["revenue"],
            ["region"],
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )

    assert rows == [{"revenue": 1}]
    messages = [str(w.message) for w in caught]
    assert any("real adapter problem" in m for m in messages)
    assert not any("disaggregate the data" in m for m in messages)


_CUBE_URL = "http://localhost:4000"
_CUBE_LOAD = f"{_CUBE_URL}/cubejs-api/v1/load"


@respx.mock
def test_query_model_cube_backend(monkeypatch):
    """Adapter parity: a cube model routes through the same collect_chart_fields
    path — measure → measures, dimension → dimensions — and rows are unprefixed."""
    from shelves.mcp.tools import query_model

    monkeypatch.setenv("CUBE_API_URL", _CUBE_URL)
    monkeypatch.setenv("CUBE_API_TOKEN", "test-token")
    route = respx.post(_CUBE_LOAD).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"orders.category": "Tech", "orders.net_sales": 100},
                    {"orders.category": "Office", "orders.net_sales": 50},
                ]
            },
        )
    )

    out = query_model(_ctx(), model="cube_orders", measures=["net_sales"], dimensions=["category"])

    assert out["rows"] == [
        {"category": "Tech", "net_sales": 100},
        {"category": "Office", "net_sales": 50},
    ]
    sent = json.loads(route.calls.last.request.content)["query"]
    assert "orders.net_sales" in sent["measures"]
    assert "orders.category" in sent["dimensions"]


# ─── latency budgets (order-of-magnitude guard) ───────────────────


def test_latency_budgets(project):
    from shelves.mcp.tools import compile_chart, render_chart, validate_spec

    text = _text("simple_bar.yaml")

    t = time.perf_counter()
    validate_spec(_ctx(), yaml_text=text)
    assert time.perf_counter() - t < 1.0

    t = time.perf_counter()
    compile_chart(_ctx(), yaml_text=text)
    assert time.perf_counter() - t < 2.5

    t = time.perf_counter()
    render_chart(project, path="yaml/simple_bar.yaml", format="png")
    assert time.perf_counter() - t < 10.0


# ─── server round trip: PNG reaches the protocol boundary ─────────


def test_server_render_chart_returns_image_content(project):
    import anyio
    from mcp.types import CallToolResult, ImageContent

    from shelves.mcp.server import build_server

    server = build_server(project)

    async def go():
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert {
            "validate_spec",
            "compile_chart",
            "render_chart",
            "render_dashboard",
            "query_model",
        } <= names

        result = await server.call_tool("render_chart", {"path": "yaml/simple_bar.yaml"})
        assert isinstance(result, CallToolResult)
        assert any(isinstance(block, ImageContent) for block in result.content)

    anyio.run(go)
