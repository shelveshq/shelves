# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Charter is a declarative visual analytics platform that translates a Tableau-inspired YAML DSL into Vega-Lite JSON specifications. The pipeline: YAML → Pydantic validation → Vega-Lite translation → Theme merge → Data binding → HTML rendering.

## Environment

**Always use the project venv.** System Python will not work (wrong version, missing deps).

```bash
# First time setup
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# All commands use .venv/bin/ prefix
.venv/bin/pytest
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests
```

## Commands

```bash
# Run all tests
.venv/bin/pytest

# Run a single test
.venv/bin/pytest tests/test_translator.py::TestSingleMarkCharts::test_simple_bar

# Lint and format
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests

# Render a chart (inline data)
.venv/bin/python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json

# Render a chart (Cube data — requires CUBE_API_URL and CUBE_API_TOKEN env vars)
.venv/bin/python -m src.cli.render tests/fixtures/yaml/cube_sales_by_category.yaml

# Dev server with live reload (open http://localhost:8089)
.venv/bin/python -m src.cli.dev tests/fixtures/yaml/cube_sales_by_category.yaml
.venv/bin/python -m src.cli.dev tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json
```

## Architecture

### Pipeline (three-tier, each stage is pure/composable)

1. **Parse** (`src/schema/`) — YAML string → `ChartSpec` via Pydantic. `chart_schema.py` defines the full DSL grammar. `field_types.py` resolves field names to Vega-Lite types (quantitative/temporal/nominal) from the data block.

2. **Translate** (`src/translator/`) — `ChartSpec` → Vega-Lite dict. `translate.py` routes based on shelf shape:
   - String shelves → `patterns/single.py` (single-measure)
   - List shelves → `patterns/stacked.py` (multi-measure: same marks use `repeat`, different marks use `vconcat`/`hconcat`)
   - Layer entries → `patterns/layers.py` (Phase 1a — parsed but raises `NotImplementedError`)
   - Facet wrapping (`facet.py`) applies uniformly to any inner spec shape
   - Supporting modules: `encodings.py`, `filters.py`, `sort.py`, `marks.py`

3. **Compose** (`src/theme/`, `src/data/`, `src/render/`) — Merge theme → bind data → render standalone HTML with vegaEmbed CDN

4. **Data** (`src/data/`) — Two modes:
   - `bind_data(spec, rows)` — inline JSON rows (Phase 1, tests, offline)
   - `resolve_data(spec, chart_spec)` — fetches from Cube.dev when no rows provided (Phase 3)
   - `cube_client.py` — Cube REST API client: query builder, filter translation, response transformer

Public API is exported from `src/__init__.py`: `parse_chart`, `translate_chart`, `merge_theme`, `bind_data`, `resolve_data`, `render_html`.

### Key Design Decisions

- **Inheritance:** Top-level marks/color/detail cascade down to multi-measure entries → layer entries. More specific overrides less specific.
- **FieldTypeResolver protocol:** Abstraction allowing future semantic layer integration without changing translator code.
- **Single validation rule:** At most ONE of rows/cols can be a multi-measure list; single-measure charts require top-level marks.
- **Cube prefix stripping:** Cube returns `orders.field_name` keys — `cube_client.py` strips to just `field_name` to match DSL conventions.
- **Filter push-down:** DSL `ShelfFilter` operators are translated to Cube filter format and pushed to the API, not filtered client-side.

## Testing

Tests live in `tests/` with YAML fixtures in `tests/fixtures/yaml/` and JSON data in `tests/fixtures/data/`. `conftest.py` provides `load_yaml(name)` and `load_data(name)` helpers.

Test files map 1:1 to features: `test_schema.py`, `test_translator.py`, `test_stacked.py`, `test_facet.py`, `test_field_types.py`, `test_layers.py`, `test_render.py`, `test_cube_client.py`, `test_data_integration.py`.

Cube tests use `respx` to mock HTTP — no live Cube instance needed for CI.

## DSL Versioning

The DSL version is defined in `src/schema/chart_schema.py` as `DSL_VERSION` (currently `0.1.0`). `ChartSpec` accepts an optional `version` field. Bump `DSL_VERSION` when the grammar changes (semver: major = breaking, minor = additive, patch = fixes).

## Documentation Rules

**Any change to the DSL (`src/schema/chart_schema.py`) MUST be accompanied by updates to:**
- `docs/guide/dsl-reference.md` — update the relevant field/property docs, examples, and type tables
- `docs/guide/getting-started.md` — update if the change affects the introductory workflow or basic examples

This applies to: new fields, removed fields, changed types, new operators, new mark types, new filter operators, renamed properties, or any change to validation rules. Do not merge DSL changes without corresponding doc updates.

## Branching Convention

Branch names follow: `KAN-{ticket}/description-in-kebab-case` (e.g. `KAN-100/semantic-layer-integration`).

## Project Status

Phase 1 (single-measure + stacked multi-measure) is complete. Phase 1a (layers/dual-axis) is schema-parsed but compilation is deferred. Phase 3 (Cube.dev semantic layer integration) is implemented — `cube_client.py`, `resolve_data`, dev server, 33 tests. See `PLAN.md` for the full roadmap, `docs/foundational/` for architecture documents, and `docs/guide/` for user-facing documentation (getting started + DSL reference).
