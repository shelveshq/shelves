"""
JSON Schema export tests (SHE-58).

The generator (`shelves.schema.json_schema`) turns the Pydantic models into
machine-readable JSON Schema, served as MCP resources and written to committed
build artifacts. The governing guard is one-directional parity: every fixture
Pydantic *accepts* must validate against the exported schema. JSON Schema cannot
express Pydantic's cross-key `model_validator` rules, so it is a superset
acceptor — we never assert the reverse direction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shelves.schema.chart_schema import DSL_VERSION, parse_chart
from shelves.schema.json_schema import (
    CHART_SCHEMA_PATH,
    DASHBOARD_SCHEMA_PATH,
    chart_json_schema,
    dashboard_json_schema,
    dumps,
)
from shelves.schema.layout_schema import parse_dashboard

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_DIR = REPO_ROOT / "tests" / "fixtures" / "yaml"
LAYOUT_DIR = REPO_ROOT / "tests" / "fixtures" / "layout"
DASHBOARDS_DIR = REPO_ROOT / "dashboards"


def _validator(schema: dict):
    from jsonschema import Draft202012Validator

    return Draft202012Validator(schema)


# ─── structure ────────────────────────────────────────────────────


def test_chart_schema_structure():
    schema = chart_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "ChartSpec"
    assert schema["description"]  # carried from the model docstring
    defs = schema["$defs"]
    for name in ("MeasureEntry", "LayerEntry", "ShelfFilter", "KPIBlock"):
        assert name in defs, f"{name} missing from $defs"


def test_dashboard_schema_structure():
    schema = dashboard_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "DashboardSpec"
    assert "properties" in schema


def test_both_schemas_version_stamped():
    for schema, kind in ((chart_json_schema(), "chart"), (dashboard_json_schema(), "dashboard")):
        assert schema["version"] == DSL_VERSION
        assert schema["$id"] == f"shelves://schema/{kind}"


def test_rows_cols_union_exports_usably():
    """The `rows: str | list[MeasureEntry]` shorthand must survive export as a
    readable anyOf (string branch + array branch), not a wall of noise."""
    schema = chart_json_schema()
    for shelf in ("rows", "cols"):
        branches = schema["properties"][shelf]["anyOf"]
        types = {b.get("type") for b in branches}
        assert "string" in types  # `rows: revenue`
        # the list-of-MeasureEntry branch
        array_branch = next(b for b in branches if b.get("type") == "array")
        assert array_branch["items"]["$ref"] == "#/$defs/MeasureEntry"


def test_strict_keys_survive_export():
    """extra='forbid' on the chart models maps to additionalProperties:false so a
    typo'd key (e.g. `colour:`) fails JSON Schema the same way Pydantic rejects it."""
    schema = chart_json_schema()
    assert schema["additionalProperties"] is False
    v = _validator(schema)
    assert list(v.iter_errors({"sheet": "S", "data": "orders", "colour": "country"}))


# ─── fixture parity (the acceptance test) ─────────────────────────


def _accepted_chart_fixtures() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(YAML_DIR.glob("*.yaml")):
        text = f.read_text()
        try:
            parse_chart(text)
        except Exception:
            continue  # Pydantic-rejected or needs params — outside parity scope
        out.append((f.name, yaml.safe_load(text)))
    return out


def _accepted_dashboard_fixtures() -> list[tuple[str, dict]]:
    out = []
    for d in (LAYOUT_DIR, DASHBOARDS_DIR):
        for f in sorted(d.glob("*.yaml")):
            text = f.read_text()
            try:
                parse_dashboard(text)
            except Exception:
                continue
            out.append((f.name, yaml.safe_load(text)))
    return out


def test_all_accepted_chart_fixtures_validate():
    fixtures = _accepted_chart_fixtures()
    assert fixtures, "no chart fixtures were accepted — parity test is vacuous"
    v = _validator(chart_json_schema())
    failures = {
        name: [e.message for e in v.iter_errors(raw)]
        for name, raw in fixtures
        if list(v.iter_errors(raw))
    }
    assert not failures, f"Pydantic-accepted fixtures rejected by JSON Schema: {failures}"


def test_all_accepted_dashboard_fixtures_validate():
    fixtures = _accepted_dashboard_fixtures()
    assert fixtures, "no dashboard fixtures were accepted — parity test is vacuous"
    v = _validator(dashboard_json_schema())
    failures = {
        name: [e.message for e in v.iter_errors(raw)]
        for name, raw in fixtures
        if list(v.iter_errors(raw))
    }
    assert not failures, f"Pydantic-accepted dashboards rejected by JSON Schema: {failures}"


# ─── determinism + committed artifacts ────────────────────────────


def test_generation_is_deterministic():
    assert dumps(chart_json_schema()) == dumps(chart_json_schema())
    assert dumps(dashboard_json_schema()) == dumps(dashboard_json_schema())
    # A trailing newline keeps the file POSIX-clean and diff-friendly.
    assert dumps(chart_json_schema()).endswith("}\n")


def test_committed_chart_schema_is_current():
    assert CHART_SCHEMA_PATH.exists(), "run `python -m shelves.schema` to generate schemas/"
    assert CHART_SCHEMA_PATH.read_text() == dumps(chart_json_schema())


def test_committed_dashboard_schema_is_current():
    assert DASHBOARD_SCHEMA_PATH.exists(), "run `python -m shelves.schema` to generate schemas/"
    assert DASHBOARD_SCHEMA_PATH.read_text() == dumps(dashboard_json_schema())


def test_committed_files_parse_as_json():
    for path in (CHART_SCHEMA_PATH, DASHBOARD_SCHEMA_PATH):
        json.loads(path.read_text())


# ─── MCP resources ────────────────────────────────────────────────


def test_server_serves_schema_resources():
    import anyio
    from mcp.server.lowlevel.helper_types import ReadResourceContents

    from shelves.mcp.server import build_server
    from shelves.mcp.tools import MCPContext

    server = build_server(MCPContext.create(project_dir=REPO_ROOT))

    async def go():
        resources = await server.list_resources()
        by_uri = {str(r.uri): r for r in resources}
        assert "shelves://schema/chart" in by_uri
        assert "shelves://schema/dashboard" in by_uri
        assert by_uri["shelves://schema/chart"].mime_type == "application/json"

        first = next(iter(await server.read_resource("shelves://schema/chart")))
        assert isinstance(first, ReadResourceContents)
        payload = json.loads(first.content)
        assert payload["title"] == "ChartSpec"
        assert payload["version"] == DSL_VERSION

    anyio.run(go)
