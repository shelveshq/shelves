# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Charter is a declarative visual analytics platform that translates a Tableau-inspired YAML DSL into Vega-Lite JSON specifications. The pipeline: YAML → Pydantic validation → Vega-Lite translation → Theme merge → Data binding → HTML rendering.

## Commands

```bash
# Install (editable + dev deps)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test
pytest tests/test_translator.py::TestSingleMarkCharts::test_simple_bar

# Lint and format
ruff check src tests
ruff format src tests

# Render a chart
charter-render tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json
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

3. **Compose** (`src/theme/`, `src/data/`, `src/render/`) — Merge theme → bind data rows → render standalone HTML with vegaEmbed CDN

Public API is exported from `src/__init__.py`: `parse_chart`, `translate_chart`, `merge_theme`, `bind_data`, `render_html`.

### Key Design Decisions

- **Inheritance:** Top-level marks/color/detail cascade down to multi-measure entries → layer entries. More specific overrides less specific.
- **FieldTypeResolver protocol:** Abstraction allowing future semantic layer integration without changing translator code.
- **Single validation rule:** At most ONE of rows/cols can be a multi-measure list; single-measure charts require top-level marks.

## Testing

Tests live in `tests/` with YAML fixtures in `tests/fixtures/yaml/` and JSON data in `tests/fixtures/data/`. `conftest.py` provides `load_yaml(name)` and `load_data(name)` helpers. Test files map 1:1 to features: `test_schema.py`, `test_translator.py`, `test_stacked.py`, `test_facet.py`, `test_field_types.py`, `test_layers.py`, `test_render.py`.

## DSL Versioning

The DSL version is defined in `src/schema/chart_schema.py` as `DSL_VERSION` (currently `0.1.0`). `ChartSpec` accepts an optional `version` field. Bump `DSL_VERSION` when the grammar changes (semver: major = breaking, minor = additive, patch = fixes). Keep `docs/guide/dsl-reference.md` in sync when the DSL changes.

## Project Status

Phase 1 (single-measure + stacked multi-measure) is complete. Phase 1a (layers/dual-axis) is schema-parsed but compilation is deferred. See `PLAN.md` for the full roadmap, `docs/foundational/` for architecture documents, and `docs/guide/` for user-facing documentation (getting started + DSL reference).