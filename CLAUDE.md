# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Area-specific context lives in sub-directory `CLAUDE.md` files (`shelves/schema/`, `shelves/translator/`, `shelves/data/`, `shelves/models/`, `docs/`, `tests/`).

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
.venv/bin/ruff check shelves tests
.venv/bin/ruff format shelves tests
```

## Commands

```bash
# Run all tests
.venv/bin/pytest

# Lint and format
.venv/bin/ruff check shelves tests
.venv/bin/ruff format shelves tests

# Render a chart (inline data)
.venv/bin/python -m shelves.cli.render tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json

# Render a chart (Cube data — requires CUBE_API_URL and CUBE_API_TOKEN env vars)
.venv/bin/python -m shelves.cli.render tests/fixtures/yaml/cube_sales_by_category.yaml

# Dev server with live reload (open http://localhost:8089)
.venv/bin/python -m shelves.cli.dev tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json
```

## Architecture Overview

The pipeline has four stages (each is pure/composable):

1. **Parse** (`shelves/schema/`) — YAML → `ChartSpec` via Pydantic
2. **Translate** (`shelves/translator/`) — `ChartSpec` → Vega-Lite dict
3. **Compose** (`shelves/theme/`, `shelves/render/`) — Theme merge → HTML rendering with vegaEmbed CDN
4. **Data** (`shelves/data/`) — Inline binding or Cube.dev fetching
5. **Models** (`shelves/models/`) — Reusable semantic model definitions for field type resolution

Public API: `parse_chart`, `translate_chart`, `merge_theme`, `bind_data`, `resolve_data`, `render_html` (exported from `shelves/__init__.py`).

See each module's `CLAUDE.md` for detailed design decisions, file descriptions, and rules.

## Branching Convention

Branch names follow: `KAN-{ticket}/description-in-kebab-case` (e.g. `KAN-100/semantic-layer-integration`).

## Project Status

Phase 1 (single-measure + stacked multi-measure) is complete. Phase 1a (layers/dual-axis) is schema-parsed but compilation is deferred. Phase 3 (Cube.dev semantic layer integration) is implemented. See `PLAN.md` for the full roadmap, `docs/foundational/` for architecture documents, and `docs/guide/` for user-facing documentation.
