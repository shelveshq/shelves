"""
JSON Schema export from the Pydantic DSL models (SHE-58).

Turns `ChartSpec` / `DashboardSpec` into machine-readable JSON Schema for
constrained/structured decoding and editor validation (YAML language server).
Published two ways: as the MCP resources `shelves://schema/{chart,dashboard}`
(see `shelves/mcp/server.py`) and as committed build artifacts under `schemas/`,
regenerated with `python -m shelves.schema` and diff-checked by the test suite.

Pure module — imports only Pydantic. `mcp` and `jsonschema` are NOT imported
here so generation runs on a core install and in CI without the `mcp` extra.

Parity is one-directional by design: JSON Schema captures structure, types,
enums, and unions, but NOT Pydantic's cross-key `model_validator` rules
("at most one multi-measure shelf", KPI exclusions, facet at-least-one-channel).
The exported schema is therefore a *superset acceptor* — a spec Pydantic accepts
always validates here, but the reverse does not hold. Do not try to encode those
validators into JSON Schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from shelves.schema.chart_schema import DSL_VERSION, ChartSpec
from shelves.schema.layout_schema import DashboardSpec

_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Committed build artifacts live INSIDE the package so they ship in the wheel
# (package-data) and resolve the same in a source checkout or an installed
# environment — never `parents[..]/schemas`, which would point outside the
# package once installed. The version stamp on each file makes them
# pydantic-version-sensitive: regenerate with `python -m shelves.schema` after a
# pydantic bump (the diff-check test enforces it).
SCHEMAS_DIR = Path(__file__).resolve().parent / "generated"
CHART_SCHEMA_PATH = SCHEMAS_DIR / "chart.schema.json"
DASHBOARD_SCHEMA_PATH = SCHEMAS_DIR / "dashboard.schema.json"


def _export(model: type, kind: str) -> dict:
    """Pydantic JSON Schema + mechanical, model-agnostic normalization: the
    dialect declaration, a stable `$id` matching the MCP resource URI, and the
    grammar version stamp (LLM Writability Spec §3.4 — public specs are tagged
    with the schema version)."""
    schema = model.model_json_schema()
    return {
        "$schema": _DIALECT,
        "$id": f"shelves://schema/{kind}",
        "version": DSL_VERSION,
        **schema,
    }


def chart_json_schema() -> dict:
    """JSON Schema for a chart spec (`ChartSpec`)."""
    return _export(ChartSpec, "chart")


def dashboard_json_schema() -> dict:
    """JSON Schema for a dashboard spec (`DashboardSpec`)."""
    return _export(DashboardSpec, "dashboard")


def dumps(schema: dict) -> str:
    """Serialize deterministically: sorted keys + trailing newline, so the
    committed artifacts are byte-stable and the diff check is meaningful."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_schemas(out_dir: Path | None = None) -> list[Path]:
    """Write both schema artifacts to `out_dir` (default: repo `schemas/`)."""
    base = out_dir or SCHEMAS_DIR
    base.mkdir(parents=True, exist_ok=True)
    written = []
    for path, schema in (
        (base / "chart.schema.json", chart_json_schema()),
        (base / "dashboard.schema.json", dashboard_json_schema()),
    ):
        path.write_text(dumps(schema))
        written.append(path)
    return written
