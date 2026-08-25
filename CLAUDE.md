# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. Area-specific context lives in sub-directory `CLAUDE.md` files (`shelves/schema/`, `shelves/translator/`, `shelves/theme/`, `shelves/data/`, `shelves/models/`, `shelves/render/`, `shelves/compose/`, `docs/`, `tests/`).

## What This Project Is

Shelves is a declarative visual analytics platform that translates a Tableau-inspired YAML DSL into Vega-Lite JSON specifications and HTML dashboards. It produces two artifacts: a **chart** (one sheet) and a **dashboard** (a layout tree of sheets). Both read field types, formats, and sources from a shared **semantic model**, backed by either a flat file (DuckDB) or Cube.dev. Surfaces on top: a `render`/`dev` CLI, a `shelves-import` model generator, and Shelves Studio (a FastAPI editor with live reload).

## Git Workflow

- Always pull/rebase latest main before starting new work or making changes on existing branches
- Check for CHANGELOG.md or other merge-in-progress files before committing

## Private Companion Repo

Confidential material — foundational/strategy docs, the design-system mirror,
per-ticket plans, the design source bundle, and `PLAN.md` — lives in the private
repo **`shelveshq/shelves-internal`**, NOT in this public repo. It is cloned to
`./.private/` (gitignored) and symlinked back to its expected paths
(`docs/foundational`, `docs/design-system`, `docs/plans`, `PLAN.md`,
`assets/Shelves Design System.zip`).

After cloning this repo, run the bootstrap once (needs read access to the
private repo):

```bash
./scripts/bootstrap-private.sh   # clones/updates .private and (re)links symlinks
```

Edit those files as normal; commit and push them **in `.private/`** (its own git
repo). Never `git add -f` a symlinked path here — the paths are gitignored on
purpose so nothing confidential lands in the public repo.

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

# Render a dashboard (layout tree of sheets)
.venv/bin/python -m shelves.cli.render dashboards/<name>.yaml

# Generate a model from a flat file
.venv/bin/python -m shelves.cli.import_cmd data/sales.csv

# Launch Shelves Studio (FastAPI editor)
.venv/bin/python -m shelves.studio.cli
```

## Architecture Overview

The single chart pipeline lives in `shelves/pipeline.py` (`compile_chart`) and is shared by every surface (CLIs, studio, dashboard composer):

1. **Parse** (`shelves/schema/`) — YAML → `ChartSpec` / `DashboardSpec` via Pydantic
2. **Translate** (`shelves/translator/`) — `ChartSpec` → Vega-Lite dict; dashboards → HTML via the layout translator/solver
3. **Theme** (`shelves/theme/`) — merge theme config into the Vega-Lite spec
4. **Data** (`shelves/data/`) — resolve via the source registry (inline / file-DuckDB / Cube.dev) and bind
5. **Render** (`shelves/render/`) — standalone HTML with vegaEmbed CDN + browser-side label patch
6. **Compose** (`shelves/compose/`) — orchestrate a full dashboard from YAML

`shelves/models/` supplies reusable semantic models for field-type resolution.

Public API (`shelves/__init__.py`): `parse_chart`, `translate_chart`, `merge_theme`, `load_theme`, `bind_data`, `resolve_data`, `render_html`, `compile_chart`, `parse_dashboard`, `translate_dashboard`, `compose_dashboard`, `resolve_model_data`.

See each module's `CLAUDE.md` and `docs/architecture-diagram.md` for design decisions, file descriptions, and rules.

## Branching Convention

Branch names MUST NOT contain a personal identifier (no username, no email
local-part). Do **not** follow the Linear/Jira-suggested branch name — it embeds
the author's email. Use one of these instead:

- **Ticket-driven** (single ticket): `{ticket-id}/description-in-kebab-case`
  (e.g. `SHE-58/json-schema-export`, `KAN-100/semantic-layer-integration`).
- **Project-driven** (a branch that will carry several related tickets): a
  generic kebab-case name from the Linear project or theme, no ticket ID
  (e.g. `llm-writability-upgrades`).

## Planning Workflow

- When using shelves-planner, check for existing plan files FIRST and ask whether to update vs. recreate before reading context repeatedly
- Route by ticket-ID prefix: `SHE-` tickets live in Linear (use the Linear MCP), `KAN-` tickets live in Jira (use the Atlassian MCP with cloud ID already configured). Linear is the current project-management tool; older Jira/`KAN-` tickets remain valid. If the matched tracker's MCP is unavailable, ask the user to paste ticket details upfront

## Testing & Type Checking

- Run full test suite AND pyright after any multi-file refactor before declaring done
- When adding tests, verify assertions match actual output format (e.g., vegaEmbed, StyleProperties) before committing
- Prefer `isinstance` narrowing over `getattr` or `cast()`; prefer `Literal` annotations over `cast()`

## Layout/Styles Conventions

- Padding is defined via shared style rules, not directly on sheets
- When switching to solver-based fixed sizing, remove display:flex from containers (border-box model)
- fit modes must be applied to rendered sheets, not just schema

## Project Status

Charts (single-measure, stacked multi-measure, and layers/dual-axis) compile. The semantic-model layer is implemented for both backends — flat file via DuckDB and Cube.dev. The Layout DSL (dashboards → HTML) and Shelves Studio editor are in active development. See `PLAN.md` for the full roadmap, `docs/foundational/` for architecture documents, and `docs/guide/` for user-facing documentation.
